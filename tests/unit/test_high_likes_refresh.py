"""刷新回执、真实 DAL 去重、互斥及维护中断；外部搜索使用隔离样本。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-25 | Codex | 验证本次新增、零新增原因与重启恢复提示 |
"""
from datetime import datetime
import json
import subprocess
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from scripts import monitor_channels as monitor
from video_processing.core.maintenance import MaintenanceDenied, gate
from video_processing.core.task_lease import read_lease_owner
from video_processing.db import PipelineDB
from web import app as web_app
from web.high_likes_refresh import HighLikesRefresh, result_message


def test_collector_counts_only_actual_inserts_and_preserves_discovery(tmp_path, monkeypatch):
    db = PipelineDB(tmp_path / 'videos.db')
    today = datetime.now().strftime('%Y%m%d')
    def line(yid, views=2000, date=today):
        return f'{yid}|||Economic research|||90|||{views}|||120|||{date}|||channel|||Education'
    db.add_video('existing-id', 'Existing', 'channel', score=80)
    db.add_to_blacklist('blocked-id')
    output = '\n'.join([line('new-id'), line('existing-id'), line('blocked-id'),
                        line('low-id', 500), line('old-id', date='20200101'),
                        line('missing-id', 'NA'), 'malformed'])
    monkeypatch.setattr(monitor, 'get_discovery_keywords', lambda: ['sample'])
    monkeypatch.setattr(monitor, 'run_youtube_metadata', lambda *a, **k: SimpleNamespace(returncode=0, stdout=output))
    monkeypatch.setattr(monitor, '_translate_title_or_source', lambda yid, title: title)
    checkpoints = []
    report = monitor.discover_high_like_videos(db, progress=checkpoints.append)
    assert report == dict(added=1, duplicates=1, blocked=1, outdated=1, low_views=1,
                          invalid=2, candidates=7, searches=1, completed=1, failed=0, timeouts=0)
    assert checkpoints[-1] == report
    assert any(item['added'] == 1 for item in checkpoints)
    new = db.get_video_by_youtube_id('new-id')
    assert (new['source'], new['score'], new['status']) == ('DISCOVERY', 0, 'PENDING')
    assert db.get_paginated_videos('high_likes')[1] == 1
    assert db.get_paginated_videos('waitlist')[1] == 0
    assert db.get_video_by_youtube_id('existing-id')['score'] == 80
    repeated = monitor.discover_high_like_videos(db)
    assert repeated['added'] == 0 and repeated['duplicates'] == 2


def test_collector_distinguishes_empty_failure_and_timeout(monkeypatch):
    monkeypatch.setattr(monitor, 'get_discovery_keywords', lambda: ['empty', 'failed', 'timeout'])
    def search(cmd, **kwargs):
        if 'ytsearch10:timeout' in cmd:
            raise subprocess.TimeoutExpired(cmd, 180)
        return SimpleNamespace(returncode=1 if 'ytsearch10:failed' in cmd else 0, stdout='')
    monkeypatch.setattr(monitor, 'run_youtube_metadata', search)
    report = monitor.discover_high_like_videos(None)
    assert (report['searches'], report['completed'], report['failed'], report['timeouts']) == (3, 3, 1, 1)
    assert report['added'] == report['candidates'] == 0


@pytest.mark.parametrize('report,expected', [
    ({'duplicates': 3}, '已有记录 3 条'),
    ({'blocked': 2}, '入库保护规则排除 2 条'),
    ({'outdated': 1}, '超出最近 3 天'),
    ({'low_views': 4}, '观看量未超过 500'),
    ({'invalid': 2}, '元数据不完整或无法解析'),
    ({'failed': 1}, '搜索或采集失败 1 组'),
    ({'timeouts': 2}, '搜索超时 2 组'),
    ({'searches': 1}, '未返回符合采集条件的视频'),
    ({}, '没有可执行的搜索词'),
])
def test_zero_insert_explains_reason_and_destination(report, expected):
    message = result_message(dict(outcome='complete', report=report))
    assert '新增 0 条' in message and expected in message
    assert '素材进入「近期高互动」' in message and '不进入「待筛选」' in message
    assert '当前筛选' in message


@pytest.mark.parametrize('report,outcome', [
    ({'added': 2, 'completed': 1}, 'complete'),
    ({'added': 1, 'completed': 3, 'failed': 1, 'timeouts': 1}, 'partial'),
    ({'added': 0, 'completed': 2, 'failed': 1, 'timeouts': 1}, 'error'),
])
def test_receipt_survives_reload_and_blocks_duplicate_start(tmp_path, report, outcome):
    path = tmp_path / 'refresh.json'
    service = HighLikesRefresh(path)
    queued = []
    def collect(progress):
        progress(report)
        assert service.status()['running']
        return report
    started = service.start(collect, lambda target, **kw: queued.append(target))
    assert started['started'] and service.status()['running']
    assert not service.start(collect, lambda *a, **k: pytest.fail('duplicate dispatch'))['started']
    queued.pop()()
    reloaded = HighLikesRefresh(path).status()
    assert not reloaded['running']
    assert reloaded['result']['run_id'] == started['run_id']
    assert reloaded['result']['outcome'] == outcome
    assert f"新增 {report['added']} 条" in reloaded['result']['message']
    assert reloaded['result']['report'] == report


def test_maintenance_race_records_interruption_and_releases_lease(tmp_path):
    service = HighLikesRefresh(tmp_path / 'refresh.json')
    control = gate()
    queued = []
    def dispatch(target, **kw):
        assert kw['waiting'] is True
        ticket = control._acquire(kw['role'], kw['object_key'])
        def deferred():
            try:
                with ticket.bind():
                    target()
            finally:
                ticket.close()
        queued.append(deferred)
    service.start(lambda progress: pytest.fail('maintenance must prevent collection'), dispatch)
    control.enter('test interruption')
    queued.pop()()
    result = service.status()
    assert not result['running'] and not read_lease_owner(service.lock_path)
    assert result['result']['outcome'] == 'interrupted'
    assert '最终新增数量尚未核实' in result['result']['message']


def test_partial_progress_kept_on_unexpected_failure(tmp_path):
    service = HighLikesRefresh(tmp_path / 'refresh.json')
    def collect(progress):
        progress({'added': 2})
        raise RuntimeError('sample failure')
    service.start(collect, lambda target, **kw: target())
    status = service.status()
    assert not status['running']
    assert status['result']['outcome'] == 'error'
    assert '已新增 2 条' in status['result']['message']
    assert '采集发生异常' in status['result']['message']


def test_dispatch_denial_releases_lease(tmp_path):
    service = HighLikesRefresh(tmp_path / 'refresh.json')
    def denied(*args, **kwargs):
        raise MaintenanceDenied()
    with pytest.raises(MaintenanceDenied):
        service.start(lambda progress: {}, denied)
    assert not read_lease_owner(service.lock_path)
    assert service.status()['result']['outcome'] == 'interrupted'
    assert service.start(lambda progress: {'added': 0}, lambda target, **kw: target())['started']


def test_restart_does_not_report_incomplete_collection_as_success(tmp_path):
    path = tmp_path / 'refresh.json'
    path.write_text(json.dumps(dict(run_id='previous', outcome='running', report={'added': 3})))
    before = path.read_bytes()
    result = HighLikesRefresh(path).status()
    assert not result['running']
    assert result['result']['outcome'] == 'interrupted'
    assert '已记录新增 3 条' in result['result']['message']
    assert path.read_bytes() == before  # GET 不写回或启动采集。


@pytest.mark.parametrize('data', ['not-json', '[]', '{}'])
def test_unreadable_receipt_does_not_claim_zero(tmp_path, data):
    path = tmp_path / 'refresh.json'
    path.write_text(data)
    message = HighLikesRefresh(path).status()['result']['message']
    assert '读取失败' in message and '新增数量尚未核实' in message
    assert '新增 0' not in message


def test_api_returns_receipt_and_maintenance_does_not_dispatch(tmp_path, monkeypatch):
    service = HighLikesRefresh(tmp_path / 'refresh.json')
    monkeypatch.setattr(web_app, '_high_likes_refresh', service)
    monkeypatch.setattr(web_app, 'spawn_admitted', lambda target, **kw: target())
    # 入口保持原 scripts 搜索路径；只替换外部采集，不替换回执逻辑。
    import sys
    monkeypatch.setitem(sys.modules, 'monitor_channels', SimpleNamespace(
        discover_high_like_videos=lambda db, progress: {'added': 4, 'completed': 1}))
    with TestClient(web_app.app) as client:
        assert client.get('/api/high-likes/status').json() == {'running': False, 'result': None}
        assert not service.path.exists()
        assert client.post('/api/high-likes/refresh').json()['started']
        result = client.get('/api/high-likes/status').json()['result']
        assert result['outcome'] == 'complete' and result['report']['added'] == 4
        assert result['destination'] == 'high_likes'
        assert '近期高互动' in result['message']
        previous = service.path.read_bytes()
        gate().enter('API test maintenance')
        assert client.post('/api/high-likes/refresh').status_code == 503
        assert service.path.read_bytes() == previous
