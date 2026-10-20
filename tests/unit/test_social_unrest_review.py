"""社会动荡题材：漏判/误判、完整字幕、原输入复核及上传边界。

真实规则、临时 SQLite、实际 VTT/ASS；不接触历史库或平台。
"""
from unittest.mock import Mock
import json
from pathlib import Path

import pytest
import pysubs2
from fastapi.testclient import TestClient

from config.settings import settings
from video_processing import censor_engine, social_unrest_review as review
from video_processing.core.social_unrest import DEFAULT_RULES, classify
from video_processing.pipeline_manager import PipelineManager


@pytest.mark.parametrize("text", [
    "Paris Protests Erupt Over High Fuel Costs & Trump Cuts Diesel Deal with Russia | The Daily Show",
    "法国周末抗议源于生活成本压力，局势随后演变为抢掠与街头冲突。",
    "Riots erupt in Paris over high fuel costs", "Rioting and looting spread overnight",
    "Civil unrest spreads", "Street clashes reported", "Clashes with police continue",
    "Workers protest rising prices", "Protesters marched peacefully",
    "Students demonstrated in the streets", "Demonstrators gathered outside parliament",
    "The government faces nationwide demonstrations", "A mass rally begins",
    "Workers are striking over pay", "Unions announce a general strike",
    "A road blockade by workers", "An uprising against the regime",
    "An insurrection outside government buildings", "Rebellion against the regime",
    "They are overthrowing the regime", "Protesters take to the streets",
    "民众上街示威反对油价上涨", "工人举行全国罢工", "号召上街推翻政权",
    "今晨警方报告纵火和暴乱", "ＲＩＯＴＳ erupt", "The protests erupted in Argentina", "街头暴\n乱",
    "A stock rally is followed by riots in the streets", "A robot demonstration as protesters march outside",
    "Riots erupt today recalling the French Revolution in 1789",
])
def test_recall(text):
    assert classify(review.text_documents(title=text), DEFAULT_RULES), text


@pytest.mark.parametrize("text", [
    "AI revolution transforms industry", "The AI revolution improves government services",
    "工业革命如何改变生产率", "French Revolution in 1789: a historical account",
    "1968 student protests and police: a historical account", "Stock market rally lifts prices",
    "A rally in bond prices", "A stock rally follows government stimulus",
    "Solar flares strike the atmosphere", "The baseball player strikes out",
    "A demonstration of a new AI chip", "产品功能演示与芯片技术革命",
    "Patriot battery technology", "The developer protests an API rename",
    "A Star Wars rebellion strategy game", "Fuel costs are falling",
    "Police review the new camera. The AI revolution changes manufacturing.",
    "A demonstration of a police robot", "Students learn how a pitcher strikes out",
])
def test_precision(text):
    assert classify(review.text_documents(title=text), DEFAULT_RULES) is None, text


def test_no_cross_sentence_or_document_cooccurrence():
    documents = review.text_documents(title="A demonstration of an AI chip.", description="Police discuss equipment.")
    assert classify(documents, DEFAULT_RULES) is None
    assert classify(review.text_documents(subtitle="A demonstration of an AI chip. " + "Safe content. " * 100 + "Police discuss equipment."), DEFAULT_RULES) is None


@pytest.fixture
def manager(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "enable_censorship_engine", True)
    monkeypatch.setattr(settings, "enable_channel_policy_filter", True)
    monkeypatch.setattr(settings, "enable_external_censor_rules", False)
    monkeypatch.setattr(settings, "enable_channel_policy_fail_open", False)
    monkeypatch.setattr(settings, "enable_blacklist_tombstone", False)
    monkeypatch.setattr(settings, "enable_deep_insight_enrichment", False)
    instance = PipelineManager(str(tmp_path / "pipeline.db"))
    instance._OUT_DIR = tmp_path
    instance._ORIG_VIDEO_DIR = tmp_path / "original_video"
    instance._ORIG_VIDEO_DIR.mkdir(exist_ok=True)
    instance.send_telegram_msg = lambda *_: None
    instance.db.add_video("unrest", "Daily technology update", "trusted", score=90)
    return instance


def vtt(root, text, *, name="unrest_source_subtitle.en.vtt", start="00:00:10.000"):
    path = root / name
    path.write_text(f"WEBVTT\n\n{start} --> 00:00:15.000\n{text}\n", encoding="utf-8")
    return path


def ass(root, text, *, name="unrest.ass"):
    subs = pysubs2.SSAFile()
    subs.append(pysubs2.SSAEvent(start=10000, end=15000, text=text))
    path = root / name
    subs.save(str(path))
    return path


def test_legacy_bypass_and_trusted_channel_cannot_bypass_new_risk(manager, monkeypatch):
    monkeypatch.setattr(type(settings), "censorship_bypass_channel_set", property(lambda _: {"trusted"}))
    manager.db.set_bypass_censorship("unrest", True)
    assert manager._check_censorship("unrest", "Paris Protests Erupt Over High Fuel Costs")
    row = manager.db.get_video_by_youtube_id("unrest")
    assert row["status"] == "FAILED" and row["censor_tag"] == review.TAG
    incident = manager.db.get_censorship_incidents("unrest")[0]
    assert incident["stage"] == "social_unrest" and incident["level"] == "RISK"
    assert incident["input_hash"] and incident["rule_pack_version"]


def test_source_subtitle_blocks_before_download(manager):
    vtt(manager._OUT_DIR, "Peaceful protesters march over high fuel costs.")
    manager._run_tracked = Mock()
    assert not manager._ensure_source_subtitle_preflight(manager.db.get_video_by_youtube_id("unrest"))
    manager._run_tracked.assert_not_called()
    incident = manager.db.get_censorship_incidents("unrest")[0]
    evidence = review.replay(manager.db.get_video_by_youtube_id("unrest"), incident, manager._OUT_DIR)
    assert evidence["status"] == "VERIFIED_REPLAY"
    assert evidence["terms"][0]["locations"][0]["start"] == "00:00:10.000"


def test_subtitle_tail_after_40000_chars_is_checked_at_final_boundary(manager):
    root = manager._OUT_DIR
    ass(root, "Safe technology update. " * 2500 + " Riots erupted in the streets.")
    title, copy = root / "unrest_title.txt", root / "unrest_copy.txt"
    title.write_text("科技观察", encoding="utf-8")
    copy.write_text("今日科技观察", encoding="utf-8")
    manager.db.add_video("historic", "Historic published", "channel", score=90)
    manager.db.update_video_status("historic", "PUBLISHED")
    before = manager.db.get_video_by_youtube_id("historic")
    manager._run_tracked = Mock()
    manager._publish_prepared_assets(manager.db.get_video_by_youtube_id("unrest"), copy, title,
                                     root / "unrest_category.txt", root / "unrest_cover.jpg")
    manager._run_tracked.assert_not_called()
    assert manager.db.get_video_by_youtube_id("unrest")["status"] == "FAILED"
    assert manager.db.get_video_by_youtube_id("historic") == before
    incident = manager.db.get_censorship_incidents("unrest")[0]
    evidence = review.replay(manager.db.get_video_by_youtube_id("unrest"), incident, root)
    assert evidence["status"] == "VERIFIED_REPLAY"
    assert evidence["terms"][0]["offset_start"] > 40000


def test_final_gate_keeps_original_title_and_checks_cover_text(manager):
    root = manager._OUT_DIR
    ass(root, "A safe technology update.")
    (root / "unrest_display_title.txt").write_text("法国街头爆发示威", encoding="utf-8")
    assert manager._check_censorship("unrest", "科技观察", zh_title="科技观察", stage="wechat_publish", fail_closed=True)
    assert manager.db.get_censorship_incidents("unrest")[0]["source_field"].startswith("cover_text:")
    (root / "unrest_display_title.txt").write_text("科技观察", encoding="utf-8")
    manager.db.add_video("original", "Paris protests erupt over fuel costs", "channel", score=90)
    ass(root, "A safe technology update.", name="original.ass")
    assert manager._check_censorship("original", "科技观察", zh_title="科技观察", stage="wechat_publish", fail_closed=True)
    assert manager.db.get_censorship_incidents("original")[0]["source_field"] == "source_title"


def test_final_missing_or_broken_evidence_fails_closed(manager):
    assert manager._check_censorship("unrest", "Technology", stage="wechat_publish", fail_closed=True)
    assert "fail-closed" in manager.db.get_video_by_youtube_id("unrest")["error_msg"]
    (manager._OUT_DIR / "unrest.ass").write_text("not an ASS subtitle", encoding="utf-8")
    assert manager._check_censorship("unrest", "Technology", stage="wechat_publish", fail_closed=True)


def test_cue_time_window_does_not_join_far_apart_text(tmp_path):
    path = vtt(tmp_path, "A demonstration showing a chip", start="00:00:00.000")
    path.write_text(path.read_text() + "\n01:00:00.000 --> 01:00:02.000\nPolice discuss cameras\n")
    documents = review.collect_documents({"youtube_id": "unrest"}, tmp_path, title="Tech", stage="source_subtitle_preflight")
    assert review.evaluate(documents) is None


def test_adjacent_cues_supply_context(tmp_path):
    path = vtt(tmp_path, "A demonstration", start="00:00:10.000")
    path.write_text(path.read_text() + "\n00:00:15.000 --> 00:00:20.000\nwith workers in the streets\n")
    documents = review.collect_documents({"youtube_id": "unrest"}, tmp_path, title="News", stage="source_subtitle_preflight")
    evidence = review.evaluate(documents)
    assert evidence and len(evidence["terms"]) == 2
    assert 0 <= evidence["gap"] <= evidence["max_gap"]
    assert evidence["terms"][1]["locations"][0]["start"] == "00:00:15.000"


def test_actual_recorded_cover_typography_is_reviewed(manager):
    root = manager._OUT_DIR
    ass(root, "A safe update.")
    (root / "unrest_cover_provenance.json").write_text(json.dumps({
        "rendered_typography": {"bounds": [{"text": "街头暴"}, {"text": "乱"}]}}))
    assert manager._check_censorship("unrest", "Tech", stage="wechat_publish", fail_closed=True)
    assert manager.db.get_censorship_incidents("unrest")[0]["source_field"].startswith("cover_rendered_text:")


def test_rules_change_invalidates_manual_approval(manager, monkeypatch):
    vtt(manager._OUT_DIR, "Protesters march over fuel costs.")
    assert manager._check_censorship("unrest", "Tech", stage="source_subtitle_preflight", fail_closed=True)
    incident = manager.db.get_censorship_incidents("unrest")[0]
    manager.db.record_censorship_incident(
        "unrest", stage="manual_review", level="RISK", action="MANUAL_BYPASS", tag=review.TAG,
        score=None, matched=incident["matched"], channel="operator", decision=review.APPROVAL,
        input_hash=incident["input_hash"], rule_pack_version=incident["rule_pack_version"])
    assert not manager._check_censorship("unrest", "Tech", stage="source_subtitle_preflight", fail_closed=True)
    monkeypatch.setattr(censor_engine, "current_rules_fingerprint", lambda: "changed-rule-version")
    assert manager._check_censorship("unrest", "Tech", stage="source_subtitle_preflight", fail_closed=True)


def test_old_and_invalid_external_rules_keep_category(monkeypatch):
    old = censor_engine.dump_default_rules()
    del old["channel_policy"]["social_unrest"]
    assert censor_engine._validate_rules(old)[1]["social_unrest"] == DEFAULT_RULES
    bad = censor_engine.dump_default_rules()
    bad["channel_policy"]["social_unrest"]["families"]["unrest"]["terms"] = []
    with pytest.raises(ValueError):
        censor_engine._validate_rules(bad)


def test_slice_inputs_exclude_parent_and_other_slices(tmp_path):
    vtt(tmp_path, "Riots erupt in Paris.")
    ass(tmp_path, "Riots erupt in Paris.", name="unrest_s11.ass")
    ass(tmp_path, "A safe technology update.", name="unrest_s1.ass")
    documents = review.collect_documents({"youtube_id": "unrest", "slice_index": 1}, tmp_path,
                                         title="Tech", stage="wechat_publish")
    assert review.evaluate(documents) is None


def test_manual_review_binds_input_and_rules(manager, monkeypatch):
    import web.app
    root = manager._OUT_DIR
    source = vtt(root, "Protesters march over fuel costs.")
    assert manager._check_censorship("unrest", "Daily technology update", stage="source_subtitle_preflight", fail_closed=True)
    monkeypatch.setattr(web.app, "db", manager.db)
    monkeypatch.setattr(web.app, "_OUT_DIR", root)
    monkeypatch.setattr(web.app, "_trigger_video_async", Mock())
    client = TestClient(web.app.app)
    payload = client.get("/api/videos/unrest/censor-keywords").json()
    assert payload["evidence"]["status"] == "VERIFIED_REPLAY"
    assert any(row.get("layer") == "RISK" for row in payload["matched"])
    assert client.post("/api/videos/unrest/bypass-censor").json()["success"]
    assert not manager._check_censorship("unrest", "Daily technology update", stage="source_subtitle_preflight", fail_closed=True)
    source.write_text(source.read_text().replace("fuel costs", "rising prices"))
    assert manager._check_censorship("unrest", "Daily technology update", stage="source_subtitle_preflight", fail_closed=True)
    original_fingerprint = censor_engine.current_rules_fingerprint()
    assert original_fingerprint
    # 改输入后的旧复核审计不能用于新 hash。
    rows = manager.db.get_censorship_incidents("unrest")
    assert rows[0]["input_hash"] != next(row["input_hash"] for row in rows if row["decision"] == review.APPROVAL)


def test_current_news_not_exempted_by_historical_reference():
    assert classify(review.text_documents(title="Today protesters confront police again, recalling 1968."), DEFAULT_RULES)


def test_family_key_order_cannot_change_evidence():
    reordered = {**DEFAULT_RULES, "families": dict(reversed(list(DEFAULT_RULES["families"].items())))}
    documents = review.text_documents(title="Protesters take to the streets as riots erupt.")
    assert classify(documents, DEFAULT_RULES) == classify(documents, reordered)


def test_external_rule_families_match_builtin_defaults():
    config = Path(__file__).resolve().parents[2] / "config/censor_rules.json"
    assert json.loads(config.read_text())["channel_policy"]["social_unrest"] == DEFAULT_RULES


def test_source_tail_and_enrichment_are_replayable(manager, monkeypatch):
    vtt(manager._OUT_DIR, "A safe technology update. " * 2500 + " Riots erupt in Paris.")
    monkeypatch.setattr(settings, "enable_deep_insight_enrichment", True)
    monkeypatch.setattr(manager, "_insight_review_text", lambda _: "A safe insight.")
    assert manager._check_censorship("unrest", "Daily technology update",
                                     stage="source_subtitle_preflight", fail_closed=True)
    incident = manager.db.get_censorship_incidents("unrest")[0]
    evidence = review.replay(manager.db.get_video_by_youtube_id("unrest"), incident, manager._OUT_DIR)
    assert evidence["status"] == "VERIFIED_REPLAY"
    assert evidence["terms"][0]["offset_start"] > 40000
    assert not incident["description_preview"]


def test_source_description_is_not_duplicated_during_replay(tmp_path):
    video = {"youtube_id": "unrest", "title": "Daily update", "description": "Original source description"}
    vtt(tmp_path, "Protesters march over fuel costs.")
    documents = review.collect_documents(video, tmp_path, title=video["title"], stage="source_subtitle_preflight")
    evidence = review.evaluate(documents)
    incident = {"review_stage": "source_subtitle_preflight", "title": video["title"],
                "input_hash": evidence["input_hash"], "rule_pack_version": evidence["rule_version"]}
    assert review.replay(video, incident, tmp_path)["status"] == "VERIFIED_REPLAY"


@pytest.mark.parametrize("platform", ["快手", "抖音"])
def test_platform_final_copy_and_cancellation_are_replayable(manager, monkeypatch, platform):
    root = manager._OUT_DIR
    ass(root, "A safe technology update.")
    title = root / "unrest_title.txt"
    title.write_text("科技观察", encoding="utf-8")
    generic = root / "unrest_copy.txt"
    generic.write_text("安全文案", encoding="utf-8")
    copy = root / ("unrest_kuaishou_copy.txt" if platform == "快手" else "unrest_copy.txt")
    copy.write_text("\nProtesters march over fuel costs.\n", encoding="utf-8")
    update = Mock()
    monkeypatch.setattr(manager.db, "update_kuaishou_publication_state" if platform == "快手"
                        else "update_douyin_publication_state", update)
    assert manager._platform_publication_censorship_blocked(
        {"id": 123, "youtube_id": "unrest", "slice_index": 0}, platform, copy,
        None if platform == "快手" else title)
    assert update.call_args.args == (123, "CANCELED")
    incident = manager.db.get_censorship_incidents("unrest")[0]
    evidence = review.replay(manager.db.get_video_by_youtube_id("unrest"), incident, root)
    assert evidence["status"] == "VERIFIED_REPLAY"
    assert evidence["source_field"] == "description"


def test_engagement_exposes_risk_as_manual_review(manager):
    from video_processing.core.engagement_presentation import present_engagement
    assert manager._check_censorship("unrest", "Paris protests erupt over fuel costs")
    row = manager.db.get_engagement_video("unrest")
    assert row["engagement_stage"] == "ENG_POLICY"
    assert present_engagement(row)["action"] == "bypass-censor"
    assert row["score"] == 90 and not manager.db.is_blacklisted("unrest")
