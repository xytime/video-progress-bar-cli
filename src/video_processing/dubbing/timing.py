"""MiniMax 配音时长闭环策略。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-29 | Codex | 建立语速重合成、微调、留白与人工改写阻断策略 |
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class TimingDecision:
    """单个语义片段的最终对齐决策。"""

    strategy: str
    post_tempo: float
    pad_ms: int
    requires_rewrite: bool


def next_synthesis_speed(current_speed: float, actual_ms: int, target_ms: int, *, minimum: float, maximum: float) -> float:
    """按实测时长闭环计算下一次 MiniMax 语速，并限制在可理解区间。"""
    if target_ms <= 0 or actual_ms <= 0:
        raise ValueError("actual_ms and target_ms must be positive")
    return max(minimum, min(maximum, current_speed * actual_ms / target_ms))


def decide_timing(actual_ms: int, target_ms: int) -> TimingDecision:
    """只允许有限后处理，避免把短句拖慢或把长句压成不可理解的快读。"""
    if target_ms <= 0 or actual_ms <= 0:
        raise ValueError("actual_ms and target_ms must be positive")
    ratio = actual_ms / target_ms
    if 0.96 <= ratio <= 1.04:
        return TimingDecision("micro_tempo", ratio, 0, False)
    if ratio < 0.96:
        return TimingDecision("natural_pause", 1.0, target_ms - actual_ms, False)
    if ratio <= 1.12:
        return TimingDecision("bounded_tempo", ratio, 0, False)
    return TimingDecision("needs_rewrite", 1.0, 0, True)
