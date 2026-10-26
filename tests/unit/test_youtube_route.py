"""必须先证明自建出口，再允许下载；拒绝不能触发 curl 重试。"""
import json
import socket
import subprocess
import urllib.error
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from video_processing.utils import youtube_route as route
from video_processing.utils.download_strategy import DownloadOptions, execute_download_with_fallback, NativeDownloadStrategy, CurlDownloadStrategy


def config():
    return SimpleNamespace(youtube_download_proxy='http://127.0.0.1:7890',
                           youtube_download_required_node='hy2-ai.optionbank.us',
                           clash_api_url='http://127.0.0.1:9090', clash_api_secret='test')


def state():
    return {'/proxies/' + config().youtube_download_required_node: {'type': 'Hysteria2'}}


@pytest.mark.parametrize('fault', ['404', 'timeout', 'proxy_down', 'other_node', 'direct', 'group', 'empty_chain', 'name_in_group_only'])
def test_bad_route_never_transfers(monkeypatch, tmp_path, fault):
    data = state()
    def query(path, _config):
        if fault == '404':raise urllib.error.HTTPError('http://localhost', 404, 'missing', {}, None)
        if fault == 'timeout':raise TimeoutError()
        return data[path]
    if fault == 'group':data['/proxies/hy2-ai.optionbank.us'] = {'type': 'Selector', 'all': ['Panda']}
    monkeypatch.setattr(route, '_controller_json', query)
    def probe(*args):
        if fault == 'proxy_down':raise ConnectionRefusedError()
        chains = {'other_node': ['Panda', 'PROXY'], 'direct': ['DIRECT'],
                  'empty_chain': [], 'name_in_group_only': ['Panda', config().youtube_download_required_node]}
        return {'chains': chains.get(fault, [config().youtube_download_required_node, 'PROXY'])}
    monkeypatch.setattr(route, '_probe_youtube_connection', probe)
    calls = []
    options = DownloadOptions('yt-dlp', 'https://youtu.be/example', str(tmp_path/'source.%(ext)s'),
                              proxy_url=config().youtube_download_proxy, route_audit_path=tmp_path/'routes.jsonl')
    with pytest.raises(route.YoutubeRouteError):
        execute_download_with_fallback(options, lambda *a, **k: calls.append('transfer'), lambda: None,
                                       on_fallback=lambda _: calls.append('fallback'))
    assert calls == []
    evidence = json.loads((tmp_path/'routes.jsonl').read_text())
    assert evidence['result'] == 'route_rejected'
    assert evidence['proxy_connection_bytes'] is None
    assert evidence['downloader_reported_media_bytes'] is None


@pytest.mark.parametrize('groups', [[], ['PROXY'], ['auto', 'GLOBAL']])
def test_live_self_hosted_route_accepts_groups_without_reading_or_changing_rules(monkeypatch, groups):
    calls = []
    monkeypatch.setattr(route, '_controller_json', lambda path, cfg: calls.append(path) or state()[path])
    monkeypatch.setattr(route, '_probe_youtube_connection',
                        lambda *args: {'chains': [config().youtube_download_required_node, *groups]})
    evidence = route.verify_youtube_route(config=config())
    assert evidence['policy_verified']
    assert evidence['verification'] == 'live_connection'
    assert calls == ['/proxies/hy2-ai.optionbank.us']


class ProbeSocket:
    def __init__(self, response=b'HTTP/1.1 200 Connection established\r\n\r\n'):
        self.response = response
        self.closed = False
        self.sent = b''

    def __enter__(self):return self
    def __exit__(self, *args):self.closed = True
    def getsockname(self):return ('127.0.0.1', 54321)
    def sendall(self, data):self.sent += data
    def recv(self, size):
        result, self.response = self.response[:size], self.response[size:]
        return result


@pytest.mark.parametrize('fault', [None, 'other_port', 'other_host', 'other_ip', 'other_destination', 'udp', 'duplicate', 'missing'])
def test_probe_only_accepts_its_own_live_connection(monkeypatch, fault):
    connection = ProbeSocket()
    metadata = dict(sourceIP='127.0.0.1', sourcePort='54321', host='www.youtube.com', destinationPort='443', network='tcp')
    changes = {'other_port': ('sourcePort', '12345'), 'other_host': ('host', 'other.example'),
               'other_ip': ('sourceIP', '127.0.0.2'), 'other_destination': ('destinationPort', '80'), 'udp': ('network', 'udp')}
    if fault in changes:
        key, value = changes[fault]; metadata[key] = value
    row = {'metadata': metadata, 'chains': [config().youtube_download_required_node, 'PROXY']}
    rows = [] if fault == 'missing' else [row, row] if fault == 'duplicate' else [row]
    monkeypatch.setattr(route.socket, 'create_connection', lambda *a, **kw: connection)
    def wrap(sock, server_hostname):
        assert sock is connection and server_hostname == 'www.youtube.com'
        return nullcontext(sock)
    monkeypatch.setattr(route.ssl, 'create_default_context', lambda: SimpleNamespace(wrap_socket=wrap))
    def query(path, cfg):
        assert not connection.closed and path == '/connections'
        return {'connections': rows}
    monkeypatch.setattr(route, '_controller_json', query)
    endpoint = route.urlsplit(config().youtube_download_proxy)
    if fault:
        with pytest.raises(route.YoutubeRouteError, match='无法确认'):
            route._probe_youtube_connection(config(), endpoint)
    else:
        assert route._probe_youtube_connection(config(), endpoint) == row
    assert connection.closed
    assert connection.sent == b'CONNECT www.youtube.com:443 HTTP/1.1\r\nHost: www.youtube.com:443\r\n\r\n'


@pytest.mark.parametrize('response', [b'', b'HTTP/1.1 407 Proxy Authentication Required\r\n\r\n', b'x' * 8193])
def test_probe_rejects_invalid_proxy_response(monkeypatch, response):
    connection = ProbeSocket(response)
    monkeypatch.setattr(route.socket, 'create_connection', lambda *a, **kw: connection)
    with pytest.raises(route.YoutubeRouteError):
        route._probe_youtube_connection(config(), route.urlsplit(config().youtube_download_proxy))
    assert connection.closed


def test_proxy_args_shared_by_native_curl_and_sections():
    for section in (None, '*0-1'):
        options=DownloadOptions('yt-dlp', 'https://youtu.be/example', 'x.%(ext)s', proxy_url=config().youtube_download_proxy, download_sections=section)
        for strategy in (NativeDownloadStrategy(), CurlDownloadStrategy()):
            cmd=strategy.build_command(options)
            assert cmd[cmd.index('--proxy')+1] == config().youtube_download_proxy
            assert '--ignore-config' in cmd
            if section:assert cmd[cmd.index('--download-sections')+1] == section


def test_youtube_environment_clears_bypass_without_mutating_ai_environment():
    base={'HTTPS_PROXY':'http://paid:123', 'NO_PROXY':'*', 'PATH':'/bin', 'TOKEN':'opaque'}
    env=route.youtube_environment(base)
    assert env['HTTPS_PROXY']==config().youtube_download_proxy
    assert env['NO_PROXY']=='' and env['no_proxy']==''
    assert base['HTTPS_PROXY']=='http://paid:123' and base['NO_PROXY']=='*'
    assert env['TOKEN']=='opaque'


def test_audit_redacts_urls_and_distinguishes_bytes(monkeypatch, tmp_path):
    monkeypatch.setattr(route, 'verify_youtube_route', lambda **kw: {'policy_verified':True})
    target=tmp_path/'x.mp4';target.write_bytes(b'123')
    result=subprocess.CompletedProcess([],0,'ROUTE_MEDIA_BYTES:x:140:100\nROUTE_MEDIA_BYTES:x:140:130\nROUTE_MEDIA_BYTES:x:136:250\nhttps://signed.example/?token=secret','')
    route.guarded_youtube_call(lambda:result, task_id='x', source_url='https://youtube.com/watch?v=x&secret=xx', downloader='native',evidence_path=tmp_path/'evidence',artifact_paths=lambda:[target])
    text=(tmp_path/'evidence').read_text();d=json.loads(text)
    assert 'secret' not in text and d['source_host']=='youtube.com'
    assert d['downloader_reported_media_bytes']==380 and d['artifact_bytes']==3
    assert d['proxy_connection_bytes'] is None and d['provider_billed_bytes'] is None


def test_forced_urllib_proxy_does_not_consult_no_proxy(monkeypatch):
    from urllib.request import Request
    monkeypatch.setenv('NO_PROXY', '*')
    req = Request('https://www.youtube.com/api/timedtext')
    route._ForcedProxyHandler({}).proxy_open(req, config().youtube_download_proxy, 'https')
    assert req.host == '127.0.0.1:7890'
    assert req._tunnel_host == 'www.youtube.com'


def test_nonzero_process_result_is_recorded_as_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(route, 'verify_youtube_route', lambda **kw: {'policy_verified': True})
    route.guarded_youtube_call(lambda: subprocess.CompletedProcess([], 1, '', 'failure'),
        task_id='x', source_url='https://youtube.com/', downloader='curl', evidence_path=tmp_path/'audit')
    assert json.loads((tmp_path/'audit').read_text())['result'] == 'process_failed'
