"""视频号商品设置：独立路由可隔离测试，不启动发布任务。"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Callable
from datetime import datetime, timezone
from uuid import uuid4
import subprocess
import os
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field
from video_processing.core.wechat_product_policy import GROUP_LABELS, parse_product_policy
from video_processing.core.wechat_product_library import references
from video_processing.utils.wechat_product_config import load_policy, policy_status, save_policy, PolicyConflict, decision_payload
from video_processing.utils.wechat_product_context import video_product_context
from video_processing.utils.wechat_product_context import video_attachment_context
from dataclasses import replace
from video_processing.core.wechat_product_policy import ProductIdentity
from video_processing.utils.wechat_product_waits import ProductWaitStore
from video_processing.utils.wechat_product_lifecycle import impact, list_revisions, read_revision
from video_processing.utils.wechat_product_catalog import catalog_view, prepare_import, import_catalog


def _loaded_revision() -> str:
    try:
        return subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=Path(__file__).resolve().parents[2],
                              capture_output=True, text=True, check=True, timeout=3).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return 'unknown'


# 启动时冻结，磁盘 git 更新不能冒充已加载进程采用新版。
LOADED_REVISION = _loaded_revision()
LOADED_AT = datetime.now(timezone.utc).isoformat()


class SaveRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    config: dict
    expected_digest: str = Field(min_length=64, max_length=64)


class RevisionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    expected_digest: str = Field(pattern=r'^[a-f0-9]{64}$')


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
                                   videos: Callable[[], list[dict]], publisher_connected: bool = False,
                                   production_lookup: Callable | None = None, decision_lookup: Callable | None = None,
                                   legacy_lookup: Callable | None = None) -> APIRouter:
    router = APIRouter()

    def response_view(policy):
        config = json.loads(policy.serialized)
        return {'config': config, 'status': status_view(policy), 'groups': GROUP_LABELS,
                'catalog': catalog_view(active.with_name('wechat_product_catalog.json'), config['products'])}

    def status_view(policy):
        result = selection_status(policy)
        result["publisher_connected"] = publisher_connected
        from video_processing.utils.wechat_product_task import PUBLISHER_CAPABILITY
        result['publisher_capability'] = PUBLISHER_CAPABILITY if publisher_connected else None
        last = result.get('last_selection') or {}
        result['runtime_adoption_verified'] = bool(publisher_connected
            and last.get('publisher_capability') == PUBLISHER_CAPABILITY
            and last.get('config_digest') == policy.digest
            and ((last.get('phase') == 'BOUND' and last.get('binding_confirmed') is True)
                 or (last.get('phase') in {'SKIPPED', 'UNBOUND'} and last.get('unbound_confirmed') is True)))
        result['adopted_by_last_selection'] = result['runtime_adoption_verified']
        result['actual_binding_verified'] = bool(result['runtime_adoption_verified'] and last.get('binding_confirmed') is True)
        if not publisher_connected:
            result["adopted_by_last_selection"] = False
        return result

    @router.get('/api/product-settings/runtime')
    def runtime_diagnostics():
        """纯只读进程/消费者契约诊断；不创建任务、不登记首条、不写采用记录。"""
        from video_processing.utils.wechat_product_task import PUBLISHER_CAPABILITY, product_profile_scope
        from video_processing.core.wechat_product_attachment import ATTACHMENT_VERSION
        policy = load_policy(active)
        return dict(publisher_connected=publisher_connected,
                    publisher_capability=PUBLISHER_CAPABILITY if publisher_connected else None,
                    attachment_version=ATTACHMENT_VERSION, loaded_revision=LOADED_REVISION,
                    loaded_at=LOADED_AT, process_id=os.getpid(),
                    config_digest=policy.digest, config_version=policy.version,
                    internal_profile_scope=product_profile_scope(output / 'wechat_state.json'),
                    scope_is_platform_account=False, actual_task_adoption=status_view(policy)['runtime_adoption_verified'])

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

    @router.get('/api/products/manual-options')
    def manual_options():
        from video_processing.utils.wechat_product_task import manual_product_options
        try:
            return manual_product_options(active)
        except (ValueError, OSError) as exc:
            raise HTTPException(503, '商品资料暂不可用，仍可选择不绑定商品加入队列') from exc

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

    @router.get('/api/product-settings/waits')
    def waits():
        try:
            return {'scheduler_connected': publisher_connected, 'records': ProductWaitStore(output / 'wechat_product_waits.json').records(),
                    'reason': ('发布入口消费等待账本；仅明确未点击发表的任务按有界退避重新核验，已有受理/结果不明不重传。'
                               if publisher_connected else '等待调度接入，当前只展示隔离账本，未核实发布入口消费。')}
        except (ValueError, OSError) as exc:
            raise HTTPException(503, '等待记录不可读，实际状态未知') from exc

    @router.get('/api/product-settings/history')
    def history():
        try:
            return {'revisions': list_revisions(active)}
        except (ValueError, OSError) as exc:
            raise HTTPException(503, '历史快照读取失败') from exc

    @router.post('/api/product-settings/impact')
    def compare(body: SaveRequest, request: Request):
        checked_origin(request)
        try:
            return impact(active, body.config, body.expected_digest, videos(), output,
                          production_lookup=production_lookup, decision_lookup=decision_lookup)
        except PolicyConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post('/api/product-settings/history/restore-draft')
    def restore_draft(body: RevisionRequest, request: Request):
        checked_origin(request)
        try:
            candidate = json.loads(read_revision(active, body.digest).serialized)
            report = impact(active, candidate, body.expected_digest, videos(), output,
                            production_lookup=production_lookup, decision_lookup=decision_lookup)
            return {'config': candidate, 'impact': report, 'draft_only': True}
        except PolicyConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(422, '历史快照不可恢复：' + str(exc)) from exc

    @router.post('/api/product-settings/catalog/refresh')
    def refresh(request: Request):
        checked_origin(request)
        return {'connected': False, 'refreshed': False, 'reason': '真实同步适配器尚未核验；保留原清单，请导入可靠资料。'}

    @router.put('/api/product-settings')
    def save(body: SaveRequest, request: Request):
        checked_origin(request)
        try:
            data = dict(body.config)
            from video_processing.core.wechat_product_library import validate_library
            if 'library' in data:
                validate_library(data['library'], data['products'])
                catalog = catalog_view(active.with_name('wechat_product_catalog.json'), data['products'])
                account = catalog.get('account_id')
                if account and any(row['identity_status'] == 'VERIFIED' and row['account_id'] != account for row in data['library'].values()):
                    raise ValueError('商品所属发布账号与清单账号不一致')
            for alias, product in data['products'].items():
                if not product.get('enabled') and references(data, alias):
                    raise ValueError('停用商品仍被引用，请在同次保存修复：' + '、'.join(references(data, alias)))
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
            video = {}
            if body.video_key:
                video = next((v for v in videos() if v['preview_key'] == body.video_key), None)
                if video is None:
                    raise HTTPException(404, '该视频已离开最近待发布列表，请重新载入视频列表。')
                context = video_product_context(output, video)
            if set(context) - {'category', 'source_channel_id', 'content_type', 'product_topic', 'youtube_id', 'view_count', 'like_count', 'product_intent', 'product_id', 'product_title', 'production_task_id'}:
                raise ValueError('预览上下文包含未知字段')
            from video_processing.core.wechat_product_attachment import attachment_decision
            keys = ('category', 'source_channel_id', 'content_type', 'product_topic')
            decision = parse_product_policy(body.config).decide(**{k:context.get(k) for k in keys}, product_alias=body.product_alias)
            source_context = dict(video_attachment_context(output, video), **context) if video else dict(context)
            if video.get('review_id') and source_context.get('_manifest_product_context_present') is False and legacy_lookup and legacy_lookup(video['review_id'], video.get('manifest_sha256')):
                # 已绑定旧审核包不会补登记；只读预览也解释其迁移兼容决定。
                if not source_context.get('production_task_id'):
                    source_context.update(legacy_pre_cutover=True, legacy_review_id=video['review_id'],
                        legacy_manifest_sha256=video['manifest_sha256'], production_task_id='legacy-review:'+video['review_id'])
            if body.product_alias:
                chosen = parse_product_policy(body.config).products[body.product_alias].identity
                source_context.update(product_intent='PRODUCT', product_id=chosen.product_id, product_title=chosen.title)
                decision = replace(decision, candidates=(chosen,), reason='MANUAL_EXACT')
            elif source_context.get('product_intent') == 'PRODUCT':
                chosen = ProductIdentity(source_context['product_id'], source_context['product_title'])
                decision = replace(decision, candidates=(chosen,), reason='MANUAL_EXACT')
            task_id = source_context.get('task_id') or source_context.get('production_task_id') or f"pipeline:{source_context.get('youtube_id')}:{source_context.get('slice_index') or 0}"
            production = production_lookup(task_id) if production_lookup else None
            outcome = attachment_decision(source_context, production, preview=True)
            frozen = decision_lookup(task_id) if decision_lookup else None
            return dict(decision_payload(decision), attachment=outcome, frozen_task=frozen,
                        saved_task_id=task_id, source_context=source_context,
                        order_warning='尚未正式制作登记，预计结果受真实运行顺序影响' if outcome['require_product'] is None else None, video_group_label=GROUP_LABELS[decision.video_group],
                        preview_only=True, platform_availability='NOT_VERIFIED')
        except (ValueError, OSError) as exc:
            raise HTTPException(422, str(exc)) from exc

    return router
