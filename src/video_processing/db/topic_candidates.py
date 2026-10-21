"""专题候选 DAL：独立增量表、短事务，主流水线与黑名单仅查询。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.1 | 2026-10-21 | Codex | 独立预筛选复用本机会话、官方请求与共享门禁预算 |
| 0.4.2 | 2026-10-14 | Codex | 规则恢复与每次自动调用验证首轮一条上限 |
| 0.5.0 | 2026-10-15 | Codex | 显式续期恢复、暂停保持、忙碌拒绝与审计 |
| 0.4.1 | 2026-10-14 | Codex | 试运行使用原子累计预算，跨日、重启和项目切换不重置 |
| 0.4.0 | 2026-10-13 | Codex | 关键词定时采集、统一评分和受控准入隔离实现 |
| 1.0.1 | 2026-10-12 | Codex | 连接及 PRAGMA 纳入完整故障边界，保证资源释放 |
| 1.0.0 | 2026-10-11 | Codex | 候选/决定/作业/配额持久化；原子预算与 CAS；不写主表 |
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import timedelta

from ..core.topic_candidates import (TopicError, TERMINAL, REASONS, source_key,
                                     stamp, quota_day, topic_fields)


from .keyword_collection import KeywordCollectionDAL
from .video_prefilter import VideoPrefilterDAL


class TopicCandidateDAL(KeywordCollectionDAL, VideoPrefilterDAL):
    """PipelineDB 的专题方法；不从应用层暴露 SQL 或连接。"""

    @contextmanager
    def _topic_connection(self, *, write=False):
        if getattr(self, "_read_only", False) and write:
            raise TopicError("READ_ONLY", "数据库为只读", 503)
        conn = None
        try:
            conn = self._connect_topic()
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            # 清理 API 字段时清零释放的页内容；不对共享主库执行 VACUUM。
            conn.execute("PRAGMA secure_delete=ON")
            if write:
                conn.execute("BEGIN IMMEDIATE")
            with conn:
                yield conn
        except sqlite3.OperationalError as exc:
            busy = getattr(exc, "sqlite_errorcode", None) in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
            raise TopicError("DATABASE_BUSY" if busy else "DATABASE_ERROR",
                             "候选数据库忙，请稍后重试" if busy else "候选数据库操作未完成", 503) from exc
        finally:
            if conn is not None:
                try:
                    conn.close()
                except sqlite3.OperationalError as exc:
                    raise TopicError("DATABASE_ERROR", "候选数据库资源释放未确认", 503) from exc

    def topic_initialize(self):
        with self._topic_connection(write=True) as c:
            for ddl in (
                "CREATE TABLE IF NOT EXISTS topic_control (id INTEGER PRIMARY KEY CHECK(id=1), mode TEXT NOT NULL CHECK(mode IN ('OFF','DISCOVERY_ONLY')), version INTEGER NOT NULL)",
                "CREATE TABLE IF NOT EXISTS topic_definitions (id TEXT PRIMARY KEY, name TEXT NOT NULL, query TEXT NOT NULL, category TEXT NOT NULL, lookback_days INTEGER NOT NULL, valid_days INTEGER NOT NULL, identity TEXT NOT NULL, expires_at TEXT NOT NULL, status TEXT NOT NULL, version INTEGER NOT NULL, last_run_at TEXT)",
                "CREATE TABLE IF NOT EXISTS topic_candidates (key TEXT PRIMARY KEY, youtube_id TEXT UNIQUE, metadata TEXT, fetched_at TEXT, expires_at TEXT, content_version TEXT, rule_version TEXT, eligibility TEXT, reason TEXT, revision INTEGER NOT NULL DEFAULT 1)",
                "CREATE TABLE IF NOT EXISTS topic_decisions (key TEXT PRIMARY KEY REFERENCES topic_candidates(key), state TEXT NOT NULL CHECK(state IN ('NEW','SAVED','REJECTED')), content_version TEXT, rule_version TEXT, reason TEXT, revision INTEGER NOT NULL DEFAULT 1)",
                "CREATE TABLE IF NOT EXISTS topic_jobs (id TEXT PRIMARY KEY, topic_id TEXT NOT NULL REFERENCES topic_definitions(id), topic_version INTEGER NOT NULL, control_version INTEGER NOT NULL, idempotency TEXT NOT NULL UNIQUE, state TEXT NOT NULL, started_at TEXT NOT NULL, ended_at TEXT, code TEXT, counts TEXT NOT NULL DEFAULT '{}')",
                "CREATE TABLE IF NOT EXISTS topic_hits (key TEXT REFERENCES topic_candidates(key), topic_id TEXT REFERENCES topic_definitions(id), job_id TEXT REFERENCES topic_jobs(id), topic_version INTEGER NOT NULL, PRIMARY KEY(key,topic_id,job_id))",
                "CREATE TABLE IF NOT EXISTS topic_budget (id TEXT PRIMARY KEY, project TEXT NOT NULL, bucket TEXT NOT NULL, day TEXT NOT NULL, units INTEGER NOT NULL, job_id TEXT NOT NULL REFERENCES topic_jobs(id), created_at TEXT NOT NULL)",
                "CREATE INDEX IF NOT EXISTS topic_budget_day ON topic_budget(project,bucket,day)",
                "CREATE INDEX IF NOT EXISTS topic_candidates_expiry ON topic_candidates(expires_at)",
                "CREATE TABLE IF NOT EXISTS topic_audit (id INTEGER PRIMARY KEY, actor TEXT NOT NULL, action TEXT NOT NULL, object_key TEXT NOT NULL, version TEXT NOT NULL, at TEXT NOT NULL, reason TEXT)",
                "CREATE TABLE IF NOT EXISTS topic_sessions (key TEXT PRIMARY KEY, expires_at TEXT NOT NULL)",
            ):
                c.execute(ddl)
            c.execute("INSERT OR IGNORE INTO topic_control VALUES(1,'OFF',1)")
            self._keyword_schema(c)
            self._prefilter_schema(c)

    @staticmethod
    def _topic_audit(c, actor, action, key, version, now, reason=None):
        c.execute("INSERT INTO topic_audit(actor,action,object_key,version,at,reason) VALUES(?,?,?,?,?,?)",
                  (actor, action, key, str(version), stamp(now), reason))

    @staticmethod
    def _topic_expire(c, now):
        c.execute("UPDATE topic_definitions SET status='EXPIRED', version=version+1 WHERE status IN ('ACTIVE','PAUSED') AND expires_at<=?", (stamp(now),))

    def topic_maintenance(self, now, *, recover=False):
        with self._topic_connection(write=True) as c:
            self._prefilter_maintenance(c, now, recover)
            self._topic_expire(c, now)
            c.execute("DELETE FROM topic_sessions WHERE expires_at<=?", (stamp(now),))
            c.execute("UPDATE topic_candidates SET youtube_id=NULL,metadata=NULL,fetched_at=NULL,expires_at=NULL,content_version=NULL,rule_version=NULL,score=NULL,score_policy=NULL,score_inputs=NULL,next_refresh=NULL,eligibility='INCOMPLETE',reason='资料已到期，需再次手动搜索',revision=revision+1 WHERE expires_at<=?", (stamp(now),))
            if recover:
                c.execute("UPDATE topic_jobs SET state='INTERRUPTED',code='RESTARTED',ended_at=? WHERE state IN ('RUNNING','STOPPING')", (stamp(now),))

    def topic_session(self, key, now, *, issue=False):
        with self._topic_connection(write=issue) as c:
            if issue:
                c.execute("INSERT INTO topic_sessions VALUES(?,?)", (key, stamp(now + timedelta(hours=8))))
                return True
            return c.execute("SELECT 1 FROM topic_sessions WHERE key=? AND expires_at>?", (key, stamp(now))).fetchone() is not None

    def topic_control(self):
        with self._topic_connection() as c:
            return dict(c.execute("SELECT mode,version FROM topic_control WHERE id=1").fetchone())

    def topic_set_mode(self, mode, version, actor, now):
        if mode not in ("OFF", "DISCOVERY_ONLY"):
            raise TopicError("INVALID_MODE", "运行模式无效", 422)
        with self._topic_connection(write=True) as c:
            changed = c.execute("UPDATE topic_control SET mode=?,version=version+1 WHERE id=1 AND version=?", (mode, version)).rowcount
            if not changed:
                raise TopicError("STALE", "运行状态已更新，请重新载入")
            if mode == "OFF":
                c.execute("UPDATE topic_jobs SET state='STOPPING' WHERE state='RUNNING'")
            self._topic_audit(c, actor, "MODE", "control", version + 1, now, mode)
        return self.topic_control()

    def topic_list(self, now):
        with self._topic_connection(write=True) as c:
            self._topic_expire(c, now)
            return [dict(r) for r in c.execute("SELECT t.*, (SELECT COUNT(DISTINCT key) FROM topic_hits WHERE topic_id=t.id) AS candidate_count FROM topic_definitions t ORDER BY rowid DESC LIMIT 500")]

    def topic_get(self, topic_id, now):
        with self._topic_connection(write=True) as c:
            self._topic_expire(c, now)
            row = c.execute("SELECT * FROM topic_definitions WHERE id=?", (topic_id,)).fetchone()
            if not row:
                raise TopicError("NOT_FOUND", "专题不存在", 404)
            return dict(row)

    def topic_save(self, value, actor, now, *, topic_id=None, expected_version=None):
        if topic_id:
            previous = self.topic_get(topic_id, now)
            value = {**previous, **value}
        fields = topic_fields(value)
        with self._topic_connection(write=True) as c:
            self._topic_expire(c, now)
            old = c.execute("SELECT * FROM topic_definitions WHERE id=?", (topic_id,)).fetchone() if topic_id else None
            if topic_id and (not old or old["version"] != expected_version):
                raise TopicError("STALE", "专题已更新，请重新载入")
            if old and old["status"] == "ARCHIVED":
                raise TopicError("ARCHIVED", "已归档专题不能编辑")
            if old and c.execute("SELECT 1 FROM topic_jobs WHERE topic_id=? AND state IN ('RUNNING','STOPPING')", (topic_id,)).fetchone():
                raise TopicError("BUSY", "搜索进行中，请结束后编辑")
            if c.execute("SELECT 1 FROM topic_definitions WHERE identity=? AND status IN ('ACTIVE','PAUSED') AND id!=?", (fields["identity"], topic_id or "")).fetchone():
                raise TopicError("DUPLICATE", "已有相同查询条件的有效专题", 422)
            status = old["status"] if old else "ACTIVE"
            if status == "ACTIVE" and not old and c.execute("SELECT COUNT(*) FROM topic_definitions WHERE status='ACTIVE'").fetchone()[0] >= 10:
                raise TopicError("CAPACITY", "最多 10 个有效专题，请先暂停或归档其他专题", 422)
            identity = topic_id or uuid.uuid4().hex
            version = old["version"] + 1 if old else 1
            expires = stamp(now + timedelta(days=fields["valid_days"]))
            c.execute("INSERT INTO topic_definitions(id,name,query,category,lookback_days,valid_days,identity,expires_at,status,version) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,query=excluded.query,category=excluded.category,lookback_days=excluded.lookback_days,valid_days=excluded.valid_days,identity=excluded.identity,expires_at=excluded.expires_at,version=excluded.version",
                      (identity, fields["name"], fields["query"], fields["category"], fields["lookback_days"], fields["valid_days"], fields["identity"], expires, status, version))
            c.execute("UPDATE topic_definitions SET language=?,min_duration=? WHERE id=?",
                      (fields["language"], fields["min_duration"], identity))
            self._topic_audit(c, actor, "EDIT" if old else "CREATE", identity, version, now)
        return self.topic_get(identity, now)

    def topic_renew(self, topic_id, version, valid_days, restore, actor, now):
        """明确续期；过期恢复须主动选择，暂停规则不因续期自动启用。"""
        if type(valid_days) is not int or not 1 <= valid_days <= 30 or type(restore) is not bool:
            raise TopicError('INVALID_EXPIRY', '续期需设置1–30天有效期', 422)
        with self._topic_connection(write=True) as c:
            self._topic_expire(c, now)
            old = c.execute('SELECT * FROM topic_definitions WHERE id=?', (topic_id,)).fetchone()
            if not old or old['version'] != version:
                raise TopicError('STALE', '采集规则已变化，请重新载入')
            if old['status'] == 'ARCHIVED':
                raise TopicError('ARCHIVED', '已归档规则不能续期')
            if c.execute("SELECT 1 FROM topic_jobs WHERE topic_id=? AND state IN ('RUNNING','STOPPING')", (topic_id,)).fetchone():
                raise TopicError('BUSY', '等待当前作业结束后续期')
            if old['status'] == 'EXPIRED' and not restore:
                raise TopicError('RESTORE_REQUIRED', '过期规则需明确选择续期并恢复')
            status = 'ACTIVE' if old['status'] == 'EXPIRED' else old['status']
            if status == 'ACTIVE':
                if old['auto_enabled']:
                    self._keyword_capacity(c, exclude=topic_id)
                if c.execute("SELECT COUNT(*) FROM topic_definitions WHERE status='ACTIVE' AND id!=?", (topic_id,)).fetchone()[0] >= 10:
                    raise TopicError('CAPACITY', '有效规则已达10个')
                if c.execute("SELECT 1 FROM topic_definitions WHERE identity=? AND id!=? AND status IN ('ACTIVE','PAUSED')", (old['identity'],topic_id)).fetchone():
                    raise TopicError('DUPLICATE', '已有相同条件的有效规则')
            c.execute('''UPDATE topic_definitions SET status=?,valid_days=?,expires_at=?,
                next_run_at=?,version=version+1 WHERE id=?''',
                (status,valid_days,stamp(now+timedelta(days=valid_days)),
                 stamp(now) if status=='ACTIVE' and old['auto_enabled'] else old['next_run_at'],topic_id))
            self._topic_audit(c,actor,'RENEW_RESTORE' if old['status']=='EXPIRED' else 'RENEW',topic_id,version+1,now,
                              f'{valid_days}天；{status}；原准入消耗保留')
        return self.topic_get(topic_id,now)

    def topic_transition(self, topic_id, version, status, actor, now, valid_days=None):
        if status not in ("ACTIVE", "PAUSED", "ARCHIVED"):
            raise TopicError("INVALID_STATE", "专题状态无效", 422)
        with self._topic_connection(write=True) as c:
            self._topic_expire(c, now)
            old = c.execute("SELECT * FROM topic_definitions WHERE id=?", (topic_id,)).fetchone()
            if not old or old["version"] != version:
                raise TopicError("STALE", "专题已更新，请重新载入")
            if old["status"] == "ARCHIVED":
                raise TopicError("ARCHIVED", "已归档专题不能恢复")
            expires = old["expires_at"]
            if status == "ACTIVE":
                if old['auto_enabled']:
                    self._keyword_capacity(c, exclude=topic_id)
                if old["status"] != "ACTIVE" and c.execute("SELECT COUNT(*) FROM topic_definitions WHERE status='ACTIVE'").fetchone()[0] >= 10:
                    raise TopicError("CAPACITY", "有效专题已达 10 个", 422)
                if old["status"] == "EXPIRED":
                    if type(valid_days) is not int or not 1 <= valid_days <= 30:
                        raise TopicError("INVALID_EXPIRY", "恢复过期专题需设置 1–30 天有效期", 422)
                    expires = stamp(now + timedelta(days=valid_days))
                if c.execute("SELECT 1 FROM topic_definitions WHERE identity=? AND id!=? AND status IN ('ACTIVE','PAUSED')", (old["identity"], topic_id)).fetchone():
                    raise TopicError("DUPLICATE", "已有相同条件的有效专题", 422)
            c.execute("UPDATE topic_definitions SET status=?,expires_at=?,version=version+1 WHERE id=?", (status, expires, topic_id))
            c.execute("UPDATE topic_jobs SET state='STOPPING' WHERE topic_id=? AND state='RUNNING'", (topic_id,))
            self._topic_audit(c, actor, status, topic_id, version + 1, now)
        return self.topic_get(topic_id, now)

    def topic_presence(self, video_id, channel_id):
        with self._topic_connection() as c:
            rows = c.execute("SELECT status,slice_index FROM processed_videos WHERE youtube_id=?", (video_id,)).fetchall()
            blocked = c.execute("SELECT 1 FROM blacklisted_videos WHERE youtube_id=?", (video_id,)).fetchone()
            channel = c.execute("SELECT status FROM recommended_channels WHERE channel_id=?", (channel_id,)).fetchone()
            return dict(pipeline_present=bool(rows), pipeline_states=[dict(r) for r in rows],
                        blacklisted=bool(blocked), channel_blocked=bool(channel and channel[0] == "BLACKLISTED"))

    def topic_create_job(self, topic_id, version, idem, actor, now, *, kind="MANUAL"):
        if kind not in ("MANUAL", "SCHEDULED", "REFRESH"):
            raise TopicError("INVALID_JOB", "作业类型无效")
        with self._topic_connection(write=True) as c:
            self._topic_expire(c, now)
            existing = c.execute("SELECT * FROM topic_jobs WHERE idempotency=?", (idem,)).fetchone()
            if existing:
                if existing["topic_id"] != topic_id:
                    raise TopicError("INVALID_IDEMPOTENCY", "重复请求标识不匹配", 422)
                return dict(existing)
            topic = c.execute("SELECT * FROM topic_definitions WHERE id=?", (topic_id,)).fetchone()
            if not topic or topic["version"] != version:
                raise TopicError("STALE", "专题已更新，请重新载入")
            control = c.execute("SELECT * FROM topic_control").fetchone()
            if topic["status"] != "ACTIVE" or control["mode"] != "DISCOVERY_ONLY":
                raise TopicError("STOPPED", "搜索已关闭，或专题已暂停/过期")
            if c.execute("SELECT 1 FROM topic_jobs WHERE state IN ('RUNNING','STOPPING')").fetchone():
                raise TopicError("BUSY", "其他搜索正在进行，请稍后重试")
            cooldown = stamp(now - timedelta(minutes=15))
            recent = c.execute("SELECT COALESCE(ended_at,started_at) at FROM topic_jobs WHERE topic_id=? AND COALESCE(ended_at,started_at)>? ORDER BY at DESC LIMIT 1", (topic_id, cooldown)).fetchone()
            if recent and kind != "REFRESH":
                from datetime import datetime
                from zoneinfo import ZoneInfo
                next_at = (datetime.fromisoformat(recent["at"]) + timedelta(minutes=15)).astimezone(ZoneInfo("Asia/Shanghai"))
                raise TopicError("COOLDOWN", f"同专题需间隔 15 分钟，可于北京时间 {next_at:%m-%d %H:%M:%S} 再次搜索")
            job_id = uuid.uuid4().hex
            c.execute("INSERT INTO topic_jobs(id,topic_id,topic_version,control_version,idempotency,state,started_at) VALUES(?,?,?,?,?,'RUNNING',?)", (job_id, topic_id, version, control["version"], idem, stamp(now)))
            c.execute("UPDATE topic_jobs SET kind=? WHERE id=?", (kind, job_id))
            if kind == "SCHEDULED":
                if not topic["auto_enabled"]:
                    raise TopicError("STOPPED", "定时采集未启用")
                c.execute("UPDATE topic_definitions SET next_run_at=? WHERE id=?", (stamp(now + timedelta(hours=4)), topic_id))
            if kind != "REFRESH":
                c.execute("UPDATE topic_definitions SET last_run_at=? WHERE id=?", (stamp(now), topic_id))
            self._topic_audit(c, actor, "SEARCH", topic_id, version, now)
            return dict(c.execute("SELECT * FROM topic_jobs WHERE id=?", (job_id,)).fetchone())

    @staticmethod
    def _topic_check_job(c, job_id, now):
        job = c.execute("SELECT * FROM topic_jobs WHERE id=?", (job_id,)).fetchone()
        if not job or job["state"] != "RUNNING":
            raise TopicError("STOPPED", "搜索正在停止")
        topic = c.execute("SELECT * FROM topic_definitions WHERE id=?", (job["topic_id"],)).fetchone()
        control = c.execute("SELECT * FROM topic_control").fetchone()
        if (topic["status"] != "ACTIVE" or topic["version"] != job["topic_version"] or topic["expires_at"] <= stamp(now)
                or control["mode"] != "DISCOVERY_ONLY" or control["version"] != job["control_version"]):
            raise TopicError("STOPPED", "专题或运行状态已改变")
        if job['kind'] in ('SCHEDULED','REFRESH'):
            KeywordCollectionDAL._keyword_capacity(c)
            if not topic['auto_enabled']:
                raise TopicError('STOPPED', '定时采集已停止')
        return job

    def topic_check_job(self, job_id, now):
        with self._topic_connection() as c:
            return dict(self._topic_check_job(c, job_id, now))

    def topic_reserve(self, job_id, project, bucket, limit, now, *, trial=False):
        if bucket not in ("search", "general"):
            raise TopicError("INVALID_BUCKET", "预算桶无效", 422)
        with self._topic_connection(write=True) as c:
            job = self._topic_check_job(c, job_id, now)
            if trial:
                if job["kind"] != "MANUAL":
                    raise TopicError("TRIAL_CONFIG", "试运行仅允许手动搜索")
                # 计入所有历史预留（包括失败和重试），不通过换项目或日期释放。
                total = self._shared_budget_used(c, bucket)
                if total >= (3 if bucket == "search" else 6):
                    raise TopicError("TRIAL_BUDGET", "试运行累计额度已用完；不会随跨日或重启恢复")
            if bucket == "search" and job["kind"] == "SCHEDULED":
                auto_used = c.execute("SELECT COUNT(*) FROM topic_budget b JOIN topic_jobs j ON j.id=b.job_id WHERE b.project=? AND b.bucket='search' AND b.day=? AND j.kind='SCHEDULED'", (project, quota_day(now))).fetchone()[0]
                if auto_used >= min(18, max(0, limit - 2)):
                    raise TopicError("BUDGET", "定时搜索额度已用完；保留手动搜索额度")
            used = self._shared_budget_used(c, bucket, project=project, day=quota_day(now))
            if used >= limit:
                raise TopicError("BUDGET", "本模块今日预算不足；请等待太平洋时间次日")
            c.execute("INSERT INTO topic_budget VALUES(?,?,?,?,?,?,?)", (uuid.uuid4().hex, project, bucket, quota_day(now), 1, job_id, stamp(now)))

    def topic_trial_budget(self):
        with self._topic_connection() as c:
            used = {bucket: self._shared_budget_used(c, bucket) for bucket in ('search', 'general')}
            return {bucket: dict(used=used.get(bucket, 0), limit=limit,
                                remaining=max(0, limit - used.get(bucket, 0)))
                    for bucket, limit in (("search", 3), ("general", 6))}

    def topic_budget(self, project, now):
        with self._topic_connection() as c:
            return dict(day=quota_day(now), **{bucket: self._shared_budget_used(c, bucket, project=project, day=quota_day(now))
                                             for bucket in ('search', 'general')})

    def topic_store_results(self, job_id, candidates, now):
        with self._topic_connection(write=True) as c:
            job = self._topic_check_job(c, job_id, now)
            counts = dict(new=0, duplicate=0, restricted=0)
            for candidate in candidates:
                meta = candidate["metadata"]
                key = source_key(meta["youtube_id"])
                old = c.execute("SELECT key FROM topic_candidates WHERE key=?", (key,)).fetchone()
                counts["duplicate" if old else "new"] += 1
                counts["restricted"] += int(candidate["eligibility"] != "CHECKABLE")
                c.execute("INSERT INTO topic_candidates(key,youtube_id,metadata,fetched_at,expires_at,content_version,rule_version,eligibility,reason) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET youtube_id=excluded.youtube_id,metadata=excluded.metadata,fetched_at=excluded.fetched_at,expires_at=excluded.expires_at,content_version=excluded.content_version,rule_version=excluded.rule_version,eligibility=excluded.eligibility,reason=excluded.reason,revision=topic_candidates.revision+1", (key, meta["youtube_id"], json.dumps(meta, ensure_ascii=False), stamp(now), stamp(now + timedelta(days=30)), candidate["content_version"], candidate["rule_version"], candidate["eligibility"], candidate["reason"]))
                c.execute("INSERT OR IGNORE INTO topic_decisions(key,state) VALUES(?,'NEW')", (key,))
                c.execute("INSERT OR IGNORE INTO topic_hits VALUES(?,?,?,?)", (key, job["topic_id"], job_id, job["topic_version"]))
            c.execute("UPDATE topic_jobs SET counts=? WHERE id=?", (json.dumps(counts), job_id))
            return counts

    def topic_finish_job(self, job_id, state, code, now):
        if state not in TERMINAL:
            raise TopicError("INVALID_STATE", "搜索结果状态无效", 422)
        with self._topic_connection(write=True) as c:
            c.execute("UPDATE topic_jobs SET state=?,code=?,ended_at=? WHERE id=? AND state IN ('RUNNING','STOPPING')", (state, code, stamp(now), job_id))

    def topic_jobs(self, *, idem=None):
        with self._topic_connection() as c:
            select = "SELECT j.*, (SELECT COALESCE(SUM(units),0) FROM topic_budget WHERE job_id=j.id AND bucket='search') search_requests, (SELECT COALESCE(SUM(units),0) FROM topic_budget WHERE job_id=j.id AND bucket='general') general_units FROM topic_jobs j"
            rows = c.execute(select + " WHERE idempotency=?", (idem,)) if idem else c.execute(select + " ORDER BY started_at DESC,j.rowid DESC LIMIT 30")
            return [dict(r, counts=json.loads(r["counts"])) for r in rows]

    def topic_candidates(self, *, topic_id="", state="", eligibility="", q="", page=1):
        where, params = ["c.metadata IS NOT NULL"], []
        if topic_id:
            where.append("EXISTS(SELECT 1 FROM topic_hits h WHERE h.key=c.key AND h.topic_id=?)")
            params.append(topic_id)
        if state:
            where.append("d.state=?")
            params.append(state)
        if eligibility:
            where.append("c.eligibility=?")
            params.append(eligibility)
        if q:
            where.append("(json_extract(c.metadata,'$.title') LIKE ? ESCAPE '\\' OR json_extract(c.metadata,'$.channel_name') LIKE ? ESCAPE '\\')")
            pattern = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            params.extend((pattern, pattern))
        clause = " AND ".join(where)
        with self._topic_connection() as c:
            total = c.execute("SELECT COUNT(*) FROM topic_candidates c JOIN topic_decisions d USING(key) WHERE " + clause, params).fetchone()[0]
            rows = c.execute("SELECT c.*,d.state,d.content_version saved_version,d.rule_version saved_rules,d.revision decision_revision FROM topic_candidates c JOIN topic_decisions d USING(key) WHERE " + clause + " ORDER BY json_extract(c.metadata,'$.published_at') DESC,c.key LIMIT 25 OFFSET ?", params + [(page - 1) * 25]).fetchall()
            result = []
            for row in rows:
                record = dict(row)
                record["metadata"] = json.loads(record["metadata"])
                record["topics"] = [dict(r) for r in c.execute("SELECT DISTINCT t.id,t.name FROM topic_hits h JOIN topic_definitions t ON h.topic_id=t.id WHERE h.key=?", (row["key"],))]
                record["needs_review"] = row["state"] == "SAVED" and row["saved_version"] != row["content_version"]
                result.append(record)
            return dict(candidates=result, total=total, page=page, page_size=25)

    def topic_decide(self, key, revision, decision_revision, content_version, state, reason, rule_version, actor, now):
        if state not in ("NEW", "SAVED", "REJECTED") or (state == "REJECTED" and reason not in REASONS):
            raise TopicError("INVALID_DECISION", "请选择有效的整理动作与原因", 422)
        with self._topic_connection(write=True) as c:
            old = c.execute("SELECT c.*,d.state,d.revision decision_revision FROM topic_candidates c JOIN topic_decisions d USING(key) WHERE key=?", (key,)).fetchone()
            if not old or old["revision"] != revision or old["decision_revision"] != decision_revision or old["content_version"] != content_version:
                raise TopicError("STALE", "候选资料或整理决定已更新，请重新载入")
            if old["state"] == "REJECTED":
                raise TopicError("REJECTED", "排除决定不能恢复")
            if state == "SAVED":
                if old["eligibility"] != "CHECKABLE" or old["rule_version"] != rule_version or not old["expires_at"] or old["expires_at"] <= stamp(now):
                    raise TopicError("RECHECK", "资料或规则已变化，需重新核实")
                meta = json.loads(old["metadata"])
                if c.execute("SELECT 1 FROM processed_videos WHERE youtube_id=?", (meta["youtube_id"],)).fetchone() or c.execute("SELECT 1 FROM blacklisted_videos WHERE youtube_id=?", (meta["youtube_id"],)).fetchone() or c.execute("SELECT 1 FROM recommended_channels WHERE channel_id=? AND status='BLACKLISTED'", (meta["channel_id"],)).fetchone():
                    raise TopicError("PIPELINE_PRESENT", "已在主流水线或黑名单，不能收藏")
            c.execute("UPDATE topic_decisions SET state=?,content_version=?,rule_version=?,reason=?,revision=revision+1 WHERE key=?", (state, old["content_version"], old["rule_version"], reason if state == "REJECTED" else None, key))
            self._topic_audit(c, actor, state, key, old["content_version"], now, reason if state == "REJECTED" else None)

    def topic_candidate(self, key):
        with self._topic_connection() as c:
            row = c.execute("SELECT * FROM topic_candidates WHERE key=?", (key,)).fetchone()
            return dict(row, metadata=json.loads(row["metadata"]) if row["metadata"] else None) if row else None

    def topic_refresh_rules(self, key, revision, current):
        with self._topic_connection(write=True) as c:
            if not c.execute("UPDATE topic_candidates SET rule_version=?,eligibility=?,reason=?,content_version=?,revision=revision+1 WHERE key=? AND revision=?", (current["rule_version"], current["eligibility"], current["reason"], current["content_version"], key, revision)).rowcount:
                raise TopicError("STALE", "候选资料已更新，请重新载入")

    def topic_audit_records(self):
        with self._topic_connection() as c:
            return [dict(r) for r in c.execute("SELECT * FROM topic_audit ORDER BY id DESC LIMIT 100")]
    def _connect_topic(self):
        """候选连接的单一故障注入边界；生产使用真实 SQLite。"""
        return sqlite3.connect(self.db_path, timeout=2)
