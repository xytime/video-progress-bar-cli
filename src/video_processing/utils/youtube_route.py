"""YouTube 独立下载入口：核对真实连接的自建出口，无法证明就拒绝获取。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 2.0 | 2026-10-27 | Codex | 独立后台出口与 Unix 控制面，解除桌面客户端端口依赖。 |
"""
from __future__ import annotations

import json
import fcntl
import logging
import re
import socket
import ssl
import subprocess
import time
from pathlib import Path
from typing import Callable, Mapping
from urllib.parse import quote, urlsplit
from urllib.request import ProxyHandler, build_opener

from config.settings import settings
from .youtube_egress import controller_json, proxy_endpoint

logger = logging.getLogger(__name__)
_PROBE_HOST = 'www.youtube.com'


class YoutubeRouteError(RuntimeError):
    """出口保护拒绝，禁止作为下载器故障进行降级。"""


def _controller_json(path: str, config) -> dict:
    try:
        return controller_json(path, Path(config.youtube_controller_socket).expanduser())
    except (FileNotFoundError, ConnectionRefusedError):
        raise YoutubeRouteError('独立 YouTube 出口服务未就绪；保留缓存等待恢复') from None


def _probe_youtube_connection(config, endpoint) -> dict:
    """只做 TLS 握手，用本次连接的源端口核对 Clash 实际节点，不获取视频。"""
    with socket.create_connection((endpoint.hostname, endpoint.port), timeout=8) as connection:
        source_ip, source_port = connection.getsockname()[:2]
        connection.sendall(
            f'CONNECT {_PROBE_HOST}:443 HTTP/1.1\r\nHost: {_PROBE_HOST}:443\r\n\r\n'.encode('ascii')
        )
        header = bytearray()
        while not header.endswith(b'\r\n\r\n'):
            chunk = connection.recv(1)
            if not chunk or len(header) >= 8192:
                raise YoutubeRouteError('YouTube 代理未返回有效的连接响应')
            header.extend(chunk)
        status = bytes(header).split(b'\r\n', 1)[0].split()
        if len(status) < 2 or status[1] != b'200':
            raise YoutubeRouteError('YouTube 代理拒绝建立连接')
        # 完成真实握手后连接才进入 Clash 活跃连接表；保持打开直到回读完成。
        with ssl.create_default_context().wrap_socket(connection, server_hostname=_PROBE_HOST):
            for attempt in range(5):
                rows = _controller_json('/connections', config).get('connections') or []
                matches = []
                for row in rows:
                    metadata = row.get('metadata', {})
                    if (str(metadata.get('sourcePort')) == str(source_port)
                            and metadata.get('sourceIP') == source_ip
                            and metadata.get('host', '').lower() == _PROBE_HOST
                            and str(metadata.get('destinationPort')) == '443'
                            and metadata.get('network') == 'tcp'):
                        matches.append(row)
                if len(matches) == 1:
                    return matches[0]
                if len(matches) > 1:
                    break
                if attempt < 4:
                    time.sleep(0.1)
    raise YoutubeRouteError('无法确认本次 YouTube 连接的实际出口，停止获取')


def verify_youtube_route(*, config=None, expected_proxy: str | None = None) -> dict:
    config = config or settings
    proxy = expected_proxy or config.youtube_download_proxy
    node = config.youtube_download_required_node
    try:
        endpoint = proxy_endpoint(proxy)
        if proxy != config.youtube_download_proxy:
            raise YoutubeRouteError('YouTube 下载入口与独立出口配置不一致')
        actual_node = _controller_json('/proxies/' + quote(node, safe=''), config)
        if actual_node.get('type') != 'Hysteria2' or actual_node.get('all') is not None:
            raise YoutubeRouteError('YouTube 目标必须是自建实体节点，不能是可切换策略组')
        try:
            connection = _probe_youtube_connection(config, endpoint)
        except (OSError, ssl.SSLError):
            raise YoutubeRouteError('独立出口未能建立 YouTube 连接；检查自建节点或目标服务') from None
        chains = connection.get('chains')
        # Clash chains 从实际出口到上层策略组排列；允许任意分组，只验最终实体节点。
        if not isinstance(chains, list) or not chains or chains[0] != node:
            raise YoutubeRouteError('本次 YouTube 连接未经过指定自建 VPN，停止获取')
    except YoutubeRouteError:
        raise
    except Exception as exc:
        # 不把请求 URL、认证、签名媒体地址或外部响应体写进错误。
        raise YoutubeRouteError(f'YouTube 出口无法验收，停止获取：{type(exc).__name__}') from None
    return {'proxy': proxy, 'required_node': node, 'policy_verified': True,
            'verification': 'live_connection', 'probe_host': _PROBE_HOST,
            'service': 'independent-egress',
            'checked_at': time.time()}


def youtube_cli_args(*, verify: bool = True) -> list[str]:
    if verify:verify_youtube_route()
    return ['--ignore-config', '--proxy', settings.youtube_download_proxy, '--no-playlist']


def youtube_environment(base: Mapping[str, str]) -> dict[str, str]:
    """仅传给 YouTube 子进程；清除 no_proxy 以免 curl/FFmpeg 绕过。"""
    result = {k: v for k, v in base.items() if k.lower() not in {'http_proxy', 'https_proxy', 'all_proxy', 'no_proxy'}}
    for key in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy'):
        result[key] = settings.youtube_download_proxy
    result.update(NO_PROXY='', no_proxy='')
    return result


class _ForcedProxyHandler(ProxyHandler):
    def proxy_open(self, req, proxy, type):
        # urllib 默认会检查进程 NO_PROXY；这里的专用入口不允许绕过。
        req.set_proxy(urlsplit(proxy).netloc, 'http')
        return None


def youtube_opener():
    return build_opener(_ForcedProxyHandler({'http': settings.youtube_download_proxy,
                                            'https': settings.youtube_download_proxy}))


def youtube_urlopen(request, *, timeout=20):
    """频道 RSS / Data API 同样使用独立出口，不继承系统代理。"""
    verify_youtube_route()
    return youtube_opener().open(request, timeout=timeout)


def run_youtube_metadata(command, *, timeout=180):
    """元数据 CLI 的网络边界，业务采集器不自行选择代理。"""
    from .subprocess_env import build_subprocess_env
    return subprocess.run([command[0], *youtube_cli_args(), *command[1:]],
                          capture_output=True, text=True, timeout=timeout,
                          env=youtube_environment(build_subprocess_env()))


def _reported_bytes(output) -> int | None:
    if isinstance(output, bytes):output = output.decode(errors='replace')
    streams = {}
    for video, fmt, value in re.findall(r'ROUTE_MEDIA_BYTES:([^:\s]+):([^:\s]+):(\d+)', output or ''):
        streams[(video, fmt)] = max(streams.get((video, fmt), 0), int(value))
    return sum(streams.values()) if streams else None


def guarded_youtube_call(call: Callable, *, task_id: str, source_url: str, downloader: str,
                         evidence_path: Path | None = None, artifact_paths: Callable = lambda: (),
                         expected_proxy: str | None = None):
    """每次获取前验收，落盘不含签名 URL 的尝试证据；字节不等同账单。"""
    record = {'task_id': task_id, 'source_host': urlsplit(source_url).hostname,
              'started_at': time.time(), 'downloader': downloader, 'route': None,
              'downloader_reported_media_bytes': None, 'artifact_bytes': None,
              'proxy_connection_bytes': None, 'provider_billed_bytes': None,
              'byte_semantics': 'downloader cumulative bytes may include resumed data; not billed bytes'}
    result = None
    try:
        record['route'] = verify_youtube_route(expected_proxy=expected_proxy)
        result = call()
        record['exit_code'] = getattr(result, 'returncode', None)
        record['result'] = 'process_failed' if record['exit_code'] else 'completed'
        return result
    except BaseException as exc:
        result = exc
        record['result'] = 'route_rejected' if isinstance(exc, YoutubeRouteError) else type(exc).__name__
        raise
    finally:
        output = []
        for attr in ('stdout', 'stderr'):
            text = getattr(result, attr, '') or ''
            output.append(text.decode(errors='replace') if isinstance(text, bytes) else text if isinstance(text, str) else '')
        record['downloader_reported_media_bytes'] = _reported_bytes('\n'.join(output))
        record['finished_at'] = time.time()
        try:
            paths = [p for p in artifact_paths() if p.is_file()]
            record['artifact_bytes'] = sum(p.stat().st_size for p in paths) if paths else None
            if evidence_path:
                evidence_path.parent.mkdir(parents=True, exist_ok=True)
                # 一行一个尝试；不覆盖失败记录，不记录原始命令或 Cookie。
                with evidence_path.open('a+', encoding='utf-8') as stream:
                    fcntl.flock(stream, fcntl.LOCK_EX)
                    stream.seek(0)
                    record['attempt'] = sum(1 for line in stream if line.strip()) + 1
                    stream.write(json.dumps(record, ensure_ascii=False) + '\n')
                    stream.flush()
        except OSError:
            logger.error('[YouTubeRoute] 无法持久化下载审计记录')
        logger.info('[YouTubeRoute] %s', json.dumps(record, ensure_ascii=False))
