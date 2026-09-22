"""英语世界短视频专属报刊封面单元测试 (test_english_world_cover.py)

# Modification History
| Version | Date       | Author                         | Description                                            |
|---------|------------|--------------------------------|--------------------------------------------------------|
| 1.3.0   | 2026-09-18 | Antigravity                    | 覆盖新语言契约下 AGY 封面生成与 approved_cover_payload 透传，以及封面渲染载荷隔离校验。 |
| 1.0.0   | 2026-08-24 | Gemini_3.7_Flash_High_planning | 初始创建：覆盖 ENGLISH_WORLD_SHORT 内容路由、教学字段装配、合规策略与全流程渲染 |
| 1.1.0 | 2026-08-24 | Codex | 覆盖 agy OCR 人审待决门禁与首选封面审核包集成。 |
| 1.2.0 | 2026-08-28 | Codex | 覆盖 Chromium 不可用时的 Pillow 英语封面回退。 |
| 1.2.1 | 2026-09-06 | Codex | 回归覆盖新 QA 指纹、调度时刻与可续接交付契约。 |
| 1.2.2 | 2026-09-09 | Codex | 验证封面保留音标对应词形或词元标签。 |
"""

import json
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest
from PIL import Image, ImageDraw
from scripts import generate_english_cover as english_cover_cli
from src.cover.semantic import SemanticAnalyzer
from src.cover.layout import LayoutComposer, _format_quote_en_html
from src.cover.engine import CoverEngine
from src.cover.english_world import build_english_world_cover_payload, validate_english_world_cover_payload
from src.cover import antigravity
from src.cover.antigravity import accept_and_normalize, build_agy_prompt, build_visual_brief
from video_processing.core.cover_policy import assert_template_respects_cover_policy, validate_dedicated_cover_file
from video_processing.core.cover_policy import compliant_cover_layout_policy


def test_pillow_wrap_preserves_s_and_whole_english_words():
    draw = ImageDraw.Draw(Image.new("RGB", (1080, 1260)))
    quote = "Big tech names like Intel, Arm Holdings and AMD are rising in the markets."
    lines = english_cover_cli._wrapped_lines(draw, quote, english_cover_cli._font(31), width=880, limit=3)
    assert " ".join(lines) == quote
    assert all(word in " ".join(lines).split() for word in ("names", "Holdings", "rising", "markets."))


def test_pillow_wrap_does_not_ellipsize_complete_last_line():
    draw = ImageDraw.Draw(Image.new("RGB", (300, 300)))
    font = english_cover_cli._font(24)
    width = int(draw.textlength("words ", font=font)) + 1
    assert english_cover_cli._wrapped_lines(draw, "these words", font, width=width, limit=2) == ["these", "words"]


def test_pillow_wrap_keeps_mixed_language_punctuation_spacing():
    draw = ImageDraw.Draw(Image.new("RGB", (1080, 1260)))
    quote = "英特尔、Arm Holdings 和 AMD 等大型科技股在市场上走强。"
    lines = english_cover_cli._wrapped_lines(draw, quote, english_cover_cli._font(27), width=880, limit=2)
    assert "".join(lines) == quote


def test_pillow_ipa_font_has_nasal_glyph_and_fails_without_font(monkeypatch):
    font = english_cover_cli._ipa_font(24)
    assert bytes(font.getmask("ŋ")) != bytes(font.getmask("\uffff"))
    monkeypatch.setattr(english_cover_cli, "_IPA_FONT_CANDIDATES", ())
    with pytest.raises(ValueError, match="IPA"):
        english_cover_cli._ipa_font(24)


def test_quote_en_html_highlighting():
    """测试重点生词的 HTML 安全转义与高亮注入"""
    quote = "To put it simply, they are houses for computers or computing power and storage."
    highlights = ["houses", "computing power", "storage"]
    result = _format_quote_en_html(quote, highlights)
    assert '<span class="hl">houses</span>' in result
    assert '<span class="hl">computing power</span>' in result
    assert '<span class="hl">storage</span>' in result


def test_semantic_analyzer_english_world_routing():
    """测试 content_type=ENGLISH_WORLD_SHORT 优先路由到报刊模板"""
    rules_path = Path("resources/cover/rules.json")
    analyzer = SemanticAnalyzer(rules_path)

    # 1. 显式 content_type 触发
    signal = analyzer.analyze({"content_type": "ENGLISH_WORLD_SHORT", "title": "数据中心科普"})
    assert signal.id == "english_world_newspaper"
    assert signal.template_variant == "cover_english_newspaper"
    assert signal.default_badge == "世界英语新闻精读"
    assert signal.base_gradient == "newspaper_ivory"
    assert signal.accent == "crimson_academic"

    # 2. 关键词模糊触发
    signal_kw = analyzer.analyze({"title": "外刊精读：全球算力底座调查"})
    assert signal_kw.template_variant == "cover_english_newspaper"


def test_layout_composer_english_world_spec():
    """测试 LayoutComposer 装配完整的英语教学载荷"""
    payload = {
        "content_type": "ENGLISH_WORLD_SHORT",
        "title": "数据中心像一座电脑的房子",
        "subtitle": "● 科技科普 · 原声双语精读",
        "quote_en": "To put it simply, they are houses for computers.",
        "quote_zh": "简单说，它们就像容纳大量电脑的房子。",
        "highlight_words": ["houses", "computers"],
        "vocab_items": [
            {"word": "computing power", "ipa": "/kəmˈpjuːtɪŋ ˈpaʊər/", "meaning": "n. 算力", "level": "CET-4"},
            {"word": "data center", "ipa": "/ˈdeɪtə ˈsentər/", "meaning": "n. 数据中心", "level": "外刊高频"}
        ],
        "difficulty_tag": "★★★☆☆ (中高考 / 四六级)",
        "audio_source": "CBC Kids News 原声",
        "date_str": "2026.08.24 今日外刊打卡"
    }

    analyzer = SemanticAnalyzer(Path("resources/cover/rules.json"))
    signal = analyzer.analyze(payload)
    theme_mock = {
        "accent_color": "#A53C2B",
        "accent_glow": "0 0 20px rgba(165,60,43,0.4)",
        "background_gradient_start": "#FBF9F4",
        "background_gradient_end": "#F5EFE6",
        "noise_opacity": 0.02,
        "grid_color": "rgba(165,60,43,0.03)",
        "orbs": []
    }

    composer = LayoutComposer()
    spec = composer.compose(payload, signal, theme_mock)

    assert spec["template_variant"] == "cover_english_newspaper"
    assert spec["badge"] == "世界英语新闻精读"
    assert spec["quote_en"] == "To put it simply, they are houses for computers."
    assert '<span class="hl">houses</span>' in spec["quote_en_html"]
    assert len(spec["vocab_items"]) >= 2
    assert spec["difficulty_tag"] == "★★★☆☆ (中高考 / 四六级)"
    assert spec["audio_source"] == "CBC Kids News 原声"


def test_timeline_payload_uses_ranked_words_and_verifiable_stat():
    """词卡和难度必须来自课程等级，不能取词表的前两项或写死阶段目标。"""
    timeline = {
        "headline_zh": "数据中心像一座电脑的房子",
        "english_text": "Computing power needs storage. The first sentence ends here.",
        "translation_zh": "算力需要存储。第一句到此结束。",
        "source_provenance": {"publisher": "CBC Kids News"},
        "vocabulary_selection": {"lexical_word_count": 37, "selected_count": 10},
        "vocabulary_candidates": [
            {"word": "power", "phonetic": "paʊər", "context_meaning_zh": "n. 力量", "recommended_level": "高考", "friendly_tag": "进阶词"},
            {"word": "computing", "phonetic": "kəmˈpjuːtɪŋ", "context_meaning_zh": "adj. 计算的", "recommended_level": "CET-4", "friendly_tag": "进阶词"},
            {"word": "storage", "phonetic": "stɔːrɪdʒ", "context_meaning_zh": "n. 存储", "recommended_level": "高考", "friendly_tag": "进阶词"},
            {"word": "they're", "phonetic": "ðeə", "context_meaning_zh": "他们是", "recommended_level": "Master", "friendly_tag": "新闻高阶词"},
        ],
    }

    payload = build_english_world_cover_payload(timeline, date_str="2026.08.24 今日外刊打卡")
    assert [item["word"] for item in payload["vocab_items"]] == ["computing", "storage"]
    assert payload["difficulty_tag"] == "★★★☆☆ (中高考 / 四六级)"
    assert payload["vocab_stat"] == "本篇 37 词 · 10 个重点"
    assert payload["subtitle"] == "● 英语新闻 · 原声双语精读"
    assert payload["quote_zh"] == "算力需要存储。"
    assert validate_english_world_cover_payload(payload)["content_type"] == "ENGLISH_WORLD_SHORT"


def test_cover_payload_keeps_explicit_lemma_for_inflected_display_word():
    timeline = {
        "headline_zh": "阅读排名", "english_text": "It ranks 13th.", "translation_zh": "它排在第13位。",
        "vocabulary_candidates": [{"word": "ranks", "phonetic": "ræŋk", "phonetic_word": "rank",
                                     "context_meaning_zh": "排名", "recommended_level": "CET-4"}],
    }
    payload = build_english_world_cover_payload(timeline)
    assert payload["vocab_items"] == [{"word": "ranks", "ipa": "/ræŋk/", "phonetic_word": "rank",
                                        "meaning": "排名", "level": "CET-4"}]


def test_timeline_uses_frozen_language_reviewed_cover_payload():
    """冻结后的实际封面不能退回旧候选池，避免显示 0 个词或错误词义。"""
    frozen = {
        "content_type": "ENGLISH_WORLD_SHORT",
        "title": "美国阅读成绩下滑",
        "quote_en": "The results for reading are sobering.",
        "quote_zh": "阅读方面的结果令人警醒。",
        "highlight_words": ["sobering"],
        "vocab_items": [{"word": "sobering", "ipa": "/ˈsoʊbərɪŋ/", "phonetic_word": "sobering",
                           "meaning": "令人警醒的", "level": "A2–B1"}],
        "difficulty_tag": "A2–B1 家庭精读",
        "vocab_stat": "本篇 9 个重点学习点",
        "audio_source": "ABC News 原声",
        "date_str": "2026.09.09 本地审看样片",
    }
    timeline = {
        "headline_zh": "旧标题", "english_text": "Old text.", "translation_zh": "旧译文。",
        "vocabulary_candidates": [], "publication_text": {"cover_payload": frozen},
    }

    assert build_english_world_cover_payload(timeline) == frozen


def test_long_chinese_title_is_balanced_into_two_lines():
    """长中文标题不能在封面上留下单字孤行。"""
    composer = LayoutComposer()
    signal = SemanticAnalyzer(Path("resources/cover/rules.json")).analyze({"content_type": "ENGLISH_WORLD_SHORT"})
    theme = CoverEngine().registry.resolve(signal)
    layout = composer.compose({"content_type": "ENGLISH_WORLD_SHORT", "title": "数据中心像一座电脑的房子"}, signal, theme)
    assert layout["title_lines"] == ["数据中心像一座", "电脑的房子"]


def test_english_cover_cli_uses_pillow_when_playwright_is_unavailable(tmp_path, monkeypatch):
    """浏览器权限被拒绝时，英语封面仍要生成可验证的本地非视频帧封面。"""
    timeline = {
        "headline_zh": "注意力也有能量预算",
        "headline_en": "Your Attention Has an Energy Budget",
        "english_text": "Attention is a limited resource.",
        "translation_zh": "注意力是一种有限的资源。",
        "source_provenance": {"publisher": "CBC Kids News"},
        "vocabulary_selection": {"lexical_word_count": 12, "selected_count": 2},
        "vocabulary_candidates": [
            {"word": "attention", "phonetic": "əˈtenʃən", "context_meaning_zh": "注意力", "recommended_level": "高考", "friendly_tag": "进阶词"},
            {"word": "resource", "phonetic": "rɪˈsɔːs", "context_meaning_zh": "资源", "recommended_level": "CET-4", "friendly_tag": "进阶词"},
        ],
    }
    timeline_path = tmp_path / "timeline.enriched.json"
    output = tmp_path / "cover.jpg"
    provenance = tmp_path / "cover_provenance.json"
    timeline_path.write_text(json.dumps(timeline, ensure_ascii=False), encoding="utf-8")
    planner = CoverEngine()

    class BrowserDeniedEngine:
        def generate(self, _payload, _output):
            raise PermissionError("Chromium MachPort denied")

        def plan(self, payload):
            return planner.plan(payload)

    monkeypatch.setattr(english_cover_cli, "CoverEngine", BrowserDeniedEngine)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_english_cover.py", "--timeline", str(timeline_path), "--output", str(output),
            "--provenance-output", str(provenance),
        ],
    )

    assert english_cover_cli.main() == 0
    assert Image.open(output).size == (1080, 1260)
    assert validate_dedicated_cover_file(output, provenance)
    assert json.loads(provenance.read_text(encoding="utf-8"))["render_backend"] == "pillow"


def test_generate_english_cover_isolates_visual_asset_from_payload_output(tmp_path, monkeypatch):
    """验证 visual_asset 不会污染导出的 payload_output JSON 或改变 payload_sha256。"""
    payload = {
        "content_type": "ENGLISH_WORLD_SHORT",
        "title": "测试标题",
        "quote_en": "Learning English is fun.",
        "quote_zh": "学习英语很有趣。",
        "difficulty_tag": "★★☆☆☆",
        "audio_source": "原声",
        "date_str": "2026.09.18",
        "highlight_words": ["fun"],
        "vocab_items": [],
    }
    payload_in = tmp_path / "payload_in.json"
    payload_in.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    payload_out = tmp_path / "payload_out.json"
    provenance_out = tmp_path / "provenance_out.json"
    cover_out = tmp_path / "cover.jpg"
    visual_png = tmp_path / "visual.png"
    Image.new("RGB", (1080, 1260), "#F5EFE6").save(visual_png)

    class DummyEngine:
        def generate(self, render_payload, output_path):
            assert render_payload.get("visual_asset_path") == str(visual_png)
            Image.new("RGB", (1080, 1260), "#F5EFE6").save(output_path)
            return {"template_variant": "cover_english_newspaper"}

    monkeypatch.setattr(english_cover_cli, "CoverEngine", DummyEngine)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_english_cover.py",
            "--payload-file", str(payload_in),
            "--visual-asset", str(visual_png),
            "--output", str(cover_out),
            "--provenance-output", str(provenance_out),
            "--payload-output", str(payload_out),
        ],
    )
    assert english_cover_cli.main() == 0
    exported_payload = json.loads(payload_out.read_text(encoding="utf-8"))
    assert "visual_asset_path" not in exported_payload
    from video_processing.study_cards.language_qa import digest
    assert digest(exported_payload) == digest(payload)


def test_antigravity_visual_contract_is_text_free_and_uses_local_fact(tmp_path):
    """Gemini 只能获得已有事实，候选必须通过 OCR 无字门禁后才可合成。"""
    timeline = {
        "source_provenance": {"source_title": "What are data centres?", "publisher": "CBC Kids News"},
    }
    payload = {
        "title": "数据中心像一座电脑的房子",
        "quote_en": "They are houses for computing power.",
    }
    brief = build_visual_brief(timeline, payload)
    prompt = build_agy_prompt(brief, tmp_path / "candidate.png")
    assert brief["source_title"] == "What are data centres?"
    assert "no text" in prompt.lower()
    source = tmp_path / "source.png"
    Image.new("RGB", (900, 1050), "#1F2937").save(source)
    evidence = accept_and_normalize(source, tmp_path / "visual.png")
    assert evidence["machine_visual_review"] == "ocr_empty"
    assert evidence["dimensions"] == {"width": 1080, "height": 1260}


def test_antigravity_ocr_suspect_is_only_retained_for_human_review(tmp_path, monkeypatch):
    """OCR 误报可进 Telegram 人审，但默认不会被机器自动放行。"""
    source = tmp_path / "source.png"
    Image.new("RGB", (900, 1050), "#1F2937").save(source)
    monkeypatch.setattr(antigravity, "_ocr_text", lambda _: "fake visual texture")
    with pytest.raises(ValueError, match="OCR 检出可读文字"):
        accept_and_normalize(source, tmp_path / "strict.png")
    evidence = accept_and_normalize(source, tmp_path / "review.png", allow_ocr_suspect=True)
    assert evidence["machine_visual_review"] == "ocr_suspect_requires_human_review"
    assert evidence["requires_human_visual_review"] is True
    assert evidence["human_visual_review"] is None


def test_review_package_prefers_agy_and_keeps_human_gate(tmp_path, monkeypatch):
    """审核包走 agy 时只生成本地材料，不发送 Telegram 或触发平台投稿。"""
    script_path = Path("scripts/notify_english_world_review.py").resolve()
    spec = importlib.util.spec_from_file_location("english_world_notifier_test", script_path)
    assert spec and spec.loader
    notifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(notifier)
    timeline = {
        "headline_zh": "数据中心像一座电脑的房子",
        "english_text": "Computing power needs storage.",
        "translation_zh": "算力需要存储。",
        "source_provenance": {"publisher": "CBC Kids News", "source_url": "https://example.invalid/source"},
        "vocabulary_candidates": [],
    }
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"content_type": "ENGLISH_WORLD_SHORT", "duration": 42.0}), encoding="utf-8")
    (tmp_path / "timeline_final_enriched.json").write_text(json.dumps(timeline), encoding="utf-8")
    mp4 = tmp_path / "sample.mp4"
    mp4.write_bytes(b"not-a-real-video")
    monkeypatch.setattr(notifier.settings, "enable_english_world_antigravity_primary", True)
    monkeypatch.setattr(notifier.settings, "english_world_antigravity_model", "gemini-3.7-flash-high")
    monkeypatch.setattr(notifier.settings, "english_world_antigravity_variants", 3)
    monkeypatch.setattr(notifier.settings, "english_world_antigravity_timeout_seconds", 30)
    monkeypatch.setattr(notifier.settings, "english_world_antigravity_allow_ocr_suspect", True)

    def fake_run(command, **_):
        assert Path(command[1]).name == "generate_english_agi_cover.py"
        assert "--allow-ocr-suspect" in command
        cover = Path(command[command.index("--cover-output") + 1])
        provenance = Path(command[command.index("--provenance-output") + 1])
        Image.new("RGB", (1080, 1260), "#F5EFE6").save(cover)
        digest = __import__("hashlib").sha256(cover.read_bytes()).hexdigest()
        provenance.write_text(json.dumps({
            "cover_kind": "dedicated_generated_image", "uses_video_frame": False,
            "cover_filename": cover.name, "cover_sha256": digest,
            "layout_policy": compliant_cover_layout_policy(),
        }), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout='{"status":"accepted"}', stderr="")

    class FakeDB:
        def get_english_world_review_by_artifact(self, _digest):
            return None

        def create_english_world_review_item(self, **kwargs):
            return {"id": "review-id", "state": "READY_FOR_REVIEW", **kwargs}

    monkeypatch.setattr(notifier.subprocess, "run", fake_run)
    monkeypatch.setattr(notifier, "get_video_duration_ffprobe", lambda _path: 42.0)
    monkeypatch.setattr(notifier, "PipelineDB", FakeDB)
    from video_processing.study_cards.qa_integrity import artifact_fingerprints
    qa = tmp_path / "qa/final_audio_qa.json"
    qa.parent.mkdir()
    timeline_path = tmp_path / "timeline_final_enriched.json"
    qa.write_text(json.dumps({"state": "PASS", "passed": True,
        "mp4": str(mp4), "manifest": str(manifest), "timeline": str(timeline_path),
        **artifact_fingerprints(mp4=mp4, manifest=manifest, timeline=timeline_path)}))
    review = notifier._prepare_publish_package(display_title="备用标题", mp4=mp4, manifest=manifest)
    assert validate_dedicated_cover_file(Path(review["cover_path"]), Path(review["cover_provenance_path"]))
    assert json.loads((tmp_path / "wechat_submission" / "agy_cover_attempt.json").read_text(encoding="utf-8"))["returncode"] == 0


def test_review_package_prefers_agy_with_language_v2_and_passes_payload_file(tmp_path, monkeypatch):
    """验证 language-v1 契约下审核包依然调用 agy 且透传 approved_cover_payload。"""
    script_path = Path("scripts/notify_english_world_review.py").resolve()
    spec = importlib.util.spec_from_file_location("english_world_notifier_test", script_path)
    assert spec and spec.loader
    notifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(notifier)
    timeline = {
        "language_contract": "english-world-language-v1",
        "headline_zh": "地震科普精读",
        "english_text": "Earthquakes shake the ground.",
        "translation_zh": "地震撼动地面。",
        "source_provenance": {"publisher": "CBC Kids News", "source_url": "https://example.invalid/source"},
        "publication_text": {
            "title": "英语世界｜地震科普精读",
            "copy": "跟随原声学习。",
            "cover_payload": {
                "content_type": "ENGLISH_WORLD_SHORT",
                "title": "地震科普精读",
                "quote_en": "Earthquakes shake the ground.",
                "quote_zh": "地震撼动地面。",
            },
        },
    }
    manifest = tmp_path / "manifest.json"
    timeline_path = tmp_path / "timeline.json"
    timeline_path.write_text(json.dumps(timeline), encoding="utf-8")
    manifest.write_text(json.dumps({
        "content_type": "ENGLISH_WORLD_SHORT",
        "language_contract": "english-world-language-v1",
        "timeline": str(timeline_path.resolve()),
        "duration": 42.0,
    }), encoding="utf-8")
    mp4 = tmp_path / "sample.mp4"
    mp4.write_bytes(b"not-a-real-video")
    monkeypatch.setattr(notifier.settings, "enable_english_world_antigravity_primary", True)
    monkeypatch.setattr(notifier.settings, "enable_english_world_language_qa", False)
    monkeypatch.setattr(notifier, "validate_audio_qa", lambda *a, **k: None)
    import video_processing.study_cards.publication_qa as pub_qa
    monkeypatch.setattr(pub_qa, "approved_publication", lambda _path: (timeline["publication_text"], "dummy-sha256"))
    import video_processing.study_cards.language_qa as lang_qa
    monkeypatch.setattr(lang_qa, "validate_publication", lambda *a, **k: None)

    passed_command = []

    def fake_run(command, **_):
        passed_command.extend(command)
        cover = Path(command[command.index("--cover-output") + 1])
        provenance = Path(command[command.index("--provenance-output") + 1])
        payload_out = Path(command[command.index("--payload-output") + 1])
        payload_in = Path(command[command.index("--payload-file") + 1])
        payload_out.write_text(payload_in.read_text(encoding="utf-8"), encoding="utf-8")
        Image.new("RGB", (1080, 1260), "#F5EFE6").save(cover)
        digest = __import__("hashlib").sha256(cover.read_bytes()).hexdigest()
        provenance.write_text(json.dumps({
            "cover_kind": "dedicated_generated_image", "uses_video_frame": False,
            "cover_filename": cover.name, "cover_sha256": digest,
            "layout_policy": compliant_cover_layout_policy(),
        }), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout='{"status":"accepted"}', stderr="")

    class FakeDB:
        def get_english_world_review_by_artifact(self, _digest):
            return None

        def create_english_world_review_item(self, **kwargs):
            return {"id": "review-id-2", "state": "READY_FOR_REVIEW", **kwargs}

    monkeypatch.setattr(notifier.subprocess, "run", fake_run)
    monkeypatch.setattr(notifier, "get_video_duration_ffprobe", lambda _path: 42.0)
    monkeypatch.setattr(notifier, "PipelineDB", FakeDB)

    review = notifier._prepare_publish_package(display_title="英语世界｜地震科普精读", mp4=mp4, manifest=manifest)
    assert Path(passed_command[1]).name == "generate_english_agi_cover.py"
    assert "--payload-file" in passed_command
    assert validate_dedicated_cover_file(Path(review["cover_path"]), Path(review["cover_provenance_path"]))
    assert json.loads((tmp_path / "wechat_submission" / "agy_cover_attempt.json").read_text(encoding="utf-8"))["returncode"] == 0


def test_cover_template_policy_compliance():
    """验证 cover_english_newspaper.html.j2 满足严格的封面合规门禁"""
    template_path = Path("resources/cover/template/cover_english_newspaper.html.j2")
    assert template_path.exists()
    content = template_path.read_text(encoding="utf-8")
    # 不抛出 ValueError
    assert_template_respects_cover_policy(content, template_path)
    assert "editorial-visual" in content
    assert "background-image: url" in content


def test_cover_engine_e2e_planning():
    """测试 CoverEngine 完整规划流程"""
    engine = CoverEngine()
    payload = {
        "content_type": "ENGLISH_WORLD_SHORT",
        "title": "哥伦比亚救援英语精读",
        "quote_en": "Hope rises in the Colombian rainforest.",
        "quote_zh": "希望在哥伦比亚雨林中升起。"
    }
    layout = engine.plan(payload)
    assert layout["style_id"] == "english_world_newspaper"
    assert layout["template_variant"] == "cover_english_newspaper"
    assert layout["canvas_width"] == 1080
    assert layout["canvas_height"] == 1260
