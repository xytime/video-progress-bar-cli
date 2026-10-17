"""有界指数退避及保守故障分类；不负责 IO 或执行重试。"""
from __future__ import annotations

import random


def backoff_seconds(attempt: int, *, base: float = 300, cap: float = 3600,
                    random_value: float | None = None, retry_after: float = 0) -> float:
    """第 1 次等待为 base 的 80–100%；后续翻倍，遵守服务端最低等待。"""
    if attempt < 1 or base <= 0 or cap < base or retry_after < 0:
        raise ValueError("invalid retry policy")
    value = random.random() if random_value is None else random_value
    if not 0 <= value <= 1:
        raise ValueError("invalid jitter")
    ceiling = min(cap, base * 2 ** min(attempt - 1, 20))
    return max(retry_after, ceiling * (0.8 + 0.2 * value))


def failure_kind(detail: str) -> str:
    """地区/认证/预算错误不按网络瞬断重试；未知错误需人工查看。"""
    text = detail.lower()
    if any(s in text for s in ("location ineligible", "unauthorized", "invalid api key", "permission denied")):
        return "PROVIDER_BLOCKED"
    if any(s in text for s in ("attempt_budget_exhausted", "review_terminal")):
        return "BUDGET_EXHAUSTED"
    if any(s in text for s in ("timed out", "timeout", "connection reset", "connection refused",
                               "tls handshake eof", "stream disconnected", "network is unreachable",
                               "temporary failure in name resolution", "no capacity", "code 503", "http 429")):
        return "TRANSIENT"
    return "NEEDS_REVIEW"
