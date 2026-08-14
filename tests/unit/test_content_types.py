# -*- coding: utf-8 -*-
"""内容生产类型的数据库回归测试。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0 | 2026-08-09 | Codex | 覆盖英语世界短视频标识的默认值、显式写入与切片继承。 |
| 1.1.0 | 2026-08-14 | Codex | 覆盖既有候选的内容生产类型纠正，不改变处理状态。 |
| 1.2.0 | 2026-08-14 | Codex | 覆盖发布前人工复核闸的任务级持久化。 |
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


def test_update_video_content_type_reclassifies_existing_video_without_changing_status(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    db.add_video("existing-video", "Existing", "channel", score=60)

    assert db.update_video_content_type("existing-video", CONTENT_TYPE_ENGLISH_WORLD_SHORT)

    video = db.get_video_by_youtube_id("existing-video")
    assert video["content_type"] == CONTENT_TYPE_ENGLISH_WORLD_SHORT
    assert video["status"] == "PENDING"
    assert video["score"] == 60


def test_publication_review_gate_is_persisted_without_changing_score_or_status(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    db.add_video("review-gated-video", "Review Gated", "channel", score=80)

    assert db.set_publication_review_required("review-gated-video", True)

    video = db.get_video_by_youtube_id("review-gated-video")
    assert video["publication_review_required"] == 1
    assert video["status"] == "PENDING"
    assert video["score"] == 80
    assert db.get_high_score_pending_videos(min_score=75) == []
