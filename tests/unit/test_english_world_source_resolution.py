"""原声恢复的真实布局、不可变账本及失败关闭回归。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-09-22 | Codex | 逐写入节点故障注入验证续跑、原证据保留及未知修改拒绝覆盖。 |
| 1.0.0 | 2026-09-22 | Codex | 临时来源与合成复听记录验证，不调用模型或生产账本。 |
"""
import importlib.util
from pathlib import Path
import pytest
from video_processing.study_cards.display_plan import build_plan
from video_processing.study_cards.language_qa import validate_language_qa
from video_processing.study_cards.language_protocol import (
    VERSION, atomic_json, cache_key, digest, expected_checks, file_digest, read_json, review_input,
)
from video_processing.study_cards.caption_evidence import transcript_differences
from video_processing.study_cards.source_resolution import check_resolution, corrected_payload


def fixture(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"synthetic media evidence")
    caption = tmp_path / "caption.json3"
    atomic_json(caption, {"events": []})
    text = "A strategist at Example speaks."
    before = {"content_type": "ENGLISH_WORLD_SHORT", "language_contract": VERSION,
              "headline_zh": "测试原声", "headline_en": "Source fixture",
              "english_text": text, "translation_zh": "策略师讲话。",
              "paragraphs": [{"english_text": text, "translation_zh": "策略师讲话。"}],
              "words": [{"text": w, "start": i, "end": i + .8} for i, w in enumerate(text.split())],
              "learning_points": [], "vocabulary_candidates": [],
              "source_provenance": {"source_video": "source.mp4", "caption_artifact": "caption.json3",
                                    "source_start_seconds": 0, "source_end_seconds": 35},
              "publication_text": {"title": "测试", "copy": "合成测试", "cover_payload": {
                  "title": "测试", "quote_en": "A strategist speaks.", "quote_zh": "策略师讲话。",
                  "difficulty_tag": "A2", "audio_source": "fixture", "date_str": "test"}}}
    timeline = tmp_path / "timeline.json"
    atomic_json(timeline, before)
    plan = build_plan(before, file_digest(timeline))
    asr_text = text.replace(" at ", " and ")
    evidence = {"source_sha256": file_digest(source), "caption_sha256": file_digest(caption),
                "model_sha256": "first-model", "source_start": 0, "source_end": 35,
                "asr_text": asr_text, "timeline_differences": transcript_differences(text, asr_text),
                "asr_words": [{"word": w, "start": i, "end": i + .8} for i, w in enumerate(asr_text.split())]}
    editorial = {"version": VERSION, "revision": 1, "changes": []}
    findings = [{"check": c, "target": t, "status": "PASS", "severity": "NONE", "evidence": "fixture", "suggestion": ""}
                for c, t in sorted(expected_checks(plan, evidence, editorial))]
    next(f for f in findings if f["target"] == "timeline_differences:0").update(status="UNCERTAIN", severity="P2")
    report = {"version": VERSION, "state": "FAIL", "result": {"findings": findings},
              "input_projection": "compact-v1", "model": "fixture", "effort": "high",
              "plan_sha256": digest(plan), "timeline_sha256": file_digest(timeline),
              "input_key": cache_key(review_input(plan, evidence, editorial), "fixture", "high")}
    audio = tmp_path / "qa/source_word_confirmation.wav"
    audio.parent.mkdir()
    audio.write_bytes(b"synthetic PCM fixture")
    confirmation = {"state": "COMPLETE", "engine": "whisper-local-unprompted", "word_index": 2,
                    "source_sha256": evidence["source_sha256"], "timeline_sha256": file_digest(timeline),
                    "model_sha256": "second-model", "sample_rate": 16000, "channels": 1,
                    "source_start": 1, "source_end": 4, "audio_sha256": file_digest(audio),
                    "words": [{"word": " and", "start": 1.1, "end": 1.4, "probability": .98}]}
    for name, value in {"display_plan.json": plan, "qa/source_evidence.json": evidence,
                        "qa/language_qa.json": report, "editorial_changes.json": editorial,
                        "qa/source_word_confirmation.json": confirmation}.items():
        atomic_json(tmp_path / name, value)
    task, cache = tmp_path / "task", tmp_path / "cache"
    atomic_json(task / "language_attempts.json", {"attempts": 3, "retries": 1, "content_terminal": True,
                "keys": [report["input_key"]], "inflight": False})
    atomic_json(cache / (report["input_key"] + ".json"), {"result": report["result"]})
    return timeline, before, plan, report, evidence, editorial, confirmation, task, cache


def resolver():
    path = Path(__file__).resolve().parents[2] / "scripts/resolve_english_world_source_word.py"
    spec = importlib.util.spec_from_file_location("resolve_source_word", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.resolve


def test_resolution_preserves_failure_ledger_and_is_idempotent(tmp_path):
    timeline, before, *_, task, cache = fixture(tmp_path)
    original = {p: p.read_bytes() for p in [task / "language_attempts.json", tmp_path / "qa/language_qa.json",
                                          tmp_path / "qa/source_evidence.json"]}
    result = resolver()(timeline, word_index=2, task_dir=task, cache_dir=cache)
    assert result["state"] == "SOURCE_RESOLVED"
    assert result["independent_review_state"] == "FAIL"
    assert read_json(timeline) == corrected_payload(before, 2, "and")
    assert all(p.read_bytes() == value for p, value in original.items())
    assert validate_language_qa(timeline)["state"] == "SOURCE_RESOLVED"
    assert resolver()(timeline, word_index=2, task_dir=task, cache_dir=cache) == result
    receipt = read_json(tmp_path / "qa/source_resolution.json")
    manifest = tmp_path / "manifest.json"
    atomic_json(manifest, {"display_plan_sha256": receipt["plan_sha256"],
                          "language_qa_sha256": file_digest(tmp_path / "qa/language_qa.json")})
    with pytest.raises(ValueError, match="成片未绑定"):
        validate_language_qa(timeline, manifest=manifest)
    value = read_json(manifest)
    value["source_resolution_sha256"] = file_digest(tmp_path / "qa/source_resolution.json")
    atomic_json(manifest, value)
    assert validate_language_qa(timeline, manifest=manifest)["state"] == "SOURCE_RESOLVED"


@pytest.mark.parametrize("change", ["translation", "another_word", "timing", "publication", "model", "source", "confidence", "position", "second_issue", "p1", "coverage"])
def test_resolution_rejects_unsupported_changes(tmp_path, change):
    _, before, plan, report, evidence, editorial, confirmation, _, _ = fixture(tmp_path)
    after = corrected_payload(before, 2, "and")
    if change == "translation": after["translation_zh"] = "篡改"
    if change == "another_word": after["words"][0]["text"] = "The"
    if change == "timing": after["words"][2]["end"] += .2
    if change == "publication": after["publication_text"]["copy"] = "改文案"
    if change == "model": confirmation["model_sha256"] = evidence["model_sha256"]
    if change == "source": confirmation["source_sha256"] = "different"
    if change == "confidence": confirmation["words"][0]["probability"] = .5
    if change == "position": confirmation["words"][0]["start"] = 0
    if change == "second_issue": report["result"]["findings"][0]["status"] = "FAIL"
    if change == "p1":
        next(f for f in report["result"]["findings"] if f["status"] == "UNCERTAIN")["severity"] = "P1"
    if change == "coverage": report["result"]["findings"].pop()
    with pytest.raises(ValueError):
        check_resolution(before, after, plan, report, evidence, editorial, confirmation, index=2)


@pytest.mark.parametrize("name", ["timeline.json", "display_plan.json", "qa/language_qa.json", "qa/source_evidence.json",
    "editorial_changes.json", "source.mp4", "caption.json3", "qa/source_word_confirmation.json",
    "qa/source_word_confirmation.wav", "task/language_attempts.json", "qa/source_resolution/timeline.before.json"])
def test_resolution_rejects_evidence_tampering(tmp_path, name):
    timeline, *_, task, cache = fixture(tmp_path)
    resolver()(timeline, word_index=2, task_dir=task, cache_dir=cache)
    path = tmp_path / name
    if path.suffix == ".json":
        atomic_json(path, {**read_json(path), "tampered": True})
    else:
        path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError): validate_language_qa(timeline)


@pytest.mark.parametrize("after_write", [False, True])
@pytest.mark.parametrize("name", ["qa/source_resolution/timeline.after.json",
    "qa/source_resolution/display_plan.after.json", "qa/source_resolution/prepared_receipt.json",
    "timeline.json", "display_plan.json", "qa/source_resolution.json"])
def test_resolution_resumes_at_every_json_write(tmp_path, monkeypatch, name, after_write):
    timeline, before, *_, task, cache = fixture(tmp_path)
    original = {p: p.read_bytes() for p in [timeline, tmp_path / "display_plan.json",
                tmp_path / "qa/language_qa.json", task / "language_attempts.json"]}
    operation = resolver()
    write = operation.__globals__["atomic_json"]
    def interrupted(path, value):
        if path == tmp_path / name and not after_write:
            raise OSError("injected interruption")
        write(path, value)
        if path == tmp_path / name and after_write:
            raise OSError("injected interruption")
    monkeypatch.setitem(operation.__globals__, "atomic_json", interrupted)
    with pytest.raises(OSError, match="injected"):
        operation(timeline, word_index=2, task_dir=task, cache_dir=cache)
    monkeypatch.setitem(operation.__globals__, "atomic_json", write)
    assert operation(timeline, word_index=2, task_dir=task, cache_dir=cache)["state"] == "SOURCE_RESOLVED"
    assert validate_language_qa(timeline)["state"] == "SOURCE_RESOLVED"
    assert read_json(timeline) == corrected_payload(before, 2, "and")
    assert (tmp_path / "qa/source_resolution/timeline.before.json").read_bytes() == original[timeline]
    assert (tmp_path / "qa/source_resolution/display_plan.before.json").read_bytes() == original[tmp_path / "display_plan.json"]
    assert (tmp_path / "qa/language_qa.json").read_bytes() == original[tmp_path / "qa/language_qa.json"]
    assert (task / "language_attempts.json").read_bytes() == original[task / "language_attempts.json"]


@pytest.mark.parametrize("after_copy", [False, True])
@pytest.mark.parametrize("name", ["timeline.before.json", "display_plan.before.json"])
def test_resolution_resumes_partial_archive(tmp_path, monkeypatch, name, after_copy):
    timeline, *_, task, cache = fixture(tmp_path)
    operation = resolver()
    preserve = operation.__globals__["_preserve_file"]
    def interrupted(source, target, expected, **kwargs):
        if target.name == name and not after_copy:
            raise OSError("injected archive interruption")
        preserve(source, target, expected, **kwargs)
        if target.name == name and after_copy:
            raise OSError("injected archive interruption")
    monkeypatch.setitem(operation.__globals__, "_preserve_file", interrupted)
    with pytest.raises(OSError, match="injected"):
        operation(timeline, word_index=2, task_dir=task, cache_dir=cache)
    monkeypatch.setitem(operation.__globals__, "_preserve_file", preserve)
    assert operation(timeline, word_index=2, task_dir=task, cache_dir=cache)["state"] == "SOURCE_RESOLVED"


@pytest.mark.parametrize("changed", ["timeline.json", "display_plan.json", "task/language_attempts.json",
    "qa/source_resolution/timeline.before.json", "qa/source_resolution/display_plan.after.json",
    "qa/source_word_confirmation.wav", "source.mp4", "cache"])
def test_resume_refuses_new_edits_without_overwriting_live_inputs(tmp_path, monkeypatch, changed):
    timeline, *_, task, cache = fixture(tmp_path)
    operation = resolver()
    write = operation.__globals__["atomic_json"]
    def interrupted(path, value):
        if path == timeline:
            raise OSError("injected commit interruption")
        write(path, value)
    monkeypatch.setitem(operation.__globals__, "atomic_json", interrupted)
    with pytest.raises(OSError, match="injected"):
        operation(timeline, word_index=2, task_dir=task, cache_dir=cache)
    monkeypatch.setitem(operation.__globals__, "atomic_json", write)
    path = next(cache.glob("*.json")) if changed == "cache" else tmp_path / changed
    if path.suffix == ".json":
        atomic_json(path, {**read_json(path), "unknown_edit": True})
    else:
        path.write_bytes(path.read_bytes() + b"unknown edit")
    live = {p: p.read_bytes() for p in [timeline, tmp_path / "display_plan.json"]}
    with pytest.raises(ValueError):
        operation(timeline, word_index=2, task_dir=task, cache_dir=cache)
    assert all(p.read_bytes() == value for p, value in live.items())
    assert not (tmp_path / "qa/source_resolution.json").exists()
