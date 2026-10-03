"""字幕最后兜底的身份、质量、总期限与有限修正。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-03 | Codex | 验证不接收缺段/重复段、虚假词汇和半片结果。 |
"""

from types import SimpleNamespace

import pytest

from video_processing.utils import codex_subtitle_provider as provider
from video_processing.utils.codex_text_provider import CodexTextError, CodexTextResult


def _raw(ids):
    return {"items": [{"id": i, "translation": "企业可以改变", "vocab": [
        {"english": "business", "chinese": "企业"}]} for i in ids]}


@pytest.mark.parametrize("ids", [[0, 0], [1, 0], [True, 1], [0], [0, 2]])
def test_duplicate_missing_reordered_and_boolean_ids_rejected(ids):
    with pytest.raises(provider.CodexSubtitleError, match="subtitle_ids"):
        provider._validate_batch(_raw(ids), ["A business can change."] * 2, 0, "")


def test_vocab_must_match_both_source_and_translation():
    raw = _raw([0]); raw["items"][0]["vocab"][0]["chinese"] = "公司"
    with pytest.raises(provider.CodexSubtitleError, match="vocab_alignment"):
        provider._validate_batch(raw, ["A business can change."], 0, "")


def test_vocab_repair_lists_all_invalid_segments():
    raw = _raw([0, 1])
    for row in raw["items"]:
        row["vocab"][0]["chinese"] = "公司"
    with pytest.raises(provider.CodexSubtitleError, match="subtitle_vocab_alignment_ids_0_1"):
        provider._validate_batch(raw, ["A business can change."] * 2, 0, "")


def test_host_quality_block_cannot_be_cached(monkeypatch):
    issue = SimpleNamespace(code="NUMBER_CHANGED")
    monkeypatch.setattr(provider, "evaluate_subtitle_translation_candidate", lambda *a, **k: SimpleNamespace(blocking_issues=[issue]))
    with pytest.raises(provider.CodexSubtitleError, match="NUMBER_CHANGED"):
        provider._validate_batch(_raw([0]), ["A business can change."], 0, "")


def test_batches_share_deadline_and_never_return_partial_candidate(tmp_path, monkeypatch):
    calls = []
    def run(prompt, **kwargs):
        calls.append(kwargs)
        return CodexTextResult({"translations": ["企业可以改变"], "vocabs": [{}]}, "gpt-5.6-luna", {}, 1)
    ticks = iter([0, 0, 11])
    monkeypatch.setattr(provider, "run_codex_structured", run)
    monkeypatch.setattr(provider.time, "monotonic", lambda: next(ticks))
    with pytest.raises(provider.CodexSubtitleError, match="total_timeout"):
        provider.build_codex_subtitle_candidate(["business"] * 2, "", state_dir=tmp_path, command="codex", batch_size=1, total_timeout=10)
    assert len(calls) == 1 and calls[0]["timeout_sec"] == 10


def test_only_local_output_errors_can_be_repaired_once(tmp_path, monkeypatch):
    calls = []
    def run(prompt, **kwargs):
        calls.append(prompt)
        if len(calls) == 1:
            raise provider.CodexSubtitleError("subtitle_ids")
        payload = kwargs["validate"](_raw([0]))
        return CodexTextResult(payload, "gpt-5.6-luna", {"output_tokens": 20}, 1)
    monkeypatch.setattr(provider, "run_codex_structured", run)
    result = provider.build_codex_subtitle_candidate(["A business can change."], "", state_dir=tmp_path, command="codex")
    assert result.translations == ["企业可以改变"] and result.vocabs == [{"business": "企业"}]
    assert len(calls) == 2 and "一次修正" in calls[1]


def test_quota_is_not_retried(tmp_path, monkeypatch):
    calls = []
    def unavailable(*a, **k):
        calls.append(1)
        raise CodexTextError("quota")
    monkeypatch.setattr(provider, "run_codex_structured", unavailable)
    with pytest.raises(CodexTextError, match="quota"):
        provider.build_codex_subtitle_candidate(["business"], "", state_dir=tmp_path, command="codex")
    assert calls == [1]
