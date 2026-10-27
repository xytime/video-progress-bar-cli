"""Telegram 自动通知投递与回执账本。

所有返回值只描述 Telegram Bot API 的响应：ACCEPTED 表示 API 已接受，UNKNOWN
表示网络层没有取得可判定响应，绝不推断手机端通知展示或用户已读。

# Modification History
| notification-guard-v1 | 2026-10-26 | Codex | 文字发送前原子持久认领和意图；UNKNOWN不重放，状态不可保存时闭锁。 |
| Version | Date | Author | Description |
| cover-source-v1 | 2026-10-15 | Codex | 贯通封面版本、投稿绑定与来源展示回执。 |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-24 | Codex | 新增自动通知回执、去重与秘密安全的错误分类。 |
| 1.1.0 | 2026-08-24 | Codex | UNKNOWN 不再被视为已送达；仅有 message_id 的 Bot API 响应可记为 ACCEPTED。 |
| 1.1.1 | 2026-09-06 | Codex | 仅对建连超时有界重试并回卷附件；保留秘密安全的 SSL 异常链类别。 |
| 1.2.0 | 2026-09-19 | Antigravity | 新增 send_photo 支持，用于发送互动评论带证据大图的图文通知。 |
"""

from __future__ import annotations

import hashlib
import logging
import time
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


def _fingerprint(event_type: str, dedupe_key: str, attachment: Path | None = None) -> str:
    digest = hashlib.sha256()
    digest.update(event_type.encode("utf-8"))
    digest.update(b"\0")
    digest.update(dedupe_key.encode("utf-8"))
    if attachment is not None:
        digest.update(b"\0")
        digest.update(attachment.name.encode("utf-8"))
        digest.update(str(attachment.stat().st_size).encode("ascii"))
    return digest.hexdigest()


def _record(
    *, event_type: str, priority: str, fingerprint: str, state: str,
    message_id: str | None = None, error_kind: str | None = None, db: PipelineDB | None = None,
    cover_context: dict | None = None,
) -> int | None:
    try:
        row = (db or PipelineDB()).record_telegram_notification_receipt(
            event_type=event_type, priority=priority, content_sha256=fingerprint,
            delivery_state="FAILED" if state == "NOT_SENT" else state, telegram_message_id=message_id, error_kind=error_kind,
            **({"cover_context": cover_context} if cover_context else {}),
        )
        return row['id']
    except Exception as exc:  # 回执故障不能影响主业务，但不得记录可能含 URL 的异常文本。
        logger.error("Telegram receipt recording failed: %s", type(exc).__name__)
        return None


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
        if message_id:
            return "ACCEPTED", message_id, None
        # HTTP 200 不是可审计投递回执；没有消息 ID 时无法对照 Telegram 侧事实。
        return "UNKNOWN", None, "MISSING_MESSAGE_ID"
    return "FAILED", None, f"HTTP_{response.status_code}"


def _post_with_connect_retry(url: str, **kwargs):
    """仅重试 requests 明确保证尚未发送的建连超时；读超时/SSL 不盲重发。"""
    files = kwargs.get("files", {})
    positions = [(value[1], value[1].tell()) for value in files.values()]
    for attempt in range(3):
        for stream, position in positions:
            stream.seek(position)
        try:
            return requests.post(url, **kwargs)
        except requests.ConnectTimeout:
            if attempt == 2:
                raise
            from .utils.retry_policy import backoff_seconds
            time.sleep(backoff_seconds(attempt + 1, base=1, cap=30))


def _transport_error(exc: Exception) -> tuple[str, str]:
    # ConnectTimeout 明确未发出；其他传输异常可能发生在服务器接受之后。
    state = "NOT_SENT" if isinstance(exc, requests.ConnectTimeout) else "UNKNOWN"
    # 不输出带 bot token 的 URL；记录 SSL 底层类别便于下次区分证书和 EOF。
    kinds = [type(exc).__name__]
    pending = [exc]
    seen = set()
    while pending and len(seen) < 12:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        for child in (getattr(current, "reason", None), getattr(current, "__cause__", None),
                      getattr(current, "__context__", None), *getattr(current, "args", ())):
            if isinstance(child, BaseException):
                kind = type(child).__name__
                if kind not in kinds:
                    kinds.append(kind)
                pending.append(child)
    return state, ":".join(kinds)


def send_text(
    *, event_type: str, priority: str, text: str, cooldown_seconds: int = 0,
    reply_markup: dict[str, Any] | None = None, timeout_seconds: int = 20,
    dedupe_key: str | None = None, db: PipelineDB | None = None,
    token: str | None = None, chat_id: str | None = None,
    cover_context: dict | None = None,
) -> TelegramDeliveryResult:
    """发送文字并记录回执；不会记录 token、URL、响应正文或消息内容。"""
    if cover_context:
        from html import escape
        from video_processing.cover_provenance import notification_text
        text += "\n" + escape(notification_text(cover_context))
    fingerprint = _fingerprint(event_type, dedupe_key or text)
    if _should_suppress(event_type=event_type, fingerprint=fingerprint, cooldown_seconds=cooldown_seconds, db=db):
        _record(event_type=event_type, priority=priority, fingerprint=fingerprint, state='SUPPRESSED', error_kind='DEDUPE', db=db, cover_context=cover_context)
        return TelegramDeliveryResult(state='SUPPRESSED', error_kind='DEDUPE', suppressed=True)
    token, chat_id = (token or "").strip(), (chat_id or "").strip()
    if not token or not chat_id:
        token, chat_id = _credentials()
    if not token or not chat_id:
        _record(event_type=event_type, priority=priority, fingerprint=fingerprint, state="FAILED", error_kind="CONFIG_MISSING", db=db, cover_context=cover_context)
        return TelegramDeliveryResult(state="FAILED", error_kind="CONFIG_MISSING")
    try:
        db = db or PipelineDB()
        claim = db.claim_notification_delivery(event_type=event_type, fingerprint=fingerprint,
            priority=priority, cooldown_seconds=cooldown_seconds, lease_seconds=timeout_seconds)
        if not claim['allowed']:
            reason=claim['reason']
            _record(event_type=event_type,priority=priority,fingerprint=fingerprint,state='SUPPRESSED',
                error_kind=reason,db=db,cover_context=cover_context)
            # 仅成功去重表示已有受理；UNKNOWN/在途闭锁不能让上层发件箱记成成功。
            blocked_state = 'SUPPRESSED' if reason == 'DEDUPE' else 'UNKNOWN' if reason.startswith('PRIOR_') else 'NOT_SENT'
            return TelegramDeliveryResult(state=blocked_state,error_kind=reason,suppressed=True)
        if not db.record_notification_send_intent(claim['token']):
            return TelegramDeliveryResult(state='NOT_SENT',error_kind='CLAIM_LOST_BEFORE_SEND',suppressed=True)
    except Exception as exc:
        logger.error('Telegram durable admission unavailable: %s',type(exc).__name__)
        return TelegramDeliveryResult(state='NOT_SENT',error_kind='DELIVERY_STATE_UNAVAILABLE',suppressed=True)
    payload: dict[str, Any] = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        response = _post_with_connect_retry(f"https://api.telegram.org/bot{token}/sendMessage", json=payload, timeout=timeout_seconds)
        state, message_id, error_kind = _result_from_response(response)
    except requests.RequestException as exc:
        state, error_kind = _transport_error(exc)
        message_id = None
    receipt_id=_record(event_type=event_type, priority=priority, fingerprint=fingerprint, state=state, message_id=message_id, error_kind=error_kind, db=db, cover_context=cover_context)
    try:
        persisted=receipt_id is not None and db.complete_notification_delivery(claim['token'],
            state='FAILED' if state=='NOT_SENT' else state,receipt_id=receipt_id,error_kind=error_kind)
    except Exception as exc:
        logger.error('Telegram outcome persistence unavailable: %s',type(exc).__name__)
        persisted=False
    if not persisted:
        # API结果与本地持久化分开；已落盘意图继续阻止任何自动重放。
        error_kind='RECEIPT_PERSISTENCE_UNCONFIRMED'
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
            response = _post_with_connect_retry(
                f"https://api.telegram.org/bot{token}/sendDocument",
                data={"chat_id": chat_id, "caption": caption},
                files={"document": (path.name, source)}, timeout=timeout_seconds,
            )
        state, message_id, error_kind = _result_from_response(response)
    except (OSError, requests.RequestException) as exc:
        state, error_kind = _transport_error(exc)
        message_id = None
    _record(event_type=event_type, priority=priority, fingerprint=fingerprint, state=state, message_id=message_id, error_kind=error_kind, db=db)
    return TelegramDeliveryResult(state=state, message_id=message_id, error_kind=error_kind)


def send_video(
    *, event_type: str, priority: str, path: Path, caption: str, timeout_seconds: int = 120,
    db: PipelineDB | None = None, token: str | None = None, chat_id: str | None = None,
    cover_context: dict | None = None,
) -> TelegramDeliveryResult:
    """发送审核视频并记录 API 回执；不会将异常 URL 写入日志。"""
    if cover_context:
        from html import escape
        from video_processing.cover_provenance import notification_text
        caption += "\n" + escape(notification_text(cover_context))
    fingerprint = _fingerprint(event_type, caption, path)
    token, chat_id = (token or "").strip(), (chat_id or "").strip()
    if not token or not chat_id:
        token, chat_id = _credentials()
    if not token or not chat_id:
        _record(event_type=event_type, priority=priority, fingerprint=fingerprint, state="FAILED", error_kind="CONFIG_MISSING", db=db, cover_context=cover_context)
        return TelegramDeliveryResult(state="FAILED", error_kind="CONFIG_MISSING")
    try:
        with path.open("rb") as source:
            response = _post_with_connect_retry(
                f"https://api.telegram.org/bot{token}/sendVideo",
                data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML", "supports_streaming": "true"},
                files={"video": (path.name, source, "video/mp4")}, timeout=timeout_seconds,
            )
        state, message_id, error_kind = _result_from_response(response)
    except (OSError, requests.RequestException) as exc:
        state, error_kind = _transport_error(exc)
        message_id = None
    _record(event_type=event_type, priority=priority, fingerprint=fingerprint, state=state, message_id=message_id, error_kind=error_kind, db=db, cover_context=cover_context)
    return TelegramDeliveryResult(state=state, message_id=message_id, error_kind=error_kind)


def send_photo(
    *, event_type: str, priority: str, path: Path, caption: str, timeout_seconds: int = 60,
    db: PipelineDB | None = None, token: str | None = None, chat_id: str | None = None,
) -> TelegramDeliveryResult:
    """发送图片照片并记录 API 回执。"""
    fingerprint = _fingerprint(event_type, caption, path)
    token, chat_id = (token or "").strip(), (chat_id or "").strip()
    if not token or not chat_id:
        token, chat_id = _credentials()
    if not token or not chat_id:
        _record(event_type=event_type, priority=priority, fingerprint=fingerprint, state="FAILED", error_kind="CONFIG_MISSING", db=db)
        return TelegramDeliveryResult(state="FAILED", error_kind="CONFIG_MISSING")
    try:
        with path.open("rb") as source:
            response = _post_with_connect_retry(
                f"https://api.telegram.org/bot{token}/sendPhoto",
                data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
                files={"photo": (path.name, source, "image/png")}, timeout=timeout_seconds,
            )
        state, message_id, error_kind = _result_from_response(response)
    except (OSError, requests.RequestException) as exc:
        state, error_kind = _transport_error(exc)
        message_id = None
    _record(event_type=event_type, priority=priority, fingerprint=fingerprint, state=state, message_id=message_id, error_kind=error_kind, db=db)
    return TelegramDeliveryResult(state=state, message_id=message_id, error_kind=error_kind)
