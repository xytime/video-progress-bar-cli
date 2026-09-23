"""片段外技术缺陷不能否决片段；片段内与内容安全规则保持阻断。"""
from copy import deepcopy

import pytest

from scripts import english_world_language as language
from scripts import english_world_programmatic_daily as daily
from video_processing.study_cards.asr_window import validate_window
from video_processing.study_cards.language_qa import atomic_json, read_json, file_digest, task_identity


def raw_words():
    return [{"word": "The", "start": 0., "end": .2},
            {"word": "report", "start": .2, "end": 30.},
            {"word": "ends.", "start": 30., "end": 43.14},
            {"word": "Kira,", "start": 64.66, "end": 64.66}]


def test_tail_zero_width_keeps_full_context_but_does_not_veto_window():
    raw = raw_words()
    original = deepcopy(raw)
    words, repairs, window = validate_window(raw, 120)
    assert words == raw[:3] and not repairs
    assert window["source_end"] == 43.14 and window["context_word_count"] == 1
    assert raw == original


@pytest.mark.parametrize("kind", ["inside", "crossing", "regression", "nan"])
def test_uncertain_evidence_in_or_crossing_window_still_blocks(kind):
    raw = raw_words()
    if kind == "inside":
        raw[0]["end"] = 0.
    elif kind == "crossing":
        raw[-1]["start"] = 43.
    elif kind == "regression":
        raw.append({"word": "missed", "start": 10., "end": 11.})
    else:
        raw[-1]["start"] = float("nan")
    with pytest.raises(ValueError, match="UNCERTAIN"):
        validate_window(raw, 120)


def test_first_sentence_failure_cannot_skip_to_later_sentence():
    raw = raw_words()
    raw[2]["start"] = raw[2]["end"]
    raw.append({"word": "Later.", "start": 70., "end": 71.})
    with pytest.raises(ValueError, match="UNCERTAIN"):
        validate_window(raw, 120)


def test_historical_medium_failure_is_preserved_and_projection_reuses_no_model(tmp_path, monkeypatch):
    source, small, medium = (tmp_path / name for name in ("source.mp4", "small.pt", "medium.pt"))
    for path in (source, small, medium):
        path.write_bytes(path.name.encode())
    caption = daily._make_bootstrap_caption(tmp_path, duration=120)
    timeline = tmp_path / "timeline.json"
    payload = {"english_text": "pending", "source_provenance": {
        "source_video": str(source), "caption_artifact": str(caption),
        "caption_format": "local_whisper_bootstrap", "source_start_seconds": 0., "source_end_seconds": 120.}}
    atomic_json(timeline, payload)
    binding = {"source_sha256": file_digest(source), "caption_sha256": file_digest(caption),
               "source_start": 0., "source_end": 120., "caption_parser_version": language.PARSER_VERSION}
    raw = {**binding, "model_sha256": file_digest(medium), "sample_rate": 16000, "channels": 1,
           "asr_text": "The report ends. Kira,", "raw_words": raw_words()}
    tasks = tmp_path / "tasks"
    task = tasks / task_identity(binding)
    receipt = task / "source_recheck.json"
    atomic_json(receipt, {"binding": binding, "status": "FAIL", "attempts": 1, "medium_raw": raw})
    original_receipt = receipt.read_bytes()
    def no_model(*args, **kwargs):
        pytest.fail("缓存恢复不应调用 ASR")
    monkeypatch.setattr(language, "source_evidence", no_model)
    language.source_evidence_with_recheck(timeline, small, medium, tasks)
    evidence = read_json(tmp_path / "qa/source_evidence.json")
    assert evidence["bootstrap_window"]["source_end"] == 43.14
    assert receipt.read_bytes() == original_receipt
    assert read_json(task / "bootstrap_scope_recheck.json")["additional_model_calls"] == 0
    moved = tmp_path / "moved/timeline.json"
    atomic_json(moved, payload)
    language.source_evidence_with_recheck(moved, small, medium, tasks)
    assert read_json(moved.parent / "qa/source_evidence.json")["bootstrap_window"] == evidence["bootstrap_window"]
    assert receipt.read_bytes() == original_receipt
    words = daily._frozen_words(evidence)
    derived = daily._make_bootstrap_caption(tmp_path, duration=43.14, words=words)
    payload["source_provenance"].update(caption_artifact=str(derived), source_end_seconds=43.14)
    payload["english_text"] = "The report ends."
    atomic_json(timeline, payload)
    language.bind_bootstrap_evidence(timeline, parent={"raw": raw, "parent_caption": str(caption)})
    language.source_evidence_with_recheck(timeline, small, medium, tasks)
    projected = read_json(tmp_path / "qa/source_evidence.json")
    assert projected["asr_words_raw"] == raw_words()
    assert projected["source_end"] == 43.14 and not projected["timeline_differences"]
    assert projected["asr_context_text"] == raw["asr_text"]
    assert receipt.read_bytes() == original_receipt
    changed = read_json(derived)
    changed["events"][0]["dDurationMs"] += 10
    atomic_json(derived, changed)
    with pytest.raises(ValueError, match="锚点"):
        language.source_evidence_with_recheck(timeline, small, medium, tasks)


def test_content_safety_still_blocks_selected_transcript(tmp_path):
    from video_processing.english_world.safety_gate import EnglishWorldSafetyGateError
    with pytest.raises(EnglishWorldSafetyGateError):
        daily._candidate_safety_preflight(
            {"source_title": "A dangerous news story", "source_channel": "ABC News"},
            timeline={"english_text": "fentanyl trafficking and gambling"},
            receipt_path=tmp_path / "safety.json")
    assert read_json(tmp_path / "safety.json")["state"] == "BLOCKED"
