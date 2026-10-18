"""恢复合同：持久退避、幂等授权、提交前证据和提交后保护。"""
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from video_processing.db.database import PipelineDB
from video_processing.delivery_recovery import DeliveryRecoveryService, keyboard
from video_processing.utils.retry_policy import backoff_seconds, failure_kind
from video_processing.utils.submission_progress import write_progress, proven_pre_submit
from video_processing.utils.production_recovery import write_context, context_path, recovery_arguments, read_outcome


def save_context(request, root, provider='programmatic'):
    paths = SimpleNamespace(project_root=root, coordinator_provider=provider, codex_model='original-codex',
                            agy_model='original-agy', coordinator_timeout_seconds=120,
                            codex_home=root / 'codex-home', codex_bin=root / 'codex',
                            python_bin=root / '.venv/bin/python', notifier_script=root / 'notifier.py',
                            log_dir=root / 'output/english_world_daily', lock_dir=root / 'production.lock',
                            agy_bin=root / 'agy')
    write_context(request, paths, retry_delay_seconds=15, wait_for_lock_seconds=7,
                  excluded_youtube_ids=('dQw4w9WgXcQ',), recoverable=True)
    return paths


@pytest.mark.parametrize('has_context', [True, False])
def test_failure_notice_queues_only_verified_config(db, tmp_path, monkeypatch, has_context):
    from scripts import notify_english_world_review as notifier
    from video_processing.telegram_delivery import TelegramDeliveryResult
    request = tmp_path / 'output/english_world_daily/failure.delivery-request.json'
    request.parent.mkdir(parents=True)
    request.write_text(json.dumps({'kind': 'failure', 'failure': 'connection reset'}))
    if has_context:
        save_context(request, tmp_path)
    sent = []
    monkeypatch.setattr(notifier, '_PROJECT_ROOT', tmp_path)
    monkeypatch.setattr(notifier, 'PipelineDB', lambda: db)
    monkeypatch.setattr(notifier, 'send_text', lambda **kw: (
        sent.append(kw) or TelegramDeliveryResult(state='ACCEPTED', message_id='123')))
    monkeypatch.setattr(notifier.sys, 'argv', ['notify', '--title', 'test', '--failure', 'connection reset',
                                            '--failure-request', str(request), '--allow-production-retry'])
    assert notifier.main() == 0
    row = db.list_delivery_recoveries()[0]
    assert row['state'] == ('QUEUED' if has_context else 'WAITING')
    assert 'recover:view:' in str(sent[0]['reply_markup'])
    assert ('已安排重试' if has_context else '缺少可核验的原制作配置') in sent[0]['text']
    assert '北京时间' in sent[0]['text']


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
    save_context(request, tmp_path)
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
    save_context(request, tmp_path)
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
    from scripts import run_english_world_daily as daily
    directory = tmp_path / 'output/english_world_daily'
    directory.mkdir(parents=True)
    request = directory / 'failed.json'
    request.write_text('{"kind":"failure"}')
    save_context(request, tmp_path)
    service = DeliveryRecoveryService(db, tmp_path)
    row = service.register_production(request, detail, allow_retry=True)
    service.act(row['id'], action='retry', actor='telegram:1')
    monkeypatch.setattr(worker, 'ROOT', tmp_path)
    sent = []
    monkeypatch.setattr(worker, 'send_text', lambda **kw: sent.append(kw))

    def run(argv, **kwargs):
        # 使用真实协调器的日志/结果写入方法；外层 stdout 故意为空。
        log_path = directory / 'run_current.log'
        with log_path.open('w') as stream:
            daily._log(stream, detail)
        log_path.with_suffix('.delivery-request.json').write_text(json.dumps({'kind': 'failure', 'failure': detail}))
        daily._write_status(Path(argv[argv.index('--recovery-status-path') + 1]), 'FAILED_COORDINATOR',
                            1, 1, log_path, directory / 'response.md')
        assert '--recovery-parent-id' in argv
        assert '--force' not in argv
        assert argv[argv.index('--coordinator-provider') + 1] == 'programmatic'
        assert argv[argv.index('--codex-model') + 1] == 'original-codex'
        assert argv[argv.index('--agy-model') + 1] == 'original-agy'
        assert argv[argv.index('--exclude-youtube-id') + 1] == 'dQw4w9WgXcQ'
        return type('Result', (), {'returncode': 1})()

    monkeypatch.setattr(worker, 'run_admitted', run)
    worker.execute(db)
    finished = db.get_delivery_recovery(row['id'])
    assert finished['state'] == expected
    assert len(sent) == 2
    if expected == 'QUEUED':
        delay = (datetime.fromisoformat(finished['next_attempt_at']) - datetime.fromisoformat(finished['updated_at'])).total_seconds()
        assert 480 <= delay <= 600
    else:
        assert finished['next_attempt_at'] is None
    assert list((tmp_path / 'output').glob('recovery_*.log'))[0].read_text() == ''
    assert detail in sent[-1]['text']


def production(db, tmp_path):
    directory = tmp_path / 'output/english_world_daily'
    directory.mkdir(parents=True, exist_ok=True)
    request = directory / 'original.delivery-request.json'
    request.write_text('{"kind":"failure","failure":"connection reset"}')
    save_context(request, tmp_path)
    service = DeliveryRecoveryService(db, tmp_path)
    return service, service.register_production(request, 'connection reset', allow_retry=True)


def test_pause_resume_preserves_due_time_budget_and_blocks_claim(db, tmp_path):
    service, row = production(db, tmp_path)
    queued = db.queue_delivery_recovery(row['id'], actor='AUTO_TRANSIENT', action='retry', delay_seconds=300)
    assert 'recover:hold:' in json.dumps(keyboard(queued))
    service.act(row['id'], action='hold', actor='telegram:1')
    held = db.get_delivery_recovery(row['id'])
    assert held['state'] == 'HELD'
    assert held['next_attempt_at'] == queued['next_attempt_at']
    assert db.claim_delivery_recovery() is None
    service.act(row['id'], action='retry', actor='telegram:1')
    resumed = db.get_delivery_recovery(row['id'])
    assert resumed['state'] == 'QUEUED'
    assert resumed['attempts'] == 0
    assert resumed['next_attempt_at'] == queued['next_attempt_at']
    with pytest.raises(ValueError):
        service.act(row['id'], action='retry', actor='telegram:1')


@pytest.mark.parametrize('retry_delay,expected', [(600, 'HELD'), (None, 'DONE')])
def test_pause_in_flight_records_result_before_stopping(db, tmp_path, retry_delay, expected):
    service, row = production(db, tmp_path)
    service.act(row['id'], action='retry', actor='telegram:1')
    db.claim_delivery_recovery()
    view = service.act(row['id'], action='hold', actor='telegram:1')
    assert '本轮结束后暂停' in view['text']
    assert db.claim_delivery_recovery() is None
    finished = db.finish_delivery_recovery(row['id'], result='本轮结果已保存', retry_delay=retry_delay)
    assert finished['state'] == expected
    assert '本轮结果已保存' in service.view(row['id'])['text']
    if retry_delay:
        service.act(row['id'], action='retry', actor='telegram:1')
        assert db.get_delivery_recovery(row['id'])['attempts'] == 1
        assert db.get_delivery_recovery(row['id'])['next_attempt_at'] == finished['next_attempt_at']


def test_unknown_pause_resume_never_requeues_publication(db, tmp_path):
    service, row = unknown(db, tmp_path)
    service.act(row['id'], action='hold', actor='telegram:1')
    assert 'recover:resume:' in json.dumps(service.view(row['id'])['reply_markup'])
    service.act(row['id'], action='resume', actor='telegram:1')
    assert db.get_delivery_recovery(row['id'])['state'] == 'WAITING'
    assert db.get_wechat_publication('4hmUTiegBrk')['state'] == 'UNCERTAIN'
    assert db.get_video_by_youtube_id('4hmUTiegBrk')['status'] == 'UNCERTAIN'


@pytest.mark.parametrize('provider', ['programmatic', 'codex', 'agy'])
def test_recovery_configuration_round_trips_without_default_provider(tmp_path, provider):
    from scripts.run_english_world_daily import parse_args
    request = tmp_path / 'failure.json'
    save_context(request, tmp_path, provider)
    args = parse_args(recovery_arguments(context_path(request), tmp_path))
    assert args.coordinator_provider == provider
    assert args.codex_model == 'original-codex'
    assert args.agy_model == 'original-agy'
    assert args.exclude_youtube_id == ['dQw4w9WgXcQ']
    assert args.wait_for_lock_seconds == 7
    assert args.coordinator_timeout_seconds == 120
    assert not args.force


def test_legacy_or_changed_configuration_cannot_silently_use_defaults(db, tmp_path):
    service, row = production(db, tmp_path)
    context = context_path(tmp_path / 'output/english_world_daily/original.delivery-request.json')
    data = json.loads(context.read_text())
    data['options']['coordinator_provider'] = 'codex'
    context.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='配置'):
        service.act(row['id'], action='retry', actor='telegram:1')
    legacy = context.parent / 'legacy.delivery-request.json'
    legacy.write_text('{"kind":"failure"}')
    old = service.register_production(legacy, 'timeout', allow_retry=True)
    assert not json.loads(old['payload_json'])['allow_retry']
    assert 'recover:retry:' not in json.dumps(keyboard(old))
    assert '缺少可核验的原制作配置' in service.view(old['id'])['text']


@pytest.mark.parametrize('phase,kind,retryable', [
    ('FAILED_COORDINATOR', 'failure', True),
    ('REPORTED_SOURCE_ACCESS_PREFLIGHT_EXCEPTION', 'failure', True),
    ('COORDINATOR_DELIVERY_UNCERTAIN', 'failure', False),
    ('FAILED_HOST_DELIVERY', 'failure', False),
    ('FAILED_COORDINATOR', 'production', False),
])
def test_result_classification_uses_host_stage_and_request(db, tmp_path, phase, kind, retryable):
    from scripts import run_english_world_daily as daily
    directory = tmp_path / 'output/english_world_daily'
    directory.mkdir(parents=True)
    log = directory / 'run.log'
    log.write_text('connection reset')
    log.with_suffix('.delivery-request.json').write_text(json.dumps({'kind': kind, 'failure': 'connection reset'}))
    status = tmp_path / 'attempt.status.txt'
    daily._write_status(status, phase, 1, 1, log, directory / 'response.md')
    text, actual = read_outcome(status, tmp_path, 1)
    assert actual == retryable
    assert 'connection reset' in text
    with pytest.raises(ValueError, match='退出码'):
        read_outcome(status, tmp_path, 0)


@pytest.mark.asyncio
async def test_telegram_pause_resume_and_view_use_persisted_state(monkeypatch, db, tmp_path):
    from bot import telegram_bot as bot
    service, row = production(db, tmp_path)
    db.queue_delivery_recovery(row['id'], actor='AUTO_TRANSIENT', action='retry', delay_seconds=300)
    class LocalAPI:
        async def delivery_recovery_action(self, rid, *, action, actor):
            return service.act(rid, action=action, actor=actor)
    monkeypatch.setattr(bot, '_api', LocalAPI())
    monkeypatch.setattr(bot, '_check_admin', lambda _: True)
    update = MagicMock()
    update.effective_user.id = 1
    update.callback_query.answer = AsyncMock()
    update.callback_query.message.reply_text = AsyncMock()
    for action, label in [('hold', '已暂停'), ('retry', '已安排重试'), ('view', '已安排重试')]:
        update.callback_query.data = f"recover:{action}:{row['id']}"
        await bot.handle_delivery_recovery_callback(update, MagicMock())
        text = update.callback_query.message.reply_text.call_args.args[0]
        assert label in text
        assert '北京时间' in text
    with db.get_connection() as c:
        c.execute("UPDATE delivery_recoveries SET next_attempt_at=datetime('now','-1 second')")
    db.claim_delivery_recovery()
    db.finish_delivery_recovery(row['id'], result='network timeout；已保存本轮失败结果', retry_delay=600)
    await bot.handle_delivery_recovery_callback(update, MagicMock())
    assert '已保存本轮失败结果' in update.callback_query.message.reply_text.call_args.args[0]


def test_real_worker_flow_increases_waits_and_stops_at_budget(monkeypatch, db, tmp_path):
    from scripts import run_delivery_recovery as worker
    from scripts import run_english_world_daily as daily
    service, row = production(db, tmp_path)
    queued = db.queue_delivery_recovery(row['id'], actor='AUTO_TRANSIENT', action='retry',
                                       delay_seconds=backoff_seconds(1))
    def interval(record):
        return (datetime.fromisoformat(record['next_attempt_at']) - datetime.fromisoformat(record['updated_at'])).total_seconds()
    waits = [interval(queued)]
    calls, notices = [], []
    def run(argv, **kwargs):
        calls.append(argv)
        log = tmp_path / 'output/english_world_daily' / f'run_attempt_{len(calls)}.log'
        with log.open('w') as stream:
            daily._log(stream, 'connection reset')
        log.with_suffix('.delivery-request.json').write_text('{"kind":"failure","failure":"connection reset"}')
        daily._write_status(Path(argv[argv.index('--recovery-status-path') + 1]), 'FAILED_COORDINATOR',
                            1, 1, log, log.with_suffix('.md'))
        return SimpleNamespace(returncode=1)
    monkeypatch.setattr(worker, 'ROOT', tmp_path)
    monkeypatch.setattr(worker, 'run_admitted', run)
    monkeypatch.setattr(worker, 'send_text', lambda **kw: notices.append(kw))
    for attempt in range(1, 4):
        with db.get_connection() as c:
            c.execute("UPDATE delivery_recoveries SET next_attempt_at=datetime('now','-1 second')")
        worker.execute(db)
        state = db.get_delivery_recovery(row['id'])
        assert state['attempts'] == attempt
        if attempt < 3:
            assert state['state'] == 'QUEUED'
            waits.append(interval(state))
        else:
            assert state['state'] == 'DONE'
            assert state['next_attempt_at'] is None
    assert 240 <= waits[0] <= 300
    assert 480 <= waits[1] <= 600
    assert 960 <= waits[2] <= 1200
    assert waits[0] < waits[1] < waits[2]
    assert len(calls) == 3 and len(notices) == 6
    worker.execute(db)
    assert len(calls) == 3
    with pytest.raises(ValueError):
        service.act(row['id'], action='retry', actor='telegram:1')
