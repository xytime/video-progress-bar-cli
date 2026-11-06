"""字幕失败的持久退避与显式修复账；不调用模型、不签发投稿授权。

依赖：database/eligibility → 本模块 → Python 标准库。所有 SQL 留在 DAL 内。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| manual-release-v1 | 2026-11-02 | Codex | 保留错误和历史，以具名证据 CAS 放行旧/新失败并原子消费一次领取。 |
| subtitle-manual-gate-v2 | 2026-11-02 | Codex | 人工复核分类硬锁，旧人工错误只读识别，不因冷却到期自动释放。 |
| 1.0.0 | 2026-10-27 | Codex | 按源与翻译合同保存失败链、幂等尝试、冷却及具名修复释放。 |
"""
from __future__ import annotations

import json
import hashlib
import math
import re
import time
import uuid


CATEGORIES = frozenset({"network", "quota", "busy", "timeout", "authentication", "quality", "budget", "unavailable", "review"})
SERVICE_FAILURES = frozenset({"network", "quota", "timeout", "unavailable"})
PRE_SUBMISSION_STATES = frozenset({"PENDING", "PROCESSING", "DOWNLOADING", "COPYWRITING", "TRANSCRIBING", "RENDERING", "FAILED"})
SHA256 = re.compile(r"[0-9a-f]{64}")
MAX_CHAIN_SECONDS = 24 * 3600
MANUAL_REVIEW_MARKERS = ('需单独审查', '需人工处理', '安全修补边界', 'binding mismatch',
                        'subtitle_checkpoint_binding', 'caption_safety_review', 'vocabulary_outro_review',
                        'translation_budget_preflight', 'NativeCaptionReviewRequired', '[NativeCaptionReview]',
                        '需先人工规范化', '原字幕位置或文字不确定', 'SUBTITLE_NEEDS_REPAIR:',
                        'native_caption_review', 'caption_source_too_narrow', 'caption_frame_uncertain',
                        'translation_budget_exhausted',
                        'All subtitle translation providers failed or were blocked.')


def _manual_review_sql(column):
    return '(' + ' OR '.join(f"instr(COALESCE({column},''),'{marker}')>0"
                             for marker in MANUAL_REVIEW_MARKERS) + ')'


def _unreleased_manual_event_sql(video_id):
    """旧失败事件是稳定证据；仅晚于该事件的具名释放可以解除，普通文案更新不能。"""
    return ("EXISTS (SELECT 1 FROM publishing_failure_events f WHERE f.video_id=" + video_id +
            " AND " + _manual_review_sql('f.reason') +
            " AND NOT EXISTS (SELECT 1 FROM subtitle_recovery_events r WHERE r.video_id=f.video_id"
            " AND r.event_type='RELEASED' AND r.state='RELEASED' AND " + _release_available_sql('r') +
            " AND (f.id<=json_extract(r.details,'$.manual_failure_event_id') OR"
            " (json_extract(r.details,'$.manual_failure_event_id') IS NULL AND"
            " r.created_at >= (julianday(f.failed_at)-2440587.5)*86400.0))))")


def _release_available_sql(alias):
    # 新版授权消费后只认同次字幕成功；旧版事件沿用原边界，不反向改写历史。
    return ("(json_extract(" + alias + ".details,'$.release_version') IS NULL OR "
            "(json_extract(" + alias + ".details,'$.expires_at')>CAST(strftime('%s','now') AS REAL) AND NOT EXISTS (SELECT 1 FROM subtitle_recovery_events used WHERE used.event_type='CLAIMED'"
            " AND used.video_id=" + alias + ".video_id AND json_extract(used.details,'$.release_event_id')=" + alias + ".id)) OR "
            "EXISTS (SELECT 1 FROM subtitle_recovery_events done WHERE done.event_type='RESOLVED'"
            " AND done.video_id=" + alias + ".video_id AND json_extract(done.details,'$.release_event_id')=" + alias + ".id))")


def _manual_error_blocked_sql(video_id):
    column = video_id.rsplit('.', 1)[0] + '.error_msg'
    return ("(" + _manual_review_sql(column) + " AND NOT EXISTS (SELECT 1 FROM subtitle_recovery_events r"
            " WHERE r.video_id=" + video_id + " AND r.event_type='RELEASED' AND r.state='RELEASED'"
            " AND json_extract(r.details,'$.review_error')=COALESCE(" + column + ",'')"
            " AND " + _release_available_sql('r') + "))")


def _consumed_trial_sql(video_id):
    return ("EXISTS (SELECT 1 FROM subtitle_recovery_events used WHERE used.video_id=" + video_id +
            " AND (used.event_type='CLAIMED' OR (used.event_type='RELEASED' AND json_extract(used.details,'$.expires_at')<=CAST(strftime('%s','now') AS REAL))) AND used.id=(SELECT MAX(e.id) FROM subtitle_recovery_events e"
            " WHERE e.video_id=" + video_id + " AND e.event_type IN ('RELEASED','CLAIMED','RESOLVED')))")


def subtitle_manual_blocked_sql(video_id):
    return '(' + _manual_error_blocked_sql(video_id) + ' OR ' + _unreleased_manual_event_sql(video_id) + ' OR ' + _consumed_trial_sql(video_id) + ')'


def subtitle_recovery_gate_sql(video_id: str) -> str:
    """仅供 DAL 固定列名调用；已到期 WAITING 可领，过期链须显式修复。"""
    if video_id not in {"pv.id", "processed_videos.id"}:
        raise ValueError("unsupported subtitle gate column")
    return ("NOT " + subtitle_manual_blocked_sql(video_id) +
            " AND NOT EXISTS (SELECT 1 FROM subtitle_recovery s WHERE s.video_id=" + video_id +
            " AND s.is_current=1 AND (s.state='NEEDS_REPAIR' OR (s.state='WAITING' AND "
            "(s.next_attempt_at>CAST(strftime('%s','now') AS REAL) OR "
            "s.expires_at<=CAST(strftime('%s','now') AS REAL)))))")


def _sha(value) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise ValueError("subtitle recovery requires a SHA256 digest")
    return value


def _text(value, limit=240) -> str:
    return " ".join(str(value or "").split())[:limit]


def _receipt(receipt, receipt_path, receipt_sha) -> dict:
    if not isinstance(receipt, dict):
        raise ValueError("invalid subtitle failure receipt")
    attempt_id = str(receipt.get("attempt_id", ""))
    try:
        attempt_id = str(uuid.UUID(attempt_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("invalid subtitle attempt identity") from exc
    category = receipt.get("category")
    if category not in CATEGORIES:
        raise ValueError("invalid subtitle failure category")
    retry_at = receipt.get("retry_at", 0)
    if type(retry_at) not in (int, float) or not math.isfinite(retry_at) or retry_at < 0:
        raise ValueError("invalid subtitle retry time")
    details = []
    for item in receipt.get("quality_details") or ():
        if not isinstance(item, dict):
            continue
        number, source_id = item.get("segment_number"), item.get("source_id")
        if type(number) is not int or number < 1 or type(source_id) is not int or source_id < 0:
            continue
        details.append(dict(segment_number=number, source_id=source_id,
                            **{k: _text(item.get(k), 120) for k in ("code", "source_signal", "translation_signal")}))
        if len(details) == 10:
            break
    path = str(receipt_path)
    if not path or len(path) > 4096 or any(c in path for c in "\r\n\0"):
        raise ValueError("invalid subtitle receipt path")
    return dict(attempt_id=attempt_id, input_sha256=_sha(receipt.get("input_sha256")),
                contract_sha256=_sha(receipt.get("contract_sha256")),
                failure_fingerprint=_sha(receipt.get("failure_fingerprint")),
                category=category, code=_text(receipt.get("code"), 120), retry_at=float(retry_at),
                quality_details=details, evidence_path=_text(receipt.get("evidence_path"), 4096),
                receipt_path=path, receipt_sha=_sha(receipt_sha))


class SubtitleRecoveryDAL:
    def initialize_subtitle_recovery(self) -> None:
        """增量建表；保留旧链，当前链独占一个任务的调度门禁。"""
        with self.get_connection() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS subtitle_recovery (
                    id INTEGER PRIMARY KEY,
                    video_id INTEGER NOT NULL REFERENCES processed_videos(id) ON DELETE CASCADE,
                    input_sha256 TEXT NOT NULL, contract_sha256 TEXT NOT NULL,
                    is_current INTEGER NOT NULL DEFAULT 1 CHECK(is_current IN (0,1)),
                    state TEXT NOT NULL CHECK(state IN ('WAITING','NEEDS_REPAIR','RELEASED','RESOLVED')),
                    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count BETWEEN 0 AND 3),
                    chain_started_at REAL NOT NULL, expires_at REAL NOT NULL, next_attempt_at REAL,
                    failure_fingerprint TEXT NOT NULL, category TEXT NOT NULL, code TEXT NOT NULL,
                    quality_details TEXT NOT NULL DEFAULT '[]',
                    last_receipt_path TEXT NOT NULL, last_receipt_sha TEXT NOT NULL,
                    evidence_path TEXT NOT NULL DEFAULT '',
                    released_receipt_sha TEXT, updated_at REAL NOT NULL,
                    UNIQUE(video_id,input_sha256,contract_sha256));
                CREATE UNIQUE INDEX IF NOT EXISTS subtitle_recovery_current
                    ON subtitle_recovery(video_id) WHERE is_current=1;
                CREATE TABLE IF NOT EXISTS subtitle_recovery_events (
                    id INTEGER PRIMARY KEY,
                    video_id INTEGER REFERENCES processed_videos(id) ON DELETE SET NULL,
                    chain_id INTEGER REFERENCES subtitle_recovery(id) ON DELETE SET NULL,
                    youtube_id TEXT NOT NULL, slice_index INTEGER NOT NULL,
                    event_type TEXT NOT NULL, attempt_id TEXT UNIQUE,
                    state TEXT NOT NULL, receipt_sha TEXT, receipt_path TEXT,
                    details TEXT NOT NULL, created_at REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS subtitle_recovery_event_video ON subtitle_recovery_events(video_id,event_type);
                CREATE TRIGGER IF NOT EXISTS subtitle_release_claim_once AFTER UPDATE OF status ON processed_videos
                WHEN NEW.status IN ('PROCESSING','PUBLISH_PRECHECK') AND OLD.status='PENDING'
                BEGIN
                    INSERT INTO subtitle_recovery_events(video_id,chain_id,youtube_id,slice_index,event_type,state,
                        receipt_sha,receipt_path,details,created_at)
                    SELECT r.video_id,r.chain_id,r.youtube_id,r.slice_index,'CLAIMED','CLAIMED',r.receipt_sha,r.receipt_path,
                        json_object('release_event_id',r.id),CAST(strftime('%s','now') AS REAL)
                    FROM subtitle_recovery_events r WHERE r.video_id=NEW.id AND r.event_type='RELEASED'
                        AND r.id=(SELECT MAX(latest.id) FROM subtitle_recovery_events latest WHERE latest.video_id=NEW.id AND latest.event_type='RELEASED')
                        AND json_extract(r.details,'$.release_version')=1
                        AND NOT EXISTS (SELECT 1 FROM subtitle_recovery_events used
                            WHERE used.video_id=r.video_id AND used.event_type='CLAIMED'
                            AND json_extract(used.details,'$.release_event_id')=r.id);
                END;
            """)
            columns = {r[1] for r in c.execute('PRAGMA table_info(subtitle_recovery)')}
            if 'evidence_path' not in columns:
                c.execute("ALTER TABLE subtitle_recovery ADD COLUMN evidence_path TEXT NOT NULL DEFAULT ''")

    @staticmethod
    def _subtitle_row(c, video_id: int):
        return c.execute("SELECT * FROM subtitle_recovery WHERE video_id=? AND is_current=1", (video_id,)).fetchone()

    @staticmethod
    def _subtitle_result(row, **extra) -> dict | None:
        if row is None:
            return None
        result = dict(row)
        result["quality_details"] = json.loads(result["quality_details"])
        return result | extra

    @staticmethod
    def _subtitle_eligible(c, video) -> bool:
        """写事务内重新确认原任务边界；任何平台行均保守视为投稿保护。"""
        if not video or video["status"] not in PRE_SUBMISSION_STATES:
            return False
        if (video["source"] or "AUTO") not in {"AUTO", "MANUAL", "KEYWORD"}:
            return False
        if not c.execute("SELECT keyword_allowed(?,?)", (video["source"], video["youtube_id"])).fetchone()[0]:
            return False
        if c.execute("SELECT 1 FROM blacklisted_videos WHERE youtube_id=?", (video["youtube_id"],)).fetchone():
            return False
        if c.execute("SELECT 1 FROM recommended_channels WHERE channel_id=? AND status='BLACKLISTED'", (video["channel_id"],)).fetchone():
            return False
        vid = video["id"]
        for table in ("wechat_publications", "wechat_submission_attempts", "wechat_publications_historical_archive", "douyin_publications", "kuaishou_publications"):
            if c.execute(f"SELECT 1 FROM {table} WHERE video_id=? LIMIT 1", (vid,)).fetchone():
                return False
        # subject_id 是稳定身份；兼容早期平台行只绑定主体、video_id 为空的记录。
        # historical_archive 的 video_id 为 NOT NULL，且该表没有 subject_id。
        for table in ("wechat_publications", "wechat_submission_attempts"):
            if c.execute(f"SELECT 1 FROM {table} p JOIN publication_subjects s ON s.id=p.subject_id WHERE s.video_id=? LIMIT 1", (vid,)).fetchone():
                return False
        return True

    @classmethod
    def _subtitle_blocker_in(cls, c, video_id: int, now: float | None = None) -> dict | None:
        row = cls._subtitle_row(c, video_id)
        video = c.execute('SELECT * FROM processed_videos WHERE id=?', (video_id,)).fetchone()
        blocked_error = c.execute('SELECT ' + _manual_error_blocked_sql('pv.id') +
                                  ' FROM processed_videos pv WHERE pv.id=?', (video_id,)).fetchone()
        marker = next((m for m in MANUAL_REVIEW_MARKERS if video and m in (video['error_msg'] or '')), None) if blocked_error and blocked_error[0] else None
        if not marker and c.execute('SELECT ' + _unreleased_manual_event_sql('?'), (video_id,)).fetchone()[0]:
            marker = 'unreleased_manual_failure_event'
        # 无 recovery 行且只有 error_msg 的旧失败同样只允许一次；普通清文案不能续杯。
        if not marker and video and video['status'] in {'PENDING', 'FAILED'}:
            if c.execute('SELECT '+_consumed_trial_sql('?'), (video_id,video_id)).fetchone()[0]:
                marker = 'manual_trial_consumed_or_expired'
        if marker:
            # 历史日志只读识别，不迁移失败记录、不清账本，也不受旧 WAITING 到期影响。
            return dict(code='SUBTITLE_NEEDS_REPAIR', state='NEEDS_REPAIR', next_attempt_at=None,
                        reason=f'字幕需人工复核，停止出片（{marker}）；原失败证据保留，禁止自动重跑',
                        failure_code=row['code'] if row else 'legacy_caption_review',
                        last_receipt_sha=row['last_receipt_sha'] if row else None,
                        last_receipt_path=row['last_receipt_path'] if row else '',
                        quality_details=json.loads(row['quality_details']) if row else [])
        if row is None or row["state"] in {"RELEASED", "RESOLVED"}:
            return None
        now = time.time() if now is None else now
        repair = row["state"] == "NEEDS_REPAIR" or row["expires_at"] <= now
        if not repair and row["next_attempt_at"] <= now:
            return None
        details = json.loads(row['quality_details'])
        locations = '、'.join(str(d['segment_number']) for d in details)
        diagnostic = row['code'] + (f'；段 {locations}' if locations else '')
        return dict(code="SUBTITLE_NEEDS_REPAIR" if repair else "SUBTITLE_BACKOFF",
                    reason=("字幕翻译需要修复后具名恢复" if repair else "字幕翻译服务冷却尚未到期") + f'（{diagnostic}）',
                    state="NEEDS_REPAIR" if repair else "WAITING", next_attempt_at=None if repair else row["next_attempt_at"],
                    attempt_count=row["attempt_count"], expires_at=row["expires_at"],
                    failure_fingerprint=row["failure_fingerprint"], last_receipt_sha=row["last_receipt_sha"],
                    last_receipt_path=row['last_receipt_path'], evidence_path=row['evidence_path'],
                    quality_details=details, failure_code=row['code'])

    def get_subtitle_recovery(self, video_id: int) -> dict | None:
        """只读返回当前链；过期的 WAITING 不在读取时写库。"""
        with self.get_connection() as c:
            return self._subtitle_result(self._subtitle_row(c, video_id))

    def subtitle_recovery_blocker(self, video_id: int) -> dict | None:
        """统一显示与领取门禁；到期 WAITING 可领，过期链需显式修复。"""
        with self.get_connection() as c:
            return self._subtitle_blocker_in(c, video_id)

    def expire_subtitle_recoveries(self, limit: int = 20) -> list[dict]:
        """既有调度轮收敛过期等待；仅处理无进程、无投稿证据的待领任务。"""
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("invalid subtitle expiry batch limit")
        now = time.time()
        expired = []
        with self.get_connection() as c:
            c.execute("BEGIN IMMEDIATE")
            candidates = c.execute("""SELECT s.video_id FROM subtitle_recovery s
                JOIN processed_videos pv ON pv.id=s.video_id
                WHERE s.is_current=1 AND s.state='WAITING' AND s.expires_at<=?
                AND pv.status='PENDING' AND pv.process_pid IS NULL
                ORDER BY s.expires_at,s.id""", (now,))
            for candidate in candidates:
                video = c.execute("SELECT * FROM processed_videos WHERE id=?", (candidate["video_id"],)).fetchone()
                if not self._subtitle_eligible(c, video):
                    continue
                row = self._subtitle_row(c, video["id"])
                c.execute("UPDATE subtitle_recovery SET state='NEEDS_REPAIR',next_attempt_at=NULL,updated_at=? WHERE id=?", (now, row["id"]))
                c.execute("""UPDATE processed_videos SET status='FAILED',
                    error_msg='SUBTITLE_NEEDS_REPAIR: 字幕自动恢复超过24小时，需具名修复',
                    updated_at=CURRENT_TIMESTAMP WHERE id=?""", (video["id"],))
                self._subtitle_transition_event(c, video, row, "NEEDS_REPAIR", event_type="EXPIRED")
                expired.append(self._subtitle_result(self._subtitle_row(c, video["id"]),
                    youtube_id=video["youtube_id"], slice_index=video["slice_index"], notify=True))
                if len(expired) == limit:
                    break
        return expired

    def record_subtitle_failure(self, youtube_id: str, slice_index: int, receipt: dict,
                                receipt_path: str, receipt_sha: str) -> dict | None:
        """幂等记录本次安全失败；未提交任务才可回队，不消费全局 retry_count。"""
        safe = _receipt(receipt, receipt_path, receipt_sha)
        now = time.time()
        with self.get_connection() as c:
            c.execute("BEGIN IMMEDIATE")
            video = c.execute("SELECT * FROM processed_videos WHERE youtube_id=? AND slice_index=?", (youtube_id, slice_index)).fetchone()
            if not self._subtitle_eligible(c, video):
                return None
            old_event = c.execute("SELECT * FROM subtitle_recovery_events WHERE attempt_id=?", (safe["attempt_id"],)).fetchone()
            if old_event:
                if old_event["video_id"] != video["id"] or old_event["receipt_sha"] != safe["receipt_sha"]:
                    raise ValueError("subtitle attempt identity collision")
                return self._subtitle_result(self._subtitle_row(c, video["id"]), deduplicated=True, notify=False)
            current = self._subtitle_row(c, video["id"])
            old = c.execute("SELECT * FROM subtitle_recovery WHERE video_id=? AND input_sha256=? AND contract_sha256=?",
                            (video["id"], safe["input_sha256"], safe["contract_sha256"])).fetchone()
            # 未修复的当前链不能因换合同或换错误分类自动获得新预算。
            blocked_current = current is not None and (current["state"] == "NEEDS_REPAIR" or
                              (current["state"] == "WAITING" and current["expires_at"] <= now))
            if blocked_current and (old is None or old["id"] != current["id"]):
                c.execute("UPDATE subtitle_recovery SET state='NEEDS_REPAIR',next_attempt_at=NULL,updated_at=? WHERE id=?", (now, current["id"]))
                c.execute("""INSERT INTO subtitle_recovery_events(video_id,chain_id,youtube_id,slice_index,event_type,attempt_id,
                    state,receipt_sha,receipt_path,details,created_at) VALUES(?,?,?,?,?,?,'NEEDS_REPAIR',?,?,?,?)""",
                          (video["id"], current["id"], youtube_id, slice_index, "SUPPRESSED", safe["attempt_id"],
                           safe["receipt_sha"], safe["receipt_path"], json.dumps(safe, ensure_ascii=False), now))
                c.execute("UPDATE processed_videos SET status='FAILED',error_msg='SUBTITLE_NEEDS_REPAIR: 原字幕失败链尚未具名修复',updated_at=CURRENT_TIMESTAMP WHERE id=?", (video["id"],))
                current = self._subtitle_row(c, video["id"])
                return self._subtitle_result(current, deduplicated=False, suppressed=True, notify=False)
            count = old["attempt_count"] if old else 0
            started = old["chain_started_at"] if old else now
            expires = old["expires_at"] if old else now + MAX_CHAIN_SECONDS
            suppressed = old is not None and old["state"] == "NEEDS_REPAIR"
            if not suppressed and safe["category"] in SERVICE_FAILURES:
                count = min(3, count + 1)
            repair = (suppressed or expires <= now or safe["retry_at"] > now + MAX_CHAIN_SECONDS or
                      safe["category"] in {"authentication", "quality", "budget", "review"} or count >= 3)
            state = "NEEDS_REPAIR" if repair else "WAITING"
            due = None if repair else max(safe["retry_at"], now + (60 if safe["category"] == "busy" else (300 if count == 1 else 900)))
            if due is not None and due >= expires:
                state, due = "NEEDS_REPAIR", None
            notify = not suppressed and (current is None or current["state"] != state or
                                         current["failure_fingerprint"] != safe["failure_fingerprint"])
            if suppressed and old["is_current"] != 1:
                c.execute("UPDATE subtitle_recovery SET is_current=0 WHERE video_id=? AND is_current=1", (video["id"],))
                c.execute("UPDATE subtitle_recovery SET is_current=1 WHERE id=?", (old["id"],))
            if not suppressed:
                c.execute("UPDATE subtitle_recovery SET is_current=0 WHERE video_id=? AND is_current=1", (video["id"],))
                values = (video["id"], safe["input_sha256"], safe["contract_sha256"], state, count, started, expires, due,
                          safe["failure_fingerprint"], safe["category"], safe["code"], json.dumps(safe["quality_details"], ensure_ascii=False),
                          safe["receipt_path"], safe["receipt_sha"], safe['evidence_path'], now)
                c.execute("""INSERT INTO subtitle_recovery(video_id,input_sha256,contract_sha256,is_current,state,attempt_count,
                    chain_started_at,expires_at,next_attempt_at,failure_fingerprint,category,code,quality_details,last_receipt_path,last_receipt_sha,evidence_path,updated_at)
                    VALUES(?,?,?,1,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(video_id,input_sha256,contract_sha256) DO UPDATE SET
                    is_current=1,state=excluded.state,attempt_count=excluded.attempt_count,next_attempt_at=excluded.next_attempt_at,
                    failure_fingerprint=excluded.failure_fingerprint,category=excluded.category,code=excluded.code,
                    quality_details=excluded.quality_details,last_receipt_path=excluded.last_receipt_path,
                    last_receipt_sha=excluded.last_receipt_sha,evidence_path=excluded.evidence_path,updated_at=excluded.updated_at""", values)
            row = self._subtitle_row(c, video["id"])
            c.execute("""INSERT INTO subtitle_recovery_events(video_id,chain_id,youtube_id,slice_index,event_type,attempt_id,
                state,receipt_sha,receipt_path,details,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                      (video["id"], row["id"], youtube_id, slice_index, "SUPPRESSED" if suppressed else "FAILURE", safe["attempt_id"],
                       row["state"], safe["receipt_sha"], safe["receipt_path"], json.dumps(safe, ensure_ascii=False), now))
            reason = "SUBTITLE_NEEDS_REPAIR: 字幕翻译需修复后恢复" if row["state"] == "NEEDS_REPAIR" else "SUBTITLE_BACKOFF: 字幕翻译服务等待重试"
            c.execute("UPDATE processed_videos SET status=?,error_msg=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                      ("FAILED" if row["state"] == "NEEDS_REPAIR" else "PENDING", reason + ": " + row["code"], video["id"]))
            return self._subtitle_result(row, deduplicated=False, suppressed=suppressed, notify=notify)

    def resolve_subtitle_recovery(self, video_id: int, input_sha256: str | None = None,
                                  contract_sha256: str | None = None) -> bool:
        """正常字幕完成后的具名回写；不清历史、不修改任务状态或投稿授权。"""
        with self.get_connection() as c:
            c.execute("BEGIN IMMEDIATE")
            video = c.execute("SELECT * FROM processed_videos WHERE id=?", (video_id,)).fetchone()
            row = self._subtitle_row(c, video_id)
            if not self._subtitle_eligible(c, video):
                return False
            release = c.execute("SELECT * FROM subtitle_recovery_events WHERE video_id=? AND event_type='RELEASED' ORDER BY id DESC LIMIT 1", (video_id,)).fetchone()
            if row is None:
                if not release or input_sha256 is None or video['status'] not in {'PROCESSING','DOWNLOADING','COPYWRITING','TRANSCRIBING','RENDERING'}:
                    return False
                _sha(input_sha256)
                if not c.execute("SELECT 1 FROM subtitle_recovery_events WHERE video_id=? AND event_type='CLAIMED' AND json_extract(details,'$.release_event_id')=?", (video_id, release['id'])).fetchone():
                    return False
                if c.execute("SELECT 1 FROM subtitle_recovery_events WHERE video_id=? AND event_type='RESOLVED' AND json_extract(details,'$.release_event_id')=?", (video_id, release['id'])).fetchone():
                    return False
                self._subtitle_transition_event(c, video, None, 'RESOLVED', details={'release_event_id': release['id'], 'input_sha256': input_sha256})
                return True
            if row['state'] == 'RESOLVED':
                return False
            if (input_sha256 is not None and row["input_sha256"] != input_sha256 or
                    contract_sha256 is not None and row["contract_sha256"] != contract_sha256):
                return False
            c.execute("UPDATE subtitle_recovery SET state='RESOLVED',next_attempt_at=NULL,updated_at=? WHERE id=?", (time.time(), row["id"]))
            self._subtitle_transition_event(c, video, row, "RESOLVED", details={'release_event_id': release['id']} if release else {})
            return True

    @staticmethod
    def _subtitle_review_binding(c, video, row):
        failure_id = c.execute('SELECT COALESCE(MAX(id),0) FROM publishing_failure_events WHERE video_id=?', (video['id'],)).fetchone()[0]
        value = dict(video_id=video['id'], youtube_id=video['youtube_id'], slice_index=video['slice_index'],
                     review_error=video['error_msg'] or '', manual_failure_event_id=failure_id,
                     last_receipt_sha=row['last_receipt_sha'] if row else None)
        token = hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        return value, token

    def get_subtitle_manual_review(self, video_id: int) -> dict | None:
        """只读复核凭据；API 的放行必须回传当前 token，避免误放新失败。"""
        with self.get_connection() as c:
            video = c.execute('SELECT * FROM processed_videos WHERE id=?', (video_id,)).fetchone()
            if video is None:
                return None
            row = self._subtitle_row(c, video_id)
            _, token = self._subtitle_review_binding(c, video, row)
            blocker = self._subtitle_blocker_in(c, video_id)
            release = c.execute("SELECT * FROM subtitle_recovery_events WHERE video_id=? AND event_type='RELEASED' ORDER BY id DESC LIMIT 1", (video_id,)).fetchone()
            audit = None
            already_released = False
            if release:
                details = json.loads(release['details'])
                already_released = details.get('review_token') == token
                audit = dict(event_id=release['id'], created_at=release['created_at'],
                             actor=details.get('actor'), reason=details.get('reason'), expires_at=details.get('expires_at'))
            return dict(video_id=video_id, youtube_id=video['youtube_id'], slice_index=video['slice_index'],
                        review_token=token, expected_receipt_sha=row['last_receipt_sha'] if row else token,
                        error_msg=video['error_msg'], last_release=audit,
                        blocker=blocker, releasable=bool(blocker and not already_released and self._subtitle_eligible(c, video)
                            and video['status'] in {'FAILED','PENDING'} and video['process_pid'] is None))

    def release_subtitle_recovery_after_repair(self, video_id: int, expected_receipt_sha: str, *,
                                              actor: str, reason: str, expected_review_token: str | None = None) -> bool:
        """一次 CAS 修复试跑；即使旧预算已满也不清次数、不延长原链期限。"""
        _sha(expected_receipt_sha)
        actor, reason = _text(actor, 120), _text(reason, 1000)
        if not actor or not reason:
            raise ValueError('manual subtitle release requires actor and reason')
        with self.get_connection() as c:
            c.execute("BEGIN IMMEDIATE")
            video = c.execute("SELECT * FROM processed_videos WHERE id=?", (video_id,)).fetchone()
            row = self._subtitle_row(c, video_id)
            if (not self._subtitle_eligible(c, video) or video["process_pid"] is not None or
                    video["status"] not in {"FAILED", "PENDING"} or not self._subtitle_blocker_in(c, video_id)):
                return False
            binding, token = self._subtitle_review_binding(c, video, row)
            if expected_review_token is not None and token != expected_review_token:
                return False
            if expected_receipt_sha != (row['last_receipt_sha'] if row else token):
                return False
            if c.execute("SELECT 1 FROM subtitle_recovery_events WHERE video_id=? AND event_type='RELEASED' AND json_extract(details,'$.review_token')=?", (video_id,token)).fetchone():
                return False
            if row:
                c.execute("UPDATE subtitle_recovery SET state='RELEASED',next_attempt_at=NULL,released_receipt_sha=?,updated_at=? WHERE id=?",
                          (expected_receipt_sha, time.time(), row['id']))
            self._subtitle_transition_event(c, video, row, "RELEASED", details=binding | dict(
                review_token=token, release_version=1, actor=actor, reason=reason, expires_at=time.time()+MAX_CHAIN_SECONDS))
            c.execute("UPDATE processed_videos SET status='PENDING',updated_at=CURRENT_TIMESTAMP WHERE id=?", (video_id,))
            return True

    @staticmethod
    def _subtitle_transition_event(c, video, row, state: str, *, event_type: str | None = None, details=None) -> None:
        # 同一写事务绑定已经存在的失败序号，不用可漂移的墙钟释放未来失败。
        details = dict(details or {})
        if state == 'RELEASED':
            details['manual_failure_event_id'] = c.execute(
                'SELECT COALESCE(MAX(id),0) FROM publishing_failure_events WHERE video_id=?',
                (video['id'],)).fetchone()[0]
        c.execute("""INSERT INTO subtitle_recovery_events(video_id,chain_id,youtube_id,slice_index,event_type,state,
            receipt_sha,receipt_path,details,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                  (video["id"], row["id"] if row else None, video["youtube_id"], video["slice_index"], event_type or state, state,
                   row["last_receipt_sha"] if row else details.get('review_token'), row["last_receipt_path"] if row else '', json.dumps(details,ensure_ascii=False), time.time()))
