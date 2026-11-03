"""字幕候选的供应商时间份额；共享整片期限，并预留兜底及质量核验时间。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| review-fixes-20261103 | 2026-11-03 | Codex | 修复片尾降级、投递口径、字幕预算或复核绑定；保留历史证据。 |
| subtitle-manual-gate-v2 | 2026-11-02 | Codex | CLI 顺序预留可执行窗口，保留整片期限与质量预留。 |
| 1.2.0 | 2026-11-01 | Grok Bot | Codex 排在中间（CLI 优先顺序）时按普通候选公平分配，不再独占剩余期限；Codex 末位兜底行为不变。 |
| 1.1.0 | 2026-11-01 | Codex | 仅按兜底原累计可执行余额预留；未用份额交前序候选，总期限与质量预留不变。 |
| 1.0.0 | 2026-10-31 | Codex | 防止前序网络失败耗尽全部翻译预算；不增加总时限或修改质量门。 |
"""
from contextlib import contextmanager
import time
import math


def candidate_deadline(deadline, providers, index, *, now, total_seconds,
                       quality_seconds, fallback_seconds, fallback_capacity=None, cli_seconds=None):
    """按优先顺序预留 CLI 请求窗口；未使用份额交给后续候选。"""
    if not 0 <= index < len(providers):
        raise ValueError('provider index outside plan')
    remaining = max(0., deadline - now)
    quality = min(float(quality_seconds), float(total_seconds) * .2)
    available = max(0., remaining - quality)
    tail = providers[index:]
    if providers[-1] != 'codex':
        # 保留已验证的 Codex 长请求；Grok 仅保底总预算的 10%，有余时仍可用完整上限。
        # 600s 中质量占 120s，最坏 AGY/Codex/Grok 为 120/300/60；快速失败继续让时。
        caps = dict(agy=120., codex=min(float(fallback_seconds), float(total_seconds) * .5), grok=150.)
        caps.update(cli_seconds or {})
        reserves = caps | {'grok': min(caps['grok'], float(total_seconds) * .1)}
        reserve = sum(reserves.get(provider, 0.) for provider in tail[1:])
        if fallback_capacity is not None and 'codex' in tail[1:]:
            capacity = float(fallback_capacity)
            reserve -= caps['codex'] - min(caps['codex'], max(0., capacity) if math.isfinite(capacity) else 0.)
        seconds = min(caps.get(tail[0], available / len(tail)), max(0., available - reserve))
    elif 'codex' in tail and tail[0] != 'codex':
        reserve = min(float(fallback_seconds), float(total_seconds) * .5)
        if fallback_capacity is not None:
            capacity = float(fallback_capacity)
            reserve = min(reserve, max(0., capacity)) if math.isfinite(capacity) else 0.
        seconds = max(0., available - reserve) / tail.index('codex')
    elif tail[0] == 'codex':
        seconds = available
    else:
        seconds = available / len(tail)
    return min(deadline, now + seconds)


def fallback_capacity_seconds(texts, context, config):
    """缺少预算配置的旧调用维持原行为；关闭份额功能时不读持久状态。"""
    required = ('default_output_dir', 'codex_text_model', 'codex_text_effort',
                'codex_subtitle_batch_size', 'codex_subtitle_total_timeout_seconds',
                'codex_text_request_timeout_seconds', 'subtitle_translation_total_timeout_seconds')
    if (not getattr(config, 'subtitle_provider_budget_allocation_enabled', False)
            or not all(hasattr(config, name) for name in required)):
        return None
    from .codex_subtitle_provider import codex_subtitle_capacity
    return codex_subtitle_capacity(texts, context,
        state_dir=config.default_output_dir / 'codex_text_cache',
        model=config.codex_text_model, effort=config.codex_text_effort,
        batch_size=config.codex_subtitle_batch_size,
        total_timeout=min(config.codex_subtitle_total_timeout_seconds,
                          config.subtitle_translation_total_timeout_seconds),
        request_timeout=config.codex_text_request_timeout_seconds)


@contextmanager
def translation_provider_window(processor, providers, index, config, *, fallback_capacity=None):
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
        fallback_seconds=config.subtitle_translation_fallback_reserve_seconds,
        fallback_capacity=fallback_capacity,
        cli_seconds=dict(agy=getattr(config, 'agy_timeout_sec', 120),
                         grok=getattr(config, 'grok_timeout_sec', 150)))
    try:
        yield processor._translation_deadline > now
    finally:
        processor._translation_deadline = overall


def require_single_video_budget(segment_count, config):
    """保守容量预检：按每批一次完整请求额度规划，不承诺模型会在平均时间内返回。"""
    if not getattr(config, 'subtitle_provider_budget_allocation_enabled', False):
        return
    batch = max(30, min(int(getattr(config, 'codex_subtitle_batch_size', 40)), 50))
    request = float(getattr(config, 'codex_text_request_timeout_seconds', 120))
    available = max(0., float(config.subtitle_translation_total_timeout_seconds)
                    - float(config.subtitle_translation_quality_reserve_seconds))
    required = math.ceil(segment_count / batch) * request
    if required > available:
        from .subtitle_failure_receipt import SubtitleReviewRequired
        raise SubtitleReviewRequired(
            f'片长超出单片预算：{segment_count} 段，保守批次额度 {required:g}s，'
            f'可用 {available:g}s；需人工选择分片方案', code='translation_budget_preflight')
