"""持久化评论扫描释放时间；复用既有发送检查，仅恢复扫描阶段。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.1 | 2026-10-26 | Codex | 已允许准入的 until 是检查时刻而非阻挡期限，避免循环追逐移动时钟。 |
| 1.0.0 | 2026-10-25 | Codex | 本地等待不占浏览器、不计费；到期重检全部原生门禁，重启沿用等待事实。 |
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import time
import uuid
from zoneinfo import ZoneInfo

from config.settings import settings


def scope_key(account, finder):
    return hashlib.sha256((account + "\n" + finder).encode()).hexdigest()


class ScanWakeStore:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def locked(self, suffix=".lock", *, nonblocking=False):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_suffix(suffix).open("a+b") as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblocking else 0))
            except BlockingIOError:
                yield False
                return
            try:
                yield True
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def read(self):
        if not self.path.exists():
            return None
        row = json.loads(self.path.read_text(encoding="utf-8"))
        if row is None:
            return None
        if (not isinstance(row, dict) or set(row) != {"schema", "token", "scope", "wake_at", "scan_limit", "revision", "codes"}
                or row["schema"] != 1 or not isinstance(row["token"], str)
                or not isinstance(row["scope"], str) or len(row["scope"]) != 64
                or type(row["wake_at"]) not in (int, float) or not math.isfinite(row["wake_at"])
                or type(row["scan_limit"]) is not int or not 1 <= row["scan_limit"] <= 5
                or not isinstance(row["codes"], list) or not all(isinstance(c, str) for c in row["codes"])
                or not isinstance(row["revision"], str)):
            raise ValueError("扫描等待记录无效；不启动扫描")
        return row

    def _write(self, row):
        temp = self.path.with_name(self.path.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            with temp.open("x", encoding="utf-8") as stream:
                temp.chmod(0o600)
                json.dump(row, stream, ensure_ascii=False, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            temp.replace(self.path)
        finally:
            temp.unlink(missing_ok=True)

    def defer(self, scope, *, until, scan_limit, revision="", codes=(), expected_token=None):
        if type(until) not in (int, float) or not math.isfinite(until):
            raise ValueError("扫描释放时间必须是有限的 epoch 秒")
        if (not isinstance(scope, str) or len(scope) != 64 or type(scan_limit) is not int
                or not 1 <= scan_limit <= 5 or not isinstance(revision, str)):
            raise ValueError("扫描等待作用域或批次上限无效")
        with self.locked():
            current = self.read()
            if expected_token is not None and (not current or current["token"] != expected_token):
                return None
            row = dict(schema=1, token=uuid.uuid4().hex, scope=scope, wake_at=until,
                       scan_limit=scan_limit, revision=revision, codes=list(codes))
            self._write(row)
            return row

    def complete(self, scope, token):
        with self.locked():
            row = self.read()
            if row and row["scope"] == scope and row["token"] == token:
                self._write(None)


def store():
    return ScanWakeStore(settings.default_output_dir / "secondary_reply_scan_wake.json")


def remember_scan_wait(exc, *, account, finder, scan_limit, platform):
    """只登记正常自动扫描；具名单次人工范围不扩展到后台恢复。"""
    if not getattr(getattr(platform, "adapter", None), "state_path", None):
        return None
    from video_processing.utils.runtime_configuration import snapshot, value
    current = snapshot(fresh=True)
    hint = getattr(exc, "admission", None) or {}
    until = hint.get("until")
    if type(until) not in (int, float) or not math.isfinite(until):
        until = time.time() + value("task_scheduling", "local_defer_fallback_seconds", 300)
    codes = [str(x.get("code", "UNKNOWN")) for x in hint.get("blockers", [])] or ["RESOURCE_OR_ADMISSION_WAIT"]
    return store().defer(scope_key(account, finder), until=until, scan_limit=scan_limit,
                         revision=current.revision if current else "", codes=codes)


def window_open_at(now, start, end):
    """北京时间窗口；只限制恢复入口，不改变原正常扫描的时段合同。"""
    local = datetime.fromtimestamp(now, timezone.utc).astimezone(ZoneInfo("Asia/Shanghai"))
    parse = lambda value: int(value[:2]) * 60 + int(value[3:])
    a, b, minute = parse(start), parse(end), local.hour * 60 + local.minute
    if a == b or (a < b and a <= minute < b) or (a > b and (minute >= a or minute < b)):
        return now
    opening = local.replace(hour=a // 60, minute=a % 60, second=0, microsecond=0)
    if opening.timestamp() <= now:
        opening += timedelta(days=1)
    return opening.timestamp()


class NativeScanWakeEnvironment:
    def __init__(self, platform):
        self.platform = platform

    def inspect(self, now):
        from video_processing.core.maintenance import gate
        from video_processing.core.wechat_request_guard import WeChatRequestGuard
        from video_processing.interaction.secondary_reply_ops import DEFAULT_STOP_FILE
        from video_processing.utils.runtime_configuration import snapshot
        gate().require_running()
        current = snapshot(fresh=True)
        domains = current.domains()
        controls = domains["interaction_controls"]
        strategy = controls.get("reply_strategy") or {
            "window_start_shanghai": settings.wechat_reply_window_start_shanghai,
            "window_end_shanghai": settings.wechat_reply_window_end_shanghai}
        return {"enabled": controls["automatic_replies_enabled"] and not DEFAULT_STOP_FILE.exists(),
                "window_until": window_open_at(now, strategy["window_start_shanghai"], strategy["window_end_shanghai"]),
                "admission": WeChatRequestGuard(self.platform.adapter.state_path).evaluate(purpose="评论扫描", account_only=True),
                "scan_limit": domains["wechat_operations"]["operations"]["comment_scan"]["max_videos_per_run"],
                "revision": current.revision}


def resume_scan_wait(wakes, scope, environment, execute, *, cadence, now=time.time,
                     sleep=time.sleep, monotonic=time.monotonic):
    """正常发送检查顺带恢复已登记扫描，绝不增加新的平台扫描许可。

    长等待仅保存；进入既有检查节拍的最后一个周期才本地等待，不占浏览器。
    等待中的维护/配置/开关变化每秒重查。单次至多执行一次扫描阶段。
    """
    row = wakes.read()
    if not row or row["scope"] != scope:
        return None
    with wakes.locked(".run.lock", nonblocking=True) as claimed:
        if not claimed:
            return {"ok": True, "status": "SCAN_WAKE_ALREADY_RUNNING"}
        row = wakes.read()
        if not row or row["scope"] != scope:
            return None
        original_token = row["token"]
        # 未核实检查周期时不推测预唤醒；已经到期仍可走完整准入。
        horizon = min(cadence, 300) if type(cadence) is int and cadence > 0 else 0
        started = monotonic()
        while True:
            latest = wakes.read()
            if not latest or latest["token"] != original_token:
                return {"ok": True, "status": "SCAN_WAKE_SUPERSEDED"}
            current_time = now()
            control = environment.inspect(current_time)
            if not control["enabled"]:
                return {"ok": True, "status": "SCAN_WAKE_PAUSED_DISABLED"}
            admission = control["admission"]
            release = admission.get("until")
            if not admission.get("allowed") and (type(release) not in (int, float) or not math.isfinite(release)):
                return {"ok": True, "status": "SCAN_WAKE_BLOCKED", "scan_wait": row}
            # allowed 时原生 until 默认是 guard 稍后取得的当前时刻，不能当作新门禁。
            deadline = control["window_until"]
            if not admission.get("allowed"):
                deadline = max(deadline, release)
            if "RESOURCE_OR_ADMISSION_WAIT" in row["codes"]:
                deadline = max(deadline, row["wake_at"])
            if deadline > current_time:
                remaining_budget = horizon + 1 - (monotonic() - started)
                if deadline - current_time > remaining_budget:
                    updated = wakes.defer(scope, until=deadline, scan_limit=row["scan_limit"],
                        revision=control["revision"], codes=[str(x.get("code", "UNKNOWN")) for x in admission.get("blockers", [])],
                        expected_token=original_token)
                    return None if updated else {"ok": True, "status": "SCAN_WAKE_SUPERSEDED"}
                sleep(min(1.0, deadline - current_time))
                continue
            if not admission.get("allowed"):
                return {"ok": True, "status": "SCAN_WAKE_BLOCKED", "scan_wait": row}
            result = execute(min(row["scan_limit"], control["scan_limit"]))
            if not result.get("scan_deferred") and result.get("status") not in {
                    "DEFERRED_MAINTENANCE", "SKIPPED_FEATURE_DISABLED", "SKIPPED_STOP_FILE_PRESENT", "CONFIG_MISSING"}:
                wakes.complete(scope, original_token)
            return {**result, "scan_wake_resumed": True}
