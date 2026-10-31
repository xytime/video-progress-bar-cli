"""有界问题段修复的全片保真及真实执行证据。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-01 | Codex | 验证隔离上下文、原期限、全片段号和失败不伪造修复。 |
"""
from copy import deepcopy
from dataclasses import dataclass, field
import time

import pytest

from video_processing.utils import subtitle_targeted_repair as module
from video_processing.utils.subtitle_translation_provider import SubtitleTranslationCandidate
from video_processing.utils.vocab_helper import _build_prompt


def original():
    return SubtitleTranslationCandidate('Gemini', ['普通文本。', '价格。', '末句。'],
        vocabs=[{'text': '文本'}, {}, {}],
        supports_vocab=True)


def test_real_targeted_request_preserves_other_rows_metadata_and_shared_deadline(monkeypatch):
    candidate = original()
    before = deepcopy(candidate)
    deadline = time.monotonic() + 60
    calls = []
    def translate(texts, **kwargs):
        calls.append((texts, kwargs))
        kwargs['model_out'].append('existing-free-model')
        return [dict(translation='价格是115美元。', vocab={})]
    monkeypatch.setattr(module, 'extract_vocab_batch', translate)
    result = module.repair_with_gemini(candidate, ['Some text.', 'The price is $115.', 'End.'],
                                       'Untrusted background', [2], deadline=deadline)
    assert calls[0][0] == ['The price is $115.']
    assert calls[0][1]['deadline'] == deadline
    assert calls[0][1]['context_is_authoritative'] is False
    assert result.translations == ['普通文本。', '价格是115美元。', '末句。']
    assert result.vocabs[0] == candidate.vocabs[0]
    assert result.repair_history[-1]['segment_numbers'] == [2]
    assert result.repair_history[-1]['executed'] is True
    assert candidate == before


def test_optional_metadata_is_preserved_when_present(monkeypatch):
    @dataclass(frozen=True)
    class RichCandidate(SubtitleTranslationCandidate):
        vocab_levels: list = field(default_factory=list)

    candidate = RichCandidate('Gemini', ['文本。', '价格。', '末句。'],
                             vocab_levels=[{'text': 3}, {}, {'end': 2}])
    monkeypatch.setattr(module, 'extract_vocab_batch', lambda *args, **kwargs:
                        [dict(translation='价格115美元。', vocab_levels={'price': 1})])
    result = module.repair_with_gemini(candidate, ['Text', 'Price $115', 'End'], '', [2],
                                     deadline=time.monotonic() + 60)
    assert result.vocab_levels == [{'text': 3}, {'price': 1}, {'end': 2}]


@pytest.mark.parametrize('rows', [None, [], [{}], [dict(translation='承接上文')],
                                  [dict(translation='')], [dict(translation='译文。')] * 2])
def test_missing_or_invalid_response_has_no_repair_evidence(monkeypatch, rows):
    candidate = original()
    monkeypatch.setattr(module, 'extract_vocab_batch', lambda *args, **kwargs: rows)
    assert module.repair_with_gemini(candidate, ['Text', 'Price', 'End'], '', [2],
                                     deadline=time.monotonic() + 60) is None
    assert not candidate.repair_history


def test_expired_budget_does_not_issue_request(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail('expired repair issued a request')
    monkeypatch.setattr(module, 'extract_vocab_batch', unexpected)
    assert module.repair_with_gemini(original(), ['A', 'B', 'C'], '', [2],
                                     deadline=time.monotonic() - 1) is None


def test_repair_prompt_keeps_each_sources_authority():
    prompt = _build_prompt(['The price is $115.'], None, 'billions in other segment',
                           context_is_authoritative=False)
    assert "Each segment's own source text is authoritative" in prompt
    assert 'global context is more authoritative' not in prompt
    assert 'never import facts' in prompt
