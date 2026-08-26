#!/usr/bin/env python3
"""每日英语世界短视频生产协调器：仅制作并发 Telegram 审核，不投稿。

本入口由 LaunchAgent 直接以 Python 程序执行，避免 launchd 通过 shell 读取外接盘
脚本时受 macOS 文件访问策略拦截。

# Modification History
# | Version | Date | Author | Description |
# | --- | --- | --- | --- |
# | 2.0.0 | 2026-08-24 | Codex | 以直接 Python 入口替代 shell 协调器，保留有界重试、锁、状态及 Telegram 失败回执。 |
# | 2.1.0 | 2026-08-24 | Codex | 日更生产提示明确英语世界成片必须严格大于 30 秒且不超过 300 秒。 |
# | 2.2.0 | 2026-08-25 | Codex | 对 Codex 瞬时传输故障和 Telegram 失败回执实施有界重试，避免网络抖动吞掉审核窗口。 |
# | 2.3.0 | 2026-08-25 | Codex | 瞬时失败重试前核验本次已获 API 接受的审核回执，阻断可能重复的生产/投递。 |
# | 2.4.0 | 2026-08-26 | Codex | 为 Codex 协调器增加进程组级超时终止与持久失败状态，卡死不再吞掉当日审核窗口。 |
# | 2.5.0 | 2026-08-26 | Codex | 锁持久化所有者 PID；仅回收已证实进程不存在的陈旧锁，避免中断后永久跳过日更。 |
# | 2.6.0 | 2026-08-26 | Codex | SIGTERM/SIGINT 受控收口：终止协调器子进程组、持久化中断状态并释放锁。 |
# | 2.7.0 | 2026-08-26 | Codex | 明确生产代理不得接管锁、进程或失败通知，防止其越权终止协调器。 |
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TextIO


DEFAULT_PROJECT_ROOT = Path("/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing")
DEFAULT_CODEX_HOME = Path("/Users/ryusei/.codex")
DEFAULT_CODEX_BIN = Path("/Users/ryusei/.local/bin/codex")

PROMPT = """执行今日“英语世界短视频”无人值守制作任务。工作目录是 Video-precessing。

这是独立的 ENGLISH_WORLD_SHORT 生产：不得编辑项目源码、不得修改通用频道白名单、不得调用 PipelineManager、wechat_uploader.py 或任何平台投稿/发布逻辑；绝不提交视频号。只允许生成学习卡素材和发送 Telegram 审核回执。

协调器进程、锁、重试、失败通知和运行日志均由本入口管理。不得运行 `kill`、`pkill`、`launchctl`、`rm`、`rmdir` 或任何进程/锁清理命令；不得根据既有日志自行发送失败通知、终止进程或干预其他运行。遇到已有素材、旧审核项或运行异常时，只报告事实并继续本次合规素材的研究/制作；本入口会负责收口。

来源仅限以下频道，并按频道 ID 严格核验：
- CBC Kids News：UCWUA2W6LueNy9BSovivFVvQ
- CBS Evening News：UCAeWdyKJXGWmVAXFpgLNNTg
- ABC News：UCBi2mrWuNuyYy4gbM6fU18Q

先搜索当天或近期未使用的候选，再检查标题、简介、英文字幕/转写和必要的画面。只能选择适合儿童与家庭学习者的自然、科学、教育、健康、文化、日常生活或正向人文题材。排除政治、战争、暴力、犯罪、成人话题、强时政评论，以及包含真实伤亡、恐慌、疏散或令人不适灾情画面的素材；不确定即放弃当天生产。自然科学与天气科普（包括风暴、闪电、龙卷风的成因）并非关键词禁区，必须结合实际画面和叙事判断。

若找到合格来源，按 make-english-world-short 技能和 production-contract 完整制作一条：自然完整句收尾；逐词红线；每个可见阅读屏至少 8 个微笔记；右栏随左侧同步且可用时至少 5 张词卡；中文完整；词汇只用已有离线 Hermes 分级；`content_type=ENGLISH_WORLD_SHORT`；保留 source_provenance、timeline、manifest、质检材料。最终 MP4 实测时长必须严格大于 30 秒且不超过 300 秒；不得用静音、循环或无语音尾段凑时长，必须覆盖完整自然语句。完成后核验 MP4、音频收尾、manifest 与关键帧。

质检通过后，必须运行以下命令把 MP4 和 manifest 发到 Telegram 人工审核：
PYTHONPATH=src .venv/bin/python scripts/notify_english_world_review.py --title '<实际标题>' --mp4 '<绝对MP4路径>' --manifest '<绝对manifest路径>'
若当天无合格候选或制作/质检失败，必须运行：
PYTHONPATH=src .venv/bin/python scripts/notify_english_world_review.py --title '今日英语世界短视频' --failure '<准确原因>'

最终只报告真实状态、来源、证据路径与 Telegram 发送结果。不得将 Telegram 发送、素材生成或审核回执描述成视频号发布。"""


@dataclass(frozen=True)
class RuntimePaths:
    project_root: Path
    codex_home: Path
    codex_bin: Path
    python_bin: Path
    notifier_script: Path
    log_dir: Path
    lock_dir: Path
    coordinator_timeout_seconds: float


class CoordinatorInterrupted(RuntimeError):
    """协调器父进程收到中断信号；必须落盘而不是留下孤儿锁。"""

    def __init__(self, signum: int) -> None:
        self.signum = signum
        super().__init__(f"coordinator interrupted by signal {signum}")


def _raise_coordinator_interrupted(signum: int, _frame: object) -> None:
    raise CoordinatorInterrupted(signum)


def _lock_owner_path(lock_dir: Path) -> Path:
    return lock_dir / "owner.json"


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _acquire_lock(lock_dir: Path) -> bool:
    """领取日更锁；只回收带失效 PID 的新式锁，旧空锁须由运维显式处理。"""
    try:
        lock_dir.mkdir()
    except FileExistsError:
        owner_path = _lock_owner_path(lock_dir)
        try:
            owner = json.loads(owner_path.read_text(encoding="utf-8"))
            owner_pid = int(owner.get("pid", 0))
        except (OSError, ValueError, json.JSONDecodeError, TypeError):
            return False
        if _pid_is_running(owner_pid):
            return False
        try:
            owner_path.unlink()
            lock_dir.rmdir()
            lock_dir.mkdir()
        except OSError:
            return False
    _lock_owner_path(lock_dir).write_text(
        json.dumps({"pid": os.getpid(), "started_at": _timestamp()}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return True


def _release_lock(lock_dir: Path) -> None:
    try:
        _lock_owner_path(lock_dir).unlink()
        lock_dir.rmdir()
    except OSError:
        pass


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    """尽力结束独立协调器进程组；进程已退出也视为成功。"""
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=10)
        except ProcessLookupError:
            pass
    except ProcessLookupError:
        pass


def _timestamp() -> str:
    return datetime.now().strftime("%F %T %z")


def _write_status(status_path: Path, phase: str, exit_code: int, attempts: int, run_log: Path, response_path: Path) -> None:
    content = (
        f"timestamp={_timestamp()}\nphase={phase}\nexit_code={exit_code}\nattempts={attempts}\n"
        f"run_log={run_log}\nresponse_path={response_path}\n"
    )
    temporary_path = status_path.with_suffix(".tmp")
    temporary_path.write_text(content, encoding="utf-8")
    temporary_path.replace(status_path)


def _log(stream: TextIO, message: str) -> None:
    stream.write(f"[{_timestamp()}] {message}\n")
    stream.flush()


def _is_transient_transport_failure(run_log: Path, start_offset: int = 0) -> bool:
    """只把明确的网络瞬断归入重试，避免对业务/质量错误盲目重跑。"""
    try:
        with run_log.open("rb") as stream:
            stream.seek(max(0, start_offset))
            text = stream.read().decode("utf-8", errors="replace").lower()
    except OSError:
        return False
    markers = (
        "tls handshake eof",
        "stream disconnected",
        "connection reset",
        "connection refused",
        "timed out",
        "temporary failure in name resolution",
        "network is unreachable",
    )
    return any(marker in text for marker in markers)


def _accepted_review_receipt_snapshots(project_root: Path) -> dict[Path, int]:
    """读取可审计的 Telegram 审核回执快照；不把本地成片当作投递成功。"""
    receipt_root = project_root / "output" / "english_world_daily"
    snapshots: dict[Path, int] = {}
    for receipt_path in receipt_root.glob("*/*/telegram_receipt.json"):
        try:
            payload = json.loads(receipt_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and payload.get("status") == "ACCEPTED":
                snapshots[receipt_path.resolve()] = receipt_path.stat().st_mtime_ns
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return snapshots


def _new_accepted_review_receipts(project_root: Path, before: dict[Path, int]) -> list[Path]:
    """返回一次协调尝试中新增或更新且已获 Telegram API 接受的审核回执。"""
    after = _accepted_review_receipt_snapshots(project_root)
    return sorted(path for path, modified_at in after.items() if before.get(path) != modified_at)


def _notify_failure(
    paths: RuntimePaths,
    reason: str,
    stream: TextIO,
    *,
    max_attempts: int = 3,
    retry_delay_seconds: float = 10,
) -> None:
    if not paths.python_bin.is_file() or not paths.notifier_script.is_file():
        _log(stream, "ERROR: cannot notify Telegram; notifier unavailable")
        return
    for attempt in range(1, max_attempts + 1):
        result = subprocess.run(
            [str(paths.python_bin), str(paths.notifier_script), "--title", "今日英语世界短视频", "--failure", reason],
            stdout=stream,
            stderr=subprocess.STDOUT,
            check=False,
            text=True,
        )
        if result.returncode == 0:
            _log(stream, f"Telegram failure notifier accepted on attempt {attempt}/{max_attempts}")
            return
        _log(stream, f"ERROR: Telegram failure notifier exited {result.returncode} (attempt {attempt}/{max_attempts})")
        if attempt < max_attempts:
            time.sleep(retry_delay_seconds)
    _log(stream, "ERROR: Telegram failure notifier exhausted retries; local run log is the authoritative failure record")


def _run_coordinator(paths: RuntimePaths, response_path: Path, stream: TextIO) -> int:
    """运行一次协调器；超时后终止整个进程组，避免遗留子进程继续生产。"""
    command = [
        str(paths.codex_bin), "exec", "--cd", str(paths.project_root), "--add-dir", "/Users/ryusei/.codex/skills",
        "--sandbox", "danger-full-access", "-c", 'approval_policy="never"', "--output-last-message", str(response_path), PROMPT,
    ]
    environment = dict(os.environ)
    environment["CODEX_HOME"] = str(paths.codex_home)
    process = subprocess.Popen(
        command,
        cwd=paths.project_root,
        env=environment,
        stdout=stream,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    try:
        return process.wait(timeout=paths.coordinator_timeout_seconds)
    except subprocess.TimeoutExpired:
        _log(
            stream,
            "ERROR: coordinator timed out after "
            f"{paths.coordinator_timeout_seconds:g}s; terminating its process group",
        )
        _terminate_process_group(process)
        raise
    except BaseException:
        _terminate_process_group(process)
        raise


def run(paths: RuntimePaths, *, max_attempts: int, retry_delay_seconds: float) -> int:
    paths.log_dir.mkdir(parents=True, exist_ok=True)
    paths.lock_dir.parent.mkdir(parents=True, exist_ok=True)
    response_path = paths.log_dir / "last_codex_response.md"
    status_path = paths.log_dir / "last_run_status.txt"
    run_log = paths.log_dir / f"run_{datetime.now().strftime('%F_%H%M%S')}.log"
    if not _acquire_lock(paths.lock_dir):
        with run_log.open("a", encoding="utf-8") as stream:
            _log(stream, "skipped: daily English World run is already active")
        _write_status(status_path, "SKIPPED_ACTIVE", 0, 0, run_log, response_path)
        return 0

    previous_sigterm_handler = signal.signal(signal.SIGTERM, _raise_coordinator_interrupted)
    previous_sigint_handler = signal.signal(signal.SIGINT, _raise_coordinator_interrupted)
    try:
        with run_log.open("a", encoding="utf-8") as stream:
            if not paths.codex_bin.is_file() or not os.access(paths.codex_bin, os.X_OK):
                _log(stream, f"ERROR: Codex CLI is not executable: {paths.codex_bin}")
                _write_status(status_path, "FAILED_BOOTSTRAP", 1, 0, run_log, response_path)
                _notify_failure(paths, f"生产协调器未启动：Codex CLI 不可执行。运行日志：{run_log}", stream)
                return 1
            _log(stream, "starting daily English World production coordinator")
            exit_code = 0
            accepted_receipts: list[Path] = []
            for attempt in range(1, max_attempts + 1):
                _log(stream, f"coordinator attempt {attempt}/{max_attempts}")
                attempt_log_offset = run_log.stat().st_size
                receipt_snapshot = _accepted_review_receipt_snapshots(paths.project_root)
                try:
                    exit_code = _run_coordinator(paths, response_path, stream)
                except subprocess.TimeoutExpired:
                    exit_code = 124
                    accepted_receipts = _new_accepted_review_receipts(paths.project_root, receipt_snapshot)
                    if accepted_receipts:
                        _log(
                            stream,
                            "accepted Telegram review receipt detected after coordinator timeout; "
                            "stopping without retry: " + ", ".join(str(path) for path in accepted_receipts),
                        )
                        _write_status(
                            status_path,
                            "COORDINATOR_DELIVERY_UNCERTAIN",
                            exit_code,
                            attempt,
                            run_log,
                            response_path,
                        )
                        return exit_code
                    _write_status(status_path, "COORDINATOR_TIMED_OUT", exit_code, attempt, run_log, response_path)
                    _notify_failure(
                        paths,
                        f"生产协调器超过 {paths.coordinator_timeout_seconds:g} 秒未退出，已终止其进程组"
                        f"（尝试={attempt}/{max_attempts}）。运行日志：{run_log}。"
                        "未生成可确认的今日审核成片，未触发视频号投稿。",
                        stream,
                    )
                    return exit_code
                accepted_receipts = _new_accepted_review_receipts(paths.project_root, receipt_snapshot)
                if exit_code != 0 and accepted_receipts:
                    _log(
                        stream,
                        "accepted Telegram review receipt detected after failed coordinator; "
                        "stopping without retry: " + ", ".join(str(path) for path in accepted_receipts),
                    )
                    _write_status(
                        status_path,
                        "COORDINATOR_DELIVERY_UNCERTAIN",
                        exit_code,
                        attempt,
                        run_log,
                        response_path,
                    )
                    return exit_code
                transient_failure = exit_code == 78 or (
                    exit_code != 0 and _is_transient_transport_failure(run_log, attempt_log_offset)
                )
                if not transient_failure or attempt == max_attempts:
                    break
                _log(stream, f"Codex transient transport failure (exit={exit_code}); retrying after {retry_delay_seconds:g}s")
                time.sleep(retry_delay_seconds)
            if exit_code == 0:
                _write_status(status_path, "COORDINATOR_FINISHED", 0, attempt, run_log, response_path)
                _log(stream, "coordinator exited successfully; inspect its Telegram receipt separately")
                return 0
            _write_status(status_path, "FAILED_COORDINATOR", exit_code, attempt, run_log, response_path)
            _notify_failure(paths, f"生产协调器异常退出（exit={exit_code}，尝试={attempt}/{max_attempts}）。运行日志：{run_log}。未生成可确认的今日审核成片，未触发视频号投稿。", stream)
            return exit_code
    except CoordinatorInterrupted as exc:
        exit_code = 128 + exc.signum
        with run_log.open("a", encoding="utf-8") as stream:
            _log(stream, f"ERROR: coordinator interrupted by signal {exc.signum}; production child group was terminated")
            _write_status(status_path, "COORDINATOR_INTERRUPTED", exit_code, 0, run_log, response_path)
            _notify_failure(
                paths,
                f"生产协调器被信号 {exc.signum} 中断，已终止其子进程组。运行日志：{run_log}。"
                "未生成可确认的今日审核成片，未触发视频号投稿。",
                stream,
            )
        return exit_code
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm_handler)
        signal.signal(signal.SIGINT, previous_sigint_handler)
        _release_lock(paths.lock_dir)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=DEFAULT_PROJECT_ROOT)
    parser.add_argument("--codex-home", type=Path, default=DEFAULT_CODEX_HOME)
    parser.add_argument("--codex-bin", type=Path, default=DEFAULT_CODEX_BIN)
    parser.add_argument("--python-bin", type=Path)
    parser.add_argument("--notifier-script", type=Path)
    parser.add_argument("--log-dir", type=Path)
    parser.add_argument("--lock-dir", type=Path)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--retry-delay-seconds", type=float, default=15)
    parser.add_argument(
        "--coordinator-timeout-seconds",
        type=float,
        default=2 * 60 * 60,
        help="单次 Codex 协调器最长运行时间；超时将终止整个进程组并写入状态账本。",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    if args.max_attempts < 1:
        raise ValueError("--max-attempts must be at least 1")
    if args.coordinator_timeout_seconds <= 0:
        raise ValueError("--coordinator-timeout-seconds must be greater than 0")
    project_root = args.project_root.resolve()
    paths = RuntimePaths(
        project_root=project_root,
        codex_home=args.codex_home,
        codex_bin=args.codex_bin,
        python_bin=args.python_bin or project_root / ".venv/bin/python",
        notifier_script=args.notifier_script or project_root / "scripts/notify_english_world_review.py",
        log_dir=args.log_dir or project_root / "output/english_world_daily",
        lock_dir=args.lock_dir or project_root / "output/locks/english_world_daily.lock",
        coordinator_timeout_seconds=args.coordinator_timeout_seconds,
    )
    return run(paths, max_attempts=args.max_attempts, retry_delay_seconds=args.retry_delay_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
