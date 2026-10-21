"""独立预筛选 DAL；不写 topic_hits、topic_candidates 或 processed_videos。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-21 | Codex | 规则 CAS、快照、去重决定、历史、独立账本共享预算 |
"""
from __future__ import annotations

import json
import uuid
from datetime import timedelta

from ..core.topic_candidates import TopicError, source_key, stamp, quota_day
from ..core.video_prefilter import fields, PURPOSE, CATEGORIES


class VideoPrefilterDAL:
    @staticmethod
    def _prefilter_schema(c):
        for ddl in (
            "CREATE TABLE IF NOT EXISTS prefilter_rules (id TEXT PRIMARY KEY, version INTEGER NOT NULL, config TEXT NOT NULL, updated_at TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS prefilter_jobs (id TEXT PRIMARY KEY, rule_id TEXT NOT NULL REFERENCES prefilter_rules(id), rule_version INTEGER NOT NULL, snapshot TEXT NOT NULL, control_version INTEGER NOT NULL, idempotency TEXT UNIQUE NOT NULL, state TEXT NOT NULL, phase TEXT NOT NULL, started_at TEXT NOT NULL, ended_at TEXT, code TEXT, counts TEXT NOT NULL DEFAULT '{}', has_more INTEGER NOT NULL DEFAULT 0, purpose TEXT NOT NULL CHECK(purpose='PREFILTER_ONLY'))",
            "CREATE TABLE IF NOT EXISTS prefilter_candidates (key TEXT PRIMARY KEY, decision TEXT NOT NULL DEFAULT 'NEW' CHECK(decision IN ('NEW','SAVED','REJECTED')), revision INTEGER NOT NULL DEFAULT 1)",
            "CREATE TABLE IF NOT EXISTS prefilter_results (job_id TEXT NOT NULL REFERENCES prefilter_jobs(id), key TEXT NOT NULL REFERENCES prefilter_candidates(key), observation TEXT, fetched_at TEXT NOT NULL, expires_at TEXT NOT NULL, PRIMARY KEY(job_id,key))",
            "CREATE TABLE IF NOT EXISTS prefilter_budget (id TEXT PRIMARY KEY, project TEXT NOT NULL, bucket TEXT NOT NULL, day TEXT NOT NULL, units INTEGER NOT NULL, job_id TEXT NOT NULL REFERENCES prefilter_jobs(id), created_at TEXT NOT NULL)",
            "CREATE INDEX IF NOT EXISTS prefilter_budget_day ON prefilter_budget(project,bucket,day)",
            "CREATE INDEX IF NOT EXISTS prefilter_results_expiry ON prefilter_results(expires_at)",
        ):
            c.execute(ddl)

    @staticmethod
    def _prefilter_maintenance(c, now, recover):
        c.execute("UPDATE prefilter_results SET observation=NULL WHERE expires_at<=?", (stamp(now),))
        if recover:
            c.execute("UPDATE prefilter_jobs SET state='INTERRUPTED',phase='FINISHED',code='RESTARTED',ended_at=? WHERE state='RUNNING'", (stamp(now),))

    def prefilter_rules(self):
        with self._topic_connection() as c:
            return [dict(id=r['id'], version=r['version'], **json.loads(r['config']))
                    for r in c.execute("SELECT * FROM prefilter_rules ORDER BY rowid")]

    def prefilter_save(self, value, actor, now, *, rule_id=None, version=None):
        config = fields(value)
        with self._topic_connection(write=True) as c:
            old = c.execute("SELECT * FROM prefilter_rules WHERE id=?", (rule_id,)).fetchone()
            if rule_id and (not old or old['version'] != version):
                raise TopicError("STALE", "规则已更新，请重新载入；当前草稿已保留")
            if old and c.execute("SELECT 1 FROM prefilter_jobs WHERE rule_id=? AND state='RUNNING'", (rule_id,)).fetchone():
                raise TopicError("BUSY", "本规则正在检索，请结束后保存")
            if not old and c.execute("SELECT COUNT(*) FROM prefilter_rules").fetchone()[0] >= 20:
                raise TopicError("CAPACITY", "最多保存 20 套预筛选规则", 422)
            rule_id, version = rule_id or uuid.uuid4().hex, (old['version'] + 1 if old else 1)
            c.execute("INSERT INTO prefilter_rules VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET version=excluded.version,config=excluded.config,updated_at=excluded.updated_at",
                      (rule_id, version, json.dumps(config, ensure_ascii=False), stamp(now)))
            self._topic_audit(c, actor, "PREFILTER_SAVE", rule_id, version, now)
        return dict(id=rule_id, version=version, **config)

    @staticmethod
    def _prefilter_job(row):
        return dict(row, snapshot=json.loads(row['snapshot']), counts=json.loads(row['counts']))

    def prefilter_jobs(self, *, idem=None, rule_id=None):
        where, args = (" WHERE idempotency=?", (idem,)) if idem else ((" WHERE rule_id=?", (rule_id,)) if rule_id else ("", ()))
        with self._topic_connection() as c:
            return [self._prefilter_job(r) for r in c.execute("SELECT * FROM prefilter_jobs" + where + " ORDER BY rowid DESC LIMIT 30", args)]

    def prefilter_create_job(self, rule_id, version, idem, actor, now):
        with self._topic_connection(write=True) as c:
            existing = c.execute("SELECT * FROM prefilter_jobs WHERE idempotency=?", (idem,)).fetchone()
            if existing:
                if existing['rule_id'] != rule_id:
                    raise TopicError("INVALID_IDEMPOTENCY", "请求标识不匹配", 422)
                return self._prefilter_job(existing)
            rule = c.execute("SELECT * FROM prefilter_rules WHERE id=?", (rule_id,)).fetchone()
            if not rule or rule['version'] != version:
                raise TopicError("STALE", "规则已更新，请重新载入")
            control = c.execute("SELECT * FROM topic_control").fetchone()
            if control['mode'] != 'DISCOVERY_ONLY':
                raise TopicError("SEARCH_CLOSED", "手动搜索已关闭", 403)
            if c.execute("SELECT 1 FROM prefilter_jobs WHERE state='RUNNING'").fetchone() or c.execute("SELECT 1 FROM topic_jobs WHERE state IN ('RUNNING','STOPPING')").fetchone():
                raise TopicError("BUSY", "其他搜索正在进行，请稍后重试")
            recent = c.execute("SELECT 1 FROM prefilter_jobs WHERE rule_id=? AND started_at>?", (rule_id, stamp(now-timedelta(minutes=15)))).fetchone()
            if recent:
                raise TopicError("COOLDOWN", "同规则两次检索需间隔 15 分钟")
            job_id = uuid.uuid4().hex
            c.execute("INSERT INTO prefilter_jobs(id,rule_id,rule_version,snapshot,control_version,idempotency,state,phase,started_at,purpose) VALUES(?,?,?,?,?,?,'RUNNING','SEARCH',?,?)",
                      (job_id, rule_id, version, rule['config'], control['version'], idem, stamp(now), PURPOSE))
            self._topic_audit(c, actor, "PREFILTER_SEARCH", rule_id, version, now)
            return self._prefilter_job(c.execute("SELECT * FROM prefilter_jobs WHERE id=?", (job_id,)).fetchone())

    @staticmethod
    def _prefilter_check(c, job_id):
        job = c.execute("SELECT * FROM prefilter_jobs WHERE id=?", (job_id,)).fetchone()
        control = c.execute("SELECT * FROM topic_control").fetchone()
        if not job or job['state'] != 'RUNNING' or control['mode'] != 'DISCOVERY_ONLY' or control['version'] != job['control_version']:
            raise TopicError("STOPPED", "本轮检索已停止，或搜索运行状态已改变")
        rule = c.execute("SELECT version FROM prefilter_rules WHERE id=?", (job['rule_id'],)).fetchone()
        if not rule or rule['version'] != job['rule_version']:
            raise TopicError("STALE", "规则版本已改变，本轮停止")
        return job

    def prefilter_check(self, job_id):
        with self._topic_connection() as c:
            self._prefilter_check(c, job_id)

    @staticmethod
    def _shared_budget_used(c, bucket, *, project=None, day=None):
        clause, args = " WHERE bucket=?", [bucket]
        if project is not None:
            clause += " AND project=? AND day=?"
            args += [project, day]
        return sum(c.execute("SELECT COALESCE(SUM(units),0) FROM " + table + clause, args).fetchone()[0]
                   for table in ('topic_budget', 'prefilter_budget'))

    def prefilter_reserve(self, job_id, project, bucket, limit, now, *, trial=False):
        if bucket not in ('search', 'general'):
            raise TopicError("INVALID_BUCKET", "预算桶无效", 422)
        with self._topic_connection(write=True) as c:
            self._prefilter_check(c, job_id)
            if trial and self._shared_budget_used(c, bucket) >= (3 if bucket == 'search' else 6):
                raise TopicError("TRIAL_BUDGET", "试运行累计额度已用完，跨日或重启不重置")
            if self._shared_budget_used(c, bucket, project=project, day=quota_day(now)) >= limit:
                raise TopicError("BUDGET", "共享官方 API 今日预算不足，等待太平洋时间次日")
            c.execute("INSERT INTO prefilter_budget VALUES(?,?,?,?,?,?,?)", (uuid.uuid4().hex, project, bucket, quota_day(now), 1, job_id, stamp(now)))

    def prefilter_progress(self, job_id, phase, counts):
        with self._topic_connection(write=True) as c:
            self._prefilter_check(c, job_id)
            c.execute("UPDATE prefilter_jobs SET phase=?,counts=? WHERE id=?", (phase, json.dumps(counts), job_id))

    def prefilter_store(self, job_id, observations, now):
        with self._topic_connection(write=True) as c:
            self._prefilter_check(c, job_id)
            for result in observations:
                key = source_key(result['metadata']['youtube_id'])
                c.execute("INSERT OR IGNORE INTO prefilter_candidates(key) VALUES(?)", (key,))
                c.execute("INSERT INTO prefilter_results VALUES(?,?,?,?,?)", (job_id, key, json.dumps(result, ensure_ascii=False), stamp(now), stamp(now+timedelta(days=30))))

    def prefilter_finish(self, job_id, state, code, counts, now, has_more=False):
        if state not in ('COMPLETE', 'PARTIAL', 'FAILED', 'INTERRUPTED'):
            raise TopicError("INVALID_STATE", "无效作业状态", 422)
        with self._topic_connection(write=True) as c:
            c.execute("UPDATE prefilter_jobs SET state=?,phase='FINISHED',code=?,counts=?,ended_at=?,has_more=? WHERE id=? AND state='RUNNING'",
                      (state, code, json.dumps(counts), stamp(now), int(has_more), job_id))

    def prefilter_results(self, job_id, category='', page=1):
        if category and category not in CATEGORIES:
            raise TopicError("INVALID_CATEGORY", "分类无效", 422)
        clause = "r.job_id=? AND r.observation IS NOT NULL"
        args = [job_id]
        if category:
            clause += " AND json_extract(r.observation,'$.category')=?"
            args.append(category)
        with self._topic_connection() as c:
            job = c.execute("SELECT * FROM prefilter_jobs WHERE id=?", (job_id,)).fetchone()
            if not job:
                raise TopicError("NOT_FOUND", "检索记录不存在", 404)
            total = c.execute("SELECT COUNT(*) FROM prefilter_results r WHERE " + clause, args).fetchone()[0]
            rows = c.execute("SELECT r.*,c.decision,c.revision FROM prefilter_results r JOIN prefilter_candidates c USING(key) WHERE " + clause + " ORDER BY json_extract(r.observation,'$.metadata.views') DESC,r.key LIMIT 25 OFFSET ?", args+[(page-1)*25]).fetchall()
            return dict(job=self._prefilter_job(job), total=total, page=page, page_size=25,
                        results=[dict(r, observation=json.loads(r['observation'])) for r in rows])

    def prefilter_decide(self, job_id, key, revision, content_version, decision, actor, now):
        if decision not in ('NEW', 'SAVED', 'REJECTED'):
            raise TopicError("INVALID_DECISION", "整理动作无效", 422)
        with self._topic_connection(write=True) as c:
            row = c.execute("SELECT r.*,c.revision FROM prefilter_results r JOIN prefilter_candidates c USING(key) WHERE job_id=? AND key=?", (job_id, key)).fetchone()
            if not row or not row['observation'] or row['expires_at'] <= stamp(now):
                raise TopicError("RECHECK", "资料已到期，请重新检索")
            result = json.loads(row['observation'])
            if row['revision'] != revision or result['content_version'] != content_version:
                raise TopicError("STALE", "整理决定已更新，请重新读取结果")
            if decision == 'SAVED' and result['category'] != 'QUALIFIED':
                raise TopicError("RECHECK", "仅可收藏本轮合格候选")
            c.execute("UPDATE prefilter_candidates SET decision=?,revision=revision+1 WHERE key=?", (decision,key))
            self._topic_audit(c, actor, 'PREFILTER_'+decision, key, revision+1, now)
        return dict(saved=True, purpose=PURPOSE)

    def prefilter_result(self, job_id, key):
        with self._topic_connection() as c:
            row = c.execute("SELECT * FROM prefilter_results WHERE job_id=? AND key=?", (job_id,key)).fetchone()
            return dict(row, observation=json.loads(row['observation']) if row['observation'] else None) if row else None
