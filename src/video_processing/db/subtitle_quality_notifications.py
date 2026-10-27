"""字幕告警的持久发件箱；只保存投递事实，不改变视频发布状态。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-27 | Codex | 选中字幕候选按问题摘要幂等入队，租约抢占、失败退避与投递结果持久保存。 |
"""
from __future__ import annotations

import json
import math
import re
import time
import uuid


_SHA = re.compile(r"[0-9a-f]{64}")
MAX_DELIVERY_ATTEMPTS = 6
RETRY_SECONDS = (300, 900, 1800, 3600, 7200)


def _digest(value):
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise ValueError("subtitle warning requires a SHA256 digest")
    return value


def _now(value):
    value = time.time() if value is None else value
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError("invalid subtitle notification clock")
    return float(value)


def _row(row):
    if row is None:
        return None
    value = dict(row)
    value["warning"] = json.loads(value.pop("warning_json"))
    return value


class SubtitleQualityNotificationsDAL:
    def initialize_subtitle_quality_notifications(self):
        with self.get_connection() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS subtitle_quality_notifications (
                    id INTEGER PRIMARY KEY,
                    video_id INTEGER REFERENCES processed_videos(id) ON DELETE SET NULL,
                    youtube_id TEXT NOT NULL, slice_index INTEGER NOT NULL,
                    candidate_sha256 TEXT NOT NULL, summary_sha256 TEXT NOT NULL,
                    warning_json TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'PENDING'
                        CHECK(state IN ('PENDING','PROCESSING','ACCEPTED','FAILED')),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at REAL NOT NULL, claimed_at REAL, claim_token TEXT,
                    last_delivery_state TEXT, last_error_kind TEXT, telegram_message_id TEXT,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    UNIQUE(youtube_id,slice_index,candidate_sha256,summary_sha256));
                CREATE INDEX IF NOT EXISTS subtitle_quality_notification_due
                    ON subtitle_quality_notifications(state,next_attempt_at,id);
            """)

    def enqueue_subtitle_quality_notification(self, youtube_id, slice_index, warning, *, now=None):
        """父进程已验证的完整告警按候选/问题永久幂等；不把旧告警换成新正文。"""
        now = _now(now)
        if (not isinstance(warning, dict) or warning.get("status") != "accepted_with_warnings"
                or not isinstance(warning.get("report"), dict) or type(slice_index) is not int or slice_index < 0):
            raise ValueError("invalid subtitle warning envelope")
        candidate_sha, summary_sha = _digest(warning.get("candidate_sha256")), _digest(warning.get("summary_sha256"))
        encoded = json.dumps(warning, ensure_ascii=False, sort_keys=True, allow_nan=False)
        if len(encoded.encode("utf-8")) > 262144:
            raise ValueError("subtitle warning envelope too large")
        with self.get_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            video = connection.execute(
                "SELECT id FROM processed_videos WHERE youtube_id=? AND slice_index=?",
                (youtube_id, slice_index),
            ).fetchone()
            if video is None:
                raise ValueError("subtitle warning video missing")
            connection.execute("""INSERT OR IGNORE INTO subtitle_quality_notifications
                (video_id,youtube_id,slice_index,candidate_sha256,summary_sha256,warning_json,
                 next_attempt_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                (video["id"], youtube_id, slice_index, candidate_sha, summary_sha, encoded, now, now, now))
            stored = connection.execute("""SELECT * FROM subtitle_quality_notifications
                WHERE youtube_id=? AND slice_index=? AND candidate_sha256=? AND summary_sha256=?""",
                (youtube_id, slice_index, candidate_sha, summary_sha)).fetchone()
            connection.commit()
            return _row(stored)

    def claim_subtitle_quality_notifications(self, limit=4, *, now=None, lease_seconds=120):
        """顺序领取有限告警；崩溃租约过期后可以恢复，已获受理的告警永不再领。"""
        now = _now(now)
        if type(limit) is not int or not 1 <= limit <= 20 or type(lease_seconds) not in (int, float) or not 30 <= lease_seconds <= 3600:
            raise ValueError("invalid subtitle notification claim bounds")
        with self.get_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("""UPDATE subtitle_quality_notifications
                SET state=CASE WHEN attempts>=? THEN 'FAILED' ELSE 'PENDING' END,
                    next_attempt_at=?,claim_token=NULL,claimed_at=NULL,
                    last_delivery_state='UNKNOWN',last_error_kind='STALE_DELIVERY_LEASE',updated_at=?
                WHERE state='PROCESSING' AND claimed_at<=?""",
                (MAX_DELIVERY_ATTEMPTS, now, now, now - lease_seconds))
            rows = connection.execute("""SELECT id FROM subtitle_quality_notifications
                WHERE state='PENDING' AND attempts<? AND next_attempt_at<=?
                ORDER BY next_attempt_at,id LIMIT ?""", (MAX_DELIVERY_ATTEMPTS, now, limit)).fetchall()
            claimed = []
            for item in rows:
                token = uuid.uuid4().hex
                connection.execute("""UPDATE subtitle_quality_notifications
                    SET state='PROCESSING',attempts=attempts+1,claimed_at=?,claim_token=?,updated_at=?
                    WHERE id=? AND state='PENDING'""", (now, token, now, item["id"]))
                claimed.append(_row(connection.execute("SELECT * FROM subtitle_quality_notifications WHERE id=?", (item["id"],)).fetchone()))
            connection.commit()
            return claimed

    def finish_subtitle_quality_notification(self, notification_id, claim_token, delivery_state, *, message_id=None, error_kind=None, now=None):
        """记录 Bot API 结果；FAILED/UNKNOWN 有界退避，绝不等同手机已读。"""
        now = _now(now)
        if delivery_state not in {"ACCEPTED", "SUPPRESSED", "FAILED", "UNKNOWN", "NOT_SENT"}:
            raise ValueError("invalid subtitle notification delivery state")
        if delivery_state == "ACCEPTED" and not str(message_id or "").strip():
            raise ValueError("Telegram API acceptance requires message ID")
        safe_error = str(error_kind or "")
        if not re.fullmatch(r"[A-Za-z0-9_:.-]{0,120}", safe_error):
            safe_error = "DELIVERY_ERROR"
        with self.get_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute("SELECT * FROM subtitle_quality_notifications WHERE id=?", (notification_id,)).fetchone()
            if current is None or current["state"] != "PROCESSING" or current["claim_token"] != claim_token:
                connection.commit()
                return _row(current)
            # SUPPRESSED 只用于既有 ACCEPTED 回执去重，不代表一次新投递。
            accepted = delivery_state in {"ACCEPTED", "SUPPRESSED"}
            attempts = int(current["attempts"])
            state = "ACCEPTED" if accepted else "FAILED" if attempts >= MAX_DELIVERY_ATTEMPTS else "PENDING"
            next_attempt = now if accepted else now + RETRY_SECONDS[min(attempts - 1, len(RETRY_SECONDS) - 1)]
            connection.execute("""UPDATE subtitle_quality_notifications
                SET state=?,next_attempt_at=?,claimed_at=NULL,claim_token=NULL,last_delivery_state=?,
                    last_error_kind=?,telegram_message_id=?,updated_at=? WHERE id=? AND claim_token=?""",
                (state, next_attempt, delivery_state, safe_error or None, str(message_id or "")[:80] or None,
                 now, notification_id, claim_token))
            updated = connection.execute("SELECT * FROM subtitle_quality_notifications WHERE id=?", (notification_id,)).fetchone()
            connection.commit()
            return _row(updated)

    def get_subtitle_quality_notification(self, notification_id):
        with self.get_connection() as connection:
            return _row(connection.execute("SELECT * FROM subtitle_quality_notifications WHERE id=?", (notification_id,)).fetchone())

    def list_subtitle_quality_notifications(self, *, state=None, limit=100):
        """供运维和周报读投递结果；不自动重排视频或重新投稿。"""
        if state not in {None, "PENDING", "PROCESSING", "ACCEPTED", "FAILED"} or type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("invalid subtitle notification query")
        with self.get_connection() as connection:
            rows = connection.execute("""SELECT * FROM subtitle_quality_notifications
                WHERE (? IS NULL OR state=?) ORDER BY id DESC LIMIT ?""", (state, state, limit)).fetchall()
            return [_row(row) for row in rows]
