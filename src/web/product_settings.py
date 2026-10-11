"""视频号商品设置：独立路由可隔离测试，不启动发布任务。"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Callable
from datetime import datetime, timezone
from uuid import uuid4
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field
from video_processing.core.wechat_product_policy import GROUP_LABELS, parse_product_policy
from video_processing.utils.wechat_product_config import load_policy, policy_status, save_policy, PolicyConflict, decision_payload
from video_processing.utils.wechat_product_context import video_product_context
from video_processing.utils.wechat_product_catalog import catalog_view, prepare_import, import_catalog


class SaveRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    config: dict
    expected_digest: str = Field(min_length=64, max_length=64)


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    config: dict
    video_key: str | None = Field(default=None, max_length=120)
    context: dict = Field(default_factory=dict)
    product_alias: str | None = Field(default=None, max_length=100)


class CatalogImportRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    content: str = Field(min_length=1, max_length=5_000_000)
    expected_catalog_digest: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')
    expected_policy_digest: str = Field(pattern=r'^[a-f0-9]{64}$')


def create_product_settings_router(*, active: Path, status: Path, output: Path,
                                   videos: Callable[[], list[dict]], publisher_connected: bool = False) -> APIRouter:
    router = APIRouter()

    def response_view(policy):
        config = json.loads(policy.serialized)
        return {'config': config, 'status': status_view(policy), 'groups': GROUP_LABELS,
                'catalog': catalog_view(active.with_name('wechat_product_catalog.json'), config['products'])}

    def status_view(policy):
        result = selection_status(policy)
        result["publisher_connected"] = publisher_connected
        if not publisher_connected:
            result["adopted_by_last_selection"] = False
        return result

    def selection_status(policy):
        try:
            return policy_status(active, status, policy=policy)
        except (ValueError, OSError):
            # A broken receipt must not make a valid, already saved configuration look unsaved.
            p = policy
            return {'saved_version': p.version, 'saved_digest': p.digest,
                    'last_selection': None, 'adopted_by_last_selection': False,
                    'runtime_error': '最近采用记录不可读取，实际采用状态未知。'}

    def checked_origin(request: Request):
        origin = request.headers.get('origin')
        if origin and origin != f'{request.url.scheme}://{request.url.netloc}':
            raise HTTPException(403, '请从当前控制台页面操作')

    @router.get('/product-settings', response_class=HTMLResponse)
    def page():
        return HTMLResponse((Path(__file__).parent/'templates/product_settings.html').read_text(),
                            headers={'Cache-Control': 'no-store'})

    @router.get('/api/product-settings')
    def read():
        try:
            policy = load_policy(active)
            return response_view(policy)
        except (ValueError, OSError) as exc:
            raise HTTPException(503, '配置读取失败，请检查商品配置文件后重新载入。') from exc

    @router.get('/api/product-settings/videos')
    def list_videos():
        return {'videos': videos(), 'limit': 100}

    def catalog_operation(body: CatalogImportRequest, request: Request, *, apply: bool):
        checked_origin(request)
        try:
            args = dict(expected_catalog_digest=body.expected_catalog_digest,
                        expected_policy_digest=body.expected_policy_digest)
            path = active.with_name('wechat_product_catalog.json')
            if apply:
                report = import_catalog(body.content, path, active, **args)
                return dict(response_view(load_policy(active)), import_report=report)
            _, report = prepare_import(body.content, path, active, **args)
            return report
        except PolicyConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise HTTPException(422, f'清单校验未通过：{exc}') from exc
        except OSError as exc:
            raise HTTPException(503, '清单操作未确认，请重新载入核对；不要重复替换文件。') from exc

    @router.post('/api/product-settings/catalog/preview')
    def preview_catalog(body: CatalogImportRequest, request: Request):
        return catalog_operation(body, request, apply=False)

    @router.post('/api/product-settings/catalog/import')
    def apply_catalog(body: CatalogImportRequest, request: Request):
        return catalog_operation(body, request, apply=True)

    @router.put('/api/product-settings')
    def save(body: SaveRequest, request: Request):
        checked_origin(request)
        try:
            data = dict(body.config)
            data['version'] = datetime.now(timezone.utc).strftime('books-%Y%m%dT%H%M%SZ-') + uuid4().hex[:8]
            saved = save_policy(data, active, expected_digest=body.expected_digest)
            return response_view(saved)
        except PolicyConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(503, '保存失败，请检查磁盘与写入权限；可重新载入核对当前版本。') from exc

    @router.post('/api/product-settings/preview')
    def preview(body: PreviewRequest, request: Request):
        checked_origin(request)
        try:
            context = body.context
            if body.video_key:
                video = next((v for v in videos() if v['preview_key'] == body.video_key), None)
                if video is None:
                    raise HTTPException(404, '该视频已离开最近待发布列表，请重新载入视频列表。')
                context = video_product_context(output, video)
            if set(context) - {'category', 'source_channel_id', 'content_type', 'product_topic'}:
                raise ValueError('预览上下文包含未知字段')
            decision = parse_product_policy(body.config).decide(**context, product_alias=body.product_alias)
            return dict(decision_payload(decision), video_group_label=GROUP_LABELS[decision.video_group],
                        preview_only=True, platform_availability='NOT_VERIFIED')
        except (ValueError, OSError) as exc:
            raise HTTPException(422, str(exc)) from exc

    return router
