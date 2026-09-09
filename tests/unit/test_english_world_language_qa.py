"""真实错误形态与失败关闭回归；不调用网络或生产数据库。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-09 | Codex | JSON3 完整词、逐目标审校覆盖及重启缓存测试。 |
"""
from pathlib import Path
import pytest

from video_processing.study_cards.caption_evidence import parse_json3, transcript_differences
from video_processing.study_cards.language_qa import (
    VERSION, atomic_json, cache_key, digest, evaluate, expected_checks, file_digest, read_json, review_input,
)
from video_processing.study_cards.language_review_service import review
from video_processing.utils.agy_provider import AgyProviderError


def test_benchmark_has_independent_sources_and_labeled_coverage():
    corpus = read_json(Path(__file__).parents[1] / "fixtures/english_world_language_benchmark.json")
    clips = corpus["clips"]
    assert len({c["id"] for c in clips}) >= 10
    assert sum(len(c["points"]) for c in clips) >= 50
    assert sum(len(c["errors"]) for c in clips) >= 20
    assert {e["severity"] for c in clips for e in c["errors"]} == {"P0", "P1"}
    for clip in clips:
        for word, pos, meaning in clip["points"]:
            assert word.lower() in clip["text"].lower() and pos and meaning


def test_reviewer_does_not_receive_generator_scores():
    p = plan()
    p["content"]["vocabulary"][0]["confidence"] = 0.99
    assert "confidence" not in str(review_input(p, {}, {}))


def test_publication_fields_need_explicit_coverage():
    p = plan()
    p["publication_text"] = {"title": "阅读", "copy": "阅读练习", "cover_payload": {}}
    assert ("SEMANTIC_CONSISTENCY", "publication:cover_payload") in expected_checks(p)


def test_incremental_publication_shares_budget_and_binds_approved_body(tmp_path, monkeypatch):
    from video_processing.study_cards import publication_qa as module
    timeline, p = setup_review(tmp_path)
    p["content"].update(headline_en="Reading", headline_zh="阅读")
    atomic_json(tmp_path / "display_plan.json", p)
    monkeypatch.setattr(module, "validate_language_qa", lambda _: {"input_key": "base-pass"})
    atomic_json(tmp_path / "task/language_attempts.json", {"attempts": 2, "retries": 0, "keys": ["base", "revision"]})
    publication = {"title": "阅读成绩", "copy": "阅读成绩令人警醒", "cover_payload": {
        "title": "阅读成绩", "quote_en": "The results are sobering.", "quote_zh": "结果令人警醒。",
        "difficulty_tag": "A2–B1", "audio_source": "ABC News", "date_str": "2026.09.09"}}
    _, projected, _ = module.inputs_for(timeline, publication)
    calls = []
    def caller(*a, **k):
        calls.append(1)
        return good(projected)
    kw = dict(cache_dir=tmp_path / "cache", task_dir=tmp_path / "task", model="m", caller=caller)
    report = module.review_publication(timeline, publication, **kw)
    assert report["state"] == "PASS" and report["attempts"] == 3
    assert module.review_publication(timeline, publication, **kw)["cache_hit"]
    assert len(calls) == 1
    assert module.approved_publication(timeline)[0]["title"] == publication["title"]
    with pytest.raises(ValueError, match="最多一次修订"):
        module.review_publication(timeline, {**publication, "title": "另一标题"}, **kw)
    p["content"]["headline_en"] = "Changed"
    atomic_json(tmp_path / "display_plan.json", p)
    with pytest.raises(ValueError): module.approved_publication(timeline)


@pytest.mark.parametrize("message", ["permission", "model not found", "invalid JSON envelope", "quota exhausted"])
def test_terminal_failure_never_falls_back_or_restarts(tmp_path, message):
    timeline, _ = setup_review(tmp_path)
    calls = []
    def caller(*a, **kw):
        calls.append(1)
        raise AgyProviderError(message)
    kw = dict(cache_dir=tmp_path / "cache", task_dir=tmp_path / "task", model="m", caller=caller)
    with pytest.raises(AgyProviderError): review(timeline, **kw)
    with pytest.raises(ValueError): review(timeline, **kw)
    assert len(calls) == 1


def test_invalid_structured_response_is_terminal(tmp_path):
    timeline, _ = setup_review(tmp_path)
    import jsonschema
    with pytest.raises(jsonschema.ValidationError):
        review(timeline, cache_dir=tmp_path / "cache", task_dir=tmp_path / "task", model="m", caller=lambda *a, **k: {})
    assert read_json(tmp_path / "task/language_attempts.json")["terminal"]


def test_same_key_concurrent_requests_are_coalesced(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    timeline, p = setup_review(tmp_path)
    calls = []
    def caller(*a, **k):
        calls.append(1)
        return good(p)
    kw = dict(cache_dir=tmp_path / "cache", task_dir=tmp_path / "task", model="m", caller=caller)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: review(timeline, **kw), range(2)))
    assert len(calls) == 1
    assert sorted(x["cache_hit"] for x in results) == [False, True]


def test_cache_hit_does_not_invalidate_existing_render_report(tmp_path):
    timeline, p = setup_review(tmp_path)
    kw = dict(cache_dir=tmp_path / "cache", task_dir=tmp_path / "task", model="m", caller=lambda *a, **k: good(p))
    review(timeline, **kw)
    previous = file_digest(tmp_path / "qa/language_qa.json")
    assert review(timeline, **kw)["cache_hit"]
    assert file_digest(tmp_path / "qa/language_qa.json") == previous


def test_second_content_failure_cannot_reopen_old_pass(tmp_path):
    timeline, p = setup_review(tmp_path)
    kw = dict(cache_dir=tmp_path / "cache", task_dir=tmp_path / "task", caller=lambda *a, **k: good(p))
    review(timeline, model="first", **kw)
    failure = good(p)
    failure["findings"][0].update(status="FAIL", severity="P1")
    kw["caller"] = lambda *a, **k: failure
    assert review(timeline, model="revision", **kw)["state"] == "FAIL"
    with pytest.raises(ValueError, match="已停止"): review(timeline, model="first", **kw)


def test_one_retry_is_shared_across_revision_and_restart(tmp_path):
    timeline, p = setup_review(tmp_path)
    calls = []
    def caller(*a, **k):
        calls.append(1)
        if len(calls) != 2:
            raise AgyProviderError("timeout")
        return good(p)
    kw = dict(cache_dir=tmp_path / "cache", task_dir=tmp_path / "task", caller=caller)
    assert review(timeline, model="first", **kw)["attempts"] == 2
    with pytest.raises(AgyProviderError): review(timeline, model="revision", **kw)
    with pytest.raises(ValueError): review(timeline, model="revision", **kw)
    assert len(calls) == 3


@pytest.mark.parametrize("changed", ["timeline.json", "display_plan.json", "qa/source_evidence.json", "editorial_changes.json", "source.mp4", "caption.json3"])
def test_gate_rejects_any_changed_bound_artifact(tmp_path, changed):
    from video_processing.study_cards.language_qa import validate_language_qa
    timeline, p = setup_review(tmp_path)
    (tmp_path / "source.mp4").write_bytes(b"media fixture")
    atomic_json(tmp_path / "caption.json3", {"events": []})
    atomic_json(timeline, {"language_contract": VERSION, "source_provenance": {
        "source_video": "source.mp4", "caption_artifact": "caption.json3",
        "source_start_seconds": 0, "source_end_seconds": 1}})
    p["timeline_sha256"] = file_digest(timeline)
    atomic_json(tmp_path / "display_plan.json", p)
    atomic_json(tmp_path / "qa/source_evidence.json", {"source_sha256": file_digest(tmp_path / "source.mp4"),
        "caption_sha256": file_digest(tmp_path / "caption.json3"), "source_start": 0, "source_end": 1})
    review(timeline, cache_dir=tmp_path / "cache", task_dir=tmp_path / "task", model="m", caller=lambda *a, **k: good(p))
    assert validate_language_qa(timeline)["state"] == "PASS"
    target = tmp_path / changed
    if changed.endswith(".mp4"):
        target.write_bytes(b"new media")
    else:
        value = read_json(target)
        value["changed"] = True
        atomic_json(target, value)
    with pytest.raises(ValueError): validate_language_qa(timeline)


def caption(*values):
    return {"events": [{"tStartMs": i * 1000, "dDurationMs": 1000, "segs": [{"utf8": v}]} for i, v in enumerate(values)]}


def test_parser_preserves_ordinals_and_age():
    result = parse_json3(caption("15year-olds", "13th", "27th"), 0, 3)
    assert [w["text"] for w in result["words"]] == ["15-year-olds", "13th", "27th"]
    assert result["changes"][0]["kind"] == "typography"


def test_parser_preserves_currency_decimal_sign_and_percentage():
    result = parse_json3(caption("$76.11", "-14", "2.5%", "1,000"), 0, 4)
    assert [w["text"] for w in result["words"]] == ["$76.11", "-14", "2.5%", "1,000"]


def test_multitoken_segment_requires_alignment_without_loss():
    result = parse_json3(caption("The results are sobering."), 0, 1)
    assert result["english_text"] == "The results are sobering"
    assert result["requires_alignment"] and result["words"] == []


def test_multitoken_alignment_uses_real_asr_times_and_rejects_differences():
    from video_processing.study_cards.caption_evidence import align_json3
    parsed = parse_json3(caption("The results are sobering."), 0, 1)
    observed = [{"word": w, "start": i * .2, "end": i * .2 + .1}
                for i, w in enumerate("The results are sobering".split())]
    aligned = align_json3(parsed, observed)
    assert aligned[1] == {"text": "results", "start": .2, "end": .3}
    observed[-1]["word"] = "sober"
    with pytest.raises(ValueError, match="UNCERTAIN"): align_json3(parsed, observed)


def test_duplicate_event_and_overlapping_end():
    value = caption("one", "two")
    value["events"][0]["dDurationMs"] = 6000
    value["events"].append(value["events"][0])
    result = parse_json3(value, 0, 2)
    assert len(result["words"]) == 2
    assert result["words"][0]["end"] == 1


@pytest.mark.parametrize("a,b", [("not higher", "higher"), ("13th", "30th"), ("nearly 90", "90"), ("15-year-olds", "15")])
def test_diff_never_silently_repairs(a, b):
    assert transcript_differences(a, b)


def plan():
    return {"content": {"paragraphs": [{"english_text": "The results are sobering.", "translation_zh": "结果令人警醒。"}],
                        "vocabulary": [{"item_id": "word:3:1", "word": "sobering", "meaning_zh": "令人警醒的"}]}}


def good(p):
    return {"findings": [{"check": c, "target": t, "status": "PASS", "severity": "NONE",
                           "evidence": "当前句法和上下文一致", "suggestion": ""} for c, t in sorted(expected_checks(p))]}


@pytest.mark.parametrize("status,severity", [("FAIL", "P0"), ("FAIL", "P1"), ("UNCERTAIN", "NONE"), ("PASS", "P1")])
def test_fail_closed(status, severity):
    p = plan(); result = good(p)
    result["findings"][0].update(status=status, severity=severity)
    assert evaluate(result, p) == "FAIL"


def test_missing_duplicate_and_blank_evidence_block():
    p = plan()
    for mode in ("missing", "duplicate", "blank"):
        result = good(p)
        if mode == "missing": result["findings"].pop()
        if mode == "duplicate": result["findings"].append(result["findings"][0])
        if mode == "blank": result["findings"][0]["evidence"] = " "
        with pytest.raises(ValueError): evaluate(result, p)


def test_style_suggestion_is_not_semantic_failure():
    p = plan(); result = good(p)
    result["findings"][0]["severity"] = "P2"
    assert evaluate(result, p) == "PASS"


def setup_review(tmp_path):
    timeline = tmp_path / "timeline.json"
    atomic_json(timeline, {"english_text": "test"})
    p = {**plan(), "timeline_sha256": file_digest(timeline)}
    atomic_json(tmp_path / "display_plan.json", p)
    atomic_json(tmp_path / "qa/source_evidence.json", {"source_sha256": "source"})
    atomic_json(tmp_path / "editorial_changes.json", {"version": VERSION, "revision": 0})
    return timeline, p


def test_cache_restart_and_model_invalidation(tmp_path):
    timeline, p = setup_review(tmp_path)
    calls = []
    def caller(*args, **kwargs):
        calls.append(kwargs["model"])
        return good(p)
    kwargs = dict(cache_dir=tmp_path / "cache", task_dir=tmp_path / "task", caller=caller)
    assert review(timeline, model="model-a", **kwargs)["state"] == "PASS"
    assert review(timeline, model="model-a", **kwargs)["cache_hit"]
    assert review(timeline, model="model-b", **kwargs)["state"] == "PASS"
    assert calls == ["model-a", "model-b"]
    with pytest.raises(ValueError, match="最多一次"):
        review(timeline, model="model-c", **kwargs)


def test_transient_failure_only_retries_once(tmp_path):
    timeline, _ = setup_review(tmp_path)
    calls = []
    def caller(*args, **kwargs):
        calls.append(1)
        raise AgyProviderError("agy timed out")
    kwargs = dict(cache_dir=tmp_path / "cache", task_dir=tmp_path / "task", caller=caller, model="test")
    with pytest.raises(AgyProviderError): review(timeline, **kwargs)
    with pytest.raises(ValueError): review(timeline, **kwargs)
    assert len(calls) == 2


def test_permission_failure_is_terminal(tmp_path):
    timeline, _ = setup_review(tmp_path)
    def caller(*args, **kwargs): raise AgyProviderError("agy exit 1: permission")
    kwargs = dict(cache_dir=tmp_path / "cache", task_dir=tmp_path / "task", caller=caller, model="test")
    with pytest.raises(AgyProviderError): review(timeline, **kwargs)
    assert read_json(tmp_path / "task/language_attempts.json")["attempts"] == 1
    with pytest.raises(ValueError): review(timeline, **kwargs)


def test_path_only_binding_does_not_change_cache():
    a, b = {**plan(), "timeline_sha256": "a"}, {**plan(), "timeline_sha256": "b"}
    assert cache_key(review_input(a, {}, {})) == cache_key(review_input(b, {}, {}))


def test_occurrence_specific_highlight():
    from video_processing.study_cards.models import VocabularyItem
    from video_processing.study_cards.template_a import _highlighted_token_indices
    item = VocabularyItem("key", "关键的", word_index=3, item_id="word:3:1")
    assert not _highlighted_token_indices(["key"], (item,), start_index=0)
    assert _highlighted_token_indices(["key"], (item,), start_index=3)
