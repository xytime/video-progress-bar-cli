"""独立出口的配置与只读 Unix 控制面；不依赖桌面客户端。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0 | 2026-10-27 | Codex | 固定回环入口、物理网卡出口及受保护的本地控制面。 |
"""
from __future__ import annotations

import http.client
import json
import os
import re
import socket
import stat
from pathlib import Path
from urllib.parse import urlsplit


def proxy_endpoint(proxy: str):
    endpoint = urlsplit(proxy)
    if (endpoint.scheme != 'http' or endpoint.hostname != '127.0.0.1'
            or not endpoint.port or endpoint.username or endpoint.password
            or endpoint.path not in ('', '/') or endpoint.query or endpoint.fragment):
        raise ValueError('必须使用固定本机 HTTP 代理')
    return endpoint


def core_config(proxy: str, control_socket: Path, node: str, interface: str) -> dict:
    """唯一出站为受控 provider；没有 DIRECT 或桌面代理兜底。"""
    endpoint = proxy_endpoint(proxy)
    if not re.fullmatch(r'en\d+', interface):
        raise ValueError('出口必须是明确的物理以太网或 Wi-Fi 接口')
    if not node or ',' in node or '\n' in node:
        raise ValueError('无效的自建节点名称')
    if not control_socket.is_absolute() or len(str(control_socket).encode()) >= 104:
        raise ValueError('控制 socket 路径无效或过长')
    return {
        'mixed-port': endpoint.port, 'allow-lan': False, 'bind-address': '127.0.0.1',
        'mode': 'rule', 'log-level': 'silent', 'ipv6': False,
        'interface-name': interface, 'tun': {'enable': False},
        'external-controller': '', 'external-controller-unix': str(control_socket),
        'profile': {'store-selected': False, 'store-fake-ip': False},
        # 只供内核解析；不监听 DNS 端口，不继承 GUI 的 fake-IP DNS。
        'dns': {'enable': True, 'ipv6': False, 'enhanced-mode': 'redir-host',
                'default-nameserver': ['223.5.5.5', '119.29.29.29'],
                'proxy-server-nameserver': ['223.5.5.5', '119.29.29.29'],
                'nameserver': ['223.5.5.5', '119.29.29.29']},
        'proxy-providers': {'self-hosted': {
            'type': 'file', 'path': './nodes.yaml', 'filter': '^' + re.escape(node) + '$',
            'health-check': {'enable': False},
            'override': {'interface-name': interface, 'dialer-proxy': ''},
        }},
        'proxy-groups': [{'name': 'VIDEO_SELF_ONLY', 'type': 'select', 'use': ['self-hosted']}],
        'rules': ['MATCH,VIDEO_SELF_ONLY'],
    }


class _UnixConnection(http.client.HTTPConnection):
    def __init__(self, path: Path):
        super().__init__('localhost', timeout=3)
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(str(self.path))


def controller_json(path: str, control_socket: Path) -> dict:
    """只有本用户私有目录中的 socket 可用；不读取或传递桌面 API 密钥。"""
    control_socket = Path(control_socket)
    parent = control_socket.parent.lstat()
    target = control_socket.lstat()
    if (not control_socket.is_absolute() or not stat.S_ISDIR(parent.st_mode)
            or parent.st_uid != os.getuid() or parent.st_mode & 0o077
            or not stat.S_ISSOCK(target.st_mode) or target.st_uid != os.getuid()):
        raise ValueError('控制 socket 不在本用户私有目录中')
    if not path.startswith('/') or '\r' in path or '\n' in path:
        raise ValueError('无效控制请求')
    connection = _UnixConnection(control_socket)
    try:
        connection.request('GET', path)
        response = connection.getresponse()
        body = response.read(2_000_001)
        if response.status != 200 or len(body) > 2_000_000:
            raise ValueError('控制接口响应异常')
        result = json.loads(body)
        if not isinstance(result, dict):
            raise ValueError('控制接口响应类型异常')
        return result
    finally:
        connection.close()
