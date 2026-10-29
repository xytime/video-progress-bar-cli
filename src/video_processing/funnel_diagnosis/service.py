"""入库批次流程概览与异常诊断服务层门面（Facade）。

封装 DAL 数据读取、运行态探针采集、三层异常规则判定与证据链组装，为 Web API 与 CLI
提供统一、无副作用的只读序列化字典。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.2.0 | 2026-10-29 | Codex | 区分读取失败与真实空集，注入集中配置阈值，保守呈现未命中规则的任务证据。 |
| 1.1.0 | 2026-10-29 | Antigravity | 修复任务反查匹配回退缺陷（不匹配严格返回 None 防串话）、支持 video_id 整数规整、补充非异常任务平台回执与诊断频道名称。 |
| 1.0.0 | 2026-10-29 | Antigravity | 初始创建服务层门面，解耦 Web 路由与底层诊断/探针逻辑。 |
"""
from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Optional, Sequence

from ..core.runtime_probe import (
    enrich_cohort_tasks_with_runtime,
    enrich_task_facts_with_runtime,
    probe_runtime_environment,
)
from config.settings import settings

from .models import DiagnosisThresholds, TaskUnitFacts
from .narrative import attach_task_evidence, evaluate_cohort_diagnosis
from .rules import diagnose_task_unit, format_bj_timestamp, resolve_delivery_state

_VALID_WINDOWS = frozenset({"24h", "today_bj", "7d", "30d", "all"})


class DiagnosisUnavailable(RuntimeError):
    """关键诊断事实不可读取；禁止将失败降级为正常空集。"""

    detail = {
        "code": "FUNNEL_DIAGNOSIS_UNAVAILABLE",
        "message": "诊断数据暂不可用，请稍后重试。",
    }


def _diagnosis_thresholds() -> DiagnosisThresholds:
    """从配置单一来源注入领域规则，避免环境配置与展示脱节。"""
    return DiagnosisThresholds(
        pre_submission_orphan_seconds=settings.pre_submission_orphan_seconds,
        publishing_orphan_seconds=settings.publishing_orphan_seconds,
        caption_progress_stale_seconds=settings.caption_progress_stale_seconds,
        missed_window_stall_seconds=settings.missed_window_stall_seconds,
        ready_supervisor_heartbeat_stale_seconds=settings.ready_supervisor_heartbeat_stale_seconds,
        queue_stale_days=settings.queue_stale_days,
    )


def _probe_environment(out_dir: Path) -> Any:
    """运行态来源不可观测时返回不可用，禁止用默认空锁推断正常。"""
    env = probe_runtime_environment(output_dir=out_dir)
    if not env.runtime_available:
        raise DiagnosisUnavailable("Runtime evidence is unavailable")
    return env


def _read_task_facts(db: Any, names: Sequence[str], *args: Any, **kwargs: Any) -> list[TaskUnitFacts]:
    """关键 DAL 读取失败显式上抛；只有合法的空列表表示真实空集。"""
    getter = next((getattr(db, name, None) for name in names if callable(getattr(db, name, None))), None)
    if getter is None:
        raise DiagnosisUnavailable("Diagnosis DAL is unavailable")
    try:
        facts = getter(*args, **kwargs)
        if not isinstance(facts, (list, tuple)) or any(not isinstance(t, TaskUnitFacts) for t in facts):
            raise ValueError("Invalid task facts")
        score_lines = settings.auto_publish_channel_min_scores
        return [replace(task, qualified_score_line=score_lines.get(task.channel_id, task.qualified_score_line))
                for task in facts]
    except Exception as exc:
        raise DiagnosisUnavailable("Diagnosis DAL read failed") from exc


def _normalize_window(window: Optional[str]) -> str:
    """规整时间窗口参数，非法或缺省值回退为 today_bj。"""
    if not window or not isinstance(window, str):
        return "today_bj"
    cleaned = window.strip().lower()
    return cleaned if cleaned in _VALID_WINDOWS else "today_bj"


def _normalize_channel(channel: Optional[str]) -> Optional[str]:
    """规整频道筛选参数，通配符或空值视作全站。"""
    if not channel or not isinstance(channel, str):
        return None
    cleaned = channel.strip()
    return None if cleaned in ("all", "*", "") else cleaned


def _fetch_cohort_tasks(
    db: Any, window: str, channel: Optional[str]
) -> list[TaskUnitFacts]:
    """通过 DAL 获取批次任务事实列表（兼容 get_cohort_task_facts 与 get_funnel_cohort_task_facts）。"""
    return _read_task_facts(
        db, ("get_cohort_task_facts", "get_funnel_cohort_task_facts"),
        window=window, channel_id=channel,
    )


def _fetch_task_family(db: Any, video_id: Any) -> list[TaskUnitFacts]:
    """通过 DAL 获取单任务所属主任务族的全部任务事实。"""
    try:
        vid = int(video_id)
        if isinstance(video_id, bool) or vid <= 0:
            return []
    except (ValueError, TypeError):
        return []
    return _read_task_facts(
        db, ("get_funnel_task_family_facts_by_ids", "get_task_family_facts_by_ids"), [vid],
    )


def _build_non_anomalous_evidence(enriched: TaskUnitFacts) -> dict[str, Any]:
    """为无异常任务构建标准只读证据快照。"""
    c_time = format_bj_timestamp(enriched.created_epoch, enriched.created_at)
    d_state = resolve_delivery_state(enriched)
    facts: list[str] = [
        f"入库时间：{c_time}",
        f"当前状态：{enriched.status}（未触发现有异常规则）",
        f"交付状态：{d_state}",
    ]
    pub = enriched.wechat_publication or {}
    if pub.get("platform_post_id"):
        facts.append(f"平台回执：已绑定 {pub.get('platform_post_id')} (状态={pub.get('state')})")
    elif enriched.submission_attempts:
        facts.append(f"平台回执：无公开 export/ 凭证 (尝试次数={len(enriched.submission_attempts)})")
    if enriched.has_active_task_lock:
        owner = enriched.task_lock_owner or {}
        facts.append(f"任务锁：持有中 ({owner.get('stage') or '加工'} pid={owner.get('pid')})")
    return {
        "video_id": enriched.video_id,
        "youtube_id": enriched.youtube_id,
        "slice_index": enriched.slice_index,
        "title": enriched.title,
        "channel_id": enriched.channel_id,
        "channel_name": enriched.channel_name,
        "status": enriched.status,
        "score": enriched.score,
        "delivery_state": d_state,
        "is_anomalous": False,
        "diagnosis": None,
        "evidence": {
            "facts": facts,
            "inferences": ["当前证据未触发现有异常规则；公开可见性以独立回读结果为准。"],
            "recommendations": ["继续观察任务与平台回执；证据不足时先核对，禁止盲目重投。"],
            "sanitized_error_excerpt": "",
        },
        "runtime": {
            "runtime_observation_available": enriched.runtime_observation_available,
            "runtime_observed_at_bj": enriched.runtime_observed_at_bj,
            "process_alive": enriched.process_alive,
            "process_pid": enriched.process_pid,
            "has_active_task_lock": enriched.has_active_task_lock,
            "task_lock_owner": dict(enriched.task_lock_owner or {}),
            "caption_stage": enriched.caption_stage,
        },
    }


def _build_anomalous_evidence(
    enriched: TaskUnitFacts, diag: Any
) -> dict[str, Any]:
    """为异常诊断任务构建包含事实/推测/建议三元组的序列化字典。"""
    return {
        "video_id": enriched.video_id,
        "youtube_id": enriched.youtube_id,
        "slice_index": enriched.slice_index,
        "title": enriched.title,
        "channel_id": enriched.channel_id,
        "channel_name": enriched.channel_name,
        "status": enriched.status,
        "score": enriched.score,
        "delivery_state": diag.delivery_state,
        "is_anomalous": True,
        "diagnosis": asdict(diag),
        "evidence": {
            "facts": list(diag.facts),
            "inferences": list(diag.inferences),
            "recommendations": list(diag.recommendations),
            "sanitized_error_excerpt": diag.sanitized_error_excerpt,
        },
        "runtime": {
            "runtime_observation_available": enriched.runtime_observation_available,
            "runtime_observed_at_bj": enriched.runtime_observed_at_bj,
            "process_alive": enriched.process_alive,
            "process_pid": enriched.process_pid,
            "has_active_task_lock": enriched.has_active_task_lock,
            "task_lock_owner": dict(enriched.task_lock_owner or {}),
            "caption_stage": enriched.caption_stage,
        },
    }


def get_funnel_diagnosis_payload(
    db: Any,
    out_dir: Path,
    window: str = "today_bj",
    channel: Optional[str] = None,
) -> dict[str, Any]:
    """按入库批次窗口与可选频道获取三层异常诊断只读序列化结果。"""
    win = _normalize_window(window)
    ch = _normalize_channel(channel)
    raw_tasks = _fetch_cohort_tasks(db, window=win, channel=ch)
    channel_name: Optional[str] = None
    if ch and db is not None:
        ch_getter = getattr(db, "get_channel_by_id", None)
        if callable(ch_getter):
            try:
                ch_info = ch_getter(ch)
                if isinstance(ch_info, dict):
                    channel_name = ch_info.get("channel_name") or ch
            except Exception:
                pass
    try:
        env = _probe_environment(out_dir)
        enriched_tasks = enrich_cohort_tasks_with_runtime(raw_tasks, output_dir=out_dir)
        eval_res = evaluate_cohort_diagnosis(enriched_tasks, env, _diagnosis_thresholds())
    except Exception as exc:
        raise DiagnosisUnavailable("Diagnosis runtime read failed") from exc
    return {
        "success": True,
        "window": win,
        "channel_id": ch,
        "channel_name": channel_name,
        "as_of_bj": eval_res["as_of_bj"],
        "summary": eval_res["summary"],
        "causes": [asdict(c) for c in eval_res["causes"]],
        "tasks": [asdict(t) for t in eval_res["tasks"]],
    }


def get_funnel_task_evidence_payload(
    db: Any,
    out_dir: Path,
    video_id: Any,
) -> Optional[dict[str, Any]]:
    """获取单任务事实、推测与建议三元组异常证据链与运行态快照（不存在返回 None）。"""
    try:
        vid = int(video_id)
        if isinstance(video_id, bool) or vid <= 0:
            return None
    except (ValueError, TypeError):
        return None
    family = _fetch_task_family(db, video_id=vid)
    if not family:
        return None
    target = next((t for t in family if t.video_id == vid), None)
    if target is None:
        return None
    try:
        env = _probe_environment(out_dir)
        enriched = enrich_task_facts_with_runtime(target, output_dir=out_dir)
        diag = diagnose_task_unit(enriched, env, _diagnosis_thresholds())
    except Exception as exc:
        raise DiagnosisUnavailable("Diagnosis runtime read failed") from exc
    if diag is not None:
        diag = attach_task_evidence(enriched, diag, env)
        return _build_anomalous_evidence(enriched, diag)
    return _build_non_anomalous_evidence(enriched)
