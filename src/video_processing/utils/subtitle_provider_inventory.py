"""旧供应商缓存的只读预算盘点；processor → inventory → provider/纯校验工具。

不实例化恢复状态，不创建目录/账本，不调用模型，不删除拒绝缓存。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-29 | Codex | Google/Codex 已有缓存逐批验证后扣减成本，保留 Codex 旧累计终态。 |
"""
import hashlib
import json
import math
from pathlib import Path
import time


def google_inventory(root, texts, target_lang, seconds_per_row):
    from .generated_content_validation import is_upstream_error_response
    from .subtitle_content_contract import is_translation_placeholder
    identity = json.dumps(['google-v2', 'auto', target_lang, texts], ensure_ascii=False)
    path = Path(root) / (hashlib.sha256(identity.encode()).hexdigest() + '.json')
    try:
        rows = json.loads(path.read_text())
        if not isinstance(rows, list) or len(rows) != len(texts):
            raise ValueError('invalid aligned cache')
        cached = sum(isinstance(value, str) and bool(value.strip()) and not is_upstream_error_response(value)
                     and not is_translation_placeholder(value)
                     and not any(marker in value.lower() for marker in
                                 ('<html', 'cloudflare', 'captcha', 'attention required')) for value in rows)
    except (OSError, ValueError, TypeError):
        cached = 0
    return dict(cached_batches=cached, remaining_batches=len(texts) - cached,
                estimated_seconds=(len(texts) - cached) * seconds_per_row,
                cost_basis='cold_start_estimate')


def codex_inventory(root, texts, context, *, model, effort, batch_size, seconds_per_batch,
                    binding=None, include_candidate=False):
    from jsonschema import Draft202012Validator, ValidationError
    from .codex_subtitle_provider import (_batch_prompt, _schema, _validate_batch,
                                         MAX_SUBTITLE_BATCH_ROWS, subtitle_cache_contract)
    from .codex_text_provider import strict_schema, CodexTextError
    from .subtitle_recovery_state import RECOVERY_RECIPE
    effective = min(batch_size, MAX_SUBTITLE_BATCH_ROWS)
    recipe = [RECOVERY_RECIPE, effective, 2, 'parent-first-rejection-to-singletons']
    identity = json.dumps([texts, context, model, effort, recipe], ensure_ascii=False, sort_keys=True)
    key = hashlib.sha256(identity.encode()).hexdigest()
    try:
        state = json.loads((Path(root) / 'subtitle-recovery' / (key + '.json')).read_text())
        if state.get('identity') != key or state.get('recipe') != RECOVERY_RECIPE:
            raise ValueError('invalid recovery identity')
        splits = state['split_batches']
        if (not isinstance(splits, dict)
                or type(state['requests_used']) is not int or state['requests_used'] < 0
                or type(state['max_requests']) is not int or state['max_requests'] <= 0
                or not math.isfinite(state['elapsed_seconds']) or state['elapsed_seconds'] < 0
                or not math.isfinite(state['total_timeout']) or state['total_timeout'] <= 0):
            raise ValueError('invalid split state')
        elapsed = state['elapsed_seconds']
        active = state.get('active_window')
        if active:
            if (not math.isfinite(active['started_at']) or active['started_at'] < 0
                    or not math.isfinite(active['allowance_seconds']) or active['allowance_seconds'] < 0):
                raise ValueError('invalid active budget window')
            elapsed += min(max(0.0, time.time() - active['started_at']), active['allowance_seconds'])
        exhausted = (elapsed >= state['total_timeout']
                     or state['requests_used'] >= state['max_requests'])
    except FileNotFoundError:
        state, splits, exhausted = {}, {}, False
    except (OSError, ValueError, KeyError, TypeError):
        state, splits, exhausted = {}, {}, True

    def cached(batch, offset, singleton=False):
        next_source = texts[offset + len(batch)] if offset + len(batch) < len(texts) else ''
        prompt = _batch_prompt(batch, offset, '' if singleton else context, next_source)
        schema = strict_schema(_schema(len(batch)))
        parts = ['codex-text-v1', model, effort, prompt, schema, [],
                 subtitle_cache_contract(singleton_repair=singleton, binding=binding)]
        signature = hashlib.sha256(json.dumps(parts, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        try:
            payload = json.loads((Path(root) / (signature + '.json')).read_text())['payload']
            Draft202012Validator(schema).validate(payload)
            return _validate_batch(payload, batch, offset, context, next_source_text=next_source)
        except (OSError, ValueError, KeyError, TypeError, ValidationError, CodexTextError):
            return None
    remaining, accepted, parts = 0, 0, []
    for offset in range(0, len(texts), effective):
        batch = texts[offset:offset + effective]
        if f'{offset}:{len(batch)}' in splits and len(batch) > 1:
            children = [cached([source], index, True) for index, source in enumerate(batch, start=offset)]
            accepted += sum(child is not None for child in children)
            remaining += sum(child is None for child in children)
            parts.extend(child for child in children if child is not None)
        else:
            part = cached(batch, offset)
            if part is None:
                remaining += 1
            else:
                accepted += 1
                parts.append(part)
    result = dict(cached_batches=accepted, remaining_batches=remaining,
                estimated_seconds=(max(86400.0, remaining * seconds_per_batch)
                                   if exhausted and remaining else remaining * seconds_per_batch),
                cost_basis='cold_start_estimate', budget_exhausted=bool(exhausted and remaining))
    if include_candidate:
        from .subtitle_translation_provider import SubtitleTranslationCandidate
        result['candidate'] = (SubtitleTranslationCandidate(provider='codex', model=model,
            translations=[text for part in parts for text in part['translations']],
            vocabs=[vocab for part in parts for vocab in part['vocabs']], supports_vocab=True)
            if texts and remaining == 0 else None)
    return result


def cached_codex_candidate(root, texts, context, *, model, effort, batch_size, binding):
    """只读完整新绑定缓存；不收缩旧计划期限，也不给缺批提供执行机会。"""
    return codex_inventory(root, texts, context, model=model, effort=effort, batch_size=batch_size,
        seconds_per_batch=0.0, binding=binding, include_candidate=True)['candidate']
