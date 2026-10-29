"""运行环境锁、进程存活与进度文件只读探测器（无业务写入，观测失败显式不可用）。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.2.0 | 2026-10-29 | Codex | 正确读取配置，保留锁/进度/窗口观测失败，统一观测时间。 |
| 1.1.0 | 2026-10-29 | Antigravity | 修复规范化授权状态文件路径（移除多余前导点）、支持 requests.json 重新登录检测与 market 窗口 epoch 透传。 |
| 1.0.0 | 2026-10-29 | Antigravity | 初始创建运行环境锁快照、任务锁与进度文件只读探测能力。 |
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from typing import Any, Optional, Sequence

from ..funnel_diagnosis.models import RuntimeEnvironmentFacts, TaskUnitFacts
from ..funnel_diagnosis.rules import format_bj_timestamp
from .task_lease import read_lease_owner


def is_pid_alive(pid: Optional[int]) -> bool:
    """安全检测进程 PID 是否存活；无进程、非法 PID 或无权限时不抛异常。"""
    if pid is None or not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        raise
    except (OSError, ProcessLookupError):
        return False


def read_task_lease_owner(lock_path: Path) -> dict[str, Any]:
    """安全调用 read_lease_owner 获取锁归属信息，防御任何路径或权限异常。"""
    owner = read_lease_owner(Path(lock_path))
    if not isinstance(owner, dict):
        raise ValueError("Invalid lease observation")
    return owner


def read_caption_progress(output_dir: Path, prefix: str) -> dict[str, Any]:
    """只读检查字幕阶段文件 output/{prefix}_caption_progress.json。"""
    res: dict[str, Any] = {
        "stage": None,
        "stage_started_epoch": None,
        "updated_epoch": None,
    }
    try:
        p = Path(output_dir) / f"{prefix}_caption_progress.json"
        if not p.is_file():
            return res
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Invalid caption progress")
        st = data.get("stage")
        res["stage"] = str(st) if st else None
        st_at = data.get("stage_started_at")
        res["stage_started_epoch"] = float(st_at) if st_at is not None else None
        up_at = data.get("updated_at")
        res["updated_epoch"] = float(up_at) if up_at is not None else None
    except FileNotFoundError:
        pass
    return res


def _read_ready_supervisor_heartbeat(
    output_dir: Path, now_epoch: float
) -> Optional[float]:
    """只读检查 ready_publications_status.json 中的调度心跳。"""
    try:
        status_path = Path(output_dir) / "ready_publications_status.json"
        if not status_path.is_file():
            return None
        payload = json.loads(status_path.read_text(encoding="utf-8"))
        hb = float(payload.get("heartbeat_at", 0))
        return max(0.0, now_epoch - hb) if hb > 0 else None
    except FileNotFoundError:
        return None


def _read_wechat_cooldown(
    output_dir: Path, now_epoch: float
) -> tuple[Optional[float], str]:
    """只读读取微信请求守卫状态文件，获取退避到期时刻与原因。"""
    try:
        p = Path(output_dir) / ".wechat_state.json.requests.json"
        if not p.is_file():
            return None, ""
        data = json.loads(p.read_text(encoding="utf-8"))
        b_until = float(data.get("blocked_until") or 0)
        n_sess = float(data.get("next_session_at") or 0)
        until = max(b_until, n_sess)
        if until > now_epoch:
            reason = "视频号返回限流" if b_until >= n_sess else "账号会话最小间隔"
            return until, reason
    except FileNotFoundError:
        pass
    return None, ""


def _check_wechat_login_valid(output_dir: Path) -> bool:
    """只读检测微信授权凭据文件、元数据文件与请求守卫手工登录标记。"""
    try:
        state_path = Path(output_dir) / "wechat_state.json"
        if not state_path.is_file():
            return False
        auth_candidates = [
            state_path.with_name(f"{state_path.name}.auth_state.json"),
            state_path.with_name(f".{state_path.name}.auth_state.json"),
            state_path.with_name("wechat_auth_state.json"),
        ]
        for auth_path in auth_candidates:
            if auth_path.is_file():
                auth = json.loads(auth_path.read_text(encoding="utf-8"))
                status = str(auth.get("last_keepalive_status") or "")
                last_v = auth.get("last_verified_at")
                last_k = auth.get("last_keepalive_at")
                superseded = bool(last_v and (last_k is None or last_v > last_k))
                if status in ("LOGIN_REQUIRED", "REUSE_VERIFICATION_FAILED") and not superseded:
                    return False
                break
        req_path = state_path.with_name(f".{state_path.name}.requests.json")
        if req_path.is_file():
            req_data = json.loads(req_path.read_text(encoding="utf-8"))
            if req_data.get("requires_manual_login"):
                return False
        return True
    except FileNotFoundError:
        return False


def _check_agy_cover_relogin(output_dir: Path, now_epoch: float) -> bool:
    """只读读取 AGY 封面授权状态快照。"""
    try:
        auth_file = Path(output_dir) / "agy_cover_auth.json"
        if not auth_file.is_file():
            return False
        data = json.loads(auth_file.read_text(encoding="utf-8"))
        chk = float(data.get("checked_at") or 0)
        fresh = 0 < chk <= now_epoch and (now_epoch - chk) < 300
        return bool(fresh and data.get("status") == "AUTH_REQUIRED")
    except FileNotFoundError:
        return False


def _check_market_and_publish_windows(
    now_epoch: Optional[float] = None,
) -> tuple[bool, bool, bool]:
    """读取 settings 配置中的美股盘中避让、公开发布窗口与发布暂停开关（透传 epoch）。"""
    from config.settings import settings
    now_dt = datetime.fromtimestamp(now_epoch, tz=timezone.utc) if now_epoch is not None else None
    return (
        bool(settings.is_us_market_guard_window(now=now_dt)),
        bool(settings.is_public_publish_window(now=now_dt)),
        bool(settings.wechat_publishing_paused),
    )


def _resolve_output_dir(output_dir: Optional[Path]) -> Path:
    """安全解析输出目录路径。"""
    if output_dir is not None:
        return Path(output_dir)
    from config.settings import settings
    return Path(settings.default_output_dir)


def _observe(call, fallback, errors: list[str], source: str):
    try:
        return call()
    except Exception as exc:
        errors.append(f"{source}:{type(exc).__name__}")
        return fallback


def probe_runtime_environment(
    output_dir: Optional[Path] = None,
    now_epoch: Optional[float] = None,
) -> RuntimeEnvironmentFacts:
    """只读采集当前运行环境锁、进程心跳与窗口状态快照。"""
    ep = float(now_epoch if now_epoch is not None else time.time())
    out = _resolve_output_dir(output_dir)

    errors: list[str] = []
    def owner(name):
        return _observe(lambda: read_task_lease_owner(out / name), {}, errors, name)
    pipe_owner = owner("pipeline.lock")
    ready_owner = owner("ready_publications.lock")
    rec_owner = owner("publishing_recovery_worker.lock")
    browser_owner = owner(".wechat_state.json.browser.lock")
    hb_age = _observe(lambda: _read_ready_supervisor_heartbeat(out, ep), None, errors, "supervisor_heartbeat")
    cooldown_until, cooldown_reason = _observe(lambda: _read_wechat_cooldown(out, ep), (None, ""), errors, "cooldown")
    wechat_valid = _observe(lambda: _check_wechat_login_valid(out), False, errors, "login_metadata")
    agy_relogin = _observe(lambda: _check_agy_cover_relogin(out, ep), False, errors, "cover_auth_metadata")
    in_guard, in_pub, wechat_paused = _observe(lambda: _check_market_and_publish_windows(ep), (True, False, True), errors, "schedule_config")

    return RuntimeEnvironmentFacts(
        now_epoch=ep,
        now_bj_iso=format_bj_timestamp(ep),
        in_market_guard_window=in_guard,
        in_public_publish_window=in_pub,
        wechat_publishing_paused=wechat_paused,
        pipeline_lock_held=bool(pipe_owner),
        pipeline_lock_owner=pipe_owner,
        ready_supervisor_lock_held=bool(ready_owner),
        ready_supervisor_heartbeat_age_sec=hb_age,
        recovery_worker_lock_held=bool(rec_owner),
        wechat_browser_lock_held=bool(browser_owner),
        wechat_cooldown_until_epoch=cooldown_until,
        wechat_cooldown_reason=cooldown_reason,
        wechat_login_valid=wechat_valid,
        agy_cover_relogin_required=agy_relogin,
        runtime_available=not errors,
        runtime_unavailable_reasons=tuple(errors),
    )


def enrich_task_facts_with_runtime(
    task: TaskUnitFacts,
    output_dir: Optional[Path] = None,
) -> TaskUnitFacts:
    """为单条任务单元补充运行态探针事实（内核任务锁、字幕进度心跳与进程存活）。"""
    out = _resolve_output_dir(output_dir)
    prefix = f"{task.youtube_id}_s{task.slice_index}" if task.slice_index else task.youtube_id
    errors: list[str] = []
    task_owner = _observe(lambda: read_task_lease_owner(out / "task_locks" / f"{prefix}.lock"), {}, errors, "task_lease")
    cp = _observe(lambda: read_caption_progress(out, prefix), {}, errors, "caption_progress")
    alive = _observe(lambda: is_pid_alive(task.process_pid) or is_pid_alive(task_owner.get("pid")), False, errors, "process")

    return replace(
        task,
        has_active_task_lock=bool(task_owner),
        task_lock_owner=task_owner,
        caption_stage=cp.get("stage"),
        caption_stage_started_epoch=cp.get("stage_started_epoch"),
        caption_progress_updated_epoch=cp.get("updated_epoch"),
        process_alive=alive,
        runtime_observation_available=not errors,
        runtime_observed_at_bj=format_bj_timestamp(time.time()),
    )


def enrich_cohort_tasks_with_runtime(
    tasks: Sequence[TaskUnitFacts],
    output_dir: Optional[Path] = None,
) -> list[TaskUnitFacts]:
    """批量为入库批次任务事实列表补充运行态探针数据。"""
    return [enrich_task_facts_with_runtime(t, output_dir=output_dir) for t in tasks]
