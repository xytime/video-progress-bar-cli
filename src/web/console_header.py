"""工作台全局状态与独立频道扫描；不启动加工或发布。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-20 | Codex | 只读维护摘要、跨线程扫描互斥与真实结束状态 |
"""
from fastapi import APIRouter, HTTPException

from config.settings import settings
from video_processing.core.maintenance import gate, spawn_admitted, current
from video_processing.core.maintenance_child import run_admitted
from video_processing.core.task_lease import TaskLease, TaskLeaseBusy, read_lease_owner

router = APIRouter()
_outcome = "idle"


def _lock_path():
    return settings.default_output_dir / "channel_scan.lock"


@router.get("/api/console/header")
def header_status():
    """只读取维护登记与扫描锁，不恢复调度、不验证平台或启动登录。"""
    state = gate().status()
    return {"state": state["state"], "reason": state.get("reason", ""),
            "channel_scan": {"running": bool(read_lease_owner(_lock_path())), "outcome": _outcome}}


def _scan_channels():
    global _outcome
    root = settings.project_root
    try:
        gate().require_running()
        with (settings.default_output_dir / "channel_scan.log").open("a") as log:
            result = run_admitted(
                [str(root / ".venv/bin/python"), "-u", str(root / "scripts/monitor_channels.py"), "--bootstrap"],
                cwd=str(root), stdout=log, stderr=log, start_new_session=True,
            )
        _outcome = "complete" if result.returncode == 0 else "error"
    except Exception:
        _outcome = "error"


@router.post("/api/console/scan-channels")
def scan_channels():
    """显式准入后仅运行频道采集；锁覆盖线程排队和子进程生命周期。"""
    global _outcome
    gate().require_running()
    lease = TaskLease(_lock_path(), stage="channel-scan")
    try:
        lease.__enter__()
    except TaskLeaseBusy:
        raise HTTPException(409, "频道扫描已在运行，请等待完成")
    _outcome = "running"

    def run():
        try:
            current().start()
            _scan_channels()
        except Exception:
            global _outcome
            _outcome = "error"
            raise
        finally:
            lease.__exit__(None, None, None)

    try:
        spawn_admitted(run, role="channel-scan-dispatch", object_key="channel-scan", name="channel-scan", waiting=True)
    except BaseException:
        _outcome = "error"
        lease.__exit__(None, None, None)
        raise
    return {"started": True, "message": "频道扫描已启动，仅采集元数据；可在频道白名单查看访问结果"}
