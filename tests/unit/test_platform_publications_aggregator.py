"""单元测试：多平台发布状态数据聚合层测试

# Modification History
| Version | Date       | Author                        | Description                             |
|---------|------------|-------------------------------|-----------------------------------------|
| 1.0.0   | 2026-07-24 | Gemini_3.6_Flash_planning     | 新增多平台发布状态聚合查询单元测试       |
"""
import tempfile
import pytest
from video_processing.db.database import PipelineDB

# [Gemini_3.6_Flash_planning] 校验多平台发布聚合层

@pytest.fixture
def test_db():
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        db = PipelineDB(db_path=tmp.name)
        yield db

def test_get_video_publications_map(test_db):
    # 1. 插入两条测试视频
    with test_db.get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO processed_videos (youtube_id, slice_index, title, channel_id, status, updated_at) VALUES ('yid1', 0, 'Title 1', 'ch1', 'PUBLISHED', '2026-07-24 09:00:00')"
        )
        vid1 = cursor.lastrowid
        cursor = conn.execute(
            "INSERT INTO processed_videos (youtube_id, slice_index, title, channel_id, status) VALUES ('yid2', 0, 'Title 2', 'ch1', 'PENDING')"
        )
        vid2 = cursor.lastrowid

        # 2. 为 vid1 插入快手和抖音记录
        conn.execute(
            """INSERT INTO kuaishou_publications (video_id, asset_sha256, source_kind, state, video_path, attempt_number, published_at, external_url)
               VALUES (?, 'sha1', 'NEW', 'PUBLISHED', '/path1', 1, '2026-07-24 09:05:00', 'https://kuaishou.com/1')""",
            (vid1,)
        )
        conn.execute(
            """INSERT INTO douyin_publications (video_id, asset_sha256, source_kind, state, video_path, attempt_number, last_error_message)
               VALUES (?, 'sha1', 'NEW', 'RETRYABLE_FAILED', '/path1', 1, '网络超时')""",
            (vid1,)
        )
        conn.commit()

    # 3. 执行聚合查询
    pub_map = test_db.get_video_publications_map([vid1, vid2])

    assert vid1 in pub_map
    assert vid2 in pub_map

    v1_pubs = pub_map[vid1]
    assert v1_pubs["wechat"]["state"] == "PUBLISHED"
    assert v1_pubs["wechat"]["published_at"] == "2026-07-24 09:00:00"

    assert v1_pubs["kuaishou"]["state"] == "PUBLISHED"
    assert v1_pubs["kuaishou"]["published_at"] == "2026-07-24 09:05:00"
    assert v1_pubs["kuaishou"]["external_url"] == "https://kuaishou.com/1"

    assert v1_pubs["douyin"]["state"] == "RETRYABLE_FAILED"
    assert v1_pubs["douyin"]["error"] == "网络超时"

    # vid2 初始没有任何快手和抖音记录，应为 NOT_QUEUED
    v2_pubs = pub_map[vid2]
    assert v2_pubs["wechat"]["state"] == "PENDING"
    assert v2_pubs["kuaishou"]["state"] == "NOT_QUEUED"
    assert v2_pubs["douyin"]["state"] == "NOT_QUEUED"
