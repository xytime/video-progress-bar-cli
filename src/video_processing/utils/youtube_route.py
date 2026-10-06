"""YouTube 独立下载入口：只读核对 Clash，无法证明自建出口就拒绝传输。"""
from __future__ import annotations

import json
import fcntl
import logging
import re
import socket
import time
from pathlib import Path
from typing import Callable, Mapping
from urllib.parse import quote, urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from config.settings import settings

logger = logging.getLogger(__name__)
_REQUIRED_SUFFIXES = {'youtube.com', 'youtu.be', 'googlevideo.com', 'ytimg.com', 'ggpht.com'}
_REQUIRED_DOMAINS = {'youtubei.googleapis.com', 'youtube.googleapis.com'}


class YoutubeRouteError(RuntimeError):
    """出口保护拒绝，禁止作为下载器故障进行降级。"""


def _controller_json(path: str, config) -> dict:
    url = urlsplit(config.clash_api_url)
    if url.scheme != 'http' or url.hostname != '127.0.0.1' or not url.port:
        raise YoutubeRouteError('YouTube 出口检查只允许本机 Clash 控制器')
    request = Request(config.clash_api_url.rstrip('/') + path)
    if config.clash_api_secret:
        request.add_header('Authorization', 'Bearer ' + config.clash_api_secret)
    # 控制面直连回环，不能递归经过待验收的代理。
    with build_opener(ProxyHandler({})).open(request, timeout=3) as response:
        return json.load(response)


def verify_youtube_route(*, config=None, expected_proxy: str | None = None) -> dict:
    config = config or settings
    proxy = expected_proxy or config.youtube_download_proxy
    node = config.youtube_download_required_node
    try:
        endpoint = urlsplit(proxy)
        if proxy != config.youtube_download_proxy or endpoint.scheme != 'http' or endpoint.hostname != '127.0.0.1' or endpoint.port != 7890 or endpoint.username or endpoint.password or endpoint.path not in ('', '/'):
            raise YoutubeRouteError('YouTube 下载必须使用本机 HTTP 代理 127.0.0.1:7890')
        core = _controller_json('/configs', config)
        if core.get('mode', '').lower() != 'rule' or 7890 not in (core.get('mixed-port'), core.get('port')):
            raise YoutubeRouteError('Clash 必须处于规则模式且监听已指定代理端口')
        actual_node = _controller_json('/proxies/' + quote(node, safe=''), config)
        if actual_node.get('type') != 'Hysteria2' or actual_node.get('all') is not None:
            raise YoutubeRouteError('YouTube 目标必须是自建实体节点，不能是可切换策略组')
        rules = _controller_json('/rules', config).get('rules', [])
        suffixes, domains = set(), set()
        # 只接受规则表最前方连续的自建域名规则；避免进程/IP/规则集抢先匹配。
        for rule in rules:
            if rule.get('proxy') != node or rule.get('type') not in ('Domain', 'DomainSuffix', 'DomainKeyword') or rule.get('extra', {}).get('disabled'):
                break
            if rule['type'] == 'DomainSuffix':suffixes.add(rule.get('payload', '').lower())
            if rule['type'] == 'Domain':domains.add(rule.get('payload', '').lower())
        if not _REQUIRED_SUFFIXES <= suffixes or not _REQUIRED_DOMAINS <= (domains | suffixes):
            raise YoutubeRouteError('YouTube/CDN 必需域名未被优先固定到自建')
        matches = [r for r in rules if r.get('type') == 'Match']
        if len(matches) != 1 or matches[0].get('proxy') != node or rules[-1] != matches[0] or matches[0].get('extra', {}).get('disabled'):
            raise YoutubeRouteError('Clash 默认兜底必须直接绑定自建，禁止猫熊或 DIRECT 回退')
        with socket.create_connection(('127.0.0.1', 7890), timeout=2):pass
    except YoutubeRouteError:
        raise
    except Exception as exc:
        # 不把请求 URL、认证、签名媒体地址或外部响应体写进错误。
        raise YoutubeRouteError(f'YouTube 出口无法验收，停止获取：{type(exc).__name__}') from None
    return {'mode': 'rule', 'proxy': proxy, 'required_node': node, 'policy_verified': True, 'checked_at': time.time()}


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
