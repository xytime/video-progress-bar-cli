"""Telegram /last 平台确认发布历史的隔离测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-09 | Codex | 覆盖 /last 账本筛选、范围校验、卡片链接及分包边界。 |
| 1.0.1 | 2026-09-09 | Codex | 断言平台确认及原片时间均标注 BJ 时区。 |
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from bot.api_client import PipelineAPIClient
from bot.formatter import fmt_last_published_entry
from bot.telegram_bot import _reply_last_published_chunks, cmd_last, parse_last_range
from video_processing.db.database import MAX_SQLITE_INTEGER, PipelineDB
from web import app as web_app


def _add_video(db: PipelineDB, youtube_id: str, *, title: str, slice_index: int = 0) -> None:
    assert db.add_video(
        youtube_id, "source title", "test-channel", score=80,
        zh_title=title, slice_index=slice_index,
        source_published_at="2026-08-01T02:03:04Z",
    )


def _publish_douyin(db: PipelineDB, youtube_id: str, *, slice_index: int, stamp: str) -> None:
    publication = db.create_douyin_publication(
        youtube_id,
        f"{slice_index:x}{youtube_id[:1] or 'x'}{'d' * 62}"[:64],
        "/tmp/video.mp4",
        source_kind="HISTORY",
        slice_index=slice_index,
    )
    assert db.update_douyin_publication_state(publication["id"], "PUBLISHED")
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE douyin_publications SET published_at = ? WHERE id = ?",
            (stamp, publication["id"]),
        )
        conn.commit()


def test_confirmed_history_uses_platform_ledger_and_keeps_slices_distinct(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "basevideo01", title="原片")
    _add_video(db, "basevideo01", title="切片", slice_index=1)
    _add_video(db, "workflow001", title="仅工作流")
    db.update_video_status("workflow001", "PUBLISHED")
    _publish_douyin(db, "basevideo01", slice_index=0, stamp="2026-09-08 03:00:00")
    _publish_douyin(db, "basevideo01", slice_index=1, stamp="2026-09-09 03:00:00")

    videos = db.get_recent_confirmed_published_videos(limit=10)

    assert [(video["youtube_id"], video["slice_index"]) for video in videos] == [
        ("basevideo01", 1), ("basevideo01", 0),
    ]
    assert videos[0]["platforms"]["douyin"]["confirmed_at"] == "2026-09-09 03:00:00"


def test_last_endpoint_validates_range_and_forwards_offset(monkeypatch):
    ledger = MagicMock()
    ledger.get_recent_confirmed_published_videos.return_value = [{"youtube_id": "ledger-only"}]
    monkeypatch.setattr(web_app, "db", ledger)
    client = TestClient(web_app.app)

    response = client.get("/api/published-videos", params={"start": 10, "end": 30})

    assert response.status_code == 200
    ledger.get_recent_confirmed_published_videos.assert_called_once_with(offset=9, limit=21)
    assert client.get("/api/published-videos", params={"start": 1, "end": 101}).status_code == 422
    assert client.get(
        "/api/published-videos", params={"start": 1, "end": MAX_SQLITE_INTEGER + 1},
    ).status_code == 422


def test_last_formatter_uses_base_youtube_link_and_caps_bad_legacy_id():
    video = {
        "youtube_id": "ODhae8RmBIc",
        "slice_index": 2,
        "zh_title": "<喜悦> 的涟漪",
        "source_published_at": "2026-09-08T23:15:17Z",
        "last_confirmed_publish_at": "2026-09-09 03:38:31",
        "platforms": {
            "wechat": {"state": "PUBLISHED", "confirmed_at": "2026-09-09 03:00:00"},
            "douyin": {"state": "UNDER_REVIEW", "confirmed_at": None},
            "kuaishou": {"state": "NOT_QUEUED", "confirmed_at": None},
        },
    }

    card = fmt_last_published_entry(10, video)
    assert "&lt;喜悦&gt; 的涟漪" in card
    assert "部分发布 · 09-09 11:38 BJ" in card
    assert "原片：09-09 07:15 BJ" in card
    assert "ODhae8RmBIc_s2" in card
    assert 'href="https://www.youtube.com/watch?v=ODhae8RmBIc"' in card
    assert "watch?v=ODhae8RmBIc_s2" not in card

    oversized_card = fmt_last_published_entry(11, {**video, "youtube_id": "x" * 4000})
    assert len(oversized_card) < 1_000
    assert "x" * 4000 not in oversized_card


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ([], (1, 10)),
        (["30"], (1, 30)),
        (["10-30"], (10, 30)),
        (["0"], None),
        (["1-101"], None),
        (["9" * 5_000], None),
        ([str(MAX_SQLITE_INTEGER + 1)], None),
    ],
)
def test_parse_last_range_enforces_limits(args: list[str], expected: tuple[int, int] | None):
    assert parse_last_range(args) == expected


@pytest.mark.asyncio
async def test_last_command_and_chunking_keep_each_video_card_intact():
    video = {
        "youtube_id": "ODhae8RmBIc", "slice_index": 0, "zh_title": "标题",
        "last_confirmed_publish_at": "2026-09-09 03:38:31", "source_published_at": None,
        "upload_date": None,
        "platforms": {
            "wechat": {"state": "NOT_QUEUED", "confirmed_at": None},
            "douyin": {"state": "PUBLISHED", "confirmed_at": "2026-09-09 03:38:31"},
            "kuaishou": {"state": "NOT_QUEUED", "confirmed_at": None},
        },
    }
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = ["10-10"]
    api = MagicMock()
    api.get_confirmed_published_videos = AsyncMock(return_value=[video])

    with patch("bot.telegram_bot._check_admin", return_value=True), patch("bot.telegram_bot._api", api):
        await cmd_last(update, context)

    api.get_confirmed_published_videos.assert_awaited_once_with(10, 10)
    assert "10. <b>标题</b>" in update.message.reply_text.call_args.args[0]

    message = MagicMock()
    message.reply_text = AsyncMock()
    await _reply_last_published_chunks(message, [video, video], 10, max_length=420)
    sent = [call.args[0] for call in message.reply_text.await_args_list]
    assert all(text.count("<b>标题</b>") == 1 for text in sent)
    assert all(len(text) <= 420 for text in sent)


@pytest.mark.asyncio
@respx.mock
async def test_last_api_client_requests_requested_range():
    base_url = "http://localhost:8765"
    route = respx.get(f"{base_url}/api/published-videos").mock(
        return_value=httpx.Response(200, json={"videos": [{"youtube_id": "ledger-only"}]}),
    )
    client = PipelineAPIClient(base_url=base_url)

    assert await client.get_confirmed_published_videos(10, 30) == [{"youtube_id": "ledger-only"}]
    assert dict(route.calls.last.request.url.params) == {"start": "10", "end": "30"}
