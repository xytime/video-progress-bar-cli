#!/usr/bin/env python3
"""提交一条已获 Telegram 批准的英语世界学习卡到视频号。

仅消费 ``english_world_review_items`` 中已原子领取的审核项；不会进入
PipelineManager、不会扫描任何待处理项，也不会为失败/未确认的提交自动重试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-23 | Codex | 新增英语世界学习卡的独立、一次性视频号投稿执行器。 |
| 1.1.0 | 2026-08-26 | Codex | 投稿器在领取前尊重全局微信暂停开关，避免自动策略绕过运营暂停。 |
| 1.2.0 | 2026-08-29 | Codex | 自动投稿遵守公共窗口；Telegram 单项批准仅在两小时 capability 内允许窗口外提交。 |
| 1.3.0 | 2026-08-29 | Codex | 上传前复核完整投稿包哈希，并将每次尝试绑定独立 evidence_dir 持久化。 |
| 1.4.0 | 2026-08-29 | Codex | 专用投稿器复用全局 pipeline.lock，避免与通用流水线并发操作微信浏览器会话。 |
| 1.5.0 | 2026-08-30 | Codex | 窗口外延后返回独立状态码，禁止把“尚未上传”误报为执行成功。 |
| 1.6.0 | 2026-08-30 | Codex | 支持具名操作员对零尝试自动延后项签发两小时单项补发授权。 |
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import json
import logging
from pathlib import Path
import subprocess
import time

import requests

from config.settings import settings
from video_processing.core.cover_policy import validate_dedicated_cover_file
from video_processing.db.database import PipelineDB
from video_processing.english_world.package_integrity import verify_package_hashes


logger = logging.getLogger(__name__)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_UPLOAD_TIMEOUT_SECONDS = 25 * 60
EXIT_DEFERRED = 10


def _post_status(text: str) -> None:
    """尽力发送 Telegram 回执；通知失败不覆盖已落盘的投稿状态。"""
    token = (settings.telegram_bot_token or "").strip()
    chat_id = (settings.active_telegram_chat_id or "").strip()
    if not token or not chat_id:
        logger.warning("Telegram submission receipt skipped: credentials/chat id unavailable")
        return
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=20,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        # requests 异常可能包含带 Token 的 URL，日志中只保留错误类别。
        logger.warning("Telegram submission receipt failed: %s", type(exc).__name__)


def _require_publish_package(item: dict) -> None:
    """在启动浏览器前验证审核项绑定的完整发布包，防止改路径或默认封面投稿。"""
    required = ("mp4_path", "manifest_path", "title_path", "copy_path", "cover_path", "cover_provenance_path")
    for field in required:
        value = Path(str(item.get(field) or ""))
        if not value.is_file() or value.stat().st_size <= 0:
            raise FileNotFoundError(f"English World publish package missing: {field}")
    try:
        manifest = json.loads(Path(str(item["manifest_path"])).read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("English World publish manifest is unreadable") from exc
    if manifest.get("content_type") != "ENGLISH_WORLD_SHORT":
        raise ValueError("English World publish item content type is invalid")
    if not validate_dedicated_cover_file(
        Path(str(item["cover_path"])), Path(str(item["cover_provenance_path"])),
    ):
        raise ValueError("English World publish cover is not a verified dedicated cover")
    verify_package_hashes(item)


def _completion_for_exit_code(code: int) -> tuple[str, str]:
    """把 uploader 返回码映射为保守账本状态，永远不在这里声称已公开。"""
    if code in {0, 6}:
        return "UNDER_REVIEW", "视频号已受理提交，等待平台审核/作品管理页确认；尚无公开发布证明。"
    if code == 2:
        return "LOGIN_REQUIRED", "视频号登录失效，未完成可确认投稿；请完成扫码后人工处理本条。"
    if code == 3:
        return "UNCERTAIN", "投稿结果无法确认，可能已受理；已停止自动重传，需在视频号后台核验。"
    return "FAILED", f"投稿器返回 exit={code}，未自动重传。请先核验视频号后台再决定后续动作。"


def _manual_authorization_active(item: dict) -> bool:
    """人工或具名补发项只有在两小时 capability 有效期内才可绕过公共窗口。"""
    if str(item.get("approval_source") or "") not in {"TELEGRAM_REVIEW", "OPERATOR_RECOVERY"}:
        return False
    raw_expiry = str(item.get("authorization_expires_at") or "").strip()
    if not raw_expiry:
        return False
    try:
        expires_at = datetime.strptime(raw_expiry, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    return expires_at > datetime.now(timezone.utc)


def submit(review_id: str, *, operator_recovery_reason: str | None = None) -> int:
    """领取并执行一次投稿；即使浏览器异常也保留可审计的终态回执。"""
    if settings.wechat_publishing_paused:
        logger.warning("English World submission deferred because WeChat publishing is paused")
        return EXIT_DEFERRED
    db = PipelineDB()
    pending = (
        db.authorize_english_world_operator_recovery(review_id, reason=operator_recovery_reason)
        if operator_recovery_reason
        else db.get_english_world_review_item(review_id)
    )
    if pending is None:
        logger.info("English World review item does not exist: %s", review_id)
        return 0
    if not settings.is_public_publish_window():
        if not _manual_authorization_active(pending):
            db.expire_english_world_submission_authorization(review_id)
            logger.info(
                "English World submission deferred outside public window: %s source=%s",
                review_id,
                pending.get("approval_source"),
            )
            return EXIT_DEFERRED
        logger.warning(
            "English World review %s uses its two-hour bounded capability outside the public window source=%s",
            review_id, pending.get("approval_source"),
        )
    evidence_dir = Path(str(pending["mp4_path"])).parent / "wechat_evidence" / str(time.time_ns())
    item = db.claim_english_world_submission(review_id, evidence_dir=str(evidence_dir))
    if item is None:
        logger.info("English World review item is not claimable: %s", review_id)
        return 0

    title = str(item.get("title") or "英语世界短视频")
    attempt_id = str(item["_attempt_id"])
    evidence_dir.mkdir(parents=True, exist_ok=True)
    try:
        _require_publish_package(item)
        command = [
            str(_PROJECT_ROOT / ".venv" / "bin" / "python"),
            str(_PROJECT_ROOT / "scripts" / "wechat_uploader.py"),
            "--video", str(item["mp4_path"]),
            "--copy", str(item["copy_path"]),
            "--title-file", str(item["title_path"]),
            "--cover", str(item["cover_path"]),
            "--cover-provenance", str(item["cover_provenance_path"]),
            "--state", str(_PROJECT_ROOT / "output" / "wechat_state.json"),
            "--evidence-dir", str(evidence_dir),
            "--fail-fast-login",
            "--no-original-declaration",
        ]
        if not settings.wechat_headless:
            command.append("--no-headless")
        pipeline_lock = _PROJECT_ROOT / "output" / "pipeline.lock"
        pipeline_lock.parent.mkdir(parents=True, exist_ok=True)
        with pipeline_lock.open("a+") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            result = subprocess.run(
                command, cwd=str(_PROJECT_ROOT), text=True, capture_output=True,
                timeout=_UPLOAD_TIMEOUT_SECONDS,
            )
        state, message = _completion_for_exit_code(result.returncode)
        if result.stderr:
            message = f"{message}\n执行摘要：{result.stderr[-500:].strip()}"
        db.complete_english_world_submission(
            review_id, state=state, uploader_exit_code=result.returncode,
            evidence_dir=str(evidence_dir), message=message, attempt_id=attempt_id,
        )
    except subprocess.TimeoutExpired:
        state = "UNCERTAIN"
        message = "视频号上传超时，无法排除平台已受理；已停止自动重传，需在后台核验。"
        db.complete_english_world_submission(
            review_id, state=state, uploader_exit_code=124,
            evidence_dir=str(evidence_dir), message=message, attempt_id=attempt_id,
        )
    except Exception as exc:  # noqa: BLE001 - worker must persist its own failure receipt
        logger.exception("English World WeChat submission failed: %s", exc)
        state = "FAILED"
        message = f"投稿前校验或执行失败：{exc}。未自动重传。"
        db.complete_english_world_submission(
            review_id, state=state, uploader_exit_code=1,
            evidence_dir=str(evidence_dir), message=message, attempt_id=attempt_id,
        )

    labels = {
        "UNDER_REVIEW": "⏳ <b>视频号已受理｜等待审核</b>",
        "UNCERTAIN": "⚠️ <b>视频号提交未确认</b>",
        "LOGIN_REQUIRED": "🔐 <b>视频号需要重新登录</b>",
        "FAILED": "❌ <b>视频号投稿未完成</b>",
    }
    _post_status(
        f"{labels[state]}\n标题：{title}\n审核编号：<code>{review_id[:8]}</code>\n"
        f"{message}\n证据目录：<code>{evidence_dir}</code>"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="提交已批准的英语世界学习卡到视频号")
    parser.add_argument("--review-id", required=True, help="Telegram 审核项 ID")
    parser.add_argument(
        "--operator-recovery-reason",
        help="具名补发原因；仅可授权零尝试的 AUTO_POLICY 延后项并在两小时内提交",
    )
    args = parser.parse_args()
    return submit(args.review_id, operator_recovery_reason=args.operator_recovery_reason)


if __name__ == "__main__":
    raise SystemExit(main())
