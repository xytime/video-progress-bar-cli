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


class OperationsPolicyError(WeChatRequestDeferred):
    """活动配置无法验证，禁止启动平台流程。"""


# 这是本次用户逐项确认的批准边界，不是微信平台规则，也不是客户端可修改的审批凭据。
# 扩大此边界需要新的明确授权与代码审查；紧急版暂不开放后台任意放宽。
APPROVED = {
    "publish": {"rolling_24h_limit": 20, "min_interval_seconds": 180, "retry_policy": "write_actions"},
    "first_comment": {"rolling_24h_limit": 50, "rolling_1h_limit": 10, "min_interval_seconds": 60, "retry_policy": "write_actions"},
    "reply": {"rolling_24h_limit": 1000, "rolling_1h_limit": 50, "min_interval_seconds": 60,
              "max_replies_per_video_lifetime": 20, "retry_policy": "write_actions"},
    "comment_scan": {"rolling_1h_limit": 1, "min_interval_seconds": 3600, "max_videos_per_run": 5},
    "post_match": {"rolling_24h_limit": 12, "same_batch_success_cooldown_seconds": 1800},
    "keepalive": {"rolling_24h_limit": 4},
}
PURPOSES = {"发布": "publish", "首评": "first_comment", "评论": "first_comment", "回复": "reply",
            "评论扫描": "comment_scan", "作品匹配": "post_match", "保活": "keepalive"}


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate configuration key")
        result[key] = value
    return result


def validate(data):
    if not isinstance(data, dict) or set(data) != {"schema_version", "operations", "retry_policies"}:
        raise ValueError("invalid operations configuration keys")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError("invalid operations schema")
    operations = data["operations"]
    if not isinstance(operations, dict) or set(operations) != set(APPROVED):
        raise ValueError("six operation policies required")
    for name, baseline in APPROVED.items():
        value = operations[name]
        if not isinstance(value, dict) or set(value) != set(baseline):
            raise ValueError("invalid operation fields: " + name)
        for key, approved in baseline.items():
            actual = value[key]
            if isinstance(approved, str):
                if actual != approved:
                    raise ValueError("unknown retry profile")
            elif type(actual) is not int or not 1 <= actual <= 604800:
                raise ValueError("positive integer required: " + key)
            elif key.endswith("seconds"):
                if actual < approved:
                    raise ValueError("shorter interval requires new approval: " + key)
            elif actual > approved:
                raise ValueError("higher limit requires new approval: " + key)
        if value.get("rolling_1h_limit", 0) > value.get("rolling_24h_limit", 2147483647):
            raise ValueError("hourly quota exceeds daily quota")
    retries = data["retry_policies"]
    if not isinstance(retries, dict) or set(retries) != {"write_actions"}:
        raise ValueError("invalid retry policies")
    retry = retries["write_actions"]
    if not isinstance(retry, dict) or set(retry) != {"max_retries", "interval_seconds"}:
        raise ValueError("invalid retry fields")
    if type(retry["max_retries"]) is not int or not 0 <= retry["max_retries"] <= 2:
        raise ValueError("retry limit exceeds approved two extra attempts")
    if type(retry["interval_seconds"]) is not int or not 60 <= retry["interval_seconds"] <= 604800:
        raise ValueError("invalid retry interval")
    return data


def load_policy():
    """启用后缺失/无效配置均报错；没有静默回退旧额度或启动请求。"""
    if not settings.wechat_operations_enabled:
        return None
    try:
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
