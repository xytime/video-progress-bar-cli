"""普通事实疑点不可停发；确定性引证与语义复核结果分别归档。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-10-09 | Codex | 验证双语跨事件引文不会被译文或生词注释干扰 |
"""
import copy
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import pysubs2

from video_processing.core.insight_script import InsightScriptV2
from video_processing.processors import insight_processor
from video_processing.utils import insight_evidence as evidence
from video_processing.utils.insight_v2_prompt import FEW_SHOT_EXAMPLE_CORNELL
from video_processing.utils.insight_planner import verify_vtt_evidence


@pytest.fixture
def case(tmp_path):
    data = copy.deepcopy(FEW_SHOT_EXAMPLE_CORNELL)
    quote = "The governor cannot appoint a prosecutor without legislative approval"
    for card in data["cards"]:
        for point in card["points"]:
            point["vtt_reference"] = {"start_sec": 1, "end_sec": 8, "source_quote": quote}
    subtitle = tmp_path / "source.srt"
    subtitle.write_text(f"1\n00:00:01,000 --> 00:00:08,000\n{quote}\n")
    return InsightScriptV2.model_validate(data), subtitle


@pytest.mark.parametrize("mutation", ["negation", "order", "number"])
def test_quote_mutations_are_not_certified(case, mutation):
    script, subtitle = case
    assert verify_vtt_evidence(script, subtitle)
    ref = script.cards[0].points[0].vtt_reference
    if mutation == "negation":
        ref.source_quote = ref.source_quote.replace("cannot", "can")
    elif mutation == "order":
        ref.source_quote = "The prosecutor cannot appoint a governor without legislative approval"
    else:
        ref.source_quote += " 100"
    assert not verify_vtt_evidence(script, subtitle)


def test_bilingual_split_quote_excludes_translation_and_glossary(case, tmp_path):
    script, _ = case
    subtitle = tmp_path / 'bilingual.ass'
    subs = pysubs2.SSAFile()
    subs.events = [
        pysubs2.SSAEvent(start=1000,end=3000,text='The governor cannot\\N州长不能，数量99'),
        pysubs2.SSAEvent(start=3000,end=5000,text='appoint a prosecutor without\\N任命检察官'),
        pysubs2.SSAEvent(start=5000,end=8000,text='legislative approval\\N立法批准'),
        pysubs2.SSAEvent(start=1000,end=8000,style='GlossaryCard',
            text='The governor can appoint a prosecutor without legislative approval'),
    ]
    subs.save(str(subtitle))
    assert verify_vtt_evidence(script, subtitle)
    script.cards[0].points[0].vtt_reference.source_quote = script.cards[0].points[0].vtt_reference.source_quote.replace('cannot','can')
    assert not verify_vtt_evidence(script, subtitle)


def test_bilingual_translation_number_cannot_certify_english_quote(case, tmp_path):
    script, _ = case
    subtitle = tmp_path / 'numbers.ass'
    subs = pysubs2.SSAFile()
    subs.events = [
        pysubs2.SSAEvent(start=1000,end=4000,text='Loans run 72\\N贷款36个月'),
        pysubs2.SSAEvent(start=4000,end=8000,text='to 84 months\\N到99个月'),
    ]
    subs.save(str(subtitle))
    for card in script.cards:
        for point in card.points:
            point.vtt_reference.source_quote = 'Loans run 72 to 84 months'
    assert verify_vtt_evidence(script, subtitle)
    script.cards[0].points[0].vtt_reference.source_quote = 'Loans run 72 to 99 months'
    assert not verify_vtt_evidence(script, subtitle)


def test_chinese_fabrication_sent_to_independent_review_and_persisted(case, tmp_path, monkeypatch):
    script, subtitle = case
    script.cards[0].points[0].explanation = "州长拥有不受任何限制的直接定罪权力"
    def reviewer(prompt, **kwargs):
        assert script.cards[0].points[0].explanation in prompt
        assert "cannot appoint" in prompt
        assert "hook.title/narration" in prompt and "outro" in prompt
        assert kwargs["timeout_sec"] <= 45
        return kwargs["validate"]({"status": "NEEDS_REVIEW", "findings": [{
            "field": "cards[0].points[0].explanation", "issue": "字幕未赋予州长直接定罪权",
            "suggestion": "区分任命权限与司法裁判权限"}]})
    service = Mock(side_effect=reviewer)
    monkeypatch.setattr(evidence, "generate_cached_agy_copy", service)
    path = tmp_path / "evidence.json"
    result = evidence.review_evidence(script, subtitle, path)
    assert all(check["quote_matched"] for check in result["quote_checks"])
    assert result["status"] == "NEEDS_REVIEW"
    assert result["publication_blocked"] is False
    assert result == json.loads(path.read_text())
    assert evidence.review_evidence(script, subtitle, path) == result
    assert service.call_count == 1
    script.cards[0].points[0].keyword = "权限边界"
    evidence.review_evidence(script, subtitle, path)
    assert service.call_count == 2


@pytest.mark.parametrize("failure", ["timeout", "malformed", "missing_subtitle", "unwritable_report"])
def test_review_failure_is_advisory(case, tmp_path, monkeypatch, failure):
    script, subtitle = case
    service = Mock(side_effect=TimeoutError)
    if failure == "malformed":
        service = Mock(return_value={"status": "NO_ISSUE_FOUND", "findings": "invalid"})
    elif failure == "missing_subtitle":
        subtitle = tmp_path / "missing.srt"
    monkeypatch.setattr(evidence, "generate_cached_agy_copy", service)
    report = tmp_path / "absent/report.json" if failure == "unwritable_report" else tmp_path / "review.json"
    result = evidence.review_evidence(script, subtitle, report)
    assert result["status"] == "UNREVIEWED"
    assert not result["publication_blocked"]


def test_masterpiece_continues_render_with_semantic_warning(case, tmp_path, monkeypatch):
    import scripts.run_masterpiece as runner
    script, subtitle = case
    script_path, source = tmp_path / "script.json", tmp_path / "base.mp4"
    script_path.write_text(script.model_dump_json())
    source.write_bytes(b"source")
    monkeypatch.setattr(evidence, "generate_cached_agy_copy", Mock(side_effect=TimeoutError))
    called = []
    class Processor:
        def process(self, src, plan, output, **kwargs):
            called.append(output)
            return False  # 到达渲染即证明普通复核不可用没有拦截；媒体失败仍真实报告。
    monkeypatch.setattr(runner, "InsightProcessor", Processor)
    monkeypatch.setattr(runner, "PipelineDB", Mock())
    with pytest.raises(RuntimeError, match="母带渲染失败"):
        runner.run_masterpiece_pipeline(script.video_id, tmp_path, source, subtitle, script_path)
    assert called == [tmp_path / f"masterpiece_{script.video_id}.mp4"]
    report = json.loads(script_path.with_suffix(".evidence.json").read_text())
    assert report["status"] == "UNREVIEWED"


def test_legacy_script_rejected_before_render(tmp_path):
    legacy = InsightScriptV2.model_validate(FEW_SHOT_EXAMPLE_CORNELL).to_legacy_v1(180)
    path = tmp_path / "old.json"
    path.write_text(legacy.model_dump_json())
    tts = Mock()
    assert not insight_processor.InsightProcessor(tts=tts).process(tmp_path / "source.mp4", path, tmp_path / "out.mp4")
    tts.generate_audio.assert_not_called()


def test_render_asset_change_invalidates_spec(tmp_path, monkeypatch):
    before = insight_processor.render_spec()
    font = tmp_path / "font.otf"
    font.write_bytes(b"different-font")
    monkeypatch.setattr(insight_processor, "font_path", lambda: font)
    assert insight_processor.render_spec() != before
