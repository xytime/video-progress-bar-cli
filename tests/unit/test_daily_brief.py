"""今日运营简报的账本口径与 Telegram 路由测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-10 | Codex | 覆盖本地简报不依赖 Gemini，且严格区分本地完成和平台确认发布 |
"""
from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.telegram_bot import _is_daily_brief_request, handle_agent_message
from video_processing.daily_brief import collect_daily_brief
from video_processing.db.database import PipelineDB


def test_daily_brief_snapshot_distinguishes_local_and_confirmed_platform_publish(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    db.add_video("today-local", "Local title", "channel", score=90)
    db.add_video("today-platform", "Platform title", "channel", score=90)
    db.update_video_status("today-local", "PUBLISHED")
    db.update_video_status("today-platform", "PUBLISHED")
    kuaishou = db.create_kuaishou_publication(
        "today-platform", "a" * 64, "/tmp/platform.mp4", source_kind="NEW"
    )
    db.update_kuaishou_publication_state(
        kuaishou["id"], "PUBLISHED", external_post_id="ks-post-1", external_url="https://example.com/ks-post-1"
    )
    db.record_censorship_incident(
        "today-local", stage="title", level="P0", action="REJECT", tag="sensitive",
        score=99, matched="x", channel="channel", decision="REJECT_FAILED_BLACKLIST",
    )

    report = collect_daily_brief(db)

    assert "视频号本地完成" in report
    assert "快手已确认发布" in report
    assert "抖音已确认发布         0" in report
    assert "https://example.com/ks-post-1" in report
    assert "创作者页链接：未核验" in report
    assert "时间：" in report


@pytest.mark.asyncio
async def test_daily_brief_message_bypasses_pipeline_agent():
    update = MagicMock()
    update.effective_chat.id = 123
    update.message.text = "今天的简报，今日采编数量、失败数量、敏感词拦截和各平台发布数量"
    update.message.reply_text = AsyncMock()
    context = MagicMock()

    with (
        patch("bot.telegram_bot._check_admin", return_value=True),
        patch("bot.telegram_bot.collect_daily_brief", return_value="<b>日报</b>") as brief,
        patch("bot.telegram_bot.PipelineAgent") as agent,
    ):
        await handle_agent_message(update, context)

    brief.assert_called_once_with()
    agent.assert_not_called()
    update.message.reply_text.assert_awaited_once_with("<b>日报</b>", parse_mode="HTML")


def test_daily_brief_request_requires_today_and_operations_intent():
    assert _is_daily_brief_request("今天的简报，失败数量和平台发布数量")
    assert not _is_daily_brief_request("介绍一下今天的天气")
    assert not _is_daily_brief_request("给我一个发布策略")
