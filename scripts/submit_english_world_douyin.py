#!/usr/bin/env python3
"""将一条视频号已受理的英语世界短视频同步提交到抖音。

该入口只消费 ``english_world_douyin_publications`` 的零尝试 QUEUED 记录；完整投稿包
位级校验、共享每日额度、pipeline.lock 和不可变尝试账本全部在打开浏览器前建立。
已受理、未确认或失败记录均不会自动重传。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
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
from video_processing.db.database import PipelineDB  # noqa: E402
from video_processing.english_world.package_integrity import verify_package_hashes  # noqa: E402
from video_processing.pipeline_manager import _build_subprocess_env  # noqa: E402


logger = logging.getLogger(__name__)
UPLOAD_TIMEOUT_SECONDS = 25 * 60
EXIT_DAILY_LIMIT = 10


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


def submit(review_id: str) -> int:
    """建立唯一账本、领取每日额度并执行一次抖音投稿。"""
    if not settings.enable_douyin_browser_publishing:
        logger.error("Douyin browser publishing is disabled")
        return 1
    db = PipelineDB()
    active_failures = [
        failure for failure in db.get_platform_ui_failure_streaks("douyin")
        if failure.get("stage") == "publish_pre_submit" and int(failure.get("active") or 0) == 1
    ]
    if active_failures and int(active_failures[0].get("consecutive_failures") or 0) >= max(
        1, int(settings.douyin_ui_failure_recording_threshold),
    ):
        logger.error(
            "Douyin publish_pre_submit UI failure fuse is active; record and calibrate the flow before retrying"
        )
        return 4
    publication = db.ensure_english_world_douyin_publication(review_id)
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
        daily_limit=settings.douyin_new_sync_daily_limit,
        evidence_dir=str(evidence_dir),
    )
    if not claimed:
        logger.warning("English World Douyin daily limit reached or item is not claimable")
        return EXIT_DAILY_LIMIT
    attempt_id = str(claimed["_attempt_id"])
    evidence_dir.mkdir(parents=True, exist_ok=True)
    try:
        verify_package_hashes(claimed)
        command = [
            str(PROJECT_ROOT / ".venv/bin/python"),
            str(PROJECT_ROOT / "scripts/douyin_uploader.py"),
            "--video", str(claimed["mp4_path"]),
            "--copy", str(claimed["copy_path"]),
            "--title-file", str(claimed["title_path"]),
            "--cover", str(claimed["cover_path"]),
            "--state", str(PROJECT_ROOT / "output/douyin_state.json"),
            "--evidence-dir", str(evidence_dir),
            "--fail-fast-login",
            "--prepare-description",
            "--publish",
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
