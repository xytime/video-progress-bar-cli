"""Independent review counterexamples; temporary snapshot only."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, BrokenBarrierError

from video_processing.db.database import PipelineDB
from video_processing.interaction.secondary_reply_approval import handle_approval_callback
from video_processing.interaction.secondary_reply_browser_adapter import SecondaryReplySubmissionGuard
from video_processing.interaction.secondary_reply_contract import AudienceCommentRecord, SecondaryReplyIntent
from video_processing.interaction.secondary_reply_service import SecondaryReplyService


def test_empty_callback_token_must_be_rejected(tmp_path):
    db = PipelineDB(str(tmp_path / 'probe.db'))
    task_id = db.create_or_update_secondary_reply_task(
        platform_post_id='export/review_probe', comment_id='root_1',
        intent='REPLY', style='MACRO', chinese_reply='谢谢分享。',
        english_reply='Thanks for sharing.', formatted_reply='谢谢分享。\nThanks for sharing.',
        provider='fixture', status='DRAFTED')
    expires = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
    assert db.bind_reply_task_approval_request(task_id, approval_token='unpredictable_fixture_token',
        expires_at_iso=expires, approver_id='123')
    result = handle_approval_callback(db, f'rep:{task_id}::app', '123', admin_ids_override='123')
    assert result[0] is False, f'Empty token unexpectedly consumed approval: {result}'


def test_missing_account_must_be_rejected():
    guard = SecondaryReplySubmissionGuard('export/review_probe', 'root_1', 'Approved text',
        expected_finder_id='approved_author@finder')
    request = SimpleNamespace(method='POST',
        url='https://channels.weixin.qq.com/cgi-bin/mmfinderassistant-bin/comment/create_comment',
        post_data_json={'exportId': 'export/review_probe', 'rootCommentId': 'root_1',
                       'replyCommentId': 'root_1', 'content': 'Approved text'})
    assert guard.capture_request(request) is False, 'Missing author identity passed guard'


def test_no_material_must_not_invent_transcript_evidence():
    comment = AudienceCommentRecord(platform_post_id='export/review_probe', comment_id='root_1',
        nickname='Fixture', content='为什么会出现这种情况？', content_hash='fixture', createtime='1791779000')
    draft = SecondaryReplyService().generate_draft(comment, video_context={})
    assert not (draft.intent == SecondaryReplyIntent.REPLY and draft.evidence_refs), (
        f'No source supplied, but reply invented evidence: {draft.evidence_refs}')


def test_two_workers_must_not_both_take_last_hourly_quota(tmp_path, monkeypatch):
    db = PipelineDB(str(tmp_path / 'quota.db'))
    # 固定时钟：上海 12:00，处于允许提交窗口内
    now = datetime(2026, 10, 12, 4, 0, 0, tzinfo=timezone.utc)
    from config.settings import settings
    monkeypatch.setattr(settings, 'wechat_reply_min_interval_seconds', 0, raising=False)
    earlier = (now - timedelta(minutes=6)).strftime('%Y-%m-%d %H:%M:%S')
    with db.get_connection() as conn:
        for i in range(9):
            conn.execute('INSERT INTO wechat_secondary_reply_idempotency_ledger '
                '(platform_post_id, root_comment_id, reply_comment_id, content_hash, status, created_at) '
                'VALUES (?, ?, ?, ?, ?, ?)', (f'export/older_{i}', f'old_{i}', f'reply_{i}', 'hash', 'VERIFIED', earlier))
    claims = []
    for i in range(2):
        task_id = db.create_or_update_secondary_reply_task(platform_post_id=f'export/new_{i}',
            comment_id=f'new_{i}', intent='REPLY', style='MACRO', chinese_reply='谢谢分享。',
            provider='fixture', status='APPROVED')
        claims.append(db.claim_approved_reply_task(task_id=task_id))
    original_check = db._check_reply_quota_conn
    barrier = Barrier(2)
    def check_then_wait(*args, **kwargs):
        result = original_check(*args, **kwargs)
        try:
            barrier.wait(timeout=1)  # 正确实现下对方被写锁阻塞，屏障必然超时，属预期
        except BrokenBarrierError:
            pass
        return result
    monkeypatch.setattr(db, '_check_reply_quota_conn', check_then_wait)
    def reserve(claim):
        return db.record_secondary_reply_submit_intent(claim['id'], claim['lease_token'],
            now_utc=now.strftime('%Y-%m-%d %H:%M:%S'))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, claims))
    assert sum(bool(result[0]) for result in results) <= 1, f'Both workers consumed last quota slot: {results}'
