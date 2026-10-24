"""视频号分用途预算；每次准入读取原子配置，坏配置闭锁，不更改业务账本。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| operations-v1 | 2026-10-24 | Codex | 接入用户确认的六类独立滚动预算和有界重试；普通配置只能在批准范围内收紧。 |
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from config.settings import settings


class WeChatRequestDeferred(RuntimeError):
    """本地准入拒绝，调用方不得启动平台请求。"""
    def __init__(self, reason, *, admission=None):
        super().__init__(reason)
        self.admission = admission


class OperationsPolicyError(WeChatRequestDeferred):
    """活动配置无法验证，禁止启动平台流程。"""


from config.wechat_operations_schema import APPROVED, PURPOSES, _pairs, validate


def load_policy(*, fresh=False):
    """启用后缺失/无效配置均报错；没有静默回退旧额度或启动请求。"""
    if not settings.wechat_operations_enabled:
        return None
    try:
        if settings.runtime_configuration_enabled:
            from .runtime_configuration import snapshot
            return validate(snapshot(fresh=fresh).domains()['wechat_operations'])
        data = json.loads(Path(settings.wechat_operations_policy_path).read_text(encoding="utf-8"),
                          object_pairs_hook=_pairs,
                          parse_constant=lambda _v: (_ for _ in ()).throw(ValueError("nonfinite value")))
        return validate(data)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise OperationsPolicyError("视频号分用途配置不可验证，停止平台操作") from exc


def revision(policy):
    return hashlib.sha256(json.dumps(policy, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def retry_policy():
    policy = load_policy()
    return policy["retry_policies"]["write_actions"] if policy else None


def is_retryable_before_intent(detail):
    """仅重试已知未提交的技术故障；身份/内容/权限/限流/未知结果不能进入此分支。"""
    text = str(detail or "").lower()
    if any(token in text for token in ("uncertain", "unknown", "限流", "429", "-360", "login", "权限", "审查", "mismatch")):
        return False
    return any(token in text for token in ("timeout", "timed out", "超时", "targetclosed", "target closed",
                                           "browser closed", "browser has been closed", "connection reset", "connection refused"))


def operation_candidates(session):
    """旧宽用途无法区分时保守预占所有可能池，保留原事件直到自然过期；不猜测、不清零。"""
    if session.get("operation") in APPROVED:
        return {session["operation"]}
    purpose = session.get("purpose")
    if purpose == "登录":
        return set()  # 人工登录沿用专用授权，不占六类业务预算。
    if purpose == "评论":
        return {"first_comment", "comment_scan", "post_match"}
    if purpose == "回复":
        return {"reply", "comment_scan"}
    return {PURPOSES[purpose]} if purpose in PURPOSES else set(APPROVED)
