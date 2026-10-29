"""入库批次流程异常判定、原因提取与处理状态推导纯规则层（无 I/O）。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-10-29 | Codex | 提交证据优先、恢复凭据验证、未知运行观测保护及阶段化停滞。 |
| 1.0.0 | 2026-10-29 | Antigravity | 实现六大异常分类、尾部异常签名提取、字幕子阶段细分、锁探活保护与处理状态推导。 |
"""
from __future__ import annotations

import re
from typing import Any, Optional

from .delivery_rules import (
    format_bj_timestamp, has_unresolved_submission, has_submission_evidence,
    has_recovery_completion_proof, resolve_delivery_state,
)
from .models import (
    CATEGORY_LABELS,
    HANDLING_STATE_LABELS,
    HISTORICAL_EVENT_COVERAGE_START,
    AnomalyCategory,
    DeliveryState,
    DiagnosisThresholds,
    HandlingState,
    RuntimeEnvironmentFacts,
    TaskAnomalyDiagnosis,
    TaskUnitFacts,
)

_SECRET_RE = re.compile(r"(?i)(token|cookie|key|secret|password|authorization|bearer)(\s*[=:]\s*)([^\s,;\"']+)")
_ABS_PATH_RE = re.compile(r"(/Volumes/[^\s:\"']+|/Users/[^\s:\"']+)")

_STAGE_MAP: dict[str, str] = {
    "PENDING": "排队等待 (PENDING)",
    "PROCESSING": "视频加工 (PROCESSING)",
    "PUBLISH_PRECHECK": "发布前检查 (PUBLISH_PRECHECK)",
    "DOWNLOADING": "视频下载 (DOWNLOADING)",
    "COPYWRITING": "文案生成 (COPYWRITING)",
    "RENDERING": "成片渲染 (RENDERING)",
    "PUBLISHING": "平台上传 (PUBLISHING)",
    "UNCERTAIN": "平台投递核实 (UNCERTAIN)",
    "SUBMITTED_UNBOUND": "平台受理待绑定 (SUBMITTED_UNBOUND)",
    "SUBMITTED_BOUND": "平台已受理 (SUBMITTED_BOUND)",
    "WECHAT_DEFERRED": "微信延后补发 (WECHAT_DEFERRED)",
    "LOGIN_REQUIRED": "登录授权门禁 (LOGIN_REQUIRED)",
    "PUBLISHED": "已发布记录 (PUBLISHED)",
}

_ERR_SIGNATURES: tuple[tuple[str, str, str, str, str], ...] = (
    ("VISUAL_REVIEW_BUDGET_EXCEEDED", AnomalyCategory.EXECUTION_FAILURE.value, "NATIVE_CAPTION_VISUAL_BUDGET", "原片内嵌字幕识别未完成：视觉核验预算耗尽", "原片字幕路由 (native_caption_router) 视觉核验超出预算 (VISUAL_REVIEW_BUDGET_EXCEEDED)"),
    ("OCR_INVALID_ROW", AnomalyCategory.EXECUTION_FAILURE.value, "NATIVE_CAPTION_OCR_INVALID", "原片内嵌字幕识别未完成：OCR 行校验失败", "原片字幕路由 OCR 行结果无效 (OCR_INVALID_ROW)"),
    ("[NativeCaptionReview]", AnomalyCategory.EXECUTION_FAILURE.value, "NATIVE_CAPTION_INCOMPLETE", "原片内嵌字幕对白不完整或无法确认", ""),
    ("原字幕位置或文字不确定", AnomalyCategory.EXECUTION_FAILURE.value, "BURNED_CAPTION_REPAIR_UNCERTAIN", "原片烧录字幕位置或文字不确定，停止出片", ""),
    ("burned_caption_repair", AnomalyCategory.EXECUTION_FAILURE.value, "BURNED_CAPTION_REPAIR_UNCERTAIN", "原片烧录字幕位置或文字不确定，停止出片", "烧录字幕定位不确定，安全门禁停止出片"),
    ("[RecoveryInterrupted]", AnomalyCategory.FLOW_STALL.value, "SUBTITLE_RECOVERY_INTERRUPTED", "修复字幕期间旧等待任务被停止（检查点已保留）", ""),
)


def sanitize_error_excerpt(raw: str, max_chars: int = 420) -> str:
    """脱敏原始错误日志（隐藏本机绝对路径与凭据）并截取尾部关键异常栈。"""
    if not raw:
        return ""
    text = _SECRET_RE.sub(r"\1\2<REDACTED>", str(raw).strip())
    text = _ABS_PATH_RE.sub("<REDACTED_PATH>", text)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    tail = "\n".join(lines[-8:]) if len(lines) > 8 else "\n".join(lines)
    return tail[-max_chars:] if len(tail) > max_chars else tail


def resolve_stage_label(task: TaskUnitFacts) -> str:
    """结合 DB 状态、字幕进度文件 stage 与尾部报错特征，解析精确发生阶段。"""
    err = task.error_msg or ""
    c_stage = (task.caption_stage or "").upper()
    if c_stage == "SOURCE_CAPTION_LOCATING" or "[NativeCaptionReview]" in err or "burned_caption_repair" in err:
        return "字幕·原片识别与擦除 (SOURCE_CAPTION_LOCATING)"
    if c_stage == "TRANSLATING" or "SUBTITLE_NEEDS_REPAIR" in err or "translation_budget" in err:
        return "字幕·双语翻译 (TRANSLATING)"
    if task.status == "TRANSCRIBING" or "asr.json" in err:
        return "字幕·语音转写 (ASR)"
    if task.status == "FAILED" and task.preparation_ready:
        return "平台发布恢复 (PUBLISHING)"
    return _STAGE_MAP.get(task.status, f"执行阶段 ({task.status})")


def _extract_matching_line(text: str, keyword: str) -> str:
    for line in reversed(text.splitlines()):
        if keyword in line:
            return line.strip()[:160]
    return ""


def _last_meaningful_error_line(text: str) -> str:
    for line in reversed(text.splitlines()):
        cleaned = line.strip()
        if cleaned and cleaned not in ("Aborted!", "Traceback (most recent call last):") and " - INFO - " not in cleaned:
            return cleaned[:160]
    return ""


def extract_tail_error_signature(task: TaskUnitFacts) -> tuple[str, str, str, str]:
    """从 error_msg 尾部向上提取结构化异常签名，严禁直接截取 stdout 头部时间戳。"""
    err = (task.error_msg or "").strip()
    wait_reason = (task.publication_wait_reason or "").strip()
    sub = task.subtitle_recovery or {}
    if "Channel Policy Reject" in err:
        line = _extract_matching_line(err, "Channel Policy Reject") or "命中频道策略限制词"
        return AnomalyCategory.QUALITY_POLICY_BLOCK.value, "CHANNEL_POLICY_REJECT", "频道策略限制拦截（非系统故障）", line
    if "Social Unrest Review" in err or (task.censor_tag and not task.bypass_censorship):
        line = _extract_matching_line(err, "Social Unrest Review") or f"命中审核标签：{task.censor_tag}"
        return AnomalyCategory.QUALITY_POLICY_BLOCK.value, "CONTENT_CENSOR_BLOCK", "内容审核/题材风险拦截（非系统故障）", line
    if "点赞率须严格" in wait_reason or task.publication_review_required:
        return AnomalyCategory.QUALITY_POLICY_BLOCK.value, "PUBLICATION_POLICY_GATE", "发布策略/点赞率或人工复核门禁（非系统故障）", (wait_reason or "需完成发布前人工复核")
    if "SUBTITLE_NEEDS_REPAIR" in err or str(sub.get("state") or "") == "NEEDS_REPAIR":
        code = str(sub.get("code") or "translation_budget_exhausted")
        return AnomalyCategory.EXECUTION_FAILURE.value, f"SUBTITLE_REPAIR_{code.upper()}", f"字幕翻译需人工修复 ({code})", f"字幕翻译耗时或预算超限 ({code})，自动退避已停止"
    for needle, cat, code, title, default_desc in _ERR_SIGNATURES:
        if needle in err:
            return cat, code, title, (default_desc or _extract_matching_line(err, needle) or title)
    tail_line = _last_meaningful_error_line(err) or "任务执行失败（详见错误日志摘要）"
    return AnomalyCategory.EXECUTION_FAILURE.value, "STAGE_EXECUTION_FAILED", f"{resolve_stage_label(task)}执行失败", tail_line


def is_task_actively_running(
    task: TaskUnitFacts, env: RuntimeEnvironmentFacts, thresholds: DiagnosisThresholds
) -> bool:
    """结合内核锁、进程存活与 caption_progress 心跳判断任务是否正在正常执行。"""
    if task.has_active_task_lock or task.process_alive:
        return True
    if task.caption_progress_updated_epoch is not None:
        return 0 <= (env.now_epoch - task.caption_progress_updated_epoch) < thresholds.caption_progress_stale_seconds
    return False


def resolve_occurred_time(
    task: TaskUnitFacts, env: RuntimeEnvironmentFacts
) -> tuple[float, str, bool]:
    """计算异常发生时间并标注是否早于 2026-10-23 事件账本覆盖期（估算时间）。"""
    if task.failed_epoch and task.failed_epoch > 0:
        return task.failed_epoch, format_bj_timestamp(task.failed_epoch, task.failed_at or ""), False
    if task.failure_events and task.failure_events[0].get("failed_epoch"):
        first_ev = task.failure_events[0]
        ep = float(first_ev["failed_epoch"])
        return ep, format_bj_timestamp(ep, str(first_ev.get("failed_at") or "")), False
    sub = task.subtitle_recovery or {}
    if sub.get("chain_started_at"):
        ep = float(sub["chain_started_at"])
        return ep, format_bj_timestamp(ep), False
    fallback_ep = float(task.updated_epoch or task.created_epoch or env.now_epoch)
    is_pre = bool(task.created_at and task.created_at < HISTORICAL_EVENT_COVERAGE_START)
    est = is_pre or (task.failed_at is None and not task.failure_events)
    label = format_bj_timestamp(fallback_ep, task.updated_at or task.created_at)
    return fallback_ep, (f"{label} (估算)" if est else label), est


def _evaluate_special_states(
    task: TaskUnitFacts, env: RuntimeEnvironmentFacts, thresholds: DiagnosisThresholds
) -> Optional[dict[str, Any]]:
    """依次评估投递待核实、恢复入队/运行/跳过、依赖退避阻塞与错过窗口停滞。"""
    pub = task.wechat_publication or {}
    pub_state = str(pub.get("state") or "")
    active = is_task_actively_running(task, env, thresholds)
    age = env.now_epoch - (task.updated_epoch or env.now_epoch)
    is_pub_orphan = task.runtime_observation_available and task.status == "PUBLISHING" and not active and age >= thresholds.publishing_orphan_seconds
    if has_unresolved_submission(task) or is_pub_orphan or (task.status == "FAILED" and has_submission_evidence(task)):
        occ_ep, occ_str, est = resolve_occurred_time(task, env)
        msg = "发布进程超时中断，未确认是否已完成平台提交" if is_pub_orphan else (task.error_msg or "缺少平台回执，投递结果待核实")
        return {
            "category": AnomalyCategory.DELIVERY_UNVERIFIED.value, "cause_code": "WECHAT_DELIVERY_UNVERIFIED",
            "cause_title": "微信投递结果待核实 (UNCERTAIN / 缺平台回执)", "stage": resolve_stage_label(task),
            "reason_summary": _last_meaningful_error_line(msg) or msg[:160], "occurred_epoch": occ_ep, "occurred_at": occ_str, "time_estimated": est,
            "latest_progress": f"状态 {task.status} · 严禁盲目重发", "handling_state": HandlingState.PENDING_VERIFY.value,
            "next_step": "核实平台回执（严禁直接重发）", "action_kind": "verify_receipt",
            "unresolved": True, "is_system_fault": True, "is_stalled": is_pub_orphan, "is_recovered": False,
        }
    if not task.runtime_observation_available or not env.runtime_available:
        return _observation_unknown(task, env)
    if task.status not in ("PUBLISHED", "SUBMITTED_BOUND") and task.recovery_items:
        latest = task.recovery_items[0]
        r_state = latest.get("state")
        if r_state in ("RESERVED", "WAITING"):
            occ_ep, occ_str, est = resolve_occurred_time(task, env)
            return {
                "category": AnomalyCategory.EXECUTION_FAILURE.value, "cause_code": "RECOVERY_QUEUED_WAITING",
                "cause_title": "已入队恢复批次，等待执行条件启动", "stage": resolve_stage_label(task),
                "reason_summary": str(latest.get("reason") or "已入队恢复，尚未完成执行"), "occurred_epoch": occ_ep, "occurred_at": occ_str, "time_estimated": est,
                "latest_progress": f"恢复项状态 {r_state}（入队未完成≠已恢复）", "handling_state": HandlingState.QUEUED.value,
                "next_step": "等待恢复监督器执行", "action_kind": "none", "unresolved": True, "is_system_fault": True, "is_stalled": False, "is_recovered": False,
            }
        if r_state == "SKIPPED" and (latest.get("op_state") in ("COMPLETED", "CANCELLED", None) or not env.recovery_worker_lock_held):
            upd_ep = float(latest.get("updated") or env.now_epoch)
            reason = str(latest.get("reason") or "预览后任务已变化，未执行")
            return {
                "category": AnomalyCategory.FLOW_STALL.value, "cause_code": "RECOVERY_SKIPPED_SUPERVISOR_STOPPED",
                "cause_title": "恢复已入队，因任务变化被跳过且监督已停止", "stage": "发布恢复 (PUBLISHING_RECOVERY)",
                "reason_summary": f"恢复项被跳过（{reason}），恢复批次已结束且监督进程已退出", "occurred_epoch": upd_ep, "occurred_at": format_bj_timestamp(upd_ep), "time_estimated": False,
                "latest_progress": f"恢复项 SKIPPED（{reason}）；批次 {latest.get('op_state') or 'COMPLETED'}", "handling_state": HandlingState.MANUAL_REQUIRED.value,
                "next_step": "重新生成恢复预览并入队", "action_kind": "open_recovery_preview", "unresolved": True, "is_system_fault": True, "is_stalled": True, "is_recovered": False,
            }
    if extract_tail_error_signature(task)[0] == AnomalyCategory.QUALITY_POLICY_BLOCK.value:
        return _evaluate_failure_or_recovery(task, env, thresholds)
    return _evaluate_block_and_stall(task, env, thresholds, active, age)


def _evaluate_block_and_stall(
    task: TaskUnitFacts, env: RuntimeEnvironmentFacts, thresholds: DiagnosisThresholds, active: bool, age: float
) -> Optional[dict[str, Any]]:
    """评估依赖阻塞、预提交孤儿、错过可执行窗口停滞与常规异常。"""
    occ_ep, occ_str, est = resolve_occurred_time(task, env)
    if task.status == "LOGIN_REQUIRED" or (task.preparation_ready and not env.wechat_login_valid):
        return {
            "category": AnomalyCategory.DEPENDENCY_BLOCK.value, "cause_code": "WECHAT_LOGIN_REQUIRED",
            "cause_title": "视频号登录态失效需重新扫码授权", "stage": "登录授权门禁 (LOGIN_REQUIRED)",
            "reason_summary": task.error_msg or "微信会话已过期或要求重新扫码", "occurred_epoch": occ_ep, "occurred_at": occ_str, "time_estimated": est,
            "latest_progress": "等待扫码恢复会话", "handling_state": HandlingState.MANUAL_REQUIRED.value,
            "next_step": "扫码恢复视频号登录", "action_kind": "relogin_wechat", "unresolved": True, "is_system_fault": True, "is_stalled": False, "is_recovered": False,
        }
    sub_next = float((task.subtitle_recovery or {}).get("next_attempt_at") or 0)
    backoff_until = max(float(task.upload_retry_next_epoch or 0), float(task.copywriter_next_epoch or 0), sub_next, float(env.wechat_cooldown_until_epoch or 0))
    if task.status == "WECHAT_DEFERRED" or (backoff_until > env.now_epoch and task.status not in ("PUBLISHED", "SUBMITTED_BOUND")):
        until_bj = format_bj_timestamp(backoff_until) if backoff_until > env.now_epoch else "恢复开启后"
        return {
            "category": AnomalyCategory.DEPENDENCY_BLOCK.value, "cause_code": "DEPENDENCY_COOLDOWN_BACKOFF",
            "cause_title": "服务配额/微信频控退避冷却等待", "stage": resolve_stage_label(task),
            "reason_summary": env.wechat_cooldown_reason or task.error_msg or f"处于退避冷却期，预计 {until_bj} 后可继续", "occurred_epoch": occ_ep, "occurred_at": occ_str, "time_estimated": est,
            "latest_progress": f"等待退避至 {until_bj}", "handling_state": HandlingState.WAITING_CONDITION.value,
            "next_step": f"等待 {until_bj} 自动恢复", "action_kind": "none", "unresolved": True, "is_system_fault": True, "is_stalled": False, "is_recovered": False,
        }
    if task.status in ("PROCESSING", "PUBLISH_PRECHECK", "DOWNLOADING", "COPYWRITING", "TRANSCRIBING", "RENDERING") and not active and age >= thresholds.pre_submission_orphan_seconds:
        return {
            "category": AnomalyCategory.FLOW_STALL.value, "cause_code": "PRE_SUBMISSION_ORPHAN_STALL",
            "cause_title": f"{resolve_stage_label(task)}进程孤儿中断/超时停滞", "stage": resolve_stage_label(task),
            "reason_summary": f"任务无活跃锁且超过 {thresholds.pre_submission_orphan_seconds // 60} 分钟无进度更新", "occurred_epoch": occ_ep, "occurred_at": occ_str, "time_estimated": est,
            "latest_progress": f"已停滞 {int(age // 60)} 分钟（无活跃进程）", "handling_state": HandlingState.UNHANDLED.value,
            "next_step": "触发任务重试或回收", "action_kind": "retry_task", "unresolved": True, "is_system_fault": True, "is_stalled": True, "is_recovered": False,
        }
    qualified = task.score >= task.qualified_score_line or task.preparation_ready
    if task.status == "PENDING" and task.source != "DISCOVERY" and qualified and not (task.censor_tag and not task.bypass_censorship) and not task.publication_review_required:
        if env.wechat_publishing_paused or not env.runtime_available or env.in_market_guard_window or not env.in_public_publish_window or env.pipeline_lock_held or env.wechat_browser_lock_held:
            return None
        window_age = env.now_epoch - env.executable_window_started_epoch if env.executable_window_started_epoch is not None else 0
        if min(age, window_age) >= thresholds.missed_window_stall_seconds:
            hb_stale = env.ready_supervisor_heartbeat_age_sec is not None and env.ready_supervisor_heartbeat_age_sec >= thresholds.ready_supervisor_heartbeat_stale_seconds
            reason = "发布监督器心跳陈旧，可执行窗口内未拉起任务" if hb_stale else "当前处于可执行窗口且无锁占用，超过调度周期仍未启动"
            return {
                "category": AnomalyCategory.FLOW_STALL.value, "cause_code": "MISSED_EXECUTABLE_WINDOW_STALL",
                "cause_title": "错过可执行窗口后仍未启动（流程停滞）", "stage": "排队调度 (PENDING)",
                "reason_summary": reason, "occurred_epoch": occ_ep, "occurred_at": occ_str, "time_estimated": est,
                "latest_progress": f"可执行窗口内已静默等待 {int(min(age, window_age) // 60)} 分钟", "handling_state": HandlingState.UNHANDLED.value,
                "next_step": "检查调度监督器或手动触发", "action_kind": "trigger_scheduler", "unresolved": True, "is_system_fault": True, "is_stalled": True, "is_recovered": False,
            }
    return None


def _evaluate_failure_or_recovery(
    task: TaskUnitFacts, env: RuntimeEnvironmentFacts, thresholds: DiagnosisThresholds
) -> Optional[dict[str, Any]]:
    """评估常规执行失败、策略拦截或曾发生异常但现已恢复的任务。"""
    occ_ep, occ_str, est = resolve_occurred_time(task, env)
    sub = task.subtitle_recovery or {}
    is_policy = (
        bool(task.censor_tag and not task.bypass_censorship)
        or task.publication_review_required
        or "Channel Policy Reject" in (task.error_msg or "")
        or "Social Unrest Review" in (task.error_msg or "")
        or "点赞率须严格" in (task.publication_wait_reason or "")
    )
    if task.status == "FAILED" or is_policy or str(sub.get("state") or "") in ("NEEDS_REPAIR", "FAILED"):
        cat, code, title, summary = extract_tail_error_signature(task)
        is_sys = cat != AnomalyCategory.QUALITY_POLICY_BLOCK.value
        h_state = HandlingState.MANUAL_REQUIRED.value if (not is_sys or str(sub.get("state") or "") == "NEEDS_REPAIR") else HandlingState.UNHANDLED.value
        next_step = "人工复核/授权豁免" if not is_sys else ("修复字幕并释放" if "SUBTITLE_REPAIR" in code else "查看错误摘要并受控重试")
        act = "review_policy" if not is_sys else ("repair_subtitle" if "SUBTITLE_REPAIR" in code else "retry_task")
        if is_sys and is_task_actively_running(task, env, thresholds):
            h_state, next_step, act = HandlingState.RUNNING.value, "观察当前任务进度，勿并发重试", "none"
        return {
            "category": cat, "cause_code": code, "cause_title": title, "stage": resolve_stage_label(task), "reason_summary": summary,
            "occurred_epoch": occ_ep, "occurred_at": occ_str, "time_estimated": est, "latest_progress": f"状态 {task.status} · {HANDLING_STATE_LABELS[h_state]}",
            "handling_state": h_state, "next_step": next_step, "action_kind": act, "unresolved": True, "is_system_fault": is_sys,
            "is_stalled": cat == AnomalyCategory.FLOW_STALL.value, "is_recovered": False,
        }
    if not (task.failure_events or task.retry_count > 0 or task.subtitle_recovery or task.recovery_items):
        return None
    active = is_task_actively_running(task, env, thresholds)
    completed = has_recovery_completion_proof(task, env.now_epoch)
    delivered = resolve_delivery_state(task) == DeliveryState.PUBLIC_CONFIRMED.value
    if not completed:
        h_state = HandlingState.RUNNING.value if active else HandlingState.MANUAL_REQUIRED.value
        return {
            "category": AnomalyCategory.EXECUTION_FAILURE.value, "cause_code": "RECOVERY_IN_PROGRESS" if active else "RECOVERY_EVIDENCE_UNVERIFIED",
            "cause_title": "恢复执行中，故障解除待核实" if active else "存在重试历史，故障解除尚未核实", "stage": resolve_stage_label(task),
            "reason_summary": "当前有运行观测，不能据此认定恢复成功" if active else "缺少晚于最后失败的恢复完成证据",
            "occurred_epoch": occ_ep, "occurred_at": occ_str, "time_estimated": est,
            "latest_progress": f"当前状态 {task.status} · 故障解除待核实", "handling_state": h_state,
            "next_step": "观察当前任务进度" if active else "核查恢复记录与当前阻塞", "action_kind": "none",
            "unresolved": True, "is_system_fault": True, "is_stalled": False, "is_recovered": False,
        }
    h_state = HandlingState.RECOVERED_COMPLETED.value if delivered else HandlingState.RECOVERED_PENDING_DELIVERY.value
    return {
        "category": AnomalyCategory.EXECUTION_FAILURE.value, "cause_code": h_state,
        "cause_title": "故障已恢复，公开交付已核实" if delivered else "故障已恢复，交付未完成", "stage": resolve_stage_label(task),
        "reason_summary": "已取得晚于最后失败的恢复完成证据；公开交付另行核实",
        "occurred_epoch": occ_ep, "occurred_at": occ_str, "time_estimated": est, "latest_progress": f"当前状态 {task.status} · {HANDLING_STATE_LABELS[h_state]}",
        "handling_state": h_state, "next_step": "无需操作" if delivered else "核查后续交付进度", "action_kind": "none",
        "unresolved": False, "is_system_fault": False, "is_stalled": False, "is_recovered": True,
    }


def _observation_unknown(task: TaskUnitFacts, env: RuntimeEnvironmentFacts) -> dict[str, Any]:
    ep, label, estimated = resolve_occurred_time(task, env)
    return {
        "category": AnomalyCategory.OBSERVATION_ANOMALY.value, "cause_code": "RUNTIME_OBSERVATION_UNAVAILABLE",
        "cause_title": "运行观测不可用", "stage": resolve_stage_label(task), "reason_summary": "无法可靠读取当前任务租约或进度，不能判定孤儿或恢复成功",
        "occurred_epoch": ep, "occurred_at": label, "time_estimated": estimated, "latest_progress": "任务运行状态未知",
        "handling_state": HandlingState.MANUAL_REQUIRED.value, "next_step": "恢复只读观测后重新核查", "action_kind": "none",
        "unresolved": True, "is_system_fault": True, "is_stalled": False, "is_recovered": False,
    }


def diagnose_task_unit(
    task: TaskUnitFacts,
    env: RuntimeEnvironmentFacts,
    thresholds: Optional[DiagnosisThresholds] = None,
) -> Optional[TaskAnomalyDiagnosis]:
    """对单个任务单元执行纯规则异常诊断；正常排队/正常执行中且无历史异常时返回 None。"""
    cfg = thresholds or DiagnosisThresholds()
    matched = _evaluate_special_states(task, env, cfg) or _evaluate_failure_or_recovery(task, env, cfg)
    if not matched:
        return None
    occ_ep = float(matched["occurred_epoch"])
    ev_count = max(
        len(task.failure_events)
        + sum(1 for i in task.recovery_items if i.get("state") in ("SKIPPED", "FAILED", "ATTENTION"))
        + (int(task.subtitle_recovery.get("attempt_count") or 1) if task.subtitle_recovery else 0),
        1,
    )
    cat = matched["category"]
    h_state = matched["handling_state"]
    return TaskAnomalyDiagnosis(
        video_id=task.video_id, family_root_id=task.parent_id or task.video_id,
        youtube_id=task.youtube_id, slice_index=task.slice_index, title=task.title, channel_id=task.channel_id,
        ingested_at=format_bj_timestamp(task.created_epoch, task.created_at),
        category=cat, category_label=CATEGORY_LABELS.get(cat, cat),
        cause_code=matched["cause_code"], cause_title=matched["cause_title"],
        stage=matched["stage"], reason_summary=matched["reason_summary"],
        occurred_at=matched["occurred_at"], occurred_epoch=occ_ep,
        duration_seconds=round(max(0.0, float(env.now_epoch) - occ_ep), 1),
        time_estimated=bool(matched["time_estimated"]), latest_progress=matched["latest_progress"],
        handling_state=h_state, handling_state_label=HANDLING_STATE_LABELS.get(h_state, h_state),
        delivery_state=resolve_delivery_state(task),
        unresolved=bool(matched["unresolved"]), is_system_fault=bool(matched["is_system_fault"]),
        is_stalled=bool(matched["is_stalled"]), is_uncertain_delivery=(cat == AnomalyCategory.DELIVERY_UNVERIFIED.value),
        is_recovered=bool(matched["is_recovered"]), event_count=ev_count,
        next_step=matched["next_step"], action_kind=matched["action_kind"],
        sanitized_error_excerpt=sanitize_error_excerpt(task.error_msg),
        status=task.status, has_active_task_lock=task.has_active_task_lock, process_alive=task.process_alive,
        runtime_observed_at_bj=task.runtime_observed_at_bj or env.now_bj_iso,
        runtime_observation_available=task.runtime_observation_available,
    )
