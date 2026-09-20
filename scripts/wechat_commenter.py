#!/usr/bin/env python3
"""视频号互动有界 worker CLI。

特性开关默认关闭；开启后每次最多发现并处理一条已确认 PUBLISHED 作品。
浏览器提交前必须由 DAL 回调持久化提交意图；之后任何不确定结果都只读回查。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 2.3.0 | 2026-09-20 | Antigravity | 放宽人工批量上限至 10 条，支持最新作品批量互动与自动收敛。 |
| 2.2.0 | 2026-09-20 | Codex | 支持仅在未持久化提交意图时审计式替换失败草稿，并从已发布文案生成唯一卡片定位提示。 |
| 2.1.0 | 2026-09-20 | Codex | 增加最多三条的人工批量入口，严格按上传记录时间选择无互动账本候选；遇到不确定或失败即停止后续提交。 |
| 2.0.0 | 2026-09-19 | Codex | 改为默认关闭、单次有界、持久状态机驱动的安全 worker。 |
| 1.1.0 | 2026-09-19 | Antigravity | 阻断性修复：严禁构造伪目标，增加已发布精准校验、pipeline.lock避让互斥、发评成功后才触发自生长学习 |
| 1.0.0 | 2026-09-19 | Antigravity | 初始创建：实现低耦合高内聚的独立发评 CLI |
"""

from __future__ import annotations

import argparse
import fcntl
import logging
import signal
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Mapping, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from config.settings import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("wechat_commenter")

WORKER_LOCK = PROJECT_ROOT / "output" / ".wechat_interaction_worker.lock"
DEFAULT_WORKER_TIMEOUT_SECONDS = 240
MAX_MANUAL_INTERACTION_BATCH_SIZE = 10


class _LiveServices:
    """将生成、浏览器和通知收口到 runner 的一个注入点。"""

    def __init__(self, db: Any, *, headless: bool, notify_tg: bool) -> None:
        from video_processing.interaction import InteractionService

        self.db = db
        self.headless = headless
        self.notify_tg = notify_tg
        self.generator = InteractionService()
        self.last_draft = None

    @staticmethod
    def _published_title_hint(youtube_id: str, slice_index: int) -> Optional[str]:
        """从已发布文案取稳定前缀，供无原生 ID 属性的后台列表做唯一绑定。"""
        prefix = f"{youtube_id}_s{slice_index}" if slice_index else youtube_id
        copy_path = PROJECT_ROOT / "output" / f"{prefix}_copy.txt"
        if not copy_path.is_file():
            return None
        try:
            text = " ".join(copy_path.read_text(encoding="utf-8").split())
        except OSError as exc:
            logger.warning("读取已发布文案定位提示失败: %s", exc)
            return None
        return text[:96] or None

    def generate_comment(self, target: Mapping[str, Any], *, force_rule: bool) -> Any:
        yid = str(target.get("youtube_id") or "")
        slice_index = int(target.get("slice_index") or 0)
        prefix = f"{yid}_s{slice_index}" if slice_index else yid
        copy_path = PROJECT_ROOT / "output" / f"{prefix}_copy.txt"
        title = str(target.get("zh_title") or target.get("title") or "精选视频")
        description = copy_path.read_text(encoding="utf-8") if copy_path.is_file() else title
        self.last_draft = self.generator.generate_comment(
            title=title,
            description=description,
            category=str(target.get("category") or "General"),
            force_rule=force_rule,
        )
        return self.last_draft

    def post_comment(self, **kwargs: Any) -> tuple[str, Optional[str], Optional[str]]:
        if not bool(kwargs.get("verify_only")):
            try:
                self.generator.validate_comment_for_submission(
                    str(kwargs.get("comment_text") or "")
                )
            except Exception as exc:
                logger.error("互动评论提交前复审拒绝: %s", exc)
                return "FAILED", None, f"提交前内容审查拒绝: {exc}"
        from video_processing.interaction import BrowserCommenter

        call_kwargs = dict(kwargs)
        hint = self._published_title_hint(
            str(call_kwargs.pop("source_youtube_id", "") or ""),
            int(call_kwargs.pop("source_slice_index", 0) or 0),
        )
        if hint:
            call_kwargs["video_title"] = hint
        return BrowserCommenter(headless=self.headless).post_comment(**call_kwargs)

    def notify_result(
        self,
        target: Mapping[str, Any],
        interaction: Mapping[str, Any],
        final_record: Mapping[str, Any],
    ) -> None:
        matching_draft = self.last_draft
        if (
            matching_draft is not None
            and matching_draft.formatted_comment != str(interaction.get("comment_text") or "")
        ):
            matching_draft = None
        if str(final_record["status"]) == "COMMENTED" and matching_draft is not None:
            try:
                self.generator.store.learn_from_success(
                    matching_draft,
                    str(target.get("zh_title") or target.get("title") or "精选视频"),
                )
            except Exception as exc:
                logger.warning("互动成功样例学习失败，不改写平台结果: %s", exc)
        if not self.notify_tg:
            return
        from video_processing.interaction import InteractionNotifier

        InteractionNotifier(db=self.db).notify_interaction_result(
            video_title=str(target.get("zh_title") or target.get("title") or "精选视频"),
            platform_post_id=str(interaction["platform_post_id"]),
            status=str(final_record["status"]),
            draft=matching_draft,
            evidence_path=final_record.get("evidence_path"),
            error_message=final_record.get("error_message"),
        )


class _WorkerDeadline(BaseException):
    """不能被生成器/浏览器的 ``except Exception`` 吞掉的总时限中断。"""


def _timeout_handler(_signum: int, _frame: Any) -> None:
    raise _WorkerDeadline("视频号互动 worker 超过有界运行时间")


@contextmanager
def _worker_deadline(seconds: int):
    previous_handler = signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(max(30, min(600, int(seconds))))
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous_handler)


def run_interaction(
    *,
    platform_post_id: str | None = None,
    video_id: int | None = None,
    reconcile_pending: bool = False,
    force_rule: bool = False,
    refresh_draft: bool = False,
    dry_run: bool = False,
    headless: bool = True,
    notify_tg: bool = True,
    worker_timeout_seconds: int = DEFAULT_WORKER_TIMEOUT_SECONDS,
    count: int = 1,
) -> int:
    """运行有限互动 tick；批量模式只消费从未建立互动账本的最新候选。"""
    if not 1 <= int(count) <= MAX_MANUAL_INTERACTION_BATCH_SIZE:
        logger.error("--count 必须介于 1 和 %d", MAX_MANUAL_INTERACTION_BATCH_SIZE)
        return 2
    if int(count) > 1 and (platform_post_id or video_id is not None or reconcile_pending):
        logger.error("--count 大于 1 时不能与显式目标或 --reconcile-pending 同时使用")
        return 2
    if refresh_draft and (dry_run or reconcile_pending or not (platform_post_id or video_id is not None)):
        logger.error("--refresh-draft 只能用于非 dry-run 的显式作品，且不能与 --reconcile-pending 同用")
        return 2
    if not settings.enable_wechat_comment_interaction and not dry_run:
        logger.info("enable_wechat_comment_interaction 未开启，未构造账本、生成器或浏览器。")
        return 0

    if reconcile_pending and (platform_post_id or video_id is not None or dry_run):
        logger.error("--reconcile-pending 不能与显式目标或 --dry-run 同时使用")
        return 2

    try:
        with _worker_deadline(worker_timeout_seconds):
            from video_processing.db.database import PipelineDB
            from video_processing.interaction.runner import run_interaction_tick

            if dry_run and not (PROJECT_ROOT / "output" / "pipeline.db").is_file():
                logger.info("[Dry Run] 账本文件不存在，受控返回 NO_WORK，不创建数据库。")
                return 0
            try:
                db = PipelineDB(read_only=dry_run)
            except (FileNotFoundError, RuntimeError) as exc:
                if dry_run:
                    logger.error("[Dry Run] 只读账本不可用: %s", exc)
                    return 1
                raise
            services = _LiveServices(db, headless=headless, notify_tg=notify_tg and not dry_run)
            if dry_run:
                if int(count) == 1:
                    result = run_interaction_tick(
                        db, services, platform_post_id=platform_post_id, video_id=video_id,
                        force_rule=True, dry_run=True,
                    )
                    logger.info("[Dry Run] %s: %s", result.status, result.detail or "")
                    return 0 if result.status in {"DRY_RUN", "NO_WORK"} else 1
                candidates = db.get_recent_wechat_posts_without_interaction(limit=int(count))
                for candidate in candidates:
                    result = run_interaction_tick(
                        db, services, platform_post_id=str(candidate["platform_post_id"]),
                        force_rule=True, dry_run=True,
                    )
                    logger.info("[Dry Run] %s %s: %s", candidate["platform_post_id"], result.status, result.detail or "")
                return 0

            WORKER_LOCK.parent.mkdir(parents=True, exist_ok=True)
            with WORKER_LOCK.open("a+") as lock_file:
                try:
                    fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except (BlockingIOError, OSError):
                    logger.info("已有互动 worker 运行；本次有界退出，PUBLISHED 目标保持可发现。")
                    return 0
                try:
                    if int(count) == 1:
                        result = run_interaction_tick(
                            db, services, platform_post_id=platform_post_id, video_id=video_id,
                            force_rule=force_rule, refresh_draft=refresh_draft,
                            reconcile_only=reconcile_pending,
                        )
                        logger.info(
                            "视频号互动 tick 结束: status=%s post_id=%s detail=%s",
                            result.status, result.platform_post_id, result.detail or "",
                        )
                        return 0 if result.status in {
                            "NO_WORK", "NOT_DUE", "COMMENTED", "SKIPPED_EXISTS", "UNCERTAIN"
                        } else 1

                    candidates = db.get_recent_wechat_posts_without_interaction(limit=int(count))
                    if not candidates:
                        logger.info("无尚未建立互动账本的可评论作品")
                        return 0
                    for candidate in candidates:
                        result = run_interaction_tick(
                            db, services, platform_post_id=str(candidate["platform_post_id"]),
                            force_rule=force_rule,
                        )
                        logger.info(
                            "视频号互动批量 tick 结束: status=%s post_id=%s detail=%s",
                            result.status, result.platform_post_id, result.detail or "",
                        )
                        if result.status in {"COMMENTED", "SKIPPED_EXISTS"}:
                            continue
                        if result.status == "UNCERTAIN":
                            logger.warning("当前作品提交结果不确定，已停止后续批量评论")
                            return 0
                        return 0 if result.status == "NO_WORK" else 1
                    return 0
                finally:
                    fcntl.flock(lock_file, fcntl.LOCK_UN)
    except _WorkerDeadline as exc:
        logger.error("%s", exc)
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="微信视频号互动有界 worker")
    parser.add_argument("--post-id", type=str, help="指定已确认 PUBLISHED 的微信原生 ID")
    parser.add_argument("--video-id", type=int, help="指定已确认 PUBLISHED 的内部 video_id")
    parser.add_argument("--latest", action="store_true", help="处理最近一条到期作品")
    parser.add_argument("--count", type=int, default=1, help="人工批量处理最新的无互动账本作品，最多 10 条")
    parser.add_argument("--reconcile-pending", action="store_true", help="优先处理 UNCERTAIN 只读回查")
    parser.add_argument("--force-rule", action="store_true", help="强制使用本地规则生成")
    parser.add_argument("--refresh-draft", action="store_true", help="仅对未提交的显式任务审计式替换为当前草稿")
    parser.add_argument("--dry-run", action="store_true", help="不受 live 开关限制的本地规则预览；数据库只读，不启动 AGY/浏览器/通知")
    parser.add_argument("--no-headless", action="store_true", help="以有头浏览器运行")
    parser.add_argument("--no-tg", action="store_true", help="跳过 Telegram 结果通知")
    args = parser.parse_args()
    sys.exit(run_interaction(
        platform_post_id=args.post_id, video_id=args.video_id,
        reconcile_pending=args.reconcile_pending, force_rule=args.force_rule,
        refresh_draft=args.refresh_draft,
        dry_run=args.dry_run, headless=not args.no_headless, notify_tg=not args.no_tg,
        count=args.count,
    ))


if __name__ == "__main__":
    main()
