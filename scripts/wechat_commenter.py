#!/usr/bin/env python3
"""WeChat Channels Automated Interaction Commenter CLI.

独立 CLI 脚本，用于为近期发布的视频号作品发表互动引导首评。
支持动态选题决策、自生长兜底机制、浏览器防重发评及 Telegram 审计图文通知。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-09-19 | Antigravity | 阻断性修复：严禁构造伪目标，增加已发布精准校验、pipeline.lock避让互斥、发评成功后才触发自生长学习 |
| 1.0.0 | 2026-09-19 | Antigravity | 初始创建：实现低耦合高内聚的独立发评 CLI |
"""

from __future__ import annotations

import argparse
import fcntl
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# 确保 src 在模块搜索路径内
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from config.settings import settings
from video_processing.db.database import PipelineDB
from video_processing.interaction import (
    BrowserCommenter,
    CensorshipViolationError,
    InteractionDraft,
    InteractionNotifier,
    InteractionService,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("wechat_commenter")


def run_interaction(
    *,
    platform_post_id: str | None = None,
    video_id: int | None = None,
    reconcile_pending: bool = False,
    force_rule: bool = False,
    dry_run: bool = False,
    headless: bool = True,
    notify_tg: bool = True,
) -> int:
    """运行一次互动发评任务。"""
    db = PipelineDB()
    service = InteractionService()
    notifier = InteractionNotifier(db=db)

    # 1. 解析目标视频（严格限定已由平台确认公开发布的作品）
    target = None

    if platform_post_id:
        target = db.get_published_wechat_post_by_platform_id(platform_post_id)
        if not target:
            logger.error("【Fail-Closed】未在数据库中找到平台状态为 PUBLISHED 的作品: %s", platform_post_id)
            return 1
    elif video_id:
        target = db.get_published_wechat_post_by_video_id(video_id)
        if not target:
            logger.error("【Fail-Closed】未在数据库中找到对应 video_id=%s 且状态为 PUBLISHED 的作品", video_id)
            return 1
    elif reconcile_pending:
        pending_candidates = db.get_pending_review_wechat_interactions(max_attempts=5, limit=5)
        if pending_candidates:
            target = pending_candidates[0]
            logger.info("选中处于 PENDING_REVIEW 的待回查作品: %s", target.get("platform_post_id"))
    else:
        candidates = db.get_recent_published_wechat_posts_without_interaction(limit=5)
        if candidates:
            target = candidates[0]

    if not target:
        logger.info("未发现待发表互动的视频号作品。")
        return 0

    post_id = str(target["platform_post_id"])
    pub_id = int(target.get("publication_id") or 0)
    title = str(target.get("zh_title") or target.get("title") or "精选视频")
    category = str(target.get("category") or "General")

    # 尝试从本地 output 目录读取更详尽的摘要描述
    yid = target.get("youtube_id", "")
    s_idx = target.get("slice_index", 0)
    prefix = f"{yid}_s{s_idx}" if s_idx else yid
    copy_path = PROJECT_ROOT / "output" / f"{prefix}_copy.txt"
    description = copy_path.read_text(encoding="utf-8") if copy_path.is_file() else title

    logger.info("目标视频: [%s] %s (类别: %s)", post_id[:16], title, category)

    # 2. 检查流水线排他锁（如果主流程正在上传或转码，主动避让退出）
    if not dry_run:
        pipeline_lock_path = PROJECT_ROOT / "output" / "pipeline.lock"
        if pipeline_lock_path.is_file():
            try:
                with open(pipeline_lock_path, "r") as pf:
                    fcntl.flock(pf, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fcntl.flock(pf, fcntl.LOCK_UN)
            except (BlockingIOError, OSError):
                logger.warning("[wechat_commenter] 主流水线当前正持有 pipeline.lock（正在上传或处理），主动避让退出。")
                return 0

    # 3. 生成互动评论（优先 AGY，失败自动降级自生长规则；全程受内容审查保护）
    try:
        draft = service.generate_comment(
            title=title,
            description=description,
            category=category,
            force_rule=force_rule,
        )
    except CensorshipViolationError as exc:
        logger.error("【内容安全阻断】互动内容生成未能通过合规审查: %s", exc)
        return 1

    logger.info("选用策略: %s (%s)", draft.interaction_type.value, draft.provider)
    logger.info("评论全文:\n%s", draft.formatted_comment)

    if dry_run:
        logger.info("[Dry Run] 演练完成，不执行浏览器提交、数据库落库与策略库沉淀。")
        return 0

    # 4. 浏览器自动化提交与平台回读
    evidence_dir = PROJECT_ROOT / "output" / "wechat_evidence" / "interactions" / prefix
    commenter = BrowserCommenter(headless=headless)
    status, evidence_path, error_msg = commenter.post_comment(
        comment_text=draft.formatted_comment,
        platform_post_id=post_id,
        video_title=title,
        evidence_dir=evidence_dir,
    )

    # 5. 记录账本
    now_str = datetime.now(timezone.utc).isoformat() if status == "COMMENTED" else None
    if pub_id > 0:
        db.record_wechat_interaction(
            publication_id=pub_id,
            platform_post_id=post_id,
            interaction_type=draft.interaction_type.value,
            provider=draft.provider,
            comment_text=draft.formatted_comment,
            status=status,
            evidence_path=evidence_path,
            error_message=error_msg,
            commented_at=now_str,
        )

    # 6. 自生长学习沉淀（严格限定：仅在真实发评成功且回读确认后才沉淀！）
    if status == "COMMENTED":
        try:
            learned = service.store.learn_from_success(draft, title)
            if learned:
                logger.info("已从本次发表成功的互动中提炼模式并沉淀入自生长库。")
        except Exception as exc:
            logger.warning("自生长经验沉淀异常: %s", exc)

    # 7. Telegram 图文汇报
    if notify_tg:
        try:
            notifier.notify_interaction_result(
                video_title=title,
                platform_post_id=post_id,
                status=status,
                draft=draft,
                evidence_path=evidence_path,
                error_message=error_msg,
            )
        except Exception as exc:
            logger.warning("Telegram 通知发送异常: %s", exc)

    logger.info("互动任务结束，状态: %s (证据: %s)", status, evidence_path)
    return 0 if status in {"COMMENTED", "SKIPPED_EXISTS"} else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="微信视频号自动化评论互动引导工具")
    parser.add_argument("--post-id", type=str, help="指定微信原生 platform_post_id（严格校验已发布）")
    parser.add_argument("--video-id", type=int, help="指定数据库 video_id（严格校验已发布）")
    parser.add_argument("--latest", action="store_true", help="处理最近一条未互动的已发布视频")
    parser.add_argument("--reconcile-pending", action="store_true", help="回查处于 PENDING_REVIEW 的待复核作品")
    parser.add_argument("--force-rule", action="store_true", help="强制使用自生长规则兜底生成（跳过 AGY）")
    parser.add_argument("--dry-run", action="store_true", help="仅生成文案演练，不启动浏览器发评且不改写知识库")
    parser.add_argument("--no-headless", action="store_true", help="以有头浏览器模式运行")
    parser.add_argument("--no-tg", action="store_true", help="跳过 Telegram 消息汇报")
    args = parser.parse_args()

    exit_code = run_interaction(
        platform_post_id=args.post_id,
        video_id=args.video_id,
        reconcile_pending=args.reconcile_pending,
        force_rule=args.force_rule,
        dry_run=args.dry_run,
        headless=not args.no_headless,
        notify_tg=not args.no_tg,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
