"""Telegram 自动通知投递与回执账本。

所有返回值只描述 Telegram Bot API 的响应：ACCEPTED 表示 API 已接受，UNKNOWN
表示网络层没有取得可判定响应，绝不推断手机端通知展示或用户已读。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-24 | Codex | 新增自动通知回执、去重与秘密安全的错误分类。 |
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from config.settings import settings
from video_processing.db.database import PipelineDB


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TelegramDeliveryResult:
    state: str
    message_id: str | None = None
    error_kind: str | None = None
    suppressed: bool = False


def _fingerprint(event_type: str, text: str, attachment: Path | None = None) -> str:
    digest = hashlib.sha256()
    digest.update(event_type.encode("utf-8"))
    digest.update(b"\0")
    digest.update(text.encode("utf-8"))
    if attachment is not None:
        digest.update(b"\0")
        digest.update(attachment.name.encode("utf-8"))
        digest.update(str(attachment.stat().st_size).encode("ascii"))
    return digest.hexdigest()


def _record(
    *, event_type: str, priority: str, fingerprint: str, state: str,
    message_id: str | None = None, error_kind: str | None = None, db: PipelineDB | None = None,
) -> None:
    try:
        (db or PipelineDB()).record_telegram_notification_receipt(
            event_type=event_type, priority=priority, content_sha256=fingerprint,
            delivery_state=state, telegram_message_id=message_id, error_kind=error_kind,
        )
    except Exception as exc:  # 回执故障不能影响主业务，但不得记录可能含 URL 的异常文本。
        logger.error("Telegram receipt recording failed: %s", type(exc).__name__)


def _credentials() -> tuple[str, str]:
    return (
        (settings.telegram_bot_token or "").strip(),
        (settings.active_telegram_chat_id or "").strip(),
    )


def _should_suppress(*, event_type: str, fingerprint: str, cooldown_seconds: int, db: PipelineDB | None = None) -> bool:
    if cooldown_seconds <= 0:
        return False
    since = (datetime.now(timezone.utc) - timedelta(seconds=cooldown_seconds)).strftime("%Y-%m-%d %H:%M:%S")
    try:
        return (db or PipelineDB()).has_recent_telegram_notification(
            event_type=event_type, content_sha256=fingerprint, since_utc=since,
        )
    except Exception as exc:
        logger.error("Telegram receipt dedupe lookup failed: %s", type(exc).__name__)
        return False


def _result_from_response(response: requests.Response) -> tuple[str, str | None, str | None]:
    try:
        payload: dict[str, Any] = response.json()
    except ValueError:
        payload = {}
    if response.ok and payload.get("ok") is True:
        result = payload.get("result")
        message_id = str(result.get("message_id")) if isinstance(result, dict) and result.get("message_id") is not None else None
        return "ACCEPTED", message_id, None
    return "FAILED", None, f"HTTP_{response.status_code}"


def send_text(
    *, event_type: str, priority: str, text: str, cooldown_seconds: int = 0,
    reply_markup: dict[str, Any] | None = None, timeout_seconds: int = 20,
    db: PipelineDB | None = None, token: str | None = None, chat_id: str | None = None,
) -> TelegramDeliveryResult:
    """发送文字并记录回执；不会记录 token、URL、响应正文或消息内容。"""
    fingerprint = _fingerprint(event_type, text)
    if _should_suppress(event_type=event_type, fingerprint=fingerprint, cooldown_seconds=cooldown_seconds, db=db):
        _record(event_type=event_type, priority=priority, fingerprint=fingerprint, state="SUPPRESSED", error_kind="DEDUPE", db=db)
        return TelegramDeliveryResult(state="SUPPRESSED", error_kind="DEDUPE", suppressed=True)

    token, chat_id = (token or "").strip(), (chat_id or "").strip()
    if not token or not chat_id:
        token, chat_id = _credentials()
    if not token or not chat_id:
        _record(event_type=event_type, priority=priority, fingerprint=fingerprint, state="FAILED", error_kind="CONFIG_MISSING", db=db)
        return TelegramDeliveryResult(state="FAILED", error_kind="CONFIG_MISSING")
    payload: dict[str, Any] = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        response = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json=payload, timeout=timeout_seconds)
        state, message_id, error_kind = _result_from_response(response)
    except requests.RequestException as exc:
        state, message_id, error_kind = "UNKNOWN", None, type(exc).__name__
    _record(event_type=event_type, priority=priority, fingerprint=fingerprint, state=state, message_id=message_id, error_kind=error_kind, db=db)
    return TelegramDeliveryResult(state=state, message_id=message_id, error_kind=error_kind)


def send_document(
    *, event_type: str, priority: str, path: Path, caption: str, timeout_seconds: int = 120,
    db: PipelineDB | None = None, token: str | None = None, chat_id: str | None = None,
) -> TelegramDeliveryResult:
    """发送附件并记录 API 回执；附件路径仅参与哈希，不写入数据库。"""
    fingerprint = _fingerprint(event_type, caption, path)
    token, chat_id = (token or "").strip(), (chat_id or "").strip()
    if not token or not chat_id:
        token, chat_id = _credentials()
    if not token or not chat_id:
        _record(event_type=event_type, priority=priority, fingerprint=fingerprint, state="FAILED", error_kind="CONFIG_MISSING", db=db)
        return TelegramDeliveryResult(state="FAILED", error_kind="CONFIG_MISSING")
    try:
        with path.open("rb") as source:
            response = requests.post(
                f"https://api.telegram.org/bot{token}/sendDocument",
                data={"chat_id": chat_id, "caption": caption},
                files={"document": (path.name, source)}, timeout=timeout_seconds,
            )
        state, message_id, error_kind = _result_from_response(response)
    except (OSError, requests.RequestException) as exc:
        state, message_id, error_kind = "UNKNOWN", None, type(exc).__name__
    _record(event_type=event_type, priority=priority, fingerprint=fingerprint, state=state, message_id=message_id, error_kind=error_kind, db=db)
    return TelegramDeliveryResult(state=state, message_id=message_id, error_kind=error_kind)


def send_video(
    *, event_type: str, priority: str, path: Path, caption: str, timeout_seconds: int = 120,
    db: PipelineDB | None = None, token: str | None = None, chat_id: str | None = None,
) -> TelegramDeliveryResult:
    """发送审核视频并记录 API 回执；不会将异常 URL 写入日志。"""
    fingerprint = _fingerprint(event_type, caption, path)
    token, chat_id = (token or "").strip(), (chat_id or "").strip()
    if not token or not chat_id:
        token, chat_id = _credentials()
    if not token or not chat_id:
        _record(event_type=event_type, priority=priority, fingerprint=fingerprint, state="FAILED", error_kind="CONFIG_MISSING", db=db)
        return TelegramDeliveryResult(state="FAILED", error_kind="CONFIG_MISSING")
    try:
        with path.open("rb") as source:
            response = requests.post(
                f"https://api.telegram.org/bot{token}/sendVideo",
                data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML", "supports_streaming": "true"},
                files={"video": (path.name, source, "video/mp4")}, timeout=timeout_seconds,
            )
        state, message_id, error_kind = _result_from_response(response)
    except (OSError, requests.RequestException) as exc:
        state, message_id, error_kind = "UNKNOWN", None, type(exc).__name__
    _record(event_type=event_type, priority=priority, fingerprint=fingerprint, state=state, message_id=message_id, error_kind=error_kind, db=db)
    return TelegramDeliveryResult(state=state, message_id=message_id, error_kind=error_kind)
