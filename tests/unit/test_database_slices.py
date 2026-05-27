"""TDD test cases for database slices and parent-child task cascade actions.

# Modification History
| Version | Date       | Author                    | Description                                     |
|---------|------------|---------------------------|-------------------------------------------------|
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
