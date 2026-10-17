"""官方适配器的隔离 HTTP 响应验收；仅使用 httpx MockTransport，无网络。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-11 | Codex | 参数、缺失/错误响应、凭据脱敏和总超时验证 |
"""
import asyncio
import time
from types import SimpleNamespace

import httpx
import pytest
from tests.topic_candidate_fixtures import Clock
from video_processing.utils.topic_search import YouTubeTopicSearch, SearchFailure


def install(monkeypatch, handler):
    actual = httpx.AsyncClient
    def client(**kwargs):
        assert kwargs['trust_env'] is False and kwargs['follow_redirects'] is False
        return actual(**kwargs, transport=httpx.MockTransport(handler))
    monkeypatch.setattr(httpx, 'AsyncClient', client)
    return YouTubeTopicSearch(SimpleNamespace(youtube_data_api_key='isolated-not-a-real-key'))


def test_official_parameters_exact_identity_and_no_key_in_url(monkeypatch):
    requests = []
    def handler(request):
        requests.append(request)
        assert request.headers['x-goog-api-key'] == 'isolated-not-a-real-key'
        assert 'key' not in request.url.params and 'isolated-not' not in str(request.url)
        return httpx.Response(200, json={'items': []})
    adapter = install(monkeypatch, handler)
    adapter.search(dict(query='energy | industry -tutorial', lookback_days=7), Clock()(), 1)
    adapter.details(['00000000001', '00000000002'], 1)
    params = dict(requests[0].url.params)
    assert params == dict(part='snippet', type='video', order='date', safeSearch='strict',
        relevanceLanguage='en', maxResults='25', q='energy | industry -tutorial',
        publishedAfter='2026-10-04T04:00:00+00:00', publishedBefore='2026-10-11T04:00:00+00:00')
    assert requests[1].url.params['id'] == '00000000001,00000000002'
    assert requests[1].url.params['part'] == 'snippet,contentDetails,statistics,status'
    assert 'pageToken' not in params and 'videoDuration' not in params


@pytest.mark.parametrize('status,code,retry', [(403,'API_ACCESS',False),(429,'API_RATE_LIMIT',False),(500,'API_ERROR',True),(302,'API_ERROR',False),(401,'API_CREDENTIALS',False)])
def test_api_failure_sanitized(monkeypatch,status,code,retry):
    adapter=install(monkeypatch,lambda req:httpx.Response(status,text='isolated-not-a-real-key sensitive provider details'))
    with pytest.raises(SearchFailure) as caught: adapter.details(['00000000001'],1)
    assert caught.value.code==code and caught.value.retryable==retry
    assert 'sensitive' not in str(caught.value) and 'isolated-not' not in str(caught.value)


@pytest.mark.parametrize('reason,code', [('quotaExceeded','API_QUOTA'),('dailyLimitExceeded','API_QUOTA'),('keyInvalid','API_CREDENTIALS'),('accessNotConfigured','API_ACCESS')])
def test_official_error_reason_is_distinct(monkeypatch,reason,code):
    adapter=install(monkeypatch,lambda req:httpx.Response(403,json={'error':{'errors':[{'reason':reason}]}}))
    with pytest.raises(SearchFailure) as caught:adapter.details(['00000000001'],1)
    assert caught.value.code==code and not caught.value.retryable


@pytest.mark.parametrize('value', [{}, {'items':None}, {'items':'invalid'}, []])
def test_invalid_response_fail_closed(monkeypatch,value):
    adapter=install(monkeypatch,lambda req:httpx.Response(200,json=value))
    with pytest.raises(SearchFailure,match='资料不足'):adapter.details(['00000000001'],1)


def test_total_deadline_and_missing_credentials(monkeypatch):
    async def slow(request):
        await asyncio.sleep(1)
        return httpx.Response(200,json={'items':[]})
    adapter=install(monkeypatch,slow);start=time.monotonic()
    with pytest.raises(SearchFailure) as caught:adapter.details(['00000000001'],.05)
    assert caught.value.code=='NETWORK' and time.monotonic()-start<.5
    adapter.settings.youtube_data_api_key=''
    assert not adapter.configured()
    with pytest.raises(SearchFailure) as caught:adapter.details(['00000000001'],1)
    assert caught.value.code=='NO_API'
