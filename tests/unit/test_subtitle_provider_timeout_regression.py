"""大批字幕的片段归属、AGY 快速降级、冷却及配置回归。"""

import json
import subprocess
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from config.settings import Settings
from video_processing.processors import caption_processor as caption
from video_processing.utils import agy_provider, codex_subtitle_provider as codex
from video_processing.utils.codex_text_provider import CodexTextResult
from video_processing.utils.translation_model_pool import DynamicTranslationModelPool


def processor(tmp_path):
    source = tmp_path / 'source.mp4'
    source.touch()
    return caption.AutoCaptionProcessor(source, tmp_path / 'unused.mp4', src_lang='en', target_lang='zh-CN')


@pytest.mark.parametrize('value,expected', [(0,30),(29,30),(30,30),(40,40),(50,50),(51,50),(1000,50)])
def test_codex_configuration_clamps_and_warns(value, expected, caplog):
    config = Settings(_env_file=None, codex_subtitle_batch_size=value)
    assert config.codex_subtitle_batch_size == expected
    assert ('clamped' in caplog.text) == (value != expected)


def test_approved_effective_order_and_defaults():
    config = Settings(_env_file=None, enable_codex_text_fallback=True)
    assert config.subtitle_translation_provider_order_list == ['agy','deepseek','gemini','google','codex']
    assert config.codex_subtitle_batch_size == 40
    assert config.agy_timeout_sec == 150
    assert config.agy_subtitle_batch_size == 80
    assert min(config.codex_subtitle_total_timeout_seconds, config.subtitle_translation_total_timeout_seconds) == 600


@pytest.mark.parametrize('field,value', [('agy_timeout_sec',119),('agy_timeout_sec',181),
                                        ('agy_subtitle_batch_size',59),('agy_subtitle_batch_size',101)])
def test_agy_configuration_rejects_outside_bounds(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field:value})


@pytest.mark.parametrize('failure,category', [('AGY_AUTH_REQUIRED','auth_or_permission'),
    ('location_unsupported','region_restricted'), ('location ineligible','region_restricted'),
    ('timeout','timeout'), ('missing','command_not_found')])
@pytest.mark.parametrize('successful_prefix', [False, True])
def test_agy_failure_abandons_remaining_batches_falls_back_and_cools(
    tmp_path, monkeypatch, failure, category, successful_prefix,
):
    config = Settings(_env_file=None, project_root=tmp_path, default_output_dir=tmp_path / 'output',
                      subtitle_translation_provider_order='agy,deepseek,gemini,google',
                      enable_codex_text_fallback=True, agy_subtitle_batch_size=60)
    config = SimpleNamespace(**{**vars(config), 'project_root':tmp_path,
        'default_output_dir':tmp_path / 'output',
        'subtitle_translation_provider_order_list':config.subtitle_translation_provider_order_list})
    monkeypatch.setattr(caption, 'settings', config)
    calls = []
    def run(args, **kwargs):
        calls.append('agy')
        if successful_prefix and calls.count('agy') == 1:
            rows = [{'id':i,'translation':'企业可以改变','vocab':{}} for i in range(60)]
            return SimpleNamespace(returncode=0, stdout=json.dumps({'structured_output':{'items':rows}}), stderr='')
        if failure == 'timeout':
            raise subprocess.TimeoutExpired(args, kwargs['timeout'])
        if failure == 'missing':
            raise FileNotFoundError('agy')
        return SimpleNamespace(returncode=1, stdout=failure, stderr='provider failure')
    def deepseek(texts, **kwargs):
        calls.append('deepseek')
        return [{'translation':'企业可以改变','vocab':{}} for text in texts]
    monkeypatch.setattr(agy_provider.subprocess, 'run', run)
    monkeypatch.setattr(caption, 'translate_batch_with_vocab_deepseek', deepseek)
    instance = processor(tmp_path)
    # 三个AGY批次；首批或第二批失败后，都不能调用剩余批次。
    result = instance._translate_segments([{'text':'A business can change.'} for _ in range(125)])
    expected = ['agy'] * (2 if successful_prefix else 1) + ['deepseek']
    assert calls == expected
    assert [row['zh_text'] for row in result] == ['企业可以改变'] * 125
    runs = caption.PipelineDB().get_ai_audit_for_video('source', limit=100)
    audit = next(run for run in runs if run['id'] == instance._translation_audit_run_id)['attempts']
    assert [(row['provider'],row['status']) for row in audit] == [('agy','FAILED'),('deepseek','SUCCEEDED')]
    assert audit[0]['error_class'] == category
    state = DynamicTranslationModelPool(tmp_path / 'output' / 'translation_model_pool.json')
    assert state.snapshot()['agy']['last_error_class'] == category
    assert 'agy' not in state.order(['agy','deepseek'])
    # 同一执行者再次翻译亦须服从持久冷却，不能每轮重新尝试。
    instance._translate_segments([{'text':'A business can change.'}])
    assert calls == expected + ['deepseek']


@pytest.mark.parametrize('size', [60,80,100])
def test_agy_batches_preserve_all_rows_and_prompt_contract(tmp_path, monkeypatch, size):
    config = Settings(_env_file=None, agy_subtitle_batch_size=size)
    monkeypatch.setattr(caption, 'settings', config)
    seen = []
    def run(prompt, **kwargs):
        rows = json.loads(prompt.split('Input JSON: ',1)[1])
        seen.append(len(rows))
        assert '原文是半句就译成半句' in prompt
        assert '≤ 18' in prompt and '≤ 24' in prompt
        assert kwargs['timeout_sec'] <= 150
        assert 'vocab' in kwargs['schema']['properties']['items']['items']['properties']
        return {'items':[{'id':row['id'],'translation':'企业可以改变','vocab':{'business':'企业'}} for row in rows]}
    monkeypatch.setattr(caption, 'run_agy_structured', run)
    result = processor(tmp_path)._build_agy_candidate(['A business can change.'] * 201, '')
    assert seen == [min(size,201-offset) for offset in range(0,201,size)]
    assert len(result.translations) == 201 and result.vocabs == [{'business':'企业'}] * 201


@pytest.mark.parametrize('fault', ['short','extra','empty','placeholder','duplicate','reordered'])
def test_agy_invalid_batch_is_rejected_immediately(tmp_path, monkeypatch, fault):
    monkeypatch.setattr(caption, 'settings', Settings(_env_file=None))
    calls = []
    def run(*args, **kwargs):
        calls.append(1)
        rows = [{'id':i,'translation':'企业可以改变','vocab':{}} for i in range(80)]
        if fault == 'short': rows.pop()
        if fault == 'extra': rows.append(dict(rows[-1]))
        if fault == 'empty': rows[1]['translation'] = ' '
        if fault == 'placeholder': rows[1]['translation'] = '（承接上文）'
        if fault == 'duplicate': rows[1]['id'] = 0
        if fault == 'reordered': rows[0],rows[1] = rows[1],rows[0]
        return {'items':rows}
    monkeypatch.setattr(caption, 'run_agy_structured', run)
    instance = processor(tmp_path)
    assert instance._build_agy_candidate(['A business can change.'] * 161, '') is None
    assert calls == [1] and instance._last_provider_error


@pytest.mark.parametrize('shifted', [False,True])
def test_forty_row_batch_keeps_half_clause_in_its_own_subtitle(tmp_path, monkeypatch, shifted):
    texts = ['A business can change.'] * 38 + ['How do we prepare', 'when oil crosses $115?']
    def run(prompt, **kwargs):
        data = json.loads(prompt.split('源字幕 JSON: ',1)[1])
        assert len(data) == 40 and '原文半句也必须保留半句' in prompt
        translated = ['企业可以改变'] * 38 + (['油价突破115美元时如何准备',''] if shifted
                                                       else ['我们该如何准备','当油价突破115美元时？'])
        # 模拟句子完整但片段错位，第二行仍非空，必须由事实归属门拒绝。
        if shifted: translated[-1] = '该怎么办？'
        raw = {'items':[{'id':i,'translation':text,'vocab':[]} for i,text in enumerate(translated)]}
        return CodexTextResult(kwargs['validate'](raw), 'gpt-5.6-luna', {}, 1)
    monkeypatch.setattr(codex, 'run_codex_structured', run)
    args = dict(state_dir=tmp_path, command='codex', max_attempts=1)
    if shifted:
        with pytest.raises(codex.CodexSubtitleError, match='NUMBER_AMOUNT_MISSING'):
            codex.build_codex_subtitle_candidate(texts, '', **args)
    else:
        result = codex.build_codex_subtitle_candidate(texts, '', **args)
        assert result.translations[-2:] == ['我们该如何准备','当油价突破115美元时？']


@pytest.mark.parametrize('fault', ['short','extra','empty','placeholder'])
def test_codex_large_batch_rejects_structural_faults(fault):
    texts = ['A business can change.'] * 40
    rows = [{'id':i,'translation':'企业可以改变','vocab':[]} for i in range(40)]
    if fault == 'short': rows.pop()
    if fault == 'extra': rows.append(dict(rows[-1]))
    if fault == 'empty': rows[1]['translation'] = ' '
    if fault == 'placeholder': rows[1]['translation'] = '（承接上文）'
    with pytest.raises(codex.CodexSubtitleError, match='subtitle_ids|subtitle_structure'):
        codex._validate_batch({'items':rows}, texts, 0, '')


def test_agy_decimal_timeout_is_not_misclassified_as_http_billing_error():
    from video_processing.utils.translation_model_pool import classify_error
    assert classify_error('agy timed out after 44.98063402075786s') == 'timeout'
