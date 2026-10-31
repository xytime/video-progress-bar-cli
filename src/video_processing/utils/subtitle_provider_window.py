"""字幕候选的供应商时间份额；共享整片期限，并预留兜底及质量核验时间。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-31 | Codex | 防止前序网络失败耗尽全部翻译预算；不增加总时限或修改质量门。 |
"""
from contextlib import contextmanager
import time


def candidate_deadline(deadline, providers, index, *, now, total_seconds,
                       quality_seconds, fallback_seconds):
    """未使用的份额交给后续候选；Codex 不可用时按剩余供应商公平分配。"""
    if not 0 <= index < len(providers):
        raise ValueError('provider index outside plan')
    remaining = max(0., deadline - now)
    quality = min(float(quality_seconds), float(total_seconds) * .2)
    available = max(0., remaining - quality)
    tail = providers[index:]
    if 'codex' in tail and tail[0] != 'codex':
        reserve = min(float(fallback_seconds), float(total_seconds) * .5)
        seconds = max(0., available - reserve) / tail.index('codex')
    elif tail[0] == 'codex':
        seconds = available
    else:
        seconds = available / len(tail)
    return min(deadline, now + seconds)


@contextmanager
def translation_provider_window(processor, providers, index, config):
    """仅候选请求使用较短期限；异常和成功后都恢复整片质量/修复期限。"""
    overall = processor._translation_deadline
    if not getattr(config, 'subtitle_provider_budget_allocation_enabled', False):
        yield True
        return
    now = time.monotonic()
    processor._translation_deadline = candidate_deadline(
        overall, providers, index, now=now,
        total_seconds=config.subtitle_translation_total_timeout_seconds,
        quality_seconds=config.subtitle_translation_quality_reserve_seconds,
        fallback_seconds=config.subtitle_translation_fallback_reserve_seconds)
    try:
        yield processor._translation_deadline > now
    finally:
        processor._translation_deadline = overall
