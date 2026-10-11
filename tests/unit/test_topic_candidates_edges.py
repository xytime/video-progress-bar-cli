"""专项异常与架构验收：真实事务、进程锁、规则与增量回退。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-11 | Codex | 补齐缺资料、保护失败、跨进程活作业、原子故障与清理边界 |
"""
import ast
import hashlib
import sqlite3
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from config.settings import Settings
from tests.topic_candidate_fixtures import tracker, topic, run, decision, video
from video_processing.core.topic_candidates import TopicError
from video_processing.db.database import PipelineDB
from video_processing.topic_tracker.service import TopicTracker
from video_processing.utils.topic_search import ExistingTopicRules


@pytest.mark.parametrize('missing', ['title','channelId','channelTitle','publishedAt','liveBroadcastContent'])
def test_a08_missing_required_metadata(tracker,missing):
    del tracker.adapter.items[0]['snippet'][missing]
    run(tracker);row=tracker.candidates()['candidates'][0]
    assert row['eligibility']=='INCOMPLETE' and not row['can_save']


@pytest.mark.parametrize('status', [{'privacyStatus':'private'},{'uploadStatus':'failed'},{'uploadStatus':'deleted'},{'uploadStatus':'rejected'}])
def test_a08_explicit_unavailable_status(tracker,status):
    tracker.adapter.items[0]['status']=status
    run(tracker);assert tracker.candidates()['candidates'][0]['eligibility']=='UNAVAILABLE'


def test_a09_current_channel_policy_and_read_only_blacklist(tracker):
    from video_processing.censor_engine import dump_default_rules
    original=dump_default_rules();tracker.rules=ExistingTopicRules()
    tracker.adapter.items=[video(title=original['channel_policy']['en'][0])]
    run(tracker);row=tracker.candidates()['candidates'][0]
    assert row['eligibility']=='RESTRICTED' and row['reason'].startswith('CP')
    assert dump_default_rules()==original
    tracker.rules=type('ClearRules',(),{'version':lambda self:'clear','check':lambda self,meta:None})()
    tracker.db.add_channel('UC-isolated','Excluded channel',status='BLACKLISTED')
    assert tracker.candidates()['candidates'][0]['eligibility']=='RESTRICTED'
    assert tracker.db.topic_presence('00000000001','UC-isolated')['channel_blocked']


def test_a09_dal_read_failure_blocks_favorite(tracker,monkeypatch):
    run(tracker)
    def fail(*args):raise TopicError('DATABASE_BUSY','busy',503)
    monkeypatch.setattr(tracker.db,'topic_presence',fail)
    row=tracker.candidates()['candidates'][0]
    assert row['eligibility']=='INCOMPLETE' and not row['can_save']
    with pytest.raises(TopicError):tracker.decide(row['key'],decision(row),'test')


def test_a10_live_process_lock_cannot_be_stolen_by_recovery(tracker):
    t=topic(tracker);job=tracker.db.topic_create_job(t['id'],t['version'],'process-lock-request','test',tracker.clock())
    script="import fcntl,sys; f=open(sys.argv[1],'a'); fcntl.flock(f.fileno(),fcntl.LOCK_EX); print('ready',flush=True); sys.stdin.read(1)"
    process=subprocess.Popen([sys.executable,'-c',script,str(tracker.lock_path)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
    try:
        assert process.stdout.readline().strip()=='ready'
        peer=TopicTracker(PipelineDB(tracker.db.db_path),tracker.config,tracker.adapter,tracker.rules,clock=tracker.clock)
        assert peer.view()['jobs'][0]['state']=='RUNNING'
        with pytest.raises(TopicError,match='正在进行'):peer.start(t['id'],t['version'],'another-process-request','test')
        assert not tracker.adapter.calls
    finally:
        process.communicate('x',timeout=5)
    tracker.maintenance()
    assert tracker.db.topic_jobs(idem=job['idempotency'])[0]['code']=='RESTARTED'


def test_a12_defaults_closed_and_budgets_cannot_be_raised():
    from pydantic import ValidationError
    config=Settings(_env_file=None)
    assert config.topic_search_enabled is False and config.topic_quota_verified is False
    assert not config.topic_quota_project
    for value in (dict(topic_search_daily_limit=21),dict(topic_general_daily_limit=41),dict(topic_search_daily_limit=0)):
        with pytest.raises(ValidationError):Settings(_env_file=None,**value)


def test_a13_unknown_guard_fails_before_request(tracker):
    t=topic(tracker)
    def fail(now):raise ValueError('unavailable')
    tracker.config.is_us_market_guard_window=fail
    with pytest.raises(TopicError) as caught:tracker.start(t['id'],t['version'],'unknown-guard-request','test')
    assert caught.value.code=='GUARD_UNKNOWN' and not tracker.adapter.calls


def test_a18_whole_result_transaction_rolls_back(tracker):
    tracker.adapter.items=[video(1),video(2)]
    with sqlite3.connect(tracker.db.db_path) as c:
        c.execute("CREATE TRIGGER fail_second_hit BEFORE INSERT ON topic_hits WHEN (SELECT COUNT(*) FROM topic_hits)>0 BEGIN SELECT RAISE(ABORT,'fault'); END")
    job=run(tracker)
    assert job['state']=='FAILED' and not tracker.candidates()['candidates']
    with sqlite3.connect(tracker.db.db_path) as c:
        assert c.execute('SELECT COUNT(*) FROM topic_decisions').fetchone()[0]==0
        assert c.execute('SELECT COUNT(*) FROM topic_hits').fetchone()[0]==0
    assert tracker.view()['budget']['search']==1 and tracker.view()['budget']['general']==1


def test_a18_concurrent_decision_cas(tracker):
    run(tracker);row=tracker.candidates()['candidates'][0]
    def decide(state):
        try:tracker.decide(row['key'],decision(row,state,'其他' if state=='REJECTED' else None),'test');return 'OK'
        except TopicError as exc:return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(decide,['SAVED','REJECTED']))
    assert sorted(results)==['OK','STALE']
    assert sum(r['action'] in ('SAVED','REJECTED') for r in tracker.db.topic_audit_records())==1


def test_a13_stop_record_retries_short_busy_lock(tracker):
    selected=topic(tracker)
    job=tracker.db.topic_create_job(selected['id'],selected['version'],'bounded-stop-record','test',tracker.clock())
    locked=threading.Event()
    def hold_write():
        with sqlite3.connect(tracker.db.db_path) as connection:
            connection.execute('BEGIN IMMEDIATE');locked.set()
            time.sleep(2.2)
    worker=threading.Thread(target=hold_write);worker.start()
    assert locked.wait(1)
    started=time.monotonic()
    tracker._finish(job['id'],'INTERRUPTED','STOPPED')
    elapsed=time.monotonic()-started;worker.join(1)
    row=tracker.db.topic_jobs(idem=job['idempotency'])[0]
    assert row['state']=='INTERRUPTED' and row['code']=='STOPPED'
    assert elapsed < 5 and not tracker.adapter.calls


def test_a03_search_window_uses_job_start_not_delayed_worker(tracker):
    selected=topic(tracker)
    job=tracker.db.topic_create_job(selected['id'],selected['version'],'fixed-start-window','test',tracker.clock())
    original=tracker.clock();tracker.clock.advance(seconds=10)
    captured=[];search=tracker.adapter.search
    def observe(topic_value, now, timeout):
        captured.append(now)
        return search(topic_value, now, timeout)
    tracker.adapter.search=observe
    tracker._run(job,selected,tracker._lock())
    assert captured==[original]
    assert tracker.db.topic_jobs(idem=job['idempotency'])[0]['state']=='COMPLETE'


def test_a19_startup_cleans_source_without_requests(tracker):
    tracker.adapter.items=[video(title='Unique API title removed by retention')]
    run(tracker);row=tracker.candidates()['candidates'][0]
    tracker.decide(row['key'],decision(row,'REJECTED','其他'),'test')
    tracker.clock.advance(days=30);tracker.config.topic_search_enabled=False
    previous=len(tracker.adapter.calls)
    peer=TopicTracker(PipelineDB(tracker.db.db_path),tracker.config,tracker.adapter,tracker.rules,clock=tracker.clock)
    assert not peer.candidates()['candidates'] and peer.view()['control']['mode']=='OFF'
    assert peer.db.topic_candidate(row['key'])['metadata'] is None and len(tracker.adapter.calls)==previous
    # 关闭所有连接后检查实际数据库页；不宣称清除外部备份/并发读取者的旧 WAL 快照。
    assert b'Unique API title removed by retention' not in Path(tracker.db.db_path).read_bytes()


def test_a21_exact_baseline_dal_operates_with_candidate_tables(tracker):
    run(tracker);row=tracker.candidates()['candidates'][0]
    tracker.decide(row['key'],decision(row,'REJECTED','其他'),'test')
    tracker.mode('OFF',tracker.db.topic_control()['version'],'test')
    path=Path(__file__).resolve().parents[2]/'src/video_processing/db/database.py'
    # 本次主 DAL 只有两行接入；还原后逐字校验已确认基线 eb7b7fa 的 SHA256。
    source=path.read_text().replace('from .topic_candidates import TopicCandidateDAL\n','').replace(
        'class PipelineDB(TopicCandidateDAL, WallstreetExperimentDAL):','class PipelineDB(WallstreetExperimentDAL):')
    assert hashlib.sha256(source.encode()).hexdigest()=='ad0ad1c4d19ea12297d7289b2b0af92309ed163555d011f7f53af81c6d28a91e'
    namespace={'__name__':'video_processing.db.rollback_baseline','__package__':'video_processing.db'}
    exec(compile(source,str(path),'exec'),namespace)
    baseline=namespace['PipelineDB'](tracker.db.db_path)
    baseline.add_video('old-rollback','Existing queue task','UC-safe',score=90)
    assert baseline.get_video_by_youtube_id('old-rollback')['title']=='Existing queue task'
    assert baseline.get_video_by_youtube_id('00000000001') is None
    assert tracker.db.topic_candidate(row['key'])['metadata'] is not None
    assert tracker.candidates()['candidates'][0]['state']=='REJECTED'


def test_a17_dependencies_and_topic_only_writes():
    root=Path(__file__).resolve().parents[2]/'src'
    paths=[root/'video_processing/core/topic_candidates.py',root/'video_processing/db/topic_candidates.py',
           root/'video_processing/topic_tracker/service.py',root/'video_processing/utils/topic_search.py',root/'web/topic_candidates.py']
    prohibited={'add_video','update_video_status','process_video','_run_pipeline_manager','run_daily_job','Popen','kill','killpg','getenv'}
    for path in paths:
        tree=ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node,ast.Call):
                name=node.func.attr if isinstance(node.func,ast.Attribute) else node.func.id if isinstance(node.func,ast.Name) else ''
                assert name not in prohibited,(path,name)
            if isinstance(node,(ast.Import,ast.ImportFrom)):
                modules=[node.module or ''] if isinstance(node,ast.ImportFrom) else [alias.name for alias in node.names]
                assert not any('pipeline_manager' in module or module.startswith(('scripts','cli','bot')) for module in modules)
    dal=ast.parse(paths[1].read_text())
    for node in ast.walk(dal):
        if isinstance(node,ast.Constant) and isinstance(node.value,str):
            sql=node.value.upper()
            if sql.startswith(('INSERT','UPDATE','DELETE','CREATE')):
                assert 'PROCESSED_VIDEOS' not in sql and 'BLACKLISTED_VIDEOS' not in sql and 'RECOMMENDED_CHANNELS' not in sql
