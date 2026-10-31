"""不含字幕正文的追加式阶段证据；不以心跳存活冒充阶段完成。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-29 | Codex | 独立尝试、阶段壁钟与子阶段指标；未绑定时零副作用。 |
| 1.1.0 | 2026-10-29 | Codex | 分离整片、字幕阶段、调度与交付事实；有效吞吐仅使用显式观测窗口。 |
| 1.1.1 | 2026-10-29 | Codex | 汇总真实等待及未知时长；持久排队仅记经过校验的墙钟近似。 |
"""
from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import math
import os
from pathlib import Path
import re
import threading
import time
import uuid

logger = logging.getLogger(__name__)
_active = contextvars.ContextVar("pipeline_stage_journal", default=None)
_ROLES = frozenset({'attempt', 'phase', 'control', 'delivery'})
_DELIVERIES = ('qualified_local_video', 'publication_package_ready', 'platform_accepted',
               'management_published_confirmed', 'public_verified')
_FIELDS = frozenset("""
duration_seconds frames ocr_calls reused_frames cache_hit resumed_frames decode_seconds
encode_seconds vision_seconds checkpoint_seconds compare_seconds normalize_seconds failed reason resource owner_token owner provider
requests batches cached_batches remaining_batches budget_seconds remaining_seconds
reserve_seconds allocation_seconds estimated_seconds elapsed_seconds outcome code
category wait_seconds resource_wait_seconds lock_wait_seconds queue_wait_seconds
request_seconds candidate_complete quality_passed attempt_count cache_key model
contract version bytes worker_count slot queued_at priority sequence backend
source_fingerprint attempt_budget_seconds reused_segments total_segments plan
request_count total_requests cached_segments phase budget_exhausted seconds
action offset count profile_sha256 elapsed_ms remaining_ms required_ms estimated_ms
allocation_ms fallback_reserve_ms cost_basis probe parent_attempt_id
""".split())


def _safe_data(data: dict) -> dict:
    """只接收计量和枚举值；禁止日志意外携带输入、密钥或供应商响应。"""
    safe = {}
    for key, value in data.items():
        if key not in _FIELDS:
            continue
        if value is None or isinstance(value, (bool, int)):
            safe[key] = value
        elif isinstance(value, float) and math.isfinite(value):
            safe[key] = value
        elif isinstance(value, str) and len(value) <= 160 and "\n" not in value:
            safe[key] = value
    return safe


def canonical_task_id(input_stem: str, *, scope_key: str | None = None) -> str:
    """父子统一视频/切片身份；继承租约优先，独立 CLI 兼容既有 _sN 文件名。"""
    if scope_key is not None:
        match = re.fullmatch(r'([A-Za-z0-9_-]+):([0-9]+)', scope_key)
        if match is None:
            raise ValueError('invalid preparation task identity')
        return f'{match[1]}:{int(match[2])}'
    stem = str(input_stem)
    match = re.fullmatch(r'(.+)_s([0-9]+)', stem)
    return f'{match[1]}:{int(match[2])}' if match else f'{stem}:0'


def persistent_queue_wait_seconds(queued_at, *, now=None):
    """持久队列时间是墙钟近似，可能受系统校时影响；非法/未知起点不记 0。"""
    current = time.time() if now is None else now
    if any(type(value) not in (int, float) or not math.isfinite(value) or value < 0
           for value in (queued_at, current)):
        return None
    return max(0.0, current - queued_at)


class StageJournal:
    """单次执行证据。所有阶段区间仅由本次执行的单调时钟计算。"""

    def __init__(self, path: Path, *, task_id: str, attempt_id: str, role: str = 'attempt'):
        self.path = Path(path)
        self.task_id = str(task_id)
        self.attempt_id = str(attempt_id)
        if role not in _ROLES:
            raise ValueError('unknown stage journal role')
        self.role = role
        self._lock = threading.RLock()
        self._stage = ""
        self._started = 0.0
        self._closed = False
        self._sequence = 0

    def emit(self, kind: str, *, stage: str = "", **data) -> None:
        """证据写入失败单独告警，不改变业务状态或伪造成功回执。"""
        try:
            with self._lock:
                self._sequence += 1
                record = {
                    "schema": "pipeline-stage-events-v1", "event_id": uuid.uuid4().hex,
                    "task_id": self.task_id, "attempt_id": self.attempt_id,
                    "role": self.role,
                    "sequence": self._sequence, "pid": os.getpid(),
                    "timestamp": time.time(), "kind": kind, "stage": stage,
                    **_safe_data(data),
                }
                encoded = (json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n").encode()
                self.path.parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                try:
                    # 一个 append；并发进程必须使用不同 attempt 文件。
                    written = os.write(fd, encoded)
                    if written != len(encoded):
                        raise OSError("short stage event write")
                finally:
                    os.close(fd)
        except (OSError, ValueError, TypeError):
            logger.warning("阶段证据写入失败: %s", self.path, exc_info=True)

    def transition(self, stage: str) -> None:
        with self._lock:
            if self._closed or self._stage == stage:
                return
            now = time.monotonic()
            if self._stage:
                self.emit("stage_end", stage=self._stage,
                          duration_seconds=max(0.0, now - self._started), outcome="advanced")
            self._stage, self._started = stage, now
            self.emit("stage_start", stage=stage)

    def close(self, outcome: str) -> None:
        with self._lock:
            if self._closed:
                return
            if self._stage:
                self.emit("stage_end", stage=self._stage,
                          duration_seconds=max(0.0, time.monotonic() - self._started),
                          outcome=outcome)
            self.emit("attempt_end", outcome=outcome)
            self._closed = True


@contextlib.contextmanager
def bind_journal(journal: StageJournal | None):
    token = _active.set(journal)
    try:
        if journal:
            journal.emit("attempt_start")
        yield journal
    finally:
        _active.reset(token)


def emit_event(kind: str, *, stage: str = "", **data) -> None:
    journal = _active.get()
    if journal is not None:
        journal.emit(kind, stage=stage, **data)


def transition_stage(stage: str) -> None:
    """外层编排阶段；没有绑定尝试时不产生证据。"""
    journal = _active.get()
    if journal is not None:
        journal.transition(stage)


def current_journal():
    """供编排入口避免对子任务重复创建同层尝试。"""
    return _active.get()


def summarize_events(paths, *, cohort=None, observation_window=None) -> dict:
    """整片尝试与子阶段分列；吞吐只用显式窗口内的成片事实，不推算分母。

    observation_window 是调用方选择的 UTC epoch 起止秒，采用 [start, end)。
    窗口只限定吞吐事实；尝试历史和固定 cohort 仍保留所有输入证据。
    """
    window = None
    if observation_window is not None:
        if (not isinstance(observation_window, (tuple, list)) or len(observation_window) != 2
                or any(type(value) not in (int, float) or not math.isfinite(value) or value < 0
                       for value in observation_window)
                or observation_window[1] <= observation_window[0]):
            raise ValueError('observation_window must contain increasing finite epoch seconds')
        window = dict(start=observation_window[0], end=observation_window[1],
                      duration_seconds=observation_window[1] - observation_window[0])
    by_role = {name: {} for name in ('attempt', 'phase', 'control')}
    metrics, errors, deliveries, window_deliveries = {}, 0, {}, {}
    waits, pending_resources = {}, {}

    def record_wait(kind, stage, resource, duration):
        bucket = waits.setdefault((kind, stage, resource), dict(kind=kind, stage=stage,
            resource=resource, records=0, known_duration_count=0, known_duration_seconds=None,
            unknown_duration_count=0))
        bucket['records'] += 1
        if type(duration) in (int, float) and math.isfinite(duration) and duration >= 0:
            bucket['known_duration_count'] += 1
            bucket['known_duration_seconds'] = (bucket['known_duration_seconds'] or 0.0) + duration
        else:
            bucket['unknown_duration_count'] += 1
    delivered_attempts = set()
    seen_events = set()
    members = set(cohort) if cohort is not None else None
    for path in paths:
        try:
            lines = Path(path).read_text(encoding="utf-8").splitlines()
        except OSError:
            errors += 1
            continue
        for line in lines:
            try:
                item = json.loads(line)
                if not isinstance(item, dict) or item.get("schema") != "pipeline-stage-events-v1":
                    raise ValueError("unknown schema")
                if not all(isinstance(item.get(name), str) for name in
                           ('task_id', 'attempt_id', 'event_id', 'kind', 'stage')):
                    raise ValueError('invalid event identity')
                role = item.get('role', 'attempt')  # 兼容引入 role 前的整片日志。
                if role not in _ROLES:
                    raise ValueError('unknown journal role')
                key = (item["task_id"], item["attempt_id"])
                event_key = (role, *key, item['event_id'])
                if event_key in seen_events:
                    continue
                seen_events.add(event_key)
                timestamp = item.get('timestamp')
                valid_timestamp = (type(timestamp) in (int, float) and
                                   math.isfinite(timestamp) and timestamp >= 0)
                if item['kind'] == 'delivery_evidence' and role in {'attempt', 'delivery'}:
                    evidence = item.get('outcome')
                    if evidence in _DELIVERIES:
                        deliveries.setdefault(evidence, set()).add(key[0])
                        if (window is not None and valid_timestamp and
                                window['start'] <= timestamp < window['end'] and
                                (members is None or key[0] in members)):
                            window_deliveries.setdefault(evidence, set()).add(key[0])
                        if role == 'attempt' and evidence == 'qualified_local_video':
                            delivered_attempts.add(key)
                if role == 'delivery':
                    continue  # 独立回查只有交付事实，不能增加加工尝试数。
                resource = item.get('resource', '')
                if not isinstance(resource, str):
                    resource = ''
                waiting_key = (role, *key, item['stage'], resource)
                if item['kind'] == 'resource_wait':
                    pending_resources[waiting_key] = pending_resources.get(waiting_key, 0) + 1
                elif item['kind'] == 'resource_acquired':
                    if pending_resources.get(waiting_key, 0):
                        pending_resources[waiting_key] -= 1
                    record_wait('resource_wait', item['stage'], resource, item.get('duration_seconds'))
                elif item['kind'] in {'lock_acquired', 'lock_wait', 'queue_wait', 'publication_wait'}:
                    kind = 'lock_wait' if item['kind'] == 'lock_acquired' else item['kind']
                    record_wait(kind, item['stage'], resource, item.get('duration_seconds'))
                attempt = by_role[role].setdefault(key, {"task_id": key[0], "attempt_id": key[1],
                    "role": role, "outcome": "unknown", "stage_wall_seconds": {},
                    "ended_at": None, "last_event_at": 0})
                if valid_timestamp:
                    attempt['last_event_at'] = max(attempt['last_event_at'], timestamp)
                if item["kind"] == "attempt_end":
                    attempt["outcome"] = item.get("outcome", "unknown")
                    attempt["ended_at"] = timestamp if valid_timestamp else None
                if item["kind"] == "stage_end":
                    duration = item.get("duration_seconds")
                    if type(duration) in (float, int) and math.isfinite(duration) and duration >= 0:
                        bucket = attempt["stage_wall_seconds"]
                        stage = item["stage"]
                        bucket[stage] = bucket.get(stage, 0.0) + duration
                if item["kind"] == "metric":
                    bucket = metrics.setdefault(item["stage"], {"records": 0})
                    bucket["records"] += 1
                    for name in ("duration_seconds", "frames", "ocr_calls", "reused_frames",
                                 "decode_seconds", "encode_seconds", "vision_seconds", "checkpoint_seconds"):
                        value = item.get(name)
                        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
                            bucket[name] = bucket.get(name, 0) + value
            except (ValueError, TypeError, KeyError):
                errors += 1
    for waiting_key, count in pending_resources.items():
        for _ in range(count):
            record_wait('resource_wait', waiting_key[-2], waiting_key[-1], None)
    rows = list(by_role['attempt'].values())
    # 必须提供固定分母；失败/复核/中断不能从分母剔除来改善完成率。
    cohort_report = None
    if members is not None:
        groups = {name: set() for name in ('completed', 'review', 'failed', 'pending_or_unknown')}
        for member in members:
            evidence = [row for row in rows if row['task_id'] == member]
            latest = max(evidence, key=lambda row: row['last_event_at'], default={})
            outcome = latest.get('outcome', 'unknown')
            if (member, latest.get('attempt_id')) in delivered_attempts:
                groups['completed'].add(member)
            elif outcome == 'review':
                groups['review'].add(member)
            elif outcome == 'failed':
                groups['failed'].add(member)
            else:
                groups['pending_or_unknown'].add(member)
        cohort_report = {'size': len(members), 'counts': {k: len(v) for k, v in groups.items()},
            'rates': {k: (len(v) / len(members) if members else None) for k, v in groups.items()},
            'note': '仅按显式终态及成片证据；无结束或缺失证据保留在固定分母。'}
    return {"schema": "pipeline-stage-summary-v1", "attempts": rows,
            "attempt_count": len(rows), "metrics": metrics, "unreadable_records": errors,
            "waits": list(waits.values()),
            "phase_attempts": list(by_role['phase'].values()), "phase_count": len(by_role['phase']),
            "control_runs": list(by_role['control'].values()), "control_count": len(by_role['control']),
            "delivery_counts": ({name: (len(deliveries[name]) if name in deliveries else None)
                                  for name in _DELIVERIES} if deliveries else None),
            "observation_window": window,
            "effective_per_hour": (len(window_deliveries['qualified_local_video']) * 3600 /
                                   window['duration_seconds'] if window is not None and
                                   'qualified_local_video' in window_deliveries else None),
            "cohort": cohort_report,
            "attempt_note": "整片仅计 attempt；字幕 CLI 为 phase，调度器为 control，独立回查为 delivery。",
            "timing_note": "stage_wall_seconds 包含等待，不能与 waits 相加；持久排队是墙钟近似，非单调时钟，受系统校时影响。",
            "delivery_note": "仅统计显式证据；未接入证据为未知，不从成片或受理推断后续发布。"}
