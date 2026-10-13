"""关键词作业的非秘密评分快照；与结果同事务保存，不补造历史证据。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-14 | Codex | 持久作业结果和实际预算关联，供阶段采用核验 |
"""
import json

from ..core.topic_candidates import stamp


class KeywordEvidenceDAL:
    @staticmethod
    def _keyword_evidence_schema(c):
        c.execute('CREATE TABLE IF NOT EXISTS keyword_job_evidence (job_id TEXT PRIMARY KEY REFERENCES topic_jobs(id), snapshot TEXT NOT NULL)')

    @staticmethod
    def _keyword_record_evidence(c, job_id, keys, now):
        rows = []
        for key in sorted(set(keys)):
            row = c.execute('SELECT key,youtube_id,score,score_policy,score_inputs,fetched_at,revision FROM topic_candidates WHERE key=?', (key,)).fetchone()
            if row:
                rows.append(dict(row))
        snapshot = dict(recorded_at=stamp(now), rows=rows)
        # 同一作业不能重写原证据；失败作业即使留有快照也不能通过部署检查。
        c.execute('INSERT INTO keyword_job_evidence VALUES(?,?)', (job_id, json.dumps(snapshot)))

    def keyword_rollout_jobs(self, ids):
        """在同一读取事务内核对作业、预算与评分快照；不存在的 ID 不会生成占位证据。"""
        with self._topic_connection() as c:
            result = {}
            for job_id in ids:
                row = c.execute('SELECT j.id,j.kind,j.state,j.code,j.started_at,j.ended_at,e.snapshot FROM topic_jobs j JOIN keyword_job_evidence e ON e.job_id=j.id WHERE j.id=?', (job_id,)).fetchone()
                if row:
                    item = dict(row)
                    item['snapshot'] = json.loads(item['snapshot'])
                    item['budget'] = [dict(b) for b in c.execute('SELECT project,bucket,SUM(units) units FROM topic_budget WHERE job_id=? GROUP BY project,bucket ORDER BY project,bucket', (job_id,))]
                    result[job_id] = item
            return result
