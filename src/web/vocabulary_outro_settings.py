"""生词片尾设置与只读预览；页面操作不启动视频处理或发布。"""
from pathlib import Path
from typing import Callable

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from video_processing.core.video_groups import GROUP_LABELS
from video_processing.utils.vocabulary_outro_policy import (
    PolicyConflict, decide, digest, load_policy, parse_policy, read_record, save_policy,
)
from video_processing.utils.wechat_product_context import video_product_context


class SaveRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    config: dict
    expected_digest: str = Field(pattern=r'^[a-f0-9]{64}$')


class Context(BaseModel):
    model_config = ConfigDict(extra='forbid')
    content_type: str = Field(default='GENERAL', pattern=r'^(GENERAL|ENGLISH_WORLD_SHORT)$')
    source_channel_id: str = Field(default='', max_length=100)
    product_topic: str = Field(default='', pattern=r'^(|AI)$')


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    config: dict
    video_key: str | None = Field(default=None, max_length=120)
    context: Context = Field(default_factory=Context)


def public_record(record: dict) -> dict:
    return {key: record.get(key) for key in (
        'prefix', 'enabled', 'group', 'group_label', 'reason', 'status', 'recorded_at',
        'updated_at', 'items_count', 'recovery_checked', 'error_code', 'config_digest')}


def create_vocabulary_outro_settings_router(*, active: Path, output: Path,
                                             videos: Callable[[], list[dict]]) -> APIRouter:
    router = APIRouter()

    def origin_check(request: Request):
        origin = request.headers.get('origin')
        if origin and origin != f'{request.url.scheme}://{request.url.netloc}':
            raise HTTPException(403, '请从当前控制台页面操作')

    def view(config):
        return dict(config=config, digest=digest(config), groups=GROUP_LABELS)

    @router.get('/vocabulary-outro-settings', response_class=HTMLResponse)
    def page():
        return HTMLResponse((Path(__file__).parent / 'templates/vocabulary_outro_settings.html').read_text(),
                            headers={'Cache-Control': 'no-store'})

    @router.get('/api/vocabulary-outro-settings')
    def read():
        try:
            return view(load_policy(active))
        except (ValueError, OSError) as exc:
            raise HTTPException(503, '片尾配置读取失败，请检查配置文件后重新载入。') from exc

    @router.put('/api/vocabulary-outro-settings')
    def save(body: SaveRequest, request: Request):
        origin_check(request)
        try:
            return view(save_policy(active, body.config, body.expected_digest))
        except PolicyConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, f'配置校验未通过：{exc}') from exc
        except OSError as exc:
            raise HTTPException(503, '保存结果未确认，草稿已保留，请重新载入核对。') from exc

    @router.get('/api/vocabulary-outro-settings/videos')
    def recent_videos():
        try:
            return dict(videos=videos()[:100], limit=100)
        except (ValueError, OSError) as exc:
            raise HTTPException(503, '最近视频暂不可读取，仍可使用样例预览。') from exc

    @router.post('/api/vocabulary-outro-settings/preview')
    def preview(body: PreviewRequest, request: Request):
        origin_check(request)
        try:
            config = parse_policy(body.config)
            context = body.context.model_dump()
            frozen = None
            applicable = True
            if body.video_key:
                video = next((v for v in videos()[:100] if v['preview_key'] == body.video_key), None)
                if video is None:
                    raise HTTPException(404, '该视频已不在最近列表，请重新载入视频或使用样例。')
                context = video_product_context(output, video)
                applicable = not (video['preview_key'].startswith('english:') or video.get('manifest_path'))
                if applicable:
                    prefix = video['youtube_id'] + (f"_s{video['slice_index']}" if video.get('slice_index') else '')
                    frozen = read_record(output, prefix)
            result = decide(config, context)
            result.pop('policy')
            result['applicable'] = applicable
            return dict(decision=result, frozen=public_record(frozen) if frozen else None,
                        scope=('草稿预览；保存后仅影响尚未开始制作片尾的任务。' if applicable else
                               '独立英语世界学习卡已有随片词卡，本配置不改变它的内容和时长。'))
        except ValueError as exc:
            raise HTTPException(422, f'预览校验未通过：{exc}') from exc
        except OSError as exc:
            raise HTTPException(503, '预览暂不可用，请重试。') from exc

    @router.get('/api/vocabulary-outro-settings/records')
    def records():
        try:
            paths = sorted(output.glob('*.outro-policy.json'), key=lambda p: p.stat().st_mtime, reverse=True)[:100]
            values, unreadable = [], 0
            for path in paths:
                try:
                    values.append(public_record(read_record(output, path.name.removesuffix('.outro-policy.json'))))
                except (ValueError, OSError, KeyError, TypeError):
                    unreadable += 1
            return dict(records=values, unreadable=unreadable, limit=100)
        except OSError as exc:
            raise HTTPException(503, '执行记录读取失败，实际采用状态未知。') from exc

    return router
