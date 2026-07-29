"""MiniMax speech-2.8-turbo 的最小生产适配器。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-29 | Codex | 增加带缓存键、实际字幕时间轴和限流重试的 MiniMax TTS 适配器 |
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


API_URL = "https://api.minimaxi.com/v1/t2a_v2"


@dataclass(frozen=True)
class MiniMaxSynthesis:
    audio_path: Path
    subtitles: List[Dict[str, Any]]
    cache_key: str
    usage_characters: Optional[int]


class MiniMaxTTSClient:
    """只负责 API 请求、缓存和返回实际时间轴，不读取数据库。"""

    def __init__(
        self, *, api_key: str, model: str, voice_id: str, request_interval_sec: float = 1.1,
        urlopen: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        if not api_key:
            raise RuntimeError("MINIMAX_API_KEY 未配置，配音任务未启动。")
        self.api_key = api_key
        self.model = model
        self.voice_id = voice_id
        self.request_interval_sec = request_interval_sec
        self.urlopen = urlopen
        self._last_request_at = 0.0

    def cache_key(self, text: str, speed: float) -> str:
        material = f"{self.model}|{self.voice_id}|{speed:.3f}|{text}".encode("utf-8")
        return hashlib.sha256(material).hexdigest()

    def synthesize(self, text: str, *, speed: float, cache_dir: Path) -> MiniMaxSynthesis:
        """合成一段完整语义文本；命中缓存不触发额外收费请求。"""
        key = self.cache_key(text, speed)
        cache_dir.mkdir(parents=True, exist_ok=True)
        audio_path = cache_dir / f"{key}.wav"
        subtitle_path = cache_dir / f"{key}.subtitle.json"
        if audio_path.is_file() and subtitle_path.is_file():
            return MiniMaxSynthesis(audio_path, self._read_subtitles(subtitle_path), key, None)

        payload = {
            "model": self.model,
            "text": text,
            "stream": False,
            "voice_setting": {"voice_id": self.voice_id, "speed": round(speed, 3), "vol": 1, "pitch": 0, "emotion": "calm"},
            "audio_setting": {"sample_rate": 44100, "bitrate": 128000, "format": "wav", "channel": 1},
            "subtitle_enable": True,
            "subtitle_type": "sentence",
            "output_format": "hex",
            "language_boost": "Chinese",
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            API_URL, data=body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}, method="POST",
        )
        response: Dict[str, Any] = {}
        for retry in range(4):
            wait = self.request_interval_sec - (time.monotonic() - self._last_request_at)
            if wait > 0:
                time.sleep(wait)
            try:
                with self.urlopen(request, timeout=120) as raw_response:
                    response = json.loads(raw_response.read().decode("utf-8"))
                self._last_request_at = time.monotonic()
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"MiniMax 请求失败: {type(exc).__name__}") from exc
            if int((response.get("base_resp") or {}).get("status_code", -1)) != 1002:
                break
            time.sleep(2 ** retry)

        base = response.get("base_resp") or {}
        if int(base.get("status_code", -1)) != 0:
            raise RuntimeError(f"MiniMax 合成失败: status_code={base.get('status_code')}, message={base.get('status_msg', '')}")
        audio_hex = str((response.get("data") or {}).get("audio") or "").strip()
        if not audio_hex:
            raise RuntimeError("MiniMax 响应缺少音频数据。")
        try:
            audio_path.write_bytes(bytes.fromhex(audio_hex))
        except ValueError as exc:
            raise RuntimeError("MiniMax 返回的音频不是有效 hex 数据。") from exc
        subtitle_url = (response.get("data") or {}).get("subtitle_file")
        subtitles = self._download_subtitles(str(subtitle_url)) if subtitle_url else []
        subtitle_path.write_text(json.dumps(subtitles, ensure_ascii=False), encoding="utf-8")
        usage = (response.get("extra_info") or {}).get("usage_characters")
        return MiniMaxSynthesis(audio_path, subtitles, key, int(usage) if usage is not None else None)

    def _download_subtitles(self, url: str) -> List[Dict[str, Any]]:
        request = urllib.request.Request(url, headers={"User-Agent": "Video-precessing dubbing studio"})
        try:
            with self.urlopen(request, timeout=30) as raw_response:
                payload = json.loads(raw_response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"MiniMax 字幕时间轴下载失败: {type(exc).__name__}") from exc
        if not isinstance(payload, list):
            raise RuntimeError("MiniMax 字幕时间轴格式错误。")
        return [item for item in payload if isinstance(item, dict)]

    @staticmethod
    def _read_subtitles(path: Path) -> List[Dict[str, Any]]:
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("MiniMax 缓存字幕文件损坏。") from exc
        return [item for item in loaded if isinstance(item, dict)] if isinstance(loaded, list) else []
