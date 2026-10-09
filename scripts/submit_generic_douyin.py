#!/usr/bin/env python3
"""将一条独立的视频投稿同步提交到抖音。

该脚本通过 PipelineDB 签发不可变单次浏览器启动 ticket 并绑定投稿包哈希，
然后调用 douyin_uploader.py 执行上传、填写和提交。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-07 | Antigravity | 新增独立/通用视频抖音提交流水线执行器，支持不可变 ticket 绑定与审计追踪。 |
| 1.1.0 | 2026-10-09 | Antigravity | 支持检测并同步视频资产哈希变更，重置并签发最新成片启动凭据。 |
| 1.2.0 | 2026-10-09 | Antigravity | 遵循 DAL 封装宪法，使用 PipelineDB.reset_douyin_publication_for_reupload 替代原生 SQL。 |
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
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
from video_processing.core.douyin_launch_context import douyin_submission_payload_sha256  # noqa: E402
from video_processing.db.database import PipelineDB  # noqa: E402
from video_processing.pipeline_manager import _build_subprocess_env  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

UPLOAD_TIMEOUT_SECONDS = 25 * 60


def _completion_for_exit_code(exit_code: int) -> tuple[str, str]:
    """按是否可能点击最终发布保守映射抖音上传器退出码。"""
    if exit_code == 6:
        return "UNDER_REVIEW", "抖音已受理提交，等待作品管理页确认公开。"
    if exit_code == 0:
        return "PUBLISHED", "抖音已发布成功。"
    if exit_code == 2:
        return "LOGIN_REQUIRED", "抖音登录态失效；本次在登录闸门停止，不自动重试。"
    if exit_code in {3, 4}:
        return "CANCELED", "抖音发布前页面或元信息闸门未通过；本次未确认提交，不自动重试。"
    if exit_code == 7:
        return "UNCERTAIN", "抖音最终提交结果未确认；可能已受理，禁止自动重传。"
    return "FAILED", f"抖音上传器返回 exit={exit_code}；未获得受理证据，不自动重试。"


def main() -> int:
    parser = argparse.ArgumentParser(description="Submit generic video to Douyin")
    parser.add_argument("--video", required=True, type=Path, help="Video path")
    parser.add_argument("--youtube-id", required=True, help="YouTube ID registered in processed_videos")
    parser.add_argument("--title-file", required=True, type=Path, help="Title text file")
    parser.add_argument("--copy", required=True, type=Path, help="Copy text file")
    parser.add_argument("--cover", required=True, type=Path, help="Vertical cover image")
    parser.add_argument("--horizontal-cover", required=True, type=Path, help="Horizontal cover image")
    parser.add_argument("--evidence-dir", required=True, type=Path, help="Evidence directory")
    args = parser.parse_args()

    video_path = args.video.resolve()
    if not video_path.exists():
        logger.error("Video file does not exist: %s", video_path)
        return 1

    video_bytes = video_path.read_bytes()
    video_sha256 = hashlib.sha256(video_bytes).hexdigest()
    logger.info("Video SHA-256: %s", video_sha256)

    db = PipelineDB()
    video = db.get_video_by_youtube_id(args.youtube_id)
    if not video:
        logger.error("Video not found in processed_videos: %s", args.youtube_id)
        return 1

    # 创建/获取 douyin publication 记录
    pub = db.get_douyin_publication(args.youtube_id)
    if not pub:
        pub = db.create_douyin_publication(
            args.youtube_id,
            asset_sha256=video_sha256,
            video_path=str(video_path),
            source_kind="NEW",
        )
        logger.info("Created new douyin publication: id=%s", pub["id"])
    elif pub.get("state") == "PUBLISHED":
        logger.info("Video is already published on Douyin: id=%s", pub["id"])
        return 0

    pub_id = pub["id"]

    # 检查成片哈希是否有更新（如重新渲染后重新提交），有则同步更新
    if pub.get("asset_sha256") != video_sha256 and pub.get("state") != "PUBLISHED":
        logger.info(
            "Video hash updated (%s -> %s), resetting pub id=%s to QUEUED with new hash",
            (pub.get("asset_sha256") or "")[:8],
            video_sha256[:8],
            pub_id,
        )
        db.reset_douyin_publication_for_reupload(
            pub_id, asset_sha256=video_sha256, video_path=str(video_path)
        )

    # 领取任务并获取启动凭据
    claimed = db.claim_douyin_publication(pub_id)
    if not claimed:
        # 可能是正在上传或重试
        logger.warning("Could not claim douyin publication id=%s; state=%s", pub_id, pub.get("state"))
        # 尝试重置为 QUEUED 后再领取
        db.reset_douyin_publication_for_reupload(
            pub_id, asset_sha256=video_sha256, video_path=str(video_path)
        )
        claimed = db.claim_douyin_publication(pub_id)
        if not claimed:
            logger.error("Failed to claim douyin publication id=%s after reset", pub_id)
            return 1

    ticket_id = str(claimed.get("_douyin_launch_ticket_id") or "").strip()
    launch_token = str(claimed.get("_douyin_launch_token") or "").strip()

    if not ticket_id or not launch_token:
        logger.error("Missing launch ticket or token for publication id=%s", pub_id)
        return 1

    args.evidence_dir.mkdir(parents=True, exist_ok=True)

    # 计算完整投稿包 sha256 并绑定
    payload_sha256 = douyin_submission_payload_sha256(
        video_path=str(video_path),
        copy_path=str(args.copy.resolve()),
        title_path=str(args.title_file.resolve()),
        cover_path=str(args.cover.resolve()),
        horizontal_cover_path=str(args.horizontal_cover.resolve()),
    )

    if not payload_sha256:
        logger.error("Failed to compute douyin submission payload sha256")
        db.cancel_douyin_publication_pre_launch_failure(
            pub_id, ticket_id=ticket_id, reason="无法计算投稿包摘要",
        )
        return 1

    if not db.bind_douyin_browser_launch_ticket_payload(
        ticket_id,
        launch_token,
        payload_sha256=payload_sha256,
    ):
        logger.error("Failed to bind douyin browser launch ticket payload")
        db.cancel_douyin_publication_pre_launch_failure(
            pub_id, ticket_id=ticket_id, reason="绑定启动凭据失败",
        )
        return 1

    logger.info("Bound launch ticket %s to payload %s", ticket_id[:8], payload_sha256[:8])

    command = [
        str(PROJECT_ROOT / ".venv/bin/python"),
        str(PROJECT_ROOT / "scripts/douyin_uploader.py"),
        "--video", str(video_path),
        "--copy", str(args.copy.resolve()),
        "--title-file", str(args.title_file.resolve()),
        "--cover", str(args.cover.resolve()),
        "--horizontal-cover", str(args.horizontal_cover.resolve()),
        "--state", str(PROJECT_ROOT / "output/douyin_state.json"),
        "--evidence-dir", str(args.evidence_dir.resolve()),
        "--fail-fast-login",
        "--prepare-description",
        "--publish",
        f"--douyin-launch-ticket={ticket_id}",
        f"--douyin-launch-token={launch_token}",
    ]
    if not settings.douyin_browser_headless:
        command.append("--no-headless")

    pipeline_lock = PROJECT_ROOT / "output/douyin_submission.lock"
    pipeline_lock.parent.mkdir(parents=True, exist_ok=True)

    logger.info("Running douyin_uploader.py...")
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

    logger.info("douyin_uploader exited with code %s", result.returncode)
    if result.stdout:
        logger.info("STDOUT:\n%s", result.stdout[-1500:].strip())
    if result.stderr:
        logger.warning("STDERR:\n%s", result.stderr[-1500:].strip())

    state, message = _completion_for_exit_code(int(result.returncode))
    if state == "FAILED":
        db.cancel_douyin_publication_pre_launch_failure(
            pub_id, ticket_id=ticket_id, reason=message,
        )
    elif state == "UNDER_REVIEW":
        db.clear_platform_ui_failure_streak("douyin", "publish_pre_submit", str(args.evidence_dir))
        db.update_douyin_publication_state(pub_id, state=state, error_message=message)
    else:
        db.update_douyin_publication_state(pub_id, state=state, error_message=message)

    logger.info("Final Douyin state: %s (%s)", state, message)
    return 0 if state in {"UNDER_REVIEW", "PUBLISHED"} else int(result.returncode or 1)


if __name__ == "__main__":
    sys.exit(main())
