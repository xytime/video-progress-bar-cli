"""受既有 queue-runner 管理的关键词调度；无独立计时线程或 cron。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 0.4.0 | 2026-10-13 | Codex | 全局串行定时采集、批量统计刷新和受控准入 |
"""
from datetime import datetime
import os
import time

from ..core.topic_candidates import TopicError, metadata, stamp


class KeywordCollection:
    def schedule(self, topic_id, version, enabled, actor):
        if enabled:
            self._ready()
            if not getattr(self.config,'topic_scheduler_enabled',False):
                raise TopicError('SCHEDULER_CLOSED','定时采集尚未开放',403)
        return self.db.keyword_schedule(topic_id,version,enabled,actor,self.clock())

    def admission(self, enabled, version, actor):
        if enabled:
            self._ready()
            if not getattr(self.config,'topic_admission_enabled',False):
                raise TopicError('ADMISSION_CLOSED','宿主准入尚未开放',403)
        return self.db.keyword_set_admission(enabled,version,actor,self.clock())

    def _verify_runtime(self):
        from config.settings import settings
        from ..core.maintenance_runtime import code_hash, process_birth, PROTOCOL
        from ..core.task_lease import read_lease_owner
        from ..core.maintenance import gate
        owner=read_lease_owner(gate().path.with_suffix('.workers')/'queue-runner.lock')
        if (not owner or owner.get('pid')!=os.getpid() or owner.get('protocol')!=PROTOCOL
                or owner.get('cwd')!=str(settings.project_root)
                or owner.get('birth')!=process_birth(os.getpid()) or owner.get('source_hash')!=code_hash()):
            raise TopicError('RUNTIME_UNVERIFIED','调度运行来源不一致，需维护核实',503)

    def tick(self, *, verify_runtime=True):
        from ..core.maintenance import MaintenanceDenied
        try:
            result=self._tick(verify_runtime=verify_runtime)
        except MaintenanceDenied as exc:
            result=exc.code
        self.db.keyword_runtime(result,self.clock())
        return result

    def _tick(self, *, verify_runtime=True):
        """每次至多一项有界工作；调用者负责周期，内核锁覆盖所有请求/准入。"""
        if not getattr(self.config,'topic_scheduler_enabled',False): return 'SCHEDULER_CLOSED'
        try:
            self._ready()
            if self.db.topic_control()['mode']=='OFF': return 'SEARCH_CLOSED'
            if verify_runtime: self._verify_runtime()
            from ..core.maintenance import gate
            ticket=gate().acquire('keyword-collection','scheduled-cycle')
            ticket.start()
            lock=None
            try:
                lock=self._lock()
                if not lock: return 'BUSY'
                self.db.topic_maintenance(self.clock(),recover=True)
                # 非瞬时错误须显式调整规则/重新启用，不每轮重试凭据或官方配额。
                blocked=self.db.keyword_blocked_rules()
                due=[t for t in self.db.keyword_due(self.clock()) if (t['id'],t['version']) not in blocked]
                budget=self.db.topic_budget(self.config.topic_quota_project,self.clock())
                auto_used=self.db.keyword_auto_budget(self.config.topic_quota_project,self.clock())
                search_available=(budget['search']<self.config.topic_search_daily_limit and auto_used<min(18,max(0,self.config.topic_search_daily_limit-2)))
                if due and search_available and budget['general']<self.config.topic_general_daily_limit:
                    t=due[0]
                    slot=int(self.clock().timestamp())//14400
                    idem=f"scheduled_{t['id']}_{t['version']}_{slot}"
                    job=self.db.topic_create_job(t['id'],t['version'],idem,'scheduler',self.clock(),kind='SCHEDULED')
                    if job['state']=='RUNNING':
                        self._run(job,t,lock,ticket)
                        lock=None
                    return 'SEARCH'
                rows=[r for r in self.db.keyword_observations(self.clock()) if (r['topic_id'],r['topic_version']) not in blocked]
                if rows and budget['general']<self.config.topic_general_daily_limit:
                    t=self.db.topic_get(rows[0]['topic_id'],self.clock())
                    batch=[r for r in rows if r['topic_id']==t['id']][:50]
                    slot=int(self.clock().timestamp())//14400
                    # 每批身份包含首个源，避免 50+ 个观察项只完成第一批。
                    idem=f"refresh_{t['id']}_{t['version']}_{slot}_{batch[0]['key'][:12]}"
                    existing=self.db.topic_jobs(idem=idem)
                    if not existing:
                        job=self.db.topic_create_job(t['id'],t['version'],idem,'scheduler',self.clock(),kind='REFRESH')
                        self._refresh(job,batch)
                self._admit_qualified()
                if (due and not search_available) or (rows and budget['general']>=self.config.topic_general_daily_limit): return 'BUDGET'
                return 'REFRESH_OR_ADMISSION'
            finally:
                if lock: lock.close()
                ticket.close()
        except TopicError as exc:
            return exc.code

    def _refresh(self, job, rows):
        deadline=time.monotonic()+60
        try:
            details=self._request(job['id'],'general',deadline,self.adapter.details,[r['youtube_id'] for r in rows])
            by_id={item.get('id'):item for item in details}
            evaluated=[(r,self._evaluate(metadata(r['youtube_id'],by_id.get(r['youtube_id'])),r)) for r in rows]
            self._timeout(job['id'],deadline)
            self.db.keyword_refresh_results(job['id'],evaluated,self.config,self.clock())
            self._finish(job['id'],'COMPLETE','OK')
        except TopicError as exc:
            self.db.keyword_defer_refresh(rows,self.clock())
            self._finish(job['id'],'PARTIAL',exc.code)
        except Exception:
            self.db.keyword_defer_refresh(rows,self.clock())
            self._finish(job['id'],'FAILED','INTERNAL_ERROR')

    def _admit_qualified(self):
        if not getattr(self.config,'topic_admission_enabled',False) or not self.db.keyword_control()['admission']: return
        # 有界扫描；SQL 只选尚未关联主库、分数达标且有有效规则命中的记录。
        for row in self.db.keyword_admission_candidates(self.clock()):
            self._ready()
            try:
                fresh=self._evaluate(row['metadata'],row)
                if fresh['eligibility']!='CHECKABLE': continue
                if fresh['content_version']!=row['content_version']:
                    self.db.topic_refresh_rules(row['key'],row['revision'],fresh)
                    continue
                self.db.keyword_admit(row['key'],row['revision'],row['topic_id'],row['topic_version'],self.rules.version,self.config,self.clock())
            except TopicError as exc:
                self.db.keyword_admission_feedback(row['key'],row['revision'],exc.code)
                continue
