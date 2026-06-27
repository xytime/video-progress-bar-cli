# -*- coding: utf-8 -*-
"""Unit tests for caption processor layouts.

# Modification History
| Version | Date       | Author                    | Description |
| ------- | ---------- | ------------------------- | ----------- |
| 1.0.0   | 2026-05-21 | Claude_Sonnet_4.6_Thinking | 初始创建 |
| 1.1.0   | 2026-06-07 | Gemini_3.5_Flash_planning | 新增竖屏视频布局与智能字幕坐标位置测试，标有 # [Gemini_3.5_Flash_planning] |
| 1.2.0   | 2026-06-07 | Gemini_3.5_Flash_planning | 新增双语字幕互调与金色英文样式及字号占比测试，标注 # [Gemini_3.5_Flash_planning] |
| 1.3.0   | 2026-06-07 | Gemini_3.5_Flash_planning | 新增竖屏字幕底盒样式及内边距 and 透明度测试，标注 # [Gemini_3.5_Flash_planning] |
| 1.4.0   | 2026-06-07 | Gemini_3.5_Flash_planning | 新增标签敏感折行函数测试，确保 highlighted 英文长词不被折断，标注 # [Gemini_3.5_Flash_planning] |
| 1.5.0   | 2026-06-07 | Gemini_3.5_Flash_planning | 更新独立双事件排版测试，适应 Option 5 贴地难词底框设计，标注 # [Gemini_3.5_Flash_planning] |
| 1.6.0   | 2026-06-07 | Gemini_3.5_Flash_High_planning | 整合双语字幕一体化卡片及多色高亮和下划线测试，标注 # [Gemini_3.5_Flash_High_planning] |
| 1.7.0   | 2026-06-07 | Claude_Sonnet_4.6_Thinking_planning | 更新测试适配 GlossaryCard 灰色背景楷体独立卡片，标注 # [Claude_Sonnet_4.6_Thinking_planning] |
| 1.8.0   | 2026-06-08 | Gemini_3.5_Flash_planning | 更新双语字幕测试断言，匹配 Georgia/Hiragino 样式与 HTML 模版配色，标注 # [Gemini_3.5_Flash_planning] |
| 1.9.0   | 2026-06-08 | Claude_Sonnet_4.6_Thinking_planning | 更新释义卡断言匹配 build_glossary_text en_size 参数的\\fs标签输出；转移中文高亮到折行之后的新行为 |
"""
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

# Adjust path to import correctly
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../src')))

from video_processing.processors.caption_processor import AutoCaptionProcessor

class TestCaptionProcessorRedBlueFixes:
    """
    Red/Blue Team Validation Tests for AutoCaptionProcessor.
    This replaces the 'performative' shell tests with strictly isolated, 
    mock-driven unit testing that imports the actual production logic.
    """
    
    @patch('video_processing.processors.caption_processor.AutoCaptionProcessor._validate_input')
    @patch('video_processing.processors.caption_processor.AutoCaptionProcessor._get_video_resolution')
    @patch('pysubs2.SSAFile')
    def test_vertical_video_font_scaling_anti_overflow(self, MockSSAFile, mock_get_resolution, mock_validate_input):
        """
        Test that vertical videos (width < height) scale their fonts based on width,
        not height, to prevent extreme font sizes overflowing the screen.
        """
        # 1. Setup Mock for 1080x1920 (TikTok/Shorts format)
        mock_get_resolution.return_value = (1080, 1920)
        
        # Setup mock SSAFile to capture the styles created by the engine
        mock_subs_instance = MagicMock()
        mock_subs_instance.styles = {}
        mock_subs_instance.info = {}
        MockSSAFile.return_value = mock_subs_instance
        
        # 2. Instantiate actual production processor
        processor = AutoCaptionProcessor(
            input_path=Path("dummy_vertical_video.mp4"),
            output_path=Path("dummy_output"),
            style="default"
        )
        
        # 3. Trigger ASS generation (pass empty segments to avoid TTS processing)
        processor._generate_ass_file(segments=[])
        
        # 4. Assertions on the applied physics/math logic
        assert "Default" in mock_subs_instance.styles, "Expected 'Default' style to be generated"
        style = mock_subs_instance.styles["Default"]
        
        # If the math uses video_w (1080), scale_factor = 1080 / 1080 = 1.0. Font size = 115 * 1.0 = 115
        # If the vulnerable math was used (video_h 1920), it would be 115 * 1.777 = 204
        assert style.fontsize == 115, f"❌ OVERFLOW DETECTED! Font size {style.fontsize} is too large for 1080px width."
        
    @patch('video_processing.processors.caption_processor.AutoCaptionProcessor._validate_input')
    @patch('video_processing.processors.caption_processor.AutoCaptionProcessor._get_video_resolution')
    @patch('pysubs2.SSAFile')
    def test_golden_stroke_is_hardcoded_default(self, MockSSAFile, mock_get_resolution, mock_validate_input):
        """
        Test that the default style has been properly overridden to Golden Stroke
        (borderstyle=1, outlinecolor=Gold), ensuring Hollywood-style captions.
        """
        mock_get_resolution.return_value = (1920, 1080)
        mock_subs_instance = MagicMock()
        mock_subs_instance.styles = {}
        MockSSAFile.return_value = mock_subs_instance
        
        processor = AutoCaptionProcessor(input_path=Path("dummy.mp4"), output_path=Path("dummy"), style="default")
        processor._generate_ass_file(segments=[])
        
        style = mock_subs_instance.styles["Default"]
        
        # Assert Golden Outline Color (pysubs2 uses R, G, B, A)
        assert style.outlinecolor.r == 255 and style.outlinecolor.g == 215 and style.outlinecolor.b == 0, \
            "❌ STYLE FAILURE: Outline color is not Gold (255, 215, 0)"
            
        # Assert Border Style is Outline (1), not Opaque Box (3)
        assert style.borderstyle == 1, "❌ STYLE FAILURE: Border style should be 1 (Outline)"

    @patch('video_processing.processors.vertical_processor.VerticalCaptionProcessor._validate_input')
    @patch('video_processing.processors.vertical_processor.VerticalCaptionProcessor._get_video_resolution')
    @patch('pysubs2.SSAFile')
    def test_vertical_processor_smart_subtitle_positioning_and_no_cropping(self, MockSSAFile, mock_get_resolution, mock_validate_input):
        """
        Test that VerticalCaptionProcessor dynamically positions subtitles to Y=1400 (blank area)
        when the input is vertical, and centers the video (video_y=0) to prevent bottom cropping.
        """
        from video_processing.processors.vertical_processor import VerticalCaptionProcessor
        from video_processing.utils.layout import VerticalLayout

        # --- Case 1: Vertical Input Video (1080x1920) ---
        mock_get_resolution.return_value = (1080, 1920)
        mock_subs_instance = MagicMock()
        mock_subs_instance.styles = {}
        mock_subs_instance.info = {}
        MockSSAFile.return_value = mock_subs_instance

        processor = VerticalCaptionProcessor(
            input_path=Path("dummy_vertical.mp4"),
            output_path=Path("dummy_output"),
            style="default"
        )
        
        # Verify Layout Calculation for Vertical Video
        layout = VerticalLayout.calculate(1080, 1920)
        assert layout.video_y == 0, f"Expected video_y to be 0 for vertical input, got {layout.video_y}"

        # Verify ASS Subtitle Top position for Vertical Video
        # [Claude_Sonnet_4.6_Thinking_planning] MarginV for vertical = 1200 (≈62.5% canvas).
        # Moved from 1000 to bring subtitles visually closer to GlossaryCard.
        # Overflow handled by per-segment dynamic font scaling, not by subtitle_top_y.
        processor._generate_ass_file(segments=[])
        assert "Default" in mock_subs_instance.styles
        style = mock_subs_instance.styles["Default"]
        assert style.marginv == 1200, f"Expected subtitle marginv (Y) to be 1200 for vertical video, got {style.marginv}"

        # --- Case 2: Landscape Input Video (1920x1080) ---
        mock_get_resolution.return_value = (1920, 1080)
        mock_subs_instance_landscape = MagicMock()
        mock_subs_instance_landscape.styles = {}
        mock_subs_instance_landscape.info = {}
        MockSSAFile.return_value = mock_subs_instance_landscape

        processor_landscape = VerticalCaptionProcessor(
            input_path=Path("dummy_landscape.mp4"),
            output_path=Path("dummy_output"),
            style="default"
        )

        # Verify Layout Calculation for Landscape Video
        layout_landscape = VerticalLayout.calculate(1920, 1080)
        assert layout_landscape.video_y == VerticalLayout.TOP_MARGIN, f"Expected video_y to be {VerticalLayout.TOP_MARGIN} for landscape input, got {layout_landscape.video_y}"

        # Verify ASS Subtitle Top position for Landscape Video
        # [Gemini_3.5_Flash_planning] MarginV for landscape 1920x1080 is dynamically calculated:
        # scaled new_h = 607, video_bottom_y = 350 + 607 = 957.
        # Subtitle starts at 957 + 90 = 1047 (just below the video in the black area, biased upwards).
        processor_landscape._generate_ass_file(segments=[])
        assert "Default" in mock_subs_instance_landscape.styles
        style_landscape = mock_subs_instance_landscape.styles["Default"]
        assert style_landscape.marginv == 1047, f"Expected subtitle marginv (Y) to be 1047 for landscape video, got {style_landscape.marginv}"

    @patch('video_processing.processors.vertical_processor.VerticalCaptionProcessor._validate_input')
    @patch('video_processing.processors.vertical_processor.VerticalCaptionProcessor._get_video_resolution')
    @patch('pysubs2.SSAFile')
    def test_bilingual_subtitle_swap_and_styling(self, MockSSAFile, mock_get_resolution, mock_validate_input):
        """
        [Gemini_3.5_Flash_planning] Test that VerticalCaptionProcessor correctly swaps bilingual text order,
        making English the primary text on top (in White, with Gold highlighted vocab), Chinese secondary on bottom (White, 0.82x size),
        automatically strips trailing punctuations, and appends the cyan vocabulary annotation bar.
        """
        from video_processing.processors.vertical_processor import VerticalCaptionProcessor

        mock_get_resolution.return_value = (1920, 1080)
        mock_subs_instance = MagicMock()
        mock_subs_instance.styles = {}
        mock_subs_instance.info = {}
        mock_events = []
        mock_subs_instance.events = mock_events
        MockSSAFile.return_value = mock_subs_instance

        # Instantiate processor with bilingual=True
        processor = VerticalCaptionProcessor(
            input_path=Path("dummy_bilingual.mp4"),
            output_path=Path("dummy_output"),
            bilingual=True,
            font_size=84,
            style="default"
        )

        test_segments = [{
            "start": 0.0,
            "end": 2.0,
            "text": "Hello world.",
            "zh_text": "你好世界。",
            "vocab": {"world": "世界"}
        }]

        # Trigger generation
        processor._generate_ass_file(segments=test_segments)

        # Assert events: 1 bilingual subtitle event + 1 GlossaryCard event
        assert len(mock_events) == 2, f"Expected 2 events (subtitle + GlossaryCard), got {len(mock_events)}"

        evt_sub = mock_events[0]
        evt_glossary = mock_events[1]

        # [Gemini_3.5_Flash_planning] 更新双语字幕测试，以适配最新版的 Georgia/Hiragino 独立字体和暖黄/暖白配色
        # 英文字号 84 * 0.71 = 59，中文字号 84 * 0.81 = 68，高亮色为 &HC7D36F&
        # [Claude_Sonnet_4.6_Thinking_planning] 中文高亮现在在折行之后执行，所以 \N 不会截断 ASS 标签
        expected_sub_text = r"{\fnGeorgia\fs59\c&H3FD2FF&}Hello {\u1\c&HC7D36F&}world{\u0\c}\N{\fs24\alpha&HFF&} \N{\fnHiragino Sans GB\fs68\alpha&H00&\c&HE9EFF2&}你好{\u1\c&HC7D36F&}世界{\u0\c&HE9EFF2&}"
        assert evt_sub.text == expected_sub_text, (
            f"Expected subtitle text '{expected_sub_text}', got '{evt_sub.text}'"
        )

        # GlossaryCard event: separate event, GlossaryCard style, Songti SC, gray background
        assert evt_glossary.style == "GlossaryCard", (
            f"Expected GlossaryCard style, got '{evt_glossary.style}'"
        )
        # [Claude_Opus_4.8 2026-06-26] 对齐当前实现：释义区字号 = font_size*0.42（≈35pt，刻意小于
        # 英文字幕 59pt，次要辅助排版，见 vertical_processor v2.2.0）；配色为 build_glossary_text
        # 当前输出值（与主字幕高亮独立）。原期望(fs59 + 主字幕色)已随主题演进过时。
        expected_glossary_text = r"{\fnHiragino Sans GB\fs35\c&HDBE5A0&}词汇  {\fnGeorgia\i0\c&H7FD9E8&}world {\fnSongti SC\i1\c&HBDC5C9&}· 世界{\i0}"
        assert evt_glossary.text == expected_glossary_text, (
            f"Expected glossary text '{expected_glossary_text}', got '{evt_glossary.text}'"
        )


    @patch('video_processing.processors.vertical_processor.VerticalCaptionProcessor._validate_input')
    @patch('video_processing.processors.vertical_processor.VerticalCaptionProcessor._get_video_resolution')
    @patch('pysubs2.SSAFile')
    def test_vertical_processor_opaque_box_styling(self, MockSSAFile, mock_get_resolution, mock_validate_input):
        """
        [Gemini_3.5_Flash_planning] Test that VerticalCaptionProcessor uses BorderStyle=3 (Opaque box)
        with semi-transparent black background and appropriate padding (outline) to ensure high readability.
        """
        from video_processing.processors.vertical_processor import VerticalCaptionProcessor

        mock_get_resolution.return_value = (1080, 1920)
        mock_subs_instance = MagicMock()
        mock_subs_instance.styles = {}
        mock_subs_instance.info = {}
        MockSSAFile.return_value = mock_subs_instance

        # Instantiate processor with default style (which has border_style=3)
        processor = VerticalCaptionProcessor(
            input_path=Path("dummy_opaque.mp4"),
            output_path=Path("dummy_output"),
            style="default"
        )

        # Trigger generation
        processor._generate_ass_file(segments=[])

        assert "Default" in mock_subs_instance.styles
        style = mock_subs_instance.styles["Default"]
        
        # Verify Border Style is 3 (Opaque Box)
        assert style.borderstyle == 3, f"Expected borderstyle to be 3 for high contrast vertical subtitles, got {style.borderstyle}"
        
        # Verify BackColor is semi-transparent black (R=0, G=0, B=0, A=200 from default config)
        assert style.backcolor.r == 0 and style.backcolor.g == 0 and style.backcolor.b == 0, \
            "Expected background color to be black"
        assert style.backcolor.a == 200, f"Expected background alpha to be 200, got {style.backcolor.a}"
        
        # Verify outline (padding) is at least 10 pixels
        assert style.outline >= 10, f"Expected outline padding to be at least 10, got {style.outline}"

    def test_tag_aware_wrap(self):
        """
        [Gemini_3.5_Flash_planning] Test that tag_aware_wrap ignores ASS override tags when calculating visual line length,
        preventing tags/words from being broken in the middle, and splitting lines correctly.
        """
        from video_processing.processors.vertical_processor import tag_aware_wrap
        
        # Test case 1: normal text wrapping
        text1 = "A complex mixture of lightweight hydrocarbons"
        wrapped1 = tag_aware_wrap(text1, 27)
        # Expected: "A complex mixture of\Nlightweight hydrocarbons"
        # Since "lightweight" (11) + " hydrocarbons" (13) = 24 <= 27, it should be wrapped before "lightweight"
        assert wrapped1 == "A complex mixture of\\Nlightweight hydrocarbons"
        
        # Test case 2: text containing ASS style override tags
        # "hydrocarbons" is wrapped in {\c&H00D7FF} and {\c} tags. Tag length is 15 chars, but visual length is 12 chars.
        text2 = "A complex mixture of lightweight {\\c&H00D7FF}hydrocarbons{\\c}"
        wrapped2 = tag_aware_wrap(text2, 27)
        # Without tag_aware_wrap, the tag + word is 27 characters.
        # "lightweight {\\c&H00D7FF}hydrocarbons{\\c}" is 11 + 1 + 27 = 39 characters, which exceeds 27.
        # "lightweight" (11) + " " (1) + "hydrocarbons" (12) = 24 <= 27.
        # It should wrap before "lightweight" and keep the tags completely intact with the word!
        assert wrapped2 == "A complex mixture of\\Nlightweight {\\c&H00D7FF}hydrocarbons{\\c}"
        
        # Test case 3: very long highlighted word that exceeds limit (should not crash/infinite loop)
        text3 = "{\\c&H00D7FF}supercalifragilisticexpialidocious{\\c}"
        wrapped3 = tag_aware_wrap(text3, 10)
        assert wrapped3 == "{\\c&H00D7FF}supercalifragilisticexpialidocious{\\c}"

    @patch('video_processing.processors.vertical_processor.VerticalCaptionProcessor._validate_input')
    @patch('video_processing.processors.vertical_processor.VerticalCaptionProcessor._get_video_resolution')
    @patch('pysubs2.SSAFile')
    def test_dynamic_font_scaling_on_long_subtitle(self, MockSSAFile, mock_get_resolution, mock_validate_input):
        """
        [Claude_Sonnet_4.6_Thinking_planning] Verify that when a bilingual subtitle segment would
        overflow SUBTITLE_ZONE_MAX_HEIGHT at default font size, the per-segment font size is
        scaled down automatically, and the resulting estimated height fits within the allowed zone.
        """
        import re
        from video_processing.processors.vertical_processor import (
            VerticalCaptionProcessor, SUBTITLE_ZONE_MAX_HEIGHT,
            SUBTITLE_MIN_EN_SIZE, SUBTITLE_MIN_ZH_SIZE, tag_aware_wrap
        )
        import textwrap as tw

        mock_get_resolution.return_value = (1080, 1920)
        mock_subs_instance = MagicMock()
        mock_subs_instance.styles = {}
        mock_subs_instance.info = {}
        mock_subs_instance.events = []
        MockSSAFile.return_value = mock_subs_instance

        processor = VerticalCaptionProcessor(
            input_path=Path("dummy_vertical.mp4"),
            output_path=Path("dummy_output"),
            style="default",
            bilingual=True,
        )

        # Construct an artificially long segment with 3 EN + 3 ZH lines
        # to trigger overflow at default sizes (en=59, zh=68)
        long_seg = {
            'start': 0.0,
            'end': 5.0,
            'text': ("This is a very long English subtitle sentence that will definitely "
                     "wrap across multiple lines when rendered at the default font size in "
                     "the vertical video canvas layout with limited width."),
            'zh_text': ("这是一段非常长的中文字幕，它将在默认字号下被折成多行，"
                        "用于测试竖屏布局中的动态字体缩放功能，确保任何长度的内容都不会溢出字幕区。"),
            'vocab': {}
        }
        processor._generate_ass_file(segments=[long_seg])

        # Extract the generated dialogue text from the mock SSAEvent call
        assert len(mock_subs_instance.events) >= 1
        evt_text = mock_subs_instance.events[0].text

        # Parse the actual en and zh font sizes used in the ASS override tags
        en_match = re.search(r'\\fnGeorgia\\fs(\d+)', evt_text)
        zh_match = re.search(r'\\fnHiragino Sans GB\\fs(\d+)', evt_text)
        assert en_match, f"No Georgia font tag found in: {evt_text[:80]}"
        assert zh_match, f"No Hiragino Sans GB font tag found in: {evt_text[:80]}"

        actual_en_size = int(en_match.group(1))
        actual_zh_size = int(zh_match.group(1))

        # Verify sizes are at or above minimum
        assert actual_en_size >= SUBTITLE_MIN_EN_SIZE, \
            f"en_size {actual_en_size} below minimum {SUBTITLE_MIN_EN_SIZE}"
        assert actual_zh_size >= SUBTITLE_MIN_ZH_SIZE, \
            f"zh_size {actual_zh_size} below minimum {SUBTITLE_MIN_ZH_SIZE}"

        # Verify estimated height fits within allowed zone using the actual sizes
        safe_width = int(1080 * 0.96)
        w_en = max(20, int(safe_width / (actual_en_size * 0.54)))
        w_zh = max(10, int(safe_width / actual_zh_size))

        en_plain = re.sub(r'\{[^}]*\}', '', long_seg['text'])
        zh_plain = re.sub(r'\{[^}]*\}', '', long_seg['zh_text'])
        wrapped_en = tag_aware_wrap(en_plain, w_en)
        wrapped_zh = tw.fill(zh_plain, width=w_zh)

        en_lines = wrapped_en.count('\\N') + 1
        zh_lines = wrapped_zh.count('\n') + 1
        outline = 10  # default
        est_height = en_lines * actual_en_size * 1.25 + 24 + zh_lines * actual_zh_size * 1.25 + outline * 2

        assert est_height <= SUBTITLE_ZONE_MAX_HEIGHT, (
            f"After font scaling, estimated height {est_height:.0f}px still exceeds "
            f"SUBTITLE_ZONE_MAX_HEIGHT={SUBTITLE_ZONE_MAX_HEIGHT}px. "
            f"en_size={actual_en_size}, zh_size={actual_zh_size}, "
            f"en_lines={en_lines}, zh_lines={zh_lines}"
        )

