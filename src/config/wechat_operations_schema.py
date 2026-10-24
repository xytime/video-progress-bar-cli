"""视频号分用途参数的服务端批准边界和严格结构校验。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| runtime-center-v1 | 2026-10-24 | Codex | 迁移原有校验器到配置层，供存储与执行者共用，不放宽边界。 |
"""
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
