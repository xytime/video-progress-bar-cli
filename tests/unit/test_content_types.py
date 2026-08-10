# -*- coding: utf-8 -*-
"""内容生产类型的数据库回归测试。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0 | 2026-08-09 | Codex | 覆盖英语世界短视频标识的默认值、显式写入与切片继承。 |
"""

from __future__ import annotations

import os
import tempfile

import pytest

from video_processing.content_types import (
    CONTENT_TYPE_ENGLISH_WORLD_SHORT,
    CONTENT_TYPE_GENERAL,
)
from video_processing.db.database import PipelineDB
from video_processing.study_cards.models import StudyCardContent


@pytest.fixture
def temp_db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        yield path
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_content_type_defaults_and_explicit_english_world_value(temp_db_path):
    db = PipelineDB(temp_db_path)

    assert db.add_video("general-video", "General", "channel")
    assert db.add_video(
        "english-world-video",
        "English World",
        "channel",
        content_type=CONTENT_TYPE_ENGLISH_WORLD_SHORT,
    )

    assert db.get_video_by_youtube_id("general-video")["content_type"] == CONTENT_TYPE_GENERAL
    assert (
        db.get_video_by_youtube_id("english-world-video")["content_type"]
        == CONTENT_TYPE_ENGLISH_WORLD_SHORT
    )


def test_batch_added_slice_preserves_english_world_content_type(temp_db_path):
    db = PipelineDB(temp_db_path)
    assert db.add_video(
        "parent-world-video",
        "English World Parent",
        "channel",
        content_type=CONTENT_TYPE_ENGLISH_WORLD_SHORT,
    )
    parent = db.get_video_by_youtube_id("parent-world-video")

    assert db.batch_add_videos([
        {
            "youtube_id": "parent-world-video",
            "slice_index": 1,
            "parent_id": parent["id"],
            "title": "English World Slice",
            "channel_id": "channel",
            "content_type": CONTENT_TYPE_ENGLISH_WORLD_SHORT,
        },
    ])

    assert db.get_video_by_youtube_id("parent-world-video", 1)["content_type"] == CONTENT_TYPE_ENGLISH_WORLD_SHORT


def test_study_card_content_defaults_to_english_world_short_type():
    content = StudyCardContent.from_mapping({
        "headline_zh": "测试标题",
        "headline_en": "Test headline",
        "english_text": "Test word",
        "translation_zh": "测试正文",
        "words": [{"text": "Test", "start": 0.0, "end": 0.5}],
        "vocabulary": [{"word": "test", "meaning_zh": "测试"}],
    })

    assert content.content_type == CONTENT_TYPE_ENGLISH_WORLD_SHORT
