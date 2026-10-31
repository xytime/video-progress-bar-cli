"""以原候选的现有供应商修复有限问题段；不重译整片或重置恢复账。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-01 | Codex | Gemini 沿用共享期限隔离翻译问题段，保留非目标正文及词注。 |
"""
from dataclasses import replace
import logging
import time

from .subtitle_translation_provider import SubtitleTranslationCandidate
from .vocab_helper import extract_vocab_batch

LOG = logging.getLogger(__name__)


def repair_with_gemini(candidate, texts, context, targets, *, deadline):
    if (candidate.provider.lower() != 'gemini' or candidate.contract_error_for(len(texts))
            or not targets or len(targets) > 10
            or any(type(n) is not int or not 1 <= n <= len(texts) for n in targets)
            or len(set(targets)) != len(targets)
            or deadline is None or time.monotonic() >= deadline):
        return None
    models = []
    try:
        rows = extract_vocab_batch([texts[n - 1] for n in targets], context_text=context,
                                   model_out=models, deadline=deadline, context_is_authoritative=False)
    except Exception as exc:
        LOG.warning('Gemini 定点修复未完成: %s', type(exc).__name__)
        return None
    if (not isinstance(rows, list) or len(rows) != len(targets)
            or any(not isinstance(row, dict) for row in rows) or time.monotonic() >= deadline):
        return None
    partial = SubtitleTranslationCandidate('Gemini', [row.get('translation') for row in rows])
    if partial.contract_error_for(len(targets)):
        return None
    translations = list(candidate.translations)
    fields = {'vocabs': 'vocab', 'vocab_phonetics': 'vocab_phonetics',
              'vocab_pos': 'vocab_pos', 'vocab_levels': 'vocab_levels'}
    fields = {field: key for field, key in fields.items() if hasattr(candidate, field)}
    metadata = {field: [dict(values[i]) if i < len(values) and isinstance(values[i], dict) else {}
                        for i in range(len(texts))]
                for field in fields for values in [getattr(candidate, field)]}
    for number, row in zip(targets, rows):
        translations[number - 1] = row['translation']
        for field, key in fields.items():
            metadata[field][number - 1] = row.get(key) if isinstance(row.get(key), dict) else {}
    entry = dict(strategy='isolated_source_repair', executed=True, provider='Gemini',
                 model=','.join(models), segment_numbers=list(targets))
    return replace(candidate, translations=translations, **metadata,
                   repair_history=[*candidate.repair_history, entry])
