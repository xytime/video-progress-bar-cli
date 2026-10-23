"""发布恢复控制台 API；页面、操作 ID 和持久批次共用领域服务。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-23 | Codex | 固定预览、分页、版本确认及幂等恢复 API。 |
"""
from __future__ import annotations
from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from video_processing.core.wechat_request_guard import WeChatRequestDeferred
from video_processing.publishing_recovery import PublishingRecoveryService


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    window: str = "24h"
    start: str | None = None
    end: str | None = None
    include_ready: StrictBool = False


class RecoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str
    expected_version: str = Field(pattern=r"^[a-f0-9]{64}$")
    preview_id: str | None = None
    selected_ids: list[int] = Field(default_factory=list, max_length=1000)
    reset_quota: StrictBool = False
    reset_cooldown: StrictBool = False
    priority: StrictBool = False
    reset_backoff: StrictBool = False
    skip_avoidance: StrictBool = False


def create_publishing_recovery_router(db, root, *, wake=None):
    router = APIRouter(prefix="/api/publishing-recovery")
    service = PublishingRecoveryService(db, root)

    def origin(request):
        if request.headers.get("origin") not in (None, str(request.base_url).rstrip("/")):
            raise HTTPException(403, "请从当前后台操作")

    def call(fn):
        try:
            return fn()
        except (ValueError, WeChatRequestDeferred) as exc:
            raise HTTPException(409, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(503, "本地状态读取失败，操作结果未确认，请刷新原操作核实。") from exc

    @router.get("/status")
    def status():
        return call(service.status)

    @router.post("/preview")
    def preview(body: PreviewRequest, request: Request):
        origin(request)
        return call(lambda: service.preview(**body.model_dump()))

    @router.get("/previews/{key}")
    def preview_page(key: str, page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100)):
        result = call(lambda: db.get_publishing_recovery_preview(key))
        items = result["items"]
        return {**result, "items": items[(page-1)*size:page*size], "total": len(items), "preview_id": key, "page": page}

    @router.post("/operations")
    def execute(body: RecoveryRequest, request: Request):
        origin(request)
        result = call(lambda: service.execute(body.model_dump()))
        if wake and result["state"] == "QUEUED":
            wake()
        return result

    @router.get("/operations")
    def operations(page: int = Query(1, ge=1), size: int = Query(10, ge=1, le=50)):
        return call(lambda: db.list_publishing_recovery_operations(limit=size, offset=(page-1)*size))

    @router.get("/operations/{key}")
    def operation(key: str):
        result = call(lambda: db.get_publishing_recovery_operation(key))
        if not result:
            raise HTTPException(404, "操作尚未记录，请保留原操作 ID 核对")
        return result

    @router.post("/operations/{key}/cancel")
    def cancel(key: str, request: Request):
        origin(request)
        return call(lambda: service.cancel(key))

    return router
