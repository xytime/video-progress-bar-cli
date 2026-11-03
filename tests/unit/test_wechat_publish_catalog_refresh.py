"""发布窗口内的商品目录刷新：自身优先锁不再阻断同步、新池直接用于本次匹配、占用记为跳过。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-03 | Grok Bot | 优先锁豁免仅限商品同步、过期/软过期刷新、跳过语义与默认商品联动。 |
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest
from config.settings import settings
from video_processing.core.task_lease import TaskLease
from video_processing.core.wechat_session_lock import WeChatSessionLock, WeChatSessionLockBusy, WeChatAccountDeferred
from video_processing.db.database import PipelineDB
from video_processing.utils.wechat_product_catalog import catalog_digest
from video_processing.utils.wechat_product_config import load_policy
from video_processing.utils.wechat_product_pool import promote_live_catalog
from video_processing.utils.wechat_product_task import freeze_task_product_decision
from tests.unit.test_wechat_product_content_match import AI_RECORDER, live, observation  # noqa: F401


def test_priority_exemption_only_for_catalog_sync_and_browser_mutex_kept(tmp_path):
    priority = tmp_path / 'wechat_publish_priority.lock'
    state = tmp_path / 'wechat_state.json'
    with TaskLease(priority, video='one', stage='发布前校验/上传'):
        with pytest.raises(WeChatSessionLockBusy):
            with WeChatSessionLock(state, purpose='商品同步'):
                pass
        with pytest.raises(WeChatSessionLockBusy):
            with WeChatSessionLock(state, purpose='保活', priority_held=True):
                pass
        with WeChatSessionLock(state, purpose='商品同步', priority_held=True):
            # 真实浏览器互斥仍然有效。
            with pytest.raises(WeChatSessionLockBusy):
                with WeChatSessionLock(state, purpose='发布', video='one'):
                    pass


def _sync_adding(active, doc, calls, item=None, result=None):
    def sync(policy_path, **kwargs):
        calls.append(kwargs)
        if result:
            return result
        path = active.with_name('wechat_product_catalog.json')
        fresh = deepcopy(doc)
        fresh['captured_at'] = datetime.now(timezone.utc).isoformat()
        if item:
            fresh['pages'][0]['items'].append(dict(item, stock=5, price='20', shop='合成店铺'))
            fresh['total_items'] += 1
        promote_live_catalog(fresh, observation(fresh), active, expected_catalog_digest=catalog_digest(path),
                             expected_policy_digest=load_policy(active).digest)
        return {'reason': 'CATALOG_SYNCED', 'state': 'COMPLETE'}
    return sync


@pytest.fixture
def publish_env(live, monkeypatch):
    from video_processing.utils import wechat_product_sync
    from video_processing.core import wechat_session_lock
    active, doc, config, now = live
    monkeypatch.setattr(settings, 'wechat_product_policy_path', active)
    monkeypatch.setattr(wechat_session_lock, 'current_wechat_session', lambda: None)
    active.with_name('wechat_product_matching.json').write_text(
        json.dumps(dict(config, default_products=[dict(AI_RECORDER)])))
    return active, doc, now, wechat_product_sync


def test_stale_publish_freeze_refreshes_in_priority_window_and_uses_new_pool(publish_env, tmp_path, monkeypatch):
    active, doc, now, sync_module = publish_env
    path = active.with_name('wechat_product_catalog.json')
    stale = deepcopy(doc); stale['captured_at'] = (now - timedelta(days=8)).isoformat()
    path.write_text(json.dumps(stale))
    calls = []
    monkeypatch.setattr(sync_module, 'run_catalog_sync', _sync_adding(active, doc, calls, AI_RECORDER))
    task = freeze_task_product_decision(PipelineDB(str(tmp_path/'t.sqlite')), 'new', {'video_title': 'unrelated giraffe'}, active)
    assert calls == [{'priority_held': True}]
    assert task['reason'] == 'MATCH_DEFAULT' and task['require_product']
    assert task['product_decision']['candidates'] == [AI_RECORDER]
    assert task['matching_snapshot']['pool']['ready']


def test_soft_refresh_failure_keeps_valid_pool(publish_env, tmp_path, monkeypatch):
    active, doc, now, sync_module = publish_env
    calls = []
    monkeypatch.setattr(sync_module, 'run_catalog_sync',
                        _sync_adding(active, doc, calls, result={'state': 'SKIPPED', 'reason': 'CATALOG_SYNC_WeChatSessionLockBusy'}))
    monkeypatch.setattr(settings, 'wechat_product_catalog_refresh_hours', 1)
    db = PipelineDB(str(tmp_path/'t.sqlite'))
    fresh = freeze_task_product_decision(db, 'fresh', {'video_title': 'stock market'}, active, now=now + timedelta(minutes=30))
    assert calls == [] and fresh['reason'] == 'MATCH_L1'
    aged = freeze_task_product_decision(db, 'aged', {'video_title': 'stock market'}, active, now=now + timedelta(hours=2))
    assert calls == [{'priority_held': True}] and aged['reason'] == 'MATCH_L1'
    assert aged['matching_snapshot']['sync_result']['state'] == 'SKIPPED'


def test_busy_session_is_recorded_as_skipped_without_touching_catalog(live, tmp_path, monkeypatch):
    from video_processing.utils import wechat_product_sync
    active, _, _, _ = live
    path = active.with_name('wechat_product_catalog.json'); before = path.read_bytes()
    monkeypatch.setattr(settings, 'wechat_operations_enabled', True)
    monkeypatch.setattr(type(settings), 'default_output_dir', property(lambda _: tmp_path/'attempts'))

    class Ticket:
        def start(self):
            pass

    class Gate:
        @contextmanager
        def admit(self, *args):
            yield Ticket()

    seen = []

    class BusyLock:
        def __init__(self, *args, **kwargs):
            seen.append(kwargs.get('priority_held'))

        def __enter__(self):
            raise WeChatAccountDeferred('catalog_sync 过去24小时额度已满')

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(wechat_product_sync, 'gate', lambda: Gate())
    monkeypatch.setattr(wechat_product_sync, 'current', lambda: None)
    monkeypatch.setattr(wechat_product_sync, 'WeChatSessionLock', BusyLock)
    result = wechat_product_sync.run_catalog_sync(active, priority_held=True)
    assert seen == [True]
    assert result['state'] == 'SKIPPED' and result['reason'] == 'CATALOG_SYNC_WeChatAccountDeferred'
    assert result['diagnostics']['browser']['launched'] is False and path.read_bytes() == before
