"""文字通知持久认领：未知发送永不自动重放，崩溃不释放发送意图。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| notification-guard-v1 | 2026-10-26 | Codex | 原子认领、提交前意图、未知历史闭锁与已知未发出失败持久退避。 |
"""
from datetime import datetime, timezone
import secrets
import time


class NotificationDeliveryDAL:
    @staticmethod
    def _notification_attempt_schema(conn):
        conn.execute('''CREATE TABLE IF NOT EXISTS telegram_notification_attempts (
            token TEXT PRIMARY KEY, event_type TEXT NOT NULL, content_sha256 TEXT NOT NULL,
            priority TEXT NOT NULL, state TEXT NOT NULL,
            claimed_at REAL NOT NULL, lease_until REAL NOT NULL, intent_at REAL,
            finished_at REAL, retry_after REAL, receipt_id INTEGER, error_kind TEXT,
            cooldown_seconds INTEGER NOT NULL)''')
        conn.execute('''CREATE INDEX IF NOT EXISTS idx_telegram_attempt_identity
            ON telegram_notification_attempts(event_type,content_sha256,state)''')

    def claim_notification_delivery(self, *, event_type, fingerprint, priority,
                                    cooldown_seconds, lease_seconds, now=None):
        """先认领再写意图；现有 UNKNOWN（包括部署前历史）不会因冷却或重启重放。"""
        if priority not in {'P0','P1','P2'} or cooldown_seconds < 0 or lease_seconds <= 0:
            raise ValueError('invalid notification admission')
        at=time.time() if now is None else float(now)
        event_type=(event_type or 'unknown')[:120];fingerprint=fingerprint[:128]
        with self.get_connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            self._notification_attempt_schema(conn)
            pending=conn.execute('''SELECT state FROM telegram_notification_attempts
                WHERE event_type=? AND content_sha256=? AND state IN ('UNKNOWN','SEND_INTENT') LIMIT 1''',
                (event_type,fingerprint)).fetchone()
            if pending:
                return {'allowed':False,'reason':'PRIOR_'+pending['state']+'_NOT_REPLAYED'}
            # 历史只增审计闭锁，不修改原 UNKNOWN/ACCEPTED 回执，不批量重放旧通知。
            legacy=conn.execute('''SELECT id,CAST(strftime('%s',created_at) AS REAL) at
                FROM telegram_notification_receipts WHERE event_type=? AND content_sha256=?
                AND delivery_state='UNKNOWN' ORDER BY id LIMIT 1''',
                (event_type,fingerprint)).fetchone()
            if legacy:
                conn.execute('''INSERT OR IGNORE INTO telegram_notification_attempts
                    (token,event_type,content_sha256,priority,state,claimed_at,lease_until,
                     finished_at,receipt_id,error_kind,cooldown_seconds)
                    VALUES (?,?,?,?,'UNKNOWN',?,?,?,?,?,?)''',
                    ('legacy:'+str(legacy['id']),event_type,fingerprint,priority,
                     legacy['at'] or at,legacy['at'] or at,legacy['at'] or at,
                     legacy['id'],'LEGACY_UNKNOWN_NOT_REPLAYED',cooldown_seconds))
            pending=conn.execute('''SELECT state FROM telegram_notification_attempts
                WHERE event_type=? AND content_sha256=? AND state IN ('UNKNOWN','SEND_INTENT') LIMIT 1''',
                (event_type,fingerprint)).fetchone()
            if pending:
                return {'allowed':False,'reason':'PRIOR_'+pending['state']+'_NOT_REPLAYED'}
            active=conn.execute('''SELECT 1 FROM telegram_notification_attempts
                WHERE event_type=? AND content_sha256=? AND state='CLAIMED' AND lease_until>? LIMIT 1''',
                (event_type,fingerprint,at)).fetchone()
            if active:
                return {'allowed':False,'reason':'NOTIFICATION_CLAIM_BUSY'}
            conn.execute('''UPDATE telegram_notification_attempts SET state='ABANDONED_PRE_INTENT',
                finished_at=?,error_kind='LEASE_EXPIRED_BEFORE_INTENT' WHERE event_type=?
                AND content_sha256=? AND state='CLAIMED' AND lease_until<=?''',
                (at,event_type,fingerprint,at))
            if cooldown_seconds:
                durable_success=conn.execute('''SELECT 1 FROM telegram_notification_attempts
                    WHERE event_type=? AND content_sha256=? AND state='ACCEPTED'
                    AND finished_at>? LIMIT 1''',(event_type,fingerprint,at-cooldown_seconds)).fetchone()
                if durable_success:
                    return {'allowed':False,'reason':'DEDUPE'}
                since=datetime.fromtimestamp(at-cooldown_seconds,timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
                accepted=conn.execute('''SELECT 1 FROM telegram_notification_receipts WHERE event_type=?
                    AND content_sha256=? AND delivery_state='ACCEPTED' AND created_at>=? LIMIT 1''',
                    (event_type,fingerprint,since)).fetchone()
                if accepted:
                    return {'allowed':False,'reason':'DEDUPE'}
            retry=conn.execute('''SELECT 1 FROM telegram_notification_attempts WHERE event_type=?
                AND content_sha256=? AND state='FAILED' AND retry_after>? LIMIT 1''',
                (event_type,fingerprint,at)).fetchone()
            if retry:
                return {'allowed':False,'reason':'KNOWN_NOT_SENT_BACKOFF'}
            token=secrets.token_hex(16)
            conn.execute('''INSERT INTO telegram_notification_attempts
                (token,event_type,content_sha256,priority,state,claimed_at,lease_until,cooldown_seconds)
                VALUES (?,?,?,?,'CLAIMED',?,?,?)''',
                (token,event_type,fingerprint,priority,at,at+lease_seconds,cooldown_seconds))
            return {'allowed':True,'token':token}

    def record_notification_send_intent(self, token, *, now=None):
        """过期/已被接替的认领不得外发；SEND_INTENT 不因租期到期而解除。"""
        at=time.time() if now is None else float(now)
        with self.get_connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            changed=conn.execute('''UPDATE telegram_notification_attempts SET state='SEND_INTENT',intent_at=?
                WHERE token=? AND state='CLAIMED' AND lease_until>?''',(at,token,at)).rowcount
            return changed==1

    def complete_notification_delivery(self, token, *, state, receipt_id, error_kind=None, now=None):
        """只在回执已持久保存后收尾；保留每次认领及结果，失败不冒充送达。"""
        if state not in {'ACCEPTED','UNKNOWN','FAILED'}:
            raise ValueError('invalid notification outcome')
        at=time.time() if now is None else float(now)
        with self.get_connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row=conn.execute("SELECT * FROM telegram_notification_attempts WHERE token=? AND state='SEND_INTENT'",(token,)).fetchone()
            if not row:
                return False
            receipt=conn.execute('''SELECT delivery_state,event_type,content_sha256 FROM
                telegram_notification_receipts WHERE id=?''',(receipt_id,)).fetchone()
            if not receipt or receipt['delivery_state']!=state or receipt['event_type']!=row['event_type'] or receipt['content_sha256']!=row['content_sha256']:
                return False
            retry_after=None
            if state=='FAILED':
                from ..utils.retry_policy import backoff_seconds
                failures=conn.execute('''SELECT COUNT(*) FROM telegram_notification_attempts WHERE
                    event_type=? AND content_sha256=? AND state='FAILED' ''',
                    (row['event_type'],row['content_sha256'])).fetchone()[0]
                retry_after=at+backoff_seconds(failures+1)
            conn.execute('''UPDATE telegram_notification_attempts SET state=?,finished_at=?,
                retry_after=?,receipt_id=?,error_kind=? WHERE token=? AND state='SEND_INTENT' ''',
                (state,at,retry_after,receipt_id,(error_kind or '')[:120] or None,token))
            return True
