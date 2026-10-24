"""等待参数契约；不推断平台每日额度或恢复时刻。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-10-24 | Codex | 明确未提交的商品清理预算超时可有界重新核验；身份冲突仍闭锁。 |
"""
DEFAULT_WAIT_POLICY = dict(base_seconds=300, max_seconds=21600, max_checks=8, lease_seconds=120)
RECHECKABLE_CLEANUP_TIMEOUT = 'PRODUCT_CLEANUP_BUDGET_EXHAUSTED'
WAIT_REASONS = {'PRODUCT_UNAVAILABLE', 'QUOTA_EXHAUSTED', 'LOGIN_REQUIRED', 'AVAILABILITY_UNVERIFIED',
                RECHECKABLE_CLEANUP_TIMEOUT}


def validate_wait_policy(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULT_WAIT_POLICY):
        raise ValueError('等待检查参数不完整')
    if any(type(v) is not int for v in value.values()):
        raise ValueError('等待检查参数必须为整数')
    if not 60 <= value['base_seconds'] <= value['max_seconds'] <= 86400:
        raise ValueError('检查间隔须在60秒到86400秒之间，且上限不小于初始间隔')
    if not 1 <= value['max_checks'] <= 30 or not 30 <= value['lease_seconds'] <= 600:
        raise ValueError('最大检查次数须为1到30次，检查租期须为30到600秒')
    return dict(value)

