"""视频号授权与会话结构化状态管理。

管理本地结构化证据，包括授权时间、最近验证/保活时间、最近失败详情、
调度阈值与锁状态。所有状态更新均通过原子写入与白名单字段持久化，
不读写或输出任何敏感凭证（如 Cookie 载荷或 Token）。

依赖方向：
core/wechat_auth_state.py -> config/settings.py
（仅依赖标准库及配置真相源，不反向依赖上层 scripts/cli/bot）。

# Modification History
| Version | Date       | Author      | Description                                                  |
|---------|------------|-------------|--------------------------------------------------------------|
| 1.3.0   | 2026-09-28 | Antigravity | 新增 last_auth_attempt_* 尝试证据追踪，失败可查分类原因；完善读取校验与展示 |
| 1.2.0   | 2026-09-28 | Antigravity | 区分历史保活失败与新验证时序、收口固定分类失败摘要、去除未来时间clamp、完整扩展名元数据派生与排期持久化 |
| 1.1.0   | 2026-09-28 | Antigravity | 修复元数据路径唯一派生、read-modify-write并发锁、脱敏白名单过滤、严谨状态评定与调度覆盖 |
| 1.0.0   | 2026-09-28 | Antigravity | 初始创建：本地结构化授权/保活状态管理，支持原子更新、白名单过滤及状态报告 |
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import logging
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from config.settings import settings

logger = logging.getLogger(__name__)

BJ_TZ = ZoneInfo("Asia/Shanghai")
AUTH_STATE_VERSION = "1.3.0"

DEFAULT_WECHAT_STATE_FILE = Path(__file__).resolve().parents[3] / "output" / "wechat_state.json"

VALID_AUTH_METHODS = {"desktop_quick", "scan_qr", "interactive", "auto", "legacy"}
VALID_KEEPALIVE_STATUSES = {
    "SUCCESS",
    "LOGIN_REQUIRED",
    "NETWORK_TIMEOUT",
    "INVALID_ORIGIN",
    "PAGE_UNREADY",
    "DOM_ERROR",
    "STORAGE_FAILED",
    "REUSE_VERIFICATION_FAILED",
    "UNKNOWN",
}
VALID_STAGES = {
    "navigation",
    "positive_validation",
    "dwell",
    "storage_save",
    "reuse_verification",
    "preflight",
    "keepalive",
    "auth",
}

# 严格白名单固定失败分类与脱敏摘要，绝不记录原始异常、完整 URL 或查询参数
VALID_FAILURE_CATEGORIES = {
    "NAVIGATION_TIMEOUT": "页面导航超时",
    "NETWORK_TIMEOUT": "网络请求超时未响应",
    "INVALID_ORIGIN": "非官方微信域名或未知重定向",
    "PAGE_UNREADY": "正向视频发布控件未就绪",
    "DOM_ERROR": "DOM探针或操作异常",
    "LOGIN_REQUIRED": "检测到登录页或登录二维码",
    "REUSE_VERIFICATION_FAILED": "独立新上下文复用验证失败",
    "STORAGE_FAILED": "会话凭证持久化写入失败",
    "BUSY_LOCK": "会话锁被其他进程占用",
    "UNKNOWN": "未分类运行时异常",
}


def _validate_timestamp(ts: Any) -> float | None:
    if ts is None:
        return None
    try:
        val = float(ts)
        if not math.isfinite(val):
            return None
        # 限制在合法时间戳范围 (2020-01-01 至 2050-01-01)
        if 1_577_836_800.0 <= val <= 2_524_608_000.0:
            return val
    except (TypeError, ValueError):
        pass
    return None


def _categorize_failure_summary(error_type: str) -> str:
    """按固定白名单分类输出脱敏摘要，严禁返回任意自由文本或 URL。"""
    raw = str(error_type or "").strip()
    if raw in VALID_FAILURE_CATEGORIES.values():
        return raw
    clean_type = raw.upper()
    return VALID_FAILURE_CATEGORIES.get(clean_type, VALID_FAILURE_CATEGORIES["UNKNOWN"])


def canonical_wechat_auth_state_path(state_path: str | Path) -> Path:
    """从会话文件路径唯一派生绑定的结构化授权状态元数据文件路径。

    使用完整文件名（含扩展名）进行派生，例如：
    output/wechat_state.json -> output/wechat_state.json.auth_state.json
    output/wechat.json       -> output/wechat.json.auth_state.json
    output/wechat.tmp        -> output/wechat.tmp.auth_state.json
    杜绝不同名/不同扩展名会话文件的元数据命名冲突。
    """
    state_file = Path(state_path).expanduser().resolve(strict=False)
    meta_name = f"{state_file.name}.auth_state.json"
    return state_file.with_name(meta_name)


@contextlib.contextmanager
def _auth_state_lock(auth_path: Path):
    """跨进程与跨线程的元数据读改写独占锁。"""
    lock_file = auth_path.with_name(f"{auth_path.name}.lock")
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_file), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)


def is_wechat_state_target(state_path: str | Path) -> bool:
    """判定是否为系统标准生产微信会话文件。

    必须严格核验规范化后的绝对路径与 settings.project_root / "output" / "wechat_state.json" 完全一致。
    杜绝仅按文件名匹配导致的自定义目录同名测试状态被误判为生产会话，
    进而污染生产遗留 marker 或清除运行中 flags。
    """
    try:
        prod_target = (settings.project_root / "output" / "wechat_state.json").resolve(strict=False)
        target = Path(state_path).expanduser().resolve(strict=False)
        return target == prod_target
    except Exception:
        return False


def read_wechat_auth_state(state_path: str | Path) -> dict[str, Any]:
    """读取绑定的微信授权结构化状态。

    若结构化文件不存在，尝试从遗留的 wechat_login_at.txt 读取授权时间作为回退，
    但不伪造最近验证时间。严格核验绑定的 canonical state 身份。
    """
    state_file = Path(state_path).expanduser().resolve(strict=False)
    canonical_state_path_str = str(state_file)
    auth_path = canonical_wechat_auth_state_path(state_file)

    # 候选读取路径：优先完整文件名派生；向后兼容旧版 stem 派生及历史文件
    candidate_paths = [auth_path]
    stem_meta = state_file.with_name(f"{state_file.stem}.auth_state.json")
    if stem_meta not in candidate_paths:
        candidate_paths.append(stem_meta)
    if is_wechat_state_target(state_file):
        legacy_meta = state_file.with_name("wechat_auth_state.json")
        if legacy_meta not in candidate_paths:
            candidate_paths.append(legacy_meta)

    for p in candidate_paths:
        if p.is_file():
            try:
                content = p.read_text(encoding="utf-8")
                data = json.loads(content)
                if isinstance(data, dict):
                    recorded_canon = data.get("canonical_state_path")
                    # 严格校验：读入没有 canonical 身份或身份不匹配时，不能默认为通过
                    if not recorded_canon or str(recorded_canon).strip() != canonical_state_path_str:
                        logger.warning(
                            "Auth state file %s recorded identity %r does not match requested %s, ignoring.",
                            p, recorded_canon, canonical_state_path_str,
                        )
                        continue

                    method = str(data.get("auth_method") or "")
                    last_status = str(data.get("last_keepalive_status") or "")
                    last_fail = data.get("last_failure")
                    clean_fail = None
                    if isinstance(last_fail, dict):
                        f_ts = _validate_timestamp(last_fail.get("timestamp"))
                        f_stage = str(last_fail.get("stage") or "unknown")[:32]
                        f_type = str(last_fail.get("error_type") or "UNKNOWN")[:32]
                        valid_err = f_type if f_type in VALID_KEEPALIVE_STATUSES else "UNKNOWN"
                        clean_fail = {
                            "timestamp": f_ts,
                            "stage": f_stage if f_stage in VALID_STAGES else "unknown",
                            "error_type": valid_err,
                            "summary": _categorize_failure_summary(valid_err),
                        }

                    att_method = str(data.get("last_auth_attempt_method") or "")
                    att_status = str(data.get("last_auth_attempt_status") or "")

                    return {
                        "version": str(data.get("version", AUTH_STATE_VERSION)),
                        "canonical_state_path": canonical_state_path_str,
                        "state_file": state_file.name,
                        "authorized_at": _validate_timestamp(data.get("authorized_at")),
                        "auth_method": method if method in VALID_AUTH_METHODS else None,
                        "last_verified_at": _validate_timestamp(data.get("last_verified_at")),
                        "last_keepalive_at": _validate_timestamp(data.get("last_keepalive_at")),
                        "last_keepalive_status": last_status if last_status in VALID_KEEPALIVE_STATUSES else None,
                        "next_keepalive_scheduled_at": _validate_timestamp(data.get("next_keepalive_scheduled_at")),
                        "last_auth_attempt_at": _validate_timestamp(data.get("last_auth_attempt_at")),
                        "last_auth_attempt_method": att_method if att_method in VALID_AUTH_METHODS else None,
                        "last_auth_attempt_status": att_status if att_status in {"SUCCESS", "FAILED"} else None,
                        "last_auth_attempt_reason": (
                            (
                                str(data.get("last_auth_attempt_reason")).upper()
                                if str(data.get("last_auth_attempt_reason")).upper() in VALID_FAILURE_CATEGORIES
                                else {v: k for k, v in VALID_FAILURE_CATEGORIES.items()}.get(str(data.get("last_auth_attempt_reason")), "UNKNOWN")
                            )
                            if data.get("last_auth_attempt_reason") and att_status == "FAILED"
                            else None
                        ),
                        "last_failure": clean_fail,
                        "updated_at": str(data.get("updated_at") or ""),
                    }
            except (OSError, ValueError, TypeError) as exc:
                logger.warning("Failed to read structured auth state from %s: %s", p, exc)

    # 兼容回退：仅当 state_file 为系统标准生产会话时，才从同目录读取 wechat_login_at.txt
    legacy_auth_ts = None
    if is_wechat_state_target(state_file):
        legacy_file = state_file.parent / "wechat_login_at.txt"
        if legacy_file.is_file():
            try:
                raw = legacy_file.read_text(encoding="utf-8").strip()
                if raw:
                    legacy_auth_ts = _validate_timestamp(float(raw))
            except (OSError, ValueError):
                legacy_auth_ts = None

    return {
        "version": AUTH_STATE_VERSION,
        "canonical_state_path": canonical_state_path_str,
        "state_file": state_file.name,
        "authorized_at": legacy_auth_ts,
        "auth_method": "legacy" if legacy_auth_ts is not None else None,
        "last_verified_at": None,
        "last_keepalive_at": None,
        "last_keepalive_status": None,
        "next_keepalive_scheduled_at": None,
        "last_auth_attempt_at": legacy_auth_ts,
        "last_auth_attempt_method": "legacy" if legacy_auth_ts is not None else None,
        "last_auth_attempt_status": "SUCCESS" if legacy_auth_ts is not None else None,
        "last_auth_attempt_reason": None,
        "last_failure": None,
        "updated_at": (
            datetime.fromtimestamp(legacy_auth_ts, tz=timezone.utc).isoformat()
            if legacy_auth_ts is not None
            else None
        ),
    }


def _write_auth_state_atomic(auth_path: Path, data: dict[str, Any]) -> None:
    """原子写入结构化状态文件（写入临时文件后执行 POSIX replace）。"""
    auth_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = auth_path.with_name(f".{auth_path.name}.tmp.{os.getpid()}.{time.time_ns()}")
    try:
        content = json.dumps(data, ensure_ascii=False, indent=2)
        tmp_path.write_text(content, encoding="utf-8")
        os.replace(tmp_path, auth_path)
    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


def record_wechat_authorization(
    state_path: str | Path,
    *,
    method: str = "auto",
    timestamp: float | None = None,
) -> dict[str, Any]:
    """记录一次真实的重新授权/登录成功事件。

    仅在真实扫码或桌面快捷授权成功且通过全新独立上下文复用验证后调用。
    更新 authorized_at、last_verified_at 与 last_auth_attempt_*，清除失败记录。
    绝不伪造或篡改 last_keepalive_at 与 last_keepalive_status。
    使用文件锁保护并发读改写。
    """
    state_file = Path(state_path).expanduser().resolve(strict=False)
    auth_path = canonical_wechat_auth_state_path(state_file)
    now_ts = float(timestamp if timestamp is not None else time.time())
    if not math.isfinite(now_ts):
        raise ValueError(f"Invalid timestamp: {timestamp}")

    valid_method = method if method in VALID_AUTH_METHODS else "auto"

    with _auth_state_lock(auth_path):
        existing = read_wechat_auth_state(state_file)
        record = {
            "version": AUTH_STATE_VERSION,
            "canonical_state_path": str(state_file),
            "state_file": state_file.name,
            "authorized_at": now_ts,
            "auth_method": valid_method,
            "last_verified_at": now_ts,
            "last_keepalive_at": existing.get("last_keepalive_at"),
            "last_keepalive_status": existing.get("last_keepalive_status"),
            "next_keepalive_scheduled_at": existing.get("next_keepalive_scheduled_at"),
            "last_auth_attempt_at": now_ts,
            "last_auth_attempt_method": valid_method,
            "last_auth_attempt_status": "SUCCESS",
            "last_auth_attempt_reason": None,
            "last_failure": None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        _write_auth_state_atomic(auth_path, record)

    # 仅当目标文件为系统生产配置的 state_file 时，才同步更新遗留 marker 与 flags
    if is_wechat_state_target(state_file):
        legacy_file = state_file.parent / "wechat_login_at.txt"
        try:
            legacy_file.write_text(str(int(now_ts)), encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to update legacy login marker %s: %s", legacy_file, exc)

        for flag_name in ("wechat_auto_relogin_started.flag", "wechat_login_warned.flag"):
            flag_path = state_file.parent / flag_name
            try:
                flag_path.unlink(missing_ok=True)
            except OSError:
                pass

    return record


def record_wechat_auth_attempt(
    state_path: str | Path,
    *,
    method: str = "auto",
    success: bool,
    reason: str | None = None,
    timestamp: float | None = None,
) -> dict[str, Any]:
    """记录一次微信授权尝试的执行证据（涵盖成功与失败）。

    失败后可查最近自动授权尝试证据，白名单固定分类，绝不泄露敏感载荷或 URL 查询。
    使用文件锁保护并发读改写。
    """
    state_file = Path(state_path).expanduser().resolve(strict=False)
    auth_path = canonical_wechat_auth_state_path(state_file)
    now_ts = float(timestamp if timestamp is not None else time.time())
    if not math.isfinite(now_ts):
        raise ValueError(f"Invalid timestamp: {timestamp}")

    valid_method = method if method in VALID_AUTH_METHODS else "auto"
    status = "SUCCESS" if success else "FAILED"
    clean_reason = None
    if not success:
        raw_key = str(reason or "UNKNOWN").upper().strip()
        inv_cat = {v: k for k, v in VALID_FAILURE_CATEGORIES.items()}
        if raw_key in VALID_FAILURE_CATEGORIES:
            clean_reason = raw_key
        elif reason in inv_cat:
            clean_reason = inv_cat[reason]
        else:
            clean_reason = "UNKNOWN"

    with _auth_state_lock(auth_path):
        existing = read_wechat_auth_state(state_file)
        record = {
            **existing,
            "version": AUTH_STATE_VERSION,
            "canonical_state_path": str(state_file),
            "state_file": state_file.name,
            "last_auth_attempt_at": now_ts,
            "last_auth_attempt_method": valid_method,
            "last_auth_attempt_status": status,
            "last_auth_attempt_reason": clean_reason,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        _write_auth_state_atomic(auth_path, record)
    return record


def record_wechat_keepalive_schedule(
    state_path: str | Path,
    scheduled_at: float,
) -> dict[str, Any]:
    """持久化记录下一次实际随机选定的计划保活时刻。使用文件锁保护并发读改写。"""
    state_file = Path(state_path).expanduser().resolve(strict=False)
    auth_path = canonical_wechat_auth_state_path(state_file)
    valid_ts = _validate_timestamp(scheduled_at)
    if valid_ts is None:
        raise ValueError(f"Invalid scheduled_at timestamp: {scheduled_at}")

    with _auth_state_lock(auth_path):
        existing = read_wechat_auth_state(state_file)
        record = {
            **existing,
            "next_keepalive_scheduled_at": valid_ts,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        _write_auth_state_atomic(auth_path, record)
    return record


def record_wechat_keepalive_result(
    state_path: str | Path,
    *,
    status: str,
    failure: dict[str, Any] | None = None,
    timestamp: float | None = None,
) -> dict[str, Any]:
    """记录保活执行结果。

    保活成功只更新 last_verified_at 与 last_keepalive_status，绝不伪造或覆盖 authorized_at。
    若失败，记录固定白名单失败证据（阶段、分类、脱敏摘要）。
    使用文件锁保护并发读改写。
    """
    state_file = Path(state_path).expanduser().resolve(strict=False)
    auth_path = canonical_wechat_auth_state_path(state_file)
    now_ts = float(timestamp if timestamp is not None else time.time())
    if not math.isfinite(now_ts):
        raise ValueError(f"Invalid timestamp: {timestamp}")

    valid_status = status if status in VALID_KEEPALIVE_STATUSES else "UNKNOWN"

    clean_failure = None
    if failure and valid_status != "SUCCESS":
        raw_stage = str(failure.get("stage", "keepalive"))
        stage = raw_stage if raw_stage in VALID_STAGES else "unknown"
        raw_type = str(failure.get("error_type", valid_status))
        error_type = raw_type if raw_type in VALID_KEEPALIVE_STATUSES else valid_status
        clean_failure = {
            "timestamp": now_ts,
            "stage": stage,
            "error_type": error_type,
            "summary": _categorize_failure_summary(error_type),
        }

    with _auth_state_lock(auth_path):
        existing = read_wechat_auth_state(state_file)
        record = {
            "version": AUTH_STATE_VERSION,
            "canonical_state_path": str(state_file),
            "state_file": state_file.name,
            "authorized_at": existing.get("authorized_at"),
            "auth_method": existing.get("auth_method"),
            "last_verified_at": now_ts if valid_status == "SUCCESS" else existing.get("last_verified_at"),
            "last_keepalive_at": now_ts,
            "last_keepalive_status": valid_status,
            "next_keepalive_scheduled_at": existing.get("next_keepalive_scheduled_at"),
            "last_auth_attempt_at": existing.get("last_auth_attempt_at"),
            "last_auth_attempt_method": existing.get("last_auth_attempt_method"),
            "last_auth_attempt_status": existing.get("last_auth_attempt_status"),
            "last_auth_attempt_reason": existing.get("last_auth_attempt_reason"),
            "last_failure": clean_failure if clean_failure else (None if valid_status == "SUCCESS" else existing.get("last_failure")),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        _write_auth_state_atomic(auth_path, record)

    return record


def _format_relative_age(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}秒前"
    if seconds < 3600:
        return f"{int(seconds // 60)}分钟前"
    hours = seconds / 3600.0
    if hours < 48:
        return f"{int(hours)}小时前"
    return f"{int(hours // 24)}天前"


def evaluate_wechat_session_status(
    auth_state: dict[str, Any],
    state_file_exists: bool,
    lock_owner: dict[str, Any] | None = None,
    now_ts: float | None = None,
    warn_hours: float | None = None,
    enable_auto_relogin: bool | None = None,
    enable_keepalive: bool | None = None,
    keepalive_min_interval: int | None = None,
    keepalive_max_interval: int | None = None,
    keepalive_interval_minutes: int | None = None,
    auto_relogin_started: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    """根据结构化状态与配置评定当前状态与建议。

    纯领域逻辑，不调用外部网络，不发起浏览器动作，不调用模型。
    """
    now = float(now_ts if now_ts is not None else time.time())
    threshold_h = float(warn_hours if warn_hours is not None else settings.wechat_session_warn_hours)
    auto_relogin_enabled = (
        enable_auto_relogin if enable_auto_relogin is not None
        else getattr(settings, "wechat_auto_relogin_enabled", False)
    )
    keepalive_enabled = (
        enable_keepalive if enable_keepalive is not None
        else getattr(settings, "wechat_keepalive_enabled", False)
    )
    ka_min_interval = int(
        keepalive_min_interval if keepalive_min_interval is not None
        else (keepalive_interval_minutes if keepalive_interval_minutes is not None
              else getattr(settings, "wechat_keepalive_min_interval", 50))
    )
    ka_max_interval = int(
        keepalive_max_interval if keepalive_max_interval is not None
        else getattr(settings, "wechat_keepalive_max_interval", 65)
    )

    authorized_at = auth_state.get("authorized_at")
    last_verified_at = auth_state.get("last_verified_at")
    last_status = auth_state.get("last_keepalive_status")
    last_failure = auth_state.get("last_failure")
    auth_method = auth_state.get("auth_method")
    last_keepalive_at = auth_state.get("last_keepalive_at")
    next_ka_ts = auth_state.get("next_keepalive_scheduled_at")
    last_att_at = auth_state.get("last_auth_attempt_at")
    last_att_status = auth_state.get("last_auth_attempt_status")
    last_att_reason = auth_state.get("last_auth_attempt_reason")

    # 未来时间戳严格检测：绝不 clamp age=0 后报绿色
    is_future_auth = bool(authorized_at is not None and authorized_at > (now + 60.0))
    is_future_verified = bool(last_verified_at is not None and last_verified_at > (now + 60.0))

    # 状态链时序区分：区分历史保活失败与更新的授权/复用成功
    # 若在最近一次保活之后，发生过更新的成功授权或独立复用验证 (last_verified_at > last_keepalive_at)，
    # 则历史保活失败状态（如 LOGIN_REQUIRED / NETWORK_TIMEOUT）已被新验证覆盖，不再作为当前失效判据。
    is_keepalive_superseded = False
    if last_verified_at is not None:
        if last_keepalive_at is None:
            is_keepalive_superseded = True
        elif last_verified_at > last_keepalive_at:
            is_keepalive_superseded = True

    active_keepalive_status = None if is_keepalive_superseded else last_status

    summary: dict[str, Any] = {
        "authorized_at": authorized_at,
        "auth_method": auth_method,
        "auth_method_label": {
            "desktop_quick": "桌面快捷",
            "scan_qr": "扫码登录",
            "legacy": "历史记录",
            "auto": "自动重登",
        }.get(str(auth_method), str(auth_method or "")),
        "last_verified_at": last_verified_at,
        "last_keepalive_at": last_keepalive_at,
        "last_keepalive_status": last_status,
        "active_keepalive_status": active_keepalive_status,
        "is_keepalive_superseded": is_keepalive_superseded,
        "last_auth_attempt_at": last_att_at,
        "last_auth_attempt_status": last_att_status,
        "last_auth_attempt_reason": last_att_reason,
        "warn_hours": threshold_h,
        "enable_auto_relogin": auto_relogin_enabled,
        "enable_keepalive": keepalive_enabled,
        "auto_relogin_started": auto_relogin_started,
    }

    # 1. 授权时间格式化
    if is_future_auth:
        summary["login_time_bj"] = "时间戳异常（超前系统时钟）"
        summary["relative_age"] = "时间戳异常（未来时间）"
        summary["auth_age_hours"] = None
        summary["hours_to_threshold"] = None
        summary["threshold_reached"] = False
    elif authorized_at is not None:
        dt_auth = datetime.fromtimestamp(authorized_at, tz=BJ_TZ)
        summary["login_time_bj"] = dt_auth.strftime("%Y-%m-%d %H:%M:%S") + " BJ"
        age_seconds = now - authorized_at
        summary["relative_age"] = _format_relative_age(max(0.0, age_seconds))
        auth_age_hours = age_seconds / 3600.0
        summary["auth_age_hours"] = auth_age_hours
        hours_to_threshold = max(0.0, threshold_h - auth_age_hours)
        summary["hours_to_threshold"] = hours_to_threshold
        summary["threshold_reached"] = bool(auth_age_hours >= threshold_h)
    else:
        summary["login_time_bj"] = "无授权记录"
        summary["relative_age"] = "无记录"
        summary["auth_age_hours"] = None
        summary["hours_to_threshold"] = None
        summary["threshold_reached"] = False

    # 2. 最近验证时间格式化
    verified_age_seconds: float | None = None
    if is_future_verified:
        summary["last_verified_bj"] = "时间戳异常（超前系统时钟）"
        summary["relative_verified_age"] = "时间戳异常（未来时间）"
    elif last_verified_at is not None:
        dt_ver = datetime.fromtimestamp(last_verified_at, tz=BJ_TZ)
        summary["last_verified_bj"] = dt_ver.strftime("%Y-%m-%d %H:%M:%S") + " BJ"
        verified_age_seconds = now - last_verified_at
        summary["relative_verified_age"] = _format_relative_age(max(0.0, verified_age_seconds))
    else:
        summary["last_verified_bj"] = "未验证"
        summary["relative_verified_age"] = "无成功保活记录"

    # 3. 最近失败格式化
    if last_failure:
        fail_ts = last_failure.get("timestamp")
        fail_bj = (
            datetime.fromtimestamp(fail_ts, tz=BJ_TZ).strftime("%m-%d %H:%M:%S")
            if fail_ts
            else "未知时间"
        )
        summary["last_failure_display"] = (
            f"{fail_bj} · {last_failure.get('error_type', 'FAIL')} "
            f"({last_failure.get('summary', '')})"
        )
    else:
        summary["last_failure_display"] = None

    # 3.1 最近授权尝试展示
    if last_att_status == "FAILED" and last_att_at is not None:
        att_bj = datetime.fromtimestamp(last_att_at, tz=BJ_TZ).strftime("%m-%d %H:%M:%S")
        reason_desc = _categorize_failure_summary(last_att_reason) if last_att_reason else "未分类"
        summary["last_auth_attempt_display"] = f"{att_bj} · 授权尝试失败 ({reason_desc})"
    elif last_att_status == "SUCCESS" and last_att_at is not None:
        att_bj = datetime.fromtimestamp(last_att_at, tz=BJ_TZ).strftime("%m-%d %H:%M:%S")
        summary["last_auth_attempt_display"] = f"{att_bj} · 授权尝试成功"
    else:
        summary["last_auth_attempt_display"] = None

    # 4. 锁状态
    if lock_owner:
        pid = lock_owner.get("pid", "?")
        stage = lock_owner.get("stage", "操作中")
        summary["lock_status"] = f"占用中 (PID {pid} · {stage})"
    else:
        summary["lock_status"] = "空闲"

    # 5. 调度估算与开关状态（涵盖实际开关、下次计划检查/授权时刻及锁延迟）
    if not auto_relogin_enabled:
        summary["schedule_estimate"] = "自动重登未开启 (wechat_auto_relogin_enabled=false)，需手动执行 /wechat_login"
    elif auto_relogin_started:
        summary["schedule_estimate"] = "自动重登近期已触发，结果以最近授权记录为准"
    elif summary["threshold_reached"]:
        if lock_owner:
            summary["schedule_estimate"] = f"已达 {threshold_h:.1f}h 调度阈值（会话锁被 PID {lock_owner.get('pid')} 占用，等待空闲）"
        else:
            summary["schedule_estimate"] = f"已达 {threshold_h:.1f}h 调度阈值（等待看门狗调度自动重登）"
    elif authorized_at is not None and not is_future_auth:
        rem = summary["hours_to_threshold"]
        target_ts = authorized_at + threshold_h * 3600
        target_dt = datetime.fromtimestamp(target_ts, tz=BJ_TZ)
        target_str = target_dt.strftime("%m-%d %H:%M") + " BJ"
        summary["schedule_estimate"] = f"计划重登：约 {target_str}（距 {threshold_h:.1f}h 阈值约 {rem:.1f} 小时，调度估算）"
    else:
        summary["schedule_estimate"] = "未启动重登调度（无有效授权时间记录）"

    # 6. 下次保活计划（必须持久化实际随机选定时间，而非伪造平均分钟）
    if not keepalive_enabled:
        summary["next_keepalive_estimate"] = "自动保活未开启 (wechat_keepalive_enabled=false)"
    elif next_ka_ts is not None:
        if next_ka_ts > now:
            next_ka_dt = datetime.fromtimestamp(next_ka_ts, tz=BJ_TZ)
            summary["next_keepalive_estimate"] = f"约 {next_ka_dt.strftime('%H:%M')} BJ（实际计划时刻）"
        else:
            summary["next_keepalive_estimate"] = "计划时刻已到（等待看门狗空闲周期执行）"
    elif last_keepalive_at is not None:
        summary["next_keepalive_estimate"] = f"未排期（配置周期 {ka_min_interval}~{ka_max_interval} 分钟）"
    else:
        summary["next_keepalive_estimate"] = f"待首次调度（配置周期 {ka_min_interval}~{ka_max_interval} 分钟）"

    # 7. 严谨状态评定与建议
    suggestions: list[str] = []
    if not state_file_exists:
        status_label = "❌ 凭证文件缺失"
        suggestions.append("会话文件缺失，建议发送 /wechat_login 重新登录保存。")
    elif is_future_auth or is_future_verified:
        status_label = "❌ 时间戳异常（未来时间戳）"
        suggestions.append("检测到时间戳超前当前系统时钟，可能系统时钟异常或数据损坏，禁止报正常。")
    elif active_keepalive_status == "INVALID_ORIGIN":
        status_label = "❌ 来源异常（非官方域名）"
        suggestions.append("最近一次检查检测到非官方微信域名重定向，可能存在网络劫持或代理配置错误。")
    elif active_keepalive_status == "LOGIN_REQUIRED":
        status_label = "❌ 会话已失效（需重新登录）"
        suggestions.append("平台已要求重新扫码登录，请发送 /wechat_login 获取二维码扫码。")
    elif active_keepalive_status == "REUSE_VERIFICATION_FAILED":
        status_label = "❌ 会话复用验证失败"
        suggestions.append("独立全新上下文无法复用会话凭证，请执行 /wechat_login 重新授权。")
    elif active_keepalive_status == "NETWORK_TIMEOUT":
        status_label = "⚠️ 检查失败（网络超时）"
        suggestions.append("最近一次检查网络超时，平台真实状态未知，等待下一轮重试或手动验证。")
    elif active_keepalive_status in ("PAGE_UNREADY", "DOM_ERROR"):
        status_label = f"⚠️ 检查未就绪（{active_keepalive_status}）"
        suggestions.append("最近一次检查未检测到正向发布控件，等待下一轮重试。")
    elif active_keepalive_status == "STORAGE_FAILED":
        status_label = "⚠️ 存储刷新失败"
        suggestions.append("会话刷新写入失败，等待下一轮重试。")
    elif active_keepalive_status == "UNKNOWN":
        status_label = "⚠️ 状态未知（检查未分类）"
        suggestions.append("最近一次检查状态未归类，未取得正向证据，平台真实状态未知。")
    elif last_verified_at is None:
        if authorized_at is not None:
            status_label = "⚠️ 未经验证（待保活验证）"
            suggestions.append("已有历史授权记录，但尚未通过正向保活验证，等待看门狗运行。")
        else:
            status_label = "❌ 未授权"
            suggestions.append("尚未检测到有效登录记录，请发送 /wechat_login 启动登录。")
    elif verified_age_seconds is not None and verified_age_seconds > 4 * 3600:
        status_label = "⚠️ 验证已陈旧（超期未验证）"
        suggestions.append("距离上次成功验证已超过 4 小时，保活可能未按时执行，建议检查看门狗。")
    elif authorized_at is None:
        status_label = "🟡 会话已验证（授权时间未知）"
        suggestions.append("会话凭证有效且近期已验证，但缺失初始授权时间戳，建议在空闲时重新登录补齐。")
    elif summary["threshold_reached"]:
        status_label = "🟡 已达重登阈值"
        if auto_relogin_enabled:
            suggestions.append(f"授权已满 {threshold_h:.1f} 小时重登阈值，系统将在看门狗空闲周期自动启动重登，或发送 /wechat_login 手动重登。")
        else:
            suggestions.append(f"授权已满 {threshold_h:.1f} 小时重登阈值，自动重登未开启，请发送 /wechat_login 手动重登。")
    elif summary["hours_to_threshold"] is not None and summary["hours_to_threshold"] <= 3.0:
        status_label = "⚠️ 临近重登阈值"
        suggestions.append(f"距离 {threshold_h:.1f} 小时重登阈值不足 3 小时，建议关注或发送 /wechat_login 提前续期。")
    else:
        status_label = "✅ 授权且已验证"
        suggestions.append("当前在授权维护期内且已通过正向验证，系统将按计划定期保活。")

    summary["status_label"] = status_label
    summary["suggestions"] = suggestions
    return summary
