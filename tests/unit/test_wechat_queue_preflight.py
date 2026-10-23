"""复现待冷却互动阻塞新发布的预检死锁，使用真实账户记录和 SQLite。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-24 | Codex | 验证新发布按既有优先级准入、同类 FIFO、恢复预留和防重发边界。 |
"""
import hashlib
import json
import pytest
from video_processing.core import wechat_request_guard as module
from video_processing.core.wechat_account_schedule import evaluate
from video_processing.core.wechat_request_guard import WeChatRequestGuard, WeChatRequestDeferred


@pytest.fixture
def account(tmp_path, monkeypatch):
    monkeypatch.setattr(type(module.settings), 'default_output_dir', property(lambda _: tmp_path))
    monkeypatch.setattr(module.settings, 'wechat_scheduler_policy_path', tmp_path / 'policy.json')
    monkeypatch.setattr(module.settings, 'wechat_account_scheduler_enabled', True)
    monkeypatch.setattr(module.settings, 'wechat_scheduler_priority_video', '')
    monkeypatch.setattr(module.settings, 'wechat_scheduler_daily_limit', 20)
    monkeypatch.setattr(module.settings, 'wechat_publishing_paused', False)
    now = 1000000.0
    monkeypatch.setattr(module.time, 'time', lambda: now)
    guard = WeChatRequestGuard(tmp_path / 'wechat_state.json')
    return guard, now


def queued(purpose, task, now):
    return dict(key=hashlib.sha256((purpose + '\n' + task).encode()).hexdigest(),
                purpose=purpose, task=task, at=now-100, seen=now)


def waiting_interaction(guard, now, purposes):
    row = guard.snapshot()
    row['schedule'] = dict(sessions=[], queue=[queued(p, f'old-{i}', now) for i, p in enumerate(purposes)],
                           publications={}, last_interaction_at=now-3600)
    guard.path.write_text(json.dumps(row))
    return row


@pytest.mark.parametrize('purposes', [('评论',), ('回复',), ('回复', '评论', '评论')])
def test_new_publish_precheck_agrees_with_admission_and_keeps_waiting_interactions(account, purposes):
    guard, now = account
    row = waiting_interaction(guard, now, purposes)
    original = guard.path.read_bytes()
    assert guard.evaluate(task='new-video')['allowed']
    assert guard.path.read_bytes() == original and not guard.audit_path.exists()
    assert not guard.evaluate(purpose=purposes[0], task='old-0')['allowed']
    guard.admission('发布', 'new-video')
    guard.start_session('发布')
    after = guard.snapshot()['schedule']
    assert after['queue'] == row['schedule']['queue']
    assert [s['task'] for s in after['sessions']] == ['new-video']


def test_existing_publish_fifo_still_blocks_new_publish_and_interactions(account):
    guard, now = account
    row = waiting_interaction(guard, now, ['评论'])
    row['schedule']['queue'].append(queued('发布', 'first-video', now))
    for purpose, task in [('发布', 'new-video'), ('评论', 'new-comment')]:
        codes = {b['code'] for b in evaluate(row, now, purpose, task)['blockers']}
        assert 'QUEUE_ORDER' in codes
    assert evaluate(row, now, task='first-video')['allowed']


def test_recovery_reserved_target_keeps_precedence_over_new_publish(account):
    guard, now = account
    row = waiting_interaction(guard, now, ['评论'])
    row['schedule']['recovery_priority'] = [dict(task='reserved', expires_at=now+1800)]
    assert 'RECOVERY_RESERVED' in {b['code'] for b in evaluate(row, now, task='new-video')['blockers']}
    assert evaluate(row, now, task='reserved')['allowed']


def test_priority_does_not_bypass_quota_or_submission_evidence(account):
    guard, now = account
    row = waiting_interaction(guard, now, ['评论'])
    row['schedule']['sessions'] = [dict(at=now-5000+i, purpose='发布', task=f's{i}') for i in range(20)]
    assert 'QUOTA_24H' in {b['code'] for b in evaluate(row, now, task='new-video')['blockers']}
    row['schedule']['sessions'] = []
    row['schedule']['submit_intents'] = {'new-video': {}}
    assert 'SUBMISSION_PROTECTED' in {b['code'] for b in evaluate(row, now, task='/output/new-video_vertical.mp4')['blockers']}


def test_real_ready_worker_crosses_precheck_while_interactions_wait(account, tmp_path, monkeypatch):
    from video_processing.pipeline_manager import PipelineManager
    from scripts.run_ready_publications import dispatch_once
    guard, now = account
    waiting_interaction(guard, now, ['回复', '评论'])
    manager = PipelineManager(str(tmp_path / 'pipeline.db'))
    manager._OUT_DIR = tmp_path
    manager.db.add_video('new-video', '已完成候选', 'channel', score=86)
    manager.db.mark_video_ready_for_publication('new-video')
    (tmp_path / 'new-video_title.txt').write_text('标题')
    (tmp_path / 'new-video_copy.txt').write_text('文案')
    monkeypatch.setattr(manager, '_prepared_submission_checkpoint_error', lambda _: None)
    monkeypatch.setattr(manager, '_check_censorship', lambda *a, **kw: False)
    sent = []
    monkeypatch.setattr(manager, '_publish_prepared_assets', lambda video, *args: sent.append(video['youtube_id']))
    original = guard.path.read_bytes()
    assert dispatch_once(manager) == 1
    assert sent == ['new-video']
    assert manager.db.get_video_by_youtube_id('new-video')['status'] == 'PUBLISH_PRECHECK'
    assert guard.path.read_bytes() == original
