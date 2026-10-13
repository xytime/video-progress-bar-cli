"""首期候选门面：手动作业、内核并发锁、宿主保护、持久预算。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| keyword-stage-v1 | 2026-10-14 | Codex | 非秘密阶段配置绑定原生部署日志，维护、漂移及完成回读闭锁 |
| 0.4.1 | 2026-10-14 | Codex | 试运行累计预算入账及错误配置关闭，提供非秘密用量回读 |
| 0.4.0 | 2026-10-13 | Codex | 关键词定时采集、统一评分和受控准入隔离实现 |
| 1.0.1 | 2026-10-12 | Codex | 锁故障脱敏，维护状态阻止模式开放与搜索 |
| 1.0.0 | 2026-10-11 | Codex | 实现 v0.2 的 OFF/仅发现与有界停止；无主管线或发布调用 |
"""
from __future__ import annotations

import fcntl
import logging
import threading
import time
from pathlib import Path

from ..core.topic_candidates import (TopicError, utc_now, metadata, source_key,
                                     eligibility, content_version)
from ..utils.topic_search import SearchFailure


from .collection import KeywordCollection


class TopicTracker(KeywordCollection):
    def __init__(self, db, config, adapter, rules, *, clock=utc_now):
        self.db, self.config, self.adapter, self.rules, self.clock = db, config, adapter, rules, clock
        self.lock_path = Path(db.db_path + ".topic-search.lock")
        self._threads = set()
        self._mutex = threading.Lock()
        self.db.topic_initialize()
        lock = self._lock()
        try:
            self.db.topic_maintenance(self.clock(), recover=lock is not None)
        finally:
            if lock:
                lock.close()
        self.enforce_closed()

    def enforce_closed(self):
        from ..core.maintenance import gate
        closed = not self.config.topic_search_enabled or gate().status()["state"] != "RUNNING"
        if closed and self.db.topic_control()["mode"] != "OFF":
            control = self.db.topic_control()
            self.db.topic_set_mode("OFF", control["version"], "host", self.clock())

    def _lock(self):
        stream = None
        try:
            stream = self.lock_path.open("a")
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return stream
        except BlockingIOError:
            stream.close()
            return None
        except OSError as exc:
            if stream:
                stream.close()
            raise TopicError("LOCK_UNAVAILABLE", "候选执行锁不可用", 503) from exc

    def maintenance(self):
        lock = self._lock()
        try:
            self.db.topic_maintenance(self.clock(), recover=lock is not None)
        finally:
            if lock:
                lock.close()
        self.enforce_closed()

    def _ready(self):
        from ..core.maintenance import gate, MaintenanceDenied
        try:
            gate().require_running()
        except MaintenanceDenied as exc:
            raise TopicError(exc.code, str(exc), 503) from exc
        if not self.config.topic_search_enabled:
            raise TopicError("SEARCH_CLOSED", "生产搜索尚未开放", 403)
        if hasattr(self.config, "topic_rollout_snapshot"):
            from ..core.keyword_rollout import verify_loaded
            try:
                if not verify_loaded(self.config, complete=True):
                    raise ValueError("KEYWORD_PROFILE_REQUIRED")
            except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
                raise TopicError("ROLLOUT_UNVERIFIED", "阶段配置或部署回执未通过核实，搜索保持关闭", 503) from exc
        if getattr(self.config, "topic_trial_mode", False) and (
                getattr(self.config, "topic_scheduler_enabled", False) or
                getattr(self.config, "topic_admission_enabled", False)):
            raise TopicError("TRIAL_CONFIG", "试运行阶段必须关闭定时采集和自动准入", 403)
        if not self.config.topic_quota_verified or not self.config.topic_quota_project:
            raise TopicError("QUOTA_UNVERIFIED", "项目配额与可分配额度尚未核实", 403)
        if not self.config.enable_market_hours_guard:
            raise TopicError("GUARD_DISABLED", "宿主保护机制未开启", 403)
        try:
            blocked = self.config.is_us_market_guard_window(self.clock())
        except Exception as exc:
            raise TopicError("GUARD_UNKNOWN", "宿主保护状态无法确认", 503) from exc
        if blocked:
            raise TopicError("MARKET_GUARD", "当前处于宿主保护窗口")

    def mode(self, mode, version, actor):
        if mode == "DISCOVERY_ONLY":
            self._ready()
        return self.db.topic_set_mode(mode, version, actor, self.clock())

    def start(self, topic_id, version, idem, actor):
        from ..core.maintenance import gate, MaintenanceDenied
        ticket = None
        try:
            ticket = gate().acquire("topic-search", topic_id)
            ticket.start()
            return self._start_admitted(topic_id, version, idem, actor, ticket)
        except MaintenanceDenied as exc:
            if ticket:
                ticket.close()
            raise TopicError(exc.code, str(exc), 503) from exc
        except BaseException:
            if ticket:
                ticket.close()
            raise

    def _start_admitted(self, topic_id, version, idem, actor, ticket):
        existing = self.db.topic_jobs(idem=idem)
        if existing:
            if existing[0]["topic_id"] != topic_id:
                raise TopicError("INVALID_IDEMPOTENCY", "请求标识不匹配", 422)
            ticket.close()
            return existing[0]
        self._ready()
        if not self.adapter.configured():
            raise TopicError("NO_API", "未配置官方 API", 403)
        lock = self._lock()
        if not lock:
            # 双击即便在前一请求刚创建作业时也复用同一记录。
            existing = self.db.topic_jobs(idem=idem)
            if existing:
                if existing[0]["topic_id"] != topic_id:
                    raise TopicError("INVALID_IDEMPOTENCY", "请求标识不匹配", 422)
                ticket.close()
                return existing[0]
            raise TopicError("BUSY", "其他搜索正在进行，请稍后重试")
        try:
            self.db.topic_maintenance(self.clock(), recover=True)
            job = self.db.topic_create_job(topic_id, version, idem, actor, self.clock())
            topic = self.db.topic_get(topic_id, self.clock())
            worker = threading.Thread(target=self._run, args=(job, topic, lock, ticket), daemon=True, name="topic-search")
            with self._mutex:
                self._threads.add(worker)
            worker.start()
            return job
        except Exception:
            lock.close()
            raise

    def _timeout(self, job_id, deadline):
        self._ready()
        current_job = self.db.topic_check_job(job_id, self.clock())
        if current_job["kind"] != "MANUAL" and not getattr(self.config,"topic_scheduler_enabled",False):
            raise TopicError("STOPPED", "定时采集已关闭")
        remaining = min(20, deadline - time.monotonic())
        # 在保护窗口边界之前结束请求，不另建时间窗定义。
        from datetime import timedelta
        for second in range(1, 21):
            try:
                guarded = self.config.is_us_market_guard_window(self.clock() + timedelta(seconds=second))
            except Exception as exc:
                raise TopicError("GUARD_UNKNOWN", "宿主保护状态无法确认", 503) from exc
            if guarded:
                remaining = min(remaining, second - 0.5)
                break
        if remaining < 0.5:
            raise TopicError("DEADLINE", "本轮时间不足，搜索已停止")
        return remaining

    def _request(self, job_id, bucket, deadline, method, *args):
        timeout = self._timeout(job_id, deadline)
        limit = self.config.topic_search_daily_limit if bucket == "search" else self.config.topic_general_daily_limit
        self.db.topic_reserve(job_id, self.config.topic_quota_project, bucket, limit, self.clock(),
                              trial=getattr(self.config, "topic_trial_mode", False))
        timeout = self._timeout(job_id, deadline)
        return method(*args, timeout=timeout)

    def _evaluate(self, meta, topic=None):
        try:
            presence = self.db.topic_presence(meta["youtube_id"], meta["channel_id"])
            version = self.rules.version()
            state, reason = eligibility(meta, self.rules.check, presence, (topic or {}).get("min_duration", 30))
            if self.rules.version() != version:
                raise TopicError("RULE_CHANGED", "审查规则正在更新，请重新核实")
        except Exception:
            presence = dict(pipeline_present=False, pipeline_states=[])
            version, state, reason = "unknown", "INCOMPLETE", "审查或主库状态无法确认，不能收藏"
        return dict(metadata=meta, eligibility=state, reason=reason, rule_version=version,
                    content_version=content_version(meta, version, state, reason), **presence)

    def _run(self, job, topic, lock, ticket):
        deadline = time.monotonic() + 60
        phase = "search"
        try:
            from datetime import datetime
            started = datetime.fromisoformat(job["started_at"])
            items = self._request(job["id"], "search", deadline, self.adapter.search, topic, started)
            ids = []
            for item in items[:25]:
                video_id = (item.get("id") or {}).get("videoId")
                try:
                    source_key(video_id)
                except TopicError:
                    raise SearchFailure("INVALID_RESPONSE", "官方响应视频身份不完整")
                if video_id not in ids:
                    ids.append(video_id)
            candidates = []
            if ids:
                phase = "details"
                try:
                    details = self._request(job["id"], "general", deadline, self.adapter.details, ids)
                except SearchFailure as exc:
                    if not exc.retryable:
                        raise
                    details = self._request(job["id"], "general", deadline, self.adapter.details, ids)
                by_id = {item.get("id"): item for item in details if item.get("id") in ids}
                candidates = [self._evaluate(metadata(i, by_id.get(i)), topic) for i in ids]
            self._timeout(job["id"], deadline)
            self.db.topic_store_results(job["id"], candidates, self.clock())
            self.db.keyword_job_coverage(job["id"], getattr(items, "has_more", False) or len(items)>25)
            self.db.keyword_score_results(job["id"], self.config, self.clock())
            self._finish(job["id"], "COMPLETE", "OK")
        except TopicError as exc:
            state = "INTERRUPTED" if exc.code in ("STOPPED", "SEARCH_CLOSED", "GUARD_DISABLED", "GUARD_UNKNOWN", "MARKET_GUARD", "DEADLINE") else "PARTIAL" if phase == "details" else "FAILED"
            self._finish(job["id"], state, exc.code)
        except Exception:
            self._finish(job["id"], "FAILED", "INTERNAL_ERROR")
        finally:
            try:
                lock.close()
            finally:
                try:
                    ticket.close()
                finally:
                    with self._mutex:
                        self._threads.discard(threading.current_thread())

    def _finish(self, job_id, state, code):
        # 每次写锁等待最多 2 秒；两次有界尝试后释放内核占用，读前恢复孤儿记录。
        for _ in range(2):
            try:
                self.db.topic_finish_job(job_id, state, code, self.clock())
                return
            except TopicError as exc:
                if exc.code != "DATABASE_BUSY":
                    break
            except Exception:
                break
        logging.getLogger(__name__).warning("专题作业停止记录未完成：数据库不可用；需本地恢复")

    def wait(self, timeout=25):
        """仅等待本模块线程；用于关闭与隔离验收，不影响其他作业。"""
        with self._mutex:
            workers = list(self._threads)
        deadline = time.monotonic() + timeout
        for worker in workers:
            worker.join(max(0, deadline - time.monotonic()))

    def candidates(self, **filters):
        self.maintenance()
        result = self.db.topic_candidates(**filters)
        observation_keys={r['key'] for r in self.db.keyword_observations(self.clock(),include_future=True)}
        for candidate in result["candidates"]:
            current = self._evaluate(candidate["metadata"], {"min_duration": self.db.keyword_min_duration(candidate["key"])})
            candidate.update(pipeline_present=current["pipeline_present"], pipeline_states=current["pipeline_states"])
            if current["content_version"] != candidate["content_version"]:
                self.db.topic_refresh_rules(candidate["key"], candidate["revision"], current)
                candidate["needs_review"] = candidate["state"] == "SAVED" and candidate["saved_version"] != current["content_version"]
                candidate.update({k: current[k] for k in ("eligibility", "reason", "rule_version", "content_version")})
                candidate["revision"] += 1
            candidate["collection"] = self.db.keyword_candidate_state(candidate["key"], self.config, self.clock(),observation_keys=observation_keys)
            candidate["can_save"] = (candidate["eligibility"] == "CHECKABLE" and not candidate["pipeline_present"] and candidate["state"] != "REJECTED")
        return result

    def decide(self, key, body, actor):
        row = self.db.topic_candidate(key)
        if body["state"] == "SAVED":
            if not row or not row["metadata"]:
                raise TopicError("RECHECK", "资料已到期，需重新核实")
            current = self._evaluate(row["metadata"], {"min_duration": self.db.keyword_min_duration(key)})
            if current["eligibility"] != "CHECKABLE" or current["content_version"] != row["content_version"]:
                raise TopicError("RECHECK", "资料或规则已变化，请重新载入并核实")
            rule_version = current["rule_version"]
        else:
            rule_version = ""
        self.db.topic_decide(key, body["revision"], body["decision_revision"], body["content_version"],
                            body["state"], body.get("reason"), rule_version, actor, self.clock())

    def view(self):
        self.maintenance()
        control = self.db.topic_control()
        try:
            self._ready()
            if not self.adapter.configured():
                raise TopicError("NO_API", "未配置官方 API", 403)
            can_enable = True
            reason_code, reason = ("MODE_OFF", "手动搜索已关闭") if control["mode"] == "OFF" else ("OK", "可手动搜索")
        except TopicError as exc:
            can_enable = False
            reason_code, reason = exc.code, str(exc)
        search_open = can_enable and control["mode"] == "DISCOVERY_ONLY"
        from ..core.maintenance import gate
        maintenance = gate().status()
        from config.keyword_rollout import FIELDS
        return dict(collection=dict(scheduler_enabled=getattr(self.config,"topic_scheduler_enabled",False), admission_available=getattr(self.config,"topic_admission_enabled",False), automatic_used=self.db.keyword_auto_budget(self.config.topic_quota_project,self.clock()), **self.db.keyword_control()), control=control, maintenance=dict(state=maintenance["state"], phase=maintenance["phase"]), topics=self.db.topic_list(self.clock()),
                    configuration={k: getattr(self.config, k, False if k.endswith(("enabled", "mode")) else 1) for k in FIELDS},
                    rollout=self.config.topic_rollout_snapshot() if hasattr(self.config, "topic_rollout_snapshot") else None,
                    jobs=self.db.topic_jobs(), budget=self.db.topic_budget(self.config.topic_quota_project, self.clock()),
                    search_open=search_open, can_enable=can_enable, search_gate=dict(code=reason_code, message=reason),
                    trial=dict(enabled=getattr(self.config, "topic_trial_mode", False), budget=self.db.topic_trial_budget()),
                    limits=dict(search=self.config.topic_search_daily_limit, general=self.config.topic_general_daily_limit))
