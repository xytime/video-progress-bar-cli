"""原生游标导航缓存的隔离、失效与有界性。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| reply-cursor-v1 | 2026-10-25 | Codex | 真实临时文件验证导航缓存不跨凭据/筛选复用，并且不保存正文。 |
"""
import json

from video_processing.interaction.secondary_reply_list_cursor import CommentListCursor


def response(description='完整发布文案', cursor='opaque-next'):
    return {'errCode': 0, 'data': {'list': [{'objectId': 'native-1', 'desc': {'description': description}}], 'lastBuff': cursor}}


def test_cursor_resume_target_consumption_and_reobservation(tmp_path):
    cache = CommentListCursor(tmp_path/'state.json', 'generation-1', {'onlyUnread': False})
    assert cache.start('export/unknown', '') == ('', True)
    cache.observe('opaque-page', response(), advance=True)
    assert cache.start('export/unknown', '') == ('opaque-next', True)
    assert cache.start('export/original', '完整发布文案') == ('opaque-page', False)
    assert cache.start('export/original', '完整发布文案') == ('opaque-next', True)
    cache.observe('opaque-page', response(), advance=False)
    assert cache.start('native-1', '') == ('opaque-page', False)
    assert '完整发布文案' not in cache.path.read_text()
    assert cache.path.stat().st_mode & 0o077 == 0


def test_cache_account_query_ttl_corruption_and_business_failure(tmp_path):
    now = [100000.0]
    path = tmp_path/'state.json'
    cache = CommentListCursor(path, 'gen-a', {'onlyUnread': False}, clock=lambda: now[0])
    cache.observe('', response(), advance=True)
    assert CommentListCursor(path, 'gen-b', {'onlyUnread': False}, clock=lambda: now[0]).start('native-1', '') == ('', True)
    assert CommentListCursor(path, 'gen-a', {'onlyUnread': True}, clock=lambda: now[0]).start('native-1', '') == ('', True)
    now[0] += cache.TTL
    assert cache.start('native-1', '') == ('', True)
    cache.path.write_text('{broken')
    assert cache.start('native-1', '') == ('', True)
    cache.observe('', response(), advance=True)
    cache.observe('opaque-next', {'errCode': 123, 'data': {}}, advance=True)
    assert cache.start('native-1', '') == ('', True)
    cache.observe('', {'data': {'list': [{'objectId': str(i)} for i in range(cache.MAX_ITEMS + 30)],
                              'lastBuff': 'server-value'}}, advance=True)
    assert len(json.loads(cache.path.read_text())['scopes'][cache.scope]['items']) == cache.MAX_ITEMS
