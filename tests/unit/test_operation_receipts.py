"""回执持久性、认证新鲜度和投稿分类；全部使用隔离数据库和文件。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0 | 2026-10-25 | Codex | 覆盖只读回执、坏缓存、旧尝试、切片与投稿证据绑定。 |
"""
import json
import pytest
from video_processing.core.operation_receipts import review_receipt, submission_feedback
from video_processing.db.database import PipelineDB
from video_processing.utils.agy_background_auth import auth_snapshot, auth_ready, AgyAuthUnavailable


def test_receipt_requires_both_audit_and_enabled_flag_and_is_readonly(tmp_path):
    db = PipelineDB(str(tmp_path / 'pipeline.db'))
    db.add_video('subject', 'test', 'channel')
    assert review_receipt(db, 'missing')['state'] == 'NOT_FOUND'
    assert review_receipt(db, 'subject')['state'] == 'NOT_SAVED'
    db.set_bypass_censorship('subject', True)
    assert review_receipt(db, 'subject')['state'] == 'UNVERIFIED'
    incident = db.record_censorship_incident('subject', slice_index=0, stage='manual_review',
        level='CP', tag='CP', score=None, matched='test', channel='operator', action='MANUAL_BYPASS', decision='MANUAL_CP_APPROVED', input_hash='input', rule_pack_version='rule')
    before = db.get_video_by_youtube_id('subject')
    receipt = review_receipt(db, 'subject')
    assert receipt['state'] == 'SAVED' and receipt['approval']['id'] == incident
    assert receipt['approval']['input_hash'] == 'input'
    assert review_receipt(db, 'subject', 1)['state'] == 'NOT_FOUND'
    assert db.get_video_by_youtube_id('subject') == before


@pytest.mark.parametrize('raw', ['bad', '[]', '{"status":"READY"}',
    '{"status":"READY","checked_at":"bad"}', '{"status":"READY","checked_at":2000}',
    '{"status":"READY","checked_at":NaN}'])
def test_bad_or_old_auth_cannot_claim_login_status(tmp_path, raw):
    path = tmp_path / 'auth.json'; path.write_text(raw)
    assert auth_snapshot(path, now=1000)['status'] == 'UNKNOWN'


def test_fresh_auth_cache_force_recheck_and_unknown_is_not_login_required(tmp_path):
    path = tmp_path / 'auth.json'; calls = []; notices = []
    def probe(): calls.append(1)
    assert auth_ready(path, check=probe, notify=notices.append, now=1000)
    assert auth_ready(path, check=probe, notify=notices.append, now=1001)
    assert len(calls) == 1
    assert auth_snapshot(path, now=1300)['status'] == 'UNKNOWN'
    def broken(): raise AgyAuthUnavailable('check failed')
    assert not auth_ready(path, check=broken, notify=lambda: notices.append(1), now=1002, force=True)
    assert auth_snapshot(path, now=1002)['status'] == 'UNKNOWN'
    assert not notices


def make_attempt(tmp_path, index=0, number='100'):
    prefix = 'subject' + (f'_s{index}' if index else '')
    evidence = tmp_path / 'wechat_evidence' / prefix / number; evidence.mkdir(parents=True)
    video = str(tmp_path / f'{prefix}_vertical_interactive.mp4')
    attempt = dict(video=video, submit_click_returned=True, draft_requested=False,
        platform_result='UNVERIFIED', manual_confirmation_required=True, automatic_result_queries=False,
        recorded_at=1234)
    (evidence / 'submission_attempt.json').write_text(json.dumps(attempt))
    (evidence / 'submission_progress.json').write_text(json.dumps(dict(video=video, submit_intent=True)))
    return evidence, attempt


@pytest.mark.parametrize('index', [0, 1])
def test_submission_manual_wait_requires_latest_attempt_and_exact_slice(tmp_path, index):
    evidence, _ = make_attempt(tmp_path, index)
    assert submission_feedback(tmp_path, 'subject', index)['kind'] == 'MANUAL_CONFIRMATION_REQUIRED'
    assert submission_feedback(tmp_path, 'subject', 1-index)['kind'] == 'RESULT_UNKNOWN'
    (evidence.parent / '200').mkdir()
    assert submission_feedback(tmp_path, 'subject', index)['kind'] == 'RESULT_UNKNOWN'


@pytest.mark.parametrize('changes', [dict(video='/other/video.mp4'), dict(submit_click_returned=False),
    dict(automatic_result_queries=True), dict(draft_requested=True), dict(platform_result='ACCEPTED')])
def test_incomplete_or_wrong_submission_evidence_never_claims_expected_wait(tmp_path, changes):
    evidence, attempt = make_attempt(tmp_path); attempt.update(changes)
    (evidence / 'submission_attempt.json').write_text(json.dumps(attempt))
    assert submission_feedback(tmp_path, 'subject')['kind'] == 'RESULT_UNKNOWN'
    assert submission_feedback(tmp_path, '../subject')['kind'] == 'RESULT_UNKNOWN'


def test_manual_auth_check_does_not_consume_background_notification(tmp_path):
    from video_processing.utils.agy_background_auth import AgyAuthRequired
    path = tmp_path / 'auth.json'; notices = []
    def missing(): raise AgyAuthRequired('login required')
    assert not auth_ready(path, check=missing, notify=None, now=1000, force=True)
    assert auth_snapshot(path, now=1000)['status'] == 'AUTH_REQUIRED'
    assert not auth_ready(path, check=missing, notify=lambda: notices.append(1), now=1300)
    assert notices == [1]


def test_submission_does_not_follow_evidence_file_outside_attempt(tmp_path):
    evidence, _ = make_attempt(tmp_path)
    original = evidence / 'submission_attempt.json'
    outside = tmp_path / 'outside.json'; original.rename(outside); original.symlink_to(outside)
    assert submission_feedback(tmp_path, 'subject')['kind'] == 'RESULT_UNKNOWN'


def test_manual_confirmation_retains_real_evidence_and_uncertain_ledger(tmp_path):
    from video_processing.pipeline_manager import PipelineManager
    evidence, _ = make_attempt(tmp_path)
    manager = PipelineManager.__new__(PipelineManager)
    manager.db = PipelineDB(str(tmp_path / 'pipeline.db'))
    manager.db.add_video('subject', 'Test', 'channel', score=100)
    manager._OUT_DIR = tmp_path; manager._PRJ_ROOT = tmp_path
    messages = []; manager.send_telegram_msg = messages.append
    receipt = evidence / 'submission_attempt.json'
    manager._mark_wechat_submission_under_review('subject', 'subject',
        evidence_path=receipt, reason='等待人工确认投稿结果')
    publication = manager.db.get_wechat_publication('subject')
    assert publication['state'] == 'UNCERTAIN'
    assert publication['evidence_path'] == str(receipt)
    assert messages and '等待人工确认投稿结果' in messages[0]
    assert '后台核验按钮' not in messages[0]
