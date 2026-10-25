"""配置写入口共用真实回环对端、本机会话与 CSRF 边界。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| console-auth-v1 | 2026-10-25 | Codex | 封面无模型认证核实复用精确同源边界，其余路径继续拒绝。 |
| video-review-origin-v1 | 2026-10-25 | Codex | 单条视频复核复用精确 HTTPS/Host/真实对端校验，保持配置页面隔离。 |
| english-world-origin-v1 | 2026-10-25 | Codex | 为英语世界可选受保护 HTTPS Origin 提供共享的精确 Host/路径判定；其它路由保持本机边界。 |
| reply-settings-v1 | 2026-10-25 | Codex | 迁移策略页复用配置中心权限，避免绕过本机会话和同源校验。 |
"""
import datetime as dt
import hashlib
import hmac
import ipaddress
import re
import secrets
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from config.runtime_policy import decode

COOKIE = 'runtime_local_session'


def configured_english_world_public_origin(request, public_origin):
    """仅对英语世界路径、真实回环对端和精确 DNS Host 返回 HTTPS Origin。"""
    if not public_origin:
        return None
    path = request.url.path
    if path != '/english-world' and not path.startswith('/api/english-world/'):
        return None
    return _configured_https_public_origin(request, public_origin)


def configured_video_review_public_origin(request, public_origin):
    """只开放单条视频复核与封面认证核实，不信任任何转发头。"""
    if request.method != 'POST' or not (
        re.fullmatch(r'/api/videos/[A-Za-z0-9_-]+/bypass-censor', request.url.path)
        or request.url.path == '/api/cover-service/auth/recheck'
    ):
        return None
    return _configured_https_public_origin(request, public_origin)


def _configured_https_public_origin(request, public_origin):
    if not public_origin:
        return None
    try:
        peer = ipaddress.ip_address(request.client.host)
        parsed = urlsplit(public_origin)
        port = parsed.port
    except (ValueError, AttributeError):
        return None
    host = parsed.hostname or ''
    labels = host.split('.')
    if (
        not peer.is_loopback
        or parsed.scheme != 'https'
        or not parsed.netloc
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
        or not host
        or not host.isascii()
        or host.endswith('.')
        or any(not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label) for label in labels)
        or (port is not None and not 1 <= port <= 65535)
        or parsed.netloc != (f'{host}:{port}' if port is not None else host)
        or request.headers.get('host') != parsed.netloc
    ):
        return None
    return public_origin


def create_runtime_access(db, port, *, public_origin=''):
    def boundary(request: Request):
        try:
            peer = ipaddress.ip_address(request.client.host)
        except (ValueError, AttributeError):
            raise HTTPException(403, '配置中心仅允许本机访问')
        hosts = {f'localhost:{port}', f'127.0.0.1:{port}', f'[::1]:{port}'}
        external_origin = configured_english_world_public_origin(request, public_origin)
        is_configured_public_host = external_origin is not None
        origin = request.headers.get('origin')
        expected = external_origin or f'{request.url.scheme}://{request.headers.get("host", "")}'
        if not peer.is_loopback or (request.headers.get('host') not in hosts and not is_configured_public_host):
            raise HTTPException(403, '配置中心仅允许控制台真实回环对端，不信任转发头')
        if (origin and origin != expected) or request.headers.get('sec-fetch-site') == 'cross-site':
            raise HTTPException(403, '请从当前控制台页面操作')
        if request.method not in ('GET', 'HEAD') and origin != expected:
            raise HTTPException(403, '写操作缺少有效同源验证')

    def key(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def csrf(token):
        return hashlib.sha256(('runtime-csrf:' + token).encode()).hexdigest()

    async def authorized(request: Request, response: Response, _=Depends(boundary)):
        response.headers['Cache-Control'] = 'no-store'
        token = request.cookies.get(COOKIE, '')
        if len(token) != 64 or not db.topic_session(key(token), dt.datetime.now(dt.timezone.utc)):
            raise HTTPException(403, '本机会话已过期；草稿保留，请重新打开策略页或配置中心')
        if request.method not in ('GET', 'HEAD') and not hmac.compare_digest(request.headers.get('x-runtime-csrf', ''), csrf(token)):
            raise HTTPException(403, '页面验证失败，请重新打开策略页或配置中心')
        if request.method not in ('GET', 'HEAD'):
            try:
                raw = await request.body()
                if len(raw) > 131072:
                    raise ValueError('配置请求过大')
                decode(raw)
            except (ValueError, UnicodeError) as exc:
                raise HTTPException(422, 'JSON存在重复键、非有限数值或无效内容') from exc
        return key(token)[:16]

    def page_response(request, content):
        token = request.cookies.get(COOKIE, '')
        if len(token) != 64 or not db.topic_session(key(token), dt.datetime.now(dt.timezone.utc)):
            token = secrets.token_hex(32)
            db.topic_session(key(token), dt.datetime.now(dt.timezone.utc), issue=True)
        content = content.replace('__RUNTIME_CSRF__', csrf(token))
        response = HTMLResponse(content, headers={'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer', 'X-Content-Type-Options': 'nosniff'})
        public_request = configured_english_world_public_origin(request, public_origin) is not None
        response.set_cookie(COOKIE, token, httponly=True, samesite='strict', secure=request.url.scheme == 'https' or public_request, max_age=8 * 3600, path='/')
        return response

    return boundary, authorized, page_response
