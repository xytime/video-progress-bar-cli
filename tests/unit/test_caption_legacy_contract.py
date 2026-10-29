"""已审查前代完成快照升级验收；只有离线整片复核，不请求翻译。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-29 | Codex | 基线/词汇元数据前代精确适配、未知合同和坏质量拒绝。 |
"""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from config.settings import settings
from video_processing.processors.caption_processor import AutoCaptionProcessor
from video_processing.utils.caption_checkpoints import CaptionCheckpoints, fingerprint, translation_contract
from video_processing.utils.caption_legacy_contract import MANIFEST, reviewed_target_contracts
from video_processing.utils.render_source_binding import digest
from video_processing.utils.subtitle_bad_cases import save_bad_case
from video_processing.utils.subtitle_failure_receipt import validate_quality_warning
from video_processing.utils.subtitle_sparse_policy import build_sparse_quality_report


def _fixture(tmp_path, profile_index=0, source=None, translated=None):
    path = tmp_path / 'video.mp4'
    path.write_bytes(b'bound media')
    source = source or [dict(start=0, end=3, text='Bonds still matter.')]
    segments = deepcopy(source)
    for segment, translation in zip(segments, translated or ['债券仍然重要。']):
        segment.update(zh_text=translation, vocab={})
    store = CaptionCheckpoints(path, dict(model='same-asr'))
    current_translation = translation_contract(AutoCaptionProcessor.__new__(AutoCaptionProcessor), settings)
    current = dict(asr_sha256=fingerprint(source), src_lang='en', detected_lang='en', target_lang='zh-CN',
                   translation=current_translation)
    profile = MANIFEST['profiles'][profile_index]
    previous = deepcopy(current)
    previous['translation'] = dict(version=1, methods=profile['methods'], modules=profile['modules'],
        config={key: current_translation['config'][key] for key in MANIFEST['legacy_config_keys']})
    return store, source, segments, previous, current


def test_target_manifest_matches_actual_execution_and_quality_contract():
    contract = translation_contract(AutoCaptionProcessor.__new__(AutoCaptionProcessor), settings)
    modules = dict(contract['modules'])
    modules.pop('caption_legacy_contract')
    assert dict(methods=contract['methods'], modules=modules) in reviewed_target_contracts()


@pytest.mark.parametrize('profile', [0, 1])
def test_exact_reviewed_legacy_contract_upgrades_atomically_after_full_quality(tmp_path, profile):
    store, source, segments, previous, current = _fixture(tmp_path, profile)
    store.save('translation', previous, segments, 'en', source, [dict(selected=True, status='clean')])
    result = store.load('translation', current, source)
    assert result and result['segments'] == segments
    assert result['quality_audit'][-1]['profile'] == MANIFEST['profiles'][profile]['name']
    payload = json.loads((store.directory / 'translation.json').read_text())
    assert payload['contract'] == current
    assert payload['result_sha256'] == fingerprint(result)
    assert store.load('translation', current, source) == result
    assert not list(store.directory.glob('*.tmp'))


@pytest.mark.parametrize('target_index', range(len(reviewed_target_contracts())))
def test_only_complete_reviewed_target_method_module_pairs_allow_revalidation(tmp_path, target_index):
    store, source, segments, previous, current = _fixture(tmp_path)
    reviewed = reviewed_target_contracts()[target_index]
    current['translation']['methods'] = reviewed['methods']
    current['translation']['modules'].update(reviewed['modules'])
    store.save('translation', previous, segments, 'en', source)
    assert store.load('translation', current, source) is not None
    current['translation']['modules']['codex_subtitle_provider'] = '0' * 64
    store.save('translation', previous, segments, 'en', source)
    assert store.load('translation', current, source) is None


@pytest.mark.parametrize('change', ['methods', 'module', 'config', 'asr', 'language', 'target_methods', 'target_module'])
def test_unknown_or_changed_dependency_is_not_a_legacy_whitelist(tmp_path, change):
    store, source, segments, previous, current = _fixture(tmp_path)
    if change == 'methods': previous['translation']['methods'] = '0' * 64
    if change == 'module': previous['translation']['modules'] = dict(previous['translation']['modules'], vocab_helper='0' * 64)
    if change == 'config': previous['translation']['config']['codex_text_model'] = 'other'
    if change == 'asr': previous['asr_sha256'] = '0' * 64
    if change == 'language': previous['src_lang'] = 'fr'
    if change == 'target_methods': current['translation']['methods'] = '0' * 64
    if change == 'target_module': current['translation']['modules']['translation_quality_guard'] = '0' * 64
    store.save('translation', previous, segments, 'en', source)
    assert store.load('translation', current, source) is None
    assert json.loads((store.directory / 'translation.json').read_text())['contract'] == previous


def test_legacy_valid_json_with_wrong_financial_facts_is_not_reused(tmp_path):
    store, source, segments, previous, current = _fixture(tmp_path,
        source=[dict(start=0, end=3, text='The fund raised $49 billion.')], translated=['基金退出49美元。'])
    store.save('translation', previous, segments, 'en', source)
    assert store.load('translation', current, source) is None
    assert json.loads((store.directory / 'translation.json').read_text())['contract'] == previous


def test_legacy_warning_cannot_lose_or_forge_immutable_evidence(tmp_path):
    store, source, segments, previous, current = _fixture(tmp_path)
    store.save('translation', previous, segments, 'en', source,
        quality_audit=[dict(selected=True, status='accepted_with_warnings')])
    assert store.load('translation', current, source) is None
    store.save('translation', previous, segments, 'en', source,
        quality_warning=dict(status='accepted_with_warnings', report={}))
    assert store.load('translation', current, source) is None


def test_verified_warning_keeps_old_case_and_binds_new_immutable_case_to_new_contract(tmp_path):
    source = [dict(start=index * 2, end=index * 2 + 2, text='Bonds are stable.') for index in range(40)]
    source[1]['text'] = 'Oil is $115 per barrel.'
    translated = ['债券稳定。'] * 40
    translated[1] = '油价为每桶1150亿美元。'
    store, source, segments, previous, current = _fixture(tmp_path, source=source, translated=translated)
    context = '\n'.join(segment['text'] for segment in source)
    history = [dict(strategy='isolated_source_repair', executed=True, segment_numbers=[2], repair_round=1)]
    report = build_sparse_quality_report(source, translated, context_text=context,
        vocabs=[{}] * 40, repair_history=history)
    assert report['status'] == 'accepted_with_warnings'
    binding = dict(input_sha256=digest(store.source), asr_sha256=fingerprint(source),
                   contract_sha256=fingerprint(previous))
    case = save_bad_case(tmp_path / 'bad_cases', dict(**binding, source_segments=source,
        translations=translated, vocabs=[{}] * 40, repair_history=history,
        context_text=context, report=report, candidate_sha256=report['candidate_sha256'],
        summary_sha256=report['summary_sha256']))
    warning = dict(status=report['status'], report=report, bad_case=case,
        candidate_sha256=report['candidate_sha256'], summary_sha256=report['summary_sha256'])
    validate_quality_warning(warning, segments=segments, **binding)
    old_bytes = Path(case['path']).read_bytes()
    store.save('translation', previous, segments, 'en', source,
        quality_audit=[dict(selected=True, status='accepted_with_warnings')], quality_warning=warning)
    result = store.load('translation', current, source)
    assert result is not None
    assert result['quality_warning']['bad_case'] != case
    assert Path(case['path']).read_bytes() == old_bytes
    validate_quality_warning(result['quality_warning'], segments=result['segments'],
        **dict(binding, contract_sha256=fingerprint(current)))
    assert store.load('translation', current, source) == result
