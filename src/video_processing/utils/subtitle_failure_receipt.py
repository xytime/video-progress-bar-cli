"""字幕子进程的具名交接；只传宿主分类和绑定哈希，不传提示词或原始错误日志。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-27 | Codex | 字幕恢复安全错误链、本次原子回执及父进程身份核验。 |
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import tempfile
import time

from ..core.base import VideoProcessingError
from .codex_text_provider import _safe_quality_details
from .render_source_binding import digest

VERSION = 1
CATEGORIES = frozenset({'network', 'quota', 'busy', 'timeout', 'authentication',
                        'quality', 'budget', 'unavailable'})


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     allow_nan=False).encode()).hexdigest()


def safe_failure(provider, code, *, retry_at=0, quality_details=(), category=None):
    """不接受任意错误正文；未知分类保守视为服务不可用。"""
    code = str(code)
    if not re.fullmatch(r'[A-Za-z0-9_:.-]{1,180}', code):
        code = 'provider_failure'
    lowered = code.lower()
    if category not in CATEGORIES:
        if any(token in lowered for token in ('budget', 'total_timeout', 'elapsed')):
            category = 'budget'
        elif any(token in lowered for token in ('subtitle_', 'invalid_output', 'quality', 'structure', 'alignment')):
            category = 'quality'
        elif 'busy' in lowered or 'cooldown' in lowered:
            category = 'busy'
        elif any(token in lowered for token in ('quota', '429', 'rate_limit')):
            category = 'quota'
        elif any(token in lowered for token in ('authentication', 'permission', '401', '403', 'billing', 'region')):
            category = 'authentication'
        elif 'timeout' in lowered:
            category = 'timeout'
        elif any(token in lowered for token in ('network', 'connection')):
            category = 'network'
        else:
            category = 'unavailable'
    provider = provider if provider in {'codex', 'agy', 'gemini', 'deepseek', 'google', 'host'} else 'host'
    return dict(provider=provider, code=code, category=category,
                retry_at=max(0, int(retry_at or 0)), quality_details=_safe_quality_details(quality_details))


class SubtitleTranslationFailure(VideoProcessingError):
    def __init__(self, failures, message='All subtitle translation providers failed or were blocked.'):
        self.failures = failures[-10:]
        # 最后实际使用的备选方案决定处置；早期供应商不可用不掩盖 Codex 的具体质量错误。
        self.failure = self.failures[-1] if self.failures else safe_failure('host', 'providers_unavailable')
        self.binding = {}
        self.evidence = {}
        super().__init__(message + f" [{self.failure['code']}]")


def _atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', dir=path.parent, encoding='utf-8', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(payload, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            import os
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_failure_receipt(path, attempt_id, input_path, error):
    if not re.fullmatch(r'[0-9a-f]{32}', attempt_id or '') or not error.binding:
        raise ValueError('subtitle failure binding missing')
    payload = dict(version=VERSION, kind='SUBTITLE_TRANSLATION_FAILED', attempt_id=attempt_id,
                   input_path=str(Path(input_path).resolve()), created_at=time.time(),
                   **error.binding, **error.failure, failures=error.failures,
                   evidence_path=str(error.evidence.get('receipt_path', '')),
                   evidence_sha256=error.evidence.get('receipt_sha256', ''))
    payload['failure_fingerprint'] = fingerprint({key: payload[key] for key in
        ('input_sha256', 'asr_sha256', 'contract_sha256', 'category', 'code', 'quality_details')})
    _atomic_json(path, payload)
    return payload


def write_success_receipt(path, attempt_id, input_path, completion):
    if not re.fullmatch(r'[0-9a-f]{32}', attempt_id or '') or not completion:
        return
    _atomic_json(path, dict(version=VERSION, kind='SUBTITLE_TRANSLATION_COMPLETED',
                           attempt_id=attempt_id, input_path=str(Path(input_path).resolve()),
                           created_at=time.time(), **completion))


def read_bound_receipt(path, *, attempt_id, input_path, input_sha256, started_at, success=False):
    """只接受本次调用的结果，重新核媒体，拒绝陈旧、错片和被更改的完成快照。"""
    try:
        path, source = Path(path), Path(input_path).resolve()
        if path.is_symlink() or path.stat().st_size > 65536:
            return None
        data = json.loads(path.read_text(encoding='utf-8'))
        kind = 'SUBTITLE_TRANSLATION_COMPLETED' if success else 'SUBTITLE_TRANSLATION_FAILED'
        if (data['version'] != VERSION or data['kind'] != kind or data['attempt_id'] != attempt_id
                or data['input_path'] != str(source) or data['input_sha256'] != input_sha256
                or digest(source) != input_sha256
                or not started_at - 1 <= data['created_at'] <= time.time() + 5
                or not all(re.fullmatch(r'[0-9a-f]{64}', data[key]) for key in
                           ('input_sha256', 'asr_sha256', 'contract_sha256'))):
            return None
        if success:
            from .caption_checkpoints import valid_segments
            checkpoint = Path(data['checkpoint_path'])
            expected_parent = source.parent / '.caption-checkpoints'
            if (checkpoint.name != 'translation.json' or checkpoint.parent.parent != expected_parent
                    or checkpoint.is_symlink() or digest(checkpoint) != data['checkpoint_sha256']):
                return None
            payload = json.loads(checkpoint.read_text(encoding='utf-8'))
            asr_path = checkpoint.with_name('asr.json')
            if asr_path.is_symlink():
                return None
            asr = json.loads(asr_path.read_text(encoding='utf-8'))
            if (payload['identity']['source_sha256'] != input_sha256
                    or payload['result']['completed'] is not True
                    or payload['result_sha256'] != fingerprint(payload['result'])
                    or fingerprint(payload['contract']) != data['contract_sha256']
                    or asr['identity'] != payload['identity'] or asr['result']['completed'] is not True
                    or asr['result_sha256'] != fingerprint(asr['result'])
                    or fingerprint(asr['result']['segments']) != data['asr_sha256']
                    or not valid_segments(payload['result']['segments'], True, asr['result']['segments'])):
                return None
        else:
            clean = safe_failure(data['provider'], data['code'], retry_at=data['retry_at'],
                                 quality_details=data['quality_details'], category=data['category'])
            if any(data[key] != value for key, value in clean.items()):
                return None
            expected = fingerprint({key: data[key] for key in
                ('input_sha256', 'asr_sha256', 'contract_sha256', 'category', 'code', 'quality_details')})
            if data['failure_fingerprint'] != expected:
                return None
        return data
    except (OSError, ValueError, KeyError, TypeError):
        return None
