"""人工执行意图账本；SQL 与原子认领只在 DAL 内。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-22 | Codex | 持久等待、原子认领和中断闭锁，禁止重复执行。 |
"""
import uuid


class ExecutionRecoveryDAL:
    def initialize_execution_recovery(self):
        with self.get_connection() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS execution_recovery (
                id TEXT PRIMARY KEY, video_id INTEGER NOT NULL UNIQUE
                REFERENCES processed_videos(id) ON DELETE CASCADE,
                state TEXT NOT NULL DEFAULT 'WAITING', owner_pid INTEGER,
                message TEXT NOT NULL DEFAULT '已登记，等待调度条件恢复',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")

    def execution_recovery(self, youtube_id, slice_index=0):
        with self.get_connection() as conn:
            row = conn.execute("""SELECT r.*, v.youtube_id, v.slice_index, v.title,
                v.status AS task_status FROM execution_recovery r
                JOIN processed_videos v ON v.id=r.video_id
                WHERE v.youtube_id=? AND v.slice_index=?""", (youtube_id, slice_index)).fetchone()
            return dict(row) if row else None

    def list_execution_recovery(self, *, waiting_only=False):
        with self.get_connection() as conn:
            return [dict(r) for r in conn.execute("""SELECT r.*, v.youtube_id, v.slice_index,
                v.title, v.status AS task_status FROM execution_recovery r
                JOIN processed_videos v ON v.id=r.video_id
                WHERE (?=0 OR r.state='WAITING') ORDER BY r.created_at, r.id""", (int(waiting_only),))]

    def enqueue_execution_recovery(self, youtube_id, slice_index=0):
        with self.get_connection() as conn:
            conn.execute("""INSERT OR IGNORE INTO execution_recovery(id, video_id)
                SELECT ?, id FROM processed_videos WHERE youtube_id=? AND slice_index=?
                AND status='PENDING' AND COALESCE(source,'AUTO')!='DISCOVERY'
                AND keyword_allowed(source,youtube_id)
                AND NOT EXISTS (SELECT 1 FROM wechat_publications p WHERE p.video_id=processed_videos.id)
                AND NOT EXISTS (SELECT 1 FROM wechat_submission_attempts a WHERE a.video_id=processed_videos.id)
                AND NOT EXISTS (SELECT 1 FROM wechat_publications_historical_archive h WHERE h.video_id=processed_videos.id)
                """, (uuid.uuid4().hex, youtube_id, slice_index))
        return self.execution_recovery(youtube_id, slice_index)

    def execution_task_blocker(self, youtube_id, slice_index=0):
        """不放宽手动分数豁免以外的发布边界；领取事务内重复检查。"""
        with self.get_connection() as conn:
            return self._execution_task_blocker(conn, youtube_id, slice_index)

    @staticmethod
    def _execution_task_blocker(conn, youtube_id, slice_index):
        row = conn.execute("""SELECT CASE
          WHEN v.status!='PENDING' THEN '任务当前状态：' || v.status
          WHEN COALESCE(v.source,'AUTO')='DISCOVERY' THEN '发现素材不可直接执行'
          WHEN NOT keyword_allowed(v.source,v.youtube_id) THEN '关键词准入未开放'
          WHEN v.publication_review_required=1 THEN '任务需要内容审核'
          WHEN EXISTS(SELECT 1 FROM blacklisted_videos b WHERE b.youtube_id=v.youtube_id)
            OR EXISTS(SELECT 1 FROM recommended_channels c WHERE c.channel_id=v.channel_id AND c.status='BLACKLISTED') THEN '黑名单阻止执行'
          WHEN EXISTS(SELECT 1 FROM wechat_publications p WHERE p.video_id=v.id)
            OR EXISTS(SELECT 1 FROM wechat_submission_attempts a WHERE a.video_id=v.id)
            OR EXISTS(SELECT 1 FROM wechat_publications_historical_archive h WHERE h.video_id=v.id) THEN '已有提交记录，禁止重复执行'
          WHEN EXISTS(SELECT 1 FROM copywriter_deferred c WHERE c.video_id=v.id AND c.next_attempt_at>CURRENT_TIMESTAMP) THEN '文案任务仍在退避'
          WHEN EXISTS(SELECT 1 FROM wechat_upload_retries r WHERE r.video_id=v.id AND r.next_attempt_at>CURRENT_TIMESTAMP) THEN '上传任务仍在退避'
          WHEN v.slice_index>0 AND EXISTS(SELECT 1 FROM processed_videos s WHERE s.parent_id=v.parent_id
            AND s.slice_index>0 AND s.slice_index<v.slice_index
            AND s.status NOT IN ('PUBLISHED','IGNORED','COMPLETED','HISTORICAL_ARCHIVED')) THEN '等待前序分集完成'
          ELSE '' END AS reason FROM processed_videos v WHERE v.youtube_id=? AND v.slice_index=?
          """, (youtube_id, slice_index)).fetchone()
        return row['reason'] if row else '任务不存在'

    def claim_execution_recovery(self, request_id, youtube_id, slice_index, owner_pid):
        with self.get_connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            if self._execution_task_blocker(conn, youtube_id, slice_index):
                return False
            cursor = conn.execute("""UPDATE execution_recovery SET state='RUNNING', owner_pid=?,
                message='执行者已认领', updated_at=CURRENT_TIMESTAMP
                WHERE id=? AND state='WAITING' AND video_id=(SELECT id FROM processed_videos
                    WHERE youtube_id=? AND slice_index=?)""", (owner_pid, request_id, youtube_id, slice_index))
            if cursor.rowcount != 1:
                return False
            conn.execute("""UPDATE processed_videos SET status='PROCESSING', process_pid=?,
                updated_at=CURRENT_TIMESTAMP WHERE youtube_id=? AND slice_index=?""",
                (owner_pid, youtube_id, slice_index))
            return True

    def update_execution_recovery(self, request_id, state, message, *, expected='RUNNING'):
        if state not in ('WAITING', 'FINISHED', 'ATTENTION'):
            raise ValueError('invalid recovery state')
        with self.get_connection() as conn:
            return conn.execute("""UPDATE execution_recovery SET state=?, message=?, owner_pid=NULL,
                updated_at=CURRENT_TIMESTAMP WHERE id=? AND state=?""",
                (state, message, request_id, expected)).rowcount == 1

    def note_execution_recovery(self, request_id, message):
        with self.get_connection() as conn:
            conn.execute("""UPDATE execution_recovery SET message=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=? AND state='WAITING' AND message!=?""", (message, request_id, message))
