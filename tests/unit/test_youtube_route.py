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
    node = config().youtube_download_required_node
    rules = [{'type': 'DomainSuffix', 'payload': d, 'proxy': node}
             for d in sorted(route._REQUIRED_SUFFIXES | route._REQUIRED_DOMAINS)]
    rules.append({'type': 'Match', 'payload': '', 'proxy': node})
    return {'/configs': {'mode': 'rule', 'mixed-port': 7890},
            '/rules': {'rules': rules}, '/proxies/' + node: {'type': 'Hysteria2'}}


@pytest.mark.parametrize('fault', ['404', 'timeout', 'proxy_down', 'global', 'paid_match', 'paid_earlier', 'group', 'disabled', 'missing'])
def test_bad_route_never_transfers(monkeypatch, tmp_path, fault):
    data = state()
    def query(path, _config):
        if fault == '404':raise urllib.error.HTTPError('http://localhost', 404, 'missing', {}, None)
        if fault == 'timeout':raise TimeoutError()
        return data[path]
    if fault == 'global':data['/configs']['mode'] = 'global'
    if fault == 'paid_match':data['/rules']['rules'][-1]['proxy'] = 'Panda'
    if fault == 'paid_earlier':data['/rules']['rules'].insert(0, {'type': 'ProcessName', 'payload': 'curl', 'proxy': 'Panda'})
    if fault == 'group':data['/proxies/hy2-ai.optionbank.us'] = {'type': 'Selector', 'all': ['Panda']}
    if fault == 'disabled':data['/rules']['rules'][0]['extra'] = {'disabled': True}
    if fault == 'missing':data['/rules']['rules'].pop(0)
    monkeypatch.setattr(route, '_controller_json', query)
    def connect(*a, **k):
        if fault == 'proxy_down':raise ConnectionRefusedError()
        return nullcontext()
    monkeypatch.setattr(route.socket, 'create_connection', connect)
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


def test_valid_policy_does_not_switch_any_global_group(monkeypatch):
    data=state();calls=[]
    monkeypatch.setattr(route, '_controller_json', lambda path, cfg: calls.append(path) or data[path])
    monkeypatch.setattr(route.socket, 'create_connection', lambda *a, **k: nullcontext())
    assert route.verify_youtube_route(config=config())['policy_verified']
    assert calls == ['/configs', '/proxies/hy2-ai.optionbank.us', '/rules']


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
