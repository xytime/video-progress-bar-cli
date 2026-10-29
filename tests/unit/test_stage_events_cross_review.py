"""交叉复核：新尝试尚未结束时，不能继承上一轮终态。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-29 | Codex | 固定分母重试进行中不能误计旧失败。 |
| 1.1.0 | 2026-10-29 | Codex | 编排器明确失败/复核与观测读取故障、窗口 CLI 参数验证。 |
"""
import json
from pathlib import Path
import runpy
from types import SimpleNamespace

import pytest

from video_processing.utils.stage_events import StageJournal,bind_journal,summarize_events


def test_running_new_attempt_is_pending_instead_of_previous_failed(tmp_path):
    previous=tmp_path/'previous.jsonl'
    old=StageJournal(previous,task_id='video:0',attempt_id='old')
    with bind_journal(old):
        old.close('failed')
    current=tmp_path/'current.jsonl'
    new=StageJournal(current,task_id='video:0',attempt_id='new')
    with bind_journal(new):
        new.transition('OCR')
    summary=summarize_events([previous,current],cohort=['video:0'])
    assert summary['cohort']['counts']['pending_or_unknown'] == 1
    assert summary['cohort']['counts']['failed'] == 0


@pytest.mark.parametrize('status,expected', [('FAILED', 'failed'), ('REVIEW', 'review'),
    ('LOCAL_READY', 'unknown'), ('PENDING', 'unknown'), ('PUBLISHED', 'unknown')])
def test_manager_observes_only_explicit_failure_or_review(tmp_path, monkeypatch, status, expected):
    from config.settings import settings
    from video_processing.pipeline_manager import _journal_video_execution
    monkeypatch.setattr(settings, 'enable_pipeline_stage_events', True)
    db = SimpleNamespace(get_video_by_youtube_id=lambda *a, **k: {'status': status})
    manager = SimpleNamespace(db=db, _OUT_DIR=tmp_path)
    work = _journal_video_execution(lambda self, video: 'business-result')
    assert work(manager, {'youtube_id': 'video', 'slice_index': 1}) == 'business-result'
    summary = summarize_events(list(tmp_path.rglob('*.jsonl')), cohort=['video:1'])
    assert summary['attempt_count'] == 1
    assert summary['attempts'][0]['outcome'] == expected
    assert summary['cohort']['counts']['completed'] == 0


@pytest.mark.parametrize('business_error', [False, True])
def test_observation_db_error_never_replaces_business_result(tmp_path, monkeypatch, business_error):
    from config.settings import settings
    from video_processing.pipeline_manager import _journal_video_execution
    monkeypatch.setattr(settings, 'enable_pipeline_stage_events', True)
    def cannot_read(*args, **kwargs):
        raise OSError('synthetic observer failure')
    manager = SimpleNamespace(db=SimpleNamespace(get_video_by_youtube_id=cannot_read), _OUT_DIR=tmp_path)
    @_journal_video_execution
    def work(self, video):
        if business_error:
            raise RuntimeError('original business error')
        return 'original result'
    if business_error:
        with pytest.raises(RuntimeError, match='original business error'):
            work(manager, {'youtube_id': 'video'})
    else:
        assert work(manager, {'youtube_id': 'video'}) == 'original result'
    assert summarize_events(list(tmp_path.rglob('*.jsonl')))['attempts'][0]['outcome'] == 'unknown'


def test_legacy_flag_off_and_bound_worker_do_not_create_extra_attempt(tmp_path, monkeypatch):
    from config.settings import settings
    from video_processing.pipeline_manager import _journal_video_execution
    manager = SimpleNamespace(_OUT_DIR=tmp_path)  # 没有 db，跳过路径不准观测读库。
    work = _journal_video_execution(lambda self, video: True)
    monkeypatch.setattr(settings, 'enable_pipeline_stage_events', False)
    before = set(tmp_path.iterdir())
    assert work(manager, {'youtube_id': 'video'}) is True
    assert set(tmp_path.iterdir()) == before
    monkeypatch.setattr(settings, 'enable_pipeline_stage_events', True)
    path = tmp_path / 'worker.jsonl'
    journal = StageJournal(path, task_id='video:0', attempt_id='worker')
    with bind_journal(journal):
        assert work(manager, {'youtube_id': 'video'}) is True
        journal.close('unknown')
    assert list(tmp_path.rglob('*.jsonl')) == [path]
    assert summarize_events([path])['attempt_count'] == 1


def test_report_cli_requires_both_window_bounds_and_never_guesses(tmp_path, capsys):
    root = Path(__file__).resolve().parents[2]
    main = runpy.run_path(str(root / 'scripts/report_stage_events.py'))['main']
    main([str(tmp_path)])
    assert json.loads(capsys.readouterr().out)['effective_per_hour'] is None
    with pytest.raises(SystemExit) as error:
        main([str(tmp_path), '--window-start', '1'])
    assert error.value.code == 2
    capsys.readouterr()
    main([str(tmp_path), '--window-start', '1', '--window-end', '3601'])
    report = json.loads(capsys.readouterr().out)
    assert report['observation_window']['duration_seconds'] == 3600
    assert report['effective_per_hour'] is None
