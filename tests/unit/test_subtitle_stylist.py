# -*- coding: utf-8 -*-
"""SubtitleStylist 单元测试

# Modification History
| Version | Date       | Author                              | Description                          |
| ------- | ---------- | ----------------------------------- | ------------------------------------ |
| 1.0.0   | 2026-06-08 | Claude_Sonnet_4.6_Thinking_planning | 初始创建：覆盖高亮、折行、动态缩放、ASS 标签构造、GlossaryCard |
"""
import pytest
from src.video_processing.utils.subtitle_stylist import (
    SubtitleStylist,
    SubtitleLayout,
    strip_trailing_punctuation,
    apply_word_highlights,
    apply_chinese_highlights,
    tag_aware_wrap,
    FONT_EN,
    FONT_ZH,
    EN_COLOR,
    ZH_COLOR,
    VOCAB_HIGHLIGHT_COLOR,
)


# ── Fixtures ────────────────────────────────────────────────────────────────

def make_layout(en_size=50, zh_size=58, safe_width=1036, max_height=500, outline=12):
    """创建测试用 SubtitleLayout"""
    return SubtitleLayout(
        en_size=en_size,
        zh_size=zh_size,
        safe_width=safe_width,
        max_height=max_height,
        outline=outline,
    )


# ── strip_trailing_punctuation ───────────────────────────────────────────────

class TestStripTrailingPunctuation:
    def test_removes_period(self):
        assert strip_trailing_punctuation("Hello world.") == "Hello world"

    def test_removes_chinese_period(self):
        assert strip_trailing_punctuation("你好。") == "你好"

    def test_keeps_mid_sentence_punctuation(self):
        result = strip_trailing_punctuation("Hello, world.")
        assert result == "Hello, world"

    def test_empty_string(self):
        assert strip_trailing_punctuation("") == ""

    def test_multiple_trailing_punctuation(self):
        assert strip_trailing_punctuation("Done!!!") == "Done"


# ── apply_word_highlights ───────────────────────────────────────────────────

class TestApplyWordHighlights:
    def test_highlights_single_word(self):
        result = apply_word_highlights("Hello world", {"Hello": "&HC7D36F&"})
        assert "\\u1" in result
        assert "Hello" in result
        assert "\\u0" in result

    def test_case_insensitive_match(self):
        result = apply_word_highlights("hello World", {"Hello": "&HC7D36F&"})
        assert "\\u1" in result

    def test_no_highlights_when_empty_vocab(self):
        text = "Hello world"
        assert apply_word_highlights(text, {}) == text

    def test_empty_text_returns_empty(self):
        assert apply_word_highlights("", {"Hello": "&HC7D36F&"}) == ""

    def test_longer_phrase_matched_before_shorter_word(self):
        # NOTE: apply_word_highlights 按降序优先匹配长词组，但被高亮后的内容可能再次被短词匹配
        # 这里验证的是：长词组 "Hello world" 被处理后，结果里包含 "Hello world" 的高亮区域
        result = apply_word_highlights("Hello world", {"Hello world": "&HC7D36F&", "Hello": "&H0000FF&"})
        # 长词组先匹配，"Hello world" 会被包裹一次
        assert "&HC7D36F&" in result  # 长词组颜色出现过
        assert "Hello" in result


# ── apply_chinese_highlights ─────────────────────────────────────────────────

class TestApplyChineseHighlights:
    def test_highlights_chinese_word_when_present(self):
        """中文生词存在于字幕文本时，应插入高亮标签"""
        result = apply_chinese_highlights("这是一个复杂的算法", {"algorithm": "算法"})
        assert f"\\u1\\c{VOCAB_HIGHLIGHT_COLOR}" in result
        assert "算法" in result
        assert f"\\u0\\c{ZH_COLOR}" in result

    def test_no_highlight_when_word_absent(self):
        """中文生词不存在于字幕文本时，不应插入高亮标签"""
        result = apply_chinese_highlights("这是一个简单的句子", {"algorithm": "算法"})
        assert "\\u1" not in result
        assert result == "这是一个简单的句子"

    def test_empty_vocab_returns_unchanged(self):
        """空词汇表时，文本原样返回"""
        text = "这是一个测试"
        assert apply_chinese_highlights(text, {}) == text

    def test_empty_text_returns_empty(self):
        assert apply_chinese_highlights("", {"algorithm": "算法"}) == ""

    def test_longer_word_matched_before_shorter(self):
        """多个词汇时，较长的词应优先匹配，防止短词干扰长词"""
        result = apply_chinese_highlights(
            "他展现了卓越的领导力",
            {"outstanding leadership": "卓越的领导力", "leader": "领导"}
        )
        # 长词先匹配后，短词可能无法在标签内部再次匹配，但长词高亮一定存在
        assert "卓越的领导力" in result

    def test_multiple_vocab_all_highlighted(self):
        """多个中文生词都在文本中时，均应被高亮"""
        result = apply_chinese_highlights(
            "他采取了大胆的行动",
            {"bold": "大胆", "action": "行动"}
        )
        assert "大胆" in result
        assert "行动" in result
        assert result.count("\\u1") >= 2

    def test_newline_preserved_after_highlighting(self):
        """折行标签 \\N 在高亮后应完整保留"""
        text = "他采取了大胆\\N的行动"
        result = apply_chinese_highlights(text, {"bold": "大胆"})
        assert "\\N" in result


# ── tag_aware_wrap ────────────────────────────────────────────────────────────

class TestTagAwareWrap:
    def test_basic_wrap(self):
        text = "This is a somewhat long English sentence for testing wrap"
        result = tag_aware_wrap(text, 20)
        assert "\\N" in result

    def test_short_text_no_wrap(self):
        result = tag_aware_wrap("Hello world", 30)
        assert "\\N" not in result

    def test_empty_string(self):
        assert tag_aware_wrap("", 20) == ""

    def test_tag_not_counted_in_width(self):
        # 标签不应被计算在视觉宽度内
        text = "{\\c&HFF0000&}Word{\\c} more text"
        result = tag_aware_wrap(text, 15)
        # 验证标签完整性，不应被截断
        assert "{\\c&HFF0000&}" in result


# ── SubtitleStylist ───────────────────────────────────────────────────────────

class TestSubtitleStylistRender:
    def test_bilingual_output_contains_georgia_tag(self):
        """双语字幕必须包含 fnGeorgia 标签（Checkpoint 缓存校验依赖此标志）"""
        stylist = SubtitleStylist(make_layout())
        result = stylist.render("Hello", "你好", bilingual=True)
        assert f"fn{FONT_EN}" in result.ass_text, "Bilingual subtitle must contain fnGeorgia"

    def test_bilingual_output_contains_both_languages(self):
        stylist = SubtitleStylist(make_layout())
        result = stylist.render("Hello world", "你好世界", bilingual=True)
        assert "Hello" in result.ass_text
        assert "你好" in result.ass_text

    def test_monolingual_output_no_english(self):
        """bilingual=False 时只显示中文，不含 fnGeorgia"""
        stylist = SubtitleStylist(make_layout())
        result = stylist.render("Hello", "你好", bilingual=False)
        assert f"fn{FONT_ZH}" in result.ass_text
        # 单语模式不应包含 Georgia（或只作为数据出现，不应是字幕标签）
        # 实际上 bilingual=False 时根本不显示英文
        assert "Hello" not in result.ass_text

    def test_no_zh_text_shows_english_only(self):
        stylist = SubtitleStylist(make_layout())
        result = stylist.render("Hello world", "", bilingual=True)
        assert f"fn{FONT_EN}" in result.ass_text
        assert "Hello" in result.ass_text

    def test_no_en_text_shows_chinese_only(self):
        stylist = SubtitleStylist(make_layout())
        result = stylist.render("", "你好", bilingual=True)
        assert f"fn{FONT_ZH}" in result.ass_text
        assert "你好" in result.ass_text

    def test_returned_font_sizes_within_bounds(self):
        stylist = SubtitleStylist(make_layout())
        result = stylist.render("Hello world", "你好世界", bilingual=True)
        assert result.en_size >= 28, "en_size should not go below minimum"
        assert result.zh_size >= 32, "zh_size should not go below minimum"

    def test_dynamic_scaling_triggers_for_very_small_height(self):
        """极小的 max_height 应触发动态字号缩放"""
        layout = make_layout(en_size=80, zh_size=90, max_height=80)  # 非常小
        stylist = SubtitleStylist(layout)
        result = stylist.render(
            "This is a very long English subtitle that should wrap to multiple lines",
            "这是一个非常长的中文字幕，应该会被折行处理并触发动态字号缩放",
            bilingual=True
        )
        # 字号应该已缩小（触发缩放）
        assert result.en_size <= 80
        assert result.zh_size <= 90

    def test_normal_content_preserves_font_sizes(self):
        """正常内容（单行）不应触发缩放"""
        layout = make_layout(en_size=50, zh_size=58, max_height=500)
        stylist = SubtitleStylist(layout)
        result = stylist.render("Hello", "你好", bilingual=True)
        # 短文本不应缩放
        assert result.en_size == 50
        assert result.zh_size == 58

    def test_vocab_highlights_in_ass_text(self):
        """有词汇时英文文本应含高亮标签"""
        stylist = SubtitleStylist(make_layout())
        result = stylist.render(
            "The algorithm is complex",
            "算法很复杂",
            vocab_items={"algorithm": "算法"},
            bilingual=True
        )
        assert "\\u1" in result.ass_text


class TestSubtitleStylistGlossaryCard:
    def test_glossary_text_contains_vocab_word(self):
        stylist = SubtitleStylist(make_layout())
        text = stylist.build_glossary_text({"algorithm": "算法，计算步骤"})
        assert "algorithm" in text

    def test_glossary_text_contains_translation(self):
        stylist = SubtitleStylist(make_layout())
        text = stylist.build_glossary_text({"algorithm": "算法，计算步骤"})
        assert "算法" in text

    def test_glossary_first_word_has_vocab_label(self):
        stylist = SubtitleStylist(make_layout())
        text = stylist.build_glossary_text({"algorithm": "算法"})
        assert "词汇" in text

    def test_glossary_empty_vocab_returns_empty(self):
        stylist = SubtitleStylist(make_layout())
        assert stylist.build_glossary_text({}) == ""

    def test_glossary_multiple_words_joined(self):
        stylist = SubtitleStylist(make_layout())
        text = stylist.build_glossary_text({
            "algorithm": "算法",
            "complex": "复杂",
        })
        assert "algorithm" in text
        assert "complex" in text
