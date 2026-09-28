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
| 1.0.0   | 2026-09-28 | Antigravity | 初始创建：本地结构化授权/保活状态管理，支持原子更新、白名单过滤及状态报告 |
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from config.settings import settings

logger = logging.getLogger(__name__)

BJ_TZ = ZoneInfo("Asia/Shanghai")
AUTH_STATE_VERSION = "1.0.0"


def canonical_wechat_auth_state_path(state_path: str | Path) -> Path:
    """从会话文件路径派生绑定的结构化授权状态元数据文件路径。

    例如：output/wechat_state.json -> output/wechat_auth_state.json
    """
    state_file = Path(state_path).expanduser().resolve(strict=False)
    stem = state_file.stem
    if stem.endswith("_state"):
        prefix = stem[:-6]
    else:
        prefix = stem
    meta_name = f"{prefix}_auth_state.json" if prefix else "wechat_auth_state.json"
    return state_file.with_name(meta_name)


def read_wechat_auth_state(state_path: str | Path) -> dict[str, Any]:
    """读取绑定的微信授权结构化状态。

    若结构化文件不存在，尝试从遗留的 wechat_login_at.txt 读取授权时间作为回退，
    但不伪造最近验证时间。
    """
    state_file = Path(state_path).expanduser().resolve(strict=False)
    auth_path = canonical_wechat_auth_state_path(state_file)

    if auth_path.is_file():
        try:
            content = auth_path.read_text(encoding="utf-8")
            data = json.loads(content)
            if isinstance(data, dict):
                return {
                    "version": str(data.get("version", AUTH_STATE_VERSION)),
                    "state_file": str(data.get("state_file", state_file.name)),
                    "authorized_at": float(data["authorized_at"]) if data.get("authorized_at") is not None else None,
                    "auth_method": str(data["auth_method"]) if data.get("auth_method") else None,
                    "last_verified_at": float(data["last_verified_at"]) if data.get("last_verified_at") is not None else None,
                    "last_keepalive_at": float(data["last_keepalive_at"]) if data.get("last_keepalive_at") is not None else None,
                    "last_keepalive_status": str(data["last_keepalive_status"]) if data.get("last_keepalive_status") else None,
                    "last_failure": data.get("last_failure") if isinstance(data.get("last_failure"), dict) else None,
                    "updated_at": str(data.get("updated_at") or ""),
                }
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("Failed to read structured auth state from %s: %s", auth_path, exc)

    # 兼容回退：检查同目录下的 wechat_login_at.txt
    legacy_file = state_file.parent / "wechat_login_at.txt"
    legacy_auth_ts = None
    if legacy_file.is_file():
        try:
            raw = legacy_file.read_text(encoding="utf-8").strip()
            if raw:
                legacy_auth_ts = float(int(raw))
        except (OSError, ValueError):
            legacy_auth_ts = None

    return {
        "version": AUTH_STATE_VERSION,
        "state_file": state_file.name,
        "authorized_at": legacy_auth_ts,
        "auth_method": "legacy" if legacy_auth_ts is not None else None,
        "last_verified_at": None,
        "last_keepalive_at": None,
        "last_keepalive_status": None,
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

    仅在真实扫码或桌面快捷授权成功后调用，更新 authorized_at 和 last_verified_at，
    清除失败记录，并清理相关自动重登标记。
    """
    state_file = Path(state_path).expanduser().resolve(strict=False)
    auth_path = canonical_wechat_auth_state_path(state_file)
    now_ts = float(timestamp if timestamp is not None else time.time())

    record = {
        "version": AUTH_STATE_VERSION,
        "state_file": state_file.name,
        "authorized_at": now_ts,
        "auth_method": method,
        "last_verified_at": now_ts,
        "last_keepalive_at": now_ts,
        "last_keepalive_status": "SUCCESS",
        "last_failure": None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    _write_auth_state_atomic(auth_path, record)

    # 同步写入 wechat_login_at.txt 保持外部脚本与旧工具兼容
    legacy_file = state_file.parent / "wechat_login_at.txt"
    try:
        legacy_file.write_text(str(int(now_ts)), encoding="utf-8")
    except OSError as exc:
        logger.warning("Failed to update legacy login marker %s: %s", legacy_file, exc)

    # 授权成功后清理自动重登与临期预警标志
    for flag_name in ("wechat_auto_relogin_started.flag", "wechat_login_warned.flag"):
        flag_path = state_file.parent / flag_name
        try:
            flag_path.unlink(missing_ok=True)
        except OSError:
            pass

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
    若失败，记录白名单失败证据（错误阶段、错误类型、摘要）。
    """
    state_file = Path(state_path).expanduser().resolve(strict=False)
    auth_path = canonical_wechat_auth_state_path(state_file)
    existing = read_wechat_auth_state(state_file)
    now_ts = float(timestamp if timestamp is not None else time.time())

    clean_failure = None
    if failure and status != "SUCCESS":
        clean_failure = {
            "timestamp": now_ts,
            "stage": str(failure.get("stage", "keepalive"))[:64],
            "error_type": str(failure.get("error_type", "UNKNOWN"))[:64],
            "detail": str(failure.get("detail", ""))[:300],
        }

    record = {
        "version": AUTH_STATE_VERSION,
        "state_file": state_file.name,
        "authorized_at": existing.get("authorized_at"),
        "auth_method": existing.get("auth_method"),
        "last_verified_at": now_ts if status == "SUCCESS" else existing.get("last_verified_at"),
        "last_keepalive_at": now_ts,
        "last_keepalive_status": status,
        "last_failure": clean_failure if clean_failure else (None if status == "SUCCESS" else existing.get("last_failure")),
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
) -> dict[str, Any]:
    """根据结构化状态与配置评定当前状态与建议。

    纯领域逻辑，不调用外部网络，不发起浏览器动作，不调用模型。
    """
    now = float(now_ts if now_ts is not None else time.time())
    threshold_h = float(warn_hours if warn_hours is not None else settings.wechat_session_warn_hours)

    authorized_at = auth_state.get("authorized_at")
    last_verified_at = auth_state.get("last_verified_at")
    last_status = auth_state.get("last_keepalive_status")
    last_failure = auth_state.get("last_failure")
    auth_method = auth_state.get("auth_method")

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
        "last_keepalive_at": auth_state.get("last_keepalive_at"),
        "last_keepalive_status": last_status,
        "warn_hours": threshold_h,
    }

    # 1. 授权时间格式化
    if authorized_at is not None:
        dt_auth = datetime.fromtimestamp(authorized_at, tz=BJ_TZ)
        summary["login_time_bj"] = dt_auth.strftime("%Y-%m-%d %H:%M:%S") + " BJ"
        age_seconds = max(0.0, now - authorized_at)
        summary["relative_age"] = _format_relative_age(age_seconds)
        auth_age_hours = age_seconds / 3600.0
        summary["auth_age_hours"] = auth_age_hours
        hours_to_threshold = max(0.0, threshold_h - auth_age_hours)
        summary["hours_to_threshold"] = hours_to_threshold
        threshold_reached = auth_age_hours >= threshold_h
        summary["threshold_reached"] = threshold_reached
    else:
        summary["login_time_bj"] = "无授权记录"
        summary["relative_age"] = "无记录"
        summary["auth_age_hours"] = None
        summary["hours_to_threshold"] = None
        summary["threshold_reached"] = False

    # 2. 最近验证时间格式化
    if last_verified_at is not None:
        dt_ver = datetime.fromtimestamp(last_verified_at, tz=BJ_TZ)
        summary["last_verified_bj"] = dt_ver.strftime("%Y-%m-%d %H:%M:%S") + " BJ"
        ver_age_seconds = max(0.0, now - last_verified_at)
        summary["relative_verified_age"] = _format_relative_age(ver_age_seconds)
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
            f"({last_failure.get('detail', '')})"
        )
    else:
        summary["last_failure_display"] = None

    # 4. 锁状态
    if lock_owner:
        pid = lock_owner.get("pid", "?")
        stage = lock_owner.get("stage", "操作中")
        summary["lock_status"] = f"占用中 (PID {pid} · {stage})"
    else:
        summary["lock_status"] = "空闲"

    # 5. 重登调度估算描述（明确声明为调度估算，不承诺平台真实剩余寿命）
    if summary["auth_age_hours"] is not None:
        rem = summary["hours_to_threshold"]
        if summary["threshold_reached"]:
            summary["schedule_estimate"] = f"已达 {threshold_h:.1f}h 调度阈值（等待空闲周期自动重登）"
        else:
            summary["schedule_estimate"] = f"距 {threshold_h:.1f}h 调度阈值约 {rem:.1f} 小时（调度估算，不代表平台剩余寿命）"
    else:
        summary["schedule_estimate"] = "未启动调度（无有效授权）"

    # 6. 综合状态评定与建议
    suggestions: list[str] = []
    if authorized_at is None:
        status_label = "❌ 未授权"
        suggestions.append("尚未检测到有效登录记录，请发送 /wechat_login 启动登录。")
    elif not state_file_exists:
        status_label = "⚠️ 凭证文件缺失"
        suggestions.append("会话文件缺失，建议发送 /wechat_login 重新保存。")
    elif last_status == "LOGIN_REQUIRED":
        status_label = "❌ 会话已失效（需重新登录）"
        suggestions.append("平台已要求重新扫码登录，请发送 /wechat_login 获取二维码扫码。")
    elif last_status == "NETWORK_TIMEOUT":
        status_label = "⚠️ 检查失败（网络超时）"
        suggestions.append("最近一次保活网络超时，等待下一轮自动保活重试；不影响现有会话。")
    elif last_status in ("PAGE_UNREADY", "UNKNOWN_STATE"):
        status_label = f"⚠️ 检查异常（{last_status}）"
        suggestions.append("最近一次保活未完成正向发布控件验证，等待下一轮重试。")
    elif last_status == "STORAGE_FAILED":
        status_label = "⚠️ 存储刷新失败"
        suggestions.append("会话刷新写入失败，等待下一轮重试。")
    elif summary["threshold_reached"]:
        status_label = "🟡 已达重登阈值"
        suggestions.append(f"授权已满 {threshold_h:.1f} 小时重登阈值，系统将在看门狗空闲周期自动启动重登，或发送 /wechat_login 手动重登。")
    elif summary["hours_to_threshold"] is not None and summary["hours_to_threshold"] <= 3.0:
        status_label = "⚠️ 临近重登阈值"
        suggestions.append(f"距离 {threshold_h:.1f} 小时重登阈值不足 3 小时，建议关注或发送 /wechat_login 提前续期。")
    else:
        status_label = "✅ 授权期内"
        suggestions.append("当前在授权维护期内，系统将按计划定期保活。")

    summary["status_label"] = status_label
    summary["suggestions"] = suggestions
    return summary
