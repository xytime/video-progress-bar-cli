"""按认证证据排期；纯计算不打开浏览器、不消耗账户额度。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-25 | Codex | 两小时闲置保活、持久退避和明确的额度等待 |
"""
from __future__ import annotations


def demand_plan(auth, now, idle_seconds=7200, admission=None):
    """既有证据决定到期时间；进程重启不会缩短退避或追加探测。"""
    verified = auth.get("last_verified_at") or 0
    attempted = auth.get("last_keepalive_attempt_at") or 0
    if verified > now + 60 or attempted > now + 60:
        return {"due": False, "at": now + idle_seconds, "reason": "CLOCK_INVALID"}
    due = verified + idle_seconds if verified else now
    reason = "RECENT_VERIFIED" if due > now else None
    if attempted >= verified:
        retry_at = auth.get("keepalive_retry_at") or 0
        if retry_at > due:
            due, reason = retry_at, "FAILURE_BACKOFF"
    if admission is not None and not admission["allowed"]:
        codes = {b["code"] for b in admission.get("blockers", [])}
        reason = "BUDGET_WAIT" if any("LIMIT" in code for code in codes) else "ACCOUNT_WAIT"
        # 无法计算解除时间的硬门禁只做本地巡检，不启动浏览器。
        due = max(due, admission.get("until") or now + 300)
        return {"due": False, "at": due, "reason": reason}
    return {"due": due <= now, "at": max(now, due), "reason": reason if due > now else None}


def failure_delay(attempt_count):
    """15/30/60/120 分钟，失败或崩溃后保持有界退避。"""
    return min(7200, 900 * 2 ** min(3, max(0, attempt_count - 1)))
