# -*- coding: utf-8 -*-
"""本地 IndexTTS 引擎单元测试。"""

from pathlib import Path
from unittest.mock import patch

import pytest

from video_processing.core.tts_engine import TTSEngine, TTSProvider


def _installation(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True)
    (tmp_path / "runner_worker.py").touch()
    (tmp_path / "test_audio.wav").touch()
    return tmp_path


def test_indextts_requires_worker_and_reference_audio(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        TTSEngine(TTSProvider.INDEXTTS, index_tts_path=tmp_path)


def test_indextts_batch_uses_validated_local_reference_audio(tmp_path: Path):
    root = _installation(tmp_path / "indextts")
    engine = TTSEngine(TTSProvider.INDEXTTS, index_tts_path=root)
    output = tmp_path / "audio"
    with patch.object(engine, "_run_indextts_jobs") as run:
        engine.batch_generate([{"text": "你好", "filename": "line.wav"}], output)
    assert run.call_args.args[0][0]["voice_prompt"] == str(root / "test_audio.wav")


def test_indextts_rejects_missing_custom_reference_audio(tmp_path: Path):
    root = _installation(tmp_path / "indextts")
    engine = TTSEngine(TTSProvider.INDEXTTS, index_tts_path=root)
    with pytest.raises(FileNotFoundError):
        engine.batch_generate([{"text": "你好", "filename": "line.wav"}], tmp_path / "audio", "missing.wav")


def test_indextts_single_generation_ignores_edge_default_voice(tmp_path: Path):
    root = _installation(tmp_path / "indextts")
    engine = TTSEngine(TTSProvider.INDEXTTS, index_tts_path=root)
    with patch.object(engine, "_run_indextts_jobs") as run:
        engine.generate_audio("你好", tmp_path / "audio.wav")
    assert run.call_args.args[0][0]["voice_prompt"] == str(root / "test_audio.wav")
