"""程序化英语世界协调器的纯函数边界测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.3.3 | 2026-09-25 | Codex | 验证 AGY Schema 无整数枚举，词典候选由宿主拒绝越界与坏发音词。 |
| 1.3.2 | 2026-09-24 | Codex | 真实词典、封面和账本覆盖发音错误替换及失败终止，验证 Schema 限制。 |
| 1.3.1 | 2026-09-23 | Codex | 入口测试使用真实词典、布局及账本验证首次 FAIL 到唯一复审 PASS 或终止。 |
| 1.3.0 | 2026-09-17 | Codex | 覆盖本地 ASR 占位锚点不会在转写前被误作成片字幕拒绝。 |
| 1.2.0 | 2026-09-17 | Codex | 覆盖无原字幕时本地 Whisper 的自然句窗口与透明引导工件。 |
| 1.1.0 | 2026-09-17 | Codex | 覆盖候选失败凭据，确保影子失败可复核具体阶段。 |
| 1.0.0 | 2026-09-17 | Codex | 覆盖自然窗口与 AGY 受限初稿的冻结边界。 |
"""

from __future__ import annotations

import json
from scripts import english_world_programmatic_daily as daily

import pytest


def _timeline():
    return {
        "words": [
            {"text": "Clean", "start": 0.0, "end": 0.4},
            {"text": "energy", "start": 0.4, "end": 0.8},
            {"text": "helps.", "start": 0.8, "end": 1.2},
            {"text": "Families", "start": 1.2, "end": 1.6},
            {"text": "learn.", "start": 1.6, "end": 2.0},
        ],
    }


def _draft():
    return {
        "headline_zh": "清洁能源", "headline_en": "Clean Energy",
        "translations": [{"paragraph_index": 0, "translation_zh": "清洁能源有帮助。家庭在学习。"}],
        "learning_points": [
            {"word_index": 0, "pos": "adj.", "context_meaning_zh": "清洁的"},
            {"word_index": 1, "pos": "n.", "context_meaning_zh": "能源"},
            {"word_index": 3, "pos": "n.", "context_meaning_zh": "家庭"},
        ],
    }


def test_event_windows_require_duration_and_natural_sentence_end():
    caption = {"events": [
        {"tStartMs": 0, "dDurationMs": 10000, "segs": [{"utf8": "Not done"}]},
        {"tStartMs": 10000, "dDurationMs": 25000, "segs": [{"utf8": "A complete sentence."}]},
        {"tStartMs": 35000, "dDurationMs": 5000, "segs": [{"utf8": "Next."}]},
    ]}

    assert list(daily._event_windows(caption, source_duration=60)) == [(0.0, 35.0), (0.0, 40.0)]


def test_caption_quality_rejects_character_fragmented_json3_but_keeps_normal_short_words():
    with pytest.raises(daily.ProgrammaticDailyError, match="碎片化"):
        daily._require_caption_text_quality({"english_text": "DE LO IT TE C AN AD A RE LE AS ED"})

    daily._require_caption_text_quality({"english_text": "We are in a clean tech programme for young learners."})


def test_asr_window_requires_real_terminal_punctuation_and_bootstrap_is_explicit():
    words = [
        {"word": "We", "start": 0.0, "end": 0.3},
        {"word": "learn", "start": 0.3, "end": 31.1},
        {"word": "together.", "start": 31.1, "end": 31.8},
    ]

    assert daily._asr_window(words, source_duration=100) == (0.0, 31.8)
    payload = daily._bootstrap_caption_payload(duration=31.8, words=words)
    assert payload["events"][0]["segs"][0]["utf8"] == "We"
    assert daily._bootstrap_caption_payload(duration=60)["events"][0]["segs"][0]["utf8"] == "pending"


def test_initial_timeline_allows_only_the_local_asr_placeholder_before_transcription(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"fixture")
    caption = tmp_path / "local_whisper_placeholder.json3"
    daily.atomic_json(caption, daily._bootstrap_caption_payload(duration=60))
    candidate = {"source_channel": "BNN Bloomberg", "source_channel_id": "channel", "youtube_id": "source",
                 "source_url": "https://example.test/source", "source_title": "Example", "upload_date": "20260917"}

    timeline = daily._initial_timeline(candidate, source=source, caption=caption, start=0, end=60)

    assert timeline["source_provenance"]["caption_format"] == "local_whisper_bootstrap"


def test_apply_draft_keeps_frozen_words_and_uses_only_indexes():
    timeline = _timeline()

    result = daily._apply_draft(timeline, _draft())

    assert result["english_text"] == "Clean energy helps. Families learn."
    assert [point["word"] for point in result["learning_points"]] == ["Clean", "energy", "Families"]
    assert result["paragraphs"][0]["english_text"] == result["english_text"]


def test_apply_draft_rejects_reused_or_out_of_range_word_indexes():
    duplicate = _draft()
    duplicate["learning_points"][2]["word_index"] = 0

    with pytest.raises(daily.ProgrammaticDailyError, match="重复"):
        daily._apply_draft(_timeline(), duplicate)

    invalid = _draft()
    invalid["learning_points"][2]["word_index"] = 99
    with pytest.raises(daily.ProgrammaticDailyError, match="越界"):
        daily._apply_draft(_timeline(), invalid)


def test_draft_schema_uses_per_screen_learning_point_bounds():
    schema = daily._draft_schema(paragraph_count=2, word_count=10)

    assert schema["properties"]["headline_zh"]["maxLength"] == 14
    assert schema["properties"]["learning_points"]["minItems"] == 0
    assert schema["properties"]["learning_points"]["maxItems"] == 8
    assert schema["properties"]["translations"]["minItems"] == 2
    assert daily._learning_point_bounds(3) == (0, 13)


def test_no_dictionary_options_produces_reading_without_forced_word_cards():
    import jsonschema
    schema = daily._draft_schema(paragraph_count=1, word_count=10, allowed_indexes=[])
    jsonschema.Draft202012Validator.check_schema(schema)
    assert schema["properties"]["learning_points"]["maxItems"] == 0
    draft = _draft()
    draft["learning_points"] = []
    result = daily._apply_draft(_timeline(), draft)
    assert result["learning_points"] == []
    assert result["english_text"] and result["translation_zh"]


def test_advisory_layout_supports_multiple_screens_without_word_cards():
    from video_processing.study_cards.display_plan import build_plan, verify_plan
    from video_processing.study_cards.quality_policy import ADVISORY_POLICY
    text = "Clean energy helps families learn together and understand the changing world. " * 2
    paragraphs = [{"english_text": text.strip(), "translation_zh": "清洁能源帮助家庭共同学习并理解不断变化的世界。"}
                  for _ in range(4)]
    english = " ".join(p["english_text"] for p in paragraphs)
    payload = {"language_contract": daily.VERSION, "quality_policy": ADVISORY_POLICY,
               "headline_zh": "清洁能源", "headline_en": "Clean energy",
               "paragraphs": paragraphs, "english_text": english,
               "translation_zh": "".join(p["translation_zh"] for p in paragraphs),
               "words": [{"text": word, "start": i * .4, "end": (i + 1) * .4}
                         for i, word in enumerate(english.split())],
               "learning_points": [], "vocabulary_candidates": [],
               "source_provenance": {"publisher": "Test News"}}
    daily._freeze_publication(payload)
    plan = build_plan(payload, "test-timeline")
    assert len(plan["screens"]) > 1
    assert all(not screen["micro_notes"] for screen in plan["screens"])
    assert verify_plan(payload, plan, "test-timeline").words
    del payload["quality_policy"]
    with pytest.raises(ValueError, match="个学习点，要求"):
        build_plan(payload, "test-timeline")


def test_frozen_words_normalizes_whisper_word_key_without_losing_timing():
    words = daily._frozen_words({"asr_words": [
        {"word": " clean", "start": 0.0, "end": 0.4},
        {"word": " energy", "start": 0.4, "end": 0.9},
    ]})

    assert words == [
        {"text": "clean", "start": 0.0, "end": 0.4},
        {"text": "energy", "start": 0.4, "end": 0.9},
    ]


def test_frozen_words_rejects_missing_text_or_time_boundary():
    with pytest.raises(daily.ProgrammaticDailyError, match="空词"):
        daily._frozen_words({"asr_words": [{"word": "", "start": 0, "end": 1}]})

    with pytest.raises(daily.ProgrammaticDailyError, match="时间边界"):
        daily._frozen_words({"asr_words": [{"word": "clean", "start": 0}]})


def test_candidate_failure_receipt_records_stage_and_error(monkeypatch, tmp_path):
    monkeypatch.setattr(daily, "_discover_candidates", lambda **_: [{"youtube_id": "source-1"}])
    monkeypatch.setattr(daily, "_download_candidate", lambda *_args, **_kwargs: (_ for _ in ()).throw(
        daily.ProgrammaticDailyError("missing subtitles")))
    monkeypatch.setattr(daily, "_run", lambda *_args, **_kwargs: None)

    with pytest.raises(daily.ProgrammaticDailyError, match="download"):
        daily.run(request=tmp_path / "request.json", output_root=tmp_path / "out", shadow_only=True)

    receipt = next((tmp_path / "out").glob("*/qa/candidate_failure.json"))
    payload = json.loads(receipt.read_text())
    assert payload["stage"] == "download"
    assert payload["error"] == "missing subtitles"


@pytest.mark.parametrize("second_passes", [True, False])
@pytest.mark.parametrize("pronunciation_failure", [True, False])
def test_coordinator_revises_once_using_real_ledger_and_refrozen_cover(tmp_path, monkeypatch, second_passes, pronunciation_failure):
    """只替换子进程边界和供应商；词典、布局、指纹、审校预算均跑真实实现。"""
    from video_processing.study_cards.learning_dictionary import attach_evidence
    from video_processing.study_cards.display_plan import build_plan
    from video_processing.study_cards.language_protocol import (atomic_json, read_json, file_digest, digest,
                                                               expected_checks, task_identity)
    from video_processing.study_cards.language_review_service import review
    from copy import deepcopy
    import time
    monkeypatch.setattr(daily, "ROOT", tmp_path)
    wordlist = tmp_path / "wordlist"
    wordlist.mkdir()
    (wordlist / "ecdict.csv").write_text("word,phonetic,definition,translation,exchange\n"
        "clean,kli:n,clean,a. 清洁的,\nenergy,enədʒi,energy,n. 能源,\nfamilies,fæməliz,families,n. 家庭,\nhelps,helps,helps,v. 帮助,\n")
    (wordlist / "exam-wordlists.csv").write_text("word,pos,exam,phonetic,translation\nclean,a.,KET,kli:n,清洁的\nenergy,n.,KET,enədʒi,能源\nfamilies,n.,KET,fæməliz,家庭\n")
    (wordlist / "cefr-enhanced.csv").write_text("word,pos,cefr,phonetic,translation\n")
    payload = daily._apply_draft(_timeline(), _draft())
    payload.update(language_contract=daily.VERSION, source_provenance={
        "publisher": "Test", "source_start_seconds": 10, "source_end_seconds": 12})
    payload = attach_evidence(payload, wordlist)
    daily._freeze_publication(payload)
    original_cover = deepcopy(payload["publication_text"]["cover_payload"])
    timeline = tmp_path / "package/timeline.json"
    atomic_json(timeline, payload)
    evidence = {"source_sha256": "source", "caption_sha256": "caption", "source_start": 10, "source_end": 12}
    atomic_json(timeline.parent / "qa/source_evidence.json", evidence)
    atomic_json(timeline.parent / "editorial_changes.json", {"version": daily.VERSION, "revision": 0, "changes": []})
    task_dir = tmp_path / "output/english_world_language/tasks" / task_identity(evidence)
    reviews, drafts = [], []

    def script(stage, *, timeline, **kwargs):
        value = read_json(timeline)
        p = build_plan(value, file_digest(timeline))
        atomic_json(timeline.parent / "display_plan.json", p)
        if stage == "prepare":
            return
        assert stage == "review"
        started = time.time_ns()
        editorial = read_json(timeline.parent / "editorial_changes.json")
        result = {"findings": [{"check": c, "target": t, "status": "PASS", "severity": "NONE",
                                "evidence": "来源核对", "suggestion": ""}
                               for c, t in sorted(expected_checks(p, evidence, editorial))]}
        if not reviews or not second_passes:
            check, target = ("VOCAB_PRONUNCIATION", "word:0:1") if pronunciation_failure and not reviews else ("TRANSLATION_ACCURACY", "paragraph:0")
            f = next(f for f in result["findings"] if f["check"] == check and f["target"] == target)
            f.update(status="FAIL", severity="P1", suggestion="纠正段译")
        report = review(timeline, cache_dir=tmp_path / "output/english_world_language/cache", task_dir=task_dir,
                        model=daily.settings.english_world_language_model, effort=daily.settings.english_world_language_effort,
                        caller=lambda *a, **k: result)
        reviews.append(report)
        atomic_json(timeline.parent / "qa/review_execution.json", {"status": "COMPLETED", "started_ns": started,
                                                                   "report_sha256": digest(read_json(timeline.parent / "qa/language_qa.json"))})
        if report["state"] != "PASS":
            raise daily.ProgrammaticDailyError("language QA: FAIL")

    def draft(*args, **kwargs):
        drafts.append(1)
        value = _draft()
        value["translations"][0]["translation_zh"] = "清洁能源带来帮助。各个家庭正在学习。"
        if pronunciation_failure:
            assert "enum" not in kwargs["schema"]["properties"]["learning_points"]["items"]["properties"]["word_index"]
            value["learning_points"][0] = {"word_index": 2, "pos": "v.", "context_meaning_zh": "帮助"}
        return value

    monkeypatch.setattr(daily, "_script", script)
    monkeypatch.setattr(daily, "run_agy_structured", draft)
    if second_passes:
        result = daily._review_and_revise(timeline, payload, wordlist_dir=wordlist)
        assert result["publication_text"]["cover_payload"]["quote_zh"] != original_cover["quote_zh"]
    else:
        with pytest.raises(daily.ProgrammaticDailyError, match="FAIL"):
            daily._review_and_revise(timeline, payload, wordlist_dir=wordlist)
        assert read_json(task_dir / "language_attempts.json")["content_terminal"]
    assert len(drafts) == 1
    assert len(reviews) == 2
    assert reviews[-1]["attempts"] == 2
    assert read_json(timeline.parent / "editorial_changes.json")["revision"] == 1
    assert read_json(task_dir / "editorial_revision.json")["preserved_attempts"] == 1


def test_dictionary_bounded_host_rejects_provider_reusing_bad_pronunciation():
    import jsonschema
    timeline = daily._apply_draft(_timeline(), _draft())
    finding = {'check': 'VOCAB_PRONUNCIATION', 'target': 'word:0:1', 'status': 'FAIL', 'severity': 'P1'}
    assert daily._rejected_pronunciation_words(timeline, [finding]) == {'Clean'}
    schema = daily._draft_schema(1, 5, allowed_indexes=[1, 2, 3])
    index_schema = schema['properties']['learning_points']['items']['properties']['word_index']
    assert index_schema == {'type': 'integer', 'minimum': 0, 'maximum': 4}
    jsonschema.validate(_draft(), schema)
    with pytest.raises(daily.ProgrammaticDailyError, match='词典候选'):
        daily._apply_draft(_timeline(), _draft(), allowed_indexes=[1, 2, 3])
    value = _draft()
    value['learning_points'][0]['word_index'] = 2
    jsonschema.validate(value, schema)
    assert [point['word_index'] for point in daily._apply_draft(
        _timeline(), value, allowed_indexes=[1, 2, 3])['learning_points']] == [2, 1, 3]
    prompt = daily._revision_draft_prompt(timeline['words'], [(0, 5)], timeline, [finding], word_options=[])
    assert '返回格式不能修改音标' in prompt


@pytest.mark.parametrize("defect", ["phonetic", "meaning", "missing_evidence", "overlap", "offscreen"])
def test_optional_bad_card_is_dropped_with_full_text_preserved(defect):
    from copy import deepcopy
    from video_processing.study_cards.display_plan import build_plan
    payload = daily._apply_draft(_timeline(), _draft())
    payload.update(language_contract=daily.VERSION, quality_policy=daily.ADVISORY_POLICY,
                   source_provenance={"publisher": "Test News"})
    for point in payload["learning_points"]:
        point.update(phonetic="enə", phonetic_word=point["word"], dictionary_source="ecdict.csv")
    before = deepcopy(payload)
    point = payload["learning_points"][1]
    if defect == "phonetic":
        point["phonetic"] = "a" * 80
    elif defect == "meaning":
        point["context_meaning_zh"] = "这是过长的解释" * 40
    elif defect == "missing_evidence":
        point.pop("dictionary_source")
    elif defect == "overlap":
        payload["learning_points"].insert(1, deepcopy(payload["learning_points"][0]))
    else:
        point["word_index"] = 999
    daily._fit_learning_point_density(payload)
    daily._freeze_publication(payload)
    assert build_plan(payload, "test-timeline")["content"]["words"]
    assert payload["quality_adjustments"][-1]["action"] == "drop_optional_card"
    for key in ("words", "english_text", "translation_zh", "paragraphs"):
        assert payload[key] == before[key]
    assert len(payload["learning_points"]) == (3 if defect == "overlap" else 2)


def test_bad_body_is_not_hidden_by_optional_card_removal():
    payload = daily._apply_draft(_timeline(), _draft())
    payload.update(quality_policy=daily.ADVISORY_POLICY, translation_zh="与段译不同")
    with pytest.raises(ValueError, match="中文"):
        daily._fit_learning_point_density(payload)


@pytest.mark.parametrize("transient", [True, False])
def test_stage_recovery_retries_only_transient_errors_in_same_workspace(tmp_path, monkeypatch, transient):
    monkeypatch.setattr(daily.time, "sleep", lambda _: None)
    calls = []
    def action():
        calls.append(1)
        if len(calls) == 1:
            raise daily.TransientStageError("transport") if transient else ValueError("code or input defect")
        return "completed"
    if transient:
        assert daily._stage_call("render", tmp_path, action) == "completed"
        assert len(calls) == 2
    else:
        with pytest.raises(ValueError):
            daily._stage_call("render", tmp_path, action)
        assert len(calls) == 1
    journal = daily.read_json(tmp_path / "qa/stage_recovery.json")
    assert journal["attempts"][0]["state"] == "FAILED"
    assert journal["attempts"][-1]["state"] == ("COMPLETED" if transient else "FAILED")


def test_stage_recovery_is_bounded_and_does_not_clear_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(daily.time, "sleep", lambda _: None)
    ledger = tmp_path / "ledger.json"
    ledger.write_text('{"calls":3}')
    def action():
        raise daily.TransientStageError("transport")
    with pytest.raises(daily.TransientStageError):
        daily._stage_call("review", tmp_path, action)
    assert len(daily.read_json(tmp_path / "qa/stage_recovery.json")["attempts"]) == 2
    assert ledger.read_text() == '{"calls":3}'


@pytest.mark.parametrize("state,error", [("BLOCKED", daily.CandidateSafetyRejected),
                                         ("FAIL_CLOSED", daily.ProgrammaticDailyError)])
def test_safety_rejection_is_distinct_from_review_unavailability(tmp_path, state, error):
    receipt = tmp_path / "qa/visual_safety.json"
    def action():
        daily.atomic_json(receipt, {"state": state})
        raise daily.ProgrammaticDailyError("safety exit 2")
    with pytest.raises(error):
        daily._stage_call("visual_safety", tmp_path, action, safety_report=receipt)
    assert len(daily.read_json(tmp_path / "qa/stage_recovery.json")["attempts"]) == 1


@pytest.mark.parametrize("locked", [False, True])
def test_candidate_switch_is_bounded_without_banning_infrastructure_failures(locked):
    route = daily._candidate_failure_route
    assert route(daily.CandidateSafetyRejected("blocked"), locked_source=locked, production_candidates=1) == (True, True)
    assert route(daily.CandidateSafetyRejected("blocked"), locked_source=locked,
                 production_candidates=daily.MAX_PRODUCTION_CANDIDATES) == (True, False)
    assert route(daily.TransientStageError("transport"), locked_source=locked, production_candidates=1) == (False, False)
    assert route(RuntimeError("program defect"), locked_source=locked, production_candidates=1) == (False, False)
    assert route(ValueError("bad input"), locked_source=locked, production_candidates=1) == ((False, False) if locked else (True, True))


def test_stale_safety_rejection_cannot_trigger_candidate_switch(tmp_path):
    import os
    receipt = tmp_path / "qa/visual_safety.json"
    daily.atomic_json(receipt, {"state": "BLOCKED"})
    os.utime(receipt, (1, 1))
    def action():
        raise daily.ProgrammaticDailyError("provider failed before writing new receipt")
    with pytest.raises(daily.ProgrammaticDailyError) as caught:
        daily._stage_call("visual_safety", tmp_path, action, safety_report=receipt)
    assert not isinstance(caught.value, daily.CandidateSafetyRejected)


def test_timed_out_stage_kills_and_reaps_process_group_before_return(tmp_path, monkeypatch):
    import subprocess
    from unittest.mock import MagicMock
    events = []
    process = MagicMock(pid=91234)
    process.__enter__.return_value = process
    def communicate(**kwargs):
        events.append("communicate")
        if kwargs:
            raise subprocess.TimeoutExpired("render", kwargs["timeout"])
        return "", ""
    process.communicate.side_effect = communicate
    def popen(command, **kwargs):
        assert kwargs["start_new_session"] is True
        return process
    monkeypatch.setattr(daily.subprocess, "Popen", popen)
    monkeypatch.setattr(daily.os, "killpg", lambda pid, sig: events.append((pid, sig)))
    with pytest.raises(subprocess.TimeoutExpired):
        daily._run(["render"], cwd=tmp_path, timeout=1)
    assert events == ["communicate", (91234, daily.signal.SIGKILL), "communicate"]
