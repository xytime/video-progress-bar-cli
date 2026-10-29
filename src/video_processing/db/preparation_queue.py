"""仅预加工执行队列；执行态与原视频/投稿 FSM 分离，等待不会消费重试。

依赖：PipelineDB → 本 DAL → 标准库；不调用处理器或业务入口。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-29 | Codex | 幂等排队、延迟业务 claim、owner CAS、持久等待与排空。 |
"""
from __future__ import annotations
import time
import uuid


class PreparationQueueDAL:
    def _preparation_eligibility(self, *, include_review=False):
        """沿用原自动候选全部闸；入队前人工锁闭合，入队后保留本地-only人工锁。

        canary allowlist 不等于分数/黑名单/内容授权；本轮不新增低分人工旁路。
        """
        gates = self._publication_gates(ready_only=False)
        if not include_review:
            gates = [row for row in gates if row[0] != 'CONTENT_REVIEW']
        return (' AND '.join('('+sql+')' for _,_,sql,_ in gates),
                tuple(value for _,_,_,args in gates for value in args))

    def initialize_preparation_queue(self) -> None:
        with self.get_connection() as c:
            c.execute('''CREATE TABLE IF NOT EXISTS preparation_execution_queue (
                video_id INTEGER PRIMARY KEY REFERENCES processed_videos(id) ON DELETE CASCADE,
                youtube_id TEXT NOT NULL, slice_index INTEGER NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('WAITING','RESERVED','RUNNING','DONE','BLOCKED')),
                trigger_source TEXT NOT NULL, owner_token TEXT, owner_pid INTEGER, owner_birth TEXT,
                queued_at REAL NOT NULL, updated_at REAL NOT NULL, started_at REAL,
                next_attempt_at REAL NOT NULL DEFAULT 0,
                resource TEXT NOT NULL DEFAULT '', stage TEXT NOT NULL DEFAULT '',
                reason TEXT NOT NULL DEFAULT '', local_preparation INTEGER NOT NULL DEFAULT 0,
                execution_wall_seconds REAL NOT NULL DEFAULT 0,
                attempts INTEGER NOT NULL DEFAULT 0, yields INTEGER NOT NULL DEFAULT 0,
                last_state TEXT NOT NULL DEFAULT 'WAITING',
                UNIQUE(youtube_id,slice_index))''')
            columns = {row[1] for row in c.execute('PRAGMA table_info(preparation_execution_queue)')}
            for name, definition in (('execution_wall_seconds', 'REAL NOT NULL DEFAULT 0'),
                    ('attempts', 'INTEGER NOT NULL DEFAULT 0'), ('yields', 'INTEGER NOT NULL DEFAULT 0'),
                    ('last_state', "TEXT NOT NULL DEFAULT 'WAITING'")):
                if name not in columns:
                    c.execute(f'ALTER TABLE preparation_execution_queue ADD COLUMN {name} {definition}')

    def enqueue_preparation(self, youtube_id: str, slice_index: int = 0, *, trigger_source: str) -> bool:
        """只有未提交 PENDING 入队；重复触发不覆盖原 owner 或排队顺序。"""
        now = time.time()
        eligible, params = self._preparation_eligibility(include_review=True)
        with self.get_connection() as c:
            cursor = c.execute('''INSERT INTO preparation_execution_queue
                (video_id,youtube_id,slice_index,state,trigger_source,queued_at,updated_at)
                SELECT pv.id,pv.youtube_id,pv.slice_index,'WAITING',?,?,? FROM processed_videos pv
                LEFT JOIN processed_videos origin ON origin.id=COALESCE(pv.parent_id,pv.id)
                WHERE pv.youtube_id=? AND pv.slice_index=? AND COALESCE(pv.preparation_ready,0)=0
                AND ''' + eligible + ' ON CONFLICT(video_id) DO NOTHING',
                (trigger_source, now, now, youtube_id, slice_index, *params))
            inserted = cursor.rowcount == 1
            if inserted:
                c.execute('''UPDATE processed_videos SET publication_review_required=1
                    WHERE youtube_id=? AND slice_index=? AND status='PENDING' ''',
                    (youtube_id, slice_index))
            return inserted

    def reserve_preparation(self, allowlist: tuple[str, ...], *, max_workers: int = 2) -> dict | None:
        """只领执行票；未拿到任务/源/资源锁以前不修改视频业务状态。"""
        if not 1 <= len(allowlist) <= 3 or max_workers not in (1, 2):
            raise ValueError('preparation canary permits at most three sources and two workers')
        from .subtitle_recovery import subtitle_recovery_gate_sql
        eligible, params = self._preparation_eligibility()
        with self.get_connection() as c:
            c.execute('BEGIN IMMEDIATE')
            count = c.execute("SELECT COUNT(*) FROM preparation_execution_queue WHERE state IN ('RESERVED','RUNNING')").fetchone()[0]
            if count >= max_workers:
                return None
            placeholders = ','.join('?' for _ in allowlist)
            row = c.execute('''SELECT q.* FROM preparation_execution_queue q
                JOIN processed_videos pv ON pv.id=q.video_id
                LEFT JOIN processed_videos origin ON origin.id=COALESCE(pv.parent_id,pv.id)
                WHERE q.state='WAITING' AND pv.status='PENDING'
                AND q.next_attempt_at<=?
                AND COALESCE(pv.preparation_ready,0)=0 AND q.youtube_id IN (''' + placeholders + ''')
                AND COALESCE(pv.source,'AUTO') NOT IN ('DISCOVERY','COMPLIANCE_REMIX')
                AND keyword_allowed(pv.source,pv.youtube_id)
                AND NOT EXISTS (SELECT 1 FROM preparation_execution_queue busy WHERE busy.youtube_id=q.youtube_id
                                AND busy.state IN ('RESERVED','RUNNING'))
                AND NOT EXISTS (SELECT 1 FROM copywriter_deferred c WHERE c.video_id=pv.id AND c.next_attempt_at>CURRENT_TIMESTAMP)
                AND NOT EXISTS (SELECT 1 FROM wechat_upload_retries r WHERE r.video_id=pv.id AND r.next_attempt_at>CURRENT_TIMESTAMP)
                AND NOT EXISTS (SELECT 1 FROM wechat_submission_attempts a WHERE a.video_id=pv.id)
                AND NOT EXISTS (SELECT 1 FROM wechat_publications p WHERE p.video_id=pv.id)
                AND ''' + subtitle_recovery_gate_sql('pv.id') + '''
                AND ''' + eligible + '''
                ORDER BY q.queued_at,q.video_id LIMIT 1''', (time.time(), *allowlist, *params)).fetchone()
            if row is None:
                return None
            token = uuid.uuid4().hex
            c.execute("UPDATE preparation_execution_queue SET state='RESERVED',last_state='RESERVED',attempts=attempts+1,owner_token=?,owner_pid=NULL,owner_birth=NULL,updated_at=?,resource='admission',reason='' WHERE video_id=? AND state='WAITING'",
                      (token, time.time(), row['video_id']))
            return dict(row) | dict(state='RESERVED', owner_token=token)

    def attach_preparation_worker(self, video_id: int, token: str, pid: int, birth: str) -> bool:
        with self.get_connection() as c:
            return c.execute('''UPDATE preparation_execution_queue SET owner_pid=?,owner_birth=?,updated_at=?
                WHERE video_id=? AND owner_token=? AND state IN ('RESERVED','RUNNING')
                AND (owner_pid IS NULL OR owner_pid=?)''',
                (pid, birth, time.time(), video_id, token, pid)).rowcount == 1

    def start_preparation_execution(self, youtube_id: str, slice_index: int, token: str, *, pid: int, birth: str) -> bool:
        """资源就绪且维护重新准入后，原子 claim；完整沿用现有领取质量闸。"""
        from .subtitle_recovery import subtitle_recovery_gate_sql
        now = time.time()
        eligible, params = self._preparation_eligibility()
        with self.get_connection() as c:
            c.execute('BEGIN IMMEDIATE')
            owner = c.execute("SELECT video_id FROM preparation_execution_queue WHERE youtube_id=? AND slice_index=? AND state='RESERVED' AND owner_token=? AND (owner_pid IS NULL OR (owner_pid=? AND owner_birth=?))",
                              (youtube_id, slice_index, token, pid, birth)).fetchone()
            if owner is None:
                return False
            cursor = c.execute('''UPDATE processed_videos SET status='PROCESSING',process_pid=?,updated_at=CURRENT_TIMESTAMP
                WHERE id=? AND status='PENDING' AND COALESCE(source,'AUTO') NOT IN ('DISCOVERY','COMPLIANCE_REMIX')
                AND COALESCE(preparation_ready,0)=0 AND keyword_allowed(source,youtube_id)
                AND NOT EXISTS (SELECT 1 FROM wechat_submission_attempts a WHERE a.video_id=processed_videos.id)
                AND NOT EXISTS (SELECT 1 FROM wechat_publications p WHERE p.video_id=processed_videos.id)
                AND NOT EXISTS (SELECT 1 FROM copywriter_deferred c WHERE c.video_id=processed_videos.id AND c.next_attempt_at>CURRENT_TIMESTAMP)
                AND NOT EXISTS (SELECT 1 FROM wechat_upload_retries r WHERE r.video_id=processed_videos.id AND r.next_attempt_at>CURRENT_TIMESTAMP)
                AND ''' + subtitle_recovery_gate_sql('processed_videos.id') + '''
                AND id IN (SELECT pv.id FROM processed_videos pv LEFT JOIN processed_videos origin
                    ON origin.id=COALESCE(pv.parent_id,pv.id) WHERE ''' + eligible + ')', (pid, owner['video_id'], *params))
            if cursor.rowcount != 1:
                return False
            c.execute("UPDATE preparation_execution_queue SET state='RUNNING',last_state='RUNNING',owner_pid=?,owner_birth=?,started_at=?,updated_at=?,resource='',stage='STARTING' WHERE video_id=? AND owner_token=?",
                      (pid, birth, now, now, owner['video_id'], token))
            return True

    def finish_preparation_execution(self, video_id: int, token: str, *, state: str, reason: str = '') -> bool:
        """仅当前 owner 可结束执行票；不把等待/退出码当成成片成功或投稿。"""
        if state not in {'WAITING', 'DONE', 'BLOCKED'}:
            raise ValueError('invalid execution outcome')
        with self.get_connection() as c:
            c.execute('BEGIN IMMEDIATE')
            owned = c.execute("SELECT state FROM preparation_execution_queue WHERE video_id=? AND owner_token=? AND state IN ('RESERVED','RUNNING')", (video_id,token)).fetchone()
            if owned is None:
                return False
            if state == 'WAITING' and owned['state'] == 'RUNNING':
                changed = c.execute('''UPDATE processed_videos SET status='PENDING',process_pid=NULL,updated_at=CURRENT_TIMESTAMP
                    WHERE id=? AND status IN ('PENDING','PROCESSING','DOWNLOADING','COPYWRITING','TRANSCRIBING','RENDERING')
                    AND NOT EXISTS (SELECT 1 FROM wechat_submission_attempts a WHERE a.video_id=processed_videos.id)
                    AND NOT EXISTS (SELECT 1 FROM wechat_publications p WHERE p.video_id=processed_videos.id)''', (video_id,))
                if changed.rowcount != 1:
                    state, reason = 'BLOCKED', 'cannot return across changed business/submission boundary'
            return c.execute('''UPDATE preparation_execution_queue SET state=?,last_state=?,reason=?,updated_at=?,next_attempt_at=?,
                execution_wall_seconds=execution_wall_seconds+CASE WHEN started_at IS NULL THEN 0 ELSE MAX(0,?-started_at) END,
                started_at=NULL,owner_pid=NULL,owner_birth=NULL,resource=''
                WHERE video_id=? AND owner_token=? AND state IN ('RESERVED','RUNNING')''',
                (state, state, reason[:500], time.time(), time.time()+5 if state == 'WAITING' else 0,
                 time.time(), video_id, token)).rowcount == 1

    def recover_preparation_execution(self, video_id: int, token: str) -> bool:
        """调用方已取得排空后的跨代 fence 并核实 owner 死亡，才允许 CAS 恢复。"""
        with self.get_connection() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute("SELECT state FROM preparation_execution_queue WHERE video_id=? AND owner_token=? AND state IN ('RESERVED','RUNNING')",
                            (video_id, token)).fetchone()
            if row is None:
                return False
            changed = c.execute('''UPDATE processed_videos SET status='PENDING',process_pid=NULL,updated_at=CURRENT_TIMESTAMP
                WHERE id=? AND status IN ('PENDING','PROCESSING','DOWNLOADING','COPYWRITING','TRANSCRIBING','RENDERING')
                AND NOT EXISTS (SELECT 1 FROM wechat_submission_attempts a WHERE a.video_id=processed_videos.id)
                AND NOT EXISTS (SELECT 1 FROM wechat_publications p WHERE p.video_id=processed_videos.id)''', (video_id,))
            if changed.rowcount != 1:
                return False
            c.execute("UPDATE preparation_execution_queue SET state='WAITING',last_state='RECOVERED',started_at=NULL,owner_pid=NULL,owner_birth=NULL,stage='RECOVERED',reason='prior cohort drained; verified owner absent',updated_at=? WHERE video_id=? AND owner_token=?",
                      (time.time(), video_id, token))
            return True

    def mark_preparation_local_ready(self, youtube_id: str, slice_index: int, token: str) -> bool:
        """只确认本地预加工；不写 ready，不入任何平台下游队列。"""
        with self.get_connection() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute("SELECT video_id FROM preparation_execution_queue WHERE youtube_id=? AND slice_index=? AND owner_token=? AND state='RUNNING'",
                            (youtube_id, slice_index, token)).fetchone()
            if row is None:
                return False
            changed = c.execute('''UPDATE processed_videos SET preparation_ready=0,publication_review_required=1,
                status='LOCAL_READY',updated_at=CURRENT_TIMESTAMP WHERE id=?
                AND status IN ('PROCESSING','DOWNLOADING','COPYWRITING','TRANSCRIBING','RENDERING','PUBLISH_PRECHECK')
                AND NOT EXISTS (SELECT 1 FROM wechat_submission_attempts a WHERE a.video_id=processed_videos.id)
                AND NOT EXISTS (SELECT 1 FROM wechat_publications p WHERE p.video_id=processed_videos.id)''', (row['video_id'],))
            if changed.rowcount != 1:
                return False
            c.execute('UPDATE preparation_execution_queue SET local_preparation=1,stage=? WHERE video_id=? AND owner_token=?',
                      ('LOCAL_READY', row['video_id'], token))
            return True

    def preparation_queue_snapshot(self) -> list[dict]:
        with self.get_connection() as c:
            return [dict(row) for row in c.execute('SELECT *,local_preparation AS local_ready_count FROM preparation_execution_queue ORDER BY queued_at,video_id')]

    def preparation_execution_summary(self) -> dict:
        """实际本地就绪与等待/进程尝试分计；不推断任何发布证据。"""
        with self.get_connection() as c:
            row = c.execute('''SELECT COUNT(*) AS queued_count,COALESCE(SUM(attempts),0) AS attempts,
                COALESCE(SUM(yields),0) AS yields,COALESCE(SUM(local_preparation),0) AS local_ready_count,
                COALESCE(SUM(state='WAITING'),0) AS waiting_count,
                COALESCE(SUM(state IN ('RESERVED','RUNNING')),0) AS owned_count
                FROM preparation_execution_queue''').fetchone()
            return dict(row)

    def yield_preparation_execution(self, youtube_id: str, slice_index: int, token: str) -> bool:
        """可靠 checkpoint 后公平回队；不碰已提交，不增加业务失败次数。"""
        with self.get_connection() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute("SELECT video_id FROM preparation_execution_queue WHERE youtube_id=? AND slice_index=? AND owner_token=? AND state='RUNNING'",
                            (youtube_id, slice_index, token)).fetchone()
            if row is None:
                return False
            changed = c.execute('''UPDATE processed_videos SET status='PENDING',process_pid=NULL,updated_at=CURRENT_TIMESTAMP
                WHERE id=? AND status IN ('PROCESSING','DOWNLOADING','COPYWRITING','TRANSCRIBING','RENDERING')
                AND NOT EXISTS (SELECT 1 FROM wechat_submission_attempts a WHERE a.video_id=processed_videos.id)
                AND NOT EXISTS (SELECT 1 FROM wechat_publications p WHERE p.video_id=processed_videos.id)''', (row['video_id'],))
            if changed.rowcount != 1:
                return False
            now = time.time()
            c.execute('''UPDATE preparation_execution_queue SET state='WAITING',last_state='YIELDED',yields=yields+1,stage='YIELDED',queued_at=?,updated_at=?,
                execution_wall_seconds=execution_wall_seconds+MAX(0,?-started_at),started_at=NULL,owner_pid=NULL,owner_birth=NULL,resource=''
                WHERE video_id=? AND owner_token=?''', (now, now, now, row['video_id'], token))
            return True

    def preparation_execution_event(self, video_id: int, token: str, *, stage: str, resource: str = '', reason: str = '') -> bool:
        with self.get_connection() as c:
            return c.execute('''UPDATE preparation_execution_queue SET stage=?,resource=?,reason=?,updated_at=?
                WHERE video_id=? AND owner_token=? AND state IN ('RESERVED','RUNNING')''',
                (stage[:120], resource[:40], reason[:500], time.time(), video_id, token)).rowcount == 1
