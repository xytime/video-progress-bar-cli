"""字幕上游完成快照：内容绑定、完整校验与原子替换，不记录模型凭据。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-23 | Codex | 独立保存 ASR 与已通过质量门的翻译，供下游失败后续跑。 |
"""
from copy import deepcopy
import hashlib
import inspect
import json
import logging
import math
from pathlib import Path
import tempfile

from .render_source_binding import digest
from .subtitle_translation_provider import SubtitleTranslationCandidate

LOG = logging.getLogger(__name__)
VERSION = 1
TRANSLATION_MODULES = (
    'subtitle_translation_provider', 'subtitle_translation_quality', 'subtitle_content_contract',
    'translation_quality_guard', 'translation_context', 'translation_candidate_arbitration',
    'translation_quality_evaluator', 'translation_consistency_guard', 'translation_fluency_guard',
    'translation_entity_guard',
    'translation_prompt_constraints', 'vocab_helper', 'translation_helper', 'deepseek_translation',
    'translation_model_pool', 'agy_provider', 'codex_subtitle_provider', 'codex_text_provider',
)
TRANSLATION_SETTINGS = (
    'subtitle_translation_provider_order', 'enable_deepseek_vocab_fallback',
    'enable_translation_quality_fail_open', 'enable_translation_numeric_guard',
    'agy_subtitle_model', 'deepseek_model', 'codex_text_model', 'codex_text_effort',
    'codex_subtitle_batch_size',
)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     allow_nan=False).encode()).hexdigest()


def implementation(methods):
    return fingerprint([inspect.getsource(method) for method in methods])


def translation_contract(processor, settings):
    # 只绑定翻译/质量方法；标题、版式和渲染代码变化不应使已完成的识别失效。
    methods = [getattr(type(processor), name) for name in dir(type(processor))
               if name.startswith(('_translate_', '_build_', '_apply_selected_translation',
                                   '_evaluate_translation', '_guard_translation', '_align_vocab'))
               and name != '_build_ass_file']
    return dict(version=VERSION, methods=implementation(methods),
                modules={name: digest(Path(__file__).with_name(name+'.py')) for name in TRANSLATION_MODULES},
                config={name: getattr(settings, name, None) for name in TRANSLATION_SETTINGS})


def valid_segments(segments, translated=False, source=None):
    if not isinstance(segments, list):
        return False
    previous = -1.0
    for segment in segments:
        if not isinstance(segment, dict) or not isinstance(segment.get('text'), str):
            return False
        start, end = segment.get('start'), segment.get('end')
        if (type(start) not in (float, int) or type(end) not in (float, int)
                or not math.isfinite(start) or not math.isfinite(end)
                or start < 0 or end < start or start < previous):
            return False
        previous = start
    if translated and segments:
        candidate = SubtitleTranslationCandidate('checkpoint', [s.get('zh_text') for s in segments])
        if candidate.contract_error_for(len(segments)):
            return False
    if source is not None:
        if len(source) != len(segments):
            return False
        if any(any(a[key] != b.get(key) for key in ('start', 'end', 'text'))
               for a, b in zip(source, segments)):
            return False
    return True


class CaptionCheckpoints:
    def __init__(self, source, asr_contract):
        self.source = Path(source)
        self.source_digest = digest(self.source)
        self.identity = dict(version=VERSION, source_sha256=self.source_digest,
                             source_name=self.source.name, asr=asr_contract)
        self.directory = self.source.parent / '.caption-checkpoints' / fingerprint(self.identity)

    def load(self, stage, contract, source=None):
        path = self.directory / (stage + '.json')
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
            result = payload['result']
            if (payload['identity'] != self.identity or payload['contract'] != contract
                    or payload['result_sha256'] != fingerprint(result)
                    or result.get('completed') is not True
                    or not isinstance(result.get('detected_lang'), (str, type(None)))
                    or not valid_segments(result['segments'], stage == 'translation', source)):
                raise ValueError('identity, integrity or segment contract mismatch')
            LOG.info('[CaptionCheckpoint] 复用已完成的 %s: %s', stage, path)
            return result
        except FileNotFoundError:
            LOG.info('[CaptionCheckpoint] %s 无有效快照，执行本阶段', stage)
        except (OSError, ValueError, KeyError, TypeError):
            LOG.warning('[CaptionCheckpoint] %s 快照不完整或依赖变化，重新执行', stage)
        return None

    def save(self, stage, contract, segments, detected_lang, source=None, quality_audit=None):
        if not valid_segments(segments, stage == 'translation', source):
            raise ValueError('字幕完成快照结构不完整')
        if digest(self.source) != self.source_digest:
            raise ValueError('字幕处理期间源媒体变化，拒绝保存快照')
        result = dict(completed=True, segments=deepcopy(segments), detected_lang=detected_lang,
                      quality_audit=quality_audit or [])
        payload = dict(identity=self.identity, contract=contract, result=result,
                       result_sha256=fingerprint(result))
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            # 每个写入者独立临时文件；读者只能看到上一个或下一个完整快照。
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.directory,
                                             prefix='.'+stage+'-', suffix='.tmp', delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(payload, handle, ensure_ascii=False, allow_nan=False)
                handle.flush()
                import os
                os.fsync(handle.fileno())
            temporary.replace(self.directory / (stage+'.json'))
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
