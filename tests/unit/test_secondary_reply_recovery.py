"""策略迁移、真实并发保护、扫描公平性与维护等待的合成回归。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| reply-recovery-v1 | 2026-10-25 | Codex | 真实临时配置仓库/SQLite/HTTP 验证，不接触平台或真实评论。 |
"""
import copy
import datetime as dt
import json
import re
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from config.settings import settings
from video_processing.core.maintenance import gate, MaintenanceDenied
from video_processing.db.database import PipelineDB
from video_processing.interaction.secondary_reply_runner import run_secondary_reply_tick
from video_processing.utils import runtime_configuration as runtime
from video_processing.utils.secondary_reply_policy import (
    PolicyConflict, policy_view, save_policy, sync_secondary_reply_settings,
)
from web.secondary_reply_settings import create_secondary_reply_settings_router
from tests.unit.test_runtime_configuration import configured, active, save, ORIGIN
from tests.unit.test_secondary_reply_m35_runner import _seed_published_post, TEST_ACCT


@pytest.fixture
def migrated(configured, tmp_path, monkeypatch):
    first, db = configured
    path = tmp_path / 'legacy-reply.json'
    legacy = dict(schema_version=1, window_start_shanghai='05:30', window_end_shanghai='21:00',
                  min_interval_seconds=3600, hourly_quota=10, max_per_video=1, approval_mode='hybrid_auto')
    path.write_text(json.dumps(legacy))
    monkeypatch.setattr(settings, 'wechat_reply_policy_path', path)
    monkeypatch.setattr(settings, 'dashboard_port', 9100)
    return first, db, path


def test_migrated_save_effective_readback_and_no_legacy_or_counter_reset(migrated):
    first, _, path = migrated
    old_bytes = path.read_bytes()
    view = policy_view(path)
    assert (view['config']['min_interval_seconds'], view['config']['hourly_quota'], view['config']['max_per_video']) == (60, 50, 20)
    candidate = dict(view['config'], hourly_quota=49, window_start_shanghai='06:00')
    save_policy(path, candidate, view['digest'], expected_revision=view['revision'])
    current = runtime.snapshot(fresh=True)
    assert current.revision != first.revision
    assert policy_view(path)['config'] == candidate
    assert sync_secondary_reply_settings()['hourly_quota'] == settings.wechat_reply_hourly_quota == 49
    assert path.read_bytes() == old_bytes
    before, after = first.domains(), current.domains()
    for operation in ('publish', 'first_comment', 'comment_scan', 'post_match', 'keepalive'):
        assert before['wechat_operations']['operations'][operation] == after['wechat_operations']['operations'][operation]
    assert after['interaction_controls']['automatic_replies_enabled'] is False


def test_migrated_concurrent_saves_one_winner_and_cross_page_cas(migrated):
    first, _, path = migrated
    view = policy_view(path)
    def attempt(quota):
        try:
            save_policy(path, dict(view['config'], hourly_quota=quota), view['digest'], expected_revision=view['revision'])
            return 'saved'
        except PolicyConflict:
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(attempt, (48, 49))) == ['conflict', 'saved']
    view = policy_view(path)
    domains = runtime.snapshot(fresh=True).domains()
    domains['observability']['wait_notice_cooldown_seconds'] = 7200
    save(domains, view['revision'], 'other_page_000000000001')
    with pytest.raises(PolicyConflict):
        save_policy(path, view['config'], view['digest'], expected_revision=view['revision'])


@pytest.mark.parametrize('change', [dict(hourly_quota=51), dict(min_interval_seconds=0),
                                  dict(window_start_shanghai='00:00', window_end_shanghai='24:00')])
def test_migrated_save_does_not_widen_approved_bounds(migrated, change):
    first, _, path = migrated
    view = policy_view(path)
    with pytest.raises(ValueError):
        save_policy(path, dict(view['config'], **change), view['digest'], expected_revision=view['revision'])
    assert runtime.snapshot(fresh=True).revision == first.revision


def test_strategy_http_auth_success_readback_and_real_conflict(migrated):
    _, db, path = migrated
    app = FastAPI()
    # 通过真实 Dashboard 中间件回归迁移入口，不能仅测试绕开它的独立路由。
    from web.app import reject_untrusted_browser_origins
    app.middleware('http')(reject_untrusted_browser_origins)
    app.include_router(create_secondary_reply_settings_router(active=path, access_db=db))
    with TestClient(app, base_url=ORIGIN, client=('127.0.0.1', 50000)) as client:
        assert client.get('/api/secondary-reply-settings').status_code == 403
        page = client.get('/secondary-reply-settings')
        assert page.status_code == 200
        token = re.search(r'name="runtime-csrf" content="([a-f0-9]+)"', page.text).group(1)
        client.headers.update({'Origin': ORIGIN, 'X-Runtime-CSRF': token})
        view = client.get('/api/secondary-reply-settings').json()
        body = dict(config=dict(view['config'], hourly_quota=49), expected_digest=view['digest'], expected_revision=view['revision'])
        assert client.put('/api/secondary-reply-settings', json=body, headers={'X-Runtime-CSRF':'invalid'}).status_code == 403
        response = client.put('/api/secondary-reply-settings', json=body)
        assert response.status_code == 200, response.text
        assert client.get('/api/secondary-reply-settings').json() == response.json()
        assert response.json()['config']['hourly_quota'] == 49
        assert client.put('/api/secondary-reply-settings', json=body).status_code == 409
        body = dict(config=dict(response.json()['config'], hourly_quota=51), expected_digest=response.json()['digest'], expected_revision=response.json()['revision'])
        assert client.put('/api/secondary-reply-settings', json=body).status_code == 422


def test_due_scan_rotates_older_posts_between_hourly_batches(tmp_path):
    db = PipelineDB(str(tmp_path / 'scan.db'))
    now = dt.datetime(2026, 10, 25, 0, tzinfo=dt.timezone.utc)
    posts = ['export/fair-' + str(i) for i in range(12)]
    for i, post in enumerate(posts):
        _seed_published_post(db, post, 'fair-' + str(i))
        with db.get_connection() as conn:
            published = now - dt.timedelta(hours=12 - i)
            conn.execute('UPDATE wechat_publications SET created_at=? WHERE platform_post_id=?', (published.strftime('%Y-%m-%d %H:%M:%S'), post))
        db.record_comment_scan_state(account_key=TEST_ACCT, platform_post_id=post, top_level_status='COMPLETE',
            observed_comment_count=0, complete=True, published_at_utc=published, now_utc=now-dt.timedelta(hours=13-i))
    first = db.get_due_comment_scan_posts(account_key=TEST_ACCT, limit=5, now_utc=now)
    assert [row['platform_post_id'] for row in first] == posts[:5]
    for row in first:
        db.record_comment_scan_state(account_key=TEST_ACCT, platform_post_id=row['platform_post_id'],
            top_level_status='COMPLETE', observed_comment_count=0, complete=True,
            published_at_utc=now-dt.timedelta(hours=1), now_utc=now)
    second = db.get_due_comment_scan_posts(account_key=TEST_ACCT, limit=5, now_utc=now+dt.timedelta(hours=1))
    assert [row['platform_post_id'] for row in second] == posts[5:10]
    # 新作品仍有首次扫描资格，不因轮转而遗漏。
    _seed_published_post(db, 'export/new', 'fair-new')
    assert db.get_due_comment_scan_posts(account_key=TEST_ACCT, limit=1, now_utc=now)[0]['platform_post_id'] == 'export/new'


def test_tick_waits_during_maintenance_without_touching_database_or_platform():
    gate().enter('合成维护等待')
    result = run_secondary_reply_tick(None, platform=None)
    assert result == dict(ok=True, status='DEFERRED_MAINTENANCE', reason='MAINTENANCE')


def test_tick_maintenance_race_preserves_completed_receipts(monkeypatch):
    from video_processing.interaction import secondary_reply_runner as runner
    def race(db, *, _progress, **kwargs):
        _progress['submitted'] = [dict(task_id=23, status='VERIFIED', platform_reply_comment_id='native-id')]
        raise MaintenanceDenied()
    monkeypatch.setattr(runner, '_run_secondary_reply_tick', race)
    result = run_secondary_reply_tick(None, platform=None)
    assert result['status'] == 'DEFERRED_MAINTENANCE'
    assert result['submitted'][0]['platform_reply_comment_id'] == 'native-id'
