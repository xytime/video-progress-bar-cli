"""字幕子进程的具名交接；只传宿主分类和绑定哈希，不传提示词或原始错误日志。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.2.0 | 2026-10-27 | Codex | 烧录前持久 intent 绑定 ASS 与正常快照，完成后绑定成片，缓存恢复拒绝遗失或替换证据。 |
| 1.1.0 | 2026-10-27 | Codex | 成功告警绑定最终正文、全片容错报告与不可变 bad case，父进程重新计算后才交接。 |
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
ASS_CHECKPOINT_PREFIX = '; Subtitle-Translation-Checkpoint: '
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
    completion = dict(completion)
    if completion.get('quality_warning'):
        completion['quality_warning'] = compact_quality_warning(completion['quality_warning'])
    _atomic_json(path, dict(version=VERSION, kind='SUBTITLE_TRANSLATION_COMPLETED',
                           attempt_id=attempt_id, input_path=str(Path(input_path).resolve()),
                           created_at=time.time(), **completion))


def compact_quality_warning(warning):
    """完整报告只存正常快照；具名回执保留固定大小的绑定身份。"""
    return {key: warning[key] for key in ('status', 'candidate_sha256', 'summary_sha256', 'bad_case')}


def caption_checkpoint_ass_comment(completion):
    """烧录前写入 ASS 的单行宿主来源凭证；完整报告仍只在正常快照内。"""
    keys = ('input_sha256', 'asr_sha256', 'contract_sha256', 'checkpoint_path', 'checkpoint_sha256')
    marker = dict(version=VERSION, **{key: completion[key] for key in keys})
    marker['quality_warning'] = (compact_quality_warning(completion['quality_warning'])
                                 if completion.get('quality_warning') is not None else None)
    _validate_ass_checkpoint_marker(marker)
    return ASS_CHECKPOINT_PREFIX + json.dumps(marker, ensure_ascii=False, sort_keys=True,
                                             separators=(',', ':'), allow_nan=False)


def _validate_ass_checkpoint_marker(marker):
    required = {'version', 'input_sha256', 'asr_sha256', 'contract_sha256', 'checkpoint_path',
                'checkpoint_sha256', 'quality_warning'}
    if (not isinstance(marker, dict) or set(marker) != required
            or type(marker.get('version')) is not int or marker['version'] != VERSION
            or any(not isinstance(marker.get(key), str) or not re.fullmatch(r'[0-9a-f]{64}', marker[key])
                   for key in ('input_sha256', 'asr_sha256', 'contract_sha256', 'checkpoint_sha256'))
            or not isinstance(marker.get('checkpoint_path'), str)
            or not Path(marker['checkpoint_path']).is_absolute()):
        raise ValueError('invalid subtitle ASS checkpoint marker')
    warning = marker['quality_warning']
    if warning is not None and (not isinstance(warning, dict)
            or set(warning) != {'status', 'candidate_sha256', 'summary_sha256', 'bad_case'}
            or warning.get('status') != 'accepted_with_warnings'):
        raise ValueError('invalid subtitle ASS warning marker')


def _ass_checkpoint_marker(ass_path):
    raw = _checkpoint_bytes(Path(ass_path))
    markers = [line for line in raw.decode('utf-8-sig').splitlines()
               if line.startswith(ASS_CHECKPOINT_PREFIX.rstrip())]
    if len(markers) > 1:
        raise ValueError('duplicate subtitle ASS checkpoint markers')
    marker = None
    if markers:
        marker = json.loads(markers[0][len(ASS_CHECKPOINT_PREFIX.rstrip()):].strip())
        _validate_ass_checkpoint_marker(marker)
    return marker, hashlib.sha256(raw).hexdigest()


def _subtitle_render_path(output_path):
    output = Path(output_path).absolute()
    return output.with_name(output.name + '.subtitle-quality.json')


def _render_digest(path):
    """成片可远大于快照；流式读取，但仍逐组件拒绝符号链接。"""
    import os
    import stat
    path = Path(path).absolute()
    for component in (*reversed(path.parents), path):
        if stat.S_ISLNK(component.lstat().st_mode):
            raise ValueError('subtitle render symlink')
    value = hashlib.sha256()
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('invalid subtitle render file')
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def begin_subtitle_render(output_path, input_path, ass_path, completion):
    """烧录前先落盘，崩溃或证据遗失不得退回无告警旧缓存。"""
    source, ass, output = Path(input_path).resolve(), Path(ass_path).absolute(), Path(output_path).absolute()
    marker, ass_sha256 = _ass_checkpoint_marker(ass)
    expected = json.loads(caption_checkpoint_ass_comment(completion)[len(ASS_CHECKPOINT_PREFIX):])
    if marker != expected or marker['input_sha256'] != _render_digest(source):
        raise ValueError('subtitle render ASS completion mismatch')
    if len({source, ass, output}) != 3:
        raise ValueError('subtitle render artifacts must be distinct')
    payload, asr = _read_success_checkpoint(source, marker)
    verified_checkpoint_warning(payload, asr, marker)
    intent = dict(version=VERSION, kind='SUBTITLE_RENDER_INTENT', state='RENDERING',
                  input_path=str(source), ass_path=str(ass), output_path=str(output),
                  input_sha256=marker['input_sha256'], ass_sha256=ass_sha256,
                  checkpoint=marker, output_sha256=None)
    sidecar = _subtitle_render_path(output)
    # 父目录可以创建；现有组件不得借链接把 intent 写到别处。
    for component in (*reversed(sidecar.parents), sidecar):
        if component.is_symlink():
            raise ValueError('subtitle render intent symlink')
    _atomic_json(sidecar, intent)
    return intent


def _read_subtitle_render_intent(output_path, input_path, ass_path, *, allow_rendering=False):
    source, ass, output = Path(input_path).resolve(), Path(ass_path).absolute(), Path(output_path).absolute()
    raw = _checkpoint_bytes(_subtitle_render_path(output))
    if len(raw) > 65536:
        raise ValueError('subtitle render intent too large')
    intent = json.loads(raw)
    required = {'version', 'kind', 'state', 'input_path', 'ass_path', 'output_path',
                'input_sha256', 'ass_sha256', 'checkpoint', 'output_sha256'}
    if (not isinstance(intent, dict) or set(intent) != required
            or type(intent.get('version')) is not int or intent['version'] != VERSION
            or intent['kind'] != 'SUBTITLE_RENDER_INTENT'
            or intent['state'] not in {'RENDERING', 'COMPLETE'}
            or intent['input_path'] != str(source) or intent['ass_path'] != str(ass)
            or intent['output_path'] != str(output)
            or any(not isinstance(intent[key], str) or not re.fullmatch(r'[0-9a-f]{64}', intent[key])
                   for key in ('input_sha256', 'ass_sha256'))):
        raise ValueError('invalid subtitle render intent')
    _validate_ass_checkpoint_marker(intent['checkpoint'])
    marker, ass_sha256 = _ass_checkpoint_marker(ass)
    if (marker is None or marker != intent['checkpoint']
            or marker['input_sha256'] != intent['input_sha256']
            or _render_digest(source) != intent['input_sha256'] or ass_sha256 != intent['ass_sha256']):
        raise ValueError('subtitle render input or ASS binding mismatch')
    if intent['state'] == 'RENDERING':
        if intent['output_sha256'] is not None or not allow_rendering:
            raise ValueError('subtitle render incomplete')
    elif (not isinstance(intent['output_sha256'], str)
            or not re.fullmatch(r'[0-9a-f]{64}', intent['output_sha256'])
            or _render_digest(output) != intent['output_sha256']):
        raise ValueError('subtitle render output binding mismatch')
    return intent


def finish_subtitle_render(output_path, input_path, ass_path):
    """烧录成功后封存输出摘要；重复完成只接受完全相同的一组成片证据。"""
    intent = _read_subtitle_render_intent(output_path, input_path, ass_path, allow_rendering=True)
    payload, asr = _read_success_checkpoint(Path(input_path).resolve(), intent['checkpoint'])
    verified_checkpoint_warning(payload, asr, intent['checkpoint'])
    intent.update(state='COMPLETE', output_sha256=_render_digest(output_path))
    _atomic_json(_subtitle_render_path(output_path), intent)
    return intent


def require_quality_warning_envelope(result):
    """选中告警的审计不可在续跑时变成无告警成功；三个读取入口共用。"""
    if not isinstance(result, dict):
        raise ValueError('invalid subtitle checkpoint result')
    audit = result.get('quality_audit') or []
    if not isinstance(audit, list):
        raise ValueError('invalid subtitle quality audit')
    audited_warning = any(
        isinstance(event, dict) and event.get('status') == 'accepted_with_warnings'
        and (event.get('selected') is True or event.get('event') == 'bad_case_saved')
        for event in audit
    )
    warning = result.get('quality_warning')
    if warning is None:
        if audited_warning:
            raise ValueError('subtitle cached warning envelope missing')
        return None
    if not isinstance(warning, dict) or warning.get('status') != 'accepted_with_warnings':
        raise ValueError('invalid subtitle warning envelope')
    return warning


def verified_checkpoint_warning(payload, asr, binding):
    """重新核实报告和案例，拒绝仅自改摘要后冒充稀疏错误的完成快照。"""
    warning = require_quality_warning_envelope(payload['result'])
    bound_warning = binding.get('quality_warning')
    if warning is None:
        if bound_warning is not None:
            raise ValueError('subtitle warning missing from checkpoint')
        return None
    if (not isinstance(warning, dict) or warning.get('status') != 'accepted_with_warnings'
            or compact_quality_warning(warning) != bound_warning):
        raise ValueError('subtitle warning receipt mismatch')
    return validate_quality_warning(
        warning, segments=payload['result']['segments'], input_sha256=binding['input_sha256'],
        asr_sha256=binding['asr_sha256'], contract_sha256=binding['contract_sha256'],
    )


def validate_quality_warning(warning, *, segments, input_sha256, asr_sha256, contract_sha256):
    """正常快照复用与父进程交接共用验证；失败抛 ValueError/IO/结构异常。"""
    from .subtitle_bad_cases import load_bad_case
    from .subtitle_sparse_policy import (
        build_sparse_quality_report, candidate_fingerprint, report_fingerprint,
    )
    if not isinstance(warning, dict) or warning.get('status') != 'accepted_with_warnings':
        raise ValueError('invalid subtitle warning envelope')
    binding = dict(input_sha256=input_sha256, asr_sha256=asr_sha256, contract_sha256=contract_sha256)
    report, bad_case = warning['report'], warning['bad_case']
    if (not isinstance(report, dict) or report.get('status') != 'accepted_with_warnings'
            or report_fingerprint(report) != warning['summary_sha256']
            or report.get('candidate_sha256') != warning['candidate_sha256']):
        raise ValueError('subtitle warning report mismatch')
    for value in (warning['summary_sha256'], warning['candidate_sha256'], bad_case['case_id'], bad_case['sha256']):
        if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value):
            raise ValueError('invalid subtitle warning digest')
    path = Path(bad_case['path'])
    if (not path.is_absolute() or path.name != bad_case['case_id'] + '.json'
            or path.parent.name != bad_case['case_id'][:2] or path.parent.parent.name != 'cases'):
        raise ValueError('invalid subtitle bad case path')
    stored = load_bad_case(path, bad_case['sha256'])
    case = stored['payload']
    if (stored['case_id'] != bad_case['case_id']
            or any(case[key] != binding[key] for key in ('input_sha256', 'asr_sha256', 'contract_sha256'))
            or any(case[key] != warning[key] for key in ('candidate_sha256', 'summary_sha256'))
            or case['report'] != report):
        raise ValueError('subtitle bad case binding mismatch')
    translations = [segment['zh_text'] for segment in segments]
    vocabs = [segment.get('vocab') or {} for segment in segments]
    source_segments = case['source_segments']
    if (fingerprint(source_segments) != asr_sha256 or len(source_segments) != len(segments)
            or any(any(original[key] != translated[key] for key in ('text', 'start', 'end'))
                   for original, translated in zip(source_segments, segments))
            or case['repair_history'] != report.get('repair_history')):
        raise ValueError('subtitle bad case source or repair binding mismatch')
    if candidate_fingerprint(segments, translations) != warning['candidate_sha256']:
        raise ValueError('subtitle warning candidate mismatch')
    if case['translations'] != translations:
        raise ValueError('subtitle bad case candidate mismatch')
    recomputed = build_sparse_quality_report(
        segments, translations, context_text=case.get('context_text', ''), vocabs=vocabs,
        repair_history=report.get('repair_history') or [],
    )
    if recomputed['status'] != 'accepted_with_warnings' or report_fingerprint(recomputed) != warning['summary_sha256']:
        raise ValueError('subtitle warning policy no longer accepts candidate')
    return warning


def _checkpoint_bytes(path):
    """读取恢复证据时逐级拒绝链接，不跟随替换到外部文件的路径。"""
    import os
    import stat
    path = Path(path).absolute()
    for component in (*reversed(path.parents), path):
        if stat.S_ISLNK(component.lstat().st_mode):
            raise ValueError('subtitle checkpoint symlink')
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > 32 * 1024 * 1024:
            raise ValueError('invalid subtitle checkpoint file')
        raw = stream.read(32 * 1024 * 1024 + 1)
    if len(raw) > 32 * 1024 * 1024:
        raise ValueError('subtitle checkpoint too large')
    return raw


def _checkpoint_json(path):
    return json.loads(_checkpoint_bytes(path))


def _read_success_checkpoint(source, binding):
    """具名成功回执与 ASS 凭证共用同一正常快照、媒体及原始时间轴绑定。"""
    from .caption_checkpoints import valid_segments
    checkpoint = Path(binding['checkpoint_path'])
    expected_parent = source.parent / '.caption-checkpoints'
    if (checkpoint.name != 'translation.json' or checkpoint.parent.parent != expected_parent
            or not re.fullmatch(r'[0-9a-f]{64}', checkpoint.parent.name)):
        raise ValueError('subtitle success checkpoint path mismatch')
    raw = _checkpoint_bytes(checkpoint)
    if hashlib.sha256(raw).hexdigest() != binding['checkpoint_sha256']:
        raise ValueError('subtitle success checkpoint digest mismatch')
    payload = json.loads(raw)
    asr = _checkpoint_json(checkpoint.with_name('asr.json'))
    if (payload['identity']['source_sha256'] != binding['input_sha256']
            or payload['identity']['source_name'] != source.name
            or checkpoint.parent.name != fingerprint(payload['identity'])
            or payload['result']['completed'] is not True
            or payload['result_sha256'] != fingerprint(payload['result'])
            or fingerprint(payload['contract']) != binding['contract_sha256']
            or asr['identity'] != payload['identity'] or asr['contract'] != asr['identity']['asr']
            or asr['result']['completed'] is not True
            or asr['result_sha256'] != fingerprint(asr['result'])
            or fingerprint(asr['result']['segments']) != binding['asr_sha256']
            or payload['contract']['asr_sha256'] != binding['asr_sha256']
            or not valid_segments(asr['result']['segments'])
            or not valid_segments(payload['result']['segments'], True, asr['result']['segments'])):
        raise ValueError('subtitle success checkpoint binding mismatch')
    return payload, asr


def _current_checkpoint_contract(payload, current_modules, current_config):
    from .caption_checkpoints import VERSION as checkpoint_version
    translation = payload['contract']['translation']
    if (payload['identity']['version'] != checkpoint_version
            or translation['version'] != checkpoint_version
            or translation['modules'] != current_modules or translation['config'] != current_config
            or not isinstance(translation.get('methods'), str)
            or not re.fullmatch(r'[0-9a-f]{64}', translation['methods'])):
        raise ValueError('subtitle cached warning checkpoint invalid or outdated')


def read_cached_quality_warning(input_path, *, ass_path=None, render_path=None):
    """查回同源成片复用时遗漏的告警；异常/冲突必须让调用方放弃成片缓存。

    不导入重型 processor：核实当前翻译依赖模块与配置、正常 ASR/译文快照、
    容错报告和不可变 bad case。这里只能验证 methods 摘要格式，无法轻量重算
    processor MRO 的方法摘要；正常 processor 复用仍验证完整 translation_contract。
    新成片 ASS 有烧录前写入的来源注释时，只验证其中指定的唯一正常快照；
    快照目录遗失不能当作无告警。无该注释才兼容扫描历史目录；多个候选拒绝猜测。
    新成片 intent 在烧录前存在；有 intent 时还必须核实 COMPLETE 状态及输入、
    ASS、成片全部摘要。缺失快照、替换 ASS 或未完成烧录均使缓存失效。
    """
    from config.settings import settings
    from . import caption_checkpoints as checkpoint_contract
    source = Path(input_path).resolve()
    input_sha256 = digest(source)
    marker = None
    if ass_path is not None:
        marker, _ = _ass_checkpoint_marker(ass_path)
        if marker is not None:
            if marker['input_sha256'] != input_sha256:
                raise ValueError('subtitle ASS checkpoint media mismatch')
    if render_path is not None:
        sidecar = _subtitle_render_path(render_path)
        if sidecar.exists() or sidecar.is_symlink():
            if ass_path is None:
                raise ValueError('subtitle render intent requires ASS evidence')
            intent = _read_subtitle_render_intent(render_path, source, ass_path)
            if marker != intent['checkpoint']:
                raise ValueError('subtitle render checkpoint marker mismatch')
    directory = source.parent / '.caption-checkpoints'
    if marker is None and not directory.exists() and not directory.is_symlink():
        return []
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError('invalid subtitle checkpoint directory')
    current_modules = {name: digest(Path(__file__).with_name(name + '.py'))
                       for name in checkpoint_contract.TRANSLATION_MODULES}
    current_config = {name: getattr(settings, name, None)
                      for name in checkpoint_contract.TRANSLATION_SETTINGS}
    # JSON 会将 tuple 等配置转为数组，必须按实际落盘合同进行比较。
    current_config = json.loads(json.dumps(current_config, allow_nan=False))
    if marker is not None:
        payload, asr = _read_success_checkpoint(source, marker)
        _current_checkpoint_contract(payload, current_modules, current_config)
        warning = verified_checkpoint_warning(payload, asr, marker)
        return [warning] if warning is not None else []
    found = {}
    for checkpoint in sorted(directory.glob('*/translation.json')):
        payload = _checkpoint_json(checkpoint)
        if not isinstance(payload, dict):
            raise ValueError('invalid subtitle cached checkpoint payload')
        identity = payload.get('identity', {})
        if not isinstance(identity, dict):
            raise ValueError('invalid subtitle cached checkpoint identity')
        if (identity.get('source_sha256') != input_sha256
                or identity.get('source_name') != source.name):
            continue
        result = payload.get('result') or {}
        if not isinstance(result, dict):
            raise ValueError('invalid subtitle cached checkpoint result')
        warning = require_quality_warning_envelope(result)
        if warning is None:
            continue
        asr = _checkpoint_json(checkpoint.with_name('asr.json'))
        binding = dict(input_sha256=input_sha256, checkpoint_path=str(checkpoint),
                       checkpoint_sha256=digest(checkpoint), asr_sha256=fingerprint(asr['result']['segments']),
                       contract_sha256=fingerprint(payload['contract']), quality_warning=compact_quality_warning(warning))
        payload, asr = _read_success_checkpoint(source, binding)
        _current_checkpoint_contract(payload, current_modules, current_config)
        verified = verified_checkpoint_warning(payload, asr, binding)
        found[(verified['candidate_sha256'], verified['summary_sha256'])] = verified
    if len(found) > 1:
        raise ValueError('subtitle cached warning selected candidate ambiguous')
    return list(found.values())


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
            payload, asr = _read_success_checkpoint(source, data)
            warning = verified_checkpoint_warning(payload, asr, data)
            if warning is not None:
                data['quality_warning'] = warning
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
