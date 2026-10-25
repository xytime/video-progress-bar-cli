"""已批准漏扫补充规格：活动优先、公平回补与分页中断证据。

依赖：本测试 -> DAL / browser adapter；无外部平台写入。
# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1 | 2026-10-25 | Codex | 覆盖旧作品、活动冷却、公平性及真实游标有界续扫失败。 |
"""
from datetime import datetime, timezone, timedelta

from video_processing.db.database import PipelineDB
from video_processing.interaction.secondary_reply_browser_adapter import SecondaryReplyBrowserAdapter


def publication(db, suffix, *, age=0):
    db.add_video(suffix, suffix, 'ch_test', score=80)
    post = 'export/' + suffix
    db.record_wechat_publication_confirmation(suffix, evidence_path='fixture.json', platform_post_id=post)
    # 测试夹具可直接设置历史时间；业务层仍仅通过 DAL。
    with db.get_connection() as conn:
        conn.execute('UPDATE wechat_publications SET created_at=? WHERE platform_post_id=?',
                     ((datetime.now(timezone.utc)-timedelta(days=age)).strftime('%Y-%m-%d %H:%M:%S'), post))
        conn.commit()
    return post


def test_old_activity_and_fair_backfill_respect_cooling(tmp_path):
    db = PipelineDB(db_path=str(tmp_path/'pipeline.db'))
    now = datetime.now(timezone.utc)
    fair = publication(db, 'fair', age=30)
    active = publication(db, 'active', age=80)
    others = [publication(db, 'other'+str(i), age=200+i) for i in range(5)]
    db.record_comment_activity(account_key='acct', platform_post_id=active, comment_count=8, unread_count=1)
    due = db.get_due_comment_scan_posts(account_key='acct', limit=2, now_utc=now)
    assert due[0]['platform_post_id'] == fair
    assert due[1]['platform_post_id'] == active
    assert due[1]['scan_candidate_origin'] == 'native_activity'
    db.record_comment_scan_state(account_key='acct', platform_post_id=active,
        top_level_status='COMPLETE', complete=True, observed_comment_count=8,
        published_at_utc=(now-timedelta(days=80)).isoformat(), now_utc=now)
    db.record_comment_activity(account_key='acct', platform_post_id=active, comment_count=9)
    assert active not in {r['platform_post_id'] for r in db.get_due_comment_scan_posts(account_key='acct', limit=20, now_utc=now)}
    later = db.get_due_comment_scan_posts(account_key='acct', limit=2, now_utc=now+timedelta(hours=5))
    assert later[1]['platform_post_id'] == active
    assert not db.get_due_comment_scan_posts(account_key='acct', limit=20, max_age_days=14, now_utc=now)


def test_progress_and_failure_do_not_erase_prior_observation(tmp_path):
    db = PipelineDB(db_path=str(tmp_path/'pipeline.db'))
    db.record_comment_scan_state(account_key='a', platform_post_id='export/a', top_level_status='HAS_MORE',
        observed_comment_count=12, comment_cursor='opaque-12')
    db.record_comment_scan_state(account_key='a', platform_post_id='export/a', top_level_status='INCOMPLETE',
        last_error='HTTP_TIMEOUT', comment_cursor='opaque-12')
    state = db.get_comment_scan_state('a', 'export/a')
    assert state['comment_cursor'] == 'opaque-12'
    assert state['observed_comment_count'] == 12
    assert state['last_complete_scan_at'] is None
    db.record_comment_scan_state(account_key='a', platform_post_id='export/a', top_level_status='COMPLETE', complete=True)
    assert db.get_comment_scan_state('a','export/a')['comment_cursor'] == ''


class NativePages:
    def __init__(self, responses):
        self.responses = responses
        self.cursors = []
    def evaluate(self, script, args):
        assert 'fetch(url' in script
        assert args['url'].startswith('https://channels.weixin.qq.com/')
        self.cursors.append(args['payload']['lastBuff'])
        result = self.responses[len(self.cursors)-1]
        if isinstance(result, Exception):
            raise result
        return {'status':201, 'payload':{'errCode':0, 'data':result}}


def body(cid, cursor, more=1):
    return {'comment':[{'commentId':str(cid),'commentContent':'example'}],
            'lastBuff':cursor,'downContinueFlag':more}


def adapter():
    a = SecondaryReplyBrowserAdapter()
    a._bound_scene_post_id='native-a'
    a._comment_request=('https://channels.weixin.qq.com/micro/interaction/cgi-bin/mmfinderassistant-bin/comment/comment_list',
        {'exportId':'native-a','lastBuff':'','commentSelection':False, 'nativeField':'preserved'})
    a._last_comment_list_payload={'errCode':0,'data':body(1,'opaque-1')}
    return a


def test_bounded_pagination_resumes_native_cursor_and_deduplicates():
    a=adapter(); page=NativePages([body(2,'opaque-2'),body(3,'opaque-3')])
    payload,error,pages=a._collect_comment_pages(page)
    assert pages==3 and error=='COMMENT_PAGE_BUDGET_EXHAUSTED'
    assert payload['data']['lastBuff']=='opaque-3'
    assert page.cursors==['opaque-1','opaque-2']
    page=NativePages([body(4,'',0)])
    payload,error,pages=a._collect_comment_pages(page,resume_cursor='opaque-3')
    assert page.cursors==['opaque-3'] and not error
    assert payload['data']['downContinueFlag']==0
    assert [r['commentId'] for r in payload['data']['comment']]==['1','4']


def test_error_repeat_cursor_and_wrong_identity_never_claim_complete():
    a=adapter(); page=NativePages([TimeoutError('bounded timeout')])
    payload,error,_=a._collect_comment_pages(page)
    assert error and payload['data']['downContinueFlag']==1
    assert payload['data']['lastBuff']=='opaque-1'
    payload,error,_=a._collect_comment_pages(NativePages([body(2,'opaque-1')]))
    assert error=='COMMENT_CURSOR_MISSING_OR_REPEATED'
    a._bound_scene_post_id='another-post'
    page=NativePages([])
    assert a._collect_comment_pages(page)[0] is None
    assert not page.cursors


def test_comment_page_hint_is_account_scoped_and_new_author_observation_is_preserved(tmp_path):
    db=PipelineDB(db_path=str(tmp_path/'pipeline.db'))
    comment={'comment_id':'root','nickname':'reader','content':'same',
             'source_page_cursor':'native-page-four'}
    db.save_discovered_audience_comments('export/post',[comment],account_key='a')
    assert db.get_audience_comment('a','export/post','root')['source_page_cursor']=='native-page-four'
    assert db.get_audience_comment('other','export/post','root') is None
    db.save_discovered_audience_comments('export/post',[dict(comment,has_author_reply=True)],account_key='a')
    db.save_discovered_audience_comments('export/post',[comment],account_key='a')
    assert db.get_audience_comment('a','export/post','root')['has_author_reply']==1
    assert not db.get_unprocessed_audience_comments(account_key='a')
