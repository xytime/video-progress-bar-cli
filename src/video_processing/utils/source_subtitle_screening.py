"""选题前源字幕安全筛查：只读抓取 YouTube VTT，不创建任务或下载视频。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-14 | Codex | 新增选题前英文源字幕 fail-closed 筛查，防标题干净但正文涉政漏入审核单。 |
"""

from __future__ import annotations

from dataclasses import dataclass
from html import unescape
import json
import re
import subprocess
from urllib.request import Request, urlopen

from config.settings import settings
from ..censor_engine import CensorResult, check_text


@dataclass(frozen=True)
class SourceSubtitleScreening:
    """选题候选的只读字幕审查结果。"""

    youtube_id: str
    title: str
    subtitle_chars: int
    result: CensorResult | None
    reason: str | None = None

    @property
    def passed(self) -> bool:
        return self.result is not None and not self.result.hit

    def to_dict(self) -> dict:
        result = self.result
        return {
            "youtube_id": self.youtube_id,
            "title": self.title,
            "subtitle_chars": self.subtitle_chars,
            "passed": self.passed,
            "reason": self.reason,
            "censor": None if result is None else {
                "hit": result.hit,
                "level": result.level,
                "tag": result.tag,
                "matched": result.matched,
                "channel": result.channel,
            },
        }


def screen_youtube_source_subtitles(url: str, *, timeout_sec: int = 30) -> SourceSubtitleScreening:
    """读取英文自动字幕并以生产 P0/P1/P2 规则筛查；缺字幕按 fail-closed 返回。"""
    payload = _read_video_metadata(url, timeout_sec)
    youtube_id = str(payload.get("id") or "")
    title = str(payload.get("title") or "")
    vtt_url = _select_english_vtt(payload.get("automatic_captions") or {})
    if not vtt_url:
        return SourceSubtitleScreening(youtube_id, title, 0, None, "未找到英文自动 VTT 字幕")

    try:
        request = Request(vtt_url, headers={"User-Agent": "Video-precessing/1.0 topic-screen"})
        with urlopen(request, timeout=timeout_sec) as response:
            subtitle_text = _parse_webvtt(response.read().decode("utf-8", errors="replace"))
    except OSError as exc:
        return SourceSubtitleScreening(youtube_id, title, 0, None, f"英文 VTT 读取失败：{type(exc).__name__}")

    if not subtitle_text:
        return SourceSubtitleScreening(youtube_id, title, 0, None, "英文 VTT 为空或不可解析")
    return SourceSubtitleScreening(
        youtube_id,
        title,
        len(subtitle_text),
        check_text(en_text=f"{title}\n{subtitle_text}"),
    )


def _read_video_metadata(url: str, timeout_sec: int) -> dict:
    command = [
        settings.ytdlp_path,
        "--dump-single-json",
        "--skip-download",
        "--no-playlist",
        "--no-warnings",
        *settings.get_yt_cookie_args(),
        url,
    ]
    completed = subprocess.run(command, check=True, capture_output=True, text=True, timeout=timeout_sec)
    return json.loads(completed.stdout)


def _select_english_vtt(captions: dict) -> str | None:
    for language in ("en-orig", "en"):
        for track in captions.get(language, []):
            if track.get("ext") == "vtt" and track.get("url"):
                return str(track["url"])
    return None


def _parse_webvtt(raw: str) -> str:
    """去除 VTT 结构、时间轴与标签，保留去重后的可审查正文。"""
    lines: list[str] = []
    for raw_line in raw.splitlines():
        line = raw_line.strip()
        if (
            not line
            or line == "WEBVTT"
            or "-->" in line
            or line.startswith(("Kind:", "Language:", "NOTE"))
            or re.fullmatch(r"\d+", line)
        ):
            continue
        line = unescape(re.sub(r"<[^>]+>", "", line)).strip()
        if line:
            lines.append(line)
    return "\n".join(dict.fromkeys(lines))
