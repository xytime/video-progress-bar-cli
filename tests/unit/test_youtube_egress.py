"""独立服务不能继承桌面代理、直连兜底或开放控制端口。"""
from pathlib import Path
from types import SimpleNamespace
import os
import stat

import pytest
from video_processing.utils.youtube_egress import core_config, controller_json, proxy_endpoint
from video_processing.utils import youtube_route


def test_core_has_one_self_hosted_route_and_no_desktop_dependency(tmp_path):
    config = core_config('http://127.0.0.1:9110', Path('/tmp/private-egress/c.sock'), 'self.example', 'en0')
    assert config['rules'] == ['MATCH,VIDEO_SELF_ONLY']
    assert config['proxy-groups'] == [{'name': 'VIDEO_SELF_ONLY', 'type': 'select', 'use': ['self-hosted']}]
    provider = config['proxy-providers']['self-hosted']
    assert provider['type'] == 'file' and provider['filter'] == r'^self\.example$'
    assert provider['override'] == {'interface-name': 'en0', 'dialer-proxy': ''}
    assert config['tun']['enable'] is False and config['external-controller'] == ''
    assert config['allow-lan'] is False and config['bind-address'] == '127.0.0.1'
    assert 'listen' not in config['dns']
    assert config['dns']['proxy-server-nameserver'] == ['223.5.5.5', '119.29.29.29']


@pytest.mark.parametrize('url', ['http://remote:9110', 'socks5://127.0.0.1:9110',
    'http://127.0.0.1', 'http://user:secret@127.0.0.1:9110',
    'http://127.0.0.1:9110/path', 'http://127.0.0.1:9110?bypass=1'])
def test_reject_nonlocal_or_ambiguous_proxy(url):
    with pytest.raises(ValueError):
        proxy_endpoint(url)


@pytest.mark.parametrize('interface', ['utun8', 'lo0', '', 'en0;exec'])
def test_reject_virtual_or_invalid_egress_interface(interface):
    with pytest.raises(ValueError):
        core_config('http://127.0.0.1:9110', Path('/tmp/x.sock'), 'self.example', interface)


@pytest.mark.parametrize('fault', ['public_dir', 'wrong_owner', 'regular_file', 'symlink_dir'])
def test_control_socket_boundary_checked_before_connect(monkeypatch, fault):
    parent = SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_uid=os.getuid())
    target = SimpleNamespace(st_mode=stat.S_IFSOCK | 0o600, st_uid=os.getuid())
    if fault == 'public_dir':parent.st_mode |= 0o005
    if fault == 'wrong_owner':target.st_uid += 1
    if fault == 'regular_file':target.st_mode = stat.S_IFREG | 0o600
    if fault == 'symlink_dir':parent.st_mode = stat.S_IFLNK | 0o700
    monkeypatch.setattr(Path, 'lstat', lambda p: target if p.name == 'c.sock' else parent)
    with pytest.raises(ValueError, match='私有目录'):
        controller_json('/proxies', Path('/tmp/private/c.sock'))


def test_missing_service_has_actionable_failure_and_never_uses_clash(monkeypatch, tmp_path):
    cfg = SimpleNamespace(youtube_controller_socket=tmp_path / 'missing.sock',
                          clash_api_url='http://paid.example:9090', clash_api_secret='not-used')
    with pytest.raises(youtube_route.YoutubeRouteError, match='独立 YouTube 出口服务未就绪'):
        youtube_route._controller_json('/proxies', cfg)


def test_controller_uses_only_private_unix_get(monkeypatch):
    import video_processing.utils.youtube_egress as module
    parent = SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_uid=os.getuid())
    target = SimpleNamespace(st_mode=stat.S_IFSOCK | 0o600, st_uid=os.getuid())
    monkeypatch.setattr(Path, 'lstat', lambda p: target if p.name == 'c.sock' else parent)
    calls = []
    class Connection:
        def __init__(self, path):calls.append(str(path))
        def request(self, method, path):calls.append((method, path))
        def getresponse(self):return SimpleNamespace(status=200, read=lambda _: b'{"ok":true}')
        def close(self):calls.append('closed')
    monkeypatch.setattr(module, '_UnixConnection', Connection)
    assert controller_json('/configs', Path('/tmp/private/c.sock')) == {'ok': True}
    assert calls == ['/tmp/private/c.sock', ('GET', '/configs'), 'closed']
