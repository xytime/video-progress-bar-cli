"""字幕故障交接绑定与恢复协调测试，不访问模型或平台。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-27 | Codex | 拒绝旧任务/错媒体/损坏快照，真实DAL验证冷却与通知去重。 |
"""
import json
from pathlib import Path
import subprocess
import time
import uuid

import pytest

from video_processing.utils.subtitle_failure_receipt import (
    SubtitleTranslationFailure, safe_failure, fingerprint, write_failure_receipt,
    write_success_receipt, read_bound_receipt,
)
from video_processing.utils.render_source_binding import digest


def failure(source, category='quality'):
    error = SubtitleTranslationFailure([safe_failure('codex', 'subtitle_quality_NUMBER_AMOUNT_MISSING',
        category=category, quality_details=[dict(segment_number=3, source_id=2, code='NUMBER_AMOUNT_MISSING',
                                               source_signal='$115', translation_signal='missing')])])
    error.binding = dict(input_sha256=digest(source), asr_sha256='b'*64, contract_sha256='c'*64, stage='TRANSLATING')
    return error


def test_failure_receipt_rejects_stale_attempt_wrong_media_and_changed_signal(tmp_path):
    source = tmp_path/'source.mp4'
    source.write_bytes(b'media')
    path, attempt, started = tmp_path/'failure.json', uuid.uuid4().hex, time.time()
    payload = write_failure_receipt(path, attempt, source, failure(source))
    kwargs = dict(attempt_id=attempt, input_path=source, input_sha256=digest(source), started_at=started)
    assert read_bound_receipt(path, **kwargs)['quality_details'][0]['source_id'] == 2
    assert read_bound_receipt(path, **(kwargs | dict(attempt_id=uuid.uuid4().hex))) is None
    assert read_bound_receipt(path, **(kwargs | dict(started_at=started+10))) is None
    payload['quality_details'][0]['source_signal'] = '$115B'
    path.write_text(json.dumps(payload))
    assert read_bound_receipt(path, **kwargs) is None
    write_failure_receipt(path, attempt, source, failure(source))
    source.write_bytes(b'changed')
    assert read_bound_receipt(path, **kwargs) is None


def test_safe_failure_does_not_persist_arbitrary_error_body():
    value = safe_failure('unknown', 'request failed token=secret\nraw prompt')
    assert value['code'] == 'provider_failure'
    assert value['provider'] == 'host'
    assert 'secret' not in json.dumps(value)


def test_success_receipt_requires_intact_normal_checkpoint(tmp_path):
    from video_processing.utils.caption_checkpoints import CaptionCheckpoints
    source = tmp_path/'source.mp4'
    source.write_bytes(b'media')
    store = CaptionCheckpoints(source, dict(model='fake'))
    segments = [dict(start=0, end=1, text='Bonds.', zh_text='债券。')]
    contract = dict(asr_sha256=fingerprint(segments), target_lang='zh-CN')
    store.save('asr', store.identity['asr'], segments, 'en')
    store.save('translation', contract, segments, 'en', segments)
    checkpoint = store.directory/'translation.json'
    completion = dict(input_sha256=digest(source), asr_sha256=fingerprint(segments),
                      contract_sha256=fingerprint(contract), checkpoint_path=str(checkpoint),
                      checkpoint_sha256=digest(checkpoint))
    path, attempt, started = tmp_path/'success.json', uuid.uuid4().hex, time.time()
    write_success_receipt(path, attempt, source, completion)
    kwargs = dict(attempt_id=attempt, input_path=source, input_sha256=digest(source), started_at=started, success=True)
    assert read_bound_receipt(path, **kwargs)
    asr_path = store.directory/'asr.json'
    asr_original = asr_path.read_bytes()
    asr_payload = json.loads(asr_original)
    asr_payload['result']['segments'][0]['text'] = 'Changed.'
    asr_payload['result_sha256'] = fingerprint(asr_payload['result'])
    asr_path.write_text(json.dumps(asr_payload))
    assert read_bound_receipt(path, **kwargs) is None
    asr_path.write_bytes(asr_original)
    checkpoint.write_text('{}')
    assert read_bound_receipt(path, **kwargs) is None


def test_pipeline_consumes_only_bound_failure_and_notifies_once(tmp_path, monkeypatch):
    from video_processing.pipeline_manager import PipelineManager
    from video_processing.core.wechat_request_guard import WeChatRequestGuard
    manager = PipelineManager(str(tmp_path/'pipeline.db'))
    manager._OUT_DIR = tmp_path
    manager.db.add_video('examplevideo', '标题', 'channel', score=80)
    manager.db.update_video_status('examplevideo', 'TRANSCRIBING')
    source = tmp_path/'source.mp4'
    source.write_bytes(b'media')
    path, attempt, started = tmp_path/'failure.json', uuid.uuid4().hex, time.time()
    write_failure_receipt(path, attempt, source, failure(source, 'network'))
    messages = []
    manager.send_telegram_msg = messages.append
    monkeypatch.setattr(WeChatRequestGuard, 'snapshot', lambda self: {'schedule': {}})
    kwargs = dict(slice_index=0, receipt_path=path, attempt_id=attempt, input_path=source,
                  input_sha256=digest(source), started_at=started)
    error = subprocess.CalledProcessError(75, ['auto-caption'])
    assert not manager._consume_subtitle_failure('examplevideo', '标题', error, **(kwargs | dict(attempt_id=uuid.uuid4().hex)))
    assert manager._consume_subtitle_failure('examplevideo', '标题', error, **kwargs)
    assert manager._consume_subtitle_failure('examplevideo', '标题', error, **kwargs)
    assert len(messages) == 1
    video = manager.db.get_video_by_youtube_id('examplevideo')
    assert video['status'] == 'PENDING' and video['retry_count'] == 0
    assert not manager.db.claim_video_for_processing('examplevideo')
    assert manager.db.subtitle_recovery_blocker(video['id'])['state'] == 'WAITING'


def test_pipeline_does_not_requeue_when_account_has_submission_intent(tmp_path, monkeypatch):
    from video_processing.pipeline_manager import PipelineManager
    from video_processing.core.wechat_request_guard import WeChatRequestGuard
    manager = PipelineManager(str(tmp_path/'pipeline.db'))
    manager._OUT_DIR = tmp_path
    manager.db.add_video('examplevideo', '标题', 'channel', score=80)
    manager.db.update_video_status('examplevideo', 'TRANSCRIBING')
    source = tmp_path/'source.mp4'
    source.write_bytes(b'media')
    path, attempt, started = tmp_path/'failure.json', uuid.uuid4().hex, time.time()
    write_failure_receipt(path, attempt, source, failure(source, 'network'))
    monkeypatch.setattr(WeChatRequestGuard, 'snapshot', lambda self: {'schedule': {'submit_intents': {'examplevideo': {}}}})
    assert not manager._consume_subtitle_failure('examplevideo', '标题', subprocess.CalledProcessError(75, []),
        slice_index=0, receipt_path=path, attempt_id=attempt, input_path=source,
        input_sha256=digest(source), started_at=started)
    assert manager.db.get_subtitle_recovery(manager.db.get_video_by_youtube_id('examplevideo')['id']) is None


def test_existing_scheduler_sweep_expires_and_notifies_only_once(tmp_path):
    from video_processing.pipeline_manager import PipelineManager
    manager = PipelineManager(str(tmp_path/'pipeline.db'))
    manager.db.add_video('examplevideo', '标题', 'channel', score=80)
    source = tmp_path/'source.mp4'
    source.write_bytes(b'media')
    path, attempt = tmp_path/'failure.json', uuid.uuid4().hex
    receipt = write_failure_receipt(path, attempt, source, failure(source, 'network'))
    manager.db.record_subtitle_failure('examplevideo', 0, receipt, str(path), digest(path))
    with manager.db.get_connection() as connection:
        connection.execute('UPDATE subtitle_recovery SET expires_at=?', (time.time()-1,))
    messages = []
    manager.send_telegram_msg = messages.append
    manager._expire_subtitle_recoveries()
    manager._expire_subtitle_recoveries()
    assert len(messages) == 1
    video = manager.db.get_video_by_youtube_id('examplevideo')
    assert video['status'] == 'FAILED'
    assert manager.db.get_subtitle_recovery(video['id'])['state'] == 'NEEDS_REPAIR'
