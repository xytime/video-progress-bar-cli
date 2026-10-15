"""维护运行归属与本机操作检查；不把局部接纳为空当作整机已排空。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| keyword-stage-v1 | 2026-10-14 | Codex | 非秘密阶段配置绑定原生部署日志，维护、漂移及完成回读闭锁 |
| 1.0.0 | 2026-10-12 | Codex | 真实角色锁、未接入来源阻断及正常 SIGTERM 生命周期 |
| 1.0.1 | 2026-10-13 | Codex | macOS 使用系统 lsof 路径，兼容 launchd 精简 PATH |
| 1.0.2 | 2026-10-13 | Codex | 独立测试入口与真实 cwd 双重核实，排除仅借用生产解释器的测试 |
| 1.0.3 | 2026-10-13 | Codex | 相对测试入口仅按已核实的进程 cwd 解析 |
| 1.0.4 | 2026-10-13 | Codex | 核实 cron shell 与唯一已登记子进程归属，保留未知阻断 |
| 1.0.5 | 2026-10-15 | Codex | 维护中只允许已完成部署证明的精确旧进程退役，仍核对真实 cwd 与 birth |
"""
from __future__ import annotations
from functools import wraps
from pathlib import Path
import hashlib
import json
import os
import signal
import shlex
import subprocess
import time
from .maintenance import gate, MaintenanceDenied
from .task_lease import TaskLease, TaskLeaseBusy, read_lease_owner
from .topic_candidates import TopicError
import sqlite3
import ctypes
import sys

PROTOCOL = 1
ROLES = ("ui", "auto-pipeline", "queue-runner", "ready-supervisor", "keepalive-watchdog", "ready-worker", "wallstreet-worker")
SOURCE_GROUPS = {"cron", "launchd", "manual", "bot", "independent-workers"}


def code_hash():
    root = Path(__file__).resolve().parents[3]
    paths = [*sorted((root / "src").rglob("*.py")), *sorted((root / "scripts").glob("*.py")), root / "vpanel"]
    value = hashlib.sha256()
    for path in paths:
        value.update(str(path.relative_to(root)).encode())
        value.update(path.read_bytes())
    return value.hexdigest()


def process_birth(pid):
    if sys.platform == "darwin":
        # Apple SDK sys/proc_info.h: PROC_PIDTBSDINFO=3，proc_bsdinfo。
        # 按 PID 查询，不用 ps 的全局 sysctl，保留测试同沙盒进程边界。
        class BSDInfo(ctypes.Structure):
            _fields_ = [("prefix", ctypes.c_uint32 * 12), ("comm", ctypes.c_char * 16),
                        ("name", ctypes.c_char * 32), ("tail", ctypes.c_uint32 * 6),
                        ("seconds", ctypes.c_uint64), ("micros", ctypes.c_uint64)]
        library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        library.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
        library.proc_pidinfo.restype = ctypes.c_int
        row = BSDInfo()
        if library.proc_pidinfo(pid, 3, 0, ctypes.byref(row), ctypes.sizeof(row)) != ctypes.sizeof(row):
            raise OSError(ctypes.get_errno(), "进程归属无法读取")
        if row.prefix[3] != pid or row.prefix[1] == 5:
            raise ProcessLookupError("进程已退出")
        return f"{row.seconds}.{row.micros:06d}"
    value = subprocess.run(["ps", "-p", str(pid), "-o", "lstart="], text=True,
                           capture_output=True, timeout=2, check=True).stdout.strip()
    if not value:
        raise ValueError("进程归属未知")
    return value


def protection_snapshot(config=None):
    from config.settings import settings
    from config.keyword_rollout import protection_values
    config = settings if config is None else config
    return protection_values(config)


def role_lease(role):
    from config.settings import settings
    if role not in ROLES:
        raise ValueError("未知执行角色")
    return TaskLease(settings.maintenance_state_path.with_suffix(".workers") / (role + ".lock"),
                     role=role, protocol=PROTOCOL, source_hash=code_hash(), cwd=str(settings.project_root),
                     birth=process_birth(os.getpid()))


def registered(role):
    def decorate(method):
        @wraps(method)
        def run(*args, **kwargs):
            try:
                with role_lease(role):
                    return method(*args, **kwargs)
            except TaskLeaseBusy:
                return None
        return run
    return decorate


def _test_runner_entry(command, root):
    """提取待核实入口；不凭命令行直接排除进程。"""
    try:
        args = shlex.split(command)
        if len(args) < 2 or args[0] != str(root / '.venv/bin/python'):
            return None
        if any(str(root) in value for value in args[1:]):
            return None
        entry = Path(args[1])
        if entry.name != 'run_isolated_tests.py' or entry.parent.name != 'scripts':
            return None
        return entry
    except ValueError:
        return None


def _independent_test_root(entry, root, cwd):
    """用真实 cwd 解析入口，再核实源码；任何歧义继续阻断。"""
    try:
        entry = entry if entry.is_absolute() else cwd / entry
        if not entry.is_file():
            return None
        entry = entry.resolve()
        if entry.name != 'run_isolated_tests.py' or entry.parent.name != 'scripts':
            return None
        if entry.read_bytes() != (root / 'scripts/run_isolated_tests.py').read_bytes():
            return None
        candidate = entry.parent.parent
        if candidate.is_relative_to(root.resolve()):
            return None
        return candidate
    except (ValueError, OSError, RuntimeError):
        return None


def inspection(control, *, evidence=None, process_pids=None, retiring_workers=None):
    """证据由另行批准的采用流程生成；哈希绑定被冻结的非秘密来源清单。

    每次操作重新检查真实角色锁/业务锁/PID。文件回执缺失不推断来源受控。
    """
    from config.settings import settings
    state = control.status()
    unknown = list(state["unknown"])
    owners = {}
    commands = {}
    try:
        expected_hash = code_hash()
        for role in ROLES:
            row = read_lease_owner(control.path.with_suffix(".workers") / (role + ".lock"))
            if row:
                retiring = (state["state"] == "MAINTENANCE" and row == (retiring_workers or {}).get(role))
                if retiring:
                    lsof = "/usr/sbin/lsof" if sys.platform == "darwin" else "lsof"
                    cwd = subprocess.run([lsof, "-a", "-p", str(row["pid"]), "-d", "cwd", "-Fn"],
                                         text=True, capture_output=True, timeout=2, check=True)
                    retiring = [line[1:] for line in cwd.stdout.splitlines() if line.startswith("n")] == [str(settings.project_root)]
                if (row.get("protocol") != PROTOCOL or (row.get("source_hash") != expected_hash and not retiring)
                        or row.get("cwd") != str(settings.project_root)
                        or row.get("birth") != process_birth(row["pid"])):
                    unknown.append({"code": "LEGACY_WORKER", "role": role})
                else:
                    owners[role] = row
        # 旧锁占用也须真实回读；未登记业务不被 UI 的版本证明掩盖。
        active_pids = {row.get("pid") for row in state["active"]}
        output = settings.default_output_dir
        paths = [output / name for name in ("pipeline.lock", "pipeline_job.lock", "publication_window_runner.lock",
                 "wechat_publish_priority.lock", "douyin_submission.lock", "kuaishou_submission.lock")]
        from .wechat_session_lock import canonical_wechat_session_lock_path
        paths += [canonical_wechat_session_lock_path(output / "wechat_state.json")]
        task_directory = output / "task_locks"
        if task_directory.exists():
            paths += [path for path in task_directory.iterdir() if path.suffix == ".lock"]
        for path in paths:
            row = read_lease_owner(path)
            if row and row.get("pid") not in active_pids:
                unknown.append({"code": "UNTRACKED_BUSINESS_LOCK", "role": path.stem})
        if process_pids is None:
            result = subprocess.run(["ps", "-axo", "pid=,command="], text=True, capture_output=True, timeout=2, check=True)
            process_pids = set()
            markers = ("src/web/app.py", "web.app", "video_processing.pipeline_manager", "cli.main", "scripts/",
                       "ffmpeg", "ffprobe", "yt-dlp")
            for line in result.stdout.splitlines():
                pieces = line.strip().split(None, 1)
                if len(pieces) != 2 or not pieces[0].isdigit():
                    continue
                pid, command = int(pieces[0]), pieces[1]
                commands[pid] = command
                if pid == os.getpid() or not any(marker in command for marker in markers):
                    continue
                test_entry = _test_runner_entry(command, settings.project_root)
                if str(settings.project_root) in command and test_entry is None:
                    process_pids.add(pid)
                else:
                    lsof = "/usr/sbin/lsof" if sys.platform == "darwin" else "lsof"
                    cwd = subprocess.run([lsof, "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
                                         text=True, capture_output=True, timeout=2)
                    directories = [line[1:] for line in cwd.stdout.splitlines() if line.startswith('n')]
                    if cwd.returncode or len(directories) != 1 or not Path(directories[0]).is_absolute():
                        unknown.append({"code": "PROCESS_CWD_UNKNOWN", "pid": pid})
                    elif (Path(directories[0]).resolve().is_relative_to(settings.project_root.resolve())
                          or (test_entry is not None and Path(directories[0]).resolve() !=
                              _independent_test_root(test_entry, settings.project_root, Path(directories[0]).resolve()))):
                        process_pids.add(pid)
        owned = {row["pid"] for row in owners.values()} | active_pids
        for pid in process_pids - owned:
            if sys.platform == 'darwin' and commands.get(pid, '').startswith('/bin/sh -c '):
                from .maintenance_cron import verified_cron_shell
                if verified_cron_shell(pid, commands[pid], settings.project_root, active_pids, commands, process_birth):
                    continue
            unknown.append({"code": "UNREGISTERED_PROCESS", "pid": pid})
        if evidence is None:
            unknown.append({"code": "SOURCES_NOT_VERIFIED"})
        else:
            proof = json.loads(Path(evidence).read_text())
            if (proof["schema"] != 1 or proof["version"] != state.get("version")
                    or proof["source_hash"] != code_hash() or not 0 <= time.time() - proof["at"] <= 300
                    or set(proof["groups"]) != SOURCE_GROUPS or not proof["checks"]
                    or proof["protections"] != protection_snapshot()
                    or {item["group"] for item in proof["checks"]} != SOURCE_GROUPS):
                raise ValueError("来源核实回执不匹配")
            for item in proof["checks"]:
                # 不接收通用的 true 开关；复核明确非秘密文件或受控状态输出。
                if item["kind"] == "file":
                    observed = Path(item["path"]).read_bytes()
                    receipt = json.loads(observed)
                    if (receipt["group"] != item["group"] or receipt["version"] != state["version"]
                            or receipt["source_hash"] != code_hash() or not receipt["readbacks"]
                            or any(row["state"] not in {"FROZEN", "ABSENT", "INTEGRATED"}
                                   for row in receipt["readbacks"])):
                        raise ValueError("来源清单未受控")
                elif item["kind"] == "cron":
                    observed = subprocess.run(["crontab", "-l"], capture_output=True, timeout=2).stdout
                    if str(settings.project_root).encode() in observed:
                        raise ValueError("cron 未冻结")
                elif item["kind"] == "launchd-disabled":
                    observed = subprocess.run(["launchctl", "print-disabled", f"gui/{os.getuid()}"],
                                              capture_output=True, timeout=2, check=True).stdout
                    label = item["label"]
                    if f'"{label}" => true'.encode() not in observed:
                        raise ValueError("launchd 重拉起未受控")
                else:
                    raise ValueError("未知来源证据类型")
                if hashlib.sha256(observed).hexdigest() != item["sha256"]:
                    raise ValueError("来源证据漂移")
            from ..db.database import PipelineDB
            if PipelineDB.maintenance_active_work(output / "pipeline.db"):
                unknown.append({"code": "UNFINISHED_LEDGER"})
            from .keyword_rollout import verify_loaded
            if verify_loaded(settings):
                if proof.get("keyword_profile") != settings.topic_rollout_snapshot():
                    unknown.append({"code": "KEYWORD_PROFILE_PROOF_MISMATCH"})
            elif (settings.topic_search_enabled or settings.topic_scheduler_enabled or settings.topic_admission_enabled or settings.topic_trial_mode
                  or settings.topic_quota_verified or settings.topic_quota_project):
                unknown.append({"code": "SEARCH_CLOSURE_UNCONFIRMED"})
            from ..db.topic_candidates import TopicCandidateDAL
            candidate_db = TopicCandidateDAL()
            candidate_db.db_path = str(output / "pipeline.db")
            if candidate_db.topic_control()["mode"] != "OFF":
                unknown.append({"code": "SEARCH_CLOSURE_UNCONFIRMED"})
            if candidate_db.keyword_control()['admission']:
                unknown.append({"code": "ADMISSION_CLOSURE_UNCONFIRMED"})
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, RuntimeError, TopicError, sqlite3.Error):
        unknown.append({"code": "INSPECTION_UNKNOWN"})
    return dict(state, workers=owners, unknown=unknown, phase="UNKNOWN" if unknown else state["phase"],
                safe=state["state"] == "MAINTENANCE" and not state["active"] and not unknown)


def stop_ui(control, *, evidence=None, process_pids=None, timeout=15):
    checked = inspection(control, evidence=evidence, process_pids=process_pids)
    if not checked["safe"] or "ui" not in checked["workers"]:
        raise MaintenanceDenied("NOT_VERIFIED_IDLE")
    owner = checked["workers"]["ui"]
    # 再回读同一个内核锁与完整归属，防 PID 文件漂移/重拉起后的误停。
    path = control.path.with_suffix(".workers") / "ui.lock"
    if read_lease_owner(path) != owner or process_birth(owner["pid"]) != owner.get("birth"):
        raise MaintenanceDenied("UI_OWNER_CHANGED")
    os.kill(owner["pid"], signal.SIGTERM)
    deadline = time.monotonic() + min(timeout, 15)
    while time.monotonic() < deadline:
        if not read_lease_owner(path):
            try:
                os.kill(owner["pid"], 0)
            except ProcessLookupError:
                return {"stopped": True, "pid": owner["pid"]}
        time.sleep(.05)
    raise MaintenanceDenied("STOP_TIMEOUT")
