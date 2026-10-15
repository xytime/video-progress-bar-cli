"""关键词长期准入账本；配额和新增任务共用上层 BEGIN IMMEDIATE 事务。

依赖：keyword_collection → 本模块 → keyword_evidence / config / core.topic_candidates。
不删除、重置或退款历史记录，未知任务状态按在途处理。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 0.5.0 | 2026-10-15 | Codex | 北京日界、滚动168小时、根任务容量和持久来源核验 |
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from config.keyword_rollout import admission_limits
from ..core.topic_candidates import TopicError, stamp
from .keyword_evidence import KeywordEvidenceDAL


class KeywordAdmissionDAL(KeywordEvidenceDAL):
    @staticmethod
    def _keyword_admission_schema(c):
        columns = {r[1] for r in c.execute('PRAGMA table_info(keyword_admissions)')}
        if 'youtube_id' not in columns:
            c.execute('ALTER TABLE keyword_admissions ADD COLUMN youtube_id TEXT')
        c.execute('''UPDATE keyword_admissions SET youtube_id=(
            SELECT youtube_id FROM processed_videos p WHERE p.id=keyword_admissions.video_id)
            WHERE youtube_id IS NULL''')
        c.execute('CREATE INDEX IF NOT EXISTS keyword_admission_time ON keyword_admissions(result,at)')

    @staticmethod
    def _keyword_admission_usage(c, config, now):
        """在同一快照中核实全部历史；错误仅闭锁新增准入。"""
        try:
            limits = admission_limits(config)
            if c.execute("SELECT 1 FROM keyword_admissions WHERE result NOT IN ('ADMITTED','EXISTING')").fetchone():
                raise ValueError('result')
            rows = c.execute("SELECT * FROM keyword_admissions WHERE result='ADMITTED' ORDER BY at,key").fetchall()
            times, seen = [], set()
            for row in rows:
                at = datetime.fromisoformat(row['at'])
                if at.tzinfo is None or at > now or row['video_id'] in seen or not row['youtube_id']:
                    raise ValueError('ledger')
                seen.add(row['video_id'])
                times.append(at)
            times.sort()
            zone = ZoneInfo('Asia/Shanghai')
            day_start = now.astimezone(zone).replace(hour=0, minute=0, second=0, microsecond=0)
            rolling_start = now - timedelta(hours=168)
            daily_times = [at for at in times if at >= day_start]
            rolling_times = [at for at in times if at > rolling_start]
            # 根失败/完成但仍有未结束切片时继续占用；SEGMENTED 有子项才由子项决定。
            inflight = c.execute('''SELECT COUNT(*) FROM keyword_admissions a
                WHERE a.result='ADMITTED' AND EXISTS (
                  SELECT 1 FROM processed_videos p WHERE p.youtube_id=a.youtube_id
                  AND p.status NOT IN ('PUBLISHED','FAILED','IGNORED','DELETED','REJECTED','SKIPPED','CANCELLED','CENSORED')
                  AND NOT (p.status='SEGMENTED' AND EXISTS (
                    SELECT 1 FROM processed_videos child WHERE child.parent_id=p.id)))''').fetchone()[0]
            # 没有可验证来源的存活旧根不能悄悄漏计容量。
            if c.execute('''SELECT 1 FROM keyword_admissions a JOIN processed_videos p ON p.id=a.video_id
                WHERE a.result='ADMITTED' AND (a.youtube_id IS NULL OR a.youtube_id!=p.youtube_id)''').fetchone():
                raise ValueError('origin')
            code, next_at = 'OK', None
            if limits['total'] is not None and len(rows) >= limits['total']:
                code = 'ADMISSION_LIMIT'
            elif limits['daily'] is not None and len(daily_times) >= limits['daily']:
                code, next_at = 'ADMISSION_DAILY', day_start + timedelta(days=1)
            if limits['rolling'] is not None and len(rolling_times) >= limits['rolling']:
                rolling_next = rolling_times[-limits['rolling']] + timedelta(hours=168)
                code, next_at = 'ADMISSION_ROLLING', max(next_at, rolling_next) if next_at else rolling_next
            if limits['inflight'] is not None and inflight >= limits['inflight']:
                code, next_at = 'ADMISSION_INFLIGHT', None
            return dict(verified=True, limits=limits, daily_used=len(daily_times), rolling_used=len(rolling_times),
                        total_used=len(rows), inflight=inflight, day=day_start.date().isoformat(),
                        code=code, next_at=stamp(next_at) if next_at else None)
        except Exception as exc:
            raise TopicError('ADMISSION_LEDGER_UNVERIFIED', '准入账本未通过核实，新增准入已停止', 503) from exc

    def keyword_admission_usage(self, config, now):
        try:
            with self._topic_connection() as c:
                return self._keyword_admission_usage(c, config, now)
        except TopicError:
            return dict(verified=False, code='ADMISSION_LEDGER_UNVERIFIED', next_at=None)

    def keyword_admission_ledger(self):
        """部署与真实验收的只读历史；不得用状态快照替代持久消费证据。"""
        with self._topic_connection() as c:
            return [dict(r) for r in c.execute('SELECT * FROM keyword_admissions ORDER BY at,key')]

    @staticmethod
    def _keyword_require_admission_capacity(c, config, now):
        usage = KeywordAdmissionDAL._keyword_admission_usage(c, config, now)
        messages = dict(ADMISSION_LIMIT='已达到累计准入上限，等待管理员评审扩容',
                        ADMISSION_DAILY='今日准入已满，等待北京时间次日额度',
                        ADMISSION_ROLLING='滚动7天准入已满，等待最早额度释放',
                        ADMISSION_INFLIGHT='已有2条未结束关键词主任务，等待任务结束')
        if usage['code'] != 'OK':
            raise TopicError(usage['code'], messages[usage['code']])
