"""最终成片视觉安全回执：AGY 只可审阅哈希绑定的九帧联系表。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| timeout-v1 | 2026-10-20 | Codex | 验证宿主超时分类与空输出失败关闭，保持全文及九帧输入合同。 |
| fallback-v1 | 2026-10-20 | Codex | 验证独立备用通道及其预算、输入、证据与失败关闭边界。 |
| 1.0.0 | 2026-09-17 | Codex | 覆盖 high-effort AGY 参数、风险阻断及复核中产物变更的失败关闭。 |
"""

from __future__ import annotations

from hashlib import sha256

import pytest

from scripts import english_world_visual_safety_review as review


def _fake_contact_sheet(_mp4, contact_sheet, **_kwargs):
    contact_sheet.parent.mkdir(parents=True, exist_ok=True)
    contact_sheet.write_bytes(b"contact-sheet")
    return 42.0, (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0)


def test_visual_review_uses_sandboxed_agy_high_effort_and_binds_current_mp4(monkeypatch, tmp_path):
    mp4 = tmp_path / "video.mp4"
    mp4.write_bytes(b"video")
    contact_sheet = tmp_path / "qa/contact.png"
    monkeypatch.setattr(review, "_extract_contact_sheet", _fake_contact_sheet)
    captured = {}

    def fake_agy(**kwargs):
        captured.update(kwargs)
        assert (kwargs["work_dir"] / "contact_sheet.png").is_file()
        return {"state": "PASS", "coverage": "SUFFICIENT", "risk_categories": []}

    monkeypatch.setattr(review, "_run_agy", fake_agy)
    receipt = review.review_video(
        mp4=mp4, contact_sheet=contact_sheet, agy_bin="agy-test", model="gemini-3.8-flash-high",
        timeout_seconds=60,
    )

    assert receipt["state"] == "PASS"
    assert receipt["effort"] == "high"
    assert receipt["mp4_sha256"] == sha256(b"video").hexdigest()
    assert receipt["contact_sheet"] == str(contact_sheet.resolve())
    assert receipt["contact_sheet_sha256"] == sha256(b"contact-sheet").hexdigest()
    assert captured["agy_bin"] == "agy-test"
    assert captured["model"] == "gemini-3.8-flash-high"


def test_visual_review_blocks_any_model_reported_risk(monkeypatch, tmp_path):
    mp4 = tmp_path / "video.mp4"
    mp4.write_bytes(b"video")
    monkeypatch.setattr(review, "_extract_contact_sheet", _fake_contact_sheet)
    monkeypatch.setattr(
        review,
        "_run_agy",
        lambda **_kwargs: {
            "state": "PASS", "coverage": "SUFFICIENT", "risk_categories": ["war_or_weapons"],
        },
    )

    receipt = review.review_video(
        mp4=mp4, contact_sheet=tmp_path / "contact.png", agy_bin="agy", model="model", timeout_seconds=60,
    )

    assert receipt["state"] == "BLOCKED"
    assert receipt["risk_categories"] == ["war_or_weapons"]


def test_visual_review_rejects_when_mp4_changes_during_review(monkeypatch, tmp_path):
    mp4 = tmp_path / "video.mp4"
    mp4.write_bytes(b"before")
    monkeypatch.setattr(review, "_extract_contact_sheet", _fake_contact_sheet)

    def mutate_mp4(**_kwargs):
        mp4.write_bytes(b"after")
        return {"state": "PASS", "coverage": "SUFFICIENT", "risk_categories": []}

    monkeypatch.setattr(review, "_run_agy", mutate_mp4)

    with pytest.raises(review.VisualSafetyReviewError, match="MP4 发生变化"):
        review.review_video(
            mp4=mp4, contact_sheet=tmp_path / "contact.png", agy_bin="agy", model="model", timeout_seconds=60,
        )



@pytest.mark.parametrize("coverage,expected", [("SUFFICIENT", "PASS"), ("INSUFFICIENT", "FAIL_CLOSED"), (None, "FAIL_CLOSED")])
def test_fulltext_is_supplied_and_coverage_is_mandatory(monkeypatch, tmp_path, coverage, expected):
    import json
    timeline = tmp_path / "timeline.json"
    timeline.write_text(json.dumps({"english_text": "All source words.", "translation_zh": "完整中文。",
                                   "publication_text": {"title": "今日新闻", "copy": "读新闻。"}}))
    (tmp_path / "qa").mkdir()
    (tmp_path / "qa/source_evidence.json").write_text(json.dumps({"asr_text": "All source words."}))
    (tmp_path / "display_plan.json").write_text("{}")
    mp4 = tmp_path / "video.mp4"
    mp4.write_bytes(b"video")
    monkeypatch.setattr(review, "_extract_contact_sheet", _fake_contact_sheet)
    def caller(**kwargs):
        supplied = json.loads((kwargs["work_dir"] / "safety_text.json").read_text())
        assert "All source words." in supplied["documents"][0]["en_text"]
        assert "完整中文。" in supplied["documents"][1]["zh_text"]
        return {"state": "PASS", "coverage": "SUFFICIENT", "risk_categories": [], "text_coverage": coverage}
    monkeypatch.setattr(review, "_run_agy", caller)
    receipt = review.review_video(mp4=mp4, contact_sheet=tmp_path / "qa/contact.png", agy_bin="agy",
                                  model="gemini-3.8-flash-high", timeout_seconds=60, timeline=timeline)
    assert receipt["state"] == expected
    assert receipt["text_review"]["input_sha256"] == review.fulltext_safety_input(timeline)["input_sha256"]


def test_fulltext_mutation_during_review_is_rejected(monkeypatch, tmp_path):
    import json
    timeline = tmp_path / "timeline.json"
    timeline.write_text(json.dumps({"english_text": "Clean energy.", "translation_zh": "清洁能源。"}))
    (tmp_path / "qa").mkdir()
    (tmp_path / "qa/source_evidence.json").write_text(json.dumps({"asr_text": "Clean energy."}))
    (tmp_path / "display_plan.json").write_text("{}")
    mp4 = tmp_path / "video.mp4"
    mp4.write_bytes(b"video")
    monkeypatch.setattr(review, "_extract_contact_sheet", _fake_contact_sheet)
    def caller(**kwargs):
        timeline.write_text(json.dumps({"english_text": "Changed text."}))
        return {"state": "PASS", "coverage": "SUFFICIENT", "risk_categories": [], "text_coverage": "SUFFICIENT"}
    monkeypatch.setattr(review, "_run_agy", caller)
    with pytest.raises(review.VisualSafetyReviewError, match="最终文本发生变化"):
        review.review_video(mp4=mp4, contact_sheet=tmp_path / "qa/contact.png", agy_bin="agy",
                            model="gemini-3.8-flash-high", timeout_seconds=60, timeline=timeline)


@pytest.mark.parametrize('coverage,expected', [('SUFFICIENT', 'PASS'), ('INSUFFICIENT', 'FAIL_CLOSED')])
def test_codex_fallback_receives_actual_image_and_fulltext(monkeypatch, tmp_path, coverage, expected):
    import json
    timeline = tmp_path / 'timeline.json'
    timeline.write_text(json.dumps({'english_text': 'Clean energy.', 'translation_zh': '清洁能源。'}))
    (tmp_path / 'qa').mkdir()
    (tmp_path / 'qa/source_evidence.json').write_text(json.dumps({'asr_text': 'Clean energy.'}))
    (tmp_path / 'display_plan.json').write_text('{}')
    mp4 = tmp_path / 'video.mp4'
    mp4.write_bytes(b'video')
    monkeypatch.setattr(review, '_extract_contact_sheet', _fake_contact_sheet)
    monkeypatch.setattr(review.ProviderRouter, 'ready', lambda self, selected: selected.name == 'codex')
    def call(selected, prompt, **kwargs):
        assert selected.name == 'codex' and selected.effort == 'high'
        assert 'Clean energy.' in prompt and '清洁能源。' in prompt
        assert len(kwargs['images']) == 1 and kwargs['images'][0].read_bytes() == b'contact-sheet'
        return {'structured_result': {'state': 'PASS', 'coverage': 'SUFFICIENT',
                    'risk_categories': [], 'text_coverage': coverage}}
    monkeypatch.setattr(review.Provider, 'call', call)
    receipt = review.review_video(mp4=mp4, contact_sheet=tmp_path / 'qa/contact.png', agy_bin='agy',
        model='gemini-3.8-flash-high', timeout_seconds=60, timeline=timeline, allow_fallback=True)
    assert receipt['provider'] == 'codex' and receipt['state'] == expected
    assert receipt['text_review']['input_sha256'] == review.fulltext_safety_input(timeline)['input_sha256']


def test_visual_agy_uses_host_timeout_and_rejects_empty_success(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    from video_processing.utils.english_world_provider import infrastructure_error

    def timeout(args, **kwargs):
        assert args[args.index("--print-timeout") + 1] == "0s"
        assert kwargs["timeout"] == 16
        raise review.subprocess.TimeoutExpired(args, 16, output="private source text")
    monkeypatch.setattr(review.subprocess, "run", timeout)
    with pytest.raises(review.AgyProviderError) as exc:
        review._run_agy(agy_bin="agy", model="test", work_dir=tmp_path, timeout_seconds=1)
    assert infrastructure_error(exc.value) and "private" not in str(exc.value)
    monkeypatch.setattr(review.subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=0, stdout=json.dumps({"status": "SUCCESS", "response": ""}), stderr=""))
    with pytest.raises(review.VisualSafetyReviewError):
        review._run_agy(agy_bin="agy", model="test", work_dir=tmp_path, timeout_seconds=1)
