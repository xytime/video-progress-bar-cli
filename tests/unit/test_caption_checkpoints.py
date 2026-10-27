"""下游失败与依赖失效的恢复验收，不加载模型或访问供应商。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-23 | Codex | 验证阶段恢复、独立失效、损坏快照和并发原子写入。 |
"""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

import pytest
import pysubs2

from config.settings import settings
from video_processing.processors.caption_processor import AutoCaptionProcessor
from video_processing.utils.caption_checkpoints import CaptionCheckpoints, fingerprint


class SyntheticCaption(AutoCaptionProcessor):
    def _validate_input(self):
        pass

    def _load_model(self):
        self.calls.append('model')

    def _extract_audio(self):
        self.calls.append('audio')
        audio = self.input_path.with_suffix('.wav')
        audio.write_bytes(b'audio')
        return audio

    def _transcribe_audio(self, path):
        self.calls.append('asr')
        self.detected_lang = 'en'
        return [dict(start=0, end=2, text='Bonds still matter.')]

    def _translate_segments(self, segments):
        self.calls.append('translation')
        if self.translation_failure:
            raise ValueError('translation blocked')
        segments[0]['zh_text'] = '债券仍然重要。'
        self._translation_quality_audit = [dict(selected=True, status='accepted')]
        return segments

    def _generate_ass_file(self, segments):
        self.calls.append('layout')
        assert self.detected_lang == 'en'
        assert segments[0]['zh_text'] == '债券仍然重要。'
        if self.layout_failure:
            raise ValueError('原字幕定位失败')
        path = self.input_path.with_suffix('.ass')
        subtitles = pysubs2.SSAFile()
        subtitles.events = [pysubs2.SSAEvent(start=0, end=2000,
            text=r'{\fnGeorgia}Bonds still matter.\N{\fnHiragino Sans GB}债券仍然重要。')]
        subtitles.save(str(path))
        return path

    def _burn_subtitles(self, path):
        self.calls.append('render')
        assert Path(path).is_file()
        self.output_path.write_bytes(b'synthetic captioned video')
        return self.output_path


def processor(source, *, fail=False, **kwargs):
    p = SyntheticCaption(source, output_path=source.with_name('output.mp4'), **kwargs)
    p.calls, p.layout_failure, p.translation_failure = [], fail, False
    return p


@pytest.fixture
def source(tmp_path):
    path = tmp_path / 'task_s1.mp4'
    path.write_bytes(b'source media')
    return path


def test_downstream_failure_retry_uses_both_snapshots_before_model_or_audio(source):
    first = processor(source, fail=True)
    with pytest.raises(ValueError, match='原字幕'):
        first.process()
    assert first.calls == ['audio', 'model', 'asr', 'translation', 'layout']
    second = processor(source)
    stages = []
    second._progress_reporter = stages.append
    second.process()
    assert second.calls == ['layout', 'render']
    assert stages[:2] == ['ASR_REUSED', 'TRANSLATION_REUSED']
    assert second._translation_quality_audit[0]['selected']


@pytest.mark.parametrize('change,expected', [
    ('source', ['audio', 'model', 'asr', 'translation', 'layout', 'render']),
    ('model', ['audio', 'model', 'asr', 'translation', 'layout', 'render']),
    ('language', ['audio', 'model', 'asr', 'translation', 'layout', 'render']),
    ('target', ['translation', 'layout', 'render']),
    ('quality', ['translation', 'layout', 'render']),
    ('provider_model', ['translation', 'layout', 'render']),
    ('style', ['layout', 'render']),
])
def test_only_changed_dependencies_are_recomputed(source, monkeypatch, change, expected):
    processor(source).process()
    kwargs = {}
    if change == 'source': source.write_bytes(b'changed media')
    if change == 'model': kwargs['model_size'] = 'base'
    if change == 'language': kwargs['src_lang'] = 'auto'
    if change == 'target': kwargs['target_lang'] = 'zh-TW'
    if change == 'quality': monkeypatch.setattr(settings, 'enable_translation_numeric_guard', not settings.enable_translation_numeric_guard)
    if change == 'provider_model': monkeypatch.setattr(settings, 'codex_text_model', 'another-model')
    if change == 'style': kwargs['style'] = 'movie_yellow'
    again = processor(source, **kwargs)
    again.process()
    assert again.calls == expected


def test_failed_translation_retries_translation_without_retranscribing(source):
    first = processor(source)
    first.translation_failure = True
    with pytest.raises(ValueError, match='translation blocked'): first.process()
    again = processor(source)
    again.process()
    assert again.calls == ['translation', 'layout', 'render']


@pytest.mark.parametrize('stage,damage', [('asr', 'truncated'), ('translation', 'digest'), ('translation', 'half')])
def test_corrupt_or_incomplete_checkpoint_is_never_reused(source, stage, damage):
    processor(source).process()
    path = next(source.parent.glob(f'.caption-checkpoints/*/{stage}.json'))
    payload = json.loads(path.read_text())
    if damage == 'truncated': path.write_text('{')
    else:
        if damage == 'digest': payload['result']['segments'][0]['zh_text'] = 'changed'
        else:
            payload['result']['segments'][0]['zh_text'] = ''
            payload['result_sha256'] = fingerprint(payload['result'])
        path.write_text(json.dumps(payload))
    again = processor(source)
    again.process()
    assert ('asr' in again.calls) == (stage == 'asr')
    # 完全相同的 ASR 结果仍可复用完整的译文，损坏译文只重做翻译。
    assert ('translation' in again.calls) == (stage == 'translation')


def test_atomic_concurrent_writes_and_source_change(source):
    store = CaptionCheckpoints(source, dict(model='test'))
    contract = dict(target='zh-CN')
    def save(index):
        segments = [dict(start=0,end=1,text='source',zh_text=f'译文{index}')]
        store.save('translation',contract,segments,'en')
        loaded = store.load('translation',contract)
        assert loaded and loaded['segments'][0]['zh_text'].startswith('译文')
    with ThreadPoolExecutor(max_workers=4) as pool: list(pool.map(save, range(24)))
    assert not list(store.directory.glob('*.tmp'))
    source.write_bytes(b'changed during work')
    with pytest.raises(ValueError, match='源媒体变化'):
        store.save('asr', {}, [], 'en')
