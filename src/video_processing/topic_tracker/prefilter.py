"""手动视频预筛选；依赖 tracker 的锁/门禁，独立 DAL 和纯规则，不调用准入。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-21 | Codex | 官方 API、共享限额、真实阶段、仅人工预筛选 |
"""
from __future__ import annotations

import logging
import re
import threading
import time
from datetime import datetime

from ..core.topic_candidates import TopicError, metadata, source_key, digest
from ..core.video_prefilter import DEFAULTS, PURPOSE, CATEGORIES, observation
from ..utils.topic_search import SearchFailure


class VideoPrefilter:
    def __init__(self, tracker):
        self.tracker = tracker
        self.db = tracker.db

    def view(self):
        tracker = self.tracker
        tracker.maintenance()
        try:
            tracker._ready()
            if not tracker.adapter.configured():
                raise TopicError('NO_API', '未配置官方 API', 403)
            if self.db.topic_control()['mode'] != 'DISCOVERY_ONLY':
                raise TopicError('SEARCH_CLOSED', '手动搜索已关闭；请在配置与运维中核实', 403)
            can_search, code, message = True, 'OK', '可手动检索；不会进入生产或发布'
        except TopicError as exc:
            can_search, code, message = False, exc.code, exc.message
        config = tracker.config
        budget = self.db.topic_budget(config.topic_quota_project, tracker.clock())
        trial = self.db.topic_trial_budget() if getattr(config, 'topic_trial_mode', False) else None
        exhausted = (budget['search'] >= config.topic_search_daily_limit or
                     budget['general'] >= config.topic_general_daily_limit)
        if trial and any(v['remaining'] == 0 for v in trial.values()):
            can_search, code, message = False, 'TRIAL_BUDGET', '试运行累计额度已用完，跨日或重启不重置'
        elif exhausted:
            can_search, code, message = False, 'BUDGET', '共享 API 今日预算不足，等待太平洋时间次日'
        return dict(purpose=PURPOSE, rules=self.db.prefilter_rules(), defaults=DEFAULTS,
                    jobs=self.db.prefilter_jobs(), can_search=can_search,
                    gate=dict(code=code, message=message), budget=budget, trial=trial,
                    limits=dict(search=config.topic_search_daily_limit, general=config.topic_general_daily_limit))

    def start(self, rule_id, version, idem, actor):
        from ..core.maintenance import gate, MaintenanceDenied
        tracker, ticket, lock = self.tracker, None, None
        try:
            existing = self.db.prefilter_jobs(idem=idem)
            if existing:
                if existing[0]['rule_id'] != rule_id:
                    raise TopicError('INVALID_IDEMPOTENCY', '请求标识不匹配', 422)
                return existing[0]
            ticket = gate().acquire('topic-search', rule_id)
            ticket.start()
            tracker._ready()
            if not tracker.adapter.configured():
                raise TopicError('NO_API', '未配置官方 API', 403)
            lock = tracker._lock()
            if not lock:
                existing = self.db.prefilter_jobs(idem=idem)
                if existing and existing[0]['rule_id'] == rule_id:
                    return existing[0]
                raise TopicError('BUSY', '其他搜索正在进行，请稍后重试')
            self.db.topic_maintenance(tracker.clock(), recover=True)
            job = self.db.prefilter_create_job(rule_id, version, idem, actor, tracker.clock())
            worker = threading.Thread(target=self._run, args=(job, lock, ticket), daemon=True, name='video-prefilter')
            with tracker._mutex:
                tracker._threads.add(worker)
            try:
                worker.start()
            except BaseException:
                with tracker._mutex:
                    tracker._threads.discard(worker)
                self.db.prefilter_finish(job['id'], 'FAILED', 'WORKER_START', {}, tracker.clock())
                raise
            lock, ticket = None, None  # 由 worker 的 finally 持有并释放。
            return job
        except MaintenanceDenied as exc:
            raise TopicError(exc.code, str(exc), 503) from exc
        finally:
            if lock:
                lock.close()
            if ticket:
                ticket.close()

    def _timeout(self, job_id, deadline):
        self.tracker._ready()
        self.db.prefilter_check(job_id)
        return self.tracker._guard_timeout(deadline)

    def _request(self, job_id, bucket, deadline, method, *args):
        self._timeout(job_id, deadline)
        config = self.tracker.config
        limit = config.topic_search_daily_limit if bucket == 'search' else config.topic_general_daily_limit
        self.db.prefilter_reserve(job_id, config.topic_quota_project, bucket, limit, self.tracker.clock(),
                                  trial=getattr(config, 'topic_trial_mode', False))
        return method(*args, timeout=self._timeout(job_id, deadline))

    def _evaluate(self, video_id, item, rule, started):
        meta = metadata(video_id, item)
        if item is None:
            meta['availability'] = 'UNKNOWN'
        else:
            # 官方计数应为无符号整数字符串；不将小数、负数或布尔值截断成有效统计。
            for source, target in (('viewCount', 'views'), ('likeCount', 'likes')):
                raw = (item.get('statistics') or {}).get(source)
                if isinstance(raw, bool) or not re.fullmatch(r'\d+', str(raw)):
                    meta[target] = None
            status = item.get('status') or {}
            live = item.get('liveStreamingDetails') or {}
            if live and (not live.get('actualEndTime') or status.get('uploadStatus') != 'processed'):
                meta['availability'] = 'LIVE'
        try:
            presence = self.db.topic_presence(video_id, meta['channel_id'])
            rules = self.tracker.rules
            policy_version = rules.version()
            reason = rules.check(meta)
            if rules.version() != policy_version:
                raise TopicError('RULE_CHANGED', '审查规则已变化')
            return observation(meta, rule, started, presence, policy_version, reason)
        except Exception:
            result = observation(meta, rule, started, {}, 'unknown')
            result.update(category='INCOMPLETE', reasons=['黑名单或内容策略状态无法核实'])
            result['content_version'] = digest(result)
            return result

    def _run(self, job, lock, ticket):
        tracker = self.tracker
        counts = dict(returned=0, detailed=0, **{k: 0 for k in CATEGORIES})
        results, has_more, stored = [], False, False
        try:
            started = datetime.fromisoformat(job['started_at'])
            rule, deadline = job['snapshot'], time.monotonic()+60
            items = self._request(job['id'], 'search', deadline, tracker.adapter.prefilter_search, rule, started)
            ids = []
            for item in items[:rule['candidate_count']]:
                video_id = (item.get('id') or {}).get('videoId')
                source_key(video_id)
                if video_id not in ids:
                    ids.append(video_id)
            counts['returned'] = len(ids)
            has_more = bool(getattr(items, 'has_more', False) or len(items) > rule['candidate_count'])
            self.db.prefilter_progress(job['id'], 'DETAILS', counts)
            if ids:
                try:
                    details = self._request(job['id'], 'general', deadline, tracker.adapter.prefilter_details, ids)
                except SearchFailure as exc:
                    for video_id in ids:
                        meta = metadata(video_id, None)
                        results.append(dict(metadata=meta, category='FAILED', reasons=[exc.message],
                                            policy_version='unknown', content_version=digest([video_id,exc.code]), purpose=PURPOSE))
                    counts['FAILED'] = len(ids)
                    self._timeout(job['id'], deadline)
                    self.db.prefilter_store(job['id'], results, tracker.clock())
                    stored = True
                    self.db.prefilter_finish(job['id'], 'FAILED', exc.code, counts, tracker.clock(), has_more)
                    return
                by_id = {item.get('id'): item for item in details if item.get('id') in ids}
                counts['detailed'] = len(by_id)
                for video_id in ids:
                    result = self._evaluate(video_id, by_id.get(video_id), rule, started)
                    results.append(result)
                    counts[result['category']] += 1
            self._timeout(job['id'], deadline)
            self.db.prefilter_store(job['id'], results, tracker.clock())
            stored = True
            self.db.prefilter_finish(job['id'], 'PARTIAL' if counts['detailed'] < len(ids) else 'COMPLETE',
                                     'MISSING_DETAILS' if counts['detailed'] < len(ids) else 'OK', counts, tracker.clock(), has_more)
        except TopicError as exc:
            interrupted = exc.code in ('STOPPED', 'SEARCH_CLOSED', 'MARKET_GUARD', 'GUARD_DISABLED', 'GUARD_UNKNOWN', 'DEADLINE')
            self._finish(job['id'], 'INTERRUPTED' if interrupted else 'FAILED', exc.code, counts, stored=stored)
        except Exception:
            self._finish(job['id'], 'FAILED', 'INTERNAL_ERROR', counts, stored=stored)
        finally:
            lock.close()
            ticket.close()
            with tracker._mutex:
                tracker._threads.discard(threading.current_thread())

    def _finish(self, job_id, state, code, counts, *, stored):
        if not stored:
            for category in CATEGORIES:
                counts[category] = 0
        counts['unprocessed'] = counts['returned'] - sum(counts[k] for k in CATEGORIES)
        for _ in range(2):
            try:
                self.db.prefilter_finish(job_id, state, code, counts, self.tracker.clock())
                return
            except TopicError:
                continue
        logging.getLogger(__name__).warning('预筛选终态未写入；读取时恢复孤儿记录')

    def decide(self, job_id, key, body, actor):
        # 收藏前再检查当前黑名单及规则；不重新搜索，不授予任何自动准入身份。
        if body['decision'] == 'SAVED':
            record = self.db.prefilter_result(job_id, key)
            if not record or not record['observation']:
                raise TopicError('RECHECK', '资料已到期，请重新检索')
            result = record['observation']
            meta = result['metadata']
            try:
                presence = self.db.topic_presence(meta['youtube_id'], meta['channel_id'])
                current_version = self.tracker.rules.version()
                current_reason = self.tracker.rules.check(meta)
                if current_version != self.tracker.rules.version():
                    raise RuntimeError('policy changed')
            except Exception as exc:
                raise TopicError('RECHECK', '当前黑名单或内容策略无法核实', 503) from exc
            if (presence['blacklisted'] or presence['channel_blocked'] or
                    result['policy_version'] != current_version or current_reason):
                raise TopicError('RECHECK', '黑名单或内容策略已变化，请重新核实')
        return self.db.prefilter_decide(job_id, key, body['revision'], body['content_version'], body['decision'], actor, self.tracker.clock())
