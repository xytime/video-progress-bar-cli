"""同供应商候选批次暂存；依赖：processor/provider → 本模块 → 质量纯函数。

身份绑定源文件/ASR、完整源文、完整上下文、provider/profile 和实际 prompt。
暂存不是完成快照，取出后仍须原来的整片质量、修复和成片门。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-29 | Codex | 原子、内容绑定的候选批次暂存和匹配 profile 的有界成本探测。 |
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time

from .translation_quality_guard import evaluate_translation_batch
from .subtitle_translation_provider import SubtitleTranslationCandidate

VERSION = 'subtitle-candidate-batches-v1'


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     allow_nan=False).encode()).hexdigest()


class CandidateBatchCache:
    def __init__(self, root, *, provider, profile, binding, texts, context,
                 batch_rows=25, batch_seconds=30.0, deadline=None, event=None, prompt_factory=None):
        self.texts, self.context = list(texts), context
        self.provider, self.profile = provider, dict(profile)
        self.identity = dict(version=VERSION, provider=provider, profile=profile, binding=binding,
                             source_sha256=_hash(texts), context_sha256=_hash(context))
        self.directory = Path(root) / VERSION / _hash(self.identity)
        self.batch_rows, self.batch_seconds = batch_rows, float(batch_seconds)
        self.deadline, self.event = deadline, event
        self.observations = []
        self.prompt_factory, self.cached_offsets = prompt_factory, set()
        self._observed_offsets = set()

    @contextmanager
    def lease(self):
        """同身份的候选构建不可重叠；无锁时让上层按 busy 退出。"""
        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory / 'candidate.lock').open('a+') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield self
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def _valid(self, items, offset, count):
        if not isinstance(items, list) or len(items) != count:
            return False
        if any(not isinstance(item, dict) or not isinstance(item.get('translation'), str)
               or not item['translation'].strip() or not isinstance(item.get('vocab', {}), dict)
               for item in items):
            return False
        if SubtitleTranslationCandidate(self.provider,
                [item['translation'] for item in items]).contract_error_for(count):
            return False
        result = evaluate_translation_batch(self.texts[offset:offset + count],
            [item['translation'] for item in items], context_text=self.context,
            next_source_text=self.texts[offset + count] if offset + count < len(self.texts) else '',
            require_amount_coverage=True)
        return result.passed

    def load(self, offset, count, prompt, *, inventory=False):
        identity = dict(**self.identity, offset=offset, count=count, prompt_sha256=_hash(prompt))
        try:
            payload = json.loads((self.directory / f'{offset:06d}.json').read_text())
            if payload['identity'] != identity or payload['result_sha256'] != _hash(
                    dict(items=payload['items'], model=payload['model'])):
                return None
            allowed_models = self.profile.get('models') or [self.profile.get('model')]
            if any(allowed_models) and payload['model'] not in allowed_models:
                return None
            if not self._valid(payload['items'], offset, count):
                return None
            elapsed = float(payload['elapsed_seconds'])
            if not math.isfinite(elapsed) or elapsed < 0:
                return None
            if offset not in self._observed_offsets:
                self.observations.append(max(0.01, elapsed))
                self._observed_offsets.add(offset)
            self.cached_offsets.add(offset)
            if not inventory:
                self._event('batch_reused', offset=offset, count=count, model=payload['model'])
            return payload['items'], payload['model']
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def store(self, offset, count, prompt, items, model, elapsed):
        if not self._valid(items, offset, count):
            return False
        payload = dict(identity=dict(**self.identity, offset=offset, count=count,
                                    prompt_sha256=_hash(prompt)), items=items,
                       result_sha256=_hash(dict(items=items, model=model)),
                       model=model, elapsed_seconds=max(0.0, elapsed), kind='CANDIDATE_BATCH')
        temporary = None
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile('w', dir=self.directory, encoding='utf-8', delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(payload, stream, ensure_ascii=False, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.directory / f'{offset:06d}.json')
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        self.observations.append(max(0.01, elapsed))
        self._observed_offsets.add(offset)
        self.cached_offsets.add(offset)
        self._event('batch_observed', offset=offset, count=count, model=model,
                    elapsed_ms=int(elapsed * 1000))
        return True

    def permit(self, offset):
        """首批是有界探测；后续按本候选真实慢批成本检查整片完成机会。"""
        if self.deadline is None:
            return True
        remaining = max(0.0, self.deadline - time.monotonic())
        if not self.observations:
            return remaining >= min(10.0, self.batch_seconds)
        measured = max(self.observations) * 1.5
        batches = sum(start not in self.cached_offsets
                      for start in range(offset, len(self.texts), self.batch_rows))
        permitted = remaining >= max(10.0, measured * batches)
        if not permitted:
            self._event('batch_budget_stopped', offset=offset, remaining_ms=int(remaining * 1000),
                        required_ms=int(measured * batches * 1000))
        return permitted

    def inventory(self):
        """请求前盘点：读回实际 prompt、哈希与事实门，不能仅按文件存在扣减成本。"""
        if self.prompt_factory:
            self.cached_offsets.clear()
            self.observations.clear()
            self._observed_offsets.clear()
            for offset in range(0, len(self.texts), self.batch_rows):
                count = min(self.batch_rows, len(self.texts) - offset)
                self.load(offset, count, self.prompt_factory(offset, count), inventory=True)
        remaining = math.ceil(len(self.texts) / self.batch_rows) - len(self.cached_offsets)
        cost = max(self.observations) * 1.5 if self.observations else self.batch_seconds
        return dict(remaining_batches=remaining, cached_batches=len(self.cached_offsets),
                    estimated_seconds=remaining * cost,
                    cost_basis='matched_profile_observed' if self.observations else 'cold_start_estimate')

    def request_deadline(self, deadline):
        # 冷启动只用一个估值窗口探测，不让 SDK 的多模型重试吞掉整候选额度。
        window = max(10.0, max(self.observations) * 2) if self.observations else self.batch_seconds
        return min(deadline, time.monotonic() + window)

    def _event(self, action, **data):
        if self.event:
            self.event(dict(action=action, provider=self.provider,
                            profile_sha256=_hash(self.profile), **data))
