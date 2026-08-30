"""YouTube 来源通路的低成本、可归因预检。

元数据可读并不能证明视频 CDN 可下载：前者可能走 YouTube API，后者才会走
实际的 googlevideo 媒体 URL。日更必须先区分“全局通路断了”和“某一候选不合格”，
避免把 VPN、代理、Cookie 或 CDN 故障误报成候选耗尽。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-30 | Codex | 新增 Cookie 格式解析与 64 KiB CDN 范围读取的来源通路预检。 |
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Mapping, Sequence


_AUTH_MARKERS = (
    "sign in to confirm you're not a bot",
    "sign in to confirm you’re not a bot",
    "cookies for authentication",
    "authentication is required",
)
_TRANSPORT_MARKERS = (
    "connection reset",
    "connection refused",
    "network is unreachable",
    "temporary failure in name resolution",
    "could not resolve host",
    "timed out",
    "tls handshake",
)
_MEDIA_REJECTION_MARKERS = (
    "http error 403",
    "http 403",
    "error: 403",
    "forbidden",
    "access denied",
)


@dataclass(frozen=True)
class YoutubeAccessResult:
    """非敏感的来源通路验收结果。"""

    ok: bool
    code: str
    detail: str = ""


def probe_youtube_media_access(
    *,
    ytdlp_path: str,
    cookie_args: Sequence[str],
    probe_url: str,
    environment: Mapping[str, str],
    curl_path: str = "/usr/bin/curl",
    timeout_seconds: int = 45,
) -> YoutubeAccessResult:
    """解析一个真实媒体 URL 并仅读取其前 64 KiB，不产生本地视频文件。"""
    format_selector = "bv*[height<=360][ext=mp4]/bv*[height<=360]/b[height<=360]/b"
    try:
        resolve = subprocess.run(
            [
                ytdlp_path,
                "--get-url",
                "--no-playlist",
                "--no-warnings",
                "-f",
                format_selector,
                *cookie_args,
                probe_url,
            ],
            capture_output=True,
            check=False,
            env=dict(environment),
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return YoutubeAccessResult(False, "TRANSPORT_UNAVAILABLE", "media URL resolution timed out")
    except OSError as exc:
        return YoutubeAccessResult(False, "YTDLP_UNAVAILABLE", type(exc).__name__)
    if resolve.returncode != 0:
        detail = _compact_detail(resolve.stderr or resolve.stdout)
        return YoutubeAccessResult(False, _classify_failure(detail), detail)

    media_urls = [line.strip() for line in resolve.stdout.splitlines() if line.strip().startswith("http")]
    if not media_urls:
        return YoutubeAccessResult(False, "MEDIA_URL_MISSING", "yt-dlp did not return a direct media URL")

    try:
        transfer = subprocess.run(
            [
                curl_path,
                "--fail",
                "--location",
                "--silent",
                "--show-error",
                "--range",
                "0-65535",
                "--connect-timeout",
                "10",
                "--max-time",
                "30",
                "--output",
                "/dev/null",
                media_urls[0],
            ],
            capture_output=True,
            check=False,
            env=dict(environment),
            text=True,
            timeout=35,
        )
    except subprocess.TimeoutExpired:
        return YoutubeAccessResult(False, "TRANSPORT_UNAVAILABLE", "media range request timed out")
    except OSError as exc:
        return YoutubeAccessResult(False, "CURL_UNAVAILABLE", type(exc).__name__)
    if transfer.returncode != 0:
        detail = _compact_detail(transfer.stderr or transfer.stdout)
        return YoutubeAccessResult(False, _classify_failure(detail), detail)
    return YoutubeAccessResult(True, "READY")


def _classify_failure(detail: str) -> str:
    """将外部错误归入可操作的恢复分支，不把细节当成候选质量结论。"""
    normalized = detail.lower()
    if any(marker in normalized for marker in _AUTH_MARKERS):
        return "AUTH_REQUIRED"
    if any(marker in normalized for marker in _TRANSPORT_MARKERS):
        return "TRANSPORT_UNAVAILABLE"
    if any(marker in normalized for marker in _MEDIA_REJECTION_MARKERS):
        return "MEDIA_ACCESS_REJECTED"
    return "SOURCE_ACCESS_UNKNOWN"


def _compact_detail(value: str) -> str:
    """保留可诊断错误类别，避免把冗长或敏感的上游输出写入运行账本。"""
    return " ".join(value.split())[:300] or "external command failed without diagnostic text"
