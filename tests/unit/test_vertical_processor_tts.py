# -*- coding: utf-8 -*-
"""VerticalCaptionProcessor TTS 自动激活逻辑单元测试

# Modification History
| Version | Date       | Author                     | Description |
| ------- | ---------- | -------------------------- | ----------- |
| 1.0.0   | 2026-05-28 | Gemini_3.5_Flash_planning  | 初始创建，测试非中文视频自动激活 TTS 逻辑 |
"""

import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

# Adjust path to import correctly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../src')))

# Mock dashscope to avoid import issues
mock_dashscope = MagicMock()
sys.modules['dashscope'] = mock_dashscope
sys.modules['dashscope.audio.tts_v2'] = MagicMock()

from video_processing.processors.vertical_processor import VerticalCaptionProcessor

class TestVerticalProcessorTTSAutoActivation:
    """[Gemini_3.5_Flash_planning] 测试 VerticalCaptionProcessor 的 TTS 自动激活与引擎降级逻辑"""

    @patch('video_processing.core.base.VideoProcessorBase._validate_input')
    @patch('video_processing.processors.vertical_processor.subprocess.run')
    @patch('video_processing.processors.vertical_processor.TTSEngine')
    @patch('video_processing.processors.vertical_processor.AudioMixer')
    @patch('src.config.settings.settings')
    def test_auto_activate_cosyvoice_when_key_exists(self, mock_settings, mock_mixer, mock_tts_engine, mock_run, mock_validate):
        """[Gemini_3.5_Flash_planning] 验证当 API Key 存在且为非中文视频时，自动激活 cosyvoice"""
        mock_settings.dashscope_api_key = "test_dashscope_key"
        
        # 准备处理器实例
        processor = VerticalCaptionProcessor(
            input_path=Path("test_video.mp4"),
            src_lang="en",
            tts_provider=None
        )
        
        # 模拟已转录出来的英文 segments
        processor.segments = [
            {"start": 0.0, "end": 2.0, "text": "Hello, welcome.", "zh_text": "你好，欢迎。"}
        ]
        processor.detected_lang = "en"
        
        # 模拟 subprocess.run 返回值以避免真实 ffprobe/ffmpeg 执行报错
        mock_run.return_value = MagicMock(stdout="1920x1080", returncode=0)
        
        # 模拟 _get_audio_duration
        with patch.object(processor, "_get_audio_duration", return_value=1.5):
            processor._burn_subtitles(Path("test_video.ass"))
            
        # 验证 tts_provider 已被自动修改为 cosyvoice
        assert processor.tts_provider == "cosyvoice"
        # 验证 TTSEngine 确实被正确实例化
        mock_tts_engine.assert_called_once()

    @patch('video_processing.core.base.VideoProcessorBase._validate_input')
    @patch('video_processing.processors.vertical_processor.subprocess.run')
    @patch('video_processing.processors.vertical_processor.TTSEngine')
    @patch('video_processing.processors.vertical_processor.AudioMixer')
    @patch('src.config.settings.settings')
    def test_auto_activate_edge_when_key_missing(self, mock_settings, mock_mixer, mock_tts_engine, mock_run, mock_validate):
        """[Gemini_3.5_Flash_planning] 验证当 API Key 缺失且为非中文视频时，降级激活 edge"""
        mock_settings.dashscope_api_key = None
        
        processor = VerticalCaptionProcessor(
            input_path=Path("test_video.mp4"),
            src_lang="en",
            tts_provider=None
        )
        processor.segments = [
            {"start": 0.0, "end": 2.0, "text": "Hello, welcome.", "zh_text": "你好，欢迎。"}
        ]
        processor.detected_lang = "en"
        
        mock_run.return_value = MagicMock(stdout="1920x1080", returncode=0)
        
        with patch.object(processor, "_get_audio_duration", return_value=1.5):
            processor._burn_subtitles(Path("test_video.ass"))
            
        # 验证 tts_provider 降级为 edge
        assert processor.tts_provider == "edge"
        mock_tts_engine.assert_called_once()

    @patch('video_processing.core.base.VideoProcessorBase._validate_input')
    @patch('video_processing.processors.vertical_processor.subprocess.run')
    @patch('video_processing.processors.vertical_processor.TTSEngine')
    @patch('src.config.settings.settings')
    def test_no_activation_for_chinese_by_lang(self, mock_settings, mock_tts_engine, mock_run, mock_validate):
        """[Gemini_3.5_Flash_planning] 验证当 src_lang 或 detected_lang 明确指定为 zh 时，不激活 TTS"""
        mock_settings.dashscope_api_key = "test_dashscope_key"
        
        # 场景 A: src_lang 为 zh
        processor_a = VerticalCaptionProcessor(
            input_path=Path("test_video.mp4"),
            src_lang="zh",
            tts_provider=None
        )
        processor_a.segments = [
            {"start": 0.0, "end": 2.0, "text": "你好，欢迎。", "zh_text": "你好，欢迎。"}
        ]
        mock_run.return_value = MagicMock(stdout="1920x1080", returncode=0)
        processor_a._burn_subtitles(Path("test_video.ass"))
        
        assert processor_a.tts_provider is None
        mock_tts_engine.assert_not_called()

        # 场景 B: detected_lang 为 zh-CN
        processor_b = VerticalCaptionProcessor(
            input_path=Path("test_video.mp4"),
            src_lang="auto",
            tts_provider=None
        )
        processor_b.detected_lang = "zh-CN"
        processor_b.segments = [
            {"start": 0.0, "end": 2.0, "text": "你好，欢迎。", "zh_text": "你好，欢迎。"}
        ]
        processor_b._burn_subtitles(Path("test_video.ass"))
        
        assert processor_b.tts_provider is None
        mock_tts_engine.assert_not_called()

    @patch('video_processing.core.base.VideoProcessorBase._validate_input')
    @patch('video_processing.processors.vertical_processor.subprocess.run')
    @patch('video_processing.processors.vertical_processor.TTSEngine')
    @patch('src.config.settings.settings')
    def test_no_activation_for_chinese_by_content(self, mock_settings, mock_tts_engine, mock_run, mock_validate):
        """[Gemini_3.5_Flash_planning] 验证当 segments 内容中包含中文字符时，不激活 TTS"""
        mock_settings.dashscope_api_key = "test_dashscope_key"
        
        processor = VerticalCaptionProcessor(
            input_path=Path("test_video.mp4"),
            src_lang="auto",
            tts_provider=None
        )
        # 虽然语言设为 auto 且无 detected_lang，但是原文字幕内容包含汉字
        processor.segments = [
            {"start": 0.0, "end": 2.0, "text": "测试中文字符", "zh_text": "测试中文字符"}
        ]
        
        mock_run.return_value = MagicMock(stdout="1920x1080", returncode=0)
        processor._burn_subtitles(Path("test_video.ass"))
        
        assert processor.tts_provider is None
        mock_tts_engine.assert_not_called()
