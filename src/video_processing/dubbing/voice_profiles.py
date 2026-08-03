"""人工普通话译制的频道音色档案解析器。

音色档案只保存可审计、可提交的频道映射与合成参数；凭据始终由 Settings 从本机 .env 注入。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-03 | Codex | 新增频道专属火山声音复刻档案与默认 MiniMax 回退解析 |
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from config.settings import settings


@dataclass(frozen=True)
class DubbingVoiceProfile:
    """一次译制任务可持久化的非密钥 TTS 选择。"""

    profile_id: str
    provider: str
    model: str
    voice_id: str
    sample_rate: int
    preferred_speed: float
    min_speed: float
    max_speed: float
    description: str
    matched_channel_id: Optional[str] = None

    def snapshot(self, *, audio_policy: str) -> Dict[str, Any]:
        """返回可写入任务 config_json 的安全快照，绝不包含 API Key。"""
        return {
            "profile_id": self.profile_id,
            "provider": self.provider,
            "model": self.model,
            "voice_id": self.voice_id,
            "sample_rate": self.sample_rate,
            "preferred_speed": self.preferred_speed,
            "min_speed": self.min_speed,
            "max_speed": self.max_speed,
            "description": self.description,
            "matched_channel_id": self.matched_channel_id,
            "audio_policy": audio_policy,
        }


def resolve_dubbing_voice_profile(channel_id: Optional[str], *, project_root: Optional[Path] = None) -> DubbingVoiceProfile:
    """精确匹配频道专属档案；无条目才回退既有 MiniMax 默认音色。"""
    root = project_root or settings.project_root
    configured_path = Path(settings.dubbing_voice_profiles_path)
    path = configured_path if configured_path.is_absolute() else root / configured_path
    if not path.is_file():
        return _default_profile()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"频道音色档案无法读取: {path}") from exc
    profiles = payload.get("profiles") if isinstance(payload, dict) else None
    if not isinstance(profiles, list):
        raise RuntimeError(f"频道音色档案格式错误: {path}")
    matches = [item for item in profiles if isinstance(item, dict) and channel_id in item.get("channel_ids", [])]
    if not matches:
        return _default_profile()
    if len(matches) != 1:
        raise RuntimeError(f"频道 {channel_id or '<empty>'} 匹配到多个 TTS 音色档案，拒绝猜测。")
    return _parse_profile(matches[0], matched_channel_id=channel_id)


def profile_from_snapshot(snapshot: Dict[str, Any]) -> DubbingVoiceProfile:
    """从任务创建时的快照恢复选择，防止日后改配置重写历史任务。"""
    if not snapshot or not snapshot.get("profile_id"):
        return _default_profile()
    persisted = dict(snapshot)
    persisted["id"] = persisted["profile_id"]
    return _parse_profile(persisted, matched_channel_id=persisted.get("matched_channel_id"))


def _default_profile() -> DubbingVoiceProfile:
    return DubbingVoiceProfile(
        profile_id="minimax_default_mandarin",
        provider="minimax",
        model=settings.minimax_tts_model,
        voice_id=settings.minimax_tts_voice_id,
        sample_rate=44100,
        preferred_speed=settings.minimax_tts_preferred_speed,
        min_speed=settings.minimax_tts_min_speed,
        max_speed=settings.minimax_tts_max_speed,
        description="未命中频道专属档案时使用的既有 MiniMax 普通话默认音色。",
    )


def _parse_profile(raw: Dict[str, Any], *, matched_channel_id: Optional[str]) -> DubbingVoiceProfile:
    required = ("id", "provider", "model", "voice_id")
    missing = [key for key in required if not str(raw.get(key) or "").strip()]
    if missing:
        raise RuntimeError(f"频道音色档案缺少字段: {', '.join(missing)}")
    provider = str(raw["provider"]).strip().lower()
    if provider not in {"minimax", "volc_speech"}:
        raise RuntimeError(f"频道音色档案使用了不支持的 provider: {provider}")
    try:
        min_speed = float(raw.get("min_speed", 0.9))
        preferred_speed = float(raw.get("preferred_speed", 1.0))
        max_speed = float(raw.get("max_speed", 1.3))
        sample_rate = int(raw.get("sample_rate", 24000))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("频道音色档案中的音频参数必须是数字。") from exc
    if not (0.5 <= min_speed <= preferred_speed <= max_speed <= 2.0):
        raise RuntimeError("频道音色档案的语速范围无效。")
    if sample_rate not in {8000, 16000, 22050, 24000, 32000, 44100, 48000}:
        raise RuntimeError("频道音色档案的 sample_rate 不受支持。")
    return DubbingVoiceProfile(
        profile_id=str(raw["id"]).strip(), provider=provider, model=str(raw["model"]).strip(),
        voice_id=str(raw["voice_id"]).strip(), sample_rate=sample_rate,
        preferred_speed=preferred_speed, min_speed=min_speed, max_speed=max_speed,
        description=str(raw.get("description") or "").strip(), matched_channel_id=matched_channel_id,
    )
