"""M01/M04/M06/M07/M12/M15/M16/M18：入口拒绝、归属、正常退出和恢复。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-12 | Codex | 真实控制/角色锁/子进程/账本；外部执行计数为零 |
| 1.0.1 | 2026-10-13 | Codex | 验证精简 PATH 的真实 lsof 读取及工具失败仍阻断 |
| 1.0.2 | 2026-10-13 | Codex | 独立测试双重归属与未知进程保护回归 |
"""
import hashlib
import json
import os
from pathlib import Path
import signal
import shlex
import subprocess
import sys
import threading
import time
import pytest
from config.settings import settings
from video_processing.core.maintenance import MaintenanceDenied, gate
from video_processing.core.maintenance_child import child_continuation
from video_processing.core.maintenance_runtime import inspection, stop_ui, code_hash, protection_snapshot, SOURCE_GROUPS
from video_processing.db.database import PipelineDB
from video_processing.pipeline_manager import PipelineManager
from tests.topic_candidate_fixtures import tracker, topic, run, decision

WORKER = Path(__file__).parents[1] / 'helpers/maintenance_worker.py'


def test_m04_all_direct_business_entries_refuse_before_adapter(isolated_running_maintenance):
    from scripts import monitor_channels, rescore_refresh, run_background_preparation, run_ready_publications, run_publication_window, run_wallstreet_ab, wechat_keepalive, wechat_commenter, submit_english_world_review, submit_english_world_douyin
    from scripts import copywriter, cover_generator, douyin_uploader, kuaishou_uploader, wechat_uploader, submit_generic_douyin, monitor_english_world_daily, add_approved_channel, run_video_task, run_english_world_daily
    from bot.pipeline_agent import PipelineAgent
    from video_processing.highlight.service import HighlightJobService
    from video_processing.english_world.research import EnglishWorldResearchService
    from video_processing.utils.wallstreet_worker import ensure_wallstreet_worker
    from video_processing.interaction.runner import run_interaction_tick
    isolated_running_maintenance.enter('维护')
    calls = [
        lambda: monitor_channels.main(), lambda: monitor_channels.fetch_latest_videos(None, 'UC-isolated'),
        lambda: rescore_refresh.main(), lambda: rescore_refresh.fetch_current('synthetic-id'),
        lambda: run_background_preparation.main(), lambda: run_ready_publications.main(),
        lambda: run_publication_window.main(), lambda: run_publication_window.dispatch_one_deferred_english_world_submission(),
        lambda: run_publication_window.dispatch_one_english_world_douyin_submission(),
        lambda: run_wallstreet_ab.run_once(None), lambda: wechat_commenter.main(),
        lambda: wechat_keepalive.main(), lambda: submit_english_world_review.submit('synthetic-review'),
        lambda: submit_english_world_douyin.submit('synthetic-review'),
        lambda: PipelineManager.__new__(PipelineManager)._process_single_video({'youtube_id': 'A', 'slice_index': 0}),
        lambda: PipelineManager.__new__(PipelineManager).drain_pending_review_notifications(),
        lambda: PipelineAgent.__new__(PipelineAgent).process_video_now('A'),
        lambda: PipelineAgent.__new__(PipelineAgent).download_video('A'),
        lambda: HighlightJobService.__new__(HighlightJobService).analyze('job-A'),
        lambda: EnglishWorldResearchService.__new__(EnglishWorldResearchService).research('job-A'),
        lambda: copywriter.main(), lambda: cover_generator.main(), lambda: douyin_uploader.main(),
        lambda: kuaishou_uploader.main(), lambda: wechat_uploader.main(), lambda: submit_generic_douyin.main(),
        lambda: monitor_english_world_daily.main(), lambda: add_approved_channel.main(), lambda: run_video_task.main(),
        lambda: run_english_world_daily.main(), lambda: ensure_wallstreet_worker(), lambda: run_interaction_tick(),
    ]
    for execute in calls:
        with pytest.raises(MaintenanceDenied) as result:
            execute()
        assert result.value.code == 'MAINTENANCE'
    assert isolated_running_maintenance.status()['active'] == []


def test_m01_scheduler_periods_in_maintenance_do_not_dispatch(isolated_running_maintenance, monkeypatch):
    from web import app as web
    isolated_running_maintenance.enter('维护')
    counts = []
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **kw: counts.append('spawn'))
    class ClockStop:
        def __init__(self): self.seconds = []; self.closed = False
        def is_set(self): return self.closed
        def wait(self, seconds):
            self.seconds.append(seconds)
            if len(self.seconds) >= 4: self.closed = True
            return self.closed
    observed = []
    for execute in (web._auto_pipeline_loop, web._queue_runner_loop, web._ready_publication_supervisor, web._wechat_keepalive_loop):
        clock = ClockStop()
        execute(clock)
        observed += clock.seconds
    assert 10 in observed and 5 in observed and 14400 in observed and 15 in observed
    assert counts == []
    assert isolated_running_maintenance.status()['state'] == 'MAINTENANCE'


def test_m04_legacy_writes_blocked_get_and_current_write_preserved(tmp_path, isolated_running_maintenance):
    db = PipelineDB(str(tmp_path / 'old.sqlite'))
    db.add_video('A', 'Current unit', 'UC-test', score=90)
    with isolated_running_maintenance.admit('video', 'A:0') as ticket:
        ticket.start()
        isolated_running_maintenance.enter('在途排空')
        db.update_video_status('A', 'READY_FOR_PUBLICATION')
    assert db.get_video_by_youtube_id('A')['status'] == 'READY_FOR_PUBLICATION'
    with pytest.raises(MaintenanceDenied): db.add_video('B', 'Next unit', 'UC-test')
    assert db.get_video_by_youtube_id('B') is None


def test_m03_child_continuation_exact_fd_argv_and_object(tmp_path, isolated_running_maintenance):
    cmd = [sys.executable, str(WORKER), 'continuation', str(isolated_running_maintenance.path), str(tmp_path / 'child')]
    with isolated_running_maintenance.admit('video', 'A:0') as ticket:
        ticket.start()
        with child_continuation(cmd, {}) as options:
            isolated_running_maintenance.enter('父项执行中')
            result = subprocess.run(cmd, **options, capture_output=True, text=True, timeout=10)
            assert result.returncode == 0, result.stderr
            mismatch = subprocess.run(cmd[:-1] + [str(tmp_path / 'forged')], **options, capture_output=True, text=True, timeout=10)
            assert mismatch.returncode == 2
            assert 'INVALID_CONTINUATION' in mismatch.stdout
            assert not (tmp_path / 'forged.finished').exists()
            forged = dict(options['env']); forged['MAINTENANCE_CHILD_FD'] = '-1'
            result = subprocess.run(cmd, env=forged, capture_output=True, text=True, timeout=10)
            assert result.returncode == 2
    assert isolated_running_maintenance.status()['phase'] == 'IDLE'


def proof(tmp_path, control):
    state = control.status(); checks = []
    for group in sorted(SOURCE_GROUPS):
        path = tmp_path / (group + '.json')
        path.write_text(json.dumps(dict(group=group, version=state['version'], source_hash=code_hash(),
                                  readbacks=[dict(source='isolated-fixture', state='ABSENT') ])))
        checks.append(dict(group=group, kind='file', path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    path = tmp_path / 'evidence.json'
    path.write_text(json.dumps(dict(schema=1, version=state['version'], source_hash=code_hash(), at=time.time(),
                         protections=protection_snapshot(), groups=sorted(SOURCE_GROUPS), checks=checks)))
    return path


def prepare_empty_output(tmp_path, monkeypatch):
    monkeypatch.setattr(type(settings), 'default_output_dir', property(lambda self: tmp_path))
    db = PipelineDB(str(tmp_path / 'pipeline.db'))
    db.topic_initialize()
    return db


@pytest.mark.parametrize('action', ['ui', 'ignore-ui'])
def test_m06_normal_ui_signal_timeout_never_kill(tmp_path, isolated_running_maintenance, monkeypatch, action):
    prepare_empty_output(tmp_path, monkeypatch)
    isolated_running_maintenance.enter('维护')
    marker = str(tmp_path / 'ui')
    process = subprocess.Popen([sys.executable, str(WORKER), action, str(isolated_running_maintenance.path), marker])
    deadline = time.monotonic() + 10
    while not Path(marker + '.ready').exists():
        assert time.monotonic() < deadline
        time.sleep(.01)
    reaper = threading.Thread(target=process.wait, daemon=True); reaper.start()
    evidence = proof(tmp_path, isolated_running_maintenance)
    try:
        duplicate = subprocess.run([sys.executable, str(WORKER), 'ui', str(isolated_running_maintenance.path), str(tmp_path/'duplicate')],
                                   capture_output=True, text=True, timeout=10)
        assert duplicate.returncode != 0 and 'TaskLeaseBusy' in duplicate.stderr
        assert not (tmp_path/'duplicate.ready').exists()
        assert process.poll() is None
        assert inspection(isolated_running_maintenance, evidence=evidence, process_pids={process.pid})['safe']
        if action == 'ui':
            assert stop_ui(isolated_running_maintenance, evidence=evidence, process_pids={process.pid}, timeout=3)['stopped']
        else:
            with pytest.raises(MaintenanceDenied) as result:
                stop_ui(isolated_running_maintenance, evidence=evidence, process_pids={process.pid}, timeout=.15)
            assert result.value.code == 'STOP_TIMEOUT'
            assert process.poll() is None
        assert Path(marker + '.signal').read_text() == str(signal.SIGTERM)
    finally:
        Path(marker + '.release').touch()
        reaper.join(10)
    assert process.returncode == 0


def test_m16_unknown_source_and_m18_single_normal_resume(tmp_path, isolated_running_maintenance, monkeypatch):
    db = prepare_empty_output(tmp_path, monkeypatch)
    state = isolated_running_maintenance.enter('维护')
    evidence = proof(tmp_path, isolated_running_maintenance)
    assert not inspection(isolated_running_maintenance, evidence=evidence, process_pids={99999999})['safe']
    assert not inspection(isolated_running_maintenance, process_pids=set())['safe']
    observed = inspection(isolated_running_maintenance, evidence=evidence, process_pids=set())
    assert observed['safe'], observed
    isolated_running_maintenance.resume(state['version'], validated=observed['safe'])
    db.add_video('existing-A', 'Original eligible item', 'UC-test', score=90)
    with isolated_running_maintenance.admit('video', 'existing-A:0') as ticket:
        ticket.start()
        assert db.claim_video_for_processing('existing-A')
        assert not db.claim_video_for_processing('existing-A')
        db.update_video_status('existing-A', 'READY_FOR_PUBLICATION')
    assert db.topic_control()['mode'] == 'OFF'
    assert db.topic_jobs() == []


def test_m15_topic_only_rollback_preserves_backup_and_current_write(tracker, tmp_path, isolated_running_maintenance):
    import sqlite3
    run(tracker)
    row = tracker.candidates()['candidates'][0]
    tracker.decide(row['key'], decision(row, 'REJECTED', '其他'), 'operator')
    tracker.mode('OFF', tracker.db.topic_control()['version'], 'operator')
    tables = ['topic_candidates','topic_decisions','topic_audit','topic_budget','topic_jobs']
    def contents():
        with sqlite3.connect(tracker.db.db_path) as db:
            return {name:db.execute('SELECT * FROM '+name+' ORDER BY rowid').fetchall() for name in tables}
    before = contents()
    backup = tmp_path/'consistent-backup.sqlite'
    with sqlite3.connect(tracker.db.db_path) as original, sqlite3.connect(backup) as saved:
        original.backup(saved)
        assert saved.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    path = Path(__file__).resolve().parents[2]/'src/video_processing/db/database.py'
    source = path.read_text().replace('from .topic_candidates import TopicCandidateDAL\n','').replace(
           'class PipelineDB(TopicCandidateDAL, WallstreetExperimentDAL):','class PipelineDB(WallstreetExperimentDAL):')
    namespace = {'__name__':'video_processing.db.rollback_baseline','__package__':'video_processing.db'}
    exec(compile(source,str(path),'exec'),namespace)
    with isolated_running_maintenance.admit('video','current-original:0') as ticket:
        ticket.start()
        paused = isolated_running_maintenance.enter('候选回退演练')
        old = namespace['PipelineDB'](tracker.db.db_path)
        old.add_video('current-original','合法既有回写','UC-test',score=90)
        old.update_video_status('current-original','READY_FOR_PUBLICATION')
    assert contents() == before
    assert old.get_video_by_youtube_id('current-original')['status'] == 'READY_FOR_PUBLICATION'
    assert isolated_running_maintenance.status()['version'] == paused['version']
    assert tracker.db.topic_control()['mode'] == 'OFF'
    with sqlite3.connect(tracker.db.db_path) as current_db:
        assert current_db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'


def test_m04_web_maintenance_writes_refused_old_get_and_candidates_work(isolated_running_maintenance, monkeypatch):
    from fastapi.testclient import TestClient
    from web import app as web
    isolated_running_maintenance.enter('实际 Web 入口')
    calls = []
    real_popen = subprocess.Popen
    def dispatch(command, *args, **kwargs):
        if command[0] in {'ps', 'lsof', '/usr/sbin/lsof'}:
            return real_popen(command, *args, **kwargs)
        calls.append('business-spawn')
        pytest.fail('维护中出现业务子进程')
    monkeypatch.setattr(subprocess, 'Popen', dispatch)
    with TestClient(web.app,base_url='http://127.0.0.1:9100',client=('127.0.0.1',1)) as client:
        assert client.post('/api/pipeline/run').status_code == 503
        assert client.post('/api/videos/synthetic/process').status_code == 503
        assert client.get('/api/stats').status_code == 200
        assert client.get('/topic-candidates').status_code == 200
        status = client.get('/api/maintenance/status').json()
        assert status['safe'] is False and status['phase'] == 'UNKNOWN'
    assert calls == []


@pytest.mark.skipif(sys.platform != 'darwin', reason='macOS launchd PATH 回归')
def test_inspection_lsof_with_launchd_path(tmp_path, isolated_running_maintenance, monkeypatch):
    """真实工具能在精简 PATH 启动；cwd 输出模拟以保留沙盒进程隔离。"""
    monkeypatch.setenv('PATH', '/usr/bin:/bin')
    real_run = subprocess.run
    observed = []
    def run(command, **kwargs):
        if command[0] == 'ps':
            return subprocess.CompletedProcess(command, 0, '99999998 python -m cli.main\n', '')
        # -v 不扫描宿主进程；裸 lsof 在这个 PATH 下会直接 FileNotFoundError。
        version = real_run([command[0], '-v'], **kwargs)
        assert version.returncode == 0 and 'lsof' in version.stderr
        observed.append(command)
        return subprocess.CompletedProcess(command, 0, 'n' + str(tmp_path) + '\n', '')
    monkeypatch.setattr(subprocess, 'run', run)
    before = isolated_running_maintenance.status()
    result = inspection(isolated_running_maintenance)
    assert len(observed) == 1
    assert result['unknown'] == [{'code': 'SOURCES_NOT_VERIFIED'}]
    assert not result['safe']
    assert isolated_running_maintenance.status() == before


@pytest.mark.parametrize('failure', ['missing', 'denied'])
def test_inspection_lsof_failure_remains_closed(isolated_running_maintenance, monkeypatch, failure):
    def run(command, **kwargs):
        if command[0] == 'ps':
            return subprocess.CompletedProcess(command, 0, '99999998 python -m cli.main\n', '')
        if failure == 'missing':
            raise FileNotFoundError('lsof unavailable')
        return subprocess.CompletedProcess(command, 1, '', 'denied')
    monkeypatch.setattr(subprocess, 'run', run)
    result = inspection(isolated_running_maintenance)
    expected = 'INSPECTION_UNKNOWN' if failure == 'missing' else 'PROCESS_CWD_UNKNOWN'
    assert expected in {row['code'] for row in result['unknown']}
    assert not result['safe']


def test_m04_clues_refresh_registered_and_maintenance_cache_only(isolated_running_maintenance, monkeypatch):
    from video_processing.utils.maintenance_clues import read_clues
    monkeypatch.setattr(settings,'enable_dynamic_keywords',True)
    class Hub:
        def _read_cache(self): return dict(keywords=['safe cached'],updated_at=0)
        def _normalize_cached_keywords(self,value): return value
        def _format_response(self,value,**kw): return dict(keywords=value,**kw)
        def refresh_sync(self): pytest.fail('维护中不得联网刷新')
    isolated_running_maintenance.enter('只读热词')
    assert read_clues(Hub())['keywords'] == ['safe cached']


def test_m06_busy_refuses_signal_to_actual_ui(tmp_path, isolated_running_maintenance, monkeypatch):
    prepare_empty_output(tmp_path, monkeypatch)
    ticket = isolated_running_maintenance.acquire('video', 'current:0')
    ticket.start()
    isolated_running_maintenance.enter('在途任务禁止停 UI')
    marker = str(tmp_path/'busy-ui')
    process = subprocess.Popen([sys.executable, str(WORKER), 'ui', str(isolated_running_maintenance.path), marker])
    try:
        deadline = time.monotonic()+10
        while not Path(marker+'.ready').exists():
            assert time.monotonic()<deadline
            time.sleep(.01)
        with pytest.raises(MaintenanceDenied) as result:
            stop_ui(isolated_running_maintenance, evidence=proof(tmp_path, isolated_running_maintenance), process_pids={process.pid})
        assert result.value.code == 'NOT_VERIFIED_IDLE'
        assert process.poll() is None and not Path(marker+'.signal').exists()
    finally:
        ticket.close()
        Path(marker+'.release').touch()
        process.wait(10)
    assert process.returncode == 0


def test_m01_m07_actual_web_lifecycle_restarts_one_scheduler_group(isolated_running_maintenance, monkeypatch):
    from fastapi.testclient import TestClient
    from web import app as web
    isolated_running_maintenance.enter('实际 UI 生命周期重启')
    calls = []
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **kw: calls.append('spawn'))
    for _ in range(3):
        with TestClient(web.app, base_url='http://127.0.0.1:9100', client=('127.0.0.1', 1)) as client:
            assert client.get('/api/stats').status_code == 200
            assert len(web._scheduler_threads) == 4
            assert all(thread.is_alive() for thread in web._scheduler_threads)
            assert len({thread.name for thread in web._scheduler_threads}) == 4
        assert not any(thread.is_alive() for thread in web._scheduler_threads)
        assert web._maintenance_ui_lease is None
    assert calls == []


def test_m05_cli_enter_acknowledges_saved_state_without_claiming_safe(isolated_running_maintenance):
    script = Path(__file__).resolve().parents[2]/'scripts/maintenance_control.py'
    result = subprocess.run([sys.executable, str(script), 'enter', '--reason', 'CLI 隔离维护'],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value['state'] == 'MAINTENANCE' and value['safe'] is False and value['phase'] == 'UNKNOWN'
    status = subprocess.run([sys.executable, str(script), 'status'], capture_output=True, text=True, timeout=10)
    assert status.returncode == 2
    assert isolated_running_maintenance.status()['state'] == 'MAINTENANCE'


def test_ui_startup_preserves_uvicorn_sigterm_handler(isolated_running_maintenance, monkeypatch):
    """生产同条件：启用旧 SIGTERM flag，真实服务器信号 owner 仍能正常退出。"""
    import uvicorn
    from web import app as web
    isolated_running_maintenance.enter('Uvicorn 正常退出回归')
    monkeypatch.setattr(web.settings,'enable_sigterm_kill',True)
    server=uvicorn.Server(uvicorn.Config(web.app))
    original=signal.getsignal(signal.SIGTERM)
    with server.capture_signals():
        expected=signal.getsignal(signal.SIGTERM)
        web.startup_event()
        try:
            assert signal.getsignal(signal.SIGTERM)==expected
            os.kill(os.getpid(),signal.SIGTERM)
            assert server.should_exit is True
            server._captured_signals.clear()  # 测试处理完毕，不向 pytest 外层重放退出。
        finally:
            web.release_maintenance_ui_role()
    assert signal.getsignal(signal.SIGTERM)==original
    assert web._maintenance_ui_lease is None
    assert not any(thread.is_alive() for thread in web._scheduler_threads)


@pytest.mark.parametrize('case', ['independent', 'cwd_mismatch', 'cwd_denied', 'cwd_empty', 'cwd_multiple', 'cwd_relative',
                                  'production_entry', 'production_cwd', 'production_argument',
                                  'changed_runner', 'symlink_entry', 'unparseable'])
def test_independent_runner_requires_verified_entry_and_cwd(tmp_path, isolated_running_maintenance, monkeypatch, case):
    root = settings.project_root
    external = tmp_path / 'independent repo'
    scripts = external / 'scripts'
    scripts.mkdir(parents=True)
    entry = scripts / 'run_isolated_tests.py'
    original = root / 'scripts/run_isolated_tests.py'
    entry.write_bytes(original.read_bytes())
    if case == 'changed_runner':
        entry.write_text('print("not the isolated runner")')
    elif case == 'symlink_entry':
        entry.unlink()
        entry.symlink_to(original)
    if case == 'production_entry':
        entry = original
    command = shlex.join([str(root / '.venv/bin/python'), str(entry), '--', '-q'])
    if case == 'production_argument':
        command += ' ' + shlex.quote(str(root / 'tests'))
    if case == 'unparseable':
        command += " '"
    cwd = root if case == 'production_cwd' else tmp_path if case == 'cwd_mismatch' else external
    def run(args, **kwargs):
        if args[0] == 'ps':
            return subprocess.CompletedProcess(args, 0, f'99999998 {command}\n', '')
        return subprocess.CompletedProcess(args, 1 if case == 'cwd_denied' else 0,
            '' if case == 'cwd_empty' else 'nrelative\n' if case == 'cwd_relative' else
            f'n{cwd}\nn{root}\n' if case == 'cwd_multiple' else f'p99999998\nn{cwd}\n', '')
    monkeypatch.setattr(subprocess, 'run', run)
    before = isolated_running_maintenance.status()
    result = inspection(isolated_running_maintenance)
    codes = {row['code'] for row in result['unknown']}
    if case == 'independent':
        assert codes == {'SOURCES_NOT_VERIFIED'}
    elif case in {'cwd_denied', 'cwd_empty', 'cwd_multiple', 'cwd_relative'}:
        assert 'PROCESS_CWD_UNKNOWN' in codes
    else:
        assert 'UNREGISTERED_PROCESS' in codes
    assert not result['safe']
    assert isolated_running_maintenance.status() == before
