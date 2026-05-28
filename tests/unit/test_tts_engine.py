# -*- coding: utf-8 -*-
"""TTS 引擎单元测试

# Modification History
| Version | Date       | Author                     | Description |
| ------- | ---------- | -------------------------- | ----------- |
| 1.0.0   | 2026-05-28 | Gemini_3.5_Flash_planning  | 初始创建，完整测试播音音色池与模型映射逻辑 |
"""

import os
import sys
from unittest.mock import patch, MagicMock

# Adjust path to import correctly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../src')))

# [Gemini_3.5_Flash_planning] Mock dashscope to avoid dependency issues during imports
mock_dashscope = MagicMock()
mock_speech_synthesizer = MagicMock()
mock_result_callback = MagicMock()
mock_audio_format = MagicMock()

sys.modules['dashscope'] = mock_dashscope
sys.modules['dashscope.audio.tts_v2'] = MagicMock()
sys.modules['dashscope.audio.tts_v2'].SpeechSynthesizer = mock_speech_synthesizer
sys.modules['dashscope.audio.tts_v2'].ResultCallback = mock_result_callback
sys.modules['dashscope.audio.tts_v2'].AudioFormat = mock_audio_format

from video_processing.core.tts_engine import (
    TTSEngine,
    TTSProvider,
    COSYVOICE_BROADCAST_VOICES,
    pick_broadcast_voice,
)

class TestTTSEngineTDD:
    """TTS 引擎新版功能 TDD 测试类"""

    def test_broadcast_voices_pool(self):
        """验证 COSYVOICE_BROADCAST_VOICES 音色池包含预期的 6 个音色"""
        # [Gemini_3.5_Flash_planning]
        expected_voices = [
            "longshuo_v3",
            "longshu_v3",
            "loongbella_v3",
            "longjing_v2",
            "longanzhi_v3",
            "longxiaochun_v3",
        ]
        assert len(COSYVOICE_BROADCAST_VOICES) == 6
        assert set(COSYVOICE_BROADCAST_VOICES) == set(expected_voices)

    def test_pick_broadcast_voice_randomness(self):
        """验证 pick_broadcast_voice() 确实能够从音色池中随机选择"""
        # [Gemini_3.5_Flash_planning]
        picks = [pick_broadcast_voice() for _ in range(50)]
        for voice in picks:
            assert voice in COSYVOICE_BROADCAST_VOICES
        
        # 统计独立选出的音色个数，应该多于 1 个（极高概率，几乎为 100%）
        assert len(set(picks)) > 1

    @patch('video_processing.core.tts_engine.pick_broadcast_voice')
    @patch('src.config.settings.settings')
    def test_tts_engine_auto_voice(self, mock_settings, mock_pick_voice):
        """验证 cosyvoice_voice='auto' 时，TTSEngine 会随机选取并锁定音色"""
        # [Gemini_3.5_Flash_planning]
        mock_pick_voice.return_value = "longjing_v2"
        mock_settings.dashscope_api_key = "test_key"

        engine = TTSEngine(
            provider=TTSProvider.COSYVOICE,
            cosyvoice_voice="auto",
            dashscope_api_key="test_key"
        )
        assert engine.cosyvoice_voice == "longjing_v2"
        mock_pick_voice.assert_called_once()

    @patch('src.config.settings.settings')
    def test_model_mapping_rules(self, mock_settings):
        """验证音色与模型的映射规则"""
        # [Gemini_3.5_Flash_planning]
        mock_settings.dashscope_api_key = "test_key"

        # Case 1: _v2 后缀 -> cosyvoice-v2
        engine_v2 = TTSEngine(
            provider=TTSProvider.COSYVOICE,
            cosyvoice_voice="longjing_v2",
            dashscope_api_key="test_key"
        )
        assert engine_v2.cosyvoice_model == "cosyvoice-v2"

        # Case 2: _v3 后缀 -> cosyvoice-v3-flash
        engine_v3 = TTSEngine(
            provider=TTSProvider.COSYVOICE,
            cosyvoice_voice="longanzhi_v3",
            dashscope_api_key="test_key"
        )
        assert engine_v3.cosyvoice_model == "cosyvoice-v3-flash"

        # Case 3: 无后缀 Benchmark -> cosyvoice-v2
        engine_bench = TTSEngine(
            provider=TTSProvider.COSYVOICE,
            cosyvoice_voice="longanyang",
            dashscope_api_key="test_key"
        )
        assert engine_bench.cosyvoice_model == "cosyvoice-v2"

        # Case 4: longwan -> cosyvoice-v1
        engine_v1 = TTSEngine(
            provider=TTSProvider.COSYVOICE,
            cosyvoice_voice="longwan",
            dashscope_api_key="test_key"
        )
        assert engine_v1.cosyvoice_model == "cosyvoice-v1"

    @patch('src.config.settings.settings')
    def test_instruction_defense_filter(self, mock_settings):
        """验证只有标杆音色 longanyang/longanhuan 支持 instruction, 其它音色被防御置空"""
        # [Gemini_3.5_Flash_planning]
        mock_settings.dashscope_api_key = "test_key"
        custom_instruction = "test instruction"

        # longanyang 应该保留 instruction
        engine_yang = TTSEngine(
            provider=TTSProvider.COSYVOICE,
            cosyvoice_voice="longanyang",
            cosyvoice_instruction=custom_instruction,
            dashscope_api_key="test_key"
        )
        assert engine_yang.cosyvoice_instruction == custom_instruction

        # longanhuan 应该保留 instruction
        engine_huan = TTSEngine(
            provider=TTSProvider.COSYVOICE,
            cosyvoice_voice="longanhuan",
            cosyvoice_instruction=custom_instruction,
            dashscope_api_key="test_key"
        )
        assert engine_huan.cosyvoice_instruction == custom_instruction

        # 其他音色（如 longjing_v2）应该置为 None
        engine_other = TTSEngine(
            provider=TTSProvider.COSYVOICE,
            cosyvoice_voice="longjing_v2",
            cosyvoice_instruction=custom_instruction,
            dashscope_api_key="test_key"
        )
        assert engine_other.cosyvoice_instruction is None

    @patch.dict(os.environ, {}, clear=True)
    @patch('src.config.settings.settings')
    def test_dashscope_api_key_loading(self, mock_settings):
        """验证 API Key 获取的优先级及未配置报错行为"""
        # [Gemini_3.5_Flash_planning]
        mock_settings.dashscope_api_key = None

        # 1. 没有任何 Key 配置时，抛出 ValueError
        try:
            TTSEngine(provider=TTSProvider.COSYVOICE)
            assert False, "Expected ValueError when no key is present"
        except ValueError as e:
            assert "未配置 DASHSCOPE_API_KEY" in str(e)

        # 2. 只有 settings 包含 Key 时，能正常初始化
        mock_settings.dashscope_api_key = "settings_key"
        engine_settings = TTSEngine(provider=TTSProvider.COSYVOICE)
        assert engine_settings._dashscope_api_key == "settings_key"

        # 3. 环境变量包含 Key 时，能正常初始化
        mock_settings.dashscope_api_key = None
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "env_key"}):
            engine_env = TTSEngine(provider=TTSProvider.COSYVOICE)
            assert engine_env._dashscope_api_key == "env_key"

        # 4. 显式参数传递 Key 时，优先级最高
        mock_settings.dashscope_api_key = "settings_key"
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "env_key"}):
            engine_param = TTSEngine(
                provider=TTSProvider.COSYVOICE,
                dashscope_api_key="param_key"
            )
            assert engine_param._dashscope_api_key == "param_key"
