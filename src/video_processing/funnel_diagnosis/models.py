"""入库批次流程概览异常诊断纯数据模型（无 I/O、无外部依赖）。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-10-29 | Codex | 补充来源、运行观测可用性与独立公开证据，避免未知状态推断成功。 |
| 1.0.0 | 2026-10-29 | Antigravity | 初始创建入库批次异常诊断分类、处理状态、任务事实与聚合结果数据类。 |
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


HISTORICAL_EVENT_COVERAGE_START = "2026-10-23 00:00:00"


class AnomalyCategory(str, Enum):
    """六大异常类别（与正常等待严格区分）。"""

    EXECUTION_FAILURE = "EXECUTION_FAILURE"        # 执行失败
    FLOW_STALL = "FLOW_STALL"                      # 流程停滞
    DEPENDENCY_BLOCK = "DEPENDENCY_BLOCK"          # 依赖阻塞
    DELIVERY_UNVERIFIED = "DELIVERY_UNVERIFIED"    # 投递结果待核实
    QUALITY_POLICY_BLOCK = "QUALITY_POLICY_BLOCK"  # 质量与策略拦截（非系统故障）
    OBSERVATION_ANOMALY = "OBSERVATION_ANOMALY"    # 观测异常


CATEGORY_LABELS: dict[str, str] = {
    AnomalyCategory.EXECUTION_FAILURE.value: "执行失败",
    AnomalyCategory.FLOW_STALL.value: "流程停滞",
    AnomalyCategory.DEPENDENCY_BLOCK.value: "依赖阻塞",
    AnomalyCategory.DELIVERY_UNVERIFIED.value: "投递结果待核实",
    AnomalyCategory.QUALITY_POLICY_BLOCK.value: "质量与策略拦截",
    AnomalyCategory.OBSERVATION_ANOMALY.value: "观测异常",
}


class HandlingState(str, Enum):
    """异常处理状态（与任务 status 解耦，严格区分入队/恢复与交付完成）。"""

    UNHANDLED = "UNHANDLED"                                  # 未处理
    WAITING_CONDITION = "WAITING_CONDITION"                  # 等待条件
    QUEUED = "QUEUED"                                        # 已入队（未启动）
    RUNNING = "RUNNING"                                      # 执行中
    PENDING_VERIFY = "PENDING_VERIFY"                        # 结果待核实
    RECOVERED_PENDING_DELIVERY = "RECOVERED_PENDING_DELIVERY"  # 故障已恢复，交付未完成
    RECOVERED_COMPLETED = "RECOVERED_COMPLETED"              # 已恢复（交付完成）
    MANUAL_REQUIRED = "MANUAL_REQUIRED"                      # 需人工处理


HANDLING_STATE_LABELS: dict[str, str] = {
    HandlingState.UNHANDLED.value: "未处理",
    HandlingState.WAITING_CONDITION.value: "等待条件",
    HandlingState.QUEUED.value: "已入队",
    HandlingState.RUNNING.value: "执行中",
    HandlingState.PENDING_VERIFY.value: "结果待核实",
    HandlingState.RECOVERED_PENDING_DELIVERY.value: "故障已恢复，交付未完成",
    HandlingState.RECOVERED_COMPLETED.value: "已恢复",
    HandlingState.MANUAL_REQUIRED.value: "需人工处理",
}


class DeliveryState(str, Enum):
    """交付进展分层状态（禁止将缺少公开回读笼统标为已发布或未发布）。"""

    IN_PREPARATION = "IN_PREPARATION"              # 制作/排队中
    LOCAL_READY = "LOCAL_READY"                    # 本地加工完成
    PLATFORM_ACCEPTED = "PLATFORM_ACCEPTED"        # 平台已受理（公开状态未核实）
    PUBLIC_CONFIRMED = "PUBLIC_CONFIRMED"          # 公开可见已确认
    LOCAL_DONE_UNVERIFIED = "LOCAL_DONE_UNVERIFIED"  # 本地完成但公开状态未核实
    DELIVERY_UNCERTAIN = "DELIVERY_UNCERTAIN"      # 投递结果待核实
    DELIVERY_UNKNOWN = "DELIVERY_UNKNOWN"          # 证据冲突或交付状态未知


@dataclass(frozen=True)
class DiagnosisThresholds:
    """阶段化异常判定阈值（源自 settings.py，不使用固定 10 分钟一刀切）。"""

    pre_submission_orphan_seconds: int = 1200
    publishing_orphan_seconds: int = 1800
    caption_progress_stale_seconds: int = 900
    missed_window_stall_seconds: int = 1800
    ready_supervisor_heartbeat_stale_seconds: int = 30
    queue_stale_days: int = 7
    default_publish_score_line: int = 75


@dataclass(frozen=True)
class RuntimeEnvironmentFacts:
    """运行环境锁与窗口快照（由 runtime_probe 只读采集后传入纯规则层）。"""

    now_epoch: float
    now_bj_iso: str
    in_market_guard_window: bool = False
    in_public_publish_window: bool = True
    wechat_publishing_paused: bool = False
    pipeline_lock_held: bool = False
    pipeline_lock_owner: dict[str, Any] = field(default_factory=dict)
    ready_supervisor_lock_held: bool = False
    ready_supervisor_heartbeat_age_sec: Optional[float] = None
    recovery_worker_lock_held: bool = False
    wechat_browser_lock_held: bool = False
    wechat_cooldown_until_epoch: Optional[float] = None
    wechat_cooldown_reason: str = ""
    wechat_login_valid: bool = True
    agy_cover_relogin_required: bool = False
    runtime_available: bool = True
    runtime_unavailable_reasons: tuple[str, ...] = ()
    executable_window_started_epoch: Optional[float] = None


@dataclass(frozen=True)
class TaskUnitFacts:
    """单个执行单元（主任务或子分集）的数据库与运行态事实快照。"""

    video_id: int
    youtube_id: str
    slice_index: int = 0
    parent_id: Optional[int] = None
    title: str = ""
    channel_id: str = ""
    channel_name: str = ""
    status: str = "PENDING"
    source: str = "MONITOR"
    score: float = 0.0
    qualified_score_line: int = 75
    retry_count: int = 0
    error_msg: str = ""
    censor_tag: Optional[str] = None
    bypass_censorship: bool = False
    preparation_ready: bool = False
    source_subtitle_status: Optional[str] = None
    publication_review_required: bool = False
    publication_wait_reason: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""
    failed_at: Optional[str] = None
    updated_epoch: Optional[float] = None
    created_epoch: Optional[float] = None
    failed_epoch: Optional[float] = None
    process_pid: Optional[int] = None
    process_alive: bool = False
    has_active_task_lock: bool = False
    task_lock_owner: dict[str, Any] = field(default_factory=dict)
    caption_stage: Optional[str] = None
    caption_stage_started_epoch: Optional[float] = None
    caption_progress_updated_epoch: Optional[float] = None
    failure_events: tuple[dict[str, Any], ...] = ()
    recovery_items: tuple[dict[str, Any], ...] = ()
    subtitle_recovery: Optional[dict[str, Any]] = None
    delivery_recoveries: tuple[dict[str, Any], ...] = ()
    upload_retry_next_epoch: Optional[float] = None
    copywriter_next_epoch: Optional[float] = None
    wechat_publication: Optional[dict[str, Any]] = None
    submission_attempts: tuple[dict[str, Any], ...] = ()
    public_visibility_evidence: Optional[dict[str, Any]] = None
    runtime_observation_available: bool = True
    runtime_observed_at_bj: str = ""


@dataclass(frozen=True)
class TaskAnomalyDiagnosis:
    """单个任务单元的异常诊断结果。"""

    video_id: int
    family_root_id: int
    youtube_id: str
    slice_index: int
    title: str
    channel_id: str
    ingested_at: str
    category: str
    category_label: str
    cause_code: str
    cause_title: str
    stage: str
    reason_summary: str
    occurred_at: str
    occurred_epoch: float
    duration_seconds: float
    time_estimated: bool
    latest_progress: str
    handling_state: str
    handling_state_label: str
    delivery_state: str
    unresolved: bool
    is_system_fault: bool
    is_stalled: bool
    is_uncertain_delivery: bool
    is_recovered: bool
    event_count: int
    next_step: str
    action_kind: str
    facts: tuple[str, ...] = ()
    inferences: tuple[str, ...] = ()
    recommendations: tuple[str, ...] = ()
    sanitized_error_excerpt: str = ""
    status: str = ""
    has_active_task_lock: bool = False
    process_alive: bool = False
    runtime_observed_at_bj: str = ""
    runtime_observation_available: bool = True
    family_primary_bucket: str = ""


@dataclass(frozen=True)
class CauseAggregationRow:
    """第二层：按原因聚合的统计行。"""

    cause_code: str
    cause_title: str
    category: str
    category_label: str
    affected_tasks: int
    affected_slices: int
    unresolved_tasks: int
    event_count: int
    earliest_occurred_at: str
    longest_duration_seconds: float
    latest_progress: str
    recommended_next_step: str
    action_kind: str
    is_system_fault: bool
    family_ids: tuple[int, ...] = ()
    task_ids: tuple[int, ...] = ()
