"""维护排空是真实控制结果；不得继续领取、伪装完成或吞掉真实失败。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-01 | Codex | 实际维护闸门验证单片结束后的阶段边界、巡航状态及 CLI 返回码。 |
"""
import fcntl
import json
from types import SimpleNamespace

import pytest

from config.settings import settings
from video_processing.core.maintenance import MaintenanceDenied
from video_processing.pipeline_manager import PipelineManager
import scripts.run_publication_window as runner


def test_daily_stops_after_drained_video_before_health_or_deferred_work(isolated_running_maintenance, monkeypatch):
    calls = []
    monkeypatch.setattr(settings, 'enable_douyin_browser_publishing', False)
    monkeypatch.setattr(settings, 'enable_kuaishou_browser_publishing', False)
    monkeypatch.setattr(settings, 'wechat_publishing_paused', False)

    class Daily:
        db = SimpleNamespace(reconcile_pending_ghost_tasks=lambda: 0,
                             cleanup_expired_waitlist_videos=lambda **kw: 0)
        def reconcile_wechat_under_review(self): return 0
        def score_pending_videos(self): calls.append('score')
        def process_high_score_videos(self, **kw):
            calls.append('video_completed')
            isolated_running_maintenance.enter('actual video drained')
        def _check_wechat_delivery_health(self): calls.append('health')
        def recover_deferred_wechat_publications(self): calls.append('deferred'); return 0
        def _dispatch_wechat_interaction_worker(self, **kw): calls.append('interaction')
        def drain_pending_review_notifications(self, **kw): calls.append('notification')
        def drain_subtitle_quality_notifications(self): calls.append('subtitle_notification')
        def wait_for_review_notifications(self, **kw): calls.append('wait')

    with pytest.raises(MaintenanceDenied):
        PipelineManager._run_daily_job_unlocked(Daily())
    assert calls == ['score', 'video_completed']
    assert isolated_running_maintenance.status()['active'] == []


@pytest.mark.parametrize('maintenance', [True, False])
def test_runner_records_drain_only_for_actual_maintenance(tmp_path, monkeypatch, isolated_running_maintenance, maintenance):
    monkeypatch.setattr(runner, 'LOCK_PATH', tmp_path / 'runner.lock')
    monkeypatch.setattr(runner, 'RUN_STATUS_PATH', tmp_path / 'status.json')
    class Manager:
        def run_daily_job(self):
            if maintenance:
                isolated_running_maintenance.enter('draining completed video')
            raise MaintenanceDenied()
    monkeypatch.setattr(runner, 'PipelineManager', lambda **kw: Manager())
    if maintenance:
        assert runner.run_publication_window() == 0
        status = json.loads(runner.RUN_STATUS_PATH.read_text())
        assert status['state'] == 'DRAINED'
        assert status['reason'] == 'MAINTENANCE'
        assert 'error' not in status
    else:
        with pytest.raises(MaintenanceDenied): runner.run_publication_window()
        assert json.loads(runner.RUN_STATUS_PATH.read_text())['state'] == 'FAILED'
    with runner.LOCK_PATH.open('a+') as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


@pytest.mark.parametrize('maintenance', [True, False])
def test_cli_treats_only_closed_gate_as_normal_deferral(monkeypatch, isolated_running_maintenance, maintenance):
    if maintenance: isolated_running_maintenance.enter('no new work')
    def denied(): raise MaintenanceDenied()
    monkeypatch.setattr(runner, 'main', denied)
    if maintenance:
        assert runner.cli_main() == 0
    else:
        with pytest.raises(MaintenanceDenied): runner.cli_main()


def test_cli_preserves_real_business_exception(monkeypatch):
    def broken(): raise ValueError('real business failure')
    monkeypatch.setattr(runner, 'main', broken)
    with pytest.raises(ValueError, match='real business failure'):
        runner.cli_main()
