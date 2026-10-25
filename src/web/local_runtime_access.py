"""配置写入口共用真实回环对端、本机会话与 CSRF 边界。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| reply-settings-v1 | 2026-10-25 | Codex | 迁移策略页复用配置中心权限，避免绕过本机会话和同源校验。 |
"""
import datetime as dt
import hashlib
import hmac
import ipaddress
import secrets

from fastapi import Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from config.runtime_policy import decode

COOKIE = 'runtime_local_session'


def create_runtime_access(db, port):
    def boundary(request: Request):
        try:
            peer = ipaddress.ip_address(request.client.host)
        except (ValueError, AttributeError):
            raise HTTPException(403, '配置中心仅允许本机访问')
        hosts = {f'localhost:{port}', f'127.0.0.1:{port}', f'[::1]:{port}'}
        origin = request.headers.get('origin')
        expected = f'{request.url.scheme}://{request.headers.get("host", "")}'
        if not peer.is_loopback or request.headers.get('host') not in hosts:
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
        response.set_cookie(COOKIE, token, httponly=True, samesite='strict', secure=request.url.scheme == 'https', max_age=8 * 3600, path='/')
        return response

    return boundary, authorized, page_response
