"""待筛选清空防火墙 (BUG-5) 单元测试

锁定：一键清空待筛选(clear_waitlist 走 DAL get_waitlist_clearable_ids)绝不波及
DISCOVERY（高赞发现）条目；且 DISCOVERY 不计入 waitlist 列表/计数。

真实临时 SQLite，无 mock。

# Modification History
| Version | Date       | Author          | Description                          |
|---------|------------|-----------------|--------------------------------------|
| 1.0.0   | 2026-06-15 | Claude_Opus_4.8 | 初始创建：锁定 BUG-5 DISCOVERY 发现防火墙 |
"""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from video_processing.db.database import PipelineDB


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    yield path
    os.close(fd)
    if os.path.exists(path):
        os.unlink(path)


def _seed(db):
    # 一条普通低分待筛选（应可清空）
    db.add_video(youtube_id="lowscore111", title="low", channel_id="c", score=10, source="AUTO")
    # 一条 DISCOVERY 高赞发现（PENDING/score=0 → 旧逻辑会被清空，新逻辑必须豁免）
    db.add_video(youtube_id="discovery222", title="disc", channel_id="c", score=0, source="DISCOVERY")
    # 一条高分队列（score>=75，本就不在 waitlist）
    db.add_video(youtube_id="highscore333", title="high", channel_id="c", score=90, source="AUTO")


def test_clearable_ids_exclude_discovery(temp_db):
    db = PipelineDB(temp_db)
    _seed(db)
    ids = db.get_waitlist_clearable_ids()
    assert "lowscore111" in ids
    assert "discovery222" not in ids      # ← BUG-5: 发现条目受防火墙保护
    assert "highscore333" not in ids      # 高分不在 waitlist


def test_discovery_survives_clear(temp_db):
    db = PipelineDB(temp_db)
    _seed(db)
    # 模拟 clear_waitlist 的删除步骤
    ids = db.get_waitlist_clearable_ids()
    db.batch_delete_video_records(ids, tombstone=True)

    assert db.get_video_by_youtube_id("lowscore111") is None      # 普通条目被清
    assert db.get_video_by_youtube_id("discovery222") is not None  # DISCOVERY 仍在
    # 且未被写入黑名单（仍可被再次发现）
    assert db.is_blacklisted("discovery222") is False


def test_waitlist_tab_and_count_exclude_discovery(temp_db):
    db = PipelineDB(temp_db)
    _seed(db)
    videos, total = db.get_paginated_videos(tab="waitlist", page=1, size=50)
    wl_ids = {v["youtube_id"] for v in videos}
    assert "lowscore111" in wl_ids
    assert "discovery222" not in wl_ids
    assert total == 1

    counts = db.get_tab_counts()
    assert counts["waitlist"] == 1          # 仅普通条目计入
    assert counts["high_likes"] >= 0        # 发现条目归属高赞 tab，不在 waitlist
