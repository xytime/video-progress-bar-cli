"""字幕稀疏问题告警的绑定交接、持久去重和投递恢复。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-27 | Codex | 真实临时DAL与正常快照拒绝伪造范围、案例缺失和陈旧投递租约。 |
"""
from copy import deepcopy
import json
import time
import uuid

import pytest

from video_processing.db.database import PipelineDB
from video_processing.utils.caption_checkpoints import CaptionCheckpoints
from video_processing.utils.render_source_binding import digest
from video_processing.utils.subtitle_bad_cases import save_bad_case
from video_processing.utils.subtitle_failure_receipt import (
    begin_subtitle_render, caption_checkpoint_ass_comment, compact_quality_warning,
    finish_subtitle_render, fingerprint,
    read_bound_receipt, read_cached_quality_warning, write_success_receipt,
)
from video_processing.utils.subtitle_quality_notifications import (
    format_subtitle_quality_warning, warning_dedupe_key,
)
from video_processing.utils.subtitle_sparse_policy import build_sparse_quality_report, report_fingerprint


def envelope():
    return dict(status='accepted_with_warnings', candidate_sha256='a'*64, summary_sha256='b'*64,
                report=dict(affected_segments=[2], segment_ratio=0.025, duration_ratio=0.025,
                            issues=[dict(segment_number=2, start=1, end=2, code='NUMBER_MAGNITUDE_MISMATCH', severity='P0',
                                         source_signal='$1 million', translation_signal='10亿美元')]),
                bad_case=dict(case_id='c'*64, path='/evidence/cases/cc/'+'c'*64+'.json', sha256='d'*64))


def database(tmp_path):
    db = PipelineDB(str(tmp_path/'pipeline.db'))
    db.add_video('examplevideo', '标题', 'channel', score=80)
    return db


def test_candidate_problem_identity_is_permanent_but_new_issue_is_independent(tmp_path):
    db = database(tmp_path)
    first = db.enqueue_subtitle_quality_notification('examplevideo', 0, envelope(), now=100)
    assert db.enqueue_subtitle_quality_notification('examplevideo', 0, envelope(), now=200)['id'] == first['id']
    claimed = db.claim_subtitle_quality_notifications(now=100)[0]
    db.finish_subtitle_quality_notification(claimed['id'], claimed['claim_token'], 'ACCEPTED', message_id='41', now=110)
    assert db.claim_subtitle_quality_notifications(now=100+365*86400) == []
    changed = envelope() | dict(summary_sha256='e'*64)
    assert db.enqueue_subtitle_quality_notification('examplevideo', 0, changed, now=300)['id'] != first['id']
    assert db.get_video_by_youtube_id('examplevideo')['status'] == 'PENDING'


def test_delivery_failure_is_persistent_and_retries_with_backoff(tmp_path):
    db = database(tmp_path)
    queued = db.enqueue_subtitle_quality_notification('examplevideo', 0, envelope(), now=100)
    claimed = db.claim_subtitle_quality_notifications(now=100)[0]
    state = db.finish_subtitle_quality_notification(claimed['id'], claimed['claim_token'], 'FAILED', error_kind='HTTP_503', now=101)
    assert state['state'] == 'PENDING' and state['next_attempt_at'] == 401
    restarted = PipelineDB(db.db_path)
    assert restarted.claim_subtitle_quality_notifications(now=400) == []
    next_claim = restarted.claim_subtitle_quality_notifications(now=401)[0]
    assert next_claim['id'] == queued['id'] and next_claim['attempts'] == 2
    state = restarted.finish_subtitle_quality_notification(next_claim['id'], next_claim['claim_token'], 'UNKNOWN', error_kind='ReadTimeout', now=402)
    assert state['state'] == 'PENDING' and state['last_delivery_state'] == 'UNKNOWN'
    assert state['next_attempt_at'] == 1302


def test_stale_worker_cannot_finish_reclaimed_lease(tmp_path):
    db = database(tmp_path)
    db.enqueue_subtitle_quality_notification('examplevideo', 0, envelope(), now=100)
    old = db.claim_subtitle_quality_notifications(now=100)[0]
    assert db.claim_subtitle_quality_notifications(now=219) == []
    fresh = db.claim_subtitle_quality_notifications(now=220)[0]
    assert fresh['last_delivery_state'] == 'UNKNOWN' and fresh['attempts'] == 2
    state = db.finish_subtitle_quality_notification(old['id'], old['claim_token'], 'ACCEPTED', message_id='old', now=221)
    assert state['state'] == 'PROCESSING' and state['claim_token'] == fresh['claim_token']
    db.finish_subtitle_quality_notification(fresh['id'], fresh['claim_token'], 'ACCEPTED', message_id='new', now=222)
    assert db.claim_subtitle_quality_notifications(now=10000) == []


def test_delivery_attempts_are_bounded_and_api_acceptance_requires_message_id(tmp_path):
    db = database(tmp_path)
    queued = db.enqueue_subtitle_quality_notification('examplevideo', 0, envelope(), now=100)
    now = 100
    for number in range(1, 7):
        task = db.claim_subtitle_quality_notifications(now=now)[0]
        assert task['attempts'] == number
        with pytest.raises(ValueError, match='message ID'):
            db.finish_subtitle_quality_notification(task['id'], task['claim_token'], 'ACCEPTED', now=now)
        state = db.finish_subtitle_quality_notification(task['id'], task['claim_token'], 'FAILED',
                                                       error_kind='token=secret\nURL', now=now)
        now = state['next_attempt_at']
    assert state['state'] == 'FAILED' and state['last_error_kind'] == 'DELIVERY_ERROR'
    assert db.claim_subtitle_quality_notifications(now=now+86400) == []
    assert db.list_subtitle_quality_notifications(state='FAILED')[0]['id'] == queued['id']


def test_warning_copy_escapes_source_signals_and_does_not_claim_publication():
    warning = envelope()
    warning['report']['issues'][0]['source_signal'] = '<script>&source'
    text = format_subtitle_quality_warning('examplevideo', 2, warning, title='<b>标题</b>')
    assert 'YouTube ID: <code>examplevideo_s2</code>' in text
    assert '&lt;script&gt;&amp;source' in text and '<script>' not in text
    assert '2.50%' in text and '第2段 00:01–00:02' in text
    assert '[P0] NUMBER_MAGNITUDE_MISMATCH' in text
    assert '不代表平台已发布' in text and '仍须通过审查与发布门禁' in text
    assert warning_dedupe_key('examplevideo', 0, warning) != warning_dedupe_key('examplevideo', 2, warning)
    assert warning_dedupe_key('examplevideo', 0, warning) != warning_dedupe_key('examplevideo', 0, warning | dict(summary_sha256='f'*64))


@pytest.mark.parametrize('field,code,label', [
    ('global_warnings', 'AMOUNT_CONSISTENCY_UNIT_DRIFT', '全片一致性疑点'),
    ('removed_vocab_issues', 'VOCAB_ALIGNMENT_MISMATCH', '已处理词注'),
])
def test_warning_copy_keeps_problem_type_when_no_local_issue_remains(field, code, label):
    warning = envelope()
    warning['report'].update(issues=[], affected_segments=[], segment_ratio=0, duration_ratio=0)
    warning['report'][field] = [dict(code=code, severity='P1' if field == 'global_warnings' else 'P2')]
    text = format_subtitle_quality_warning('examplevideo', 0, warning)
    assert label in text and code in text
    assert '已尝试针对性修复' not in text


def bound_success(tmp_path, *, current_contract=False, model='fake', mistranslation='他们募集了10亿美元。'):
    source = tmp_path/'source.mp4'
    source.write_bytes(b'media')
    store = CaptionCheckpoints(source, dict(model=model))
    original = [dict(start=index, end=index+1, text='Bonds are stable.') for index in range(40)]
    original[1]['text'] = 'They raised $1 million.'
    translations = ['债券稳定。']*40
    translations[1] = mistranslation
    history = [dict(strategy='isolated_source_repair', executed=True, segment_numbers=[2])]
    report = build_sparse_quality_report(original, translations, repair_history=history)
    assert report['status'] == 'accepted_with_warnings'
    translated = [dict(segment, zh_text=text, vocab={}) for segment, text in zip(original, translations)]
    contract = dict(asr_sha256=fingerprint(original), target_lang='zh-CN')
    if current_contract:
        from config.settings import settings
        from video_processing.utils import caption_checkpoints as checkpoint_contract
        from pathlib import Path
        contract['translation'] = dict(version=checkpoint_contract.VERSION, methods='e'*64,
            modules={name: digest(Path(checkpoint_contract.__file__).with_name(name+'.py'))
                     for name in checkpoint_contract.TRANSLATION_MODULES},
            config={name: getattr(settings, name, None) for name in checkpoint_contract.TRANSLATION_SETTINGS})
    store.save('asr', store.identity['asr'], original, 'en')
    store.save('translation', contract, translated, 'en', original)
    checkpoint = store.directory/'translation.json'
    binding = dict(input_sha256=digest(source), asr_sha256=fingerprint(original), contract_sha256=fingerprint(contract))
    case_payload = dict(**binding, candidate_sha256=report['candidate_sha256'], summary_sha256=report['summary_sha256'],
                        report=report, source_segments=original, translations=translations, vocabs=[{}]*40,
                        context_text='', repair_history=history)
    bad_case = save_bad_case(tmp_path/'bad_cases', case_payload)
    warning = dict(report=report, status='accepted_with_warnings', candidate_sha256=report['candidate_sha256'],
                   summary_sha256=report['summary_sha256'], bad_case=bad_case)
    payload = json.loads(checkpoint.read_text())
    payload['result']['quality_warning'] = warning
    payload['result_sha256'] = fingerprint(payload['result'])
    checkpoint.write_text(json.dumps(payload))
    completion = dict(**binding, checkpoint_path=str(checkpoint), checkpoint_sha256=digest(checkpoint), quality_warning=warning)
    path, attempt, started = tmp_path/'success.json', uuid.uuid4().hex, time.time()
    write_success_receipt(path, attempt, source, completion)
    kwargs = dict(attempt_id=attempt, input_path=source, input_sha256=digest(source), started_at=started, success=True)
    return path, kwargs, warning, checkpoint, case_payload


def test_success_warning_receipt_is_compact_and_revalidates_normal_case(tmp_path):
    path, kwargs, warning, _, _ = bound_success(tmp_path)
    receipt = json.loads(path.read_text())
    assert receipt['quality_warning'] == compact_quality_warning(warning)
    assert 'report' not in receipt['quality_warning']
    verified = read_bound_receipt(path, **kwargs)
    assert verified['quality_warning'] == warning


def test_missing_case_or_mismatched_summary_cannot_appear_as_clean_success(tmp_path):
    path, kwargs, warning, _, _ = bound_success(tmp_path)
    receipt = json.loads(path.read_text())
    receipt['quality_warning']['summary_sha256'] = 'e'*64
    path.write_text(json.dumps(receipt))
    assert read_bound_receipt(path, **kwargs) is None
    receipt['quality_warning'] = compact_quality_warning(warning)
    path.write_text(json.dumps(receipt))
    from pathlib import Path
    Path(warning['bad_case']['path']).unlink()
    assert read_bound_receipt(path, **kwargs) is None


def test_rehashing_a_forged_extent_still_fails_current_policy_recomputation(tmp_path):
    path, kwargs, warning, checkpoint, case_payload = bound_success(tmp_path)
    forged = deepcopy(warning)
    forged['report']['segment_ratio'] = 0
    forged['report']['summary_sha256'] = report_fingerprint(forged['report'])
    forged['summary_sha256'] = forged['report']['summary_sha256']
    case_payload.update(report=forged['report'], summary_sha256=forged['summary_sha256'])
    forged['bad_case'] = save_bad_case(tmp_path/'bad_cases', case_payload)
    payload = json.loads(checkpoint.read_text())
    payload['result']['quality_warning'] = forged
    payload['result_sha256'] = fingerprint(payload['result'])
    checkpoint.write_text(json.dumps(payload))
    receipt = json.loads(path.read_text())
    receipt.update(quality_warning=compact_quality_warning(forged), checkpoint_sha256=digest(checkpoint))
    path.write_text(json.dumps(receipt))
    assert read_bound_receipt(path, **kwargs) is None


def test_render_cache_recovers_one_current_bound_warning_without_old_receipt(tmp_path):
    _, kwargs, warning, _, _ = bound_success(tmp_path, current_contract=True)
    assert read_cached_quality_warning(kwargs['input_path']) == [warning]


@pytest.mark.parametrize('component', ['modules', 'config'])
def test_render_cache_rejects_outdated_warning_dependency_or_config(tmp_path, component):
    _, kwargs, _, checkpoint, _ = bound_success(tmp_path, current_contract=True)
    payload = json.loads(checkpoint.read_text())
    key = next(iter(payload['contract']['translation'][component]))
    payload['contract']['translation'][component][key] = 'outdated'
    checkpoint.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match='invalid or outdated'):
        read_cached_quality_warning(kwargs['input_path'])


def test_render_cache_rejects_corrupt_warning_and_missing_case(tmp_path):
    _, kwargs, warning, checkpoint, _ = bound_success(tmp_path, current_contract=True)
    original = checkpoint.read_bytes()
    payload = json.loads(original)
    payload['result']['segments'][0]['zh_text'] = '被改过的译文'
    checkpoint.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match='binding mismatch'):
        read_cached_quality_warning(kwargs['input_path'])
    checkpoint.write_bytes(original)
    from pathlib import Path
    Path(warning['bad_case']['path']).unlink()
    with pytest.raises(FileNotFoundError):
        read_cached_quality_warning(kwargs['input_path'])


def test_render_cache_rejects_multiple_possible_selected_warning_candidates(tmp_path):
    _, kwargs, _, _, _ = bound_success(tmp_path, current_contract=True)
    bound_success(tmp_path, current_contract=True, model='other-asr', mistranslation='他们募集了20亿美元。')
    with pytest.raises(ValueError, match='ambiguous'):
        read_cached_quality_warning(kwargs['input_path'])


def test_render_cache_cannot_drop_an_audited_warning_envelope(tmp_path):
    _, kwargs, _, checkpoint, _ = bound_success(tmp_path, current_contract=True)
    payload = json.loads(checkpoint.read_text())
    payload['result'].pop('quality_warning')
    payload['result']['quality_audit'] = [dict(event='bad_case_saved', status='accepted_with_warnings')]
    payload['result_sha256'] = fingerprint(payload['result'])
    checkpoint.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match='envelope missing'):
        read_cached_quality_warning(kwargs['input_path'])


@pytest.mark.parametrize('audit', [
    dict(event='bad_case_saved', status='accepted_with_warnings'),
    dict(provider='codex', selected=True, status='accepted_with_warnings'),
])
def test_normal_checkpoint_and_success_receipt_cannot_drop_audited_warning(tmp_path, audit):
    path, kwargs, _, checkpoint, case_payload = bound_success(tmp_path)
    payload = json.loads(checkpoint.read_text())
    payload['result'].pop('quality_warning')
    payload['result']['quality_audit'] = [audit]
    payload['result_sha256'] = fingerprint(payload['result'])
    checkpoint.write_text(json.dumps(payload))
    receipt = json.loads(path.read_text())
    receipt.pop('quality_warning')
    receipt['checkpoint_sha256'] = digest(checkpoint)
    path.write_text(json.dumps(receipt))
    store = CaptionCheckpoints(kwargs['input_path'], dict(model='fake'))
    assert store.load('translation', payload['contract'], case_payload['source_segments']) is None
    assert read_bound_receipt(path, **kwargs) is None


def test_normal_checkpoint_does_not_confuse_unselected_warning_with_selected_output(tmp_path):
    source = tmp_path/'source.mp4'
    source.write_bytes(b'media')
    store = CaptionCheckpoints(source, dict(model='fake'))
    original = [dict(start=0, end=1, text='Bonds are stable.')]
    translated = [dict(original[0], zh_text='债券稳定。')]
    contract = dict(target_lang='zh-CN')
    store.save('translation', contract, translated, 'en', original,
               quality_audit=[dict(provider='codex', selected=False, status='accepted_with_warnings')])
    assert store.load('translation', contract, original)['segments'] == translated


def test_render_cache_does_not_attach_warning_for_other_source_bytes(tmp_path):
    _, kwargs, _, _, _ = bound_success(tmp_path, current_contract=True)
    kwargs['input_path'].write_bytes(b'new media')
    assert read_cached_quality_warning(kwargs['input_path']) == []


def marked_ass(tmp_path, receipt_path, *, remove_warning=False):
    completion = json.loads(receipt_path.read_text())
    if remove_warning:
        completion.pop('quality_warning', None)
    comment = caption_checkpoint_ass_comment(completion)
    assert '\n' not in comment and '\r' not in comment
    path = tmp_path/'source.ass'
    path.write_text(comment + '\n[Script Info]\nScriptType: v4.00+\n', encoding='utf-8')
    return path


def test_ass_marker_selects_exact_rendered_candidate_despite_other_asr_warning(tmp_path):
    path, kwargs, warning, _, _ = bound_success(tmp_path, current_contract=True)
    ass_path = marked_ass(tmp_path, path)
    bound_success(tmp_path, current_contract=True, model='other-asr', mistranslation='他们募集了20亿美元。')
    assert read_cached_quality_warning(kwargs['input_path'], ass_path=ass_path) == [warning]


def test_ass_marker_rejects_missing_checkpoint_directory_instead_of_losing_warning(tmp_path):
    path, kwargs, _, checkpoint, _ = bound_success(tmp_path, current_contract=True)
    ass_path = marked_ass(tmp_path, path)
    import shutil
    shutil.rmtree(checkpoint.parent.parent)
    with pytest.raises(ValueError, match='checkpoint directory'):
        read_cached_quality_warning(kwargs['input_path'], ass_path=ass_path)


@pytest.mark.parametrize('change', ['digest', 'path', 'media', 'duplicate', 'missing-warning'])
def test_ass_marker_rejects_tampering_and_duplicate_provenance(tmp_path, change):
    path, kwargs, _, _, _ = bound_success(tmp_path, current_contract=True)
    completion = json.loads(path.read_text())
    if change == 'digest':
        completion['checkpoint_sha256'] = 'f'*64
    elif change == 'path':
        completion['checkpoint_path'] = str(tmp_path/'translation.json')
    elif change == 'media':
        completion['input_sha256'] = 'f'*64
    elif change == 'missing-warning':
        completion.pop('quality_warning')
    comment = caption_checkpoint_ass_comment(completion)
    ass_path = tmp_path/'source.ass'
    ass_path.write_text(comment + '\n' + (comment + '\n' if change == 'duplicate' else '[Script Info]\n'))
    with pytest.raises(ValueError):
        read_cached_quality_warning(kwargs['input_path'], ass_path=ass_path)


def test_clean_ass_marker_still_requires_unchanged_normal_checkpoint(tmp_path):
    path, kwargs, _, checkpoint, _ = bound_success(tmp_path, current_contract=True)
    payload = json.loads(checkpoint.read_text())
    # 一份真正的干净译文：同时移除已不适用的告警及审计。
    payload['result']['segments'][1]['zh_text'] = '他们募集了100万美元。'
    payload['result'].pop('quality_warning')
    payload['result']['quality_audit'] = []
    payload['result_sha256'] = fingerprint(payload['result'])
    checkpoint.write_text(json.dumps(payload))
    completion = json.loads(path.read_text())
    completion.pop('quality_warning')
    completion['checkpoint_sha256'] = digest(checkpoint)
    ass_path = tmp_path/'source.ass'
    ass_path.write_text(caption_checkpoint_ass_comment(completion) + '\n[Script Info]\n')
    assert read_cached_quality_warning(kwargs['input_path'], ass_path=ass_path) == []
    checkpoint.unlink()
    with pytest.raises(FileNotFoundError):
        read_cached_quality_warning(kwargs['input_path'], ass_path=ass_path)


def test_unmarked_legacy_ass_keeps_compatible_checkpoint_scan(tmp_path):
    path, kwargs, warning, _, _ = bound_success(tmp_path, current_contract=True)
    ass_path = tmp_path/'legacy.ass'
    ass_path.write_text('[Script Info]\nScriptType: v4.00+\n')
    assert read_cached_quality_warning(kwargs['input_path'], ass_path=ass_path) == [warning]


def render_intent_fixture(tmp_path):
    receipt, kwargs, warning, checkpoint, _ = bound_success(tmp_path, current_contract=True)
    ass = marked_ass(tmp_path, receipt)
    output = tmp_path/'captioned.mp4'
    completion = json.loads(receipt.read_text())
    begin_subtitle_render(output, kwargs['input_path'], ass, completion)
    # 无需真实编解码器，宿主绑定只依赖实际文件字节。
    output.write_bytes(b'rendered with subtitles')
    return kwargs['input_path'], ass, output, warning, checkpoint


def test_subtitle_render_intent_is_persistent_before_burn_and_complete_after_output(tmp_path):
    source, ass, output, warning, _ = render_intent_fixture(tmp_path)
    sidecar = output.with_name(output.name + '.subtitle-quality.json')
    assert json.loads(sidecar.read_text())['state'] == 'RENDERING'
    with pytest.raises(ValueError, match='incomplete'):
        read_cached_quality_warning(source, ass_path=ass, render_path=output)
    completed = finish_subtitle_render(output, source, ass)
    assert completed['state'] == 'COMPLETE' and completed['output_sha256'] == digest(output)
    assert read_cached_quality_warning(source, ass_path=ass, render_path=output) == [warning]
    assert finish_subtitle_render(output, source, ass) == completed


@pytest.mark.parametrize('change', ['ass', 'marker-missing', 'output', 'input', 'checkpoint', 'cp-directory'])
def test_subtitle_render_cache_rejects_replaced_or_missing_evidence(tmp_path, change):
    source, ass, output, _, checkpoint = render_intent_fixture(tmp_path)
    finish_subtitle_render(output, source, ass)
    if change == 'ass':
        ass.write_text(ass.read_text() + '; changed subtitle body\n')
    elif change == 'marker-missing':
        ass.write_text('[Script Info]\nScriptType: v4.00+\n')
        import shutil
        shutil.rmtree(checkpoint.parent.parent)
    elif change == 'output':
        output.write_bytes(b'another rendered video')
    elif change == 'input':
        source.write_bytes(b'another source video')
    elif change == 'checkpoint':
        checkpoint.unlink()
    elif change == 'cp-directory':
        import shutil
        shutil.rmtree(checkpoint.parent.parent)
    with pytest.raises((ValueError, OSError)):
        read_cached_quality_warning(source, ass_path=ass, render_path=output)


def test_subtitle_render_intent_cannot_be_checked_without_its_ass(tmp_path):
    source, ass, output, _, _ = render_intent_fixture(tmp_path)
    finish_subtitle_render(output, source, ass)
    with pytest.raises(ValueError, match='requires ASS'):
        read_cached_quality_warning(source, render_path=output)


@pytest.mark.parametrize('change', ['state', 'path', 'extra-field', 'output-digest', 'warning'])
def test_subtitle_render_intent_rejects_forged_schema_and_marker_binding(tmp_path, change):
    source, ass, output, _, _ = render_intent_fixture(tmp_path)
    finish_subtitle_render(output, source, ass)
    sidecar = output.with_name(output.name + '.subtitle-quality.json')
    intent = json.loads(sidecar.read_text())
    if change == 'state':
        intent['state'] = 'UNKNOWN'
    elif change == 'path':
        intent['output_path'] = str(tmp_path/'other.mp4')
    elif change == 'extra-field':
        intent['unexpected'] = True
    elif change == 'output-digest':
        intent['output_sha256'] = 'e'*64
    elif change == 'warning':
        intent['checkpoint']['quality_warning'] = None
    sidecar.write_text(json.dumps(intent))
    with pytest.raises(ValueError):
        read_cached_quality_warning(source, ass_path=ass, render_path=output)


def test_subtitle_render_begin_requires_exact_ass_completion_and_finish_requires_output(tmp_path):
    receipt, kwargs, _, _, _ = bound_success(tmp_path, current_contract=True)
    ass, output = marked_ass(tmp_path, receipt), tmp_path/'captioned.mp4'
    completion = json.loads(receipt.read_text())
    wrong_completion = deepcopy(completion)
    wrong_completion['checkpoint_sha256'] = 'e'*64
    with pytest.raises(ValueError, match='completion mismatch'):
        begin_subtitle_render(output, kwargs['input_path'], ass, wrong_completion)
    begin_subtitle_render(output, kwargs['input_path'], ass, completion)
    with pytest.raises(FileNotFoundError):
        finish_subtitle_render(output, kwargs['input_path'], ass)
    sidecar = output.with_name(output.name + '.subtitle-quality.json')
    assert json.loads(sidecar.read_text())['state'] == 'RENDERING'


def test_render_path_without_new_intent_keeps_legacy_compatibility(tmp_path):
    receipt, kwargs, warning, _, _ = bound_success(tmp_path, current_contract=True)
    ass, output = marked_ass(tmp_path, receipt), tmp_path/'old-captioned.mp4'
    output.write_bytes(b'old render')
    assert read_cached_quality_warning(kwargs['input_path'], ass_path=ass, render_path=output) == [warning]


def test_clean_render_intent_still_binds_output_and_normal_checkpoint(tmp_path):
    receipt, kwargs, _, checkpoint, _ = bound_success(tmp_path, current_contract=True)
    payload = json.loads(checkpoint.read_text())
    payload['result']['segments'][1]['zh_text'] = '他们募集了100万美元。'
    payload['result'].pop('quality_warning')
    payload['result']['quality_audit'] = []
    payload['result_sha256'] = fingerprint(payload['result'])
    checkpoint.write_text(json.dumps(payload))
    completion = json.loads(receipt.read_text())
    completion.pop('quality_warning')
    completion['checkpoint_sha256'] = digest(checkpoint)
    ass, output = tmp_path/'source.ass', tmp_path/'captioned.mp4'
    ass.write_text(caption_checkpoint_ass_comment(completion) + '\n[Script Info]\n')
    begin_subtitle_render(output, kwargs['input_path'], ass, completion)
    output.write_bytes(b'clean rendered subtitles')
    finish_subtitle_render(output, kwargs['input_path'], ass)
    assert read_cached_quality_warning(kwargs['input_path'], ass_path=ass, render_path=output) == []
    output.write_bytes(b'output replaced')
    with pytest.raises(ValueError, match='output binding'):
        read_cached_quality_warning(kwargs['input_path'], ass_path=ass, render_path=output)


def test_render_intent_rejects_symlink_sidecar_even_with_identical_bytes(tmp_path):
    source, ass, output, _, _ = render_intent_fixture(tmp_path)
    finish_subtitle_render(output, source, ass)
    sidecar = output.with_name(output.name + '.subtitle-quality.json')
    copied = tmp_path/'copied-intent.json'
    copied.write_bytes(sidecar.read_bytes())
    sidecar.unlink()
    sidecar.symlink_to(copied)
    with pytest.raises(ValueError, match='symlink'):
        read_cached_quality_warning(source, ass_path=ass, render_path=output)
