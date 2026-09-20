"""数据库层频道管理（暂停/恢复）与生产转化漏斗测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-09-20 | Gemini | 补充大盘漏斗各阶段（ingested/qualified/processed/published/failed/blocked）下钻透视单元测试。 |
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


def test_funnel_metrics_24h_and_today_bj_windows(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    cid = "UC_HOURLY"
    db.add_channel(cid, "Hourly Test", status="APPROVED")

    now = datetime.utcnow()
    t_2h = (now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    t_36h = (now - timedelta(hours=36)).strftime("%Y-%m-%d %H:%M:%S")

    # 2小时前录入并发布
    db.add_video("vid_2h", "2h Ago", cid, score=85)
    db.update_video_status("vid_2h", "PUBLISHED")
    with db.get_connection() as conn:
        conn.execute("UPDATE processed_videos SET created_at = ? WHERE youtube_id = ?", (t_2h, "vid_2h"))

    # 36小时前录入
    db.add_video("vid_36h", "36h Ago", cid, score=85)
    with db.get_connection() as conn:
        conn.execute("UPDATE processed_videos SET created_at = ? WHERE youtube_id = ?", (t_36h, "vid_36h"))

    # 24h 窗口
    m24 = db.get_channel_funnel_metrics(cid, window="24h")
    assert m24["total_ingested"] == 1
    assert m24["qualified"] == 1
    assert m24["published"] == 1

    # all 窗口
    m_all = db.get_channel_funnel_metrics(cid, window="all")
    assert m_all["total_ingested"] == 2


def test_get_paginated_videos_created_window_filter(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    cid = "UC_FILTER"
    db.add_channel(cid, "Filter Test", status="APPROVED")

    now = datetime.utcnow()
    t_1h = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    t_3d = (now - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    t_10d = (now - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")

    db.add_video("vid_1h", "1h ago", cid, score=80)
    db.update_video_status("vid_1h", "FAILED", error_msg="Channel Policy blocked")
    with db.get_connection() as conn:
        conn.execute("UPDATE processed_videos SET created_at = ? WHERE youtube_id = ?", (t_1h, "vid_1h"))

    db.add_video("vid_3d", "3d ago", cid, score=80)
    db.update_video_status("vid_3d", "FAILED", error_msg="Channel Policy blocked")
    with db.get_connection() as conn:
        conn.execute("UPDATE processed_videos SET created_at = ? WHERE youtube_id = ?", (t_3d, "vid_3d"))

    db.add_video("vid_10d", "10d ago", cid, score=80)
    db.update_video_status("vid_10d", "FAILED", error_msg="Channel Policy blocked")
    with db.get_connection() as conn:
        conn.execute("UPDATE processed_videos SET created_at = ? WHERE youtube_id = ?", (t_10d, "vid_10d"))

    # 1. 24h 过滤
    videos_24h, count_24h = db.get_paginated_videos(tab="error", page=1, size=20, created_window="24h")
    assert count_24h == 1
    assert videos_24h[0]["youtube_id"] == "vid_1h"

    # 2. 7d 过滤
    videos_7d, count_7d = db.get_paginated_videos(tab="error", page=1, size=20, created_window="7d")
    assert count_7d == 2
    yids_7d = {v["youtube_id"] for v in videos_7d}
    assert yids_7d == {"vid_1h", "vid_3d"}

    # 3. all (默认)
    videos_all, count_all = db.get_paginated_videos(tab="error", page=1, size=20, created_window="all")
    assert count_all == 3


def test_get_paginated_videos_funnel_stage(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    cid = "UC_STAGE"
    db.add_channel(cid, "Stage Test", status="APPROVED")

    # 1. 采集但未达标: score=40, PENDING
    db.add_video("vid_low", "Low Score", cid, score=40)

    # 2. 达标排队中: score=80, PENDING
    db.add_video("vid_qual", "Qualified Pending", cid, score=80)

    # 3. 处理中 (DOWNLOADING): score=82
    db.add_video("vid_proc", "Processing", cid, score=82)
    db.update_video_status("vid_proc", "DOWNLOADING")

    # 4. 发布成功 (PUBLISHED): score=90
    db.add_video("vid_pub", "Published", cid, score=90)
    db.update_video_status("vid_pub", "PUBLISHED")

    # 5. 微信已受理 (SUBMITTED_BOUND): score=88
    db.add_video("vid_sub", "Submitted Bound", cid, score=88)
    db.update_video_status("vid_sub", "SUBMITTED_BOUND")

    # 6. 普通失败 (FAILED): score=76
    db.add_video("vid_fail", "Failed Normal", cid, score=76)
    db.update_video_status("vid_fail", "FAILED", error_msg="Network timeout")

    # 7. 策略拦截 (FAILED + censor_tag): score=85
    db.add_video("vid_censor", "Censor Blocked", cid, score=85, censor_tag="🔴 涉及政治敏感人物")
    db.update_video_status("vid_censor", "FAILED", error_msg="Censorship blocked")

    # 8. 切片子视频 (parent_id 不为空，不应进入顶层统计)
    parent_vid = db.get_video_by_youtube_id("vid_pub")
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO processed_videos (youtube_id, title, channel_id, status, score, parent_id) "
            "VALUES ('vid_slice', 'Slice Child', 'UC_STAGE', 'PUBLISHED', 90, ?)",
            (parent_vid["id"],)
        )

    # 对比全局漏斗大盘
    global_m = db.get_global_funnel_metrics(window="all")
    assert global_m["total_ingested"] == 7
    assert global_m["qualified"] == 6
    assert global_m["processed"] == 3  # DOWNLOADING + PUBLISHED + SUBMITTED_BOUND
    assert global_m["published"] == 2  # PUBLISHED + SUBMITTED_BOUND
    assert global_m["failed"] == 2     # vid_fail + vid_censor
    assert global_m["censor_blocked"] == 1  # vid_censor

    # 验证各阶段下钻查询与大盘数字 100% 绝对一致
    # 阶段 1: ingested
    v_ingested, c_ingested = db.get_paginated_videos(funnel_stage="ingested")
    assert c_ingested == global_m["total_ingested"] == 7
    assert "vid_slice" not in {v["youtube_id"] for v in v_ingested}

    # 阶段 2: qualified
    v_qual, c_qual = db.get_paginated_videos(funnel_stage="qualified")
    assert c_qual == global_m["qualified"] == 6
    assert "vid_low" not in {v["youtube_id"] for v in v_qual}

    # 阶段 3: processed
    v_proc, c_proc = db.get_paginated_videos(funnel_stage="processed")
    assert c_proc == global_m["processed"] == 3
    assert {v["youtube_id"] for v in v_proc} == {"vid_proc", "vid_pub", "vid_sub"}

    # 阶段 4: published
    v_pub, c_pub = db.get_paginated_videos(funnel_stage="published")
    assert c_pub == global_m["published"] == 2
    assert {v["youtube_id"] for v in v_pub} == {"vid_pub", "vid_sub"}

    # 阶段 5: failed
    v_failed, c_failed = db.get_paginated_videos(funnel_stage="failed")
    assert c_failed == global_m["failed"] == 2
    assert {v["youtube_id"] for v in v_failed} == {"vid_fail", "vid_censor"}

    # 阶段 6: blocked
    v_blocked, c_blocked = db.get_paginated_videos(funnel_stage="blocked")
    assert c_blocked == global_m["censor_blocked"] == 1
    assert {v["youtube_id"] for v in v_blocked} == {"vid_censor"}

    # 非法阶段入参防御校验
    with pytest.raises(ValueError, match="Unknown funnel stage"):
        db.get_paginated_videos(funnel_stage="invalid_stage_xyz")


