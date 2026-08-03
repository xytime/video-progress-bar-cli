"""频道专属普通话译制音色档案测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-03 | Codex | 覆盖频道精确匹配、默认回退与冲突拒绝 |
"""

import json
from pathlib import Path

import pytest

from config.settings import settings
from video_processing.dubbing.voice_profiles import resolve_dubbing_voice_profile


def test_wall_street_truthbombs_uses_its_dedicated_volc_profile(tmp_path: Path, monkeypatch):
    config = tmp_path / "profiles.json"
    config.write_text(json.dumps({"profiles": [{
        "id": "wall-street-v1", "channel_ids": ["UCTK_cv-y88CScoudcXnS1Ew"],
        "provider": "volc_speech", "model": "seed-icl-2.0", "voice_id": "S_divMm4n62",
        "sample_rate": 24000, "preferred_speed": 1.0, "min_speed": 0.9, "max_speed": 1.3,
    }]}), encoding="utf-8")
    monkeypatch.setattr(settings, "dubbing_voice_profiles_path", str(config))

    profile = resolve_dubbing_voice_profile("UCTK_cv-y88CScoudcXnS1Ew", project_root=tmp_path)

    assert profile.provider == "volc_speech"
    assert profile.model == "seed-icl-2.0"
    assert profile.voice_id == "S_divMm4n62"
    assert profile.matched_channel_id == "UCTK_cv-y88CScoudcXnS1Ew"


def test_unmapped_channel_falls_back_to_existing_minimax_default(tmp_path: Path, monkeypatch):
    config = tmp_path / "profiles.json"
    config.write_text('{"profiles": []}', encoding="utf-8")
    monkeypatch.setattr(settings, "dubbing_voice_profiles_path", str(config))
    monkeypatch.setattr(settings, "minimax_tts_voice_id", "fallback-voice")

    profile = resolve_dubbing_voice_profile("another-channel", project_root=tmp_path)

    assert profile.profile_id == "minimax_default_mandarin"
    assert profile.provider == "minimax"
    assert profile.voice_id == "fallback-voice"


def test_duplicate_channel_profiles_fail_closed(tmp_path: Path, monkeypatch):
    config = tmp_path / "profiles.json"
    config.write_text(json.dumps({"profiles": [
        {"id": "one", "channel_ids": ["channel"], "provider": "volc_speech", "model": "seed-icl-2.0", "voice_id": "S_one"},
        {"id": "two", "channel_ids": ["channel"], "provider": "volc_speech", "model": "seed-icl-2.0", "voice_id": "S_two"},
    ]}), encoding="utf-8")
    monkeypatch.setattr(settings, "dubbing_voice_profiles_path", str(config))

    with pytest.raises(RuntimeError, match="多个 TTS 音色档案"):
        resolve_dubbing_voice_profile("channel", project_root=tmp_path)
