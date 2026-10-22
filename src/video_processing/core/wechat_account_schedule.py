"""账户统一排队策略；状态由 RequestGuard 在同一文件锁内持久保存。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| interaction-recovery-v1 | 2026-10-23 | Codex | 冷却期间保留排队顺序，覆盖半小时回帖周期并避免首评饥饿。 |
| 1.1.0 | 2026-10-22 | Antigravity | 支持单次跳过冷却凭据 bypass_cooldown 跳过访问间隔与排队等待，同时保留防重复提交与优先任务保护。 |
| 1.0.0 | 2026-10-21 | Codex | 关闭历史回查，统一恢复期/稳定期预算、优先任务和有界新投稿核对。 |
"""
from __future__ import annotations

import hashlib
from config.settings import settings

DAY = 86400


def admission(row, now, purpose, task, *, consume=False, bypass_cooldown=False):
    """返回拒绝原因；即使未准入也保存排队次序，纯本地检查不消耗额度。"""
    state = row.setdefault("schedule", {"queue": [], "sessions": [], "publications": {}})
    sessions = state["sessions"] = [s for s in state["sessions"] if s["at"] > now - DAY]
    queue = state["queue"] = [q for q in state["queue"]
                              if q["seen"] > now - (2700 if q["purpose"] == "回复" else 600)]
    priority = settings.wechat_scheduler_priority_video
    if priority and not state.get("priority_bound") and task != priority:
        return "加拿大增强版保留首次访问机会，其他任务等待"
    if purpose == "发布" and (task in state.get("submit_intents", {}) or
            any(p["task"] == task for p in state["publications"].values())):
        return "此任务已记录提交意图或原生回执，禁止再次上传；只能核对原生 ID"
    if purpose == "保活":
        # 不凭固定时钟开后台；有真实待办时由该业务会话检查登录即可。
        return "固定登录保活已停用；由实际待办复用登录态"
    if purpose == "状态核对":
        publication = state["publications"].get(task)
        if not publication:
            return "旧作品自动查询已关闭；没有本次新投稿的原生 ID 绑定"
        if publication.get("state") == "PUBLISHED":
            return "已确认公开，无需继续查询"
        attempts = publication.get("checks", 0)
        if attempts >= 3 or now > publication["at"] + DAY + 60:
            return "已到核对次数或时间上限，最终状态未核实，停止自动查询"
        due = publication["at"] + (3600, 21600, DAY)[attempts]
        if now < due:
            return f"新投稿核对尚未到时间，最早 {due:.0f}"
    if not task:
        return "缺少具体待办身份，不允许空探测"
    key = hashlib.sha256((purpose + '\n' + task).encode()).hexdigest()
    found = next((q for q in queue if q["key"] == key), None)
    if found:
        found["seen"] = now
    else:
        queue.append({"key": key, "purpose": purpose, "task": task, "at": now, "seen": now})
    # 冷却期间也维护等待次序；半小时回复 cron 不会被分钟级首评 worker 永久抢先。
    if purpose not in {"发布", "状态核对", "登录"}:
        # 所有评论/回复适配器共用一个六小时窗口，不按脚本分别计数。
        last = state.get("last_interaction_at")
        if last is not None and now < last + 21600 and not bypass_cooldown:
            return "评论和回复共用六小时间隔，本轮不访问"
    if not task:
        return "缺少具体待办身份，不允许空探测"
    recovery = state.get("recovery_started")
    recovering = (bool(row.get("last_limited_at")) and
                  (recovery is None or now < recovery + DAY))
    if recovering and purpose not in {"发布", "状态核对"} and not bypass_cooldown:
        return "恢复期仅允许投稿或绑定回执核对，登录探测、评论和回复继续等待"
    interval = (settings.wechat_scheduler_recovery_interval_seconds if recovering
                else settings.wechat_scheduler_stable_interval_seconds)
    limit = (settings.wechat_scheduler_recovery_limit if recovering
             else settings.wechat_scheduler_daily_limit)
    if not bypass_cooldown:
        if sessions and now < sessions[-1]["at"] + interval:
            return f"全账号访问间隔未到，最早 {sessions[-1]['at'] + interval:.0f}"
        if len(sessions) >= limit:
            return f"全账号过去24小时访问额度已用完，最早 {sessions[-limit]['at'] + DAY:.0f}"
    # 投稿/回执优先；回复保留 45 分钟等待，覆盖 30 分钟 cron，其他任务十分钟失效。
    queue.sort(key=lambda q: (q["purpose"] not in {"发布", "状态核对"}, q["at"]))
    if queue[0]["key"] != key and not bypass_cooldown:
        return "其他已排队任务在前，本轮只等待，不打开后台"
    if consume:
        if bypass_cooldown:
            queue[:] = [q for q in queue if q["key"] != key]
        else:
            queue.pop(0)
        sessions.append({"at": now, "purpose": purpose, "task": task})
        if recovering and recovery is None:
            state["recovery_started"] = now
        if purpose == "状态核对":
            state["publications"][task]["checks"] = attempts + 1
        elif purpose not in {"发布", "登录"}:
            state["last_interaction_at"] = now
        row["next_session_at"] = max(row["next_session_at"], now + interval)
    return ""
