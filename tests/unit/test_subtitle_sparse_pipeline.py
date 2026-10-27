"""真实字幕告警发件箱与流水线投递交接，不初始化发布流程。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-27 | Codex | 仅替换 Telegram 传输，验证显式 P1 事件、候选/问题去重、退避及重启恢复。 |
"""
from pathlib import Path

import pytest

from video_processing import pipeline_manager as pipeline
from video_processing.db.database import PipelineDB
from video_processing.telegram_delivery import TelegramDeliveryResult
from video_processing.utils.render_source_binding import digest
from video_processing.utils.subtitle_bad_cases import save_bad_case
from video_processing.utils.subtitle_failure_receipt import fingerprint, validate_quality_warning
from video_processing.utils.subtitle_quality_notifications import EVENT_TYPE, warning_dedupe_key
from video_processing.utils.subtitle_sparse_policy import build_sparse_quality_report


class _ClockedDatabase(PipelineDB):
    """仍走实际 DAL/SQLite；利用 DAL 的显式时钟参数免去睡眠或全局时间替换。"""

    def __init__(self, path, now=1000):
        super().__init__(str(path))
        self.now = now

    def enqueue_subtitle_quality_notification(self, *args, **kwargs):
        kwargs.setdefault('now', self.now)
        return super().enqueue_subtitle_quality_notification(*args, **kwargs)

    def claim_subtitle_quality_notifications(self, *args, **kwargs):
        kwargs.setdefault('now', self.now)
        return super().claim_subtitle_quality_notifications(*args, **kwargs)

    def finish_subtitle_quality_notification(self, *args, **kwargs):
        kwargs.setdefault('now', self.now)
        return super().finish_subtitle_quality_notification(*args, **kwargs)


def _database(tmp_path):
    db = _ClockedDatabase(tmp_path/'pipeline.db')
    db.add_video('examplevideo', '油价问题', 'channel', score=80)
    return db


def _manager(db):
    manager = pipeline.PipelineManager.__new__(pipeline.PipelineManager)
    manager.db = db
    # 传输边界已替换，避免读取任何真实凭据或初始化浏览器、调度器。
    manager.telegram_token = 'test-placeholder'
    manager.telegram_chat_id = 'test-chat'
    return manager


def _warning(tmp_path, *, repair_round=1):
    source = tmp_path/'source.mp4'
    source.write_bytes(b'synthetic source bytes')
    segments = [dict(start=index*2, end=index*2+2, text='Bonds are stable.') for index in range(40)]
    segments[1]['text'] = 'Oil is $115 per barrel.'
    translations = ['债券稳定。']*40
    translations[1] = '油价为每桶1150亿美元。'
    history = [dict(strategy='isolated_source_repair', executed=True,
                    segment_numbers=[2], repair_round=repair_round)]
    report = build_sparse_quality_report(segments, translations, repair_history=history)
    assert report['status'] == 'accepted_with_warnings'
    bindings = dict(input_sha256=digest(source), asr_sha256=fingerprint(segments),
                    contract_sha256=fingerprint(dict(target_lang='zh-CN')))
    case = save_bad_case(tmp_path/'bad_cases', dict(
        **bindings, candidate_sha256=report['candidate_sha256'], summary_sha256=report['summary_sha256'],
        source_segments=segments, translations=translations, vocabs=[{}]*40,
        context_text='', repair_history=history, report=report))
    warning = dict(status=report['status'], candidate_sha256=report['candidate_sha256'],
                   summary_sha256=report['summary_sha256'], report=report, bad_case=case)
    translated = [dict(segment, zh_text=text, vocab={}) for segment, text in zip(segments, translations)]
    assert validate_quality_warning(warning, segments=translated, **bindings) == warning
    assert Path(case['path']).is_file()
    return warning


def _transport(monkeypatch, *results):
    calls = []
    pending = iter(results)

    def send(**kwargs):
        calls.append(kwargs)
        result = next(pending)
        if isinstance(result, BaseException):
            raise result
        return result

    monkeypatch.setattr(pipeline, 'send_telegram_text', send)
    return calls


def test_drain_uses_explicit_p1_event_and_candidate_problem_identity(tmp_path, monkeypatch):
    db, warning = _database(tmp_path), _warning(tmp_path)
    row = db.enqueue_subtitle_quality_notification('examplevideo', 0, warning)
    calls = _transport(monkeypatch, TelegramDeliveryResult(state='ACCEPTED', message_id='902'))

    assert _manager(db).drain_subtitle_quality_notifications() == 1

    assert len(calls) == 1
    sent = calls[0]
    assert sent['event_type'] == EVENT_TYPE == 'pipeline.subtitle_quality_warning'
    assert sent['priority'] == 'P1'
    assert sent['dedupe_key'] == warning_dedupe_key('examplevideo', 0, warning)
    assert warning['candidate_sha256'] in sent['dedupe_key']
    assert warning['summary_sha256'] in sent['dedupe_key']
    assert sent['db'] is db and sent['timeout_seconds'] == 10
    assert '第2段 00:02–00:04' in sent['text']
    assert '不代表平台已发布' in sent['text']
    stored = db.get_subtitle_quality_notification(row['id'])
    assert stored['state'] == 'ACCEPTED' and stored['telegram_message_id'] == '902'
    assert db.get_video_by_youtube_id('examplevideo')['status'] == 'PENDING'


def test_failed_delivery_backs_off_then_survives_restart_without_repeat_after_acceptance(tmp_path, monkeypatch):
    db, warning = _database(tmp_path), _warning(tmp_path)
    queued = db.enqueue_subtitle_quality_notification('examplevideo', 0, warning)
    calls = _transport(monkeypatch, TelegramDeliveryResult(state='FAILED', error_kind='HTTP_503'),
                       TelegramDeliveryResult(state='ACCEPTED', message_id='903'))
    assert _manager(db).drain_subtitle_quality_notifications() == 0
    state = db.get_subtitle_quality_notification(queued['id'])
    assert state['state'] == 'PENDING' and state['last_delivery_state'] == 'FAILED'
    assert state['attempts'] == 1 and state['next_attempt_at'] == 1300

    restarted = _ClockedDatabase(db.db_path, now=1299)
    manager = _manager(restarted)
    assert manager.drain_subtitle_quality_notifications() == 0
    assert len(calls) == 1
    restarted.now = 1300
    assert manager.drain_subtitle_quality_notifications() == 1
    state = restarted.get_subtitle_quality_notification(queued['id'])
    assert state['state'] == 'ACCEPTED' and state['attempts'] == 2
    assert state['telegram_message_id'] == '903'

    final = _ClockedDatabase(db.db_path, now=1000+20*365*86400)
    assert final.enqueue_subtitle_quality_notification('examplevideo', 0, warning)['id'] == queued['id']
    assert _manager(final).drain_subtitle_quality_notifications() == 0
    assert len(calls) == 2
    assert db.get_video_by_youtube_id('examplevideo')['status'] == 'PENDING'


@pytest.mark.parametrize('result', [
    TelegramDeliveryResult(state='UNKNOWN', error_kind='ReadTimeout'),
    TelegramDeliveryResult(state='ACCEPTED'),
    RuntimeError('synthetic transport failure'),
])
def test_unknown_missing_message_id_or_transport_exception_never_becomes_accepted(tmp_path, monkeypatch, result):
    db, warning = _database(tmp_path), _warning(tmp_path)
    queued = db.enqueue_subtitle_quality_notification('examplevideo', 0, warning)
    calls = _transport(monkeypatch, result)

    assert _manager(db).drain_subtitle_quality_notifications() == 0

    state = db.get_subtitle_quality_notification(queued['id'])
    assert state['state'] == 'PENDING' and state['last_delivery_state'] == 'UNKNOWN'
    assert state['telegram_message_id'] is None and state['next_attempt_at'] == 1300
    assert len(calls) == 1
    assert db.get_video_by_youtube_id('examplevideo')['status'] == 'PENDING'


def test_same_video_new_problem_summary_gets_new_event_after_old_delivery(tmp_path, monkeypatch):
    db = _database(tmp_path)
    first, changed = _warning(tmp_path), _warning(tmp_path, repair_round=2)
    assert first['candidate_sha256'] == changed['candidate_sha256']
    assert first['summary_sha256'] != changed['summary_sha256']
    calls = _transport(monkeypatch, TelegramDeliveryResult(state='ACCEPTED', message_id='904'),
                       TelegramDeliveryResult(state='ACCEPTED', message_id='905'))
    first_row = db.enqueue_subtitle_quality_notification('examplevideo', 0, first)
    assert _manager(db).drain_subtitle_quality_notifications() == 1
    assert db.enqueue_subtitle_quality_notification('examplevideo', 0, first)['id'] == first_row['id']
    next_row = db.enqueue_subtitle_quality_notification('examplevideo', 0, changed)
    assert next_row['id'] != first_row['id']
    assert _manager(db).drain_subtitle_quality_notifications() == 1
    assert calls[0]['dedupe_key'] != calls[1]['dedupe_key']
    assert len(db.list_subtitle_quality_notifications(state='ACCEPTED')) == 2
    assert db.get_video_by_youtube_id('examplevideo')['status'] == 'PENDING'
