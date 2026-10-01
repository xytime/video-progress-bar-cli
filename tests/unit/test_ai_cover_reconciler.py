"""恢复本地兜底，真实 DAL 验证中断/并发/已提交状态保护。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-01 | Codex | 验证 Luna 新任务路由与独立来源回执 |
"""
import fcntl
import hashlib
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from scripts import reconcile_ai_cover_queue as reconciler
from video_processing.ai_cover_queue import AICoverQueue
from video_processing.db.database import PipelineDB
from video_processing.core.cover_policy import compliant_cover_layout_policy


def setup_task(tmp_path, monkeypatch, age=0, luna=False):
    queue=AICoverQueue(tmp_path/'queue',tmp_path/'finish')
    task=queue.create_task(prefix='cover-guard',youtube_id='cover-guard',slice_index=0,
        cover_payload={'title':'测试标题'},visual_brief={},final_cover_path=tmp_path/'output'/'cover-guard_cover.jpg',
        provenance_path=tmp_path/'output'/'cover-guard_cover_provenance.json',brief_path=tmp_path/'output'/'brief.json',
        content_aware=False,generation_deadline_minutes=32,fallback_after_minutes=34,primary_provider='agy',
        enable_luna_fallback=luna,now=datetime.now(timezone.utc)-timedelta(minutes=age))
    db=PipelineDB(str(tmp_path/'pipeline.db'));db.add_video('cover-guard','Title','channel',score=88)
    db.update_video_status('cover-guard','AI_COVER_PENDING')
    monkeypatch.setattr(reconciler,'PROJECT_ROOT',tmp_path)
    monkeypatch.setattr(reconciler,'LOCK_PATH',tmp_path/'queue.lock')
    monkeypatch.setattr(reconciler,'settings',SimpleNamespace(enable_codex_cover_queue=True,
        ai_cover_primary_provider='agy',ai_cover_queue_dir='queue',ai_cover_finish_dir='finish',
        enable_antigravity_cover_fallback=False))
    monkeypatch.setattr(reconciler,'PipelineDB',lambda:db)
    return queue,task,db


def test_luna_eligible_task_records_distinct_source(tmp_path, monkeypatch):
    queue, task, db = setup_task(tmp_path, monkeypatch, luna=True)
    (task.finish_dir / 'antigravity_attempt.json').write_text(json.dumps({'status':'failed','attempt_number':3}))
    reconciler.settings.enable_codex_luna_cover_fallback = True
    reconciler.settings.codex_luna_cover_timeout_seconds = 180
    reconciler.settings.codex_luna_cover_review_timeout_seconds = 60
    calls = []

    def fake_luna(item):
        calls.append(item.task_id)
        visual = item.finish_dir / 'visual.png'
        Image.new('RGB',(768,1024),'blue').save(visual)
        digest = hashlib.sha256(visual.read_bytes()).hexdigest()
        review = {'image_inspected': True, 'subject_relevant': True,
                  'composition_complete': True, 'adequate_detail': True,
                  'no_severe_artifacts': True, 'decision': 'PASS',
                  'observed_content': '芯片制造', 'reason': '题材贴合'}
        receipt = {'task_id':item.task_id,'generated_by':'codex_luna_imagegen',
                   'completed_at':datetime.now(timezone.utc).isoformat(),
                   'visual_filename':'visual.png','sha256':digest,'uses_video_frame':False,
                   'transport':'codex_cli','model':'gpt-5.6-luna','reasoning_effort':'none',
                   'machine_visual_review':'codex-luna-cover-quality-v1',
                   'quality_review':{'version':'codex-luna-cover-quality-v1',
                                     'provider':'codex_cli_independent','task_id':item.task_id,
                                     'sha256':digest,'review':review}}
        (item.finish_dir/'result.json').write_text(json.dumps(receipt))

    monkeypatch.setattr(reconciler,'_run_luna',fake_luna)
    monkeypatch.setattr(reconciler,'run_process',renderer)
    assert reconciler.reconcile()==1
    assert calls == [task.task_id]
    assert json.loads((task.finish_dir/'resolution.json').read_text())['source']=='codex_luna_ai_visual'
    assert db.get_video_by_youtube_id('cover-guard')['status']=='PENDING'


def renderer(command, **kwargs):
    output=Path(command[command.index('--output')+1])
    prov=Path(command[command.index('--provenance-output')+1])
    output.write_bytes(b'simulated-renderer-only')
    prov.write_text(json.dumps(dict(cover_kind='dedicated_generated_image',uses_video_frame=False,
        cover_filename=output.name,cover_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
        layout_policy=compliant_cover_layout_policy())))
    return SimpleNamespace(returncode=0,stderr='',stdout='')


@pytest.mark.parametrize('age,attempts',[(0,3),(33,0)])
def test_exhaustion_or_deadline_renders_fallback_once(tmp_path,monkeypatch,age,attempts):
    queue,task,db=setup_task(tmp_path,monkeypatch,age)
    if attempts:
        (task.finish_dir/'antigravity_attempt.json').write_text(json.dumps({'status':'failed','attempt_number':attempts}))
    calls=[]
    def render(*args,**kwargs):
        calls.append(1);return renderer(*args,**kwargs)
    monkeypatch.setattr(reconciler,'run_process',render)
    assert reconciler.reconcile()==1
    assert db.get_video_by_youtube_id('cover-guard')['status']=='PENDING'
    assert db.get_video_by_youtube_id('cover-guard')['preparation_ready']==1
    receipt=json.loads((task.finish_dir/'resolution.json').read_text())
    assert receipt['source']=='deterministic_fallback'
    assert receipt['cover_sha256']
    assert reconciler.reconcile()==0
    assert len(calls)==1


def test_failed_fallback_is_visible_and_not_hot_retried(tmp_path,monkeypatch):
    queue,task,db=setup_task(tmp_path,monkeypatch,33)
    calls=[]
    def broken(*a,**kw):
        calls.append(1);raise RuntimeError('PROCESS_TIMEOUT: budget=90s')
    monkeypatch.setattr(reconciler,'run_process',broken)
    assert reconciler.reconcile()==0
    assert '兜底失败' in db.get_video_by_youtube_id('cover-guard')['error_msg']
    assert reconciler.reconcile()==0
    assert len(calls)==1
    assert not (task.finish_dir/'resolution.json').exists()


def test_resolution_recovers_db_after_interruption_and_checks_hash(tmp_path,monkeypatch):
    queue,task,db=setup_task(tmp_path,monkeypatch,33)
    monkeypatch.setattr(reconciler,'run_process',renderer)
    assert reconciler.reconcile()==1
    db.update_video_status('cover-guard','AI_COVER_PENDING')
    assert reconciler.reconcile()==1
    db.update_video_status('cover-guard','AI_COVER_PENDING')
    Path(task.payload['final_cover_path']).write_bytes(b'tampered')
    assert reconciler.reconcile()==0
    assert db.get_video_by_youtube_id('cover-guard')['status']=='AI_COVER_PENDING'


@pytest.mark.parametrize('status',['PUBLISHED','PUBLISHING','UNDER_REVIEW','IGNORED'])
def test_existing_status_cannot_be_requeued_or_overwritten(tmp_path,monkeypatch,status):
    queue,task,db=setup_task(tmp_path,monkeypatch,33)
    db.update_video_status('cover-guard',status)
    monkeypatch.setattr(reconciler,'run_process',lambda *a,**kw:pytest.fail('renderer called'))
    assert reconciler.reconcile()==0
    assert reconciler._render(task,None,db) is False
    assert db.get_video_by_youtube_id('cover-guard')['status']==status


def test_live_worker_lock_blocks_fallback_without_terminal_failure(tmp_path,monkeypatch):
    queue,task,db=setup_task(tmp_path,monkeypatch,33)
    with (task.finish_dir/'worker.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        assert reconciler.reconcile()==0
    assert not (task.finish_dir/'fallback_attempt.json').exists()
    assert db.get_video_by_youtube_id('cover-guard')['status']=='AI_COVER_PENDING'


def test_old_agy_pending_not_implicitly_released_by_upgrade(tmp_path,monkeypatch):
    queue,task,db=setup_task(tmp_path,monkeypatch,33)
    task.path.write_text(task.path.read_text().replace('"quality_contract": "agy-cover-quality-v1"','"quality_contract": "legacy"'))
    assert reconciler.reconcile()==0
    assert db.get_video_by_youtube_id('cover-guard')['status']=='AI_COVER_PENDING'


def test_reconciler_global_lock_skips_second_run(tmp_path,monkeypatch):
    queue,task,db=setup_task(tmp_path,monkeypatch,33)
    with reconciler.LOCK_PATH.open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        assert reconciler.reconcile()==0


def test_submission_ledger_blocks_stale_pending_status(tmp_path,monkeypatch):
    queue,task,db=setup_task(tmp_path,monkeypatch,33)
    db.record_wechat_submission_attempt('cover-guard',evidence_path='shadow-submission')
    assert not db.can_resolve_ai_cover('cover-guard')
    assert not db.mark_ai_cover_resolved('cover-guard')
    monkeypatch.setattr(reconciler,'run_process',lambda *a,**kw:pytest.fail('renderer called'))
    assert reconciler.reconcile()==0
    assert reconciler._render(task,None,db) is False
    assert db.get_video_by_youtube_id('cover-guard')['status']=='AI_COVER_PENDING'


def test_worker_launch_failures_count_toward_fallback(tmp_path,monkeypatch):
    queue,task,db=setup_task(tmp_path,monkeypatch)
    for count in range(1,4):
        reconciler._run_antigravity(task)
        assert json.loads((task.finish_dir/'antigravity_attempt.json').read_text())['attempt_number']==count
    assert queue.should_fallback(task)


def test_ai_layout_failure_also_uses_local_fallback(tmp_path,monkeypatch):
    queue,task,db=setup_task(tmp_path,monkeypatch)
    monkeypatch.setattr(AICoverQueue,'accepted_visual',lambda *a:Path('accepted.png'))
    calls=[]
    def render(command,**kwargs):
        calls.append(command)
        if len(calls)==1:
            raise RuntimeError('PROCESS_TIMEOUT')
        return renderer(command,**kwargs)
    monkeypatch.setattr(reconciler,'run_process',render)
    assert reconciler.reconcile()==1
    assert len(calls)==2
    assert json.loads((task.finish_dir/'resolution.json').read_text())['source']=='deterministic_fallback'


def test_interrupted_final_attempt_falls_back_after_claim_expires(tmp_path,monkeypatch):
    queue,task,db=setup_task(tmp_path,monkeypatch)
    (task.finish_dir/'antigravity_attempt.json').write_text(json.dumps({'status':'running','attempt_number':3}))
    monkeypatch.setattr(reconciler,'run_process',renderer)
    assert reconciler.reconcile()==1
    assert db.get_video_by_youtube_id('cover-guard')['status']=='PENDING'


def test_cli_success_exit_is_not_the_resolved_count(monkeypatch):
    monkeypatch.setattr(reconciler,'reconcile',lambda:3)
    assert reconciler.main()==0


def test_async_cover_wait_has_no_required_pid_and_survives_orphan_reaper(tmp_path,monkeypatch):
    queue,task,db=setup_task(tmp_path,monkeypatch,33)
    with db.get_connection() as conn:
        conn.execute("UPDATE processed_videos SET updated_at=datetime('now','-2 hours') WHERE youtube_id='cover-guard'")
    assert db.get_stale_pre_submission_processing_videos(stale_minutes=20)==[]
    assert db.recover_orphaned_pre_submission_task('cover-guard',expected_process_pid=None,error_msg='worker gone') is None
    monkeypatch.setattr(reconciler,'run_process',renderer)
    assert reconciler.reconcile()==1
    assert db.get_video_by_youtube_id('cover-guard')['status']=='PENDING'
