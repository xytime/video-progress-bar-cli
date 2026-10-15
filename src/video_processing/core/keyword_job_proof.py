"""阶段开放的真实账本核验；作业 ID 仅用于定位，不能替代成功结果。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-14 | Codex | 成功作业、项目预算、统一评分及自然刷新间隔核验 |
| 1.1.0 | 2026-10-15 | Codex | 长期采用沿用并复验原自然作业证据链 |
"""
from datetime import datetime
import json

from .deployment import require
from ..scoring import compute_policy_score, SCORE_POLICY_VERSION


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value)
        require(parsed.tzinfo is not None, 'KEYWORD_JOB_TIME_INVALID')
        return parsed.timestamp()
    except (TypeError, ValueError):
        require(False, 'KEYWORD_JOB_TIME_INVALID')


def job_proof(db, transition, config, previous, now):
    target = transition['target']
    if target in ('OFF', 'TRIAL'):
        return {}
    require(previous is not None, 'KEYWORD_PREVIOUS_STAGE_REQUIRED')
    prior = previous['transition']
    require(prior['target'] == transition['source'], 'KEYWORD_PREVIOUS_STAGE_MISMATCH')
    evidence = transition['evidence']
    trial_ids = evidence['trial_job_ids']
    if transition['source'] != 'TRIAL':
        require(trial_ids == prior['evidence']['trial_job_ids'], 'KEYWORD_TRIAL_CHAIN_MISMATCH')
    if transition['source'] in ('ADMISSION', 'LONG_TERM'):
        # 长期迁移沿用已验收阶段的真实自然作业链，不能换成任意较老作业。
        for name in ('scheduled_job_ids', 'refresh_job_ids'):
            require(evidence[name] == prior['evidence'][name], 'KEYWORD_COLLECTION_CHAIN_MISMATCH')
    groups = [('trial_job_ids', 'MANUAL')]
    if target in ('ADMISSION', 'LONG_TERM'):
        groups += [('scheduled_job_ids', 'SCHEDULED'), ('refresh_job_ids', 'REFRESH')]
    ids = [i for name, _ in groups for i in evidence[name]]
    require(len(ids) == len(set(ids)), 'KEYWORD_JOB_ID_REUSED')
    rows = db.keyword_rollout_jobs(ids)
    require(set(rows) == set(ids), 'KEYWORD_JOB_EVIDENCE_MISSING')
    for name, kind in groups:
        for job_id in evidence[name]:
            job = rows[job_id]
            require(job['kind'] == kind and job['state'] == 'COMPLETE' and job['code'] == 'OK',
                    'KEYWORD_JOB_NOT_SUCCESSFUL')
            start, end = timestamp(job['started_at']), timestamp(job['ended_at'])
            recorded = timestamp(job['snapshot']['recorded_at'])
            require(start <= recorded <= end <= now, 'KEYWORD_JOB_TIME_INVALID')
            if transition['source'] == 'TRIAL' or kind != 'MANUAL' and transition['source'] not in ('ADMISSION', 'LONG_TERM'):
                require(start >= prior['created_at'], 'KEYWORD_JOB_PRECEDES_STAGE')
            budget = job['budget']
            require(budget and all(b['project'] == evidence['project'] and
                    b['bucket'] in ('search', 'general') and type(b['units']) is int and b['units'] > 0
                    for b in budget), 'KEYWORD_JOB_BUDGET_MISMATCH')
            used = {b['bucket']: b['units'] for b in budget}
            require(used.get('general', 0) >= 1 and
                    (used.get('search', 0) == 0 if kind == 'REFRESH' else used.get('search', 0) >= 1),
                    'KEYWORD_JOB_REQUESTS_MISSING')
            scores = job['snapshot']['rows']
            require(bool(scores), 'KEYWORD_JOB_RESULTS_MISSING')
            valid = 0
            for candidate in scores:
                require(start <= timestamp(candidate['fetched_at']) <= recorded,
                        'KEYWORD_JOB_STATISTICS_STALE')
                if candidate['score'] is None:
                    continue
                inputs = json.loads(candidate['score_inputs'])
                require(candidate['score_policy'] == SCORE_POLICY_VERSION and inputs.get('source') == 'KEYWORD'
                        and type(candidate['score']) is int
                        and candidate['score'] == compute_policy_score(inputs, config), 'KEYWORD_JOB_SCORE_MISMATCH')
                valid += 1
            require(valid > 0, 'KEYWORD_JOB_SCORE_MISSING')
    if target in ('ADMISSION', 'LONG_TERM'):
        searched = {r['key']: timestamp(r['fetched_at']) for i in evidence['scheduled_job_ids']
                    for r in rows[i]['snapshot']['rows']}
        refreshed = [r for i in evidence['refresh_job_ids'] for r in rows[i]['snapshot']['rows']]
        require(any(r['key'] in searched and timestamp(r['fetched_at']) - searched[r['key']] >= 14400
                    for r in refreshed), 'KEYWORD_NATURAL_REFRESH_MISSING')
    return rows
