"""YouTube Data API/RSS 目录解析的单元测试。

# Modification History
| Version | Date       | Author | Description |
|---------|------------|--------|-------------|
| 1.0.0 | 2026-07-28 | Codex | 覆盖时长、日期与 RSS 解析，防止目录降级时误收过期候选 |
"""

import datetime as dt

from video_processing.utils import youtube_catalog


def test_parse_iso8601_duration():
    assert youtube_catalog._parse_iso8601_duration("PT2M1S") == 121
    assert youtube_catalog._parse_iso8601_duration("PT44M59S") == 2699
    assert youtube_catalog._parse_iso8601_duration("invalid") is None


def test_fetch_rss_filters_old_entries(monkeypatch):
    feed = b'''<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015">
      <entry><yt:videoId>recent-id</yt:videoId><title>Recent title</title><published>2026-07-28T00:00:00+00:00</published></entry>
      <entry><yt:videoId>old-id</yt:videoId><title>Old title</title><published>2026-07-20T00:00:00+00:00</published></entry>
    </feed>'''

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return feed

    monkeypatch.setattr(youtube_catalog, "urlopen", lambda *_args, **_kwargs: Response())

    videos = youtube_catalog._fetch_rss_videos(
        "channel", lookback_days=3, timeout_sec=1,
        now=dt.datetime(2026, 7, 28, 12, tzinfo=dt.timezone.utc),
    )

    assert videos == [
        youtube_catalog.ChannelVideo(
            "recent-id", "Recent title", "20260728", source_published_at="2026-07-28T00:00:00Z"
        )
    ]


def test_data_api_catalog_includes_complete_scoring_metadata(monkeypatch):
    payloads = iter([
        {"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "uploads"}}}]},
        {"items": [{
            "snippet": {"title": "API title"},
            "contentDetails": {"videoId": "api-id", "videoPublishedAt": "2026-07-28T00:00:00Z"},
        }]},
        {"items": [{
            "id": "api-id",
            "contentDetails": {"duration": "PT10M"},
            "statistics": {"viewCount": "3000", "likeCount": "120"},
        }]},
    ])
    monkeypatch.setattr(youtube_catalog, "_request_json", lambda *_args, **_kwargs: next(payloads))

    catalog = youtube_catalog.fetch_channel_catalog(
        "channel", lookback_days=3, api_key="test-key", timeout_sec=1,
        now=dt.datetime(2026, 7, 28, 12, tzinfo=dt.timezone.utc),
    )

    assert catalog.source == "youtube_data_api"
    assert catalog.metadata_complete is True
    assert catalog.videos == [
        youtube_catalog.ChannelVideo(
            "api-id", "API title", "20260728", 600, 3000, 120, "2026-07-28T00:00:00Z"
        )
    ]
