"""本机候选工作台独立路由；会话、真实对端、Origin/Host、CSRF 与对象 CAS。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 0.4.0 | 2026-10-13 | Codex | 关键词定时采集、统一评分和受控准入隔离实现 |
| 1.0.1 | 2026-10-12 | Codex | 单飞恢复、清理与退出隔离，提供本机脱敏健康状态 |
| 1.0.0 | 2026-10-11 | Codex | v0.2 管理/候选/审计入口；默认拒绝生产搜索，无加工入口 |
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import secrets
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from video_processing.core.topic_candidates import TopicError

COOKIE = "topic_local_session"


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class TopicBody(StrictBody):
    name: str = Field(min_length=1, max_length=40)
    query: str = Field(min_length=1, max_length=120)
    category: str = Field(max_length=30)
    lookback_days: int = 1
    language: str = "en"
    min_duration: int = 30
    valid_days: int = 7


class EditBody(TopicBody):
    version: int = Field(ge=1)


class StateBody(StrictBody):
    version: int = Field(ge=1)
    state: str = Field(pattern="^(ACTIVE|PAUSED|ARCHIVED)$")
    valid_days: int | None = Field(default=None, ge=1, le=30)


class SearchBody(StrictBody):
    version: int = Field(ge=1)
    idempotency: str = Field(pattern=r"^[a-zA-Z0-9_-]{16,80}$")


class RenewBody(StrictBody):
    version: int = Field(ge=1)
    valid_days: int = Field(default=7, ge=1, le=30)
    restore: bool = False


class DecisionBody(StrictBody):
    revision: int = Field(ge=1)
    decision_revision: int = Field(ge=1)
    content_version: str = Field(pattern=r"^[a-f0-9]{64}$")
    state: str = Field(pattern="^(NEW|SAVED|REJECTED)$")
    reason: str | None = Field(default=None, max_length=30)


class ToggleBody(StrictBody):
    version: int = Field(ge=1)
    enabled: bool


class ModeBody(StrictBody):
    version: int = Field(ge=1)
    mode: str = Field(pattern="^(OFF|DISCOVERY_ONLY)$")


def create_topic_candidates_router(service_factory, *, port):
    from video_processing.topic_tracker.runtime import TopicRuntime
    runtime = TopicRuntime(service_factory)
    service = runtime.service

    async def clean_loop():
        while True:
            await asyncio.sleep(60)
            try:
                await run_in_threadpool(runtime.clean)
            except TopicError:
                # 数据库忙不代表清理成功；下一轮重试，页面读前也强制清理。
                continue

    @asynccontextmanager
    async def lifespan(app):
        app.state.topic_runtime = runtime
        try:
            await run_in_threadpool(service)
        except TopicError:
            # 该模块暂不可用时，原有后台仍可启动；专题页面返回明确的 503。
            pass
        task = asyncio.create_task(clean_loop())
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            await run_in_threadpool(runtime.stop)

    router = APIRouter(lifespan=lifespan)

    def boundary(request: Request):
        try:
            peer = ipaddress.ip_address(request.client.host)
        except (ValueError, AttributeError):
            raise HTTPException(403, "候选工作台仅允许本机访问")
        hosts = {f"localhost:{port}", f"127.0.0.1:{port}", f"[::1]:{port}"}
        if not peer.is_loopback or request.headers.get("host", "") not in hosts:
            raise HTTPException(403, "请在本机通过控制台回环地址访问")
        origin = request.headers.get("origin")
        expected = f"{request.url.scheme}://{request.headers['host']}"
        if (origin and origin != expected) or request.headers.get("sec-fetch-site") == "cross-site":
            raise HTTPException(403, "请从当前控制台页面操作")
        if request.method not in ("GET", "HEAD") and origin != expected:
            raise HTTPException(403, "写操作缺少有效页面来源")

    def token_key(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def csrf(token):
        return hashlib.sha256(("topic-csrf:" + token).encode()).hexdigest()

    def authorized(request: Request, _=Depends(boundary)):
        token = request.cookies.get(COOKIE, "")
        if len(token) != 64:
            raise HTTPException(403, "本机会话已过期，请重新打开候选工作台")
        if request.method not in ("GET", "HEAD") and not hmac.compare_digest(request.headers.get("x-topic-csrf", ""), csrf(token)):
            raise HTTPException(403, "页面验证已过期，请重新载入")
        tracker = call(service)
        if not call(tracker.db.topic_session, token_key(token), tracker.clock()):
            raise HTTPException(403, "本机会话已过期，请重新打开候选工作台")
        return token_key(token)[:16]

    def call(method, *args, **kwargs):
        try:
            return method(*args, **kwargs)
        except TopicError as exc:
            if exc.code in {"DATABASE_BUSY", "DATABASE_ERROR", "LOCK_UNAVAILABLE", "READ_ONLY"}:
                with runtime.mutex:
                    runtime.failure(exc)
            raise HTTPException(exc.status, dict(code=exc.code, message=exc.message)) from exc

    @router.get("/api/topic-candidates/health", dependencies=[Depends(boundary)])
    def health():
        return dict(runtime.health)

    @router.get("/topic-candidates", response_class=HTMLResponse, dependencies=[Depends(boundary)])
    def page(request: Request):
        tracker = call(service)
        call(runtime.clean)
        token = request.cookies.get(COOKIE, "")
        if len(token) != 64 or not call(tracker.db.topic_session, token_key(token), tracker.clock()):
            token = secrets.token_hex(32)
            call(tracker.db.topic_session, token_key(token), tracker.clock(), issue=True)
        html = (Path(__file__).parent / "templates/topic_candidates.html").read_text().replace("__TOPIC_CSRF__", csrf(token))
        response = HTMLResponse(html, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff"})
        response.set_cookie(COOKIE, token, httponly=True, samesite="strict", max_age=8 * 3600, path="/", secure=request.url.scheme == "https")
        return response

    @router.get("/api/topic-candidates/state")
    def view(actor=Depends(authorized)):
        return call(service().view)

    @router.post("/api/topic-candidates/topics")
    def create(body: TopicBody, actor=Depends(authorized)):
        return call(service().db.topic_save, body.model_dump(), actor, service().clock())

    @router.put("/api/topic-candidates/topics/{topic_id}")
    def edit(topic_id: str, body: EditBody, actor=Depends(authorized)):
        return call(service().db.topic_save, body.model_dump(exclude_unset=True), actor, service().clock(), topic_id=topic_id, expected_version=body.version)

    @router.post("/api/topic-candidates/topics/{topic_id}/state")
    def transition(topic_id: str, body: StateBody, actor=Depends(authorized)):
        return call(service().db.topic_transition, topic_id, body.version, body.state, actor, service().clock(), body.valid_days)

    @router.post("/api/topic-candidates/topics/{topic_id}/search", status_code=202)
    def search(topic_id: str, body: SearchBody, actor=Depends(authorized)):
        return call(service().start, topic_id, body.version, body.idempotency, actor)

    @router.post("/api/topic-candidates/topics/{topic_id}/renew")
    def renew(topic_id: str, body: RenewBody, actor=Depends(authorized)):
        return call(service().db.topic_renew, topic_id, body.version, body.valid_days, body.restore, actor, service().clock())

    @router.put("/api/topic-candidates/topics/{topic_id}/schedule")
    def schedule(topic_id: str, body: ToggleBody, actor=Depends(authorized)):
        return call(service().schedule, topic_id, body.version, body.enabled, actor)

    @router.put("/api/topic-candidates/admission")
    def admission(body: ToggleBody, actor=Depends(authorized)):
        return call(service().admission, body.enabled, body.version, actor)

    @router.put("/api/topic-candidates/mode")
    def mode(body: ModeBody, actor=Depends(authorized)):
        return call(service().mode, body.mode, body.version, actor)

    @router.get("/api/topic-candidates/videos")
    def candidates(topic_id: str = "", state: str = Query("", pattern="^(|NEW|SAVED|REJECTED)$"),
                   eligibility: str = Query("", pattern="^(|CHECKABLE|INCOMPLETE|RESTRICTED|UNAVAILABLE)$"),
                   q: str = Query("", max_length=120), page: int = Query(1, ge=1, le=10000), actor=Depends(authorized)):
        return call(service().candidates, topic_id=topic_id, state=state, eligibility=eligibility, q=q, page=page)

    @router.post("/api/topic-candidates/videos/{key}/decision")
    def decide(key: str, body: DecisionBody, actor=Depends(authorized)):
        call(service().decide, key, body.model_dump(), actor)
        return dict(saved=True)

    @router.get("/api/topic-candidates/audit")
    def audit(actor=Depends(authorized)):
        return call(service().db.topic_audit_records)

    return router
