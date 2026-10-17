"""恢复合同：持久退避、幂等授权、提交前证据和提交后保护。"""
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from video_processing.db.database import PipelineDB
from video_processing.delivery_recovery import DeliveryRecoveryService, keyboard
from video_processing.utils.retry_policy import backoff_seconds, failure_kind
from video_processing.utils.submission_progress import write_progress, proven_pre_submit


@pytest.fixture
def db(tmp_path):
    return PipelineDB(str(tmp_path / 'pipeline.db'))


def unknown(db, tmp_path):
    yid = '4hmUTiegBrk'
    db.add_video(yid, 'AI regulation', 'channel', score=85)
    db.update_video_status(yid, 'UNCERTAIN')
    db.record_wechat_publication_confirmation(yid, evidence_path=None, state='UNCERTAIN', error_message='unknown')
    out = tmp_path / 'output'
    out.mkdir(exist_ok=True)
    (out / f'{yid}_vertical.mp4').write_bytes(b'bound media')
    service = DeliveryRecoveryService(db, tmp_path)
    return service, service.register_unknown(yid)


def test_bounded_exponential_jitter_retry_after_and_classification():
    for attempt, ceiling in ((1, 300), (2, 600), (3, 1200), (9, 3600)):
        assert backoff_seconds(attempt, random_value=0) == ceiling * .8
        assert backoff_seconds(attempt, random_value=1) == ceiling
    assert backoff_seconds(1, retry_after=900, random_value=0) == 900
    assert failure_kind('location ineligible; timed out') == 'PROVIDER_BLOCKED'
    assert failure_kind('ATTEMPT_BUDGET_EXHAUSTED; timeout') == 'BUDGET_EXHAUSTED'
    assert failure_kind('connection reset') == 'TRANSIENT'


def test_submit_intent_is_monotonic_and_survives_reopen(tmp_path):
    video = str(tmp_path / 'video.mp4')
    write_progress(tmp_path / 'evidence', video)
    assert proven_pre_submit(tmp_path / 'evidence', video)
    assert not proven_pre_submit(tmp_path / 'evidence', video + 'other')
    write_progress(tmp_path / 'evidence', video, submit_intent=True)
    assert not proven_pre_submit(tmp_path / 'evidence', video)
    with pytest.raises(ValueError):
        write_progress(tmp_path / 'evidence', video)


def test_receipt_overrides_pre_submit_flag(tmp_path):
    write_progress(tmp_path, 'video.mp4')
    (tmp_path / 'submission_receipt.json').write_text('{}')
    assert not proven_pre_submit(tmp_path, 'video.mp4')


def test_manual_unknown_confirmation_is_one_time_and_preserves_original(db, tmp_path):
    service, row = unknown(db, tmp_path)
    assert 'recover:ask:' in json.dumps(keyboard(row))
    # 单纯查看和打开确认卡不释放未知账本。
    service.act(row['id'], action='view', actor='telegram:1')
    assert db.get_wechat_publication('4hmUTiegBrk')['state'] == 'UNCERTAIN'
    service.act(row['id'], action='confirm', actor='telegram:1')
    assert db.get_video_by_youtube_id('4hmUTiegBrk')['status'] == 'PENDING'
    assert db.get_wechat_publication('4hmUTiegBrk') is None
    with db.get_connection() as c:
        event = c.execute("SELECT * FROM delivery_recovery_events WHERE action='operator_confirmed_not_published'").fetchone()
        assert event['actor'] == 'telegram:1'
        assert json.loads(event['payload_json'])['prior_publication']['state'] == 'UNCERTAIN'
    with pytest.raises(ValueError):
        service.act(row['id'], action='confirm', actor='telegram:1')
    service.validate_confirmed_artifacts('4hmUTiegBrk')
    (tmp_path / 'output/4hmUTiegBrk_vertical.mp4').write_bytes(b'changed after confirmation')
    with pytest.raises(ValueError, match='发布包已变化'):
        service.validate_confirmed_artifacts('4hmUTiegBrk')


def test_changed_asset_or_new_platform_id_blocks_manual_replay(db, tmp_path):
    service, row = unknown(db, tmp_path)
    asset = tmp_path / 'output/4hmUTiegBrk_vertical.mp4'
    asset.write_bytes(b'changed')
    with pytest.raises(ValueError, match='产物已变化'):
        service.act(row['id'], action='confirm', actor='telegram:1')
    asset.write_bytes(b'bound media')
    with db.get_connection() as c:
        c.execute("UPDATE wechat_publications SET platform_post_id='native-id'")
    with pytest.raises(ValueError, match='账本已经变化'):
        service.act(row['id'], action='confirm', actor='telegram:1')
    assert db.get_video_by_youtube_id('4hmUTiegBrk')['status'] == 'UNCERTAIN'


def test_persistent_due_times_cap_attempts_and_duplicate_clicks(db, tmp_path):
    directory = tmp_path / 'output/english_world_daily'
    directory.mkdir(parents=True)
    request = directory / 'run.delivery-request.json'
    request.write_text(json.dumps({'kind': 'failure', 'failure': 'connection reset'}))
    service = DeliveryRecoveryService(db, tmp_path)
    row = service.register_production(request, 'connection reset', allow_retry=True)
    assert service.register_production(request, 'connection reset', allow_retry=True)['id'] == row['id']
    service.act(row['id'], action='retry', actor='telegram:1')
    with pytest.raises(ValueError):
        service.act(row['id'], action='retry', actor='telegram:1')
    for attempt in range(1, 4):
        claimed = db.claim_delivery_recovery()
        assert claimed['attempts'] == attempt
        finished = db.finish_delivery_recovery(row['id'], result='connection reset', retry_delay=300)
        reopened = PipelineDB(db.db_path).get_delivery_recovery(row['id'])
        assert reopened['attempts'] == attempt
        if attempt < 3:
            assert finished['state'] == 'QUEUED'
            assert db.claim_delivery_recovery() is None  # 未到期不能领取
            with db.get_connection() as c:
                c.execute("UPDATE delivery_recoveries SET next_attempt_at=datetime('now','-1 second')")
        else:
            assert finished['state'] == 'DONE'


def test_pre_submit_requeue_is_bounded_persistent_and_blocks_accepted(db, tmp_path):
    db.add_video('pre-submit', 'title', 'channel', score=85)
    for attempt in range(1, 4):
        db.update_video_status('pre-submit', 'PUBLISHING')
        evidence = tmp_path / f'attempt{attempt}'
        write_progress(evidence, 'video.mp4')
        result = db.requeue_proven_pre_submit_failure('pre-submit', slice_index=0, evidence_dir=evidence, video_path='video.mp4')
        if attempt < 3:
            assert result['attempt'] == attempt
            assert db.get_video_by_youtube_id('pre-submit')['status'] == 'PENDING'
        else:
            assert result is None
    db.add_video('accepted', 'title', 'channel', score=85)
    db.update_video_status('accepted', 'PUBLISHING')
    db.record_wechat_publication_confirmation('accepted', state='UNDER_REVIEW', evidence_path='post-list.png', error_message='accepted')
    assert db.requeue_proven_pre_submit_failure('accepted', slice_index=0, evidence_dir=evidence, video_path='video.mp4') is None


@pytest.mark.asyncio
async def test_recovery_callback_checks_admin_and_confirmation_does_not_execute_early(monkeypatch):
    from bot import telegram_bot as bot
    update = MagicMock()
    update.callback_query.answer = AsyncMock()
    update.callback_query.message.reply_text = AsyncMock()
    update.callback_query.data = 'recover:ask:' + 'a' * 32
    api = MagicMock()
    api.delivery_recovery_action = AsyncMock(return_value={'text': 'evidence', 'reply_markup': {'inline_keyboard': []}})
    monkeypatch.setattr(bot, '_api', api)
    monkeypatch.setattr(bot, '_check_admin', lambda _: False)
    await bot.handle_delivery_recovery_callback(update, MagicMock())
    api.delivery_recovery_action.assert_not_called()
    monkeypatch.setattr(bot, '_check_admin', lambda _: True)
    await bot.handle_delivery_recovery_callback(update, MagicMock())
    assert api.delivery_recovery_action.call_args.kwargs['action'] == 'view'
    assert '确认' in update.callback_query.message.reply_text.call_args.args[0]


def test_expired_button_and_changed_failure_request_are_rejected(db, tmp_path):
    service, row = unknown(db, tmp_path)
    with db.get_connection() as c:
        c.execute("UPDATE delivery_recoveries SET expires_at=datetime('now','-1 second')")
    with pytest.raises(ValueError, match='过期'):
        service.act(row['id'], action='confirm', actor='telegram:1')
    directory = tmp_path / 'output/english_world_daily'
    directory.mkdir()
    request = directory / 'failed.json'
    request.write_text('{"kind":"failure"}')
    row = service.register_production(request, 'timeout', allow_retry=True)
    request.write_text('{"kind":"production"}')
    with pytest.raises(ValueError, match='记录已变化'):
        service.act(row['id'], action='retry', actor='telegram:1')


def test_recovery_api_requires_internal_token_and_rejects_browser(monkeypatch, db):
    from fastapi.testclient import TestClient
    import web.app as web
    monkeypatch.setattr(web, 'db', db)
    monkeypatch.setattr(web.settings, 'pipeline_internal_api_token', 't' * 32)
    client = TestClient(web.app)
    assert client.get('/api/delivery-recoveries').status_code == 403
    assert client.get('/api/delivery-recoveries', headers={
        'X-Pipeline-Internal-Token': 't' * 32, 'Origin': 'http://localhost'}).status_code == 403
    assert client.get('/api/delivery-recoveries', headers={
        'X-Pipeline-Internal-Token': 't' * 32}).json() == {'items': []}


@pytest.mark.parametrize('detail,expected', [('connection reset', 'QUEUED'), ('location ineligible', 'DONE')])
def test_worker_only_reschedules_transient_failure(monkeypatch, db, tmp_path, detail, expected):
    from scripts import run_delivery_recovery as worker
    directory = tmp_path / 'output/english_world_daily'
    directory.mkdir(parents=True)
    request = directory / 'failed.json'
    request.write_text('{"kind":"failure"}')
    service = DeliveryRecoveryService(db, tmp_path)
    row = service.register_production(request, detail, allow_retry=True)
    service.act(row['id'], action='retry', actor='telegram:1')
    monkeypatch.setattr(worker, 'ROOT', tmp_path)
    sent = []
    monkeypatch.setattr(worker, 'send_text', lambda **kw: sent.append(kw))

    def run(argv, **kwargs):
        kwargs['stdout'].write(detail)
        assert '--recovery-parent-id' in argv
        assert '--force' not in argv
        return type('Result', (), {'returncode': 1})()

    monkeypatch.setattr(worker, 'run_admitted', run)
    worker.execute(db)
    assert db.get_delivery_recovery(row['id'])['state'] == expected
    assert len(sent) == 2
