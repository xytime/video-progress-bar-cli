"""恢复入口的范围与预算：有限多上下文回读，不扩大到其他作品或无限请求。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-23 | Codex | 验证作品筛选、零对账上限和每上下文及工作流总预算。 |
"""
from types import SimpleNamespace
import pytest
from config.settings import settings
from tests.unit.test_wechat_hardening import account
from tests.unit.secondary_reply_support import approved_task, TEST_ACCOUNT
from video_processing.core.wechat_session_lock import WeChatSessionLock, guard_wechat_context
from video_processing.db.database import PipelineDB


@pytest.mark.parametrize('purpose,contexts', [('评论', 2), ('回复', 3), ('发布', 1)])
def test_workflow_and_context_budgets(account, monkeypatch, purpose, contexts):
    monkeypatch.setattr(settings, 'wechat_interaction_list_request_budget', 2)
    class Context:
        def on(self, name, fn):
            pass
        def route(self, pattern, fn):
            self.handler = fn
    calls = []
    route = SimpleNamespace(request=SimpleNamespace(url='https://channels.weixin.qq.com/a/post/post_list'),
                            abort=lambda: calls.append('abort'), continue_=lambda: calls.append('send'))
    with WeChatSessionLock(account, purpose=purpose, video='export/one'):
        for _ in range(contexts):
            ctx = Context()
            guard_wechat_context(ctx)
            for _ in range(3):
                ctx.handler(route)
            assert calls[-3:] == ['send', 'send', 'abort']
        ctx = Context()
        guard_wechat_context(ctx)
        ctx.handler(route)
        assert calls[-1] == 'abort'
    assert calls.count('send') == 2 * contexts


def test_queries_stay_on_explicit_post_and_zero_reconcile_is_empty(tmp_path):
    db = PipelineDB(str(tmp_path / 'scope.sqlite'))
    ids = [approved_task(db, platform_post_id='export/' + name, comment_id=name,
                         chinese_reply='谢谢分享。', english_reply='Thanks.') for name in ('a', 'b')]
    assert [r['id'] for r in db.get_approved_secondary_reply_tasks(
        account_key=TEST_ACCOUNT, platform_post_id='export/a')] == ids[:1]
    with db.get_connection() as conn:
        conn.execute("UPDATE wechat_secondary_reply_tasks SET status='UNCERTAIN'")
    assert [r['id'] for r in db.get_due_uncertain_secondary_reply_tasks(
        account_key=TEST_ACCOUNT, platform_post_id='export/b')] == ids[1:]
    assert db.get_due_uncertain_secondary_reply_tasks(limit=0) == []


def test_six_hour_queue_does_not_starve_half_hour_reply_worker(monkeypatch):
    from video_processing.core.wechat_account_schedule import admission
    monkeypatch.setattr(settings, 'wechat_scheduler_priority_video', '')
    monkeypatch.setattr(settings, 'wechat_scheduler_daily_limit', 20)
    row = {'next_session_at': 0}
    base = 1000000
    assert admission(row, base, '评论', 'first', consume=True) == ''
    for minute in range(1, 360):
        now = base + minute * 60
        assert admission(row, now, '评论', 'second')
        if minute % 30 == 0:
            assert admission(row, now, '回复', 'audience')
    assert admission(row, base + 21600, '评论', 'second', consume=True) == ''
    for minute in range(360, 720):
        now = base + minute * 60
        assert admission(row, now, '评论', 'third')
        if minute % 30 == 0:
            assert admission(row, now, '回复', 'audience')
    assert '排队' in admission(row, base + 43200, '评论', 'third')
    assert admission(row, base + 43200, '回复', 'audience', consume=True) == ''
