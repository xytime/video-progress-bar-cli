"""视频号授权按时长自动快捷重登与告警的纯判定；不打开浏览器、不读写凭据、不消耗账户额度。

授权约 24 小时服务端硬过期。旧逻辑只在“闲置两小时”保活到期后才检查重登，
业务会话持续刷新验证时间时保活永远不到期，导致既不重登也不提醒。
本模块只看授权时间与明确的 LOGIN_REQUIRED 事实，由看门狗每分钟本地调用。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-02 | Grok Bot | 按授权时长触发自动快捷重登（与闲置保活解耦），失败退避/上限，失效与临期去重告警。 |
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape

_BEIJING = timezone(timedelta(hours=8))


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _clock(timestamp):
    return datetime.fromtimestamp(timestamp, _BEIJING).strftime("%m-%d %H:%M")


def login_required(auth) -> bool:
    """当前授权代际已被页面明确判定失效；成功重新授权（authorized_at/last_verified_at 更新）后自然解除。"""
    failed_at = _number(auth.get("last_keepalive_at")) or 0.0
    return (auth.get("last_keepalive_status") == "LOGIN_REQUIRED"
            and (_number(auth.get("last_verified_at")) or 0.0) <= failed_at
            and (_number(auth.get("authorized_at")) or 0.0) <= failed_at)


def relogin_plan(auth, now, *, after_hours, max_failures):
    """返回是否应启动一次自动快捷重登；只依据授权时长、失效事实与既有失败退避。"""
    authorized_at = _number(auth.get("authorized_at"))
    if authorized_at is None:
        # 从未成功授权过：首次登录必须人工完成，不做无凭据的后台尝试。
        return {"due": False, "reason": "NO_AUTHORIZATION", "age_hours": None, "expired": False}
    age_hours = max(0.0, (now - authorized_at) / 3600.0)
    expired = login_required(auth)
    plan = {"age_hours": age_hours, "expired": expired}
    if not expired and age_hours < float(after_hours):
        return {**plan, "due": False, "reason": "FRESH"}
    failures = int(auth.get("relogin_failure_count") or 0)
    if failures >= int(max_failures):
        return {**plan, "due": False, "reason": "FAILURE_CAP", "failures": failures}
    retry_at = _number(auth.get("next_relogin_allowed_at"))
    if retry_at is not None and now < retry_at:
        return {**plan, "due": False, "reason": "FAILURE_BACKOFF", "retry_at": retry_at}
    return {**plan, "due": True, "reason": "EXPIRED" if expired else "PRE_EXPIRY"}


def pending_alerts(auth, now, *, alert_hours, auto_enabled, max_failures):
    """返回 (事件类型, 去重键, HTML 文本)；去重键绑定授权代际，同一代际每类只提醒一次。"""
    authorized_at = _number(auth.get("authorized_at"))
    if authorized_at is None:
        return []
    generation = str(auth.get("credential_generation") or f"{authorized_at:.0f}")
    age_hours = max(0.0, (now - authorized_at) / 3600.0)
    failures = int(auth.get("relogin_failure_count") or 0)
    if auto_enabled and failures < int(max_failures):
        next_step = "系统会自动尝试微信快捷登录（免扫码）；若仍失败会再提醒。"
    else:
        next_step = "自动重登未开启或已达失败上限，请给 Bot 发 <code>/wechat_login</code> 或在控制台点登录。"
    if login_required(auth):
        failed_at = _number(auth.get("last_keepalive_at")) or now
        return [("WECHAT_LOGIN_REQUIRED", f"login-required:{generation}",
                 f"🔴 <b>视频号登录已失效</b>\n"
                 f"授权于北京 {_clock(authorized_at)}，{_clock(failed_at)} 页面返回 LOGIN_REQUIRED（约 {age_hours:.1f}h）。\n"
                 f"视频号发布与互动已暂停等待登录。\n{next_step}")]
    if age_hours >= float(alert_hours):
        expires_at = authorized_at + 24 * 3600
        return [("WECHAT_SESSION_EXPIRING", f"expiring:{generation}",
                 f"🟠 <b>视频号授权临期（约 {age_hours:.1f}h）</b>\n"
                 f"授权于北京 {_clock(authorized_at)}，预计北京 {_clock(expires_at)} 左右失效（约24h，估计）。\n"
                 f"{next_step}")]
    return []


def relogin_failure_alert(auth, *, started_at, returncode, max_failures):
    """自动重登子进程结束但未写入新授权时的告警文本；去重键绑定本次启动时间。"""
    failures = int(auth.get("relogin_failure_count") or 0)
    retry_at = _number(auth.get("next_relogin_allowed_at"))
    reason = escape(str(auth.get("last_auth_attempt_reason") or f"exit={returncode}"))
    if failures >= int(max_failures):
        tail = "已达自动重试上限，停止自动尝试。请给 Bot 发 <code>/wechat_login</code> 或在控制台点登录。"
    elif retry_at is not None:
        tail = f"将于北京 {_clock(retry_at)} 后自动再试一次（第 {failures + 1}/{int(max_failures)} 次）。"
    else:
        tail = "下一轮看门狗巡检会按退避规则再试。"
    return ("WECHAT_AUTO_RELOGIN_FAILED", f"auto-relogin-failed:{started_at:.0f}",
            f"🟠 <b>视频号自动快捷登录未成功</b>\n原因：{reason}\n{tail}")
