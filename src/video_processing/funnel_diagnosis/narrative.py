"""入库批次异常原因聚合、证据链组装与可追溯诊断句生成模块（纯函数、无 I/O）。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-10-29 | Codex | 当前受影响任务族互斥主态、恢复历史分离、统一证据时间与真实运行观测。 |
| 1.0.0 | 2026-10-29 | Antigravity | 实现按主任务族去重的三层汇总、原因聚合排序、事实/推测/建议证据组装与确定性诊断句生成。 |
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Optional, Sequence

from .models import (
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
from .rules import (
    diagnose_task_unit,
    format_bj_timestamp,
    is_task_actively_running,
    resolve_delivery_state,
    resolve_stage_label,
)


def attach_task_evidence(
    task: TaskUnitFacts, diag: TaskAnomalyDiagnosis, env: RuntimeEnvironmentFacts
) -> TaskAnomalyDiagnosis:
    """为单条异常任务补充【事实】【推测】【建议】三元组证据。"""
    facts: list[str] = [
        f"入库时间：{format_bj_timestamp(task.created_epoch, task.created_at)}",
        f"状态更新时间：{format_bj_timestamp(task.updated_epoch, task.updated_at)}",
        f"运行观测时间：{task.runtime_observed_at_bj or env.now_bj_iso}",
        f"当前任务状态：{task.status}",
    ]
    if diag.time_estimated:
        facts.append(f"历史覆盖说明：早于事件账本覆盖起点 ({HISTORICAL_EVENT_COVERAGE_START[:10]}) 或缺失败事件，异常时间按状态更新时间估算。")
    for ev in task.failure_events[:3]:
        facts.append(f"失败事件 #{ev.get('id')}: {format_bj_timestamp(ev.get('failed_epoch'), str(ev.get('failed_at') or ''))} 状态={ev.get('status')}")
    for item in task.recovery_items[:3]:
        facts.append(f"恢复项 #{item.get('id')}: 状态={item.get('state')}，原因={item.get('reason') or '无'}，批次={item.get('op_state') or '未知'}")
    if not task.runtime_observation_available:
        facts.append("任务锁/进度：当前观测不可用（不是未占用）")
    elif task.has_active_task_lock:
        facts.append(f"任务锁：持有中 ({task.task_lock_owner.get('stage') or '加工'} pid={task.task_lock_owner.get('pid')})")
    elif env.pipeline_lock_held and env.pipeline_lock_owner.get("video"):
        facts.append(f"全局加工锁：由任务 {env.pipeline_lock_owner.get('video')} (pid={env.pipeline_lock_owner.get('pid')}) 占用")
    else:
        facts.append("任务锁：当前未占用")
    pub = task.wechat_publication or {}
    facts.append(
        f"平台回执：已绑定 {pub.get('platform_post_id')} (状态={pub.get('state')})"
        if pub.get("platform_post_id")
        else f"平台身份：尚无原生 ID 绑定 (提交尝试次数={len(task.submission_attempts)})"
    )
    facts.append("公开可见性：独立回读已核实" if diag.delivery_state == DeliveryState.PUBLIC_CONFIRMED.value else "公开可见性：尚未取得独立公开回读证明")
    inf, rec = _infer_and_recommend(diag)
    return replace(diag, facts=tuple(facts), inferences=(inf,), recommendations=(rec,))


def _infer_and_recommend(diag: TaskAnomalyDiagnosis) -> tuple[str, str]:
    if diag.is_uncertain_delivery:
        return "提交证据未完成核对，平台可能已受理；身份回执与公开可见性需分别核实。", "请通过平台回执核实入口核对视频号后台，确认前严禁直接重发。"
    if diag.cause_code == "RECOVERY_SKIPPED_SUPERVISOR_STOPPED":
        return "恢复批次入队后任务版本发生变化，触发防误发跳过保护，且原批次已结束、监督进程已退出。", "请重新打开恢复预览生成新版本快照后入队。"
    if diag.category == AnomalyCategory.QUALITY_POLICY_BLOCK.value:
        return "命中内容审核、题材风险或频道策略门禁（不计入系统执行故障）。", "请人工复核并遵守既有发布前审查门禁。"
    if diag.handling_state == HandlingState.WAITING_CONDITION.value:
        return "存在退避或微信频控冷却条件，到期后仍须满足调度与发布门禁。", "等待条件结束后核查推进情况，勿强制重发。"
    if diag.handling_state == HandlingState.RUNNING.value:
        return "当前存在运行观测，尚不能认定前序故障已解除。", "继续观察当前任务，不并发触发重试。"
    if diag.cause_code in {"RUNTIME_OBSERVATION_UNAVAILABLE", "RECOVERY_EVIDENCE_UNVERIFIED"}:
        return "现有证据不足以认定故障已解除或任务无进程。", "先恢复观测或核查恢复完成记录。"
    if diag.is_recovered:
        return "前序技术故障已解除。", "当前无需人工排障，观察后续交付完成即可。"
    return "任务在执行阶段中止且无活跃自动恢复进程接管。", f"查看折叠的脱敏错误摘要，执行：{diag.next_step}。"


def aggregate_causes(diagnoses: Sequence[TaskAnomalyDiagnosis]) -> list[CauseAggregationRow]:
    """按 cause_code 聚合第二层异常原因，受影响任务数按主任务族 (family_root_id) 去重。"""
    grouped: dict[str, list[TaskAnomalyDiagnosis]] = {}
    for d in diagnoses:
        grouped.setdefault(d.cause_code, []).append(d)
    rows: list[CauseAggregationRow] = []
    for code, items in grouped.items():
        first = items[0]
        family_ids = tuple(sorted({i.family_root_id for i in items}))
        unresolved_families = {i.family_root_id for i in items if i.unresolved}
        earliest_item = min(items, key=lambda x: x.occurred_epoch)
        latest_item = max(items, key=lambda x: x.occurred_epoch)
        rows.append(
            CauseAggregationRow(
                cause_code=code, cause_title=first.cause_title, category=first.category, category_label=first.category_label,
                affected_tasks=len(family_ids), affected_slices=sum(1 for i in items if i.slice_index > 0),
                unresolved_tasks=len(unresolved_families), event_count=sum(i.event_count for i in items),
                earliest_occurred_at=earliest_item.occurred_at, longest_duration_seconds=round(max(i.duration_seconds for i in items), 1),
                latest_progress=latest_item.latest_progress, recommended_next_step=first.next_step,
                action_kind=first.action_kind, is_system_fault=first.is_system_fault,
                family_ids=family_ids, task_ids=tuple(i.video_id for i in items),
            )
        )
    rows.sort(
        key=lambda r: (1 if r.unresolved_tasks > 0 else 0, 1 if r.is_system_fault else 0, r.unresolved_tasks, r.longest_duration_seconds, r.affected_tasks),
        reverse=True,
    )
    return rows


def build_cohort_narrative_sentence(
    summary: dict[str, Any], causes: Sequence[CauseAggregationRow], active_lock_note: str = ""
) -> str:
    """基于真实统计数字与原因聚合确定性拼装可追溯流程诊断句（绝不调用 LLM）。"""
    ingested = int(summary.get("total_ingested") or 0)
    if ingested == 0:
        return "当前筛选批次内暂无入库任务。"
    pub_confirmed = int(summary.get("public_confirmed") or 0)
    unverified_done = int(summary.get("local_done_unverified") or 0)
    unresolved = int(summary.get("unresolved_tasks") or 0)
    recovered_pending = int(summary.get("recovered_pending_delivery") or 0)
    head_parts = [f"本批次共 {ingested} 条入库", f"{pub_confirmed} 条已确认公开" if pub_confirmed > 0 else "尚无新增公开确认"]
    if unverified_done > 0:
        head_parts.append(f"{unverified_done} 条本地完成但公开状态未核实")
    head = "，".join(head_parts)
    if unresolved == 0:
        tail = "当前无未解决异常" + (f"（另有 {recovered_pending} 条故障已恢复但交付未完成）" if recovered_pending > 0 else "")
        return f"{head}；{tail}{('；' + active_lock_note) if active_lock_note else ''}。"
    cause_fragments = [f"{c.unresolved_tasks} 条{c.cause_title}" for c in causes if c.unresolved_tasks > 0][:4]
    detail_str = f"（{'，'.join(cause_fragments)}）" if cause_fragments else ""
    extra = ([f"另有 {recovered_pending} 条故障已恢复但交付未完成"] if recovered_pending > 0 else []) + ([active_lock_note] if active_lock_note else [])
    return f"{head}；当前 {unresolved} 条未解决{detail_str}{('；' + '，'.join(extra)) if extra else ''}。"


def _build_cohort_summary(
    tasks: Sequence[TaskUnitFacts],
    diagnoses: Sequence[TaskAnomalyDiagnosis],
    causes: Sequence[CauseAggregationRow],
    pub_confirmed_fams: set[int],
    local_unverified_fams: set[int],
    active_notes: Sequence[str],
) -> dict[str, Any]:
    root_fams = {t.parent_id or t.video_id for t in tasks}
    current = [d for d in diagnoses if d.handling_state != HandlingState.RECOVERED_COMPLETED.value]
    distribution = {"system": 0, "uncertain": 0, "policy": 0, "recovered": 0}
    for bucket in {d.family_root_id: d.family_primary_bucket for d in current}.values():
        distribution[bucket] += 1
    has_insufficient = any(d.time_estimated for d in diagnoses) or any(
        bool(t.created_at and t.created_at < HISTORICAL_EVENT_COVERAGE_START) for t in tasks
    )
    summary: dict[str, Any] = {
        "total_ingested": len(root_fams) if tasks else 0,
        "public_confirmed": len(pub_confirmed_fams),
        "local_done_unverified": len(local_unverified_fams - pub_confirmed_fams),
        "affected_tasks": len({d.family_root_id for d in current}),
        "family_distribution": distribution,
        "family_distribution_priority": ["uncertain", "system", "policy", "recovered"],
        "affected_slices": sum(1 for d in current if d.slice_index > 0),
        "unresolved_tasks": len({d.family_root_id for d in diagnoses if d.unresolved}),
        "system_fault_unresolved_tasks": len({d.family_root_id for d in diagnoses if d.unresolved and d.is_system_fault}),
        "policy_block_tasks": len({d.family_root_id for d in diagnoses if d.unresolved and not d.is_system_fault}),
        "stalled_tasks": len({d.family_root_id for d in diagnoses if d.unresolved and d.is_stalled}),
        "uncertain_delivery_tasks": len({d.family_root_id for d in diagnoses if d.unresolved and d.is_uncertain_delivery}),
        "recovered_tasks": len({d.family_root_id for d in diagnoses if d.is_recovered}),
        "recovered_pending_delivery": len({d.family_root_id for d in diagnoses if d.handling_state == HandlingState.RECOVERED_PENDING_DELIVERY.value}),
        "recovered_completed": len({d.family_root_id for d in diagnoses if d.handling_state == HandlingState.RECOVERED_COMPLETED.value}),
        "has_insufficient_history": has_insufficient,
        "coverage_start": HISTORICAL_EVENT_COVERAGE_START,
        "statistics_unit": "parent_family",
        "cause_counts_overlap": True,
    }
    summary["diagnosis_sentence"] = build_cohort_narrative_sentence(summary, causes, active_notes[0] if active_notes else "")
    return summary


def evaluate_cohort_diagnosis(
    tasks: Sequence[TaskUnitFacts],
    env: RuntimeEnvironmentFacts,
    thresholds: Optional[DiagnosisThresholds] = None,
) -> dict[str, Any]:
    """对同一入库批次任务集合执行三层完整诊断（摘要 + 原因聚合 + 任务明细）。"""
    cfg = thresholds or DiagnosisThresholds()
    diagnoses: list[TaskAnomalyDiagnosis] = []
    pub_confirmed_fams: set[int] = set()
    family_states: dict[int, list[str]] = {}
    local_unverified_fams: set[int] = set()
    active_notes: list[str] = []
    for t in tasks:
        fam_id = t.parent_id or t.video_id
        d_state = resolve_delivery_state(t)
        if t.status != "SEGMENTED":
            family_states.setdefault(fam_id, []).append(d_state)
        if d_state in (DeliveryState.LOCAL_DONE_UNVERIFIED.value, DeliveryState.PLATFORM_ACCEPTED.value):
            local_unverified_fams.add(fam_id)
        if is_task_actively_running(t, env, cfg):
            dur_m = int(max(0.0, env.now_epoch - (t.caption_stage_started_epoch or t.updated_epoch or env.now_epoch)) // 60)
            active_notes.append(f"任务 {t.youtube_id} 正在执行 {resolve_stage_label(t)} (已运行 {dur_m}m)")
        diag = diagnose_task_unit(t, env, cfg)
        if diag is not None:
            diagnoses.append(attach_task_evidence(t, diag, env))
    pub_confirmed_fams = {fam for fam, states in family_states.items() if states and all(s == DeliveryState.PUBLIC_CONFIRMED.value for s in states)}
    ranks = {"uncertain": 0, "system": 1, "policy": 2, "recovered": 3}
    primary: dict[int, str] = {}
    for d in diagnoses:
        if d.handling_state == HandlingState.RECOVERED_COMPLETED.value:
            continue
        bucket = "uncertain" if d.is_uncertain_delivery else ("system" if d.unresolved and d.is_system_fault else ("policy" if d.unresolved else "recovered"))
        old = primary.get(d.family_root_id, "recovered")
        primary[d.family_root_id] = min((old, bucket), key=ranks.get)
    diagnoses = [replace(d, family_primary_bucket=primary.get(d.family_root_id, "")) for d in diagnoses]
    diagnoses.sort(key=lambda d: (1 if d.unresolved else 0, d.duration_seconds), reverse=True)
    causes = aggregate_causes(diagnoses)
    summary = _build_cohort_summary(tasks, diagnoses, causes, pub_confirmed_fams, local_unverified_fams, active_notes)
    summary["window_history_available"] = env.executable_window_started_epoch is not None
    unverified_waiting = {
        t.parent_id or t.video_id for t in tasks
        if t.status == "PENDING" and t.source != "DISCOVERY"
        and (t.score >= t.qualified_score_line or t.preparation_ready)
        and env.now_epoch - (t.updated_epoch or env.now_epoch) >= cfg.missed_window_stall_seconds
    } if not summary["window_history_available"] else set()
    summary["window_history_unverified_tasks"] = len(unverified_waiting)
    summary["window_history_note"] = (
        f"{len(unverified_waiting)} 个排队任务族缺少连续可执行窗口持续时间证据，是否漏调度尚未核实。"
        if unverified_waiting else ""
    )
    if summary["window_history_note"]:
        summary["diagnosis_sentence"] += summary["window_history_note"]
    return {"as_of_bj": env.now_bj_iso, "summary": summary, "causes": causes,
            "tasks": [d for d in diagnoses if d.handling_state != HandlingState.RECOVERED_COMPLETED.value]}
