"""入库批次流程概览 DAL 与运行态探针单元测试（隔离 SQLite 与临时目录）。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.2.0 | 2026-10-29 | Codex | 用SQLite实际400绑定参数上限覆盖双IN与关联查询，并验证缺表失败与来源透传。 |
| 1.1.0 | 2026-10-29 | Antigravity | 补充 ISO 带时区解析、微信规范授权路径、退避最大值保留与大批次分块防溢出测试。 |
| 1.0.0 | 2026-10-29 | Antigravity | 覆盖主任务族切片关联、多表事件汇聚、内核锁探测、心跳解析与端到端诊断集成。 |
"""
from __future__ import annotations

from datetime import datetime, timezone
from contextlib import contextmanager
import json
import os
import sqlite3
from pathlib import Path
import pytest

from video_processing.core.runtime_probe import (
    enrich_cohort_tasks_with_runtime,
    enrich_task_facts_with_runtime,
    is_pid_alive,
    probe_runtime_environment,
    read_caption_progress,
)
from video_processing.core.task_lease import TaskLease
from video_processing.db.database import PipelineDB
from video_processing.db.funnel_diagnosis import _parse_iso_or_epoch
from video_processing.funnel_diagnosis import (
    AnomalyCategory,
    diagnose_task_unit,
    evaluate_cohort_diagnosis,
)
from video_processing.funnel_diagnosis.models import TaskUnitFacts


@pytest.fixture
def test_db(tmp_path: Path) -> PipelineDB:
    """创建全新隔离的 SQLite 数据库并完成全表迁移。"""
    return PipelineDB(db_path=str(tmp_path / "test_pipeline.db"))


def test_empty_cohort_returns_empty_list(test_db: PipelineDB):
    """空数据库查询返回空列表。"""
    assert test_db.get_funnel_cohort_task_facts(window="all") == []


def _seed_family_filtering_data(db: PipelineDB, now_utc: str):
    """插入跨频道、父子任务及历史任务测试数据。"""
    with db.get_connection() as c:
        c.execute("INSERT INTO recommended_channels (channel_id, channel_name, status) VALUES (?, ?, ?)", ("UC_ALPHA", "Alpha Channel", "APPROVED"))
        c.execute("INSERT INTO recommended_channels (channel_id, channel_name, status) VALUES (?, ?, ?)", ("UC_BETA", "Beta Channel", "APPROVED"))
        c.execute(
            """INSERT INTO processed_videos (id, youtube_id, slice_index, parent_id, title, channel_id, status, score, created_at, updated_at)
               VALUES (1, 'vid_alpha', 0, NULL, 'Alpha Main', 'UC_ALPHA', 'SEGMENTED', 85, ?, ?)""",
            (now_utc, now_utc),
        )
        c.execute(
            """INSERT INTO processed_videos (id, youtube_id, slice_index, parent_id, title, channel_id, status, score, created_at, updated_at)
               VALUES (2, 'vid_alpha', 1, 1, 'Alpha Slice 1', 'UC_ALPHA', 'PUBLISHING', 85, ?, ?)""",
            (now_utc, now_utc),
        )
        c.execute(
            """INSERT INTO processed_videos (id, youtube_id, slice_index, parent_id, title, channel_id, status, score, created_at, updated_at)
               VALUES (3, 'vid_beta', 0, NULL, 'Beta Main', 'UC_BETA', 'PENDING', 60, ?, ?)""",
            (now_utc, now_utc),
        )
        c.execute(
            """INSERT INTO processed_videos (id, youtube_id, slice_index, parent_id, title, channel_id, status, score, created_at, updated_at)
               VALUES (4, 'vid_old', 0, NULL, 'Old Main', 'UC_ALPHA', 'PUBLISHED', 90, '2026-09-01 10:00:00', '2026-09-01 11:00:00')"""
        )


def test_cohort_task_family_and_channel_filtering(test_db: PipelineDB):
    """验证主任务与切片分集同族召回、频道过滤与窗口隔离。"""
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    _seed_family_filtering_data(test_db, now_utc)

    tasks_30d = test_db.get_funnel_cohort_task_facts(window="30d")
    ids_30d = [t.video_id for t in tasks_30d]
    assert {1, 2, 3}.issubset(set(ids_30d)) and 4 not in ids_30d

    tasks_alpha = test_db.get_funnel_cohort_task_facts(window="30d", channel_id="Alpha Channel")
    assert {t.video_id for t in tasks_alpha} == {1, 2}
    slice_task = next(t for t in tasks_alpha if t.video_id == 2)
    assert slice_task.parent_id == 1 and slice_task.channel_name == "Alpha Channel"

    family_facts = test_db.get_funnel_task_family_facts_by_ids([2])
    assert {t.video_id for t in family_facts} == {1, 2}


def _seed_associated_events_data(db: PipelineDB, now_utc: str):
    """填充全量关联子表数据（失败事件、恢复、字幕与发布记录）。"""
    with db.get_connection() as c:
        c.execute(
            """INSERT INTO processed_videos (id, youtube_id, slice_index, parent_id, title, channel_id, status, score, error_msg, created_at, updated_at, failed_at)
               VALUES (10, 'vid_err', 0, NULL, 'Error Video', 'UC_ERR', 'FAILED', 88, 'Burned caption failed', ?, ?, ?)""",
            (now_utc, now_utc, "2026-10-29 08:15:30.500"),
        )
        c.execute("INSERT INTO publishing_failure_events (id, video_id, status, reason, failed_at) VALUES (101, 10, 'FAILED', 'fail', '2026-10-29 08:15:30.500')")
        c.execute("INSERT INTO publishing_recovery_operations (id, created, updated, state, request) VALUES ('op-1', 1.0, 2.0, 'COMPLETED', '{}')")
        c.execute("INSERT INTO publishing_recovery_items (id, operation_id, video_id, position, state, reason, original, current_revision, updated) VALUES (201, 'op-1', 10, 1, 'SKIPPED', 'skip', '{}', 'r1', 1793231000.0)")
        c.execute(
            """INSERT INTO subtitle_recovery (id, video_id, input_sha256, contract_sha256, is_current, state, attempt_count, chain_started_at, expires_at, next_attempt_at, failure_fingerprint, category, code, last_receipt_path, last_receipt_sha, updated_at)
               VALUES (301, 10, 'in', 'ct', 1, 'NEEDS_REPAIR', 2, 1.0, 2.0, 3.0, 'fp1', 'TRANSLATION', 'budget_exceeded', 'p', 's', 1793230000.0)"""
        )
        c.execute("INSERT INTO delivery_recoveries (id, event_key, kind, state, payload_json, detail, failure_kind, expires_at, created_at, updated_at) VALUES ('dr-1', 'ev-1', 'WECHAT_UNKNOWN', 'WAITING', '{\"video_id\": 10}', 'd', 'f', '2026-10-30', ?, ?)", (now_utc, now_utc))
        c.execute("INSERT INTO publication_subjects (id, kind, video_id) VALUES ('video:10', 'VIDEO_ITEM', 10)")
        c.execute("INSERT INTO wechat_publications (id, video_id, subject_id, state, platform_post_id, updated_at) VALUES (401, 10, 'video:10', 'UNCERTAIN', 'post_123', ?)", (now_utc,))
        c.execute("INSERT INTO wechat_submission_attempts (attempt_id, video_id, subject_id, state, final_title, created_at) VALUES ('att-1', 10, 'video:10', 'SUBMITTED_UNBOUND', 'T', ?)", (now_utc,))
        c.execute("INSERT INTO wechat_upload_retries (evidence_path, video_id, attempt_number, next_attempt_at) VALUES ('/tmp/ev1', 10, 1, '2026-10-29 09:30:00')")
        c.execute("INSERT INTO wechat_upload_retries (evidence_path, video_id, attempt_number, next_attempt_at) VALUES ('/tmp/ev2', 10, 2, '2026-10-29 09:45:00')")


def test_cohort_associated_events_and_recoveries(test_db: PipelineDB):
    """验证失败事件、恢复项、字幕恢复、微信发布与提交尝试的全量汇聚。"""
    now_utc = "2026-10-29 08:00:00"
    _seed_associated_events_data(test_db, now_utc)

    tasks = test_db.get_funnel_cohort_task_facts(window="all")
    assert len(tasks) == 1
    t = tasks[0]
    assert t.video_id == 10
    assert any(e["id"] == 101 and e["failed_epoch"] is not None for e in t.failure_events)
    assert t.recovery_items[0]["op_state"] == "COMPLETED"
    assert t.subtitle_recovery is not None and t.subtitle_recovery["state"] == "NEEDS_REPAIR"
    assert len(t.delivery_recoveries) == 1 and t.delivery_recoveries[0]["kind"] == "WECHAT_UNKNOWN"
    assert t.wechat_publication is not None and t.wechat_publication["state"] == "UNCERTAIN"
    assert t.submission_attempts[0]["attempt_id"] == "att-1"
    # 保留最大退避到期时刻（09:45:00 胜出 09:30:00）
    assert t.upload_retry_next_epoch == _parse_iso_or_epoch("2026-10-29 09:45:00")


def test_runtime_probe_environment_and_locks(tmp_path: Path):
    """验证 runtime_probe 只读检查各类锁、心跳与退避状态。"""
    out_dir = tmp_path / "output"
    out_dir.mkdir(parents=True)
    now_epoch = 1793233200.0

    env_clean = probe_runtime_environment(output_dir=out_dir, now_epoch=now_epoch)
    assert not env_clean.pipeline_lock_held and not env_clean.wechat_login_valid

    with TaskLease(out_dir / "pipeline.lock", stage="测试管线"):
        with TaskLease(out_dir / "ready_publications.lock", stage="全天发布巡检"):
            with TaskLease(out_dir / "publishing_recovery_worker.lock", stage="恢复执行者"):
                with TaskLease(out_dir / ".wechat_state.json.browser.lock", stage="浏览器发帖"):
                    (out_dir / "ready_publications_status.json").write_text(json.dumps({"heartbeat_at": now_epoch - 12.5}))
                    (out_dir / ".wechat_state.json.requests.json").write_text(json.dumps({"blocked_until": now_epoch + 600.0}))
                    (out_dir / "wechat_state.json").write_text(json.dumps({"cookies": ["foo"]}))
                    (out_dir / "agy_cover_auth.json").write_text(json.dumps({"checked_at": now_epoch - 30.0, "status": "AUTH_REQUIRED"}))

                    env_active = probe_runtime_environment(output_dir=out_dir, now_epoch=now_epoch)
                    assert env_active.pipeline_lock_held and env_active.ready_supervisor_lock_held
                    assert env_active.recovery_worker_lock_held and env_active.wechat_browser_lock_held
                    assert env_active.ready_supervisor_heartbeat_age_sec == pytest.approx(12.5, abs=0.1)
                    assert env_active.wechat_cooldown_until_epoch == now_epoch + 600.0
                    assert env_active.wechat_login_valid and env_active.agy_cover_relogin_required

    assert not probe_runtime_environment(output_dir=out_dir, now_epoch=now_epoch).pipeline_lock_held


def test_runtime_probe_task_enrichment(tmp_path: Path):
    """验证 enrich_task_facts_with_runtime 准确补齐任务级内核锁、字幕进度与存活状态。"""
    out_dir = tmp_path / "output"
    (out_dir / "task_locks").mkdir(parents=True)
    base_facts = TaskUnitFacts(video_id=50, youtube_id="task_probe_vid", slice_index=2, process_pid=None)

    (out_dir / "task_probe_vid_s2_caption_progress.json").write_text(
        json.dumps({"stage": "TRANSLATING", "stage_started_at": 1793230000.0, "updated_at": 1793230100.0})
    )
    with TaskLease(out_dir / "task_locks" / "task_probe_vid_s2.lock", stage="分集加工"):
        enriched = enrich_task_facts_with_runtime(base_facts, output_dir=out_dir)
        assert enriched.has_active_task_lock and enriched.task_lock_owner.get("stage") == "分集加工"
        assert enriched.caption_stage == "TRANSLATING"
        assert enriched.process_alive  # 锁持有者 PID (当前测试进程) 存活

    released = enrich_task_facts_with_runtime(base_facts, output_dir=out_dir)
    assert not released.has_active_task_lock and not released.process_alive


def test_runtime_probe_never_throws_on_corrupted_files(tmp_path: Path):
    """坏文件保留读取错误，批量探针显式标未知，不伪装成空锁或有效进度。"""
    out_dir = tmp_path / "corrupt_output"
    out_dir.mkdir()
    (out_dir / "ready_publications_status.json").write_bytes(b"\x00\xff corrupt binary")
    (out_dir / ".wechat_state.json.requests.json").write_text("invalid json")
    (out_dir / "agy_cover_auth.json").write_text("[]")
    (out_dir / "prefix_caption_progress.json").write_text("{not a valid json")

    env = probe_runtime_environment(output_dir=out_dir, now_epoch=1793233200.0)
    assert env is not None and env.ready_supervisor_heartbeat_age_sec is None
    assert env.wechat_cooldown_until_epoch is None
    assert not env.runtime_available and env.runtime_unavailable_reasons
    with pytest.raises(json.JSONDecodeError):
        read_caption_progress(out_dir, "prefix")
    enriched = enrich_task_facts_with_runtime(
        TaskUnitFacts(video_id=1, youtube_id="prefix"), output_dir=out_dir,
    )
    assert not enriched.runtime_observation_available
    assert enriched.caption_stage is None
    assert not is_pid_alive(-999) and not is_pid_alive(None)


def test_dal_probe_rules_end_to_end_integration(test_db: PipelineDB, tmp_path: Path):
    """端到端全链路集成：DAL 查询事实 -> 运行态探针补齐 -> 规则诊断与批次叙事生成。"""
    out_dir = tmp_path / "e2e_output"
    out_dir.mkdir()
    now_epoch = 1793233200.0
    now_utc = "2026-10-29 08:20:00"

    with test_db.get_connection() as c:
        c.execute(
            """INSERT INTO processed_videos (id, youtube_id, slice_index, parent_id, title, channel_id, status, score, error_msg, created_at, updated_at, failed_at)
               VALUES (88, 'e2e_video', 0, NULL, 'End to End Video', 'UC_TEST', 'FAILED', 90,
                       '[NativeCaptionReview] 原字幕识别未完成：VISUAL_REVIEW_BUDGET_EXCEEDED', ?, ?, ?)""",
            (now_utc, now_utc, now_utc),
        )
        c.execute("INSERT INTO publishing_failure_events (video_id, status, reason, failed_at) VALUES (88, 'FAILED', 'VISUAL_REVIEW_BUDGET_EXCEEDED', ?)", (now_utc,))

    tasks = test_db.get_funnel_cohort_task_facts(window="all")
    assert len(tasks) == 1
    env = probe_runtime_environment(output_dir=out_dir, now_epoch=now_epoch)
    enriched = enrich_cohort_tasks_with_runtime(tasks, output_dir=out_dir)

    diag = diagnose_task_unit(enriched[0], env)
    assert diag and diag.cause_code == "NATIVE_CAPTION_VISUAL_BUDGET"
    assert diag.category == AnomalyCategory.EXECUTION_FAILURE.value and diag.unresolved is True

    res = evaluate_cohort_diagnosis(enriched, env)
    assert res["summary"]["unresolved_tasks"] == 1
    assert res["causes"][0].cause_code == "NATIVE_CAPTION_VISUAL_BUDGET"


def test_wechat_auth_canonical_and_superseded_states(tmp_path: Path):
    """验证微信授权状态的规范文件名（无前导点）、请求守卫手工登录标记与覆盖判定。"""
    out_dir = tmp_path / "wechat_auth_test"
    out_dir.mkdir()
    state_file = out_dir / "wechat_state.json"
    auth_file = out_dir / "wechat_state.json.auth_state.json"
    req_file = out_dir / ".wechat_state.json.requests.json"

    # 1. 凭据文件不存在 -> False
    assert not probe_runtime_environment(output_dir=out_dir).wechat_login_valid

    # 2. 规范 auth_state 文件标记 LOGIN_REQUIRED -> False
    state_file.write_text('{"token": "xyz"}')
    auth_file.write_text(json.dumps({"last_keepalive_status": "LOGIN_REQUIRED", "last_keepalive_at": 1000.0, "last_verified_at": None}))
    assert not probe_runtime_environment(output_dir=out_dir).wechat_login_valid

    # 3. 新验证覆盖 -> True
    auth_file.write_text(json.dumps({"last_keepalive_status": "LOGIN_REQUIRED", "last_keepalive_at": 1000.0, "last_verified_at": 2000.0}))
    assert probe_runtime_environment(output_dir=out_dir).wechat_login_valid

    # 4. requests.json 显式记录 requires_manual_login -> False
    req_file.write_text(json.dumps({"requires_manual_login": True}))
    assert not probe_runtime_environment(output_dir=out_dir).wechat_login_valid


def test_cohort_window_and_channel_edge_cases(test_db: PipelineDB):
    """验证 window 参数（24h/7d/all/days）与通道通配符（all/*）的边界处理。"""
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with test_db.get_connection() as c:
        c.execute(
            """INSERT INTO processed_videos (id, youtube_id, slice_index, parent_id, title, channel_id, status, score, created_at, updated_at)
               VALUES (99, 'edge_vid', 0, NULL, 'Edge Video', 'UC_EDGE', 'PENDING', 70, ?, ?)""",
            (now_utc, now_utc),
        )
    for ch in ("all", "*", "", None):
        assert any(t.video_id == 99 for t in test_db.get_funnel_cohort_task_facts(window="all", channel_id=ch))
    assert any(t.video_id == 99 for t in test_db.get_funnel_cohort_task_facts(days=1))
    assert any(t.video_id == 99 for t in test_db.get_funnel_cohort_task_facts(window="24h"))


def test_parse_iso_or_epoch_and_large_batch_chunking(test_db: PipelineDB, monkeypatch):
    """验证 UTC Z/+00:00 ISO 时间戳安全解析及超大批次分块防 SQLite 变量溢出。"""
    assert _parse_iso_or_epoch("2026-10-29T08:15:30Z") == 1793261730.0
    assert _parse_iso_or_epoch("2026-10-29T08:15:30+00:00") == 1793261730.0
    assert _parse_iso_or_epoch("2026-10-29 08:15:30.500") == 1793261730.5
    assert _parse_iso_or_epoch("") is None
    assert _parse_iso_or_epoch("invalid") is None

    # 构造 450 条任务批量反查主任务族（超过单块 400 边界，防变量上限）
    now_utc = "2026-10-29 08:00:00"
    with test_db.get_connection() as c:
        for i in range(100, 550):
            c.execute(
                "INSERT INTO processed_videos (id, youtube_id, slice_index, parent_id, title, channel_id, status, score, created_at, updated_at) "
                "VALUES (?, ?, 0, NULL, 'Chunk Video', 'UC_CHUNK', 'PENDING', 80, ?, ?)",
                (i, f"chunk_{i}", now_utc, now_utc),
            )
    query_ids = list(range(100, 550))
    original_connection = test_db.get_connection

    @contextmanager
    def limited_connection():
        with original_connection() as conn:
            # 限制实际SQLite连接；默认编译上限通常远高于400，无法发现双IN的800参数。
            conn.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 400)
            yield conn

    monkeypatch.setattr(test_db, "get_connection", limited_connection)
    facts = test_db.get_funnel_task_family_facts_by_ids(query_ids)
    assert {t.video_id for t in facts} == set(query_ids)
    cohort = test_db.get_funnel_cohort_task_facts(window="all")
    assert {t.video_id for t in cohort} == set(query_ids)


@pytest.mark.parametrize("table", [
    "processed_videos", "recommended_channels", "publishing_failure_events",
    "publishing_recovery_items", "publishing_recovery_operations", "subtitle_recovery",
    "delivery_recoveries", "wechat_publications", "wechat_submission_attempts",
    "wechat_upload_retries", "copywriter_deferred",
])
def test_missing_evidence_table_never_becomes_empty(test_db: PipelineDB, table: str):
    """主表和每类关联来源缺失都必须显式失败，不得伪装成正常或没有投递尝试。"""
    with test_db.get_connection() as conn:
        conn.execute("INSERT INTO processed_videos (id, youtube_id, title, channel_id, status) VALUES (1, 'schema_failure', 'Schema failure', 'UC_TEST', 'FAILED')")
        conn.execute(f'DROP TABLE "{table}"')
    with pytest.raises(sqlite3.OperationalError):
        test_db.get_funnel_cohort_task_facts(window="all")
    with pytest.raises(sqlite3.OperationalError):
        test_db.get_funnel_task_family_facts_by_ids([1])


def test_dal_preserves_discovery_source(test_db: PipelineDB):
    """browse-only DISCOVERY资格判断所需原始来源必须保留。"""
    with test_db.get_connection() as conn:
        conn.execute("INSERT INTO processed_videos (id, youtube_id, title, channel_id, status, score, source) VALUES (1, 'browse_only', 'Browse only', 'UC_TEST', 'PENDING', 99, 'DISCOVERY')")
    assert test_db.get_funnel_cohort_task_facts(window="all")[0].source == "DISCOVERY"
