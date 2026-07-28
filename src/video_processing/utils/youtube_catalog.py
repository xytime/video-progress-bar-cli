"""YouTube 频道目录读取：Data API 主源，RSS 无密钥降级。

将候选发现从 yt-dlp 下载链路中分离。官方 API 提供评分所需的统计和时长；
无密钥或 API 暂时不可用时，RSS 至少保住视频 ID、标题和发布时间，等待下次补全。

# Modification History
| Version | Date       | Author | Description |
|---------|------------|--------|-------------|
| 1.0.0 | 2026-07-28 | Codex | 新增 Data API 主源与 RSS 降级，解除频道发现对 yt-dlp 反爬状态的依赖 |
"""

from __future__ import annotations

from dataclasses import dataclass
import datetime as dt
import json
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


_ATOM_NS = "http://www.w3.org/2005/Atom"
_YT_NS = "http://www.youtube.com/xml/schemas/2015"
_API_BASE_URL = "https://www.googleapis.com/youtube/v3"
_RSS_BASE_URL = "https://www.youtube.com/feeds/videos.xml"
_USER_AGENT = "Video-precessing/1.0 channel monitor"


class YouTubeCatalogError(RuntimeError):
    """频道目录的所有安全数据源均不可用。"""


@dataclass(frozen=True)
class ChannelVideo:
    """进入候选库前的最小视频元数据。"""

    youtube_id: str
    title: str
    upload_date: str
    duration_sec: int | None = None
    view_count: int | None = None
    like_count: int | None = None


@dataclass(frozen=True)
class ChannelCatalog:
    """一次频道读取结果；RSS 结果没有完整评分元数据。"""

    source: str
    videos: list[ChannelVideo]
    metadata_complete: bool
    fallback_reason: str | None = None


def fetch_channel_catalog(
    channel_id: str,
    *,
    lookback_days: int,
    api_key: str = "",
    timeout_sec: int = 20,
    now: dt.datetime | None = None,
) -> ChannelCatalog:
    """获取频道近期视频，优先官方 API，失败时退到公开 RSS。"""
    now = now or dt.datetime.now(dt.timezone.utc)
    if api_key:
        try:
            return ChannelCatalog(
                source="youtube_data_api",
                videos=_fetch_data_api_videos(
                    channel_id,
                    lookback_days=lookback_days,
                    api_key=api_key,
                    timeout_sec=timeout_sec,
                    now=now,
                ),
                metadata_complete=True,
            )
        except YouTubeCatalogError as exc:
            fallback_reason = str(exc)
    else:
        fallback_reason = "YOUTUBE_DATA_API_KEY is not configured"

    try:
        return ChannelCatalog(
            source="youtube_rss",
            videos=_fetch_rss_videos(
                channel_id,
                lookback_days=lookback_days,
                timeout_sec=timeout_sec,
                now=now,
            ),
            metadata_complete=False,
            fallback_reason=fallback_reason,
        )
    except YouTubeCatalogError as exc:
        raise YouTubeCatalogError(
            f"Data API unavailable ({fallback_reason}); RSS unavailable ({exc})"
        ) from exc


def _fetch_data_api_videos(
    channel_id: str,
    *,
    lookback_days: int,
    api_key: str,
    timeout_sec: int,
    now: dt.datetime,
) -> list[ChannelVideo]:
    channel_payload = _request_json(
        "channels",
        {"part": "contentDetails", "id": channel_id, "key": api_key},
        timeout_sec,
    )
    items = channel_payload.get("items") or []
    if not items:
        raise YouTubeCatalogError(f"channel {channel_id} was not returned by Data API")
    uploads_playlist_id = (
        items[0].get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
    )
    if not uploads_playlist_id:
        raise YouTubeCatalogError(f"channel {channel_id} has no uploads playlist")

    playlist_payload = _request_json(
        "playlistItems",
        {
            "part": "snippet,contentDetails",
            "playlistId": uploads_playlist_id,
            "maxResults": 12,
            "key": api_key,
        },
        timeout_sec,
    )
    raw_items = playlist_payload.get("items") or []
    recent_items = []
    for item in raw_items:
        try:
            if _is_within_lookback(_published_at(item), lookback_days, now):
                recent_items.append(item)
        except (TypeError, ValueError):
            # 个别异常条目不能拖垮整频道；下轮会由官方目录再次返回。
            continue
    video_ids = [
        item.get("contentDetails", {}).get("videoId")
        or item.get("snippet", {}).get("resourceId", {}).get("videoId")
        for item in recent_items
    ]
    video_ids = [video_id for video_id in video_ids if video_id]
    if not video_ids:
        return []

    details_payload = _request_json(
        "videos",
        {
            "part": "contentDetails,statistics",
            "id": ",".join(video_ids),
            "key": api_key,
        },
        timeout_sec,
    )
    details = {item.get("id"): item for item in details_payload.get("items") or []}
    videos: list[ChannelVideo] = []
    for item in recent_items:
        video_id = (
            item.get("contentDetails", {}).get("videoId")
            or item.get("snippet", {}).get("resourceId", {}).get("videoId")
        )
        detail = details.get(video_id) or {}
        duration_sec = _parse_iso8601_duration(
            detail.get("contentDetails", {}).get("duration", "")
        )
        if duration_sec is None or not 120 < duration_sec < 2700:
            continue
        statistics = detail.get("statistics", {})
        videos.append(
            ChannelVideo(
                youtube_id=video_id,
                title=(item.get("snippet", {}).get("title") or "").strip(),
                upload_date=_published_at(item).strftime("%Y%m%d"),
                duration_sec=duration_sec,
                view_count=_int_or_none(statistics.get("viewCount")),
                like_count=_int_or_none(statistics.get("likeCount")),
            )
        )
    return videos


def _fetch_rss_videos(
    channel_id: str,
    *,
    lookback_days: int,
    timeout_sec: int,
    now: dt.datetime,
) -> list[ChannelVideo]:
    try:
        url = f"{_RSS_BASE_URL}?{urlencode({'channel_id': channel_id})}"
        request = Request(url, headers={"User-Agent": _USER_AGENT})
        with urlopen(request, timeout=timeout_sec) as response:
            body = response.read()
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise YouTubeCatalogError(f"RSS request failed: {exc}") from exc

    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise YouTubeCatalogError(f"RSS XML is invalid: {exc}") from exc

    videos: list[ChannelVideo] = []
    for entry in root.findall(f"{{{_ATOM_NS}}}entry"):
        published_raw = entry.findtext(f"{{{_ATOM_NS}}}published")
        if not published_raw:
            continue
        try:
            published_at = _parse_datetime(published_raw)
        except ValueError:
            continue
        if not _is_within_lookback(published_at, lookback_days, now):
            continue
        video_id = (entry.findtext(f"{{{_YT_NS}}}videoId") or "").strip()
        title = (entry.findtext(f"{{{_ATOM_NS}}}title") or "").strip()
        if video_id and title:
            videos.append(
                ChannelVideo(
                    youtube_id=video_id,
                    title=title,
                    upload_date=published_at.strftime("%Y%m%d"),
                )
            )
    return videos


def _request_json(endpoint: str, params: dict[str, str], timeout_sec: int) -> dict[str, Any]:
    url = f"{_API_BASE_URL}/{endpoint}?{urlencode(params)}"
    request = Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urlopen(request, timeout=timeout_sec) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise YouTubeCatalogError(f"Data API {endpoint} request failed: {exc}") from exc


def _published_at(item: dict[str, Any]) -> dt.datetime:
    raw = (
        item.get("contentDetails", {}).get("videoPublishedAt")
        or item.get("snippet", {}).get("publishedAt")
        or ""
    )
    return _parse_datetime(raw)


def _parse_datetime(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def _is_within_lookback(value: dt.datetime, lookback_days: int, now: dt.datetime) -> bool:
    return value >= now - dt.timedelta(days=lookback_days)


def _parse_iso8601_duration(value: str) -> int | None:
    match = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", value)
    if not match:
        return None
    days, hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
