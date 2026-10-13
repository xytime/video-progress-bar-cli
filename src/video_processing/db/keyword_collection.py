"""关键词采集 DAL：调度、观察与主队列原子准入。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 0.4.0 | 2026-10-13 | Codex | 独立候选的持久调度、评分证据及受控准入 |
"""
from datetime import datetime, timedelta
import json

from ..core.topic_candidates import TopicError, stamp, topic_fields, quota_day
from ..scoring import compute_policy_score, SCORE_POLICY_VERSION, PUBLISH_SCORE_LINE


class KeywordCollectionDAL:
    @staticmethod
    def _keyword_schema(c):
        additions = {
            'topic_definitions': {'language': "TEXT NOT NULL DEFAULT 'en'", 'min_duration': 'INTEGER NOT NULL DEFAULT 180',
                                  'auto_enabled': 'INTEGER NOT NULL DEFAULT 0', 'next_run_at': 'TEXT'},
            'topic_jobs': {'kind': "TEXT NOT NULL DEFAULT 'MANUAL'", 'has_more': 'INTEGER NOT NULL DEFAULT 0'},
            'topic_candidates': {'first_seen': 'TEXT', 'next_refresh': 'TEXT', 'score': 'INTEGER',
                                 'score_policy': 'TEXT', 'score_inputs': 'TEXT', 'admitted_id': 'INTEGER',
                                 'admission_code': 'TEXT', 'admission_revision': 'INTEGER'},
        }
        for table, columns in additions.items():
            existing = {r[1] for r in c.execute(f'PRAGMA table_info({table})')}
            for name, definition in columns.items():
                if name not in existing:
                    c.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')
        c.execute('CREATE TABLE IF NOT EXISTS keyword_control (id INTEGER PRIMARY KEY CHECK(id=1), admission INTEGER NOT NULL DEFAULT 0, version INTEGER NOT NULL DEFAULT 1)')
        c.execute('INSERT OR IGNORE INTO keyword_control(id) VALUES(1)')
        columns = {r[1] for r in c.execute('PRAGMA table_info(keyword_control)')}
        for name in ('runtime_code', 'runtime_at'):
            if name not in columns:
                c.execute(f'ALTER TABLE keyword_control ADD COLUMN {name} TEXT')
        c.execute('CREATE TABLE IF NOT EXISTS keyword_admissions (key TEXT PRIMARY KEY, video_id INTEGER NOT NULL, topic_id TEXT NOT NULL, topic_version INTEGER NOT NULL, score INTEGER NOT NULL, policy TEXT NOT NULL, at TEXT NOT NULL, result TEXT NOT NULL)')
        # 升级旧身份签名；不改规则版本、时长、收藏或历史命中。
        for row in c.execute('SELECT * FROM topic_definitions').fetchall():
            identity = topic_fields(dict(row))['identity']
            if identity != row['identity']:
                c.execute('UPDATE topic_definitions SET identity=? WHERE id=?', (identity, row['id']))

    def keyword_runtime(self, code, now):
        with self._topic_connection(write=True) as c:
            c.execute('UPDATE keyword_control SET runtime_code=?,runtime_at=? WHERE id=1', (code, stamp(now)))

    def keyword_blocked_rules(self):
        with self._topic_connection() as c:
            return {(r[0], r[1]) for r in c.execute("SELECT DISTINCT topic_id,topic_version FROM topic_jobs WHERE code IN ('API_CREDENTIALS','API_ACCESS','API_QUOTA')")}

    def keyword_auto_budget(self, project, now):
        with self._topic_connection() as c:
            return c.execute("SELECT COALESCE(SUM(b.units),0) FROM topic_budget b JOIN topic_jobs j ON j.id=b.job_id WHERE b.project=? AND b.bucket='search' AND b.day=? AND j.kind='SCHEDULED'", (project, quota_day(now))).fetchone()[0]

    def keyword_defer_refresh(self, rows, now):
        with self._topic_connection(write=True) as c:
            for row in rows:
                c.execute('UPDATE topic_candidates SET next_refresh=? WHERE key=? AND revision=?', (stamp(now+timedelta(hours=4)), row['key'], row['revision']))

    def keyword_admission_feedback(self, key, revision, code):
        with self._topic_connection(write=True) as c:
            c.execute('UPDATE topic_candidates SET admission_code=?,admission_revision=? WHERE key=? AND revision=?', (code, revision, key, revision))

    def keyword_control(self):
        with self._topic_connection() as c:
            return dict(c.execute('SELECT * FROM keyword_control WHERE id=1').fetchone())

    def keyword_set_admission(self, enabled, version, actor, now):
        with self._topic_connection(write=True) as c:
            if not c.execute('UPDATE keyword_control SET admission=?,version=version+1 WHERE id=1 AND version=?', (int(enabled), version)).rowcount:
                raise TopicError('STALE', '准入状态已变化，请刷新')
            self._topic_audit(c, actor, 'ADMISSION_ON' if enabled else 'ADMISSION_OFF', 'control', version+1, now)
        return self.keyword_control()

    def keyword_schedule(self, topic_id, version, enabled, actor, now):
        with self._topic_connection(write=True) as c:
            self._topic_expire(c, now)
            row = c.execute('SELECT * FROM topic_definitions WHERE id=?', (topic_id,)).fetchone()
            if not row or row['version'] != version:
                raise TopicError('STALE', '采集规则已变化，请刷新')
            if enabled and row['status'] != 'ACTIVE':
                raise TopicError('STOPPED', '请先恢复有效规则')
            if enabled and not row['auto_enabled'] and c.execute("SELECT COUNT(*) FROM topic_definitions WHERE auto_enabled=1 AND status='ACTIVE'").fetchone()[0] >= 3:
                raise TopicError('CAPACITY', '最多启用 3 条定时采集规则')
            if c.execute("SELECT 1 FROM topic_jobs WHERE topic_id=? AND state IN ('RUNNING','STOPPING')", (topic_id,)).fetchone():
                raise TopicError('BUSY', '请等待当前作业结束后调整定时采集')
            c.execute('UPDATE topic_definitions SET auto_enabled=?,next_run_at=?,version=version+1 WHERE id=?', (int(enabled), stamp(now) if enabled else None, topic_id))
            self._topic_audit(c, actor, 'SCHEDULE_ON' if enabled else 'SCHEDULE_OFF', topic_id, version+1, now)
        return self.topic_get(topic_id, now)

    def keyword_due(self, now):
        with self._topic_connection() as c:
            return [dict(r) for r in c.execute("SELECT * FROM topic_definitions WHERE auto_enabled=1 AND status='ACTIVE' AND expires_at>? AND (next_run_at IS NULL OR next_run_at<=?) ORDER BY COALESCE(next_run_at,'') LIMIT 3", (stamp(now), stamp(now)))]

    def keyword_job_coverage(self, job_id, has_more):
        with self._topic_connection(write=True) as c:
            c.execute('UPDATE topic_jobs SET has_more=? WHERE id=?', (int(has_more), job_id))

    def keyword_score_results(self, job_id, config, now):
        with self._topic_connection(write=True) as c:
            self._topic_check_job(c, job_id, now)
            for row in c.execute('SELECT DISTINCT c.* FROM topic_candidates c JOIN topic_hits h ON h.key=c.key WHERE h.job_id=?', (job_id,)).fetchall():
                meta = json.loads(row['metadata'])
                inputs = dict(view_count=meta['views'], like_count=meta['likes'], channel_id=meta['channel_id'], source='KEYWORD')
                score = None if meta['views'] is None or meta['likes'] is None else compute_policy_score(inputs, config)
                c.execute('UPDATE topic_candidates SET first_seen=COALESCE(first_seen,?),next_refresh=?,score=?,score_policy=?,score_inputs=? WHERE key=?',
                          (stamp(now), stamp(now+timedelta(hours=4)), score, SCORE_POLICY_VERSION, json.dumps(inputs), row['key']))

    def keyword_observations(self, now, *, include_future=False):
        """全局视频公平轮转；一份统计供多个规则复用，不按命中数重复请求。"""
        with self._topic_connection() as c:
            rows = c.execute("""SELECT c.*,t.id topic_id,t.version topic_version,t.min_duration,
                ROW_NUMBER() OVER(PARTITION BY c.key ORDER BY t.min_duration,t.id) n
                FROM topic_candidates c JOIN topic_decisions d USING(key)
                JOIN topic_hits h USING(key) JOIN topic_definitions t ON t.id=h.topic_id
                WHERE c.metadata IS NOT NULL AND d.state!='REJECTED' AND c.admitted_id IS NULL
                  AND c.first_seen>? AND (? OR c.next_refresh IS NULL OR c.next_refresh<=?)
                  AND t.auto_enabled=1 AND t.status='ACTIVE' AND t.expires_at>?
                  AND h.topic_version=t.version
                ORDER BY COALESCE(c.next_refresh,''),c.key""", (stamp(now-timedelta(hours=72)), int(include_future), stamp(now), stamp(now))).fetchall()
            return [dict(r, metadata=json.loads(r['metadata'])) for r in rows if r['n']==1][:200]

    def keyword_refresh_results(self, job_id, evaluated, config, now):
        with self._topic_connection(write=True) as c:
            self._topic_check_job(c, job_id, now)
            for old, current in evaluated:
                meta = current['metadata']
                inputs = dict(view_count=meta['views'],like_count=meta['likes'],channel_id=meta['channel_id'],source='KEYWORD')
                score = None if meta['views'] is None or meta['likes'] is None else compute_policy_score(inputs, config)
                c.execute('''UPDATE topic_candidates SET metadata=?,fetched_at=?,expires_at=?,next_refresh=?,score=?,score_policy=?,score_inputs=?,
                    eligibility=?,reason=?,rule_version=?,content_version=?,revision=revision+1 WHERE key=? AND revision=?''',
                    (json.dumps(meta),stamp(now),stamp(now+timedelta(days=30)),stamp(now+timedelta(hours=4)),score,SCORE_POLICY_VERSION,json.dumps(inputs),
                     current['eligibility'],current['reason'],current['rule_version'],current['content_version'],old['key'],old['revision']))

    def keyword_candidate_state(self, key, config, now, *, observation_keys=None):
        with self._topic_connection() as c:
            row = c.execute('SELECT c.*,d.state decision FROM topic_candidates c JOIN topic_decisions d USING(key) WHERE key=?', (key,)).fetchone()
            if row is None: return dict(state='INCOMPLETE')
            state = 'OBSERVING'
            if row['decision']=='REJECTED': state='REJECTED'
            elif row['admitted_id']: state='ADMITTED'
            elif row['eligibility']=='INCOMPLETE': state='INCOMPLETE'
            elif row['eligibility']!='CHECKABLE': state='RESTRICTED'
            elif not row['first_seen'] or row['first_seen']<=stamp(now-timedelta(hours=72)): state='EXPIRED'
            elif not c.execute("SELECT 1 FROM topic_hits h JOIN topic_definitions t ON t.id=h.topic_id WHERE h.key=? AND t.status='ACTIVE' AND t.expires_at>? AND t.version=h.topic_version", (key,stamp(now))).fetchone(): state='EXPIRED'
            elif row['score'] is None: state='INCOMPLETE'
            elif row['fetched_at']<=stamp(now-timedelta(hours=4)): state='WAIT_REFRESH'
            elif row['score']>=75: state='QUALIFIED'
            meta=json.loads(row['metadata'] or '{}')
            published=meta.get('published_at')
            if state in ('QUALIFIED','OBSERVING','WAIT_REFRESH') and published:
                age=datetime.fromisoformat(published.replace('Z','+00:00'))
                if not now-timedelta(hours=72)<=age<=now: state='EXPIRED'
            if state in ('OBSERVING','WAIT_REFRESH') and observation_keys is not None and key not in observation_keys:
                state='WAIT_SCHEDULE'
            existing=c.execute('SELECT id,status FROM processed_videos WHERE youtube_id=? ORDER BY slice_index LIMIT 1', (row['youtube_id'],)).fetchone()
            if existing and state!='REJECTED': state='ADMITTED' if row['admitted_id'] else 'EXISTING'
            return dict(state=state,score=row['score'],policy=row['score_policy'],next_refresh=row['next_refresh'] if state in ('OBSERVING','WAIT_REFRESH','WAIT_SCHEDULE','INCOMPLETE','QUALIFIED') else None,
                        admission_code=row['admission_code'] if row['admission_revision']==row['revision'] else None,
                        inputs=json.loads(row['score_inputs'] or '{}'),task_id=existing['id'] if existing else None)

    def keyword_admit(self, key, revision, topic_id, topic_version, current_rules, config, now):
        """事务内重读并复算；不修改既有任务、分数、状态或发布账本。"""
        with self._topic_connection(write=True) as c:
            from ..core.maintenance import gate
            gate().require_running()
            control=c.execute('SELECT admission FROM keyword_control WHERE id=1').fetchone()
            mode=c.execute('SELECT mode FROM topic_control WHERE id=1').fetchone()
            if not getattr(config,'topic_admission_enabled',False) or not control['admission'] or mode['mode']=='OFF':
                raise TopicError('ADMISSION_CLOSED','关键词准入未开放')
            t=c.execute('SELECT * FROM topic_definitions WHERE id=?',(topic_id,)).fetchone()
            r=c.execute('SELECT c.*,d.state decision FROM topic_candidates c JOIN topic_decisions d USING(key) WHERE key=?',(key,)).fetchone()
            if (not t or t['version']!=topic_version or t['status']!='ACTIVE' or t['expires_at']<=stamp(now)
                    or not r or r['revision']!=revision or r['decision']=='REJECTED'
                    or r['eligibility']!='CHECKABLE' or r['rule_version']!=current_rules()):
                raise TopicError('RECHECK','候选、规则或整理状态已变化')
            if not c.execute('SELECT 1 FROM topic_hits WHERE key=? AND topic_id=? AND topic_version=?',(key,topic_id,topic_version)).fetchone():
                raise TopicError('RECHECK','当前规则尚未命中该视频')
            meta=json.loads(r['metadata'])
            published=datetime.fromisoformat(meta['published_at'].replace('Z','+00:00'))
            if (not r['first_seen'] or r['first_seen']<=stamp(now-timedelta(hours=72)) or not now-timedelta(hours=72)<=published<=now
                    or r['fetched_at']<=stamp(now-timedelta(hours=4)) or not t['min_duration']<=meta['duration']<=1800):
                raise TopicError('STALE_METADATA','资料或报道已过期，等待刷新或重新采集')
            if meta['views'] is None or meta['likes'] is None: raise TopicError('INCOMPLETE','统计资料不足')
            score=compute_policy_score(dict(view_count=meta['views'],like_count=meta['likes'],channel_id=meta['channel_id'],source='KEYWORD'),config)
            if score<PUBLISH_SCORE_LINE: raise TopicError('LOW_SCORE','尚未达到原有评分门槛')
            if (c.execute('SELECT 1 FROM blacklisted_videos WHERE youtube_id=?',(meta['youtube_id'],)).fetchone()
                or c.execute("SELECT 1 FROM recommended_channels WHERE channel_id=? AND status='BLACKLISTED'",(meta['channel_id'],)).fetchone()):
                raise TopicError('BLACKLISTED','视频或频道已排除')
            old=c.execute('SELECT id FROM processed_videos WHERE youtube_id=? ORDER BY slice_index LIMIT 1',(meta['youtube_id'],)).fetchone()
            if old: video_id,result=old['id'],'EXISTING'
            else:
                cursor=c.execute("""INSERT INTO processed_videos(youtube_id,slice_index,title,channel_id,score,status,source,duration_sec,view_count,like_count,source_published_at,upload_date,disable_slicing,category)
                    VALUES(?,0,?,?,?,'PENDING','KEYWORD',?,?,?,?,?,0,?)""",(meta['youtube_id'],meta['title'],meta['channel_id'],score,meta['duration'],meta['views'],meta['likes'],meta['published_at'],published.strftime('%Y%m%d'),t['category']))
                video_id,result=cursor.lastrowid,'ADMITTED'
            c.execute('INSERT OR IGNORE INTO keyword_admissions VALUES(?,?,?,?,?,?,?,?)',(key,video_id,topic_id,topic_version,score,SCORE_POLICY_VERSION,stamp(now),result))
            if result=='ADMITTED': c.execute('UPDATE topic_candidates SET admitted_id=? WHERE key=?',(video_id,key))
            self._topic_audit(c,'scheduler',result,key,revision,now)
            return dict(video_id=video_id,result=result)

    def keyword_processing_allowed(self, youtube_id, slice_index=0):
        with self.get_connection() as c:
            row=c.execute('SELECT source FROM processed_videos WHERE youtube_id=? AND slice_index=?',(youtube_id,slice_index)).fetchone()
            return bool(row and self._keyword_allowed(c,row['source'],youtube_id))

    @staticmethod
    def _keyword_allowed(c, source, youtube_id=None):
        if source!='KEYWORD':
            # 准入来源不可因手工提分/改来源或衍生切片而丢失。
            try:
                admitted=c.execute("SELECT 1 FROM keyword_admissions a JOIN processed_videos p ON p.id=a.video_id WHERE p.youtube_id=? AND a.result='ADMITTED'",(youtube_id,)).fetchone()
            except Exception:
                # 兼容尚未建立新表的旧数据库；其他读取故障不得放行。
                if c.execute("SELECT 1 FROM sqlite_master WHERE name='keyword_admissions'").fetchone():
                    return False
                admitted=None
            if not admitted: return True
        from config.settings import settings
        if not settings.topic_admission_enabled: return False
        try:
            return bool(c.execute("SELECT 1 FROM keyword_control k,topic_control t WHERE k.id=1 AND t.id=1 AND k.admission=1 AND t.mode!='OFF'").fetchone())
        except Exception:
            return False

    def keyword_admission_candidates(self, now):
        with self._topic_connection() as c:
            rows=c.execute("""SELECT c.*,t.id topic_id,t.version topic_version,t.min_duration,
                ROW_NUMBER() OVER(PARTITION BY c.key ORDER BY t.min_duration,t.id) n FROM topic_candidates c
                JOIN topic_decisions d USING(key) JOIN topic_hits h USING(key) JOIN topic_definitions t ON t.id=h.topic_id
                WHERE c.metadata IS NOT NULL AND c.score>=75 AND c.admitted_id IS NULL AND d.state!='REJECTED'
                AND NOT EXISTS(SELECT 1 FROM keyword_admissions a WHERE a.key=c.key)
                AND t.status='ACTIVE' AND t.expires_at>? AND h.topic_version=t.version
                AND c.first_seen>? AND c.fetched_at>?
                ORDER BY c.fetched_at DESC""",(stamp(now),stamp(now-timedelta(hours=72)),stamp(now-timedelta(hours=4)))).fetchall()
            return [dict(r,metadata=json.loads(r['metadata'])) for r in rows if r['n']==1][:200]

    def keyword_min_duration(self, key):
        with self._topic_connection() as c:
            row=c.execute('SELECT MIN(t.min_duration) n FROM topic_hits h JOIN topic_definitions t ON t.id=h.topic_id WHERE h.key=? AND h.topic_version=t.version',(key,)).fetchone()
            return row['n'] or 180
