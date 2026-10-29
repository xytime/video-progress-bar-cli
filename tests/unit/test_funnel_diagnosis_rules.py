"""入库批次异常诊断纯规则层单元测试（零 Mock，覆盖验收场景 1/3/4/5/6 与今日真实报错签名）。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-10-29 | Codex | 覆盖冲突提交、公开证据、恢复凭据、互斥分母、配置与运行未知边界。 |
| 1.0.0 | 2026-10-29 | Antigravity | 覆盖六大异常分类、恢复跳过、避让vs停滞、分集去重、防误导门禁及真实报错尾部提取。 |
"""
from __future__ import annotations

from dataclasses import replace
import pytest

from video_processing.funnel_diagnosis import (
    AnomalyCategory,
    DeliveryState,
    DiagnosisThresholds,
    HandlingState,
    RuntimeEnvironmentFacts,
    TaskUnitFacts,
    diagnose_task_unit,
    evaluate_cohort_diagnosis,
    extract_tail_error_signature,
    resolve_delivery_state,
    sanitize_error_excerpt,
)

NOW_EPOCH = 1793233200.0  # 2026-10-29 08:20:00 BJ


def _env(**overrides) -> RuntimeEnvironmentFacts:
    base = {
        "now_epoch": NOW_EPOCH,
        "now_bj_iso": "2026-10-29 08:20:00 BJ",
        "executable_window_started_epoch": NOW_EPOCH - 7200,
        "in_market_guard_window": False,
        "in_public_publish_window": True,
        "wechat_publishing_paused": False,
        "pipeline_lock_held": False,
        "pipeline_lock_owner": {},
        "ready_supervisor_lock_held": True,
        "ready_supervisor_heartbeat_age_sec": 2.5,
        "recovery_worker_lock_held": False,
        "wechat_browser_lock_held": False,
        "wechat_cooldown_until_epoch": None,
        "wechat_cooldown_reason": "",
        "wechat_login_valid": True,
        "agy_cover_relogin_required": False,
    }
    base.update(overrides)
    return RuntimeEnvironmentFacts(**base)


def test_scenario_1_cross_day_ingestion_vs_anomaly_time_and_real_tail_signature():
    """场景 1 + 今日真实案例 #6945：昨日入库、今日失败，且从长日志尾部提取 NativeCaptionReview 原因。"""
    raw_err = (
        "2026-10-29 04:42:16,840 - video_processing.processors.caption_processor - INFO - "
        "Processing video: /Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/output/original_video/uWqFBoeLCPk.mp4\n"
        "2026-10-29 04:42:19,603 - video_processing.processors.caption_processor - INFO - Starting transcription...\n"
        "video_processing.processors.native_caption_router.NativeCaptionReviewRequired: "
        "[NativeCaptionReview] 原字幕识别未完成：VISUAL_REVIEW_BUDGET_EXCEEDED\nAborted!\n"
    )
    task = TaskUnitFacts(
        video_id=6945,
        youtube_id="uWqFBoeLCPk",
        title="Are Paid Influencers Influencing Your Midterm",
        status="FAILED",
        score=90,
        error_msg=raw_err,
        created_at="2026-10-27 16:02:24",
        created_epoch=NOW_EPOCH - 115000,
        updated_at="2026-10-28 22:02:04",
        updated_epoch=NOW_EPOCH - 8000,
        failed_at="2026-10-28 21:20:14.135",
        failed_epoch=NOW_EPOCH - 10786,
        caption_stage="SOURCE_CAPTION_LOCATING",
    )
    diag = diagnose_task_unit(task, _env())
    assert diag is not None
    assert diag.cause_code == "NATIVE_CAPTION_VISUAL_BUDGET"
    assert diag.stage == "字幕·原片识别与擦除 (SOURCE_CAPTION_LOCATING)"
    assert "2026-10-28" in diag.ingested_at or "2026-10-27" in diag.ingested_at
    assert "2026-10-29 05:20:14 BJ" == diag.occurred_at
    assert diag.ingested_at != diag.occurred_at
    assert "<REDACTED_PATH>" in diag.sanitized_error_excerpt


def test_scenario_3_recovery_skipped_and_supervisor_stopped():
    """场景 3 + 今日真实案例 #6710：恢复已入队，因任务变化被跳过，批次完成且监督退出。"""
    task = TaskUnitFacts(
        video_id=6710,
        youtube_id="AkTXAcMgO3E",
        status="FAILED",
        score=85,
        error_msg="[NativeCaptionReview] 原字幕识别未完成：OCR_INVALID_ROW",
        created_at="2026-10-26 13:17:32",
        updated_at="2026-10-28 23:30:11",
        failed_at="2026-10-27 13:15:41",
        failed_epoch=NOW_EPOCH - 90000,
        recovery_items=(
            {
                "id": 2,
                "operation_id": "7c63ab62-cf29-477d-9a6f-256de5180eee",
                "op_state": "COMPLETED",
                "state": "SKIPPED",
                "reason": "预览后任务已变化，未执行",
                "updated": NOW_EPOCH - 3000,
            },
        ),
    )
    diag = diagnose_task_unit(task, _env(recovery_worker_lock_held=False))
    assert diag is not None
    assert diag.category == AnomalyCategory.FLOW_STALL.value
    assert diag.cause_code == "RECOVERY_SKIPPED_SUPERVISOR_STOPPED"
    assert diag.handling_state == HandlingState.MANUAL_REQUIRED.value
    assert diag.is_stalled is True
    assert diag.unresolved is True
    assert "预览后任务已变化" in diag.reason_summary


def test_scenario_4_market_avoidance_vs_missed_executable_window_stall():
    """场景 4：正常美股避让或全局锁等待不报错；可执行窗口内无锁超阈值未启动升级为流程停滞。"""
    waiting_task = TaskUnitFacts(
        video_id=7001,
        youtube_id="wait_001",
        status="PENDING",
        score=88,
        preparation_ready=True,
        created_at="2026-10-28 18:00:00",
        updated_at="2026-10-28 22:00:00",
        updated_epoch=NOW_EPOCH - 3600,
    )
    # 1. 美股保护窗口内：属于正常等待，返回 None
    assert diagnose_task_unit(waiting_task, _env(in_market_guard_window=True)) is None
    # 2. 另一条任务正持有 pipeline.lock：属于正常排队，返回 None
    assert diagnose_task_unit(waiting_task, _env(pipeline_lock_held=True)) is None
    # 3. 可执行窗口内、无锁占用、超过 30m 仍未启动：判定为错过可执行窗口停滞
    stalled = diagnose_task_unit(waiting_task, _env(in_market_guard_window=False, pipeline_lock_held=False))
    assert stalled is not None
    assert stalled.category == AnomalyCategory.FLOW_STALL.value
    assert stalled.cause_code == "MISSED_EXECUTABLE_WINDOW_STALL"
    assert stalled.is_stalled is True


def test_active_slow_caption_locating_not_flagged_as_orphan():
    """今日真实案例 #6906 (YuxF7u8LZO8)：DB updated_at 已过 33 分钟，但持有任务锁且 caption_progress 1.2s 前刚刷新。"""
    slow_active_task = TaskUnitFacts(
        video_id=6906,
        youtube_id="YuxF7u8LZO8",
        status="TRANSCRIBING",
        score=80,
        created_at="2026-10-28 12:30:16",
        updated_at="2026-10-28 23:44:51",
        updated_epoch=NOW_EPOCH - 2000,  # > 1200s orphan threshold
        has_active_task_lock=True,
        task_lock_owner={"video": "YuxF7u8LZO8", "stage": "加工", "pid": 44439},
        caption_stage="SOURCE_CAPTION_LOCATING",
        caption_stage_started_epoch=NOW_EPOCH - 1740,
        caption_progress_updated_epoch=NOW_EPOCH - 1.2,
    )
    assert diagnose_task_unit(slow_active_task, _env()) is None


def test_scenario_5_parent_slice_rollup_and_polling_idempotency():
    """场景 5：同一父任务下多个分集失败按主任务族去重计为 1 个受影响任务，连续轮询 5 次计数恒定。"""
    parent = TaskUnitFacts(video_id=500, youtube_id="parent500", status="SEGMENTED", score=85, created_at="2026-10-28 10:00:00")
    slice1 = TaskUnitFacts(
        video_id=501, parent_id=500, youtube_id="parent500", slice_index=1, status="FAILED", score=85,
        error_msg="burned_caption_repair.py: ValueError: 第 0 帧原字幕位置或文字不确定，停止出片：Test 1",
        created_at="2026-10-28 10:00:00", failed_epoch=NOW_EPOCH - 1200,
    )
    slice2 = TaskUnitFacts(
        video_id=502, parent_id=500, youtube_id="parent500", slice_index=2, status="FAILED", score=85,
        error_msg="burned_caption_repair.py: ValueError: 第 12 帧原字幕位置或文字不确定，停止出片：Test 2",
        created_at="2026-10-28 10:00:00", failed_epoch=NOW_EPOCH - 900,
    )
    results = [evaluate_cohort_diagnosis([parent, slice1, slice2], _env()) for _ in range(5)]
    first = results[0]
    assert first["summary"]["total_ingested"] == 1
    assert first["summary"]["affected_tasks"] == 1
    assert first["summary"]["affected_slices"] == 2
    assert first["summary"]["unresolved_tasks"] == 1
    assert len(first["tasks"]) == 2
    assert first["causes"][0].affected_tasks == 1
    assert first["causes"][0].affected_slices == 2
    for poll_res in results[1:]:
        assert poll_res["summary"] == first["summary"]


def test_scenario_6_anti_misleading_gates_uncertain_queued_and_recovered():
    """场景 6：入队≠已恢复；故障恢复但未交付＝故障已恢复交付未完成；UNCERTAIN 严禁重发；策略拦截独立于系统故障。"""
    # 1. 入队未执行 (RESERVED)
    queued_task = TaskUnitFacts(
        video_id=601, youtube_id="q601", status="FAILED", score=82,
        error_msg="Upload timeout", created_at="2026-10-28 10:00:00", failed_epoch=NOW_EPOCH - 600,
        recovery_items=({"id": 9, "operation_id": "op_9", "op_state": "QUEUED", "state": "RESERVED", "reason": "等待执行"},),
    )
    # 2. 故障已恢复，交付未完成
    rec_pending = TaskUnitFacts(
        video_id=602, youtube_id="r602", status="RENDERING", score=84, retry_count=1,
        has_active_task_lock=True, created_at="2026-10-28 11:00:00",
        failure_events=({"id": 50, "status": "FAILED", "failed_at": "2026-10-28 12:00:00", "failed_epoch": NOW_EPOCH - 3600},),
    )
    # 3. UNCERTAIN 投递结果待核实（真实案例 #6737）
    uncertain_task = TaskUnitFacts(
        video_id=6737, youtube_id="s101zPXkOx4", status="UNCERTAIN", score=81, preparation_ready=1,
        error_msg="已执行发表操作；按当前策略不自动查询结果。请在视频号确认，勿重复投稿。",
        created_at="2026-10-28 12:00:00", updated_epoch=NOW_EPOCH - 1800,
    )
    # 4. 策略风控拦截（真实案例 #6934 Social Unrest Review）
    policy_task = TaskUnitFacts(
        video_id=6934, youtube_id="6ZrgRjdJs3o", status="FAILED", score=87,
        censor_tag="平台题材风险：社会动荡", bypass_censorship=False,
        error_msg="Social Unrest Review: 平台题材风险：社会动荡 (demonstrates + costs)",
        created_at="2026-10-28 16:02:11", failed_epoch=NOW_EPOCH - 4000,
    )
    # 5. 本地 PUBLISHED 但无微信公开回执
    local_done = TaskUnitFacts(
        video_id=605, youtube_id="p605", status="PUBLISHED", score=80, created_at="2026-10-28 09:00:00",
        wechat_publication=None,
    )
    cohort = evaluate_cohort_diagnosis([queued_task, rec_pending, uncertain_task, policy_task, local_done], _env())
    s = cohort["summary"]
    assert s["total_ingested"] == 5
    assert s["public_confirmed"] == 0
    assert s["local_done_unverified"] == 1
    assert s["affected_tasks"] == 4
    assert s["unresolved_tasks"] == 4  # 活跃恢复尚未取得解除证据
    assert s["system_fault_unresolved_tasks"] == 3  # policy_task 不计入系统故障
    assert s["policy_block_tasks"] == 1
    assert s["uncertain_delivery_tasks"] == 1
    assert s["recovered_tasks"] == 0
    assert s["recovered_pending_delivery"] == 0
    assert "公开状态未核实" in s["diagnosis_sentence"]
    assert "未发布" not in s["diagnosis_sentence"]

    by_id = {d.video_id: d for d in cohort["tasks"]}
    assert by_id[601].handling_state == HandlingState.QUEUED.value
    assert by_id[601].is_recovered is False
    assert by_id[602].handling_state == HandlingState.RUNNING.value
    assert by_id[602].is_recovered is False
    assert by_id[6737].category == AnomalyCategory.DELIVERY_UNVERIFIED.value
    assert "严禁直接重发" in by_id[6737].next_step
    assert "重发" not in by_id[6737].action_kind


def test_real_subtitle_repair_budget_and_pre_coverage_estimation():
    """今日真实案例 #6940 (SUBTITLE_NEEDS_REPAIR) 与早于 2026-10-23 历史覆盖估算标记。"""
    sub_repair_task = TaskUnitFacts(
        video_id=6940, youtube_id="vD0fgM0XZaE", status="FAILED", score=83,
        error_msg="SUBTITLE_NEEDS_REPAIR: 字幕翻译需修复后恢复: translation_budget_exhausted",
        created_at="2026-10-28 16:02:18", failed_epoch=NOW_EPOCH - 2100,
        subtitle_recovery={"state": "NEEDS_REPAIR", "category": "budget", "code": "translation_budget_exhausted"},
    )
    legacy_task = TaskUnitFacts(
        video_id=1200, youtube_id="old1200", status="FAILED", score=78,
        error_msg="Download error", created_at="2026-10-15 10:00:00",
        updated_at="2026-10-15 11:00:00", updated_epoch=NOW_EPOCH - 864000,
        failed_at=None, failure_events=(),
    )
    res = evaluate_cohort_diagnosis([sub_repair_task, legacy_task], _env())
    assert res["summary"]["has_insufficient_history"] is True
    by_id = {d.video_id: d for d in res["tasks"]}
    assert by_id[6940].cause_code == "SUBTITLE_REPAIR_TRANSLATION_BUDGET_EXHAUSTED"
    assert by_id[6940].handling_state == HandlingState.MANUAL_REQUIRED.value
    assert by_id[6940].stage == "字幕·双语翻译 (TRANSLATING)"
    assert by_id[1200].time_estimated is True
    assert "(估算)" in by_id[1200].occurred_at


@pytest.mark.parametrize("evidence", [
    {"wechat_publication": {"state": "UNCERTAIN"}},
    {"submission_attempts": ({"state": "SUBMITTED_UNBOUND"},)},
    {"submission_attempts": ({"state": "PLATFORM_ID_BOUND", "platform_post_id": "export/native"},)},
    {"recovery_items": ({"state": "SUBMITTED_UNVERIFIED"},)},
    {"recovery_items": ({"state": "PUBLISHED", "updated": NOW_EPOCH - 60},)},
])
def test_submission_evidence_overrides_failed_retry(evidence):
    task = TaskUnitFacts(video_id=1, youtube_id="x", status="FAILED", **evidence)
    diag = diagnose_task_unit(task, _env())
    assert diag.action_kind == "verify_receipt"
    assert diag.is_uncertain_delivery and not diag.is_recovered


@pytest.mark.parametrize("ledger", ["PUBLISHED", "UNDER_REVIEW", "REJECTED", "SUBMITTED_BOUND", "CONFIRMED"])
def test_native_id_does_not_prove_public_visibility(ledger):
    task = TaskUnitFacts(video_id=1, youtube_id="x", status="PUBLISHED",
                         wechat_publication={"state": ledger, "platform_post_id": "export/native"})
    assert resolve_delivery_state(task) != DeliveryState.PUBLIC_CONFIRMED.value
    assert evaluate_cohort_diagnosis([task], _env())["summary"]["public_confirmed"] == 0


def test_recovery_requires_later_completion_and_family_distribution_is_exclusive():
    base = TaskUnitFacts(video_id=2, parent_id=1, slice_index=1, youtube_id="x", status="PENDING", retry_count=1,
                         failed_epoch=NOW_EPOCH - 3600)
    unverified = diagnose_task_unit(base, _env())
    assert not unverified.is_recovered and unverified.handling_state == HandlingState.MANUAL_REQUIRED.value
    recovered = replace(base, recovery_items=({"state": "PUBLISHED", "updated": NOW_EPOCH - 60},))
    assert diagnose_task_unit(recovered, _env()).handling_state == "RECOVERED_PENDING_DELIVERY"
    old = replace(recovered, recovery_items=({"state": "PUBLISHED", "updated": NOW_EPOCH - 7200},))
    assert not diagnose_task_unit(old, _env()).is_recovered
    tasks = [recovered, replace(base, video_id=3, status="FAILED"),
             replace(base, video_id=4, censor_tag="policy"), replace(base, video_id=5, status="UNCERTAIN")]
    summary = evaluate_cohort_diagnosis(tasks, _env())["summary"]
    assert summary["affected_tasks"] == 1
    assert summary["family_distribution"] == {"system": 0, "uncertain": 1, "policy": 0, "recovered": 0}
    assert sum(summary["family_distribution"].values()) == summary["affected_tasks"]


@pytest.mark.parametrize("status", ["PROCESSING", "PUBLISH_PRECHECK"])
def test_activity_observation_unknown_and_threshold_boundaries(status):
    base = TaskUnitFacts(video_id=1, youtube_id="x", status=status, updated_epoch=NOW_EPOCH - 1500)
    assert diagnose_task_unit(base, _env()).is_stalled
    assert diagnose_task_unit(replace(base, process_alive=True), _env()) is None
    unknown = diagnose_task_unit(replace(base, runtime_observation_available=False), _env())
    assert unknown.action_kind == "none" and not unknown.is_stalled
    assert diagnose_task_unit(base, _env(), DiagnosisThresholds(pre_submission_orphan_seconds=2000)) is None


def test_pause_discovery_and_unknown_window_never_claim_missed_window():
    base = TaskUnitFacts(video_id=1, youtube_id="x", status="PENDING", score=90, updated_epoch=NOW_EPOCH - 7200)
    assert diagnose_task_unit(base, _env(wechat_publishing_paused=True)) is None
    assert diagnose_task_unit(replace(base, source="DISCOVERY"), _env()) is None
    assert diagnose_task_unit(base, _env(executable_window_started_epoch=None)) is None
    summary = evaluate_cohort_diagnosis([base], _env(executable_window_started_epoch=None))["summary"]
    assert summary["window_history_available"] is False
    assert "是否漏调度尚未核实" in summary["diagnosis_sentence"]
    assert diagnose_task_unit(base, _env()).is_stalled


def test_bj_timestamp_and_failure_facts_share_timezone():
    from video_processing.funnel_diagnosis import format_bj_timestamp
    assert format_bj_timestamp(None, "2026-10-28T20:41:37.652Z") == "2026-10-29 04:41:37 BJ"
    assert format_bj_timestamp(None, "2026-10-29T04:41:37+08:00") == "2026-10-29 04:41:37 BJ"
    task = TaskUnitFacts(video_id=1, youtube_id="x", status="FAILED",
                         failure_events=({"id": 1, "failed_at": "2026-10-28 20:41:37.652"},))
    facts = evaluate_cohort_diagnosis([task], _env())["tasks"][0].facts
    assert any("2026-10-29 04:41:37 BJ" in fact for fact in facts)


def test_runtime_uses_settings_and_does_not_hide_bad_progress(tmp_path, monkeypatch):
    from config.settings import settings
    from video_processing.core.runtime_probe import probe_runtime_environment, enrich_task_facts_with_runtime
    monkeypatch.setattr(settings, "wechat_publishing_paused", True)
    monkeypatch.setattr(type(settings), "is_us_market_guard_window", lambda self, now=None: True)
    monkeypatch.setattr(type(settings), "is_public_publish_window", lambda self, now=None: False)
    env = probe_runtime_environment(tmp_path, now_epoch=NOW_EPOCH)
    assert (env.in_market_guard_window, env.in_public_publish_window, env.wechat_publishing_paused) == (True, False, True)
    assert env.runtime_available
    (tmp_path / "ready_publications_status.json").write_text("{broken", encoding="utf-8")
    broken = probe_runtime_environment(tmp_path, now_epoch=NOW_EPOCH)
    assert not broken.runtime_available and broken.runtime_unavailable_reasons
    (tmp_path / "x_caption_progress.json").write_text("{broken", encoding="utf-8")
    task = enrich_task_facts_with_runtime(TaskUnitFacts(video_id=1, youtube_id="x"), tmp_path)
    assert not task.runtime_observation_available
    assert diagnose_task_unit(task, _env()).action_kind == "none"


def test_completed_recovery_requires_public_readback_and_is_not_current_affected():
    task = TaskUnitFacts(
        video_id=1, youtube_id="x", status="PUBLISHED", failed_epoch=NOW_EPOCH - 3600,
        runtime_observed_at_bj="2026-10-29 08:20:00 BJ",
        recovery_items=({"state": "PUBLISHED", "updated": NOW_EPOCH - 60},),
        wechat_publication={"state": "PUBLISHED", "platform_post_id": "export/native"},
        public_visibility_evidence={"video_id": 1, "platform_post_id": "export/native", "public_visible": True,
                                    "source": "independent_public_readback", "public_url": "https://public.example/video",
                                    "observed_at": NOW_EPOCH - 30},
    )
    result = evaluate_cohort_diagnosis([task], _env())
    assert result["summary"]["public_confirmed"] == 1
    assert result["summary"]["recovered_completed"] == 1
    assert result["summary"]["affected_tasks"] == 0 and result["tasks"] == []
    assert sum(result["summary"]["family_distribution"].values()) == 0
    conflict = replace(task, wechat_publication={"state": "UNDER_REVIEW", "platform_post_id": "export/native"})
    assert resolve_delivery_state(conflict) != DeliveryState.PUBLIC_CONFIRMED.value


@pytest.mark.parametrize("state,updated,expected", [
    ("RESOLVED", NOW_EPOCH - 60, True), ("RELEASED", NOW_EPOCH - 60, False),
    ("RESOLVED", NOW_EPOCH - 7200, False), ("RESOLVED", NOW_EPOCH + 60, False),
])
def test_real_subtitle_resolved_updated_at_contract(state, updated, expected):
    task = TaskUnitFacts(video_id=1, youtube_id="x", status="PENDING", failed_epoch=NOW_EPOCH - 3600,
                         updated_epoch=NOW_EPOCH - 10,
                         subtitle_recovery={"state": state, "updated_at": updated, "is_current": 1})
    diag = diagnose_task_unit(task, _env())
    assert diag.is_recovered is expected
    assert diag.handling_state == (HandlingState.RECOVERED_PENDING_DELIVERY.value if expected else HandlingState.MANUAL_REQUIRED.value)


@pytest.mark.parametrize("item_state", ["SKIPPED", "FAILED", "ATTENTION", "SUBMITTED_UNVERIFIED", "COMPLETED"])
def test_completed_operation_is_not_successful_item(item_state):
    task = TaskUnitFacts(video_id=1, youtube_id="x", status="PENDING", failed_epoch=NOW_EPOCH - 3600,
                         recovery_items=({"state": item_state, "op_state": "COMPLETED", "updated": NOW_EPOCH - 60},))
    diag = diagnose_task_unit(task, _env())
    assert not diag.is_recovered
    if item_state == "SUBMITTED_UNVERIFIED":
        assert diag.action_kind == "verify_receipt"
