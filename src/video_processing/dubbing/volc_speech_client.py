"""火山豆包语音 V3 单向流式 TTS 适配器。

仅处理 API、缓存与实际时间轴；不读取数据库，也不记录 API Key。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-03 | Codex | 新增声音复刻 2.0 的短文本流式合成与缓存适配器 |
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import httpx


API_URL = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"


@dataclass(frozen=True)
class VolcSpeechSynthesis:
    audio_path: Path
    subtitles: List[Dict[str, Any]]
    cache_key: str
    usage_characters: Optional[int]


class VolcSpeechTTSClient:
    """声音复刻 TTS 的小型端口实现，复用连接并把非成功状态转换为可追踪错误。"""

    def __init__(
        self, *, api_key: str, resource_id: str, voice_id: str, sample_rate: int,
        request_interval_sec: float = 0.2, post: Optional[Callable[..., Any]] = None,
    ) -> None:
        if not api_key:
            raise RuntimeError("VOLC_SPEECH_API_KEY 未配置，频道专属火山音色任务未启动。")
        self.api_key = api_key
        self.resource_id = resource_id
        self.voice_id = voice_id
        self.sample_rate = sample_rate
        self.request_interval_sec = request_interval_sec
        self.post = post or self._post
        self._last_request_at = 0.0

    def cache_key(self, text: str, speed: float) -> str:
        material = f"volc_speech|{self.resource_id}|{self.voice_id}|{self.sample_rate}|{speed:.3f}|{text}".encode("utf-8")
        return hashlib.sha256(material).hexdigest()

    def synthesize(self, text: str, *, speed: float, cache_dir: Path) -> VolcSpeechSynthesis:
        """合成完整语义片段；缓存命中不会触发扣费请求。"""
        key = self.cache_key(text, speed)
        cache_dir.mkdir(parents=True, exist_ok=True)
        audio_path = cache_dir / f"{key}.mp3"
        subtitle_path = cache_dir / f"{key}.subtitle.json"
        if audio_path.is_file() and subtitle_path.is_file():
            return VolcSpeechSynthesis(audio_path, self._read_subtitles(subtitle_path), key, None)
        wait = self.request_interval_sec - (time.monotonic() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)
        payload = {
            "user": {"uid": "video-precessing-dubbing"},
            "req_params": {
                "text": text,
                "speaker": self.voice_id,
                "audio_params": {
                    "format": "mp3", "sample_rate": self.sample_rate,
                    "speech_rate": max(-50, min(100, round((speed - 1.0) * 100))),
                    "enable_subtitle": True,
                },
            },
        }
        response = self.post(
            API_URL,
            headers={
                "X-Api-Key": self.api_key,
                "X-Api-Resource-Id": self.resource_id,
                "X-Api-Request-Id": str(uuid.uuid4()),
                "X-Control-Require-Usage-Tokens-Return": "*",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        self._last_request_at = time.monotonic()
        frames = self._decode_frames(response.text)
        final = next((frame for frame in reversed(frames) if frame.get("code") is not None), {})
        if response.status_code != 200 or final.get("code") != 20000000:
            error = self._error_from_response(response, frames)
            raise RuntimeError(error)
        audio = bytearray()
        for frame in frames:
            data = frame.get("data")
            if isinstance(data, str):
                try:
                    audio.extend(base64.b64decode(data))
                except ValueError as exc:
                    raise RuntimeError("火山语音响应包含无效音频分片。") from exc
        if not audio:
            raise RuntimeError("火山语音响应未包含音频数据。")
        audio_path.write_bytes(audio)
        subtitles = self._extract_subtitles(frames)
        subtitle_path.write_text(json.dumps(subtitles, ensure_ascii=False), encoding="utf-8")
        usage = final.get("usage") or {}
        words = usage.get("text_words") if isinstance(usage, dict) else None
        return VolcSpeechSynthesis(audio_path, subtitles, key, int(words) if isinstance(words, (int, float)) else None)

    @staticmethod
    def _post(url: str, *, headers: Dict[str, str], json: Dict[str, Any]) -> httpx.Response:
        with httpx.Client(timeout=120.0, trust_env=False) as client:
            return client.post(url, headers=headers, json=json)

    @staticmethod
    def _decode_frames(raw: str) -> List[Dict[str, Any]]:
        decoder, index, frames = json.JSONDecoder(), 0, []
        try:
            while index < len(raw):
                while index < len(raw) and raw[index].isspace():
                    index += 1
                if index >= len(raw):
                    break
                frame, index = decoder.raw_decode(raw, index)
                if isinstance(frame, dict):
                    frames.append(frame)
        except json.JSONDecodeError as exc:
            raise RuntimeError("火山语音响应不是有效的流式 JSON。") from exc
        return frames

    @staticmethod
    def _error_from_response(response: Any, frames: List[Dict[str, Any]]) -> str:
        header = {}
        try:
            payload = response.json()
            header = payload.get("header") or {} if isinstance(payload, dict) else {}
        except (ValueError, TypeError):
            pass
        final = next((frame for frame in reversed(frames) if frame.get("code") is not None), {})
        code = header.get("code", final.get("code", "unknown"))
        message = header.get("message", final.get("message", "unknown"))
        logid = response.headers.get("X-Tt-Logid") or response.headers.get("X-Api-Request-Id") or "unknown"
        return f"火山语音合成失败: http_status={response.status_code}, code={code}, message={message}, logid={logid}"

    @staticmethod
    def _extract_subtitles(frames: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        subtitles: List[Dict[str, Any]] = []
        for frame in frames:
            for candidate in (frame.get("sentence"), frame.get("subtitle"), (frame.get("addition") or {}).get("subtitle")):
                items = candidate if isinstance(candidate, list) else [candidate]
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    text = str(item.get("text") or item.get("pronounce_text") or "").strip()
                    start, end = item.get("time_begin", item.get("start")), item.get("time_end", item.get("end"))
                    if text and isinstance(start, (int, float)) and isinstance(end, (int, float)) and end > start:
                        subtitles.append({"text": text, "time_begin": round(start), "time_end": round(end)})
        return subtitles

    @staticmethod
    def _read_subtitles(path: Path) -> List[Dict[str, Any]]:
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("火山语音缓存字幕文件损坏。") from exc
        return [item for item in loaded if isinstance(item, dict)] if isinstance(loaded, list) else []
