"""阶段计时不能把重试、截断或嵌套指标当作成片。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-29 | Codex | 证据去重、未知中断、无正文白名单及阶段壁钟。 |
| 1.1.0 | 2026-10-29 | Codex | 父子角色去重、规范任务身份、明确窗口及独立后台/公开事实。 |
"""
import json
from types import SimpleNamespace

import pytest

from video_processing.utils.stage_events import (StageJournal, bind_journal, canonical_task_id,
    emit_event, persistent_queue_wait_seconds, summarize_events)


def test_transition_measures_wall_clock_and_deduplicates(tmp_path, monkeypatch):
    from video_processing.utils import stage_events
    clock = iter([10.0, 15.0, 20.0])
    monkeypatch.setattr(stage_events.time, 'monotonic', lambda: next(clock))
    path = tmp_path / 'attempt.jsonl'
    journal = StageJournal(path, task_id='video', attempt_id='attempt')
    with bind_journal(journal):
        journal.transition('OCR')
        emit_event('metric', stage='OCR', duration_seconds=4, frames=30)
        journal.transition('TRANSLATING')
        journal.close('local_complete')
    summary = summarize_events([path, path])
    assert summary['attempt_count'] == 1
    assert summary['attempts'][0]['stage_wall_seconds'] == {'OCR': 5, 'TRANSLATING': 5}
    assert summary['metrics']['OCR']['duration_seconds'] == 4
    assert summary['delivery_counts'] is None


def test_interruption_keeps_outcome_unknown_and_rejects_truncated_line(tmp_path):
    path = tmp_path / 'attempt.jsonl'
    journal = StageJournal(path, task_id='video', attempt_id='attempt')
    journal.transition('OCR')
    with path.open('a') as stream:
        stream.write('{"schema":')
    summary = summarize_events([path])
    assert summary['attempts'][0]['outcome'] == 'unknown'
    assert summary['attempts'][0]['stage_wall_seconds'] == {}
    assert summary['unreadable_records'] == 1


def test_no_context_has_no_write_and_payload_drops_content(tmp_path):
    before = set(tmp_path.iterdir())
    emit_event('metric', stage='OCR', frames=1)
    assert set(tmp_path.iterdir()) == before
    path = tmp_path / 'events.jsonl'
    journal = StageJournal(path, task_id='video', attempt_id='attempt')
    with bind_journal(journal):
        emit_event('metric', stage='OCR', frames=2, prompt='secret', response='subtitle',
                   error='private error', duration_seconds=float('nan'))
    last = json.loads(path.read_text().splitlines()[-1])
    assert last['frames'] == 2
    assert not {'prompt', 'response', 'error', 'duration_seconds'} & last.keys()


def test_fixed_cohort_keeps_review_failure_and_missing_evidence_in_denominator(tmp_path):
    paths = []
    for task, outcome in [('a', 'local_prepared'), ('b', 'review'), ('c', 'failed')]:
        path = tmp_path / (task + '.jsonl')
        journal = StageJournal(path, task_id=task, attempt_id='one')
        if task == 'a':
            journal.emit('delivery_evidence', outcome='qualified_local_video')
        journal.close(outcome)
        paths.append(path)
    summary = summarize_events(paths, cohort=['a', 'b', 'c', 'd'])
    assert summary['cohort']['counts'] == dict(completed=1, review=1, failed=1, pending_or_unknown=1)
    assert set(summary['cohort']['rates'].values()) == {.25}
    assert summary['delivery_counts'] == dict(qualified_local_video=1, publication_package_ready=None,
                                              platform_accepted=None, management_published_confirmed=None,
                                              public_verified=None)
    assert summary['attempt_count'] == 3


def test_new_interruption_does_not_hide_behind_previous_completed_attempt(tmp_path, monkeypatch):
    from video_processing.utils import stage_events
    path = tmp_path / 'events.jsonl'
    monkeypatch.setattr(stage_events.time, 'time', lambda: 10)
    old = StageJournal(path, task_id='a', attempt_id='old')
    old.emit('delivery_evidence', outcome='qualified_local_video')
    old.close('local_prepared')
    monkeypatch.setattr(stage_events.time, 'time', lambda: 20)
    new = StageJournal(path, task_id='a', attempt_id='new')
    new.emit('attempt_start')
    report = summarize_events([path], cohort=['a'])
    assert report['cohort']['counts']['pending_or_unknown'] == 1
    assert report['cohort']['counts']['completed'] == 0


def test_independent_public_evidence_does_not_inflate_processing_attempts(tmp_path):
    path = tmp_path / 'delivery.jsonl'
    journal = StageJournal(path, task_id='a:0', attempt_id='delivery', role='delivery')
    journal.emit('delivery_evidence', outcome='platform_accepted')
    summary = summarize_events([path, path])
    assert summary['attempt_count'] == 0
    assert summary['delivery_counts']['platform_accepted'] == 1
    assert summary['delivery_counts']['public_verified'] is None
    journal.emit('delivery_evidence', outcome='public_verified')
    summary = summarize_events([path])
    assert summary['attempt_count'] == 0
    assert summary['delivery_counts']['public_verified'] == 1


def test_phase_and_control_never_inflate_root_attempt_or_cohort(tmp_path):
    paths = []
    for role, task in [('attempt', 'video:2'), ('phase', 'video:2'),
                       ('control', 'preparation-dispatch'), ('delivery', 'video:2')]:
        path = tmp_path / f'{role}.jsonl'
        journal = StageJournal(path, task_id=task, attempt_id=role, role=role)
        with bind_journal(journal):
            journal.transition('OCR' if role == 'phase' else 'WAITING')
            if role in {'phase', 'control'}:
                # 错接子阶段的完整成片事件也不能抬高有效交付。
                journal.emit('delivery_evidence', outcome='qualified_local_video')
            if role == 'delivery':
                journal.emit('delivery_evidence', outcome='management_published_confirmed')
            journal.close('failed' if role == 'attempt' else 'local_complete')
        paths.append(path)
    summary = summarize_events(paths + paths, cohort=['video:2'])
    assert summary['attempt_count'] == summary['phase_count'] == summary['control_count'] == 1
    assert summary['attempts'][0]['role'] == 'attempt'
    assert summary['phase_attempts'][0]['outcome'] == 'local_complete'
    assert summary['cohort']['counts'] == dict(completed=0, failed=1, review=0, pending_or_unknown=0)
    assert summary['delivery_counts']['qualified_local_video'] is None
    assert summary['delivery_counts']['management_published_confirmed'] == 1
    assert summary['delivery_counts']['public_verified'] is None


@pytest.mark.parametrize('stem,scope,expected', [
    ('video_s2', None, 'video:2'), ('video_with_under_s12', None, 'video_with_under:12'),
    ('video_s0', None, 'video:0'), ('video', None, 'video:0'),
    ('video_part3', 'video:3', 'video:3'), ('unrelated', 'video:0', 'video:0'),
])
def test_canonical_task_identity_prefers_inherited_scope(stem, scope, expected):
    assert canonical_task_id(stem, scope_key=scope) == expected


def test_effective_rate_requires_explicit_window_and_qualified_evidence(tmp_path, monkeypatch):
    from video_processing.utils import stage_events
    path = tmp_path / 'events.jsonl'
    for task, timestamp in [('before:0', 9), ('inside:0', 10), ('after:0', 3610)]:
        monkeypatch.setattr(stage_events.time, 'time', lambda: timestamp)
        journal = StageJournal(path, task_id=task, attempt_id='root')
        journal.emit('delivery_evidence', outcome='qualified_local_video')
    inside = StageJournal(path, task_id='inside:0', attempt_id='duplicate-receipt', role='delivery')
    monkeypatch.setattr(stage_events.time, 'time', lambda: 100)
    inside.emit('delivery_evidence', outcome='qualified_local_video')
    assert summarize_events([path])['effective_per_hour'] is None
    summary = summarize_events([path, path], observation_window=(10, 3610))
    assert summary['observation_window'] == dict(start=10, end=3610, duration_seconds=3600)
    assert summary['effective_per_hour'] == 1
    assert summarize_events([path], cohort=['missing:0'],
                            observation_window=(10, 3610))['effective_per_hour'] is None
    assert summarize_events([], observation_window=(10, 3610))['effective_per_hour'] is None


@pytest.mark.parametrize('window', [(1, 1), (2, 1), (-1, 1), (True, 2), (0, float('nan')), (0,)])
def test_invalid_observation_window_is_rejected(window):
    with pytest.raises(ValueError, match='observation_window'):
        summarize_events([], observation_window=window)


def test_cli_phase_journal_uses_scope_identity_and_flag_off_has_no_files(tmp_path, monkeypatch):
    import importlib
    module = importlib.import_module('cli.commands.auto_caption')
    source = tmp_path / 'video_part2.mp4'
    scope = SimpleNamespace(key='video:2', owner='a' * 32)
    before = set(tmp_path.iterdir())
    monkeypatch.setattr(module.settings, 'enable_pipeline_stage_events', False)
    assert module._build_stage_journal(source, None, 'caption', scope) is None
    assert set(tmp_path.iterdir()) == before
    monkeypatch.setattr(module.settings, 'enable_pipeline_stage_events', True)
    journal = module._build_stage_journal(source, None, 'caption', scope)
    journal.close('local_complete')
    summary = summarize_events(list(tmp_path.rglob('*.jsonl')), cohort=['video:2'])
    assert summary['attempt_count'] == 0 and summary['phase_count'] == 1
    assert summary['phase_attempts'][0]['task_id'] == 'video:2'
    assert summary['cohort']['counts']['pending_or_unknown'] == 1
    assert summary['delivery_counts'] is None
    assert json.loads(journal.path.read_text().splitlines()[0])['parent_attempt_id'] == scope.owner


def test_cli_busy_exit_closes_scope_and_keeps_only_phase_evidence(tmp_path, monkeypatch):
    import importlib
    from click.testing import CliRunner
    from video_processing.core.preparation_resources import PreparationBusy
    from video_processing.utils.stage_events import current_journal
    module = importlib.import_module('cli.commands.auto_caption')
    source = tmp_path / 'video_s2.mp4'
    source.write_bytes(b'synthetic')
    closed = []
    scope = SimpleNamespace(key='video:2', owner='a' * 32, output=tmp_path,
                            close=lambda: closed.append(True))
    class BusyCaption:
        def __init__(self, **kwargs):
            self.input_path = kwargs['input_path']
            self.output_path = kwargs['output_path']
        def process(self):
            raise PreparationBusy('synthetic owner unknown')
    monkeypatch.setattr(module.settings, 'enable_pipeline_stage_events', True)
    monkeypatch.setattr(module, 'setup_execution_context', lambda: scope)
    monkeypatch.setattr(module, 'AutoCaptionProcessor', BusyCaption)
    result = CliRunner().invoke(module.auto_caption, [str(source)])
    assert result.exit_code == 77, result.output
    assert closed == [True] and current_journal() is None
    summary = summarize_events(list(tmp_path.rglob('*.jsonl')))
    assert summary['attempt_count'] == 0 and summary['phase_count'] == 1
    assert summary['phase_attempts'][0]['outcome'] == 'waiting_resource_owner_unknown'


def test_waits_keep_known_zero_distinct_from_unknown_and_do_not_add_to_stage_wall(tmp_path):
    path = tmp_path / 'waits.jsonl'
    journal = StageJournal(path, task_id='video:0', attempt_id='worker')
    journal.emit('resource_wait', stage='OCR', resource='heavy')
    journal.emit('resource_acquired', stage='OCR', resource='heavy', duration_seconds=3)
    journal.emit('resource_wait', stage='TRANSLATION', resource='network')  # 中断，未拿到槽。
    journal.emit('lock_acquired', stage='PIPELINE_LOCK', duration_seconds=0)
    journal.emit('lock_wait', stage='WAITING_TASK_LOCK', outcome='busy_unknown_wait_duration')
    journal.emit('queue_wait', stage='WAITING_PREPARATION_QUEUE', duration_seconds=10)
    journal.emit('publication_wait', stage='WAITING_PUBLICATION_SLOT', duration_seconds=True)
    journal.emit('stage_end', stage='OCR', duration_seconds=8)
    control = StageJournal(path, task_id='dispatcher', attempt_id='dispatch', role='control')
    control.emit('queue_wait', stage='WAITING_LEGACY_OR_COHORT')
    summary = summarize_events([path, path])
    waits = {(row['kind'], row['stage'], row['resource']): row for row in summary['waits']}
    heavy = waits['resource_wait', 'OCR', 'heavy']
    assert heavy['records'] == heavy['known_duration_count'] == 1
    assert heavy['known_duration_seconds'] == 3 and heavy['unknown_duration_count'] == 0
    assert waits['resource_wait', 'TRANSLATION', 'network']['known_duration_seconds'] is None
    assert waits['resource_wait', 'TRANSLATION', 'network']['unknown_duration_count'] == 1
    assert waits['lock_wait', 'PIPELINE_LOCK', '']['known_duration_seconds'] == 0
    assert waits['lock_wait', 'WAITING_TASK_LOCK', '']['unknown_duration_count'] == 1
    assert waits['publication_wait', 'WAITING_PUBLICATION_SLOT', '']['unknown_duration_count'] == 1
    assert waits['queue_wait', 'WAITING_LEGACY_OR_COHORT', '']['known_duration_seconds'] is None
    assert summary['attempts'][0]['stage_wall_seconds'] == {'OCR': 8}
    assert summary['attempt_count'] == 1 and summary['control_count'] == 1


@pytest.mark.parametrize('duration', [None, True, False, -1, float('nan'), float('inf'), '3'])
def test_invalid_wait_durations_stay_unknown(tmp_path, duration):
    path = tmp_path / 'wait.jsonl'
    # 模拟完整但来自外部的损坏日志，绕过写入端的白名单过滤。
    path.write_text(json.dumps(dict(schema='pipeline-stage-events-v1', task_id='video:0',
        attempt_id='one', event_id='event', kind='lock_wait', stage='LOCK',
        duration_seconds=duration)))
    row = summarize_events([path])['waits'][0]
    assert row['unknown_duration_count'] == 1 and row['known_duration_seconds'] is None


@pytest.mark.parametrize('queued,expected', [(10, 20), (30, 0), (40, 0),
    (True, None), (None, None), ('10', None), (-1, None), (float('nan'), None), (float('inf'), None)])
def test_persistent_queue_wait_only_trusts_finite_real_wall_clock(queued, expected):
    assert persistent_queue_wait_seconds(queued, now=30) == expected
