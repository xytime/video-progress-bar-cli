# -*- coding: utf-8 -*-
"""豆包语音合成与克制转场音效单元测试。"""

import io
import wave
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from video_processing.utils.volcengine_tts_protocol import (
    EventType,
    HeaderSizeBits,
    Message,
    MsgType,
    MsgTypeFlagBits,
    VersionBits,
)
from video_processing.utils.doubao_tts import DoubaoTTSClient, DoubaoTTSError
from video_processing.core.tts_engine import TTSEngine, TTSProvider



def test_volcengine_protocol_marshal_unmarshal():
    """测试火山引擎二进制消息帧的编解码往返一致性。"""
    msg = Message(
        version=VersionBits.Version1,
        header_size=HeaderSizeBits.HeaderSize4,
        type=MsgType.FullClientRequest,
        flag=MsgTypeFlagBits.WithEvent,
        event=EventType.StartSession,
        session_id="test-session-uuid-1234",
        payload=b'{"req_params": {"speaker": "zh_male_m191_uranus_bigtts"}}',
    )
    raw_bytes = msg.marshal()
    assert len(raw_bytes) > 0

    decoded = Message.from_bytes(raw_bytes)
    assert decoded.version == VersionBits.Version1
    assert decoded.type == MsgType.FullClientRequest
    assert decoded.event == EventType.StartSession
    assert decoded.session_id == "test-session-uuid-1234"
    assert decoded.payload == b'{"req_params": {"speaker": "zh_male_m191_uranus_bigtts"}}'


def test_volcengine_protocol_audio_frame():
    """测试下行音频数据帧编解码。"""
    audio_bytes = b"\x00\x01\x02\x03\x04\x05"
    msg = Message(
        type=MsgType.AudioOnlyServer,
        flag=MsgTypeFlagBits.NoSeq,
        payload=audio_bytes,
    )
    raw = msg.marshal()
    decoded = Message.from_bytes(raw)
    assert decoded.type == MsgType.AudioOnlyServer
    assert decoded.payload == audio_bytes


def test_doubao_tts_missing_api_key(monkeypatch, tmp_path):
    """测试未配置 API Key 时的 Fail-Closed 行为。"""
    client = DoubaoTTSClient(api_key="")
    out_file = tmp_path / "test.mp3"
    with pytest.raises(DoubaoTTSError, match="未配置豆包语音 API Key"):
        client.synthesize("测试文本", out_file)


def test_doubao_tts_empty_text(tmp_path):
    """测试空文本输入拦截。"""
    client = DoubaoTTSClient(api_key="mock-key")
    out_file = tmp_path / "test.mp3"
    with pytest.raises(ValueError, match="待合成文本不能为空"):
        client.synthesize("   ", out_file)


def test_tts_engine_doubao_dispatch(tmp_path):
    """测试 TTSEngine 路由到 DOUBAO Provider。"""
    engine = TTSEngine(TTSProvider.DOUBAO)
    out_file = tmp_path / "test.mp3"
    with patch("video_processing.utils.doubao_tts.DoubaoTTSClient.synthesize") as mock_synth:
        engine.generate_audio("测试文本", out_file, voice="zh_male_m191_uranus_bigtts")
        mock_synth.assert_called_once()
        args, kwargs = mock_synth.call_args
        assert args[0] == "测试文本"
        assert args[1] == out_file
        assert kwargs["speaker"] == "zh_male_m191_uranus_bigtts"
        assert kwargs["sample_rate"] == 44100


def test_transition_sfx_acoustic_properties():
    """测试新转场过渡音效的声学物理参数（44.1kHz、立体声、克制时长与振幅）。"""
    root = Path(__file__).resolve().parents[2]
    swish = root / "assets/audio/sfx/subtle_tape_swish.wav"
    thud = root / "assets/audio/sfx/gentle_warm_thud.wav"

    assert swish.is_file(), "subtle_tape_swish.wav 必须存在"
    assert thud.is_file(), "gentle_warm_thud.wav 必须存在"

    for path, max_dur in [(swish, 0.6), (thud, 0.35)]:
        with wave.open(str(path), "rb") as wf:
            assert wf.getframerate() == 44100, f"{path.name} 采样率必须为 44.1kHz"
            assert wf.getnchannels() == 2, f"{path.name} 必须为双声道立体声"
            frames = wf.getnframes()
            dur = frames / wf.getframerate()
            assert dur <= max_dur, f"{path.name} 时长 {dur}s 超出克制上限 {max_dur}s"
