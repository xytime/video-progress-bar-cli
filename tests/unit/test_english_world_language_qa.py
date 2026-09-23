"""真实错误形态与失败关闭回归；不调用网络或生产数据库。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.11 | 2026-09-23 | Codex | 验证修订预占、旧回执拒绝和同任务真实预算两轮审校。 |
| 1.0.10 | 2026-09-22 | Codex | 被拒绝的正文及增量输入不改账本，原启动失败仍可具名恢复。 |
| 1.0.9 | 2026-09-22 | Codex | 覆盖显式启动恢复、预检失败不改账本和三次硬上限。 |
| 1.0.0 | 2026-09-09 | Codex | JSON3 完整词、逐目标审校覆盖及重启缓存测试。 |
| 1.0.1 | 2026-09-09 | Codex | 覆盖转录差异逐项裁决、片段任务隔离和词元音标标签。 |
| 1.0.2 | 2026-09-09 | Codex | 覆盖边界跨越 JSON3 片段只能以 ASR 裁决。 |
| 1.0.3 | 2026-09-09 | Codex | 覆盖边界残留、U.S. 与数字年龄 ASR 拆词的受限对齐。 |
| 1.0.4 | 2026-09-09 | Codex | 覆盖零宽 Whisper 时间戳的受限、逐组修复与审校覆盖。 |
| 1.0.5 | 2026-09-10 | Codex | 覆盖带来源的 P1 误报裁决和 P0/非 P1 禁止放行。 |
| 1.0.6 | 2026-09-11 | Codex | 覆盖并列相邻学习点的词典义串线预检。 |
| 1.0.7 | 2026-09-11 | Codex | 覆盖同值数字、连字符拆分和冠词差异的受限来源对齐。 |
| 1.0.8 | 2026-09-14 | Codex | 覆盖时间修复后的真实修订、旧误终止迁移和二次内容失败阻断。 |
"""
from pathlib import Path
import pytest

from video_processing.study_cards.caption_evidence import parse_json3, transcript_differences
from video_processing.study_cards.language_qa import (
    VERSION, apply_adjudications, atomic_json, cache_key, digest, evaluate, expected_checks, file_digest,
    read_json, review_input,
    task_identity,
)
from video_processing.study_cards.language_review_service import review
from video_processing.utils.agy_provider import AgyProviderError


def test_local_dictionary_gate_rejects_adjacent_sense_leakage_before_review():
    from video_processing.study_cards.learning_dictionary import validate_context_meaning_separation

    points = [
        {"word_index": 0, "word": "current", "context_meaning_zh": "当前流行的",
         "dictionary_senses": {"translation": "a. 流通的, 现在的, 当前的, 流行的"}},
        {"word_index": 2, "word": "trendy", "context_meaning_zh": "时下流行的",
         "dictionary_senses": {"translation": "a. 时髦的, 流行的"}},
    ]
    words = [{"text": "current"}, {"text": "and"}, {"text": "trendy"}]

    with pytest.raises(ValueError, match="current.*trendy.*流行"):
        validate_context_meaning_separation(points, words)

    points[0]["context_meaning_zh"] = "当前的"
    assert validate_context_meaning_separation(points, words) is None


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


def test_source_differences_and_editorial_changes_need_individual_findings():
    p = plan()
    evidence = {"caption_differences": [{"kind": "missing_suffix"}],
                "timeline_differences": [{"kind": "ordinal"}]}
    editorial = {"changes": [{"kind": "parser_repair"}]}
    result = good(p)
    with pytest.raises(ValueError, match="覆盖"):
        evaluate(result, p, evidence=evidence, editorial=editorial)
    result = good(p, evidence, editorial)
    assert evaluate(result, p, evidence=evidence, editorial=editorial) == "PASS"
    targets = {(item["check"], item["target"]) for item in result["findings"]}
    assert ("TRANSCRIPT_ACCURACY", "caption_differences:0") in targets
    assert ("TRANSCRIPT_ACCURACY", "timeline_differences:0") in targets
    assert ("SEMANTIC_CONSISTENCY", "editorial_change:0") in targets


def test_zero_width_asr_timing_repair_needs_individual_review_coverage():
    p = plan()
    evidence = {"caption_differences": [], "timeline_differences": [],
                "asr_timing_repairs": [{"kind": "zero_width_asr_anchor"}]}
    result = good(p, evidence=evidence)
    assert ("TRANSCRIPT_ACCURACY", "asr_timing_repair:0") in {
        (item["check"], item["target"]) for item in result["findings"]
    }


def test_task_identity_separates_source_windows_without_path_entropy():
    base = {"source_sha256": "source", "caption_sha256": "caption", "source_start": 7.9, "source_end": 30.0}
    later = {**base, "source_start": 30.0, "source_end": 52.1}
    assert task_identity(base) != task_identity(later)
    assert task_identity(base) == task_identity(dict(base))


@pytest.mark.parametrize("advisory", [False, True])
def test_incremental_publication_shares_budget_and_binds_approved_body(tmp_path, monkeypatch, advisory):
    from video_processing.study_cards import publication_qa as module
    timeline, p = setup_review(tmp_path)
    if advisory:
        from video_processing.study_cards.quality_policy import ADVISORY_POLICY
        p["quality_policy"] = ADVISORY_POLICY
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
        result = good(projected)
        if advisory:
            result["findings"][0].update(status="FAIL", severity="P1")
        return result
    kw = dict(cache_dir=tmp_path / "cache", task_dir=tmp_path / "task", model="m", caller=caller)
    report = module.review_publication(timeline, publication, **kw)
    assert report["state"] == "PASS" and report["attempts"] == 3
    if advisory:
        assert report["review_state"] == "FAIL" and report["quality_warnings"]
    assert module.review_publication(timeline, publication, **kw)["cache_hit"]
    assert len(calls) == 1
    assert module.approved_publication(timeline)[0]["title"] == publication["title"]
    with pytest.raises(ValueError, match="最多一次修订"):
        module.review_publication(timeline, {**publication, "title": "另一标题"}, **kw)
    p["content"]["headline_en"] = "Changed"
    atomic_json(tmp_path / "display_plan.json", p)
    with pytest.raises(ValueError): module.approved_publication(timeline)


def test_cover_lemma_ipa_requires_explicit_phonetic_word(tmp_path, monkeypatch):
    from video_processing.study_cards import publication_qa as module
    timeline, p = setup_review(tmp_path)
    p["content"].update(headline_en="Reading", headline_zh="阅读", vocabulary=[{
        "item_id": "word:2:1", "word": "ranks", "meaning_zh": "排名", "phonetic": "/ræŋk/",
        "phonetic_word": "rank", "level": "CET-4",
    }])
    atomic_json(tmp_path / "display_plan.json", p)
    monkeypatch.setattr(module, "validate_language_qa", lambda _: {"input_key": "base-pass"})
    publication = {"title": "阅读成绩", "copy": "阅读成绩令人警醒", "cover_payload": {
        "title": "阅读成绩", "quote_en": "It ranks 13th.", "quote_zh": "它排在第13位。",
        "difficulty_tag": "A2–B1", "audio_source": "ABC News", "date_str": "2026.09.09",
        "vocab_items": [{"word": "ranks", "meaning": "排名", "ipa": "/ræŋk/",
                         "phonetic_word": "rank", "level": "CET-4"}],
    }}
    assert module.inputs_for(timeline, publication)[1]["publication_text"]["cover_payload"]["vocab_items"]
    publication["cover_payload"]["vocab_items"][0].pop("phonetic_word")
    with pytest.raises(ValueError, match="新增封面词汇"):
        module.inputs_for(timeline, publication)


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


def test_timing_review_does_not_consume_first_content_revision(tmp_path):
    timeline, p = setup_review(tmp_path)
    kw = dict(cache_dir=tmp_path / "cache", task_dir=tmp_path / "task", model="m")
    review(timeline, caller=lambda *a, **k: good(p), **kw)
    p["content"]["words"] = [{"text": "test", "start": 0, "end": .9}]
    atomic_json(tmp_path / "display_plan.json", p)
    bad = good(p)
    bad["findings"][0].update(status="FAIL", severity="P1")
    assert review(timeline, caller=lambda *a, **k: bad, **kw)["state"] == "FAIL"
    ledger_path = tmp_path / "task/language_attempts.json"
    ledger = read_json(ledger_path)
    assert not ledger.get("content_terminal")
    # 模拟已上线旧版本在 PASS -> FAIL 后写下的误终止，不重置任何计数。
    ledger["content_terminal"] = True
    atomic_json(ledger_path, ledger)
    p["content"]["paragraphs"][0]["translation_zh"] = "审校后的完整译文"
    atomic_json(tmp_path / "display_plan.json", p)
    report = review(timeline, caller=lambda *a, **k: good(p), **kw)
    assert report["state"] == "PASS" and report["attempts"] == 3 and report["revision"] == 1
    assert read_json(ledger_path)["budget_migration"]["preserved_attempts"] == 2
    assert review(timeline, caller=lambda *a, **k: pytest.fail("cached revision"), **kw)["cache_hit"]


def test_two_actual_content_failures_remain_terminal(tmp_path):
    timeline, p = setup_review(tmp_path)
    bad = good(p)
    bad["findings"][0].update(status="FAIL", severity="P1")
    kw = dict(cache_dir=tmp_path / "cache", task_dir=tmp_path / "task", caller=lambda *a, **k: bad)
    assert review(timeline, model="first", **kw)["state"] == "FAIL"
    assert review(timeline, model="revision", **kw)["state"] == "FAIL"
    with pytest.raises(ValueError, match="已停止"):
        review(timeline, model="third", **kw)
    assert read_json(tmp_path / "task/language_attempts.json")["attempts"] == 2


def test_legacy_terminal_without_complete_cache_cannot_reopen(tmp_path):
    timeline, p = setup_review(tmp_path)
    atomic_json(tmp_path / "task/language_attempts.json", {
        "attempts": 2, "retries": 0, "keys": ["missing"], "content_terminal": True})
    with pytest.raises(ValueError, match="已停止"):
        review(timeline, cache_dir=tmp_path / "cache", task_dir=tmp_path / "task", model="m",
               caller=lambda *a, **k: pytest.fail("must not call provider"))


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
@pytest.mark.parametrize("advisory", [False, True])
def test_gate_rejects_any_changed_bound_artifact(tmp_path, changed, advisory):
    from video_processing.study_cards.language_qa import validate_language_qa
    timeline, p = setup_review(tmp_path)
    (tmp_path / "source.mp4").write_bytes(b"media fixture")
    atomic_json(tmp_path / "caption.json3", {"events": []})
    atomic_json(timeline, {"language_contract": VERSION, "source_provenance": {
        "source_video": "source.mp4", "caption_artifact": "caption.json3",
        "source_start_seconds": 0, "source_end_seconds": 1}})
    if advisory:
        from video_processing.study_cards.quality_policy import ADVISORY_POLICY
        p["quality_policy"] = ADVISORY_POLICY
        atomic_json(timeline, {**read_json(timeline), "quality_policy": ADVISORY_POLICY})
    p["timeline_sha256"] = file_digest(timeline)
    atomic_json(tmp_path / "display_plan.json", p)
    atomic_json(tmp_path / "qa/source_evidence.json", {"source_sha256": file_digest(tmp_path / "source.mp4"),
        "caption_sha256": file_digest(tmp_path / "caption.json3"), "source_start": 0, "source_end": 1})
    result = good(p)
    if advisory:
        result["findings"][0].update(status="FAIL", severity="P1")
    review(timeline, cache_dir=tmp_path / "cache", task_dir=tmp_path / "task", model="m", caller=lambda *a, **k: result)
    assert validate_language_qa(timeline)["state"] == "PASS"
    if advisory:
        report_path = tmp_path / "qa/language_qa.json"
        report = read_json(report_path)
        atomic_json(report_path, {**report, "quality_warnings": []})
        with pytest.raises(ValueError, match="质量提示"):
            validate_language_qa(timeline)
        atomic_json(report_path, report)
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


def test_boundary_clipped_multitoken_uses_only_the_audio_confirmed_subsequence():
    from video_processing.study_cards.caption_evidence import align_json3
    parsed = parse_json3(caption("one two three"), .2, .8)
    observed = [{"word": "two", "start": .1, "end": .2}]
    assert parsed["boundary_clipped"] == {"start": True, "end": True}
    assert align_json3(parsed, observed) == [{"text": "two", "start": .1, "end": .2}]


def test_boundary_prefix_and_known_typography_splits_need_explicit_asr_equivalence():
    from video_processing.study_cards.caption_evidence import align_json3
    value = caption("Here with the results Good morning Elizabeth", "Good morning to you The US has 15-year-olds")
    value["events"][0]["dDurationMs"] = 1500
    parsed = parse_json3(value, .5, 2)
    observed = [{"word": word, "start": index * .1, "end": index * .1 + .05}
                for index, word in enumerate("Good morning to you The U S has 15 -year -olds".split())]
    aligned = align_json3(parsed, observed)
    assert [item["text"] for item in aligned] == "Good morning to you The US has 15-year-olds".split()
    assert aligned[-3] == {"text": "US", "start": .5, "end": .65}
    assert aligned[-1] == {"text": "15-year-olds", "start": .8, "end": 1.05}


def test_source_alignment_allows_only_auditable_orthographic_and_article_equivalences():
    from video_processing.study_cards.caption_evidence import align_json3, transcript_normalizations

    parsed = {"english_text": "Dress-up after 2 minutes", "source_start": 0, "source_end": 2,
              "boundary_clipped": {"start": False, "end": False}}
    observed = [
        {"word": "dress", "start": 0, "end": .15},
        {"word": "up", "start": .15, "end": .3},
        {"word": "after", "start": .3, "end": .45},
        {"word": "two", "start": .45, "end": .6},
        {"word": "minutes", "start": .6, "end": .8},
    ]
    assert align_json3(parsed, observed) == [
        {"text": "Dress-up", "start": 0.0, "end": 0.3},
        {"text": "after", "start": 0.3, "end": 0.45},
        {"text": "2", "start": 0.45, "end": 0.6},
        {"text": "minutes", "start": 0.6, "end": 0.8},
    ]
    normalizations = transcript_normalizations("dress-up after 2 minutes", "dress up after two minutes")
    assert {item["normalization"] for item in normalizations} == {
        "hyphenated_compound_split", "same_numeric_value",
    }

    article_parsed = {"english_text": "A passkey works", "source_start": 0, "source_end": 1,
                      "boundary_clipped": {"start": False, "end": False}}
    assert align_json3(article_parsed, [
        {"word": "the", "start": 0, "end": .2},
        {"word": "passkey", "start": .2, "end": .5},
        {"word": "works", "start": .5, "end": .8},
    ])[0] == {"text": "A", "start": 0.0, "end": 0.2}
    assert transcript_differences("a passkey", "the passkey") == []
    assert transcript_differences("in the app", "on the app")


def test_zero_width_asr_times_are_repaired_only_inside_the_shared_anchor_group():
    from video_processing.study_cards.caption_evidence import repair_asr_word_timestamps
    raw = [
        {"word": "Before", "start": .0, "end": .4},
        {"word": "The", "start": 1.0, "end": 1.0},
        {"word": "U", "start": 1.0, "end": 1.3},
        {"word": "S", "start": 1.3, "end": 1.5},
    ]
    repaired, records = repair_asr_word_timestamps(raw, 2.0)
    assert repaired[1:3] == [
        {"word": "The", "start": 1.0, "end": 1.15},
        {"word": "U", "start": 1.15, "end": 1.3},
    ]
    assert records[0]["word_indexes"] == [1, 2]
    assert raw[1] == {"word": "The", "start": 1.0, "end": 1.0}


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


def good(p, evidence=None, editorial=None):
    return {"findings": [{"check": c, "target": t, "status": "PASS", "severity": "NONE",
                           "evidence": "当前句法和上下文一致", "suggestion": ""}
                         for c, t in sorted(expected_checks(p, evidence, editorial))]}


@pytest.mark.parametrize("status,severity", [("FAIL", "P0"), ("FAIL", "P1"), ("UNCERTAIN", "NONE"), ("PASS", "P1")])
def test_fail_closed(status, severity):
    p = plan(); result = good(p)
    result["findings"][0].update(status=status, severity=severity)
    assert evaluate(result, p) == "FAIL"


@pytest.mark.parametrize("status,severity", [("FAIL", "P0"), ("FAIL", "P1"), ("UNCERTAIN", "P2")])
def test_new_quality_policy_preserves_findings_without_stopping_production(status, severity):
    from video_processing.study_cards.quality_policy import ADVISORY_POLICY, quality_receipt
    p = plan()
    result = good(p)
    result["findings"][0].update(status=status, severity=severity)
    strict_key = cache_key(review_input(p, {}, {}))
    p["quality_policy"] = ADVISORY_POLICY
    assert evaluate(result, p) == "PASS"
    assert quality_receipt(result, p)["review_state"] == "FAIL"
    assert quality_receipt(result, p)["quality_warnings"] == [result["findings"][0]]
    assert strict_key != cache_key(review_input(p, {}, {}))
    result["findings"].pop()
    with pytest.raises(ValueError, match="覆盖"):
        evaluate(result, p)


def test_advisory_review_cache_does_not_exhaust_revision_budget(tmp_path):
    from video_processing.study_cards.quality_policy import ADVISORY_POLICY
    from video_processing.study_cards.language_review_service import content_failure_keys
    timeline, p = setup_review(tmp_path)
    p["quality_policy"] = ADVISORY_POLICY
    atomic_json(tmp_path / "display_plan.json", p)
    calls = []
    def caller(*args, **kwargs):
        calls.append(1)
        result = good(p)
        result["findings"][0].update(status="FAIL", severity="P1")
        return result
    kwargs = dict(cache_dir=tmp_path / "cache", task_dir=tmp_path / "task", caller=caller, model="model")
    first = review(timeline, **kwargs)
    second = review(timeline, **kwargs)
    assert first["state"] == second["state"] == "PASS"
    assert first["review_state"] == "FAIL" and first["quality_warnings"]
    assert len(calls) == 1 and second["cache_hit"]
    ledger = read_json(tmp_path / "task/language_attempts.json")
    assert ledger["attempts"] == 1 and not ledger.get("content_terminal")
    assert content_failure_keys(ledger, tmp_path / "cache") == []


@pytest.mark.parametrize("en,zh", [("Ku Klux Klan", ""), ("the KKK", ""), ("", "涉及三Ｋ党的内容")])
def test_quality_policy_never_overrides_sensitive_content_gate(en, zh):
    from video_processing.english_world.safety_gate import SafetyDocument, evaluate as safety_evaluate, require_pass
    from video_processing.study_cards.quality_policy import ADVISORY_POLICY
    p = {**plan(), "quality_policy": ADVISORY_POLICY}
    assert evaluate(good(p), p) == "PASS"
    receipt = safety_evaluate("test", [SafetyDocument(name="source", en_text=en, zh_text=zh)])
    assert receipt["state"] == "BLOCKED"
    with pytest.raises(ValueError):
        require_pass(receipt)


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


def test_p1_false_positive_adjudication_requires_source_and_preserves_scope():
    p = plan()
    result = good(p)
    result["findings"][0].update(status="FAIL", severity="P1")
    adjudication = [{"check": result["findings"][0]["check"], "target": result["findings"][0]["target"],
                     "from_status": "FAIL", "from_severity": "P1",
                     "decision": "OVERRULE_P1_FALSE_POSITIVE", "reason": "权威词典确认当前读音为合法变体",
                     "source_url": "https://dictionary.cambridge.org/us/pronunciation/english/repeat"}]
    effective = apply_adjudications(result, adjudication)
    assert evaluate(effective, p) == "PASS"
    bad = [{**adjudication[0], "from_severity": "P0"}]
    with pytest.raises(ValueError):
        apply_adjudications(result, bad)


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
    assert review(timeline, model="model-c", **kwargs)["state"] == "PASS"
    with pytest.raises(ValueError, match="最多三个"):
        review(timeline, model="model-d", **kwargs)


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


def test_historical_empty_structured_output_can_recover_once(tmp_path):
    timeline, p = setup_review(tmp_path)
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    atomic_json(task_dir / "language_attempts.json", {
        "attempts": 1, "retries": 0, "keys": ["old-key"],
        "terminal": True, "last_error": "agy returned no structured_output",
    })
    calls = []
    def caller(*args, **kwargs):
        calls.append(1)
        return good(p)
    kwargs = dict(cache_dir=tmp_path / "cache", task_dir=task_dir, caller=caller, model="test")
    assert review(timeline, **kwargs)["state"] == "PASS"
    assert len(calls) == 1
    ledger = read_json(task_dir / "language_attempts.json")
    assert ledger["attempts"] == 2
    assert ledger["recovered_transient_failure"] is True


def test_permission_failure_is_terminal(tmp_path):
    timeline, _ = setup_review(tmp_path)
    def caller(*args, **kwargs): raise AgyProviderError("agy exit 1: permission")
    kwargs = dict(cache_dir=tmp_path / "cache", task_dir=tmp_path / "task", caller=caller, model="test")
    with pytest.raises(AgyProviderError): review(timeline, **kwargs)
    assert read_json(tmp_path / "task/language_attempts.json")["attempts"] == 1
    with pytest.raises(ValueError): review(timeline, **kwargs)


def setup_startup_failure(tmp_path):
    timeline, p = setup_review(tmp_path)
    def fail(*args, **kwargs):
        raise AgyProviderError("agy exit 1: provider error")
    kwargs = dict(cache_dir=tmp_path / "cache", task_dir=tmp_path / "task", model="m")
    with pytest.raises(AgyProviderError):
        review(timeline, caller=fail, **kwargs)
    return timeline, p, kwargs, tmp_path / "task/language_attempts.json"


def test_explicit_startup_recovery_preserves_budget_and_requires_fresh_probe(tmp_path, monkeypatch):
    from video_processing.study_cards import language_review_service as module
    timeline, p, kwargs, path = setup_startup_failure(tmp_path)
    ledger = read_json(path)
    ledger["attempts"] = 2
    atomic_json(path, ledger)
    probes = []
    def probe(**kw):
        probes.append(kw)
        return {"model_available": True, "exit_code": 0}
    monkeypatch.setattr(module, "probe_agy_startup", probe)
    calls = []
    def caller(*a, **kw):
        calls.append(1)
        return good(p)
    report = review(timeline, caller=caller, recover_startup_reason="Confirmed local bind denial; approved recovery",
                    **kwargs)
    assert report["state"] == "PASS" and report["attempts"] == 3
    ledger = read_json(path)
    assert ledger["startup_recovery"]["preserved_attempts"] == 2
    assert ledger["startup_recovery"]["previous_error"] == "agy exit 1: provider error"
    assert ledger["retries"] == 1 and len(calls) == len(probes) == 1
    with pytest.raises(ValueError):
        review(timeline, caller=caller, recover_startup_reason="again", **kwargs)
    assert len(calls) == 1


def test_startup_probe_failure_leaves_ledger_unchanged(tmp_path, monkeypatch):
    from video_processing.study_cards import language_review_service as module
    timeline, _, kwargs, path = setup_startup_failure(tmp_path)
    before = path.read_bytes()
    def probe(**kw):
        raise AgyProviderError("agy startup probe unavailable")
    monkeypatch.setattr(module, "probe_agy_startup", probe)
    with pytest.raises(AgyProviderError):
        review(timeline, recover_startup_reason="confirmed startup failure", **kwargs)
    assert path.read_bytes() == before


def test_rejected_model_change_does_not_poison_startup_recovery(tmp_path, monkeypatch):
    from video_processing.study_cards import language_review_service as module
    timeline, p, kwargs, path = setup_startup_failure(tmp_path)
    before = path.read_bytes()
    calls = []

    def caller(*args, **kw):
        calls.append(kw["model"])
        return good(p)

    with pytest.raises(ValueError, match="已终止"):
        review(timeline, caller=caller, **{**kwargs, "model": "different-model"})
    assert path.read_bytes() == before
    assert calls == []
    monkeypatch.setattr(module, "probe_agy_startup", lambda **kw: {"model_available": True})
    report = review(timeline, caller=caller, recover_startup_reason="confirmed startup failure", **kwargs)
    ledger = read_json(path)
    assert report["state"] == "PASS" and ledger["attempts"] == 2
    assert len(ledger["keys"]) == 1 and ledger["retries"] == 1
    assert calls == ["m"]


@pytest.mark.parametrize("blocked", [{"attempts": 3}, {"inflight": True}, {"terminal": True}])
def test_rejected_input_does_not_mutate_ledger(tmp_path, blocked):
    timeline, _ = setup_review(tmp_path)
    path = tmp_path / "task/language_attempts.json"
    atomic_json(path, {"attempts": 1, "retries": 0, "keys": ["attempted-input"], **blocked})
    before = path.read_bytes()
    with pytest.raises(ValueError, match="已终止"):
        review(timeline, cache_dir=tmp_path / "cache", task_dir=path.parent, model="new-model")
    assert path.read_bytes() == before


@pytest.mark.parametrize("blocked", [{"attempts": 3}, {"inflight": True}, {"terminal": True}])
def test_rejected_publication_input_does_not_mutate_shared_ledger(tmp_path, monkeypatch, blocked):
    from video_processing.study_cards import publication_qa as module
    timeline, p = setup_review(tmp_path)
    p["content"].update(headline_en="Reading", headline_zh="阅读")
    atomic_json(tmp_path / "display_plan.json", p)
    monkeypatch.setattr(module, "validate_language_qa", lambda _: {"input_key": "base-pass"})
    path = tmp_path / "task/language_attempts.json"
    atomic_json(path, {"attempts": 1, "retries": 0, "keys": ["attempted-input"], **blocked})
    before = path.read_bytes()
    publication = {"title": "阅读成绩", "copy": "阅读成绩令人警醒", "cover_payload": {
        "title": "阅读成绩", "quote_en": "The results are sobering.", "quote_zh": "结果令人警醒。",
        "difficulty_tag": "A2–B1", "audio_source": "ABC News", "date_str": "2026.09.09"}}
    with pytest.raises(ValueError, match="用尽或停止"):
        module.review_publication(timeline, publication, cache_dir=tmp_path / "cache", task_dir=path.parent, model="m")
    assert path.read_bytes() == before


@pytest.mark.parametrize("change", [
    {"attempts": 3}, {"retries": 1}, {"inflight": True}, {"content_terminal": True},
    {"last_error": "agy exit 1: permission"}, {"last_error": "ValidationError"},
    {"startup_recovery": {"version": 1}}, {"keys": ["missing-prior", "different-input"]},
])
def test_startup_recovery_does_not_bypass_other_blocks(tmp_path, change):
    timeline, _, kwargs, path = setup_startup_failure(tmp_path)
    ledger = read_json(path)
    ledger.update(change)
    atomic_json(path, ledger)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="恢复条件"):
        review(timeline, recover_startup_reason="confirmed startup failure", **kwargs)
    assert path.read_bytes() == before


def test_startup_recovery_final_call_failure_remains_terminal(tmp_path, monkeypatch):
    from video_processing.study_cards import language_review_service as module
    timeline, _, kwargs, path = setup_startup_failure(tmp_path)
    ledger = read_json(path)
    ledger["attempts"] = 2
    atomic_json(path, ledger)
    monkeypatch.setattr(module, "probe_agy_startup", lambda **kw: {"model_available": True})
    def fail(*a, **kw):
        raise AgyProviderError("agy timed out")
    with pytest.raises(AgyProviderError):
        review(timeline, caller=fail, recover_startup_reason="confirmed startup failure", **kwargs)
    ledger = read_json(path)
    assert ledger["attempts"] == 3 and ledger["terminal"] and ledger["retries"] == 1
    with pytest.raises(ValueError):
        review(timeline, caller=fail, **kwargs)


def test_path_only_binding_does_not_change_cache():
    a, b = {**plan(), "timeline_sha256": "a"}, {**plan(), "timeline_sha256": "b"}
    assert cache_key(review_input(a, {}, {})) == cache_key(review_input(b, {}, {}))


def test_occurrence_specific_highlight():
    from video_processing.study_cards.models import VocabularyItem
    from video_processing.study_cards.template_a import _highlighted_token_indices
    item = VocabularyItem("key", "关键的", word_index=3, item_id="word:3:1")
    assert not _highlighted_token_indices(["key"], (item,), start_index=0)
    assert _highlighted_token_indices(["key"], (item,), start_index=3)


def _first_failure_for_revision(tmp_path, check="TRANSLATION_ACCURACY"):
    timeline, p = setup_review(tmp_path)
    result = good(p)
    finding = next(f for f in result["findings"] if f["check"] == check)
    finding.update(status="FAIL", severity="P1", suggestion="按当前上下文修正", evidence="原句与当前表述不同")
    kwargs = {"cache_dir": tmp_path / "cache", "task_dir": tmp_path / "task", "model": "test", "effort": "high"}
    report = review(timeline, caller=lambda *a, **k: result, **kwargs)
    atomic_json(tmp_path / "qa/review_execution.json",
                {"status": "COMPLETED", "started_ns": 100, "report_sha256": digest(report)})
    return timeline, p, kwargs


def test_revision_reservation_keeps_budget_and_survives_restart(tmp_path):
    from video_processing.study_cards.language_review_service import reserve_editorial_revision
    timeline, p, kwargs = _first_failure_for_revision(tmp_path)
    ledger = kwargs["task_dir"] / "language_attempts.json"
    original = ledger.read_bytes()
    assert reserve_editorial_revision(timeline, not_before_ns=100, **kwargs)
    assert ledger.read_bytes() == original
    with pytest.raises(ValueError, match="已经预占"):
        reserve_editorial_revision(timeline, not_before_ns=100, **kwargs)
    assert ledger.read_bytes() == original

    # 真正复审消费原审校服务的第二次额度；仍为同一任务，不建立新账本。
    atomic_json(timeline, {"english_text": "test", "translation_zh": "修正翻译"})
    p["timeline_sha256"] = file_digest(timeline)
    p["content"]["paragraphs"][0]["translation_zh"] = "结果令人警醒。"
    atomic_json(tmp_path / "display_plan.json", p)
    editorial = {"version": VERSION, "revision": 1, "changes": [
        {"kind": "translation", "before": "旧译", "after": "新译", "evidence": "来源 10–20s"}]}
    atomic_json(tmp_path / "editorial_changes.json", editorial)
    result = review(timeline, caller=lambda *a, **k: good(p, editorial=editorial), **kwargs)
    assert result["state"] == "PASS"
    assert result["attempts"] == 2
    assert read_json(ledger)["attempts"] == 2


@pytest.mark.parametrize("case", ["budget", "terminal", "content_terminal", "inflight", "stale_report",
                                  "stale_execution", "execution_error", "cache_changed", "source_changed"])
def test_revision_refuses_invalid_evidence_before_generation(tmp_path, case):
    from video_processing.study_cards.language_review_service import reserve_editorial_revision
    timeline, p, kwargs = _first_failure_for_revision(tmp_path)
    ledger_path = kwargs["task_dir"] / "language_attempts.json"
    ledger = read_json(ledger_path)
    if case == "budget":
        ledger["attempts"] = 3
    elif case in {"terminal", "content_terminal", "inflight"}:
        ledger[case] = True
    elif case == "stale_report":
        atomic_json(timeline, {"english_text": "changed"})
    elif case in {"stale_execution", "execution_error"}:
        receipt = read_json(tmp_path / "qa/review_execution.json")
        receipt.update(started_ns=1 if case == "stale_execution" else 100,
                       status="ERROR" if case == "execution_error" else "COMPLETED")
        atomic_json(tmp_path / "qa/review_execution.json", receipt)
    elif case == "cache_changed":
        cache = kwargs["cache_dir"] / f"{ledger['keys'][0]}.json"
        value = read_json(cache)
        value["result"] = good(p)
        atomic_json(cache, value)
    else:
        atomic_json(tmp_path / "qa/source_evidence.json", {"source_sha256": "other"})
    atomic_json(ledger_path, ledger)
    before = ledger_path.read_bytes()
    with pytest.raises(ValueError):
        reserve_editorial_revision(timeline, not_before_ns=100, **kwargs)
    assert ledger_path.read_bytes() == before
    assert not (kwargs["task_dir"] / "editorial_revision.json").exists()


def test_transcript_failure_cannot_trigger_text_only_revision(tmp_path):
    from video_processing.study_cards.language_review_service import reserve_editorial_revision
    timeline, p, kwargs = _first_failure_for_revision(tmp_path, check="TRANSCRIPT_ACCURACY")
    with pytest.raises(ValueError, match="不能由受限编辑修订"):
        reserve_editorial_revision(timeline, not_before_ns=100, **kwargs)


def setup_rate_limit_failure(tmp_path):
    timeline, p = setup_review(tmp_path)
    def fail(*args, **kwargs):
        raise AgyProviderError("agy exit 3: rate limit")
    kwargs = dict(cache_dir=tmp_path / "cache", task_dir=tmp_path / "task", model="m")
    with pytest.raises(AgyProviderError):
        review(timeline, caller=fail, **kwargs)
    return timeline, p, kwargs, tmp_path / "task/language_attempts.json"


def test_quota_recovery_uses_only_remaining_third_call_and_preserves_history(tmp_path):
    timeline, p, kwargs, path = setup_rate_limit_failure(tmp_path)
    before = read_json(path)
    assert before["attempts"] == 2 and before["retries"] == 1 and before["terminal"]
    calls = []
    def caller(*a, **kw):
        calls.append(1)
        return good(p)
    recovery = {"reason": "Provider reset confirmed by operator", "not_before": 1}
    report = review(timeline, caller=caller, recover_rate_limit=recovery, **kwargs)
    ledger = read_json(path)
    assert report["state"] == "PASS" and report["attempts"] == 3
    assert ledger["retries"] == 1 and ledger["keys"] == before["keys"]
    assert ledger["rate_limit_recovery"]["previous_error"] == before["last_error"]
    assert ledger["rate_limit_recovery"]["preserved_attempts"] == 2
    with pytest.raises(ValueError, match="恢复条件"):
        review(timeline, caller=caller, recover_rate_limit=recovery, **kwargs)
    assert len(calls) == 1


@pytest.mark.parametrize("change", [
    {"attempts": 3}, {"inflight": True}, {"content_terminal": True},
    {"last_error": "agy exit 1: permission"}, {"last_error": "agy timed out"},
    {"last_error": "ValidationError"}, {"rate_limit_recovery": {"version": 1}},
    {"startup_recovery": {"version": 1}}, {"keys": ["different-input"]},
    {"publication_keys": ["missing-result"]},
])
def test_quota_recovery_cannot_bypass_other_failures_or_change_inputs(tmp_path, change):
    timeline, _, kwargs, path = setup_rate_limit_failure(tmp_path)
    ledger = read_json(path)
    ledger.update(change)
    atomic_json(path, ledger)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="恢复条件"):
        review(timeline, recover_rate_limit={"reason": "reset confirmed", "not_before": 1}, **kwargs)
    assert path.read_bytes() == before


@pytest.mark.parametrize("not_before", [float("inf"), float("nan"), -1, 10**12])
def test_quota_recovery_rejects_unknown_or_future_reset_without_mutation(tmp_path, not_before):
    timeline, _, kwargs, path = setup_rate_limit_failure(tmp_path)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="恢复时间"):
        review(timeline, recover_rate_limit={"reason": "reset", "not_before": not_before}, **kwargs)
    assert path.read_bytes() == before


def test_quota_recovery_final_provider_failure_stays_terminal(tmp_path):
    timeline, _, kwargs, path = setup_rate_limit_failure(tmp_path)
    def fail(*args, **kw):
        raise AgyProviderError("agy exit 3: rate limit")
    with pytest.raises(AgyProviderError):
        review(timeline, caller=fail, recover_rate_limit={"reason": "reset confirmed", "not_before": 1}, **kwargs)
    ledger = read_json(path)
    assert ledger["attempts"] == 3 and ledger["terminal"]
    with pytest.raises(ValueError):
        review(timeline, caller=fail, **kwargs)


def test_quota_recovery_cannot_override_completed_content_failure(tmp_path):
    timeline, p, kwargs, path = setup_rate_limit_failure(tmp_path)
    ledger = read_json(path)
    result = good(p)
    result["findings"][0].update(status="FAIL", severity="P1")
    atomic_json(kwargs["cache_dir"] / (ledger["keys"][0] + ".json"), {"result": result})
    before = path.read_bytes()
    with pytest.raises(ValueError, match="恢复条件"):
        review(timeline, recover_rate_limit={"reason": "reset", "not_before": 1}, **kwargs)
    assert path.read_bytes() == before
