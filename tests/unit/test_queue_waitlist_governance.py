"""待筛选(waitlist)与待处理(queue)队列治理与状态自愈单元测试。

覆盖：
1. 幽灵任务排除与自愈校准 (Ghost tasks calibration and exclusion from queue/waitlist)
2. 待筛选低分素材 TTL 时效淘汰与归档 (Waitlist TTL eviction to EXPIRED)
3. 待处理超期排队丢弃与忽略 (Queue stale discard to IGNORED, single video ignore)
4. 待筛选素材提权入队 (Waitlist promotion to queue/manual, including reviving EXPIRED)
5. 治理相关控制面 API 测试 (cleanup-expired, discard-stale, calibrate, ignore, promote)

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-20 | Antigravity | 初始创建：覆盖待筛选与待处理队列治理、状态自愈与控制面接口 |
"""

import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient

from video_processing.db.database import PipelineDB
from web import app as web_app


@pytest.fixture
def test_db(tmp_path):
    db_file = tmp_path / "test_pipeline.db"
    return PipelineDB(str(db_file))


def test_ghost_tasks_excluded_and_calibrated(test_db):
    """测试已归档/已确认的幽灵 PENDING 任务被 queue 谓词排除，并可自愈校准。"""
    # 1. 插入一个真正的活跃排队任务
    test_db.add_video("active-q-1", "Active Job 1", "TEDx Talks", score=85, source="AUTO")

    # 2. 插入一个原本在历史归档中的高分幽灵任务
    test_db.add_video("ghost-archived-1", "Ghost in Archive", "TEDx Talks", score=82, source="AUTO")
    # 获取其内部自增 ID
    ghost_vid = test_db.get_video_by_youtube_id("ghost-archived-1")["id"]
    with test_db.get_connection() as conn:
        conn.execute(
            """INSERT INTO wechat_publications_historical_archive (
                original_publication_id, archived_at, archive_reason, video_id, state
            ) VALUES (1, CURRENT_TIMESTAMP, 'Operator archived', ?, 'UNCERTAIN')""",
            (ghost_vid,)
        )
        conn.commit()

    # 3. 插入一个在 wechat_publications 中状态为 REJECTED 的幽灵高分任务
    test_db.add_video("ghost-rejected-1", "Ghost Rejected", "Bloomberg", score=88, source="AUTO")
    rejected_vid = test_db.get_video_by_youtube_id("ghost-rejected-1")["id"]
    with test_db.get_connection() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO publication_subjects (id, kind, video_id)
               VALUES (?, 'VIDEO_ITEM', ?)""",
            (f"video:{rejected_vid}", rejected_vid)
        )
        conn.execute(
            """INSERT INTO wechat_publications (
                video_id, subject_id, state, last_error_message
            ) VALUES (?, ?, 'REJECTED', '审核未通过驳回')""",
            (rejected_vid, f"video:{rejected_vid}")
        )
        conn.commit()

    # 4. 插入一个在 wechat_publications 中状态为 PUBLISHED 的幽灵待筛选低分任务
    test_db.add_video("ghost-pub-1", "Ghost Published", "Bloomberg", score=30, source="AUTO")
    pub_vid = test_db.get_video_by_youtube_id("ghost-pub-1")["id"]
    with test_db.get_connection() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO publication_subjects (id, kind, video_id)
               VALUES (?, 'VIDEO_ITEM', ?)""",
            (f"video:{pub_vid}", pub_vid)
        )
        conn.execute(
            """INSERT INTO wechat_publications (
                video_id, subject_id, state
            ) VALUES (?, ?, 'PUBLISHED')""",
            (pub_vid, f"video:{pub_vid}")
        )
        conn.commit()

    # 验证谓词层排除：虽然 status 仍为 PENDING，但已在归档/发布账本中的记录不计入 queue / waitlist
    counts = test_db.get_tab_counts()
    assert counts["queue"] == 1  # 仅 active-q-1

    queue_vids, total_queue = test_db.get_paginated_videos(tab="queue", page=1, size=10)
    assert total_queue == 1
    assert queue_vids[0]["youtube_id"] == "active-q-1"

    # 执行自愈校准
    calibrated_count = test_db.reconcile_pending_ghost_tasks()
    assert calibrated_count == 3

    # 校准后验证真实 status
    v_archived = test_db.get_video_by_youtube_id("ghost-archived-1")
    assert v_archived["status"] == "HISTORICAL_ARCHIVED"

    v_rejected = test_db.get_video_by_youtube_id("ghost-rejected-1")
    assert v_rejected["status"] == "FAILED"
    assert "审核未通过驳回" in (v_rejected["error_msg"] or "")

    v_pub = test_db.get_video_by_youtube_id("ghost-pub-1")
    assert v_pub["status"] == "PUBLISHED"

    # 再次验证 counts 保持准确
    counts_after = test_db.get_tab_counts()
    assert counts_after["queue"] == 1


def test_waitlist_ttl_eviction(test_db):
    """测试待筛选低分素材的 TTL 时效淘汰机制。"""
    # 插入 3 条低分素材
    test_db.add_video("wl-fresh", "Fresh Video", "TEDx Talks", score=30, source="AUTO")
    test_db.add_video("wl-stale-1", "Old Stale 1", "TEDx Talks", score=20, source="AUTO")
    test_db.add_video("wl-stale-2", "Old Stale 2", "Bloomberg", score=15, source="AUTO")
    # 插入 1 条 DISCOVERY 高赞发现素材（受发现防火墙保护，绝不被 waitlist TTL 误淘汰）
    test_db.add_video("wl-discovery", "Discovery Item", "TEDx Talks", score=0, source="DISCOVERY")
    # 插入 1 条高分任务（不应被 waitlist TTL 淘汰）
    test_db.add_video("wl-high-score", "High Score Item", "TEDx Talks", score=80, source="AUTO")

    # 手动将 wl-stale-1, wl-stale-2, wl-discovery, wl-high-score 的 created_at 改为 45 天前
    old_time = (datetime.now() - timedelta(days=45)).strftime("%Y-%m-%d %H:%M:%S")
    with test_db.get_connection() as conn:
        conn.execute(
            "UPDATE processed_videos SET created_at = ? WHERE youtube_id IN ('wl-stale-1', 'wl-stale-2', 'wl-discovery', 'wl-high-score')",
            (old_time,)
        )
        conn.commit()

    # 初始 counts
    counts_init = test_db.get_tab_counts()
    assert counts_init["waitlist"] == 3  # wl-fresh, wl-stale-1, wl-stale-2

    # 执行 30 天 TTL 淘汰
    evicted = test_db.cleanup_expired_waitlist_videos(ttl_days=30)
    assert evicted == 2  # 仅 wl-stale-1, wl-stale-2 被淘汰

    # 验证状态
    v_stale1 = test_db.get_video_by_youtube_id("wl-stale-1")
    assert v_stale1["status"] == "EXPIRED"

    v_stale2 = test_db.get_video_by_youtube_id("wl-stale-2")
    assert v_stale2["status"] == "EXPIRED"

    v_fresh = test_db.get_video_by_youtube_id("wl-fresh")
    assert v_fresh["status"] == "PENDING"

    v_disc = test_db.get_video_by_youtube_id("wl-discovery")
    assert v_disc["status"] == "PENDING"  # DISCOVERY 豁免

    v_high = test_db.get_video_by_youtube_id("wl-high-score")
    assert v_high["status"] == "PENDING"  # 高分豁免

    # 验证 waitlist 列表与计数已更新
    counts_after = test_db.get_tab_counts()
    assert counts_after["waitlist"] == 1

    wl_vids, total = test_db.get_paginated_videos(tab="waitlist")
    assert total == 1
    assert [v["youtube_id"] for v in wl_vids] == ["wl-fresh"]


def test_queue_stale_discard_and_ignore(test_db):
    """测试待处理排队过久丢弃 (Stale Discard) 与单条忽略 (ignore_video)。"""
    test_db.add_video("q-fresh", "Fresh Queue Video", "Channel A", score=80, source="AUTO")
    test_db.add_video("q-stale", "Stale Queue Video", "Channel A", score=85, source="AUTO")

    # 将 q-stale 设为 10 天前入队
    stale_time = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
    with test_db.get_connection() as conn:
        conn.execute(
            "UPDATE processed_videos SET created_at = ? WHERE youtube_id = 'q-stale'",
            (stale_time,)
        )
        conn.commit()

    assert test_db.get_tab_counts()["queue"] == 2

    # 执行超期（7天）放弃
    discarded = test_db.discard_stale_queue_videos(stale_days=7)
    assert discarded == 1

    v_stale = test_db.get_video_by_youtube_id("q-stale")
    assert v_stale["status"] == "IGNORED"

    # 验证 queue 数量减少
    assert test_db.get_tab_counts()["queue"] == 1

    # 测试单条任务人工忽略
    success = test_db.ignore_video("q-fresh", reason="测试人工忽略")
    assert success is True
    v_fresh = test_db.get_video_by_youtube_id("q-fresh")
    assert v_fresh["status"] == "IGNORED"
    assert v_fresh["error_msg"] == "测试人工忽略"
    assert test_db.get_tab_counts()["queue"] == 0


def test_waitlist_promotion(test_db):
    """测试待筛选素材提权入队，包括普通待筛选和已过期的素材。"""
    test_db.add_video("wl-sub75", "Sub 75 Video", "Channel B", score=45, source="AUTO")
    test_db.add_video("wl-expired", "Expired Video", "Channel B", score=25, source="AUTO")
    test_db.update_video_status("wl-expired", "EXPIRED")

    assert test_db.get_tab_counts()["queue"] == 0
    assert test_db.get_tab_counts()["waitlist"] == 1

    # 1. 提权普通待筛选条目
    res = test_db.promote_waitlist_to_queue("wl-sub75", score=100)
    assert res is True
    v_promoted = test_db.get_video_by_youtube_id("wl-sub75")
    assert v_promoted["source"] == "MANUAL"
    assert v_promoted["score"] == 100
    assert v_promoted["is_manually_scored"] == 1
    assert v_promoted["status"] == "PENDING"

    # 2. 提权已过期的条目（复活入队）
    res_exp = test_db.promote_waitlist_to_queue("wl-expired", score=90)
    assert res_exp is True
    v_exp_promoted = test_db.get_video_by_youtube_id("wl-expired")
    assert v_exp_promoted["source"] == "MANUAL"
    assert v_exp_promoted["score"] == 90
    assert v_exp_promoted["status"] == "PENDING"

    # 验证两部视频都已加入待处理队列
    assert test_db.get_tab_counts()["queue"] == 2
    assert test_db.get_tab_counts()["waitlist"] == 0


def test_api_governance_endpoints(test_db, monkeypatch):
    """测试控制面新增的治理接口。"""
    monkeypatch.setattr(web_app, "db", test_db)
    client = TestClient(web_app.app)

    # 准备测试数据
    test_db.add_video("api-wl-stale", "Stale Waitlist", "Channel C", score=10, source="AUTO")
    test_db.add_video("api-q-stale", "Stale Queue", "Channel C", score=90, source="AUTO")
    old_time = (datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d %H:%M:%S")
    with test_db.get_connection() as conn:
        conn.execute(
            "UPDATE processed_videos SET created_at = ? WHERE youtube_id IN ('api-wl-stale', 'api-q-stale')",
            (old_time,)
        )
        conn.commit()

    # 1. POST /api/videos/waitlist/cleanup-expired
    res = client.post("/api/videos/waitlist/cleanup-expired?days=30")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["cleaned_count"] == 1

    # 2. POST /api/videos/queue/discard-stale
    res = client.post("/api/videos/queue/discard-stale?days=7")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["discarded_count"] == 1

    # 3. POST /api/videos/queue/calibrate
    res = client.post("/api/videos/queue/calibrate")
    assert res.status_code == 200
    assert res.json()["success"] is True

    # 4. POST /api/videos/{id}/ignore
    test_db.add_video("api-ignore-me", "To Ignore", "Channel C", score=80, source="AUTO")
    res = client.post("/api/videos/api-ignore-me/ignore")
    assert res.status_code == 200
    assert res.json()["success"] is True
    assert test_db.get_video_by_youtube_id("api-ignore-me")["status"] == "IGNORED"

    # 5. POST /api/videos/{id}/promote (for waitlist)
    test_db.add_video("api-promote-wl", "To Promote", "Channel C", score=40, source="AUTO")
    res = client.post("/api/videos/api-promote-wl/promote")
    assert res.status_code == 200
    assert res.json()["success"] is True
    promoted_v = test_db.get_video_by_youtube_id("api-promote-wl")
    assert promoted_v["source"] == "MANUAL"
    assert promoted_v["score"] == 100
