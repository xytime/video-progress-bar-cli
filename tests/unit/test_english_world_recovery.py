"""独立英语世界停更回归；真实DAL/持久记录，所有平台与通知只用隔离适配器。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-24 | Codex | 覆盖库存失真、清理超时恢复预算、跨重启轮换、并发领取和未知提交保护。 |
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import importlib
import json
from types import SimpleNamespace
import subprocess
import sys

import pytest

from config.settings import settings
from scripts import run_ready_publications as ready
from video_processing.db.database import PipelineDB
from video_processing.english_world.delivery_health import delivery_health
from video_processing.utils.wechat_product_execution import _wait_row_ready, product_wait_ready
from video_processing.utils.wechat_product_waits import ProductWaitStore


def item(db, number, authorization='AUTO_POLICY', *, package=None):
    digest = f'{number:064x}'
    row = db.create_english_world_review_item(
        artifact_sha256=digest, title=f'英语学习 {number}', mp4_path=str(package/'english_world.mp4') if package else f'/{number}.mp4',
        manifest_path='/manifest.json', title_path='/title.txt', copy_path='/copy.txt',
        cover_path='/cover.jpg', cover_provenance_path='/provenance.json',
        manifest_sha256=digest, title_sha256=digest, copy_sha256=digest,
        cover_sha256=digest, cover_provenance_sha256=digest)
    if authorization:
        row = db.approve_english_world_submission(row['id'], authorization=authorization)
    return row


def test_inventory_matches_runnable_auto_queue_and_dependency_reentry(tmp_path):
    path = tmp_path/'pipeline.db';db = PipelineDB(str(path))
    good = item(db, 1);blocked = item(db, 2);manual = item(db, 3, 'TELEGRAM_REVIEW');item(db, 4, None)
    db.freeze_product_task_decision('product:blocked', {'frozen_at':'2026-10-24', 'context':{'review_id':blocked['id']}})
    db.freeze_product_task_decision('product:good', {'frozen_at':'2026-10-24', 'context':{'review_id':good['id']}})
    assert db.get_english_world_inventory_count(excluded_product_tasks=['product:blocked']) == 1
    assert db.get_next_auto_approved_english_world_submission(excluded_product_tasks=['product:blocked'])['id'] == good['id']
    # 商品依赖恢复仅改变候选资格，不改批准/内容或人工项；重开DAL仍读相同持久状态。
    restarted = PipelineDB(str(path))
    assert restarted.get_english_world_inventory_count() == 2
    assert restarted.get_english_world_review_item(manual['id'])['approval_source'] == 'TELEGRAM_REVIEW'


def deferred(tmp_path, *, reason='PRODUCT_CLEANUP_BUDGET_EXHAUSTED', count=1, state='BLOCKED'):
    store = ProductWaitStore(tmp_path/'wechat_product_waits.json', clock=lambda:1000)
    row = store.defer('english:test', reason=reason, config_digest='config', artifacts_digest='artifact',
                      submission_state='NOT_SUBMITTED', observation_generation='old', count_failed_attempt=True)
    row.update(state=state, checks=count)
    return row


def test_legacy_cleanup_timeout_reenters_only_after_backoff_and_respects_restart_budget(tmp_path):
    row = deferred(tmp_path)
    assert not _wait_row_ready(row, row['next_check_at']-1, 'old')
    assert _wait_row_ready(json.loads(json.dumps(row)), row['next_check_at'], 'old')
    row['checks'] = row['wait_policy']['max_checks']
    assert not _wait_row_ready(row, row['next_check_at']+86400, 'old')
    assert _wait_row_ready(row, row['next_check_at']+86400, 'new')
    row['submission_state'] = 'UNKNOWN'
    assert not _wait_row_ready(row, row['next_check_at']+86400, 'new')


@pytest.mark.parametrize('reason', ['BINDING_IDENTITY_CONFLICT','CANNOT_CONFIRM_CLEARED','RESIDUAL_LINK_AFTER_CANCEL','PRODUCT_CLEANUP_ERROR:ValueError'])
def test_unsafe_product_failures_are_not_reopened_by_dependency_change(tmp_path, reason):
    row = deferred(tmp_path, reason=reason)
    assert not _wait_row_ready(row, row['next_check_at']+86400, 'new')


def test_cleanup_retry_keeps_artifact_and_live_owner_guards(tmp_path):
    row = deferred(tmp_path)
    row['lease_until'] = 100000
    assert not _wait_row_ready(row, 99999, 'new')
    assert not product_wait_ready({'task_id':'english:test'}, tmp_path, 'changed', clock=lambda:999999)
    assert json.loads((tmp_path/'wechat_product_waits.json').read_text())['tasks']['english:test']['checks'] == 1


def test_new_cleanup_failure_uses_persisted_eight_check_budget_without_reset(tmp_path):
    now=[1000];store=ProductWaitStore(tmp_path/'wait.json', clock=lambda:now[0])
    for n in range(1,9):
        row=store.defer('task',reason='PRODUCT_CLEANUP_BUDGET_EXHAUSTED',config_digest='c',artifacts_digest='a',
                        submission_state='NOT_SUBMITTED',observation_generation='same',count_failed_attempt=True)
        assert row['checks']==n
        assert row['state']==('WAITING' if n<8 else 'CHECK_LIMIT')
        now[0]=row['next_check_at']
        # Simulate machine restart without resetting budget.
        store=ProductWaitStore(store.path,clock=lambda:now[0])
    assert not _wait_row_ready(row,now[0]+86400,'same')


def test_domain_turn_survives_process_restart_and_does_not_starve_general(tmp_path, monkeypatch):
    code = ('from pathlib import Path; from types import SimpleNamespace; '
            'from scripts import run_ready_publications as r; '
            'r.dispatch_english_world_once=lambda _:print("english") or 1; '
            'r.dispatch_once=lambda _:print("general") or 1; '
            'r.dispatch_ready_round(SimpleNamespace(_OUT_DIR=Path(__import__("sys").argv[1])))')
    calls=[subprocess.check_output([sys.executable,'-c',code,str(tmp_path)],text=True).strip() for _ in range(4)]
    assert calls==['english','general','english','general']
    assert json.loads((tmp_path/'ready_publications.turn.json').read_text())['next']=='english_world'


def test_empty_or_quota_blocked_round_preserves_turn_and_claims_nothing(tmp_path, monkeypatch):
    manager=SimpleNamespace(_OUT_DIR=tmp_path);calls=[]
    monkeypatch.setattr(ready,'dispatch_english_world_once',lambda _:calls.append('english') or 0)
    monkeypatch.setattr(ready,'dispatch_once',lambda _:calls.append('general') or 0)
    assert ready.dispatch_ready_round(manager)==0
    assert not (tmp_path/'ready_publications.turn.json').exists()
    assert calls==['english','general']


def test_no_english_candidate_yields_opportunity_to_general(tmp_path, monkeypatch):
    manager=SimpleNamespace(_OUT_DIR=tmp_path);calls=[]
    monkeypatch.setattr(ready,'dispatch_english_world_once',lambda _:0)
    monkeypatch.setattr(ready,'dispatch_once',lambda _:calls.append('general') or 1)
    assert ready.dispatch_ready_round(manager)==1 and calls==['general']


def test_duplicate_claim_and_unknown_completion_stay_protected_after_restart(tmp_path):
    path=tmp_path/'pipeline.db';db=PipelineDB(str(path));row=item(db,12)
    with ThreadPoolExecutor(2) as pool:
        claims=list(pool.map(lambda _:PipelineDB(str(path)).claim_english_world_submission(row['id']),range(2)))
    claimed=[c for c in claims if c]
    assert len(claimed)==1
    db.complete_english_world_submission(row['id'],state='UNCERTAIN',uploader_exit_code=3,attempt_id=claimed[0]['_attempt_id'])
    restarted=PipelineDB(str(path))
    assert restarted.get_next_auto_approved_english_world_submission() is None
    assert restarted.get_english_world_inventory_count()==0
    assert restarted.claim_english_world_submission(row['id']) is None


def test_monitor_uses_local_acceptance_not_fresh_creation_or_uncertain_attempt(tmp_path):
    path=tmp_path/'pipeline.db';db=PipelineDB(str(path));row=item(db,18)
    fresh=delivery_health(path,now=datetime.now(timezone.utc))
    assert fresh['state']=='AWAITING_FIRST_ACCEPTANCE' and not fresh['stalled']
    claim=db.claim_english_world_submission(row['id'])
    db.complete_english_world_submission(row['id'],state='UNCERTAIN',uploader_exit_code=3,
                                        platform_post_id='export/unknown',attempt_id=claim['_attempt_id'])
    result=delivery_health(path,now=datetime.now(timezone.utc)+timedelta(hours=25))
    assert result['state']=='DELIVERY_STALLED' and result['last_accepted_receipt_at'] is None
    assert result['public_visibility']=='NOT_VERIFIED' and result['automatic_inventory']==0


def test_monitor_unknown_notification_never_claims_acceptance(tmp_path, monkeypatch):
    from scripts import monitor_english_world_daily as monitor
    import video_processing.telegram_delivery as telegram
    paths=monitor.MonitorPaths(tmp_path,tmp_path/'english_world_daily',tmp_path/'lock',tmp_path/'python',tmp_path/'runner')
    paths.log_dir.mkdir();PipelineDB(str(tmp_path/'pipeline.db'))
    monkeypatch.setattr(telegram,'send_text',lambda **_:telegram.TelegramDeliveryResult(state='UNKNOWN'))
    payload={'delivery_flow':{'state':'DELIVERY_STALLED','automatic_inventory':0,'blocked_automatic_inventory':0}}
    monitor.report_delivery_progress(paths,payload)
    assert payload['delivery_notification']['state']=='UNKNOWN'
    assert not (paths.log_dir/'delivery_watch.json').exists()


def test_monitor_notifies_once_on_actual_acceptance_recovery(tmp_path, monkeypatch):
    from scripts import monitor_english_world_daily as monitor
    import video_processing.telegram_delivery as telegram
    paths=monitor.MonitorPaths(tmp_path,tmp_path/'english_world_daily',tmp_path/'lock',tmp_path/'python',tmp_path/'runner')
    paths.log_dir.mkdir();PipelineDB(str(tmp_path/'pipeline.db'))
    watch=paths.log_dir/'delivery_watch.json';watch.write_text(json.dumps({'state':'DELIVERY_STALLED'}))
    calls=[]
    def notify(**kwargs):
        calls.append(kwargs)
        return telegram.TelegramDeliveryResult(state='ACCEPTED')
    monkeypatch.setattr(telegram,'send_text',notify)
    payload={'delivery_flow':{'state':'RECENT_LOCAL_ACCEPTANCE','last_accepted_receipt_at':'2026-10-24 03:00:00'}}
    monitor.report_delivery_progress(paths,payload);monitor.report_delivery_progress(paths,payload)
    assert len(calls)==1 and calls[0]['event_type']=='english_world.delivery_resumed'
    assert json.loads(watch.read_text())['state']=='RECENT_LOCAL_ACCEPTANCE'


def test_quota_blocks_real_dispatch_before_any_candidate_or_turn_change(tmp_path, monkeypatch):
    from video_processing.core.wechat_request_guard import WeChatRequestGuard
    manager=SimpleNamespace(_OUT_DIR=tmp_path,db=object())
    monkeypatch.setattr(WeChatRequestGuard,'evaluate',lambda *a,**k:{'allowed':False})
    monkeypatch.setattr(settings,'wechat_publishing_paused',False)
    monkeypatch.setattr(settings,'enable_english_world_auto_publish',True)
    assert ready.dispatch_ready_round(manager)==0
    assert not (tmp_path/'ready_publications.turn.json').exists()


@pytest.mark.parametrize('finished', [True,False])
def test_actual_click_receipt_is_distinct_from_acceptance_and_never_reopens_unknown(tmp_path, finished):
    path=tmp_path/'pipeline.db';db=PipelineDB(str(path));package=tmp_path/'package'
    row=item(db,29,package=package);evidence=package/'wechat_evidence'/'attempt';evidence.mkdir(parents=True)
    claim=db.claim_english_world_submission(row['id'],evidence_dir=str(evidence));now=datetime.now(timezone.utc)
    receipt={'video':str(package/'english_world.mp4'),'submit_click_returned':True,'draft_requested':False,
             'automatic_result_queries':False,'platform_result':'UNVERIFIED','recorded_at':now.timestamp()}
    (evidence/'submission_attempt.json').write_text(json.dumps(receipt))
    if finished:
        db.complete_english_world_submission(row['id'],state='UNCERTAIN',uploader_exit_code=3,
                                            attempt_id=claim['_attempt_id'],evidence_dir=str(evidence))
    result=delivery_health(path,now=now+timedelta(seconds=2))
    assert result['state']=='RECENT_SUBMIT_ACTION' and result['last_submit_action_at']
    assert result['last_accepted_receipt_at'] is None and result['public_visibility']=='NOT_VERIFIED'
    restarted=PipelineDB(str(path))
    assert restarted.get_next_auto_approved_english_world_submission() is None
    assert restarted.claim_english_world_submission(row['id']) is None
    assert restarted.get_english_world_review_item(row['id'])['state']==('UNCERTAIN' if finished else 'SUBMITTING')


@pytest.mark.parametrize('change', [{'draft_requested':True},{'video':'/other/video.mp4'},
                                    {'submit_click_returned':False},{'recorded_at':float('nan')}])
def test_intent_draft_wrong_package_or_bad_timestamp_is_not_real_send_evidence(tmp_path,change):
    path=tmp_path/'pipeline.db';db=PipelineDB(str(path));package=tmp_path/'package'
    row=item(db,30,package=package);evidence=package/'wechat_evidence'/'attempt';evidence.mkdir(parents=True)
    claim=db.claim_english_world_submission(row['id'],evidence_dir=str(evidence));now=datetime.now(timezone.utc)
    (evidence/'submission_progress.json').write_text(json.dumps({'submit_intent':True}))
    receipt={'video':str(package/'english_world.mp4'),'submit_click_returned':True,'draft_requested':False,
             'automatic_result_queries':False,'recorded_at':now.timestamp(),**change}
    (evidence/'submission_attempt.json').write_text(json.dumps(receipt))
    db.complete_english_world_submission(row['id'],state='UNCERTAIN',uploader_exit_code=3,attempt_id=claim['_attempt_id'])
    result=delivery_health(path,now=now+timedelta(seconds=2))
    assert result['last_submit_action_at'] is None and result['last_accepted_receipt_at'] is None
    assert result['state']=='AWAITING_FIRST_ACCEPTANCE'


def test_real_click_notification_does_not_claim_platform_acceptance(tmp_path,monkeypatch):
    from scripts import monitor_english_world_daily as monitor
    import video_processing.telegram_delivery as telegram
    paths=monitor.MonitorPaths(tmp_path,tmp_path/'english_world_daily',tmp_path/'lock',tmp_path/'python',tmp_path/'runner')
    paths.log_dir.mkdir();PipelineDB(str(tmp_path/'pipeline.db'))
    (paths.log_dir/'delivery_watch.json').write_text(json.dumps({'state':'DELIVERY_STALLED'}));calls=[]
    def notify(**kwargs):
        calls.append(kwargs);return telegram.TelegramDeliveryResult(state='ACCEPTED')
    monkeypatch.setattr(telegram,'send_text',notify)
    payload={'delivery_flow':{'state':'RECENT_SUBMIT_ACTION','last_submit_action_at':'2026-10-24T04:00:00Z'}}
    monitor.report_delivery_progress(paths,payload)
    assert '结果待确认' in calls[0]['text'] and '受理' not in calls[0]['text']


def test_known_acceptance_is_not_downgraded_to_click_only(tmp_path):
    path=tmp_path/'pipeline.db';db=PipelineDB(str(path));package=tmp_path/'package'
    row=item(db,31,package=package);evidence=package/'wechat_evidence'/'attempt';evidence.mkdir(parents=True)
    claim=db.claim_english_world_submission(row['id'],evidence_dir=str(evidence));now=datetime.now(timezone.utc)
    (evidence/'submission_attempt.json').write_text(json.dumps({'video':str(package/'english_world.mp4'),
        'submit_click_returned':True,'draft_requested':False,'automatic_result_queries':False,'recorded_at':now.timestamp()}))
    db.complete_english_world_submission(row['id'],state='UNDER_REVIEW',uploader_exit_code=6,
                                        attempt_id=claim['_attempt_id'],evidence_dir=str(evidence))
    result=delivery_health(path,now=now+timedelta(seconds=2))
    assert result['state']=='RECENT_LOCAL_ACCEPTANCE' and result['last_submit_action_at']
    assert result['last_accepted_receipt_at'] and result['public_visibility']=='NOT_VERIFIED'
