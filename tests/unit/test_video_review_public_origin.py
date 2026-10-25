"""复核请求在 HTTPS 反代后仍可保存，同源例外严格限于具名复核入口。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-25 | Codex | 覆盖真实 CP 审查、批准审计、切片隔离、重入保护及来源拒绝不写库。 |
"""
from unittest.mock import Mock

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest
from starlette.requests import Request

from config.settings import Settings
from video_processing.censorship_service import CensorshipService
from video_processing.db.database import PipelineDB
from web.local_runtime_access import configured_video_review_public_origin

ORIGIN = 'https://v.optionbank.us'
HOST = 'v.optionbank.us'
YID = 'RMYN_lnk1uc'
PATH = f'/api/videos/{YID}/bypass-censor'


def _request(path=PATH, method='POST', host=HOST, peer='127.0.0.1'):
    return Request(dict(type='http', scheme='http', method=method, path=path,
                        query_string=b'', server=('127.0.0.1', 9100), client=(peer, 50000),
                        headers=[(b'host', host.encode()), (b'x-forwarded-for', b'127.0.0.1'),
                                 (b'x-forwarded-proto', b'https')]))


@pytest.mark.parametrize('changes', [
    {}, {'peer': '::1'}, {'peer': '198.51.100.1'}, {'host': 'attacker.invalid'},
    {'method': 'GET'}, {'path': '/api/pipeline/run'}, {'path': '/runtime-settings'},
    {'path': '/api/videos/other/retry'}, {'path': PATH + '/extra'},
])
def test_public_exception_requires_exact_review_path_host_and_socket_peer(changes):
    expected = ORIGIN if changes in ({}, {'peer': '::1'}) else None
    assert configured_video_review_public_origin(_request(**changes), ORIGIN) == expected
    assert configured_video_review_public_origin(_request(**changes), '') is None


@pytest.mark.parametrize('origin', [
    'http://v.optionbank.us', ORIGIN + '/', ORIGIN + '?x=1',
    'https://user@v.optionbank.us', 'https://v.optionbank.us:0443',
])
def test_review_origin_cannot_be_malformed(origin):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, dashboard_review_public_origin=origin)
    assert configured_video_review_public_origin(_request(), origin) is None


@pytest.mark.parametrize('index', [0, 1])
def test_https_review_persists_approval_and_audit_then_pipeline_honors_it(tmp_path, monkeypatch, index):
    import web.app as dashboard

    db = PipelineDB(str(tmp_path / 'pipeline.db'))
    db.add_video(YID, 'Obama reacts to Republican attacks', 'channel', score=100)
    if index:
        db.add_video(YID, 'Obama reacts to Republican attacks', 'channel', score=100, slice_index=index)
    monkeypatch.setattr(dashboard, 'db', db)
    trigger = Mock()
    monkeypatch.setattr(dashboard, '_trigger_video_async', trigger)
    monkeypatch.setattr(dashboard.settings, 'dashboard_review_public_origin', ORIGIN)
    monkeypatch.setattr(dashboard.settings, 'enable_channel_policy_filter', True)
    monkeypatch.setattr(dashboard.settings, 'enable_censorship_engine', True)
    service = CensorshipService(db, lambda _message: None)
    title = 'Obama reacts to Republican attacks'
    description = 'Donald Trump made claims that did not prevent Obama winning re-election.'
    assert service.check(YID, title, description, slice_index=index) is True
    before = db.get_video_by_youtube_id(YID, slice_index=index)
    assert before['status'] == 'FAILED' and before['bypass_censorship'] == 0
    incident = db.get_censorship_incidents(YID, slice_index=index)[0]
    assert incident['level'] == 'CP'

    client = TestClient(dashboard.app, base_url='http://' + HOST, client=('127.0.0.1', 50000))
    url = PATH + f'?slice_index={index}'
    rejected = client.post(url, headers={'Origin': 'https://attacker.invalid'}, json={})
    assert rejected.status_code == 403
    assert db.get_video_by_youtube_id(YID, slice_index=index) == before
    assert len(db.get_censorship_incidents(YID, slice_index=index)) == 1
    trigger.assert_not_called()

    accepted = client.post(url, headers={'Origin': ORIGIN}, json={})
    assert accepted.status_code == 200 and accepted.json()['success'] is True
    assert accepted.json()['triggered'] is True
    assert db.get_video_by_youtube_id(YID, slice_index=index)['bypass_censorship'] == 1
    approval = db.get_censorship_incidents(YID, slice_index=index)[0]
    assert approval['decision'] == 'MANUAL_CP_APPROVED'
    assert approval['input_hash'] == incident['input_hash']
    assert approval['rule_pack_version'] == incident['rule_pack_version']
    assert approval['slice_index'] == index
    assert str(incident['id']) in approval['text_excerpt']
    assert db.has_manual_p0_approval(YID, slice_index=index) is False
    assert service.check(YID, title, description, slice_index=index) is False
    trigger.assert_called_once()
    if index:
        assert db.get_video_by_youtube_id(YID)['bypass_censorship'] == 0
    repeated = client.post(url, headers={'Origin': ORIGIN}, json={})
    assert repeated.json()['success'] is False
    trigger.assert_called_once()


def test_public_review_configuration_does_not_open_other_routes(monkeypatch):
    import web.app as dashboard

    monkeypatch.setattr(dashboard.settings, 'dashboard_review_public_origin', ORIGIN)
    client = TestClient(dashboard.app, base_url='http://' + HOST, client=('127.0.0.1', 50000))
    for path in ('/api/pipeline/run', '/api/videos/other/retry', '/runtime-settings'):
        assert client.post(path, headers={'Origin': ORIGIN}).status_code == 403
    remote = TestClient(dashboard.app, base_url='http://' + HOST, client=('198.51.100.1', 50000))
    assert remote.post(PATH, headers={'Origin': ORIGIN, 'X-Forwarded-For': '127.0.0.1',
                                     'X-Forwarded-Proto': 'https'}).status_code == 403
