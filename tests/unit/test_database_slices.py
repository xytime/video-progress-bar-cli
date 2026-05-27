"""TDD test cases for database slices and parent-child task cascade actions.

# Modification History
| Version | Date       | Author                    | Description                                     |
|---------|------------|---------------------------|-------------------------------------------------|
| 1.2.0   | 2026-05-27 | Unknown_Model_planning    | 新增测试：验证 purge_stale_tasks, batch_add_videos 补齐 disable_slicing 以及 delete_slices_by_parent_id |
| 1.1.0   | 2026-05-27 | Unknown_Model_planning    | 新增测试：验证多切片视频在不同子切片状态下的 Tab 归属逻辑 |
| 1.0.0   | 2026-05-27 | Gemini_3.5_Flash_planning | Initial TDD test creation for database composite keys |
"""

import pytest
import sqlite3
import tempfile
import os
from pathlib import Path
from video_processing.db.database import PipelineDB

# [Gemini_3.5_Flash_planning] TDD 测试：验证复合唯一索引与级联删除

@pytest.fixture
def temp_db():
    """创建一个临时数据库用于测试"""
    fd, path = tempfile.mkstemp(suffix=".db")
    yield path
    os.close(fd)
    if os.path.exists(path):
        os.unlink(path)

def test_composite_unique_constraint(temp_db):
    """验证 UNIQUE(youtube_id, slice_index) 复合唯一索引约束"""
    db = PipelineDB(temp_db)
    
    # 1. 插入相同 youtube_id 但不同 slice_index 的数据，应该成功
    success1 = db.add_video(
        youtube_id="yid12345678",
        title="Main Video",
        channel_id="channel_1",
        score=80,
        trim_start=None,
        trim_end=None
    )
    assert success1 is True
    
    # 子任务 1 (slice_index = 1)
    # [Gemini_3.5_Flash_planning] 注意：为了支持复合主键，db.add_video 应当在实现时扩展支持传入 slice_index，默认值为 0
    # 在 TDD 阶段，我们假设 add_video 方法已经支持传入 slice_index 参数
    # 2. 插入完全相同的复合键数据 (youtube_id, slice_index=0)，应当抛出错误或返回 False
    # 在现有 add_video 逻辑中，当 IntegrityError 触发时它捕获并返回 False。
    success2 = db.add_video(
        youtube_id="yid12345678",
        title="Duplicate Main Video",
        channel_id="channel_1",
        score=80,
        slice_index=0
    )
    assert success2 is False
    
    # 3. 开启不同 slice_index，应当能成功插入
    success3 = db.add_video(
        youtube_id="yid12345678",
        title="Slice Video 1",
        channel_id="channel_1",
        score=80,
        slice_index=1
    )
    assert success3 is True

def test_batch_insertion_and_cascade(temp_db):
    """测试批量插入与级联删除父子任务关系"""
    db = PipelineDB(temp_db)
    
    # 1. 插入主任务
    db.add_video(
        youtube_id="parent_vid",
        title="Main Parent Video",
        channel_id="channel_1",
        score=90,
        slice_index=0
    )
    parent_video = db.get_video_by_youtube_id("parent_vid", 0)
    assert parent_video is not None
    parent_id = parent_video["id"]
    
    # 2. 批量插入子任务
    slices = [
        {
            "youtube_id": "parent_vid",
            "slice_index": 1,
            "parent_id": parent_id,
            "title": "Slice 1",
            "channel_id": "channel_1",
            "score": 90,
            "source": "AUTO"
        },
        {
            "youtube_id": "parent_vid",
            "slice_index": 2,
            "parent_id": parent_id,
            "title": "Slice 2",
            "channel_id": "channel_1",
            "score": 90,
            "source": "AUTO"
        }
    ]
    assert db.batch_add_videos(slices) is True
    
    # 验证插入成功
    sub_slices = db.get_slices_by_parent_yid("parent_vid")
    assert len(sub_slices) == 2
    assert sub_slices[0]["slice_index"] == 1
    assert sub_slices[1]["slice_index"] == 2
    
    # 3. 验证级联删除 (CASCADE DELETE)
    # 删除父任务
    db.delete_video_record("parent_vid", 0)
    
    # 子任务应当被外键级联删除
    sub_slices_after = db.get_slices_by_parent_yid("parent_vid")
    assert len(sub_slices_after) == 0

def test_segmented_parent_tab_routing(temp_db):
    """[Unknown_Model_planning] 验证当父视频为 SEGMENTED 时，根据子视频切片的不同状态分别路由到不同的选项卡"""
    db = PipelineDB(temp_db)
    
    # 1. 插入父视频 (STATUS = SEGMENTED)
    db.add_video(
        youtube_id="segmented_parent",
        title="Segmented Video Parent",
        channel_id="channel_1",
        score=90,
        slice_index=0
    )
    db.update_video_status("segmented_parent", "SEGMENTED", slice_index=0)
    
    parent_video = db.get_video_by_youtube_id("segmented_parent", 0)
    parent_id = parent_video["id"]
    
    # 2. 插入两个子视频切片，默认状态为 PENDING
    slices = [
        {
            "youtube_id": "segmented_parent",
            "slice_index": 1,
            "parent_id": parent_id,
            "title": "Slice 1",
            "channel_id": "channel_1",
            "score": 90,
            "source": "AUTO"
        },
        {
            "youtube_id": "segmented_parent",
            "slice_index": 2,
            "parent_id": parent_id,
            "title": "Slice 2",
            "channel_id": "channel_1",
            "score": 90,
            "source": "AUTO"
        }
    ]
    db.batch_add_videos(slices)
    
    # 因为子任务在 PENDING 状态（未完成），父任务应该被归入 active（处理中）选项卡，而不应该在 completed 选项卡中
    videos, total = db.get_paginated_videos(tab="active")
    assert any(v["youtube_id"] == "segmented_parent" for v in videos)
    
    videos_comp, total_comp = db.get_paginated_videos(tab="completed")
    assert not any(v["youtube_id"] == "segmented_parent" for v in videos_comp)
    
    counts = db.get_tab_counts()
    assert counts["active"] == 1
    assert counts["completed"] == 0
    assert counts["error"] == 0

    # 3. 将 Slice 1 改为 FAILED，验证父任务进入 error 选项卡
    db.update_video_status("segmented_parent", "FAILED", slice_index=1)
    
    videos_err, total_err = db.get_paginated_videos(tab="error")
    assert any(v["youtube_id"] == "segmented_parent" for v in videos_err)
    
    videos_act, total_act = db.get_paginated_videos(tab="active")
    assert not any(v["youtube_id"] == "segmented_parent" for v in videos_act)
    
    counts = db.get_tab_counts()
    assert counts["active"] == 0
    assert counts["completed"] == 0
    assert counts["error"] == 1

    # 4. 将 Slice 1 改回 PUBLISHED，Slice 2 改为 PUBLISHED，全部完成，验证父任务进入 completed 选项卡
    db.update_video_status("segmented_parent", "PUBLISHED", slice_index=1)
    db.update_video_status("segmented_parent", "PUBLISHED", slice_index=2)
    
    videos_comp2, total_comp2 = db.get_paginated_videos(tab="completed")
    assert any(v["youtube_id"] == "segmented_parent" for v in videos_comp2)
    
    # 验证 slices_count 与 completed_slices_count 字段带出正确
    parent_comp = next(v for v in videos_comp2 if v["youtube_id"] == "segmented_parent")
    assert parent_comp["slices_count"] == 2
    assert parent_comp["completed_slices_count"] == 2
    
    videos_err2, total_err2 = db.get_paginated_videos(tab="error")
    assert not any(v["youtube_id"] == "segmented_parent" for v in videos_err2)
    
    counts = db.get_tab_counts()
    assert counts["active"] == 0
    assert counts["completed"] == 1
    assert counts["error"] == 0


def test_database_disable_slicing_column(temp_db):
    """[Gemini_3.5_Flash_planning] 验证数据库写入与读取时 disable_slicing 值的正确性与默认值"""
    db = PipelineDB(temp_db)
    
    # 1. 默认参数添加视频，验证其 disable_slicing 默认为 1
    db.add_video("default_slicing", "Default title", "channel_1")
    v_default = db.get_video_by_youtube_id("default_slicing")
    assert v_default["disable_slicing"] == 1
    
    # 2. 传入 disable_slicing=0，验证其是否成功保存为 0
    db.add_video("enable_slicing", "Sliced title", "channel_1", disable_slicing=0)
    v_sliced = db.get_video_by_youtube_id("enable_slicing")
    assert v_sliced["disable_slicing"] == 0


def test_purge_stale_tasks_excludes_segmented(temp_db):
    """[Unknown_Model_planning] 验证 purge_stale_tasks 运行后，SEGMENTED 和 IGNORED 的任务状态仍维持原样，不被重置"""
    db = PipelineDB(temp_db)
    
    # 1. 插入状态为 SEGMENTED 和 IGNORED 的任务
    db.add_video("yid_seg", "Segmented Video", "channel_1", slice_index=0)
    db.update_video_status("yid_seg", "SEGMENTED", slice_index=0)
    
    db.add_video("yid_ignored", "Ignored Video", "channel_1", slice_index=1)
    db.update_video_status("yid_ignored", "IGNORED", slice_index=1)
    
    # 2. 插入一个 DOWNLOADING 任务
    db.add_video("yid_dl", "Downloading Video", "channel_1", slice_index=0)
    db.update_video_status("yid_dl", "DOWNLOADING", slice_index=0)
    
    # 手动把他们的 updated_at 设置为 3 小时前，以触发过期
    with db.get_connection() as conn:
        conn.execute("UPDATE processed_videos SET updated_at = datetime('now', '-3 hours')")
        conn.commit()
        
    # 3. 运行清洗，清理 2 小时前的数据
    purged_count = db.purge_stale_tasks(stale_hours=2)
    
    # 4. 验证只有 DOWNLOADING 的被重置了，SEGMENTED 和 IGNORED 没有被重置
    v_seg = db.get_video_by_youtube_id("yid_seg", 0)
    v_ignored = db.get_video_by_youtube_id("yid_ignored", 1)
    v_dl = db.get_video_by_youtube_id("yid_dl", 0)
    
    assert v_seg["status"] == "SEGMENTED"
    assert v_ignored["status"] == "IGNORED"
    assert v_dl["status"] == "PENDING"
    assert purged_count == 1


def test_batch_add_videos_preserves_disable_slicing(temp_db):
    """[Unknown_Model_planning] 验证批量插入子任务时，disable_slicing 值在数据库中正确持久化"""
    db = PipelineDB(temp_db)
    
    slices = [
        {
            "youtube_id": "batch_sliced",
            "slice_index": 1,
            "title": "Slice 1",
            "channel_id": "channel_1",
            "score": 90,
            "source": "AUTO",
            "disable_slicing": 1
        },
        {
            "youtube_id": "batch_sliced",
            "slice_index": 2,
            "title": "Slice 2",
            "channel_id": "channel_1",
            "score": 90,
            "source": "AUTO",
            "disable_slicing": 0
        }
    ]
    
    db.batch_add_videos(slices)
    
    v1 = db.get_video_by_youtube_id("batch_sliced", 1)
    v2 = db.get_video_by_youtube_id("batch_sliced", 2)
    
    assert v1["disable_slicing"] == 1
    assert v2["disable_slicing"] == 0


def test_delete_slices_by_parent_id(temp_db):
    """[Unknown_Model_planning] 验证 delete_slices_by_parent_id 能成功删除关联子切片记录，但保留父任务"""
    db = PipelineDB(temp_db)
    
    db.add_video("parent_yid", "Parent title", "channel_1", slice_index=0)
    parent = db.get_video_by_youtube_id("parent_yid", 0)
    parent_id = parent["id"]
    
    slices = [
        {
            "youtube_id": "parent_yid",
            "slice_index": 1,
            "parent_id": parent_id,
            "title": "Slice 1",
            "channel_id": "channel_1"
        },
        {
            "youtube_id": "parent_yid",
            "slice_index": 2,
            "parent_id": parent_id,
            "title": "Slice 2",
            "channel_id": "channel_1"
        }
    ]
    db.batch_add_videos(slices)
    
    assert len(db.get_slices_by_parent_yid("parent_yid")) == 2
    
    # 删除子切片
    success = db.delete_slices_by_parent_id(parent_id)
    assert success is True
    
    # 验证子切片被删，父任务还在
    assert len(db.get_slices_by_parent_yid("parent_yid")) == 0
    assert db.get_video_by_youtube_id("parent_yid", 0) is not None
