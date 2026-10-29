"""入库批次流程概览与异常诊断 Web API 与服务门面单元测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.2.0 | 2026-10-29 | Codex | 覆盖不可用503与真实空集的区分、GET无写入、阈值注入及平台受理未公开确认边界。 |
| 1.1.0 | 2026-10-29 | Antigravity | 补充 target 错配防御断言、空白参数规整、正常任务回执证据与 DAL 异常鲁棒性测试。 |
| 1.0.0 | 2026-10-29 | Antigravity | 覆盖 /api/funnel 频道筛选、/api/funnel/diagnosis 三层诊断与 tasks/{video_id}/evidence 证据链 API。 |
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from video_processing.db.database import PipelineDB
from video_processing.funnel_diagnosis.service import (
    DiagnosisUnavailable,
    _diagnosis_thresholds,
    get_funnel_diagnosis_payload,
    get_funnel_task_evidence_payload,
)
from web import app as web_app


@pytest.fixture
def test_db(tmp_path: Path) -> PipelineDB:
    """创建全新隔离的 SQLite 数据库。"""
    return PipelineDB(db_path=str(tmp_path / "test_pipeline.db"))


@pytest.fixture
def mock_app_context(test_db: PipelineDB, tmp_path: Path):
    """隔离 app 中的 db 与 _OUT_DIR 依赖。"""
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    with patch.object(web_app, "db", test_db), patch.object(web_app, "_OUT_DIR", out_dir):
        yield TestClient(web_app.app), out_dir


def test_api_funnel_backward_compatibility(mock_app_context, test_db: PipelineDB):
    """验证 GET /api/funnel 全局调用保持向下兼容。"""
    client, _ = mock_app_context
    test_db.add_channel("UC_1", "Channel 1", status="APPROVED")
    test_db.add_video("vid_1", "Video 1", "UC_1", score=80)
    test_db.update_video_status("vid_1", "PUBLISHED")

    res = client.get("/api/funnel?window=all")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["window"] == "all"
    assert data["metrics"]["total_ingested"] == 1
    assert data["metrics"]["published"] == 1


def test_api_funnel_with_channel_filtering(mock_app_context, test_db: PipelineDB):
    """验证 GET /api/funnel 增加 channel 参数后的过滤与通配符行为。"""
    client, _ = mock_app_context
    test_db.add_channel("UC_A", "Alpha Channel", status="APPROVED")
    test_db.add_channel("UC_B", "Beta Channel", status="APPROVED")
    test_db.add_video("vid_a", "Video A", "UC_A", score=90)
    test_db.update_video_status("vid_a", "PUBLISHED")
    test_db.add_video("vid_b", "Video B", "UC_B", score=40)

    # 1. 明确按 UC_A 筛选
    res_a = client.get("/api/funnel?window=all&channel=UC_A")
    assert res_a.status_code == 200
    data_a = res_a.json()
    assert data_a["channel_id"] == "UC_A"
    assert data_a["channel_name"] == "Alpha Channel"
    assert data_a["metrics"]["total_ingested"] == 1
    assert data_a["metrics"]["published"] == 1

    # 2. 明确按 UC_B 筛选
    res_b = client.get("/api/funnel?window=all&channel=UC_B")
    assert res_b.status_code == 200
    data_b = res_b.json()
    assert data_b["metrics"]["total_ingested"] == 1
    assert data_b["metrics"]["published"] == 0

    # 3. 通配符 channel=all 退回全局指标
    res_all = client.get("/api/funnel?window=all&channel=all")
    assert res_all.status_code == 200
    assert "channel_id" not in res_all.json()
    assert res_all.json()["metrics"]["total_ingested"] == 2


def test_api_funnel_diagnosis_empty(mock_app_context):
    """空数据批次下 GET /api/funnel/diagnosis 返回空摘要与确定性叙事句。"""
    client, _ = mock_app_context
    res = client.get("/api/funnel/diagnosis?window=today_bj")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["window"] == "today_bj"
    assert data["summary"]["total_ingested"] == 0
    assert data["summary"]["unresolved_tasks"] == 0
    assert data["causes"] == []
    assert data["tasks"] == []
    assert data["summary"]["diagnosis_sentence"] == "当前筛选批次内暂无入库任务。"


def _seed_diagnosis_test_tasks(db: PipelineDB, now_utc: str):
    """写入测试用多状态任务族数据。"""
    with db.get_connection() as c:
        c.execute("INSERT INTO recommended_channels (channel_id, channel_name, status) VALUES ('UC_DIAG', 'Diag Ch', 'APPROVED')")
        # 1. 执行失败任务
        c.execute(
            """INSERT INTO processed_videos (id, youtube_id, slice_index, parent_id, title, channel_id, status, score, error_msg, created_at, updated_at)
               VALUES (1, 'fail_vid', 0, NULL, 'Failed Task', 'UC_DIAG', 'FAILED', 85, 'VISUAL_REVIEW_BUDGET_EXCEEDED', ?, ?)""",
            (now_utc, now_utc),
        )
        c.execute(
            "INSERT INTO publishing_failure_events (video_id, status, reason, failed_at) VALUES (1, 'FAILED', '预算耗尽', ?)",
            (now_utc,),
        )
        # 2. 正常发布成功任务
        c.execute(
            """INSERT INTO processed_videos (id, youtube_id, slice_index, parent_id, title, channel_id, status, score, created_at, updated_at)
               VALUES (2, 'pub_vid', 0, NULL, 'Published Task', 'UC_DIAG', 'PUBLISHED', 90, ?, ?)""",
            (now_utc, now_utc),
        )
        c.execute("INSERT INTO publication_subjects (id, kind, video_id) VALUES ('video:2', 'VIDEO_ITEM', 2)")
        c.execute(
            "INSERT INTO wechat_publications (video_id, subject_id, state, platform_post_id) VALUES (2, 'video:2', 'PUBLISHED', 'export/pub123')"
        )


def test_api_funnel_diagnosis_with_tasks(mock_app_context, test_db: PipelineDB):
    """GET /api/funnel/diagnosis 聚合原因与任务明细。"""
    client, _ = mock_app_context
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    _seed_diagnosis_test_tasks(test_db, now_utc)

    res = client.get("/api/funnel/diagnosis?window=all")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    summary = data["summary"]
    assert summary["total_ingested"] == 2
    # export/ ID 只能证明平台已绑定，不能证明独立公开回读。
    assert summary["public_confirmed"] == 0
    assert summary["unresolved_tasks"] == 1
    assert len(data["causes"]) == 1
    assert data["causes"][0]["cause_code"] == "NATIVE_CAPTION_VISUAL_BUDGET"
    assert len(data["tasks"]) == 1
    assert data["tasks"][0]["video_id"] == 1
    assert len(data["tasks"][0]["facts"]) >= 1


def test_api_task_evidence_not_found(mock_app_context):
    """GET /api/funnel/tasks/{video_id}/evidence 对不存在任务返回 404。"""
    client, _ = mock_app_context
    res = client.get("/api/funnel/tasks/999999/evidence")
    assert res.status_code == 404
    assert res.json()["detail"] == "Task not found"


def test_api_task_evidence_anomalous_task(mock_app_context, test_db: PipelineDB):
    """GET /api/funnel/tasks/{video_id}/evidence 返回包含三元组事实证据的异常详情。"""
    client, _ = mock_app_context
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    _seed_diagnosis_test_tasks(test_db, now_utc)

    res = client.get("/api/funnel/tasks/1/evidence")
    assert res.status_code == 200
    payload = res.json()["data"]
    assert payload["video_id"] == 1
    assert payload["is_anomalous"] is True
    assert payload["diagnosis"]["cause_code"] == "NATIVE_CAPTION_VISUAL_BUDGET"
    assert len(payload["evidence"]["facts"]) >= 1
    assert len(payload["evidence"]["inferences"]) == 1
    assert len(payload["evidence"]["recommendations"]) == 1
    assert "runtime" in payload


def test_api_task_evidence_normal_task(mock_app_context, test_db: PipelineDB):
    """GET /api/funnel/tasks/{video_id}/evidence 返回无异常任务的正常证据链。"""
    client, _ = mock_app_context
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    _seed_diagnosis_test_tasks(test_db, now_utc)

    res = client.get("/api/funnel/tasks/2/evidence")
    assert res.status_code == 200
    payload = res.json()["data"]
    assert payload["video_id"] == 2
    assert payload["is_anomalous"] is False
    assert payload["diagnosis"] is None
    assert "未触发现有异常规则" in payload["evidence"]["facts"][1]
    assert payload["delivery_state"] == "PLATFORM_ACCEPTED"


def test_service_facade_direct_edge_cases(tmp_path: Path, test_db: PipelineDB):
    """数据库缺失不能成功假0；真实空集仍允许窗口规整后成功返回。"""
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    for unavailable_db in (None, object()):
        with pytest.raises(DiagnosisUnavailable):
            get_funnel_diagnosis_payload(unavailable_db, out_dir=out_dir)
        with pytest.raises(DiagnosisUnavailable):
            get_funnel_task_evidence_payload(unavailable_db, out_dir=out_dir, video_id=123)
    result = get_funnel_diagnosis_payload(test_db, out_dir=out_dir, window="invalid_win")
    assert result["success"] is True and result["window"] == "today_bj"
    assert result["summary"]["total_ingested"] == 0


def test_api_task_evidence_sliced_subtask(mock_app_context, test_db: PipelineDB):
    """GET /api/funnel/tasks/{video_id}/evidence 能正确定位切片分集任务。"""
    client, _ = mock_app_context
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with test_db.get_connection() as c:
        c.execute("INSERT INTO recommended_channels (channel_id, channel_name, status) VALUES ('UC_SLICE', 'Slice Ch', 'APPROVED')")
        c.execute(
            """INSERT INTO processed_videos (id, youtube_id, slice_index, parent_id, title, channel_id, status, score, created_at, updated_at)
               VALUES (10, 'vid_parent', 0, NULL, 'Parent Video', 'UC_SLICE', 'SEGMENTED', 85, ?, ?)""",
            (now_utc, now_utc),
        )
        c.execute(
            """INSERT INTO processed_videos (id, youtube_id, slice_index, parent_id, title, channel_id, status, score, error_msg, created_at, updated_at)
               VALUES (11, 'vid_parent', 1, 10, 'Slice Part 1', 'UC_SLICE', 'FAILED', 85, 'VISUAL_REVIEW_BUDGET_EXCEEDED', ?, ?)""",
            (now_utc, now_utc),
        )

    res = client.get("/api/funnel/tasks/11/evidence")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["video_id"] == 11
    assert data["slice_index"] == 1
    assert data["is_anomalous"] is True
    assert data["diagnosis"]["cause_code"] == "NATIVE_CAPTION_VISUAL_BUDGET"


def test_api_funnel_diagnosis_channel_filtering(mock_app_context, test_db: PipelineDB):
    """GET /api/funnel/diagnosis 支持指定 channel 参数筛选。"""
    client, _ = mock_app_context
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with test_db.get_connection() as c:
        c.execute("INSERT INTO recommended_channels (channel_id, channel_name, status) VALUES ('UC_X', 'Channel X', 'APPROVED')")
        c.execute("INSERT INTO recommended_channels (channel_id, channel_name, status) VALUES ('UC_Y', 'Channel Y', 'APPROVED')")
        c.execute(
            """INSERT INTO processed_videos (id, youtube_id, slice_index, parent_id, title, channel_id, status, score, error_msg, created_at, updated_at)
               VALUES (20, 'vid_x', 0, NULL, 'Task X', 'UC_X', 'FAILED', 80, 'VISUAL_REVIEW_BUDGET_EXCEEDED', ?, ?)""",
            (now_utc, now_utc),
        )
        c.execute(
            """INSERT INTO processed_videos (id, youtube_id, slice_index, parent_id, title, channel_id, status, score, error_msg, created_at, updated_at)
               VALUES (21, 'vid_y', 0, NULL, 'Task Y', 'UC_Y', 'FAILED', 80, 'OCR_INVALID_ROW', ?, ?)""",
            (now_utc, now_utc),
        )

    # 1. 仅查 UC_X
    res_x = client.get("/api/funnel/diagnosis?window=all&channel=UC_X")
    assert res_x.status_code == 200
    data_x = res_x.json()
    assert data_x["channel_id"] == "UC_X"
    assert data_x["channel_name"] == "Channel X"
    assert data_x["summary"]["total_ingested"] == 1
    assert len(data_x["causes"]) == 1
    assert data_x["causes"][0]["cause_code"] == "NATIVE_CAPTION_VISUAL_BUDGET"

    # 2. 仅查 UC_Y
    res_y = client.get("/api/funnel/diagnosis?window=all&channel=UC_Y")
    assert res_y.status_code == 200
    data_y = res_y.json()
    assert data_y["channel_id"] == "UC_Y"
    assert data_y["channel_name"] == "Channel Y"
    assert data_y["summary"]["total_ingested"] == 1
    assert len(data_y["causes"]) == 1
    assert data_y["causes"][0]["cause_code"] == "NATIVE_CAPTION_OCR_INVALID"


def test_api_funnel_whitespace_and_invalid_window(mock_app_context, test_db: PipelineDB):
    """验证 GET /api/funnel 空白字符清洗与非法窗口参数回退。"""
    client, _ = mock_app_context
    test_db.add_channel("UC_WS", "Whitespace Channel", status="APPROVED")
    test_db.add_video("vid_ws", "Video WS", "UC_WS", score=80)

    # 1. channel 前后带空格被正常剥离匹配
    res_ws = client.get("/api/funnel?window=all&channel=%20UC_WS%20")
    assert res_ws.status_code == 200
    assert res_ws.json()["channel_id"] == "UC_WS"
    assert res_ws.json()["channel_name"] == "Whitespace Channel"
    assert res_ws.json()["metrics"]["total_ingested"] == 1

    # 2. channel 仅包含空格时回退为全局指标
    res_blank = client.get("/api/funnel?window=all&channel=%20%20%20")
    assert res_blank.status_code == 200
    assert "channel_id" not in res_blank.json()

    # 3. 非法窗口参数回退为 today_bj
    res_invalid_win = client.get("/api/funnel?window=non_existent_win")
    assert res_invalid_win.status_code == 200
    assert res_invalid_win.json()["window"] == "today_bj"


def test_service_facade_mismatched_target_defense(tmp_path: Path):
    """验证服务门面防御 target 错配缺陷（若返回的 family 未命中目标 ID，严格返回 None）。"""
    from video_processing.funnel_diagnosis.models import TaskUnitFacts

    class MismatchedFamilyDB:
        def get_funnel_task_family_facts_by_ids(self, ids):
            return [TaskUnitFacts(video_id=10, youtube_id="vid_10")]

    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    # 请求 999 但 DB 仅返回 10，不得误把 10 当作 999 返回
    res = get_funnel_task_evidence_payload(MismatchedFamilyDB(), out_dir=out_dir, video_id=999)
    assert res is None

    # 支持合法数字字符串规整
    res_str = get_funnel_task_evidence_payload(MismatchedFamilyDB(), out_dir=out_dir, video_id="10")
    assert res_str is not None
    assert res_str["video_id"] == 10

    # 非法或布尔 ID 安全返回 None
    assert get_funnel_task_evidence_payload(MismatchedFamilyDB(), out_dir=out_dir, video_id="abc") is None
    assert get_funnel_task_evidence_payload(MismatchedFamilyDB(), out_dir=out_dir, video_id=-1) is None
    assert get_funnel_task_evidence_payload(MismatchedFamilyDB(), out_dir=out_dir, video_id=True) is None


def test_api_task_evidence_normal_task_with_platform_receipt(mock_app_context, test_db: PipelineDB):
    """GET /api/funnel/tasks/{video_id}/evidence 对已发布正常任务包含平台回执事实。"""
    client, _ = mock_app_context
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    _seed_diagnosis_test_tasks(test_db, now_utc)

    res = client.get("/api/funnel/tasks/2/evidence")
    assert res.status_code == 200
    payload = res.json()["data"]
    facts = payload["evidence"]["facts"]
    assert any("export/pub123" in f for f in facts)


@pytest.mark.parametrize("endpoint", ["/api/funnel/diagnosis", "/api/funnel/tasks/1/evidence"])
def test_api_diagnosis_source_failure_is_unavailable(mock_app_context, test_db: PipelineDB, endpoint):
    """根查询失败返回稳定503，既不伪造空集/404，也不泄露底层异常。"""
    client, _ = mock_app_context
    with test_db.get_connection() as conn:
        conn.execute("DROP TABLE processed_videos")
    response = client.get(endpoint)
    assert response.status_code == 503
    assert response.json() == {"detail": DiagnosisUnavailable.detail}
    assert "processed_videos" not in response.text


def test_api_partial_evidence_failure_is_unavailable(mock_app_context, test_db: PipelineDB):
    """存在任务但缺关联事件来源，不能返回看似完整的成功诊断。"""
    client, _ = mock_app_context
    _seed_diagnosis_test_tasks(test_db, datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
    with test_db.get_connection() as conn:
        conn.execute("DROP TABLE wechat_submission_attempts")
    for endpoint in ("/api/funnel/diagnosis?window=all", "/api/funnel/tasks/1/evidence"):
        response = client.get(endpoint)
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "FUNNEL_DIAGNOSIS_UNAVAILABLE"


def test_api_diagnosis_reads_do_not_write(mock_app_context, test_db: PipelineDB):
    """真实GET全链路在SQLite拒绝写入且初始化禁止时仍成功。"""
    from contextlib import contextmanager
    import sqlite3

    client, out_dir = mock_app_context
    _seed_diagnosis_test_tasks(test_db, datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
    original_connection = test_db.get_connection
    writes = []
    mutating = {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE,
                sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_ALTER_TABLE, sqlite3.SQLITE_DROP_TABLE}

    @contextmanager
    def readonly_connection():
        with original_connection() as conn:
            def authorize(action, *args):
                if action in mutating:
                    writes.append(action)
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            conn.set_authorizer(authorize)
            yield conn

    before = sorted(str(p.relative_to(out_dir)) for p in out_dir.rglob("*"))
    with patch.object(test_db, "get_connection", readonly_connection):
        assert client.get("/api/funnel/diagnosis?window=all").status_code == 200
        assert client.get("/api/funnel/tasks/1/evidence").status_code == 200
    assert writes == []
    assert sorted(str(p.relative_to(out_dir)) for p in out_dir.rglob("*")) == before


def test_service_uses_configured_thresholds():
    """配置单一来源的所有健康度阈值均传入规则配置。"""
    from config.settings import settings

    with patch.object(settings, "pre_submission_orphan_seconds", 600):
        thresholds = _diagnosis_thresholds()
    assert thresholds.pre_submission_orphan_seconds == 600
    assert thresholds.publishing_orphan_seconds == settings.publishing_orphan_seconds
    assert thresholds.caption_progress_stale_seconds == settings.caption_progress_stale_seconds
    assert thresholds.missed_window_stall_seconds == settings.missed_window_stall_seconds
    assert thresholds.ready_supervisor_heartbeat_stale_seconds == settings.ready_supervisor_heartbeat_stale_seconds
    assert thresholds.queue_stale_days == settings.queue_stale_days


def test_service_applies_channel_admission_thresholds():
    """演讲频道40分资格必须进入规则事实，禁止被DAL的默认75分覆盖。"""
    from config.settings import settings
    from video_processing.funnel_diagnosis.service import _fetch_cohort_tasks, _fetch_task_family
    from video_processing.funnel_diagnosis.models import TaskUnitFacts

    task = TaskUnitFacts(video_id=1, youtube_id="speech", channel_id="UC_SPEECH", score=45)

    class TaskDB:
        def get_cohort_task_facts(self, **kwargs):
            return [task]

        def get_funnel_task_family_facts_by_ids(self, ids):
            return [task]

    with patch.object(settings, "speech_channel_ids", "UC_SPEECH"):
        cohort = _fetch_cohort_tasks(TaskDB(), "all", None)
        family = _fetch_task_family(TaskDB(), 1)
    assert cohort[0].qualified_score_line == settings.speech_publish_score_line
    assert family[0].qualified_score_line == settings.speech_publish_score_line
    assert task.qualified_score_line == 75  # 原始DAL事实不原地修改。


def test_service_threshold_changes_summary_and_task_evidence(tmp_path: Path):
    """配置从20分钟改成10分钟后，15分钟无进度任务的两个入口同时变为停滞。"""
    from config.settings import settings
    from video_processing.funnel_diagnosis.models import TaskUnitFacts

    timestamp = datetime.now(timezone.utc).timestamp() - 900
    task = TaskUnitFacts(video_id=1, youtube_id="threshold_test", status="DOWNLOADING",
                         created_epoch=timestamp, updated_epoch=timestamp)

    class TaskDB:
        def get_cohort_task_facts(self, **kwargs):
            return [task]

        def get_funnel_task_family_facts_by_ids(self, ids):
            return [task]

    with patch.object(settings, "pre_submission_orphan_seconds", 1200):
        assert get_funnel_diagnosis_payload(TaskDB(), tmp_path)["tasks"] == []
    with patch.object(settings, "pre_submission_orphan_seconds", 600):
        summary = get_funnel_diagnosis_payload(TaskDB(), tmp_path)
        evidence = get_funnel_task_evidence_payload(TaskDB(), tmp_path, 1)
    assert summary["tasks"][0]["cause_code"] == "PRE_SUBMISSION_ORPHAN_STALL"
    assert evidence["diagnosis"]["cause_code"] == "PRE_SUBMISSION_ORPHAN_STALL"


def test_service_rejects_invalid_dal_results(tmp_path: Path):
    """非法DAL返回值不能被吞成真实空集。"""
    class InvalidDB:
        def get_cohort_task_facts(self, **kwargs):
            return None

    with pytest.raises(DiagnosisUnavailable):
        get_funnel_diagnosis_payload(InvalidDB(), tmp_path)


def test_api_runtime_source_unavailable_is_503(mock_app_context, test_db: PipelineDB):
    """探针明确不可用时不能呈现默认空锁、正常状态或空摘要。"""
    from types import SimpleNamespace
    from video_processing.funnel_diagnosis import service

    client, _ = mock_app_context
    _seed_diagnosis_test_tasks(test_db, datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
    with patch.object(service, "probe_runtime_environment", return_value=SimpleNamespace(runtime_available=False)):
        for endpoint in ("/api/funnel/diagnosis?window=all", "/api/funnel/tasks/1/evidence"):
            response = client.get(endpoint)
            assert response.status_code == 503
            assert response.json()["detail"] == DiagnosisUnavailable.detail
