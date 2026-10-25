"""商品恢复的真实 DAL、旧证据拒绝与一次性并发领取回归。"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from config.settings import settings
from video_processing.db.database import PipelineDB
from video_processing.english_world.package_integrity import calculate_package_hashes
from video_processing.core.wechat_product_attachment import attachment_decision
from video_processing.utils.wechat_product_config import load_policy, decision_payload
from video_processing.utils.wechat_product_task import freeze_task_product_decision, PUBLISHER_CAPABILITY


@pytest.fixture
def blocked(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'wechat_operations_enabled', False)
    db = PipelineDB(str(tmp_path / 'pipeline.db'))
    paths = {}
    for field in ('mp4_path', 'manifest_path', 'title_path', 'copy_path', 'cover_path', 'cover_provenance_path'):
        path = tmp_path / field
        path.write_text('{}' if field == 'manifest_path' else field)
        paths[field] = str(path)
    item = db.create_english_world_review_item(title='商品故障恢复测试', **paths, **calculate_package_hashes(paths))
    db.approve_english_world_submission(item['id'], authorization='AUTO_POLICY')
    context = dict(task_id='original', production_task_id='original', review_id=item['id'],
                   content_type='ENGLISH_WORLD_SHORT', product_intent='AUTO')
    active = Path(__file__).parents[2] / 'config/wechat_products.json'
    policy = load_policy(active)
    selection = policy.decide(content_type='ENGLISH_WORLD_SHORT')
    old = dict(attachment_decision(context, None), task_id='original', context=context,
               frozen_at=datetime.now(timezone.utc).isoformat(), publisher_capability=PUBLISHER_CAPABILITY,
               policy_snapshot=json.loads(policy.serialized), config_version=policy.version, config_digest=policy.digest,
               product_decision=decision_payload(replace(selection, reason='ENGLISH_WORLD_REQUIRED', candidates=selection.candidates[:1])))
    old.update(attachment_version='wechat-english-all-v1', reason='ATTACH_ENGLISH_ALL')
    db.freeze_product_task_decision('original', old)
    for index in range(3):
        evidence = tmp_path / f'evidence-{index}'
        evidence.mkdir()
        claim = db.claim_english_world_submission(item['id'], evidence_dir=str(evidence))
        receipt = dict(required=True, binding_confirmed=False, state='BLOCKED',
                       reason='PRODUCT_CLEANUP_OPERATION_TIMEOUT', task_id='original', config_digest=policy.digest)
        wait = dict(not_submitted=True, submission_state='NOT_SUBMITTED', reason=receipt['reason'],
                    task_key='original', config_digest=policy.digest)
        progress = dict(version=1, video=paths['mp4_path'], submit_intent=False)
        for name, value in [('product_selection_receipt.json',receipt),('product_wait.json',wait),('submission_progress.json',progress)]:
            (evidence / name).write_text(json.dumps(value))
        assert db.defer_english_world_product_wait(item['id'], attempt_id=claim['_attempt_id'],
                  evidence_dir=str(evidence), receipt=receipt, wait_evidence=wait)
    new_context = dict(context, task_id='english-product-recovery:' + item['id'])
    new = freeze_task_product_decision(db, new_context['task_id'], new_context, active)
    monkeypatch.setattr(settings, 'wechat_operations_enabled', True)
    return db, item['id'], old, new, tmp_path


def authorize(blocked):
    db, key, old, new, _ = blocked
    return db.authorize_english_world_product_recovery(key, reason='用户批准修复后恢复一轮重发',
                                                     source_decision=old, decision=new)


def test_exhausted_automatic_budget_gets_exactly_one_new_claim_without_reset(blocked):
    db, key, old, new, _ = blocked
    before = db.list_english_world_submission_attempts(key)
    assert db.claim_english_world_submission(key) is None
    authorized = authorize(blocked)
    assert authorized['approval_source'] == 'OPERATOR_RECOVERY'
    assert db.get_next_auto_approved_english_world_submission() is None
    assert db.get_product_task_decision('original') == old
    assert new['attachment_version'] == 'wechat-english-preferred-v1'
    with ThreadPoolExecutor(max_workers=4) as pool:
        claims = list(pool.map(lambda _: db.claim_english_world_submission(key), range(4)))
    assert len([r for r in claims if r]) == 1
    grant = db.get_english_world_product_recovery(key)
    assert grant['consumed_at'] and grant['attempt_id']
    assert len(grant['payload']['attempts']) == 3
    assert all(r in db.list_english_world_submission_attempts(key) for r in before)
    with pytest.raises(ValueError):
        authorize(blocked)


@pytest.mark.parametrize('change', ['intent', 'receipt', 'wait', 'package', 'state', 'attempt', 'digest', 'decision'])
def test_uncertain_changed_or_foreign_evidence_rejects(blocked, change):
    db, key, old, new, root = blocked
    evidence = root / 'evidence-1'
    if change == 'intent':
        path = evidence / 'submission_progress.json'
        path.write_text(json.dumps(dict(json.loads(path.read_text()), submit_intent=True)))
    elif change == 'receipt':
        (evidence / 'submission_receipt.json').write_text('{}')
    elif change == 'wait':
        path = evidence / 'product_wait.json'
        path.write_text(json.dumps(dict(json.loads(path.read_text()), submission_state='UNCERTAIN')))
    elif change == 'package':
        (root / 'copy_path').write_text('已更改')
    elif change == 'decision':
        new['context']['youtube_id'] = 'another-video'
    else:
        with db.get_connection() as conn:
            if change == 'state':
                conn.execute("UPDATE english_world_review_items SET state='UNCERTAIN' WHERE id=?", (key,))
            elif change == 'attempt':
                conn.execute("UPDATE english_world_submission_attempts SET state='SUBMITTING' WHERE review_id=?", (key,))
            else:
                conn.execute("UPDATE english_world_submission_attempts SET artifact_sha256='changed' WHERE review_id=?", (key,))
    with pytest.raises((ValueError, FileNotFoundError)):
        authorize(blocked)
    assert db.get_english_world_product_recovery(key) is None


def test_expired_and_consumed_grant_cannot_claim_again(blocked):
    db, key, _, _, _ = blocked
    authorize(blocked)
    with db.get_connection() as conn:
        conn.execute("UPDATE english_world_product_recoveries SET expires_at=datetime('now','-1 minute') WHERE review_id=?", (key,))
    assert db.claim_english_world_submission(key) is None


def test_recovery_request_still_stops_before_authorization_and_uploader_on_content_gate(blocked, monkeypatch):
    from scripts import submit_english_world_review as submitter
    db, key, _, _, root = blocked
    (root / 'manifest_path').write_text(json.dumps({'content_type': 'ENGLISH_WORLD_SHORT'}))
    (root / 'title_path').write_text('习近平')
    monkeypatch.setattr(submitter, 'PipelineDB', lambda: db)
    monkeypatch.setattr(submitter, '_PROJECT_ROOT', root)
    def forbidden(*args, **kwargs):
        raise AssertionError('内容门禁未通过不得调用上传器')
    monkeypatch.setattr(submitter.subprocess, 'run', forbidden)
    assert submitter.submit(key, product_recovery_reason='用户批准修复后恢复一轮重发') == 1
    assert db.get_english_world_product_recovery(key) is None
    assert len(db.list_english_world_submission_attempts(key)) == 3


@pytest.fixture
def recovery_failure(blocked):
    db, key, old, new, root = blocked
    authorize(blocked)
    evidence = root / 'recovery-failure'
    evidence.mkdir()
    claim = db.claim_english_world_submission(key, evidence_dir=str(evidence))
    item = db.get_english_world_review_item(key)
    receipt = dict(required=True, binding_confirmed=False, state='BLOCKED',
        reason='PRODUCT_CLEANUP_OPERATION_TIMEOUT', task_id=new['task_id'], config_digest=new['config_digest'])
    wait = dict(not_submitted=True, submission_state='NOT_SUBMITTED', task_key=new['task_id'],
        config_digest=new['config_digest'], reason=receipt['reason'])
    for name, value in [('product_selection_receipt.json',receipt), ('product_wait.json',wait),
                        ('submission_progress.json', dict(version=1, video=item['mp4_path'], submit_intent=False))]:
        (evidence/name).write_text(json.dumps(value))
    assert db.defer_english_world_product_wait(key, attempt_id=claim['_attempt_id'],
        evidence_dir=str(evidence), receipt=receipt, wait_evidence=wait)
    with db.get_connection() as conn:
        conn.execute("UPDATE english_world_submission_attempts SET finished_at=datetime('now','-61 seconds') WHERE attempt_id=?", (claim['_attempt_id'],))
    context = dict(new['context'], task_id=new['task_id'] + ':technical-retry')
    retry = freeze_task_product_decision(db, context['task_id'], context,
        Path(__file__).parents[2] / 'config/wechat_products.json')
    return db, key, new, retry, evidence


def test_same_round_named_technical_continuation_preserves_consumed_grant(recovery_failure):
    db, key, source, retry, _ = recovery_failure
    before = db.get_english_world_product_recovery(key)
    db.authorize_english_world_product_recovery(key, reason='已修复原生不可售卖与占位结构，续跑同轮',
        source_decision=source, decision=retry)
    with ThreadPoolExecutor(max_workers=4) as pool:
        claims = list(pool.map(lambda _: db.claim_english_world_submission(key), range(4)))
    assert len([r for r in claims if r]) == 1
    after = db.get_english_world_product_recovery(key)
    assert after['consumed_at'] == before['consumed_at']
    assert after['attempt_id'] == before['attempt_id']
    assert after['expires_at'] == before['expires_at']
    assert after['payload']['technical_retry']['attempt_id'] != before['attempt_id']
    with pytest.raises(ValueError):
        db.authorize_english_world_product_recovery(key, reason='不许再次扩大次数', source_decision=source, decision=retry)


@pytest.mark.parametrize('change', ['intent', 'receipt', 'interval', 'package', 'uncertain'])
def test_continuation_still_requires_fresh_exact_unsubmitted_proof(recovery_failure, change):
    db, key, source, retry, evidence = recovery_failure
    if change == 'intent':
        path = evidence/'submission_progress.json'
        path.write_text(json.dumps(dict(json.loads(path.read_text()), submit_intent=True)))
    elif change == 'receipt':
        (evidence/'submission_receipt.json').write_text('{}')
    elif change == 'package':
        Path(db.get_english_world_review_item(key)['mp4_path']).write_text('changed')
    else:
        with db.get_connection() as conn:
            if change == 'interval':
                conn.execute("UPDATE english_world_submission_attempts SET finished_at=CURRENT_TIMESTAMP WHERE review_id=?", (key,))
            else:
                conn.execute("UPDATE english_world_review_items SET state='UNCERTAIN' WHERE id=?", (key,))
    with pytest.raises(ValueError):
        db.authorize_english_world_product_recovery(key, reason='用户授权同轮续跑', source_decision=source, decision=retry)
    assert 'technical_retry' not in db.get_english_world_product_recovery(key)['payload']
