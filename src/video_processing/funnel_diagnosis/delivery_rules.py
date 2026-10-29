"""交付证据与时间规范化纯函数；账本身份绑定不等于公开可见。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-29 | Codex | 集中提交待核优先级、独立公开证据与故障解除证据校验。 |
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Optional

from .models import DeliveryState, TaskUnitFacts

_BJ_TZ = timezone(timedelta(hours=8))
_UNCERTAIN_STATES = {"UNCERTAIN", "NOT_FOUND", "SUBMITTED_UNBOUND", "MANUAL_CONFIRMATION_REQUIRED"}
_BOUND_STATES = {"PUBLISHED", "UNDER_REVIEW", "SUBMITTED_BOUND", "CONFIRMED"}


def evidence_epoch(value: object) -> Optional[float]:
    """SQLite 无时区时间按 UTC；带时区 ISO 保留来源时区。无效值明确未知。"""
    if value is None or value == "":
        return None
    try:
        number = float(value)
        return number if isfinite(number) else None
    except (ValueError, TypeError):
        try:
            raw = str(value).strip()
            dt = datetime.fromisoformat(raw.removesuffix(" BJ").replace("Z", "+00:00"))
            tz = _BJ_TZ if raw.endswith(" BJ") else timezone.utc
            return dt.replace(tzinfo=tz).timestamp() if dt.tzinfo is None else dt.timestamp()
        except (ValueError, TypeError, OverflowError):
            return None


def format_bj_timestamp(epoch: Optional[float], fallback_iso: str = "") -> str:
    ep = evidence_epoch(epoch if epoch is not None else fallback_iso)
    try:
        return datetime.fromtimestamp(ep, tz=_BJ_TZ).strftime("%Y-%m-%d %H:%M:%S BJ") if ep is not None else "未知时间"
    except (ValueError, OverflowError, OSError):
        return "未知时间"


def has_unresolved_submission(task: TaskUnitFacts) -> bool:
    """任何未绑定或冲突提交账本优先于主任务状态；不得推导可重投。"""
    if task.status in _UNCERTAIN_STATES or str((task.wechat_publication or {}).get("state") or "") in _UNCERTAIN_STATES:
        return True
    if any(str(a.get("state") or "") != "PLATFORM_ID_BOUND" or not a.get("platform_post_id") for a in task.submission_attempts):
        return True
    if any(item.get("state") == "SUBMITTED_UNVERIFIED" for item in task.recovery_items):
        return True
    return any(d.get("kind") == "WECHAT_UNKNOWN" and d.get("state") == "WAITING" for d in task.delivery_recoveries)


def has_submission_evidence(task: TaskUnitFacts) -> bool:
    return bool(task.wechat_publication or task.submission_attempts or task.status in _BOUND_STATES or task.status in _UNCERTAIN_STATES
                or any(item.get("state") in {"PUBLISHED", "SUBMITTED_UNVERIFIED"} for item in task.recovery_items))


def has_public_visibility_proof(task: TaskUnitFacts) -> bool:
    """只接受带任务/平台身份、来源、观测时间的独立公开回读，账本本身无此能力。"""
    proof, pub = task.public_visibility_evidence or {}, task.wechat_publication or {}
    if has_unresolved_submission(task) or str(pub.get("state") or "") in {"REJECTED", "UNDER_REVIEW", "NOT_FOUND"}:
        return False
    post_id = str(pub.get("platform_post_id") or "")
    observed = evidence_epoch(proof.get("observed_at"))
    snapshot = evidence_epoch(task.runtime_observed_at_bj)
    latest_pub = evidence_epoch(pub.get("last_reconciled_at") or pub.get("updated_at"))
    return bool(
        proof.get("public_visible") is True and proof.get("video_id") == task.video_id
        and proof.get("source") in {"independent_public_readback", "public_page_readback"}
        and post_id and proof.get("platform_post_id") == post_id and proof.get("public_url")
        and observed is not None and snapshot is not None and observed <= snapshot
        and (latest_pub is None or observed >= latest_pub)
    )


def resolve_delivery_state(task: TaskUnitFacts) -> str:
    if has_unresolved_submission(task):
        return DeliveryState.DELIVERY_UNCERTAIN.value
    if has_public_visibility_proof(task):
        return DeliveryState.PUBLIC_CONFIRMED.value
    pub = task.wechat_publication or {}
    if str(pub.get("state") or "") == "REJECTED":
        return DeliveryState.DELIVERY_UNKNOWN.value
    if str(pub.get("state") or "") in _BOUND_STATES or task.status in {"SUBMITTED_BOUND", "UNDER_REVIEW"}:
        return DeliveryState.PLATFORM_ACCEPTED.value
    if task.status == "PUBLISHED":
        return DeliveryState.LOCAL_DONE_UNVERIFIED.value
    if task.submission_attempts:
        return DeliveryState.PLATFORM_ACCEPTED.value
    if any(item.get("state") == "PUBLISHED" for item in task.recovery_items):
        return DeliveryState.LOCAL_DONE_UNVERIFIED.value
    return DeliveryState.LOCAL_READY.value if task.preparation_ready else DeliveryState.IN_PREPARATION.value


def latest_failure_epoch(task: TaskUnitFacts) -> Optional[float]:
    values = [evidence_epoch(task.failed_epoch or task.failed_at)]
    values += [evidence_epoch(e.get("failed_epoch") or e.get("failed_at")) for e in task.failure_events]
    return max((v for v in values if v is not None), default=None)


def has_recovery_completion_proof(task: TaskUnitFacts, now_epoch: float) -> bool:
    """仅明确完成且晚于最后失败的恢复证据证明解除；retry_count/持锁不证明成功。"""
    failed = latest_failure_epoch(task)
    if failed is None:
        return False
    subtitle = task.subtitle_recovery or {}
    resolved = evidence_epoch(subtitle.get("updated_at"))
    if subtitle.get("state") == "RESOLVED" and resolved is not None and failed < resolved <= now_epoch:
        return True
    for record in task.recovery_items:
        completed = evidence_epoch(record.get("updated"))
        if record.get("state") == "PUBLISHED" and completed is not None and failed < completed <= now_epoch:
            return True
    return False
