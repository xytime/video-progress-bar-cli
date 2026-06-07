# -*- coding: utf-8 -*-
"""Unit tests for caption processor layouts.

# Modification History
| Version | Date       | Author                    | Description |
| ------- | ---------- | ------------------------- | ----------- |
| 1.0.0   | 2026-05-21 | Claude_Sonnet_4.6_Thinking | 初始创建 |
| 1.1.0   | 2026-06-07 | Gemini_3.5_Flash_planning | 新增竖屏视频布局与智能字幕坐标位置测试，标有 # [Gemini_3.5_Flash_planning] |
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
        # [Gemini_3.5_Flash_planning] MarginV should be 1400 for vertical video
        processor._generate_ass_file(segments=[])
        assert "Default" in mock_subs_instance.styles
        style = mock_subs_instance.styles["Default"]
        assert style.marginv == 1400, f"Expected subtitle marginv (Y) to be 1400 for vertical video, got {style.marginv}"

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
        # [Gemini_3.5_Flash_planning] MarginV should be 1000 for landscape video
        processor_landscape._generate_ass_file(segments=[])
        assert "Default" in mock_subs_instance_landscape.styles
        style_landscape = mock_subs_instance_landscape.styles["Default"]
        assert style_landscape.marginv == 1000, f"Expected subtitle marginv (Y) to be 1000 for landscape video, got {style_landscape.marginv}"
