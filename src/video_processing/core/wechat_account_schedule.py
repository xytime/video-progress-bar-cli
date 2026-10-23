"""账户统一排队策略；状态由 RequestGuard 在同一文件锁内持久保存。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| queue-preflight-v1 | 2026-10-24 | Codex | 新候选参与既有发布优先排序，预检不再被待冷却互动饿死。 |
| recovery-console-v1 | 2026-10-23 | Codex | 统一只读准入、额度重置基线及单次恢复优先级，保留访问历史。 |
| interaction-recovery-v1 | 2026-10-23 | Codex | 冷却期间保留排队顺序，覆盖半小时回帖周期并避免首评饥饿。 |
| 1.1.0 | 2026-10-22 | Antigravity | 支持单次跳过冷却凭据 bypass_cooldown 跳过访问间隔与排队等待，同时保留防重复提交与优先任务保护。 |
| 1.0.0 | 2026-10-21 | Codex | 关闭历史回查，统一恢复期/稳定期预算、优先任务和有界新投稿核对。 |
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from config.settings import settings

DAY = 86400


def task_identity(task):
    """发布路径与人工 ID 共用身份，成片变体不会绕过去重或自阻塞。"""
    stem = Path(task).stem if str(task).endswith(".mp4") else str(task)
    for suffix in ("_vertical_interactive", "_vertical", "_vocab", "_insight"):
        if stem.endswith(suffix):
            return stem[:-len(suffix)]
    return stem


def evaluate(row, now, purpose="发布", task="", *, bypass_cooldown=False, account_only=False):
    """页面、调度和最终上传共同使用的纯准入计算；不排队、不消耗预算。"""
    state = row.get("schedule", {})
    actual = sorted((s for s in state.get("sessions", []) if s["at"] > now - DAY), key=lambda s: s["at"])
    epoch = state.get("quota_epoch", "legacy")
    sessions = [s for s in actual if s.get("quota_epoch", "legacy") == epoch]
    interval_sessions = [s for s in actual if s["at"] > state.get("interval_reset_at", 0)]
    recovery = state.get("recovery_started")
    recovering = bool(row.get("last_limited_at")) and (recovery is None or now < recovery + DAY)
    interval = (settings.wechat_scheduler_recovery_interval_seconds if recovering
                else settings.wechat_scheduler_stable_interval_seconds)
    limit = settings.wechat_scheduler_recovery_limit if recovering else settings.wechat_scheduler_daily_limit
    blockers = []

    def block(code, reason, until=None):
        blockers.append({"code": code, "reason": reason, "until": until})

    if not bypass_cooldown:
        if row.get("blocked_until", 0) > now:
            block("PLATFORM_BACKOFF", "视频号返回限流，本地退避中", row["blocked_until"])
        if row.get("next_session_at", 0) > now:
            block("SESSION_INTERVAL", "账号会话最小间隔未到", row["next_session_at"])
    if settings.wechat_account_scheduler_enabled:
        if purpose == "状态核对":
            block("READBACK_DISABLED", "发布后自动查询已停用；由用户手工确认")
        if purpose == "保活":
            block("KEEPALIVE_DISABLED", "固定登录保活已停用")
        if not account_only and not task:
            block("TASK_REQUIRED", "缺少具体待办身份，不允许空探测")
        priority = settings.wechat_scheduler_priority_video
        if priority and not state.get("priority_bound") and task_identity(task) != task_identity(priority):
            block("RESERVED_PRIORITY", "加拿大增强版保留首次访问机会，其他任务等待")
        if not account_only and purpose == "发布" and any(task_identity(t) == task_identity(task)
                for t in [*state.get("submit_intents", {}), *(p.get("task", "") for p in state.get("publications", {}).values())]):
            block("SUBMISSION_PROTECTED", "此任务已记录提交意图或原生回执，禁止再次上传；等待用户手工确认")
        if not bypass_cooldown:
            if purpose not in {"发布", "状态核对", "登录"}:
                last = state.get("last_interaction_at")
                if last is not None and now < last + 21600:
                    block("INTERACTION_INTERVAL", "评论和回复共用六小时间隔，本轮不访问", last + 21600)
            if recovering and purpose not in {"发布", "状态核对"}:
                block("RECOVERY_PURPOSE", "恢复期仅允许投稿，登录探测、评论和回复继续等待",
                      recovery + DAY if recovery is not None else None)
            if interval_sessions and now < interval_sessions[-1]["at"] + interval:
                block("ACCOUNT_INTERVAL", "全账号访问间隔未到", interval_sessions[-1]["at"] + interval)
            if len(sessions) >= limit:
                block("QUOTA_24H", "全账号过去24小时访问额度已用完", sessions[-limit]["at"] + DAY)
            if not account_only and task:
                queue = [q for q in state.get("queue", []) if q["seen"] > now - (2700 if q["purpose"] == "回复" else 600)]
                priority_tasks = list(dict.fromkeys(task_identity(p["task"]) for p in state.get("recovery_priority", []) if p["expires_at"] > now))
                if priority_tasks and task_identity(task) != priority_tasks[0]:
                    block("RECOVERY_RESERVED", "所选恢复任务已保留下一次机会，等待该项启动或许可到期",
                          min(p["expires_at"] for p in state.get("recovery_priority", []) if p["expires_at"] > now))
                def rank(q):
                    identity = task_identity(q["task"])
                    return (identity not in priority_tasks,
                            priority_tasks.index(identity) if identity in priority_tasks else 0,
                            q["purpose"] not in {"发布", "状态核对"}, q["at"])
                if queue and task_identity(min(queue, key=rank)["task"]) != task_identity(task):
                    # 新候选同样参与既有排序，避免待冷却互动挡住尚未登记的发布。
                    if rank({"task": task, "purpose": purpose, "at": now}) >= rank(min(queue, key=rank)):
                        block("QUEUE_ORDER", "其他已排队任务在前，本轮只等待，不打开后台")
    untils = [b["until"] for b in blockers if b["until"] is not None]
    return {"allowed": not blockers, "blockers": blockers,
            "until": None if any(b["until"] is None for b in blockers) else max(untils, default=now),
            "sessions_24h_count": len(sessions), "actual_sessions_24h_count": len(actual),
            "daily_limit": limit, "interval_seconds": interval, "recovering": recovering,
            "quota_reset_at": state.get("quota_reset_at"), "recent_sessions": actual[-8:]}


def admission(row, now, purpose, task, *, consume=False, bypass_cooldown=False):
    """返回拒绝原因；即使未准入也保存排队次序，纯本地检查不消耗额度。"""
    state = row.setdefault("schedule", {"queue": [], "sessions": [], "publications": {}})
    initial = evaluate(row, now, purpose, task, bypass_cooldown=bypass_cooldown)
    hard = {"READBACK_DISABLED", "KEEPALIVE_DISABLED", "TASK_REQUIRED", "RESERVED_PRIORITY", "SUBMISSION_PROTECTED"}
    if any(b["code"] in hard for b in initial["blockers"]):
        return next(b["reason"] for b in initial["blockers"] if b["code"] in hard)
    sessions = state["sessions"] = [s for s in state["sessions"] if s["at"] > now - DAY]
    queue = state["queue"] = [q for q in state["queue"]
                              if q["seen"] > now - (2700 if q["purpose"] == "回复" else 600)]
    key = hashlib.sha256((purpose + '\n' + task).encode()).hexdigest()
    found = next((q for q in queue if q["key"] == key), None)
    if found:
        found["seen"] = now
    else:
        queue.append({"key": key, "purpose": purpose, "task": task, "at": now, "seen": now})
    info = evaluate(row, now, purpose, task, bypass_cooldown=bypass_cooldown)
    if info["blockers"]:
        first = info["blockers"][0]
        return first["reason"] + (f"，最早 {first['until']:.0f}" if first["until"] else "")
    if consume:
        queue[:] = [q for q in queue if q["key"] != key]
        state["recovery_priority"] = [p for p in state.get("recovery_priority", []) if task_identity(p["task"]) != task_identity(task) and p["expires_at"] > now]
        sessions.append({"at": now, "purpose": purpose, "task": task,
                         "quota_epoch": state.get("quota_epoch", "legacy")})
        if info["recovering"] and state.get("recovery_started") is None:
            state["recovery_started"] = now
        if purpose == "状态核对":
            state["publications"][task]["checks"] = attempts + 1
        elif purpose not in {"发布", "登录"}:
            state["last_interaction_at"] = now
        row["next_session_at"] = max(row["next_session_at"], now + info["interval_seconds"])
    return ""
