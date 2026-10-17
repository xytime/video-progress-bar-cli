"""具名恢复动作和不可变事件账本；SQL 仅由 PipelineDB 混入使用。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import uuid


def stamp(value=None):
    return (value or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S")


class DeliveryRecoveryDAL:
    def initialize_delivery_recovery(self):
        with self.get_connection() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS delivery_recoveries (
                id TEXT PRIMARY KEY, event_key TEXT NOT NULL UNIQUE, kind TEXT NOT NULL,
                state TEXT NOT NULL, payload_json TEXT NOT NULL, detail TEXT NOT NULL,
                failure_kind TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TEXT, expires_at TEXT NOT NULL, actor TEXT,
                result TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
            c.execute("""CREATE TABLE IF NOT EXISTS delivery_recovery_events (
                id INTEGER PRIMARY KEY, recovery_id TEXT NOT NULL,
                action TEXT NOT NULL, actor TEXT, payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL)""")

    def create_delivery_recovery(self, *, event_key, kind, payload, detail, failure_kind):
        now = datetime.now(timezone.utc)
        with self.get_connection() as c:
            c.execute("""INSERT OR IGNORE INTO delivery_recoveries
                (id,event_key,kind,state,payload_json,detail,failure_kind,expires_at,created_at,updated_at)
                VALUES (?,?,?,'WAITING',?,?,?,?,?,?)""",
                (uuid.uuid4().hex, event_key, kind, json.dumps(payload, ensure_ascii=False), detail[:1500],
                 failure_kind, stamp(now + timedelta(hours=24)), stamp(now), stamp(now)))
            return dict(c.execute("SELECT * FROM delivery_recoveries WHERE event_key=?", (event_key,)).fetchone())

    def get_delivery_recovery(self, recovery_id):
        with self.get_connection() as c:
            row = c.execute("SELECT * FROM delivery_recoveries WHERE id=?", (recovery_id,)).fetchone()
            return dict(row) if row else None

    def list_delivery_recoveries(self, limit=10):
        with self.get_connection() as c:
            return [dict(r) for r in c.execute("SELECT * FROM delivery_recoveries ORDER BY created_at DESC LIMIT ?",
                                               (min(20, max(1, limit)),))]

    @staticmethod
    def _recovery_event(c, recovery_id, action, actor, payload):
        c.execute("INSERT INTO delivery_recovery_events(recovery_id,action,actor,payload_json,created_at) VALUES(?,?,?,?,?)",
                  (recovery_id, action, actor, json.dumps(payload, ensure_ascii=False), stamp()))

    def queue_delivery_recovery(self, recovery_id, *, actor, action, delay_seconds=0):
        """一次性领取操作授权；等待期间重复点击不得重置退避或计数。"""
        with self.get_connection() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT * FROM delivery_recoveries WHERE id=?", (recovery_id,)).fetchone()
            if not row or row['state'] != 'WAITING' or row['expires_at'] <= stamp():
                raise ValueError("按钮已消费、任务已更新或已过期，请刷新 /recoveries")
            if not actor or action not in {'retry', 'verify', 'hold'}:
                raise ValueError("恢复动作无效")
            if action == 'retry' and row['kind'] != 'EW_PRODUCTION':
                raise ValueError("此任务不能自动重传")
            state = 'HELD' if action == 'hold' else 'QUEUED'
            self._recovery_event(c, recovery_id, action, actor, {'previous_state': row['state']})
            c.execute("UPDATE delivery_recoveries SET state=?,actor=?,next_attempt_at=?,updated_at=? WHERE id=?",
                      (state, actor, stamp(datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)), stamp(), recovery_id))
            return dict(c.execute("SELECT * FROM delivery_recoveries WHERE id=?", (recovery_id,)).fetchone())

    def claim_delivery_recovery(self):
        with self.get_connection() as c:
            c.execute("BEGIN IMMEDIATE")
            c.execute("UPDATE delivery_recoveries SET state='EXPIRED',updated_at=? WHERE state IN ('WAITING','QUEUED') AND expires_at<=?", (stamp(), stamp()))
            # 中途退出的动作绝不自动重放；保留结果核验入口。
            c.execute("""UPDATE delivery_recoveries SET state='NEEDS_REVIEW',
                result='执行者中断或超时；需核验已有阶段记录，未自动重放',updated_at=?
                WHERE state='RUNNING' AND updated_at < datetime('now','-4 hours')""", (stamp(),))
            row = c.execute("""SELECT * FROM delivery_recoveries WHERE state='QUEUED'
                AND next_attempt_at<=? AND expires_at>? ORDER BY next_attempt_at LIMIT 1""", (stamp(), stamp())).fetchone()
            if not row:
                return None
            c.execute("UPDATE delivery_recoveries SET state='RUNNING',attempts=attempts+1,updated_at=? WHERE id=?",
                      (stamp(), row['id']))
            return dict(c.execute("SELECT * FROM delivery_recoveries WHERE id=?", (row['id'],)).fetchone())

    def has_due_delivery_recovery(self):
        with self.get_connection() as c:
            c.execute("""UPDATE delivery_recoveries SET state='NEEDS_REVIEW',
                result='恢复执行者中断，需核验已有阶段记录；未自动重放',updated_at=?
                WHERE state='RUNNING' AND updated_at < datetime('now','-4 hours')""", (stamp(),))
            return bool(c.execute("SELECT 1 FROM delivery_recoveries WHERE state='QUEUED' AND next_attempt_at<=? AND expires_at>? LIMIT 1", (stamp(), stamp())).fetchone())

    def finish_delivery_recovery(self, recovery_id, *, result, retry_delay=None):
        with self.get_connection() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT * FROM delivery_recoveries WHERE id=? AND state='RUNNING'", (recovery_id,)).fetchone()
            if not row:
                return None
            delay = retry_delay if row['attempts'] < 3 else None
            state = 'QUEUED' if delay is not None else 'DONE'
            due = stamp(datetime.now(timezone.utc) + timedelta(seconds=delay)) if delay is not None else None
            self._recovery_event(c, recovery_id, 'result', row['actor'], {'result': result, 'next_attempt_at': due})
            c.execute("UPDATE delivery_recoveries SET state=?,result=?,next_attempt_at=?,updated_at=? WHERE id=?",
                      (state, result[:1500], due, stamp(), recovery_id))
            return dict(c.execute("SELECT * FROM delivery_recoveries WHERE id=?", (recovery_id,)).fetchone())

    def confirm_unpublished_delivery_recovery(self, recovery_id, *, actor):
        """原子消费人工未发布确认，保存旧未知记录；受理/原生 ID/墓碑始终阻断。"""
        with self.get_connection() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT * FROM delivery_recoveries WHERE id=?", (recovery_id,)).fetchone()
            if not row or row['kind'] != 'WECHAT_UNKNOWN' or row['state'] != 'WAITING' or row['expires_at'] <= stamp():
                raise ValueError("任务已更新、已消费或按钮已过期")
            p = json.loads(row['payload_json'])
            video = c.execute("SELECT * FROM processed_videos WHERE id=?", (p['video_id'],)).fetchone()
            publication = c.execute("SELECT * FROM wechat_publications WHERE video_id=?", (p['video_id'],)).fetchone()
            if (not actor or not video or video['status'] != 'UNCERTAIN' or video['process_pid'] is not None
                    or video['retry_count'] != p['video_retry_count'] or not publication
                    or publication['state'] != 'UNCERTAIN' or publication['platform_post_id']
                    or publication['platform_url'] or publication['confirmed_at'] or publication['updated_at'] != p['publication_updated_at']):
                raise ValueError("任务或平台账本已经变化，拒绝重传，请刷新")
            for table in ('wechat_submission_attempts', 'wechat_publications_historical_archive'):
                if c.execute(f"SELECT 1 FROM {table} WHERE video_id=?", (p['video_id'],)).fetchone():
                    raise ValueError("存在提交尝试或历史保护记录，禁止重传")
            if c.execute("SELECT 1 FROM english_world_review_items WHERE source_youtube_id=?", (video['youtube_id'],)).fetchone():
                raise ValueError("来源已进入独立英语世界审核链，禁止通用重传")
            self._recovery_event(c, recovery_id, 'operator_confirmed_not_published', actor,
                                 {'video': dict(video), 'prior_publication': dict(publication), 'artifacts': p['artifacts']})
            # 旧记录已完整保留于不可变事件；只有本次未知、无受理 ID 的活动阻断记录可解除。
            c.execute("DELETE FROM wechat_publications WHERE id=? AND state='UNCERTAIN'", (publication['id'],))
            c.execute("""UPDATE processed_videos SET status='PENDING',preparation_ready=1,
                process_pid=NULL,publication_wait_reason='人工核验未发布，等待发布执行者重新审查',
                retry_count=COALESCE(retry_count,0)+1,error_msg=NULL,updated_at=? WHERE id=?""", (stamp(), video['id']))
            c.execute("UPDATE delivery_recoveries SET state='DONE',actor=?,result=?,updated_at=? WHERE id=?",
                      (actor, '已消费人工未发布确认；成片已排队，尚未重新上传', stamp(), recovery_id))
            return dict(c.execute("SELECT * FROM delivery_recoveries WHERE id=?", (recovery_id,)).fetchone())

    def requeue_proven_pre_submit_failure(self, youtube_id, *, slice_index, evidence_dir, video_path):
        from ..utils.submission_progress import proven_pre_submit, NAME
        from ..utils.retry_policy import backoff_seconds
        if not proven_pre_submit(evidence_dir, video_path):
            return None
        evidence = str((evidence_dir / NAME).resolve())
        with self.get_connection() as c:
            c.execute('BEGIN IMMEDIATE')
            video = c.execute("""SELECT id FROM processed_videos v WHERE youtube_id=? AND slice_index=? AND status='PUBLISHING'
                AND NOT EXISTS(SELECT 1 FROM wechat_publications p WHERE p.video_id=v.id)
                AND NOT EXISTS(SELECT 1 FROM wechat_submission_attempts a WHERE a.video_id=v.id)
                AND NOT EXISTS(SELECT 1 FROM wechat_publications_historical_archive h WHERE h.video_id=v.id)""",
                (youtube_id, slice_index)).fetchone()
            if not video or c.execute('SELECT 1 FROM wechat_upload_retries WHERE evidence_path=?', (evidence,)).fetchone():
                return None
            count = c.execute('SELECT count(*) FROM wechat_upload_retries WHERE video_id=?', (video['id'],)).fetchone()[0]
            # 现有上传恢复表允许两次重试，加上原始上传共三次。
            if count >= 2:
                return None
            due = stamp(datetime.now(timezone.utc) + timedelta(seconds=backoff_seconds(count+1)))
            c.execute('INSERT INTO wechat_upload_retries(video_id,evidence_path,attempt_number,next_attempt_at) VALUES(?,?,?,?)',
                      (video['id'], evidence, count+1, due))
            c.execute("""UPDATE processed_videos SET status='PENDING',preparation_ready=1,process_pid=NULL,
                error_msg=?,publication_wait_reason=?,retry_count=COALESCE(retry_count,0)+1,updated_at=? WHERE id=?""",
                (f'提交前浏览器关闭；第{count+1}/2次重试退避，下次 UTC {due}', f'退避至 UTC {due}', stamp(), video['id']))
            return {'attempt': count+1, 'next_attempt_at': due}

    def get_confirmed_recovery_artifacts(self, youtube_id, slice_index=0):
        """人工确认后仍绑定同一发布包，排队期间变化也不能静默上传。"""
        with self.get_connection() as c:
            row = c.execute("""SELECT r.payload_json FROM delivery_recoveries r
                JOIN processed_videos v ON v.id=json_extract(r.payload_json,'$.video_id')
                WHERE r.kind='WECHAT_UNKNOWN' AND r.state='DONE'
                AND v.youtube_id=? AND v.slice_index=?
                AND EXISTS(SELECT 1 FROM delivery_recovery_events e WHERE e.recovery_id=r.id
                    AND e.action='operator_confirmed_not_published')
                ORDER BY r.updated_at DESC,r.rowid DESC LIMIT 1""", (youtube_id, slice_index)).fetchone()
            return json.loads(row['payload_json'])['artifacts'] if row else []
