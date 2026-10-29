"""入库批次流程概览三层异常诊断纯规则包。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-10-29 | Codex | 服务导出延迟加载，避免纯模型导入反向拉起运行探针。 |
| 1.0.0 | 2026-10-29 | Antigravity | 导出入库批次异常诊断模型、规则判定与叙事聚合接口。 |
"""
from __future__ import annotations

from .models import (
    CATEGORY_LABELS,
    HANDLING_STATE_LABELS,
    HISTORICAL_EVENT_COVERAGE_START,
    AnomalyCategory,
    CauseAggregationRow,
    DeliveryState,
    DiagnosisThresholds,
    HandlingState,
    RuntimeEnvironmentFacts,
    TaskAnomalyDiagnosis,
    TaskUnitFacts,
)
from .narrative import (
    aggregate_causes,
    attach_task_evidence,
    build_cohort_narrative_sentence,
    evaluate_cohort_diagnosis,
)
from .rules import (
    diagnose_task_unit,
    extract_tail_error_signature,
    format_bj_timestamp,
    is_task_actively_running,
    resolve_delivery_state,
    resolve_occurred_time,
    resolve_stage_label,
    sanitize_error_excerpt,
)
def __getattr__(name):
    if name in {"get_funnel_diagnosis_payload", "get_funnel_task_evidence_payload"}:
        from . import service
        return getattr(service, name)
    raise AttributeError(name)

__all__ = [
    "CATEGORY_LABELS",
    "HANDLING_STATE_LABELS",
    "HISTORICAL_EVENT_COVERAGE_START",
    "AnomalyCategory",
    "CauseAggregationRow",
    "DeliveryState",
    "DiagnosisThresholds",
    "HandlingState",
    "RuntimeEnvironmentFacts",
    "TaskAnomalyDiagnosis",
    "TaskUnitFacts",
    "aggregate_causes",
    "attach_task_evidence",
    "build_cohort_narrative_sentence",
    "diagnose_task_unit",
    "evaluate_cohort_diagnosis",
    "extract_tail_error_signature",
    "format_bj_timestamp",
    "get_funnel_diagnosis_payload",
    "get_funnel_task_evidence_payload",
    "is_task_actively_running",
    "resolve_delivery_state",
    "resolve_occurred_time",
    "resolve_stage_label",
    "sanitize_error_excerpt",
]
