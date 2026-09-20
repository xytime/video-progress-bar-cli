"""数据库层频道管理（暂停/恢复）与生产转化漏斗测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-20 | Gemini | 初始创建：覆盖频道 PAUSED/APPROVED 状态切换、受管白名单查询以及多时间窗口漏斗统计。 |
"""

from datetime import datetime, timedelta
import pytest

from video_processing.db.database import PipelineDB


def test_set_channel_paused_and_get_managed_channels(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))

    # 录入不同状态的频道
    db.add_channel("UC_ACTIVE", "Active Channel", status="APPROVED")
    db.add_channel("UC_PAUSED", "Paused Channel", status="PAUSED")
    db.add_channel("UC_MANUAL", "Manual Channel", status="MANUAL_ONLY")

    # 1. 验证 get_approved_channels 只包含 APPROVED
    approved = db.get_approved_channels()
    assert [c["channel_id"] for c in approved] == ["UC_ACTIVE"]

    # 2. 验证 get_managed_channels 包含 APPROVED 和 PAUSED，但不包含 MANUAL_ONLY
    managed = db.get_managed_channels()
    managed_ids = [c["channel_id"] for c in managed]
    assert "UC_ACTIVE" in managed_ids
    assert "UC_PAUSED" in managed_ids
    assert "UC_MANUAL" not in managed_ids

    # 3. 暂停已激活频道
    ok = db.set_channel_paused("UC_ACTIVE", True)
    assert ok is True
    channel = db.get_channel_by_id("UC_ACTIVE")
    assert channel["status"] == "PAUSED"

    # 再次调用 get_approved_channels，UC_ACTIVE 应不再出现
    assert len(db.get_approved_channels()) == 0

    # 4. 恢复已暂停频道
    ok = db.set_channel_paused("UC_ACTIVE", False)
    assert ok is True
    channel = db.get_channel_by_id("UC_ACTIVE")
    assert channel["status"] == "APPROVED"
    assert len(db.get_approved_channels()) == 1

    # 5. 对非白名单状态（MANUAL_ONLY）或不存在的频道调用暂停，应拒绝
    assert db.set_channel_paused("UC_MANUAL", True) is False
    assert db.set_channel_paused("UC_NONEXISTENT", True) is False


def test_get_channel_funnel_metrics_time_windows(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    cid = "UC_TEST_FUNNEL"
    db.add_channel(cid, "Funnel Test Channel", status="APPROVED")

    now = datetime.utcnow()
    t_3d = (now - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    t_15d = (now - timedelta(days=15)).strftime("%Y-%m-%d %H:%M:%S")
    t_45d = (now - timedelta(days=45)).strftime("%Y-%m-%d %H:%M:%S")

    # 插入不同时间切片和状态的视频记录
    # 近 3 天：2 条采集，1 条高分发布，1 条低分 PENDING
    db.add_video("vid_recent_pub", "Recent Pub", cid, score=85)
    db.update_video_status("vid_recent_pub", "PUBLISHED")
    with db.get_connection() as conn:
        conn.execute("UPDATE processed_videos SET created_at = ? WHERE youtube_id = ?", (t_3d, "vid_recent_pub"))

    db.add_video("vid_recent_low", "Recent Low", cid, score=40)
    with db.get_connection() as conn:
        conn.execute("UPDATE processed_videos SET created_at = ? WHERE youtube_id = ?", (t_3d, "vid_recent_low"))

    # 15 天前（落在 30 天内，不在 7 天内）：1 条高分但失败，带敏感词标签
    db.add_video("vid_mid_fail", "Mid Fail", cid, score=78, censor_tag="🔴 敏感词")
    db.update_video_status("vid_mid_fail", "FAILED", error_msg="Censorship reject")
    with db.get_connection() as conn:
        conn.execute("UPDATE processed_videos SET created_at = ? WHERE youtube_id = ?", (t_15d, "vid_mid_fail"))

    # 45 天前（仅落在 all 内）：1 条发布
    db.add_video("vid_old_pub", "Old Pub", cid, score=90)
    db.update_video_status("vid_old_pub", "PUBLISHED")
    with db.get_connection() as conn:
        conn.execute("UPDATE processed_videos SET created_at = ? WHERE youtube_id = ?", (t_45d, "vid_old_pub"))

    # ── 1. 验证 7 天窗口 ──────────────────────────────────────────
    m7 = db.get_channel_funnel_metrics(cid, days=7)
    assert m7["total_ingested"] == 2
    assert m7["qualified"] == 1
    assert m7["published"] == 1
    assert m7["failed"] == 0
    assert m7["censor_blocked"] == 0
    assert m7["qualification_rate"] == 50.0
    assert m7["publishing_rate"] == 100.0

    # ── 2. 验证 30 天窗口 ─────────────────────────────────────────
    m30 = db.get_channel_funnel_metrics(cid, days=30)
    assert m30["total_ingested"] == 3
    assert m30["qualified"] == 2
    assert m30["published"] == 1
    assert m30["failed"] == 1
    assert m30["censor_blocked"] == 1
    assert round(m30["qualification_rate"], 1) == 66.7
    assert m30["publishing_rate"] == 50.0

    # ── 3. 验证全量窗口 (days=None) ───────────────────────────────
    m_all = db.get_channel_funnel_metrics(cid, days=None)
    assert m_all["total_ingested"] == 4
    assert m_all["qualified"] == 3
    assert m_all["published"] == 2
    assert m_all["failed"] == 1
    assert m_all["censor_blocked"] == 1
    assert m_all["qualification_rate"] == 75.0
    assert round(m_all["publishing_rate"], 1) == 66.7


def test_get_global_funnel_metrics(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    # 录入来自不同频道的视频
    db.add_channel("UC_1", "Channel 1", status="APPROVED")
    db.add_channel("UC_2", "Channel 2", status="APPROVED")

    db.add_video("vid_1", "Vid 1", "UC_1", score=80)
    db.update_video_status("vid_1", "PUBLISHED")

    db.add_video("vid_2", "Vid 2", "UC_2", score=90)
    db.update_video_status("vid_2", "DOWNLOADING")

    db.add_video("vid_3", "Vid 3", "UC_2", score=30)

    # 全局漏斗
    global_m = db.get_global_funnel_metrics()
    assert global_m["total_ingested"] == 3
    assert global_m["qualified"] == 2
    assert global_m["processed"] == 2  # PUBLISHED + DOWNLOADING
    assert global_m["published"] == 1
    assert round(global_m["qualification_rate"], 1) == 66.7
    assert global_m["processing_rate"] == 100.0
    assert global_m["publishing_rate"] == 50.0

