#!/usr/bin/env python3
"""将一条视频号已受理的英语世界短视频同步提交到抖音。

该入口只消费 ``english_world_douyin_publications`` 的零尝试 QUEUED 记录；完整投稿包
位级校验、pipeline.lock 和不可变尝试账本全部在打开浏览器前建立。
已受理、未确认或失败记录均不会自动重传。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.4.0 | 2026-09-04 | Codex | 抖音投稿改用独立横竖英语视觉短视频海报封面，并把两图一同绑定至启动凭据。 |
| 1.3.2 | 2026-09-02 | Codex | 未启动票据的包校验/启动失败及超时遗留仅收口为 CANCELED，需显式恢复才可重投。 |
| 1.3.1 | 2026-09-02 | Codex | 投稿 worker 将不可变英语世界尝试绑定到一次性抖音浏览器启动凭据，拒绝借用来源参数。 |
| 1.3.0 | 2026-09-02 | Codex | 投稿同步复用阶段熔断策略：管理页故障不阻断新片，未知 UI 阶段保持 fail-closed。 |
| 1.2.0 | 2026-09-01 | Codex | 与视频号统一为不设抖音日额度；仍只领取唯一 QUEUED 尝试。 |
| 1.1.0 | 2026-08-30 | Codex | 投稿前页面失败接入持久 UI 熔断；一次证据化修复后只允许一轮显式恢复。 |
| 1.0.0 | 2026-08-30 | Codex | 新增英语世界到抖音的隔离、账本安全单次同步执行器。 |
"""

from __future__ import annotations

import argparse
import fcntl
import logging
from pathlib import Path
import subprocess
import sys
import time

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from config.settings import settings  # noqa: E402
from video_processing.core.douyin_ui_guard_policy import (  # noqa: E402
    active_douyin_ui_failure_stages,
    douyin_publish_is_blocked,
)
from video_processing.core.douyin_launch_context import douyin_submission_payload_sha256  # noqa: E402
from video_processing.db.database import PipelineDB  # noqa: E402
from video_processing.english_world.douyin_cover import prepare_douyin_cover_package  # noqa: E402
from video_processing.english_world.package_integrity import verify_package_hashes  # noqa: E402
from video_processing.pipeline_manager import _build_subprocess_env  # noqa: E402


logger = logging.getLogger(__name__)
UPLOAD_TIMEOUT_SECONDS = 25 * 60
EXIT_NOT_CLAIMABLE = 10


def _completion_for_exit_code(exit_code: int) -> tuple[str, str]:
    """按是否可能点击最终发布保守映射抖音上传器退出码。"""
    if exit_code == 6:
        return "UNDER_REVIEW", "抖音已受理提交，等待作品管理页确认公开。"
    if exit_code == 2:
        return "LOGIN_REQUIRED", "抖音登录态失效；本次在登录闸门停止，不自动重试。"
    if exit_code in {3, 4}:
        return "CANCELED", "抖音发布前页面或元信息闸门未通过；本次未确认提交，不自动重试。"
    if exit_code == 7:
        return "UNCERTAIN", "抖音最终提交结果未确认；可能已受理，禁止自动重传。"
    return "FAILED", f"抖音上传器返回 exit={exit_code}；未获得受理证据，不自动重试。"


def _cancel_unstarted_english_world_ticket(
    db: PipelineDB,
    *,
    review_id: str,
    attempt_id: str,
    ticket_id: str,
    evidence_dir: Path,
    message: str,
) -> bool:
    """只有 DAL 证明 ticket 未启动时才把本次领取收口为可显式恢复的取消。"""
    try:
        canceled = db.cancel_english_world_douyin_pre_launch_failure(
            review_id,
            attempt_id=attempt_id,
            ticket_id=ticket_id,
            evidence_dir=str(evidence_dir),
            message=message,
        )
    except Exception:  # noqa: BLE001 - 取消审计不可写时保守保持不可恢复失败
        logger.exception("English World Douyin pre-launch cancellation could not be recorded")
        return False
    return bool(canceled)


def submit(review_id: str) -> int:
    """建立唯一账本、领取一次投稿并执行抖音同步。"""
    if not settings.enable_douyin_browser_publishing:
        logger.error("Douyin browser publishing is disabled")
        return 1
    db = PipelineDB()
    try:
        active_stages = active_douyin_ui_failure_stages(
            db.get_platform_ui_failure_streaks("douyin"),
            recording_threshold=settings.douyin_ui_failure_recording_threshold,
        )
    except Exception:  # noqa: BLE001 - 账本不可读时不能开始新的公开提交
        logger.exception("Douyin UI failure ledger cannot be read; stop before ledger claim or browser")
        return 4
    if douyin_publish_is_blocked(active_stages):
        logger.error(
            "Douyin UI failure fuse is active for %s; record and calibrate before retrying",
            ", ".join(sorted(active_stages)),
        )
        return 4
    publication = db.ensure_english_world_douyin_publication(review_id)
    if publication.get("state") == "SUBMITTING":
        try:
            stale_canceled = db.cancel_stale_english_world_douyin_pre_launch_failure(
                review_id,
                stale_after_seconds=settings.douyin_prelaunch_ticket_recovery_ttl_seconds,
                evidence_dir=str(publication.get("evidence_dir") or ""),
            )
        except Exception:  # noqa: BLE001 - 无法证明未启动时不能领取或重投
            logger.exception("English World Douyin stale pre-launch ticket cannot be inspected")
            return 4
        if stale_canceled:
            logger.error(
                "English World Douyin stale unstarted ticket canceled: review=%s; explicit recovery required",
                review_id[:8],
            )
            return 1
    if publication.get("state") != "QUEUED":
        logger.info(
            "English World Douyin publication already exists: review=%s state=%s",
            review_id[:8], publication.get("state"),
        )
        return 0
    evidence_dir = (
        Path(str(publication["mp4_path"])).parent
        / "douyin_evidence"
        / str(time.time_ns())
    )
    claimed = db.claim_english_world_douyin_publication(
        review_id,
        daily_limit=max(0, int(settings.douyin_new_sync_daily_limit or 0)) or None,
        evidence_dir=str(evidence_dir),
    )
    if not claimed:
        logger.warning("English World Douyin item is not claimable")
        return EXIT_NOT_CLAIMABLE
    attempt_id = str(claimed["_attempt_id"])
    ticket_id = str(claimed.get("_douyin_launch_ticket_id") or "").strip()
    launch_token = str(claimed.get("_douyin_launch_token") or "").strip()
    try:
        evidence_dir.mkdir(parents=True, exist_ok=True)
        verify_package_hashes(claimed)
        douyin_covers = prepare_douyin_cover_package(claimed)
        vertical_cover_path = str(douyin_covers["vertical_cover_path"])
        horizontal_cover_path = str(douyin_covers["horizontal_cover_path"])
        payload_sha256 = douyin_submission_payload_sha256(
            video_path=claimed["mp4_path"],
            copy_path=claimed["copy_path"],
            title_path=claimed["title_path"],
            cover_path=vertical_cover_path,
            horizontal_cover_path=horizontal_cover_path,
        )
        if not payload_sha256 or not ticket_id or not launch_token:
            raise RuntimeError("英语世界抖音领取缺少一次性浏览器启动凭据或完整投稿包摘要")
        if not db.bind_douyin_browser_launch_ticket_payload(
            ticket_id,
            launch_token,
            payload_sha256=payload_sha256,
        ):
            raise RuntimeError("英语世界抖音启动凭据、领取状态或完整投稿包不匹配")
        command = [
            str(PROJECT_ROOT / ".venv/bin/python"),
            str(PROJECT_ROOT / "scripts/douyin_uploader.py"),
            "--video", str(claimed["mp4_path"]),
            "--copy", str(claimed["copy_path"]),
            "--title-file", str(claimed["title_path"]),
            "--cover", vertical_cover_path,
            "--horizontal-cover", horizontal_cover_path,
            "--state", str(PROJECT_ROOT / "output/douyin_state.json"),
            "--evidence-dir", str(evidence_dir),
            "--fail-fast-login",
            "--prepare-description",
            "--publish",
            "--douyin-launch-ticket", ticket_id,
            "--douyin-launch-token", launch_token,
        ]
        if not settings.douyin_browser_headless:
            command.append("--no-headless")
        pipeline_lock = PROJECT_ROOT / "output/pipeline.lock"
        pipeline_lock.parent.mkdir(parents=True, exist_ok=True)
        with pipeline_lock.open("a+") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            result = subprocess.run(
                command,
                cwd=PROJECT_ROOT,
                env=_build_subprocess_env(),
                text=True,
                capture_output=True,
                timeout=UPLOAD_TIMEOUT_SECONDS,
                check=False,
            )
        state, message = _completion_for_exit_code(int(result.returncode))
        if result.stderr:
            message = f"{message} 执行摘要：{result.stderr[-500:].strip()}"
        if state == "FAILED" and _cancel_unstarted_english_world_ticket(
            db,
            review_id=review_id,
            attempt_id=attempt_id,
            ticket_id=ticket_id,
            evidence_dir=evidence_dir,
            message=f"上传器在启动浏览器前结束：{message}",
        ):
            logger.warning(
                "English World Douyin uploader ended before browser launch: review=%s",
                review_id[:8],
            )
            return int(result.returncode or 1)
        if result.returncode in {3, 4}:
            failure = db.record_platform_ui_failure(
                "douyin",
                "publish_pre_submit",
                message,
                evidence_path=str(evidence_dir),
                recording_threshold=settings.douyin_ui_failure_recording_threshold,
            )
            if int(failure.get("consecutive_failures") or 0) >= max(
                1, int(settings.douyin_ui_failure_recording_threshold),
            ):
                message = (
                    f"{message} 已达到 UI 失败熔断阈值；请录制抖音封面设置到最终发布前的操作流程。"
                )
        elif state == "UNDER_REVIEW":
            db.clear_platform_ui_failure_streak(
                "douyin", "publish_pre_submit", str(evidence_dir),
            )
        db.complete_english_world_douyin_publication(
            review_id,
            attempt_id=attempt_id,
            state=state,
            uploader_exit_code=int(result.returncode),
            evidence_dir=str(evidence_dir),
            message=message,
        )
        logger.info(
            "English World Douyin submission completed: review=%s state=%s exit=%s",
            review_id[:8], state, result.returncode,
        )
        return 0 if state == "UNDER_REVIEW" else int(result.returncode or 1)
    except subprocess.TimeoutExpired:
        if _cancel_unstarted_english_world_ticket(
            db,
            review_id=review_id,
            attempt_id=attempt_id,
            ticket_id=ticket_id,
            evidence_dir=evidence_dir,
            message="投稿超时，但上传器尚未消费浏览器启动票据",
        ):
            logger.warning(
                "English World Douyin timeout canceled before browser launch: review=%s",
                review_id[:8],
            )
            return 124
        db.complete_english_world_douyin_publication(
            review_id,
            attempt_id=attempt_id,
            state="UNCERTAIN",
            uploader_exit_code=124,
            evidence_dir=str(evidence_dir),
            message="抖音投稿超时；无法排除平台已受理，禁止自动重传。",
        )
        return 124
    except Exception as exc:  # noqa: BLE001 - worker must persist an auditable stop state
        logger.exception("English World Douyin submission failed: %s", exc)
        if _cancel_unstarted_english_world_ticket(
            db,
            review_id=review_id,
            attempt_id=attempt_id,
            ticket_id=ticket_id,
            evidence_dir=evidence_dir,
            message=f"投稿包校验或子进程启动失败：{exc}",
        ):
            logger.warning(
                "English World Douyin failure canceled before browser launch: review=%s",
                review_id[:8],
            )
            return 1
        db.complete_english_world_douyin_publication(
            review_id,
            attempt_id=attempt_id,
            state="FAILED",
            uploader_exit_code=1,
            evidence_dir=str(evidence_dir),
            message=f"投稿包校验或执行失败：{exc}。未自动重传。",
        )
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="同步一条已受理英语世界短视频到抖音")
    parser.add_argument("--review-id", required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return submit(args.review_id)


if __name__ == "__main__":
    raise SystemExit(main())
