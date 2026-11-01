"""Gemini 已完成批次的断点；仅复用完整结构，整片质量门仍由调用者执行。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-01 | Codex | 同全文、上下文、提示与实现绑定的原子批次快照，拒绝部分或损坏候选。 |
"""
import hashlib
import json
import logging
import os
from pathlib import Path
import tempfile

from .subtitle_translation_provider import SubtitleTranslationCandidate

LOG = logging.getLogger(__name__)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     allow_nan=False).encode()).hexdigest()


class GeminiBatchCache:
    """只保存供应商输出；快照并不表示通过全片质量或允许发布。"""
    def __init__(self, directory, identity, models):
        self.directory = Path(directory) if directory is not None else None
        self.identity = fingerprint(dict(schema=1, input=identity, models=list(models)))
        self.models = tuple(models)

    def path(self, prompt):
        return self.directory / (fingerprint([self.identity, prompt])+'.json')

    def _parsed(self, raw, model, count, parse):
        if not isinstance(raw, str) or model not in self.models:
            return None
        rows = parse(raw, count)
        if not isinstance(rows, list) or len(rows) != count:
            return None
        if any(not isinstance(row, dict) or not isinstance(row.get('vocab'), dict) for row in rows):
            return None
        candidate = SubtitleTranslationCandidate('Gemini', [row.get('translation') for row in rows])
        return rows if candidate.contract_error_for(count) is None else None

    def load(self, prompt, count, parse):
        if self.directory is None:
            return None
        try:
            path = self.path(prompt)
            if path.is_symlink():
                return None
            payload = json.loads(path.read_text(encoding='utf-8'))
            if (payload['identity'] != self.identity or payload['prompt'] != fingerprint(prompt)
                    or payload['response_sha256'] != fingerprint([payload['raw'], payload['model']])):
                return None
            rows = self._parsed(payload['raw'], payload['model'], count, parse)
            if rows is not None:
                return rows, payload['model']
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError, KeyError):
            LOG.warning('[GeminiBatchCache] 快照无效；按原请求和质量规则重新处理。')
        return None

    def save(self, prompt, raw, model, count, parse):
        if self.directory is None or self._parsed(raw, model, count, parse) is None:
            return
        temporary = None
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            payload = dict(identity=self.identity, prompt=fingerprint(prompt), raw=raw, model=model,
                           response_sha256=fingerprint([raw, model]))
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.directory,
                                             prefix='.batch-', suffix='.tmp', delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(payload, handle, ensure_ascii=False, allow_nan=False)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(self.path(prompt))
        except OSError:
            # 缓存不可写不丢弃已经取得的供应商结果，也不绕过全片质量门。
            LOG.warning('[GeminiBatchCache] 快照未写入；当前结果仍须通过原全片质量门。')
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
