"""视频号互动单次 worker 状态机。

只协调 DAL 与已注入的生成/浏览器/通知门面；不读环境变量、不自行连接平台，
也不含 SQL。一次调用最多消费一条任务。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-19 | Codex | 建立有界 tick、提交意图 callback 与 UNCERTAIN 只读回查协议。 |
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Protocol

from video_processing.db.database import PipelineDB

logger = logging.getLogger(__name__)


class InteractionWorkerServices(Protocol):
    """生成、浏览器和通知的窄门面，测试只需注入一个替身。"""

    def generate_comment(self, target: Mapping[str, Any], *, force_rule: bool) -> Any: ...

    def post_comment(
        self,
        *,
        comment_text: str,
        platform_post_id: str,
        video_title: Optional[str],
        evidence_dir: Path,
        before_submit: Optional[Callable[[], bool]],
        verify_only: bool,
    ) -> tuple[str, Optional[str], Optional[str]]: ...

    def notify_result(
        self,
        target: Mapping[str, Any],
        interaction: Mapping[str, Any],
        final_record: Mapping[str, Any],
    ) -> None: ...


@dataclass(frozen=True)
class InteractionTickResult:
    """单次 worker 的可观测结果。"""

    status: str
    platform_post_id: Optional[str] = None
    interaction_id: Optional[int] = None
    detail: Optional[str] = None


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _select_target(
    db: PipelineDB,
    *,
    platform_post_id: Optional[str],
    video_id: Optional[int],
) -> Optional[dict]:
    if platform_post_id:
        return db.get_published_wechat_post_by_platform_id(platform_post_id)
    if video_id is not None:
        return db.get_published_wechat_post_by_video_id(video_id)
    return db.get_wechat_interaction_discovery_candidate()


def run_interaction_tick(
    db: PipelineDB,
    services: InteractionWorkerServices,
    *,
    platform_post_id: Optional[str] = None,
    video_id: Optional[int] = None,
    force_rule: bool = False,
    dry_run: bool = False,
    reconcile_only: bool = False,
    clock: Callable[[], datetime.datetime] = _utc_now,
    evidence_root: Optional[Path] = None,
) -> InteractionTickResult:
    """发现/建账并最多执行一条到期任务。"""
    if platform_post_id and video_id is not None:
        raise ValueError("platform_post_id and video_id are mutually exclusive")
    if reconcile_only and (platform_post_id or video_id is not None or dry_run):
        raise ValueError("reconcile_only cannot be combined with an explicit target or dry_run")
    explicit_target = bool(platform_post_id or video_id is not None)
    claimed = None
    # 自动 tick 先消费已持久的到期任务，不让最新作品或无新作品
    # 的情形把历史 UNCERTAIN/退避任务永久饥饿。
    if not explicit_target and not dry_run:
        claimed = db.claim_due_wechat_interaction(
            now=clock(), verify_only_only=reconcile_only
        )
        if reconcile_only and claimed is None:
            return InteractionTickResult(
                status="NO_WORK", detail="无到期 UNCERTAIN 只读回查任务"
            )
    target = dict(claimed) if claimed else _select_target(
        db, platform_post_id=platform_post_id, video_id=video_id
    )
    if not target:
        return InteractionTickResult(
            status="NO_WORK",
            platform_post_id=platform_post_id,
            detail="无严格 PUBLISHED 目标或显式目标不可用",
        )

    post_id = str(target["platform_post_id"])
    existing = db.get_wechat_interaction_by_post_id(post_id)
    draft = None
    if existing is None:
        draft = services.generate_comment(target, force_rule=force_rule)
        comment_text = str(draft.formatted_comment).strip()
        if dry_run:
            return InteractionTickResult(
                status="DRY_RUN", platform_post_id=post_id, detail=comment_text
            )
        existing = db.queue_wechat_interaction(
            publication_id=int(target["publication_id"]),
            platform_post_id=post_id,
            interaction_type=str(draft.interaction_type.value),
            provider=str(draft.provider),
            comment_text=comment_text,
            now=clock(),
        )
    elif dry_run:
        return InteractionTickResult(
            status="DRY_RUN",
            platform_post_id=post_id,
            interaction_id=int(existing["id"]),
            detail=str(existing["comment_text"]),
        )

    if claimed is None:
        claimed = db.claim_due_wechat_interaction(
            now=clock(), platform_post_id=post_id
        )
    if not claimed:
        current = db.get_wechat_interaction_by_post_id(post_id)
        return InteractionTickResult(
            status="NOT_DUE",
            platform_post_id=post_id,
            interaction_id=int(current["id"]) if current else None,
            detail=str(current["status"]) if current else None,
        )

    interaction_id = int(claimed["id"])
    lease_token = str(claimed["lease_token"])
    verify_only = bool(claimed.get("verify_only"))
    prefix = str(claimed.get("youtube_id") or post_id).replace("/", "_")
    root = evidence_root or (
        Path(__file__).resolve().parents[3]
        / "output" / "wechat_evidence" / "interactions"
    )

    def persist_submit_intent() -> bool:
        return db.mark_wechat_interaction_submit_intent(
            interaction_id, lease_token, now=clock()
        )

    status, evidence_path, error_message = services.post_comment(
        comment_text=str(claimed["comment_text"]),
        platform_post_id=post_id,
        video_title=str(claimed.get("zh_title") or claimed.get("title") or "") or None,
        evidence_dir=root / prefix,
        before_submit=None if verify_only else persist_submit_intent,
        verify_only=verify_only,
    )
    final_record = db.finish_wechat_interaction_attempt(
        interaction_id,
        lease_token,
        result_status=status,
        evidence_path=evidence_path,
        error_message=error_message,
        now=clock(),
    )
    try:
        services.notify_result(target, claimed, final_record)
    except Exception as exc:  # 通知失败不改写平台事实
        logger.warning("视频号互动结果通知失败: %s", exc)
    return InteractionTickResult(
        status=str(final_record["status"]),
        platform_post_id=post_id,
        interaction_id=interaction_id,
        detail=error_message,
    )
