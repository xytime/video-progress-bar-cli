"""TDD test cases for database slices and parent-child task cascade actions.

# Modification History
| Version | Date       | Author                    | Description                                     |
|---------|------------|---------------------------|-------------------------------------------------|
| 2.1.0 | 2026-08-23 | Codex | 覆盖源视频精确发布时间的插入与非空补齐 |
| 2.0.0   | 2026-08-21 | Codex                    | 覆盖评分输入缓存与历史微信墓碑不计入待恢复队列 |
| 1.2.0   | 2026-05-27 | Unknown_Model_planning    | 新增测试：验证 purge_stale_tasks, batch_add_videos 补齐 disable_slicing 以及 delete_slices_by_parent_id |
| 1.3.0   | 2026-07-13 | Codex                    | 覆盖 AI 字幕审计运行、provider 尝试与汇总查询 |
| 1.4.0   | 2026-07-29 | Codex                    | 覆盖发布后日指标、内容身份、视频关系和 AB 实验汇总 |
| 1.5.0   | 2026-08-05 | Codex                    | 覆盖源标题译文的定点更新 DAL |
| 1.9.0   | 2026-08-21 | Codex                    | 覆盖视频号待恢复队列不混入实际处理中的仪表盘语义 |
| 1.8.0   | 2026-08-21 | Codex                    | 锁定每个 DAL 连接启用 SQLite 外键约束 |
| 1.6.0   | 2026-08-14 | Codex                    | 覆盖平台待确认任务与实际加工队列的 Tab 分离 |
| 1.7.0   | 2026-08-18 | Codex                    | 覆盖 DAL 连接上下文退出后关闭 SQLite 文件描述符 |
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


def test_connection_context_closes_sqlite_handle(temp_db):
    """DAL 的连接上下文必须释放句柄，不能只提交事务。"""
    db = PipelineDB(temp_db)

    with db.get_connection() as conn:
        assert conn.execute("SELECT 1").fetchone()[0] == 1

    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        conn.execute("SELECT 1")


def test_connection_context_enables_foreign_keys(temp_db):
    """SQLite 外键必须在每个 DAL 连接中启用，不能只依赖初始化连接。"""
    db = PipelineDB(temp_db)

    with db.get_connection() as conn:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_monitored_video_retains_precise_source_publish_time(temp_db):
    db = PipelineDB(temp_db)
    assert db.upsert_monitored_video(
        "precise-published-at", "Title", "channel", zh_title=None, duration_sec=60,
        view_count=100, like_count=3, upload_date="20260823", metadata_complete=True,
        source_published_at="2026-08-23T01:02:03Z",
    ) == "inserted"
    assert db.upsert_monitored_video(
        "precise-published-at", "Title", "channel", zh_title=None, duration_sec=60,
        view_count=100, like_count=3, upload_date="20260823", metadata_complete=True,
        source_published_at=None,
    ) == "refreshed"

    assert db.get_video_by_youtube_id("precise-published-at")["source_published_at"] == "2026-08-23T01:02:03Z"


def test_orphaned_pre_submission_recovery_is_bounded(temp_db):
    db = PipelineDB(temp_db)
    assert db.add_video("orphan-bounded", "title", "channel", score=80)
    db.update_video_status("orphan-bounded", "DOWNLOADING")

    assert db.recover_orphaned_pre_submission_task(
        "orphan-bounded", expected_process_pid=None, error_msg="worker gone", max_retry_count=1,
    ) == "PENDING"
    db.update_video_status("orphan-bounded", "DOWNLOADING")
    assert db.recover_orphaned_pre_submission_task(
        "orphan-bounded", expected_process_pid=None, error_msg="worker gone again", max_retry_count=1,
    ) == "FAILED"

    row = db.get_video_by_youtube_id("orphan-bounded")
    assert row["status"] == "FAILED"
    assert row["retry_count"] == 1

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


def test_update_video_zh_title_does_not_change_status(temp_db):
    db = PipelineDB(temp_db)
    assert db.add_video("translated-title", "English source", "channel", score=80)
    db.update_video_status("translated-title", "COPYWRITING")

    assert db.update_video_zh_title("translated-title", "中文源标题")
    row = db.get_video_by_youtube_id("translated-title")

    assert row["zh_title"] == "中文源标题"
    assert row["status"] == "COPYWRITING"


def test_under_review_is_separate_from_processing_tab(temp_db):
    """平台待确认不能被显示为仍在下载、转写或上传。"""
    db = PipelineDB(temp_db)
    assert db.add_video("review-video", "Review", "channel", score=80)
    assert db.add_video("processing-video", "Processing", "channel", score=80)
    assert db.add_video("deferred-video", "Deferred", "channel", score=80)
    db.update_video_status("review-video", "UNDER_REVIEW")
    db.update_video_status("processing-video", "PUBLISHING")
    db.update_video_status("deferred-video", "WECHAT_DEFERRED")

    active, active_total = db.get_paginated_videos(tab="active")
    deferred, deferred_total = db.get_paginated_videos(tab="wechat_deferred")
    review, review_total = db.get_paginated_videos(tab="review")
    counts = db.get_tab_counts()

    assert active_total == counts["active"] == 1
    assert {video["youtube_id"] for video in active} == {"processing-video"}
    assert deferred_total == counts["wechat_deferred"] == 1
    assert {video["youtube_id"] for video in deferred} == {"deferred-video"}
    assert review_total == counts["review"] == 1
    assert {video["youtube_id"] for video in review} == {"review-video"}


def test_score_cache_only_refreshes_changed_inputs_or_expired_ttl(temp_db):
    db = PipelineDB(temp_db)
    assert db.add_video("score-cache", "Title", "channel", view_count=100, like_count=2)

    assert [row["youtube_id"] for row in db.get_pending_videos_requiring_score_refresh(180)] == ["score-cache"]
    db.update_video_score("score-cache", 10)
    assert db.get_pending_videos_requiring_score_refresh(180) == []

    assert db.upsert_monitored_video(
        "score-cache", "Title", "channel", zh_title=None, duration_sec=60,
        view_count=200, like_count=6, upload_date="20260821", metadata_complete=True,
    ) == "refreshed"
    assert [row["youtube_id"] for row in db.get_pending_videos_requiring_score_refresh(180)] == ["score-cache"]
    db.update_video_score("score-cache", 20)
    assert [row["youtube_id"] for row in db.get_pending_videos_requiring_score_refresh(0)] == ["score-cache"]


def test_historical_wechat_tombstone_is_not_displayed_as_deferred_recovery(temp_db):
    db = PipelineDB(temp_db)
    assert db.add_video("archived-deferred", "Title", "channel", score=80)
    db.record_wechat_publication_confirmation(
        "archived-deferred", evidence_path="evidence.png", state="SUBMITTED_UNBOUND",
    )
    assert db.archive_wechat_publication_as_historical_unresolved(
        "archived-deferred", reason="test archive",
    )
    db.update_video_status("archived-deferred", "WECHAT_DEFERRED")

    rows, total = db.get_paginated_videos(tab="wechat_deferred")
    assert total == 0
    assert rows == []
    assert db.get_tab_counts()["wechat_deferred"] == 0

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


def test_ai_processing_audit_records_timeline_and_summary(temp_db):
    db = PipelineDB(temp_db)
    run_id = db.start_ai_processing_run("audit_video")
    db.record_ai_provider_attempt(
        run_id,
        provider="gemini",
        model="gemini-2.5-flash",
        capabilities="translate,vocab",
        attempt_order=1,
        status="FAILED",
        duration_ms=120,
        error_class="rate_limit",
        error_message="429 quota",
    )
    db.record_ai_provider_attempt(
        run_id,
        provider="deepseek",
        model="deepseek-v4-flash",
        capabilities="translate,vocab",
        attempt_order=2,
        status="SUCCEEDED",
        duration_ms=240,
        quality_score=100.0,
        selected=True,
    )
    db.finish_ai_processing_run(
        run_id,
        status="SUCCEEDED",
        final_provider="DeepSeek",
        fallback_used=True,
        quality_score=100.0,
        chinese_coverage=1.0,
        vocabulary_segments=3,
        quality_status="passed",
    )

    runs = db.get_ai_audit_for_video("audit_video")
    assert len(runs) == 1
    assert runs[0]["final_provider"] == "DeepSeek"
    assert [item["provider"] for item in runs[0]["attempts"]] == ["gemini", "deepseek"]
    assert runs[0]["attempts"][1]["selected"] == 1

    summary = db.get_ai_audit_summary(hours=1)
    assert summary["runs"]["total_runs"] == 1
    assert summary["runs"]["fallback_runs"] == 1
    assert {item["provider"] for item in summary["providers"]} == {"gemini", "deepseek"}


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


def test_published_video_daily_metrics_are_idempotent_and_summarized(temp_db):
    db = PipelineDB(temp_db)
    db.add_video("metric-video", "Metric title", "channel_1", score=80)
    db.update_video_status("metric-video", "PUBLISHED")

    first = db.record_published_video_daily_metrics(
        "metric-video",
        platform="wechat",
        metric_date="2026-07-28",
        click_count=10,
        view_count=100,
        like_count=8,
        share_count=2,
        comment_count=1,
        source="manual_export",
        raw={"row": 1},
    )
    second = db.record_published_video_daily_metrics(
        "metric-video",
        platform="wechat",
        metric_date="2026-07-28",
        click_count=12,
        view_count=130,
        like_count=9,
        share_count=3,
        comment_count=2,
        source="manual_export",
        raw={"row": 2},
    )
    db.record_published_video_daily_metrics(
        "metric-video",
        platform="douyin",
        metric_date="2026-07-29",
        click_count=4,
        view_count=50,
        like_count=5,
        share_count=1,
        comment_count=0,
    )

    assert first["id"] == second["id"]
    assert second["click_count"] == 12

    rows = db.get_daily_metrics_for_video("metric-video")
    assert [(row["platform"], row["metric_date"]) for row in rows] == [
        ("wechat", "2026-07-28"),
        ("douyin", "2026-07-29"),
    ]

    summary = db.get_published_video_metric_summary("metric-video")
    assert summary["total"]["metric_days"] == 2
    assert summary["total"]["click_count"] == 16
    assert summary["total"]["view_count"] == 180
    assert {row["platform"]: row["like_count"] for row in summary["by_platform"]} == {
        "douyin": 5,
        "wechat": 9,
    }


def test_content_identity_and_video_relationships_support_variant_lineage(temp_db):
    db = PipelineDB(temp_db)
    db.add_video("source-video", "Original title", "channel_1", score=80, duration_sec=90)
    db.add_video("variant-video", "Variant title", "channel_1", score=80, duration_sec=90)

    source_identity = db.assign_video_content_identity(
        "source-video",
        content_key="content:market-brief-001",
        source_kind="TRANSCRIPT",
        fingerprint_hash="f" * 64,
        normalized_title="market brief 001",
        relationship_to_content="ORIGINAL",
    )
    variant_identity = db.assign_video_content_identity(
        "variant-video",
        content_key="content:market-brief-001",
        source_kind="TRANSCRIPT",
        relationship_to_content="VARIANT",
        variant_key="B",
    )
    relation = db.record_video_relationship(
        "source-video",
        "variant-video",
        relation_type="AB_VARIANT_OF",
        notes="标题 AB 测试",
    )

    assert source_identity["id"] == variant_identity["id"]
    assert variant_identity["variant_key"] == "B"
    assert relation["relation_type"] == "AB_VARIANT_OF"
    assert db.get_video_content_identity("variant-video")["content_key"] == "content:market-brief-001"
    assert db.get_related_videos("source-video", direction="parent")[0]["child_youtube_id"] == "variant-video"


def test_ab_experiment_summary_rolls_up_variant_metrics(temp_db):
    db = PipelineDB(temp_db)
    db.add_video("variant-a", "A title", "channel_1", score=80)
    db.add_video("variant-b", "B title", "channel_1", score=80)
    db.assign_video_content_identity(
        "variant-a",
        content_key="content:ab-foundation",
        relationship_to_content="ORIGINAL",
        variant_key="A",
    )
    db.assign_video_content_identity(
        "variant-b",
        content_key="content:ab-foundation",
        relationship_to_content="VARIANT",
        variant_key="B",
    )
    experiment = db.create_ab_experiment(
        "cover-title-test",
        content_key="content:ab-foundation",
        hypothesis="短标题提升点击",
        primary_metric="click_count",
        state="RUNNING",
    )
    db.add_ab_experiment_variant(experiment["id"], "variant-a", variant_key="A", variant_label="长标题")
    db.add_ab_experiment_variant(experiment["id"], "variant-b", variant_key="B", variant_label="短标题")

    db.record_published_video_daily_metrics(
        "variant-a",
        platform="wechat",
        metric_date="2026-07-28",
        click_count=10,
        view_count=100,
        like_count=6,
    )
    db.record_published_video_daily_metrics(
        "variant-b",
        platform="wechat",
        metric_date="2026-07-28",
        click_count=18,
        view_count=110,
        like_count=7,
    )

    summary = db.get_ab_experiment_summary(experiment["id"], platform="wechat")
    by_variant = {row["variant_key"]: row for row in summary["variants"]}

    assert summary["experiment"]["content_key"] == "content:ab-foundation"
    assert by_variant["A"]["click_count"] == 10
    assert by_variant["B"]["click_count"] == 18
    assert by_variant["B"]["youtube_id"] == "variant-b"
