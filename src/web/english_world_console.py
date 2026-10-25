"""英语世界管理路由：复用本机会话，只读任务与已有本地证据。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.2.0 | 2026-10-25 | Codex | 按上海当前时间展示最近的配置计划时刻。 |
| 1.1.0 | 2026-10-25 | Codex | 接入会话可信桌面动作、幂等回执、固定媒体证据与安全执行状态。 |
| 1.0.0 | 2026-10-25 | Codex | 独立管理入口、有限分页和固定类型报告；没有生产写接口。 |
"""
from pathlib import Path
import sqlite3
from datetime import date as Date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from config.settings import settings
from video_processing.english_world.console import EnglishConsole
from video_processing.english_world.daily_schedule import production_slots, validate_installed_schedule
from .local_runtime_access import create_runtime_access
from video_processing.english_world.workbench import EnglishWorldWorkbench


SHANGHAI = ZoneInfo('Asia/Shanghai')


def next_scheduled_display(slots, now=None):
    """返回上海时区最近的配置时刻；只描述计划，不代表任务已启动。"""
    current = now or datetime.now(SHANGHAI)
    current = current.replace(tzinfo=SHANGHAI) if current.tzinfo is None else current.astimezone(SHANGHAI)
    candidates = []
    for slot in slots:
        if isinstance(slot, str):
            slot = time.fromisoformat(slot)
        target = datetime.combine(current.date(), slot, tzinfo=SHANGHAI)
        if target > current:
            candidates.append(target)
    if not candidates:
        tomorrow = current.date() + timedelta(days=1)
        candidates = [datetime.combine(tomorrow, time.fromisoformat(slot) if isinstance(slot, str) else slot,
                                       tzinfo=SHANGHAI) for slot in slots]
    if not candidates:
        return None
    target = min(candidates)
    if target.date() == current.date():
        return target.strftime('%H:%M')
    if target.date() == current.date() + timedelta(days=1):
        return '明日 ' + target.strftime('%H:%M')
    return target.strftime('%Y-%m-%d %H:%M')


class WorkbenchActionRequest(BaseModel):
    task: str = Field(min_length=1, max_length=100)
    action: str = Field(min_length=1, max_length=40)
    revision: str = Field(min_length=1, max_length=80)
    operation_id: str = Field(min_length=8, max_length=80)
    payload: dict = Field(default_factory=dict)


def create_english_console_router(db, *, port, output=None, start_research=None,
                                  start_production=None, start_submission=None, start_resume=None):
    router = APIRouter()
    boundary, authorized, page_response = create_runtime_access(db, port)
    service = EnglishConsole(db, output or settings.default_output_dir)
    workbench = EnglishWorldWorkbench(db, output or settings.default_output_dir)

    @router.get('/english-world', response_class=HTMLResponse, dependencies=[Depends(boundary)])
    def page(request: Request):
        return page_response(request, (Path(__file__).parent/'templates/english_world_console.html').read_text())

    @router.get('/api/english-world/console', dependencies=[Depends(authorized)])
    def listing(q: str = Query('', max_length=160),
                category: str = Query('all', pattern='^(all|active|attention|done)$'),
                trigger: str = Query('', pattern='^(|manual|scheduled|auto)$'),
                date: str = Query('', max_length=10), page: int = Query(1, ge=1, le=100000)):
        try:
            if date:
                Date.fromisoformat(date)
            result = service.view(q=q, category=category, trigger=trigger, date=date, page=page)
        except ValueError as exc:
            raise HTTPException(422, '日期或筛选条件无效') from exc
        except (OSError, RuntimeError, sqlite3.Error) as exc:
            raise HTTPException(503, '本地任务读取失败，请稍后刷新') from exc
        try:
            schedule = {'slots': [slot.strftime('%H:%M') for slot in production_slots()],
                        'timezone': 'Asia/Shanghai', 'installed': '未核实',
                        'auto_submission': bool(settings.enable_english_world_auto_publish)}
            validate_installed_schedule(Path.home()/'Library/LaunchAgents/com.videopipeline.english-world-daily.plist')
            schedule['installed'] = '已安装时刻与配置一致；运行状态未现场探测'
        except (OSError, ValueError):
            schedule = {'slots': [slot.strftime('%H:%M') for slot in production_slots()],
                        'timezone': 'Asia/Shanghai', 'installed': '安装状态未知或时刻不一致',
                        'auto_submission': bool(settings.enable_english_world_auto_publish)}
        result['schedule'] = schedule
        return result

    @router.get('/api/english-world/console/report', dependencies=[Depends(authorized)])
    def report(task: str = Query(min_length=1, max_length=100),
               kind: str = Query(pattern='^(history|asset|audio|language|visual|safety|platform)$')):
        try:
            return service.report(task, kind)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except (OSError, ValueError, TypeError, sqlite3.Error) as exc:
            raise HTTPException(503, '证据暂不可读取，请关闭后重试') from exc

    @router.get('/api/english-world/workbench', dependencies=[Depends(authorized)])
    def workbench_listing(view: str = Query('attention', pattern='^(attention|all|runs)$'),
                          q: str = Query('', max_length=160), status: str = Query('', max_length=40),
                          trigger: str = Query('', pattern='^(|manual|scheduled|auto)$'),
                          date_from: str = Query('', max_length=10), date_to: str = Query('', max_length=10),
                          page: int = Query(1, ge=1, le=100000), history: bool = False):
        try:
            if date_from: Date.fromisoformat(date_from)
            if date_to: Date.fromisoformat(date_to)
            result = workbench.view(view=view, q=q, status=status, trigger=trigger,
                                    date_from=date_from, date_to=date_to, page=page, history=history)
            result['schedule'] = {'slots': [slot.strftime('%H:%M') for slot in production_slots()],
                                  'timezone': 'Asia/Shanghai', 'installed': '未核实',
                                  'auto_submission': bool(settings.enable_english_world_auto_publish),
                                  'message': '计划时刻来自配置；安装和运行状态尚未现场探测。'}
            try:
                validate_installed_schedule(Path.home()/'Library/LaunchAgents/com.videopipeline.english-world-daily.plist')
                result['schedule']['installed'] = '已安装时刻与配置一致；运行状态未现场探测'
            except (OSError, ValueError):
                result['schedule']['installed'] = '安装状态未知或时刻不一致'
            result['summary']['next_scheduled'] = {'time': next_scheduled_display(production_slots()),
                                                   'detail': '计划时刻；并非已启动或预计完成时间'}
            return result
        except ValueError as exc:
            raise HTTPException(422, '日期或筛选条件无效') from exc
        except (OSError, RuntimeError, sqlite3.Error) as exc:
            raise HTTPException(503, '本地工作台读取失败，请稍后刷新') from exc

    @router.get('/api/english-world/workbench/task', dependencies=[Depends(authorized)])
    def workbench_task(task: str = Query(min_length=1, max_length=100)):
        try:
            return workbench.detail(task)
        except LookupError as exc:
            raise HTTPException(404, '任务或运行记录不存在') from exc
        except (OSError, RuntimeError, sqlite3.Error) as exc:
            raise HTTPException(503, '任务详情暂不可读取') from exc

    @router.get('/api/english-world/workbench/media', dependencies=[Depends(authorized)])
    def workbench_media(task: str = Query(min_length=1, max_length=100),
                        kind: str = Query(pattern='^(video|cover|submission|submission_capture|audio|language|visual|safety)$')):
        try:
            row = service.find(task)
            record = row['_record']
            field = {'video': 'mp4_path', 'cover': 'cover_path'}.get(kind)
            if kind == 'submission_capture':
                raw_dir = record.get('reconciliation_evidence_dir')
                if raw_dir:
                    directory = Path(raw_dir).resolve()
                    if Path(raw_dir).is_symlink() or not directory.is_relative_to(workbench.console.output):
                        raise ValueError('提交截图目录身份无效')
                    for name in ('management_published.png', 'management_under_review.png', 'management_page.png'):
                        candidate = directory / name
                        if candidate.is_file() and not candidate.is_symlink():
                            return FileResponse(candidate, media_type='image/png', headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})
                raise LookupError('固定管理页截图缺失')
            if field:
                path = service.local(record.get(field))
                expected_hash = record.get('artifact_sha256' if kind == 'video' else 'cover_sha256')
                if task.startswith('review:') and not expected_hash:
                    raise ValueError('当前复核版本没有绑定媒体哈希')
                if expected_hash and workbench._sha256_file(path) != expected_hash:
                    raise ValueError('当前媒体与复核绑定哈希不一致')
                media_type = 'video/mp4' if kind == 'video' else 'image/*'
                return FileResponse(path, media_type=media_type, headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})
            return service.report(task, {'submission':'platform'}.get(kind, kind))
        except LookupError as exc:
            raise HTTPException(404, '任务或证据不存在') from exc
        except (OSError, ValueError, TypeError, sqlite3.Error) as exc:
            raise HTTPException(404, '证据缺失、身份未核实或不可读取') from exc

    @router.post('/api/english-world/workbench/actions')
    def workbench_action(body: WorkbenchActionRequest, actor: str = Depends(authorized)):
        try:
            result = workbench.action(task_id=body.task, action=body.action, revision=body.revision,
                                      operation_id=body.operation_id, payload=body.payload, actor=actor)
            if not result.get('replayed') and not result.get('operation_pending'):
                try:
                    callback = None
                    if body.action == 'approve_submission' and start_submission:
                        callback = lambda: start_submission(body.task.removeprefix('review:'))
                    elif body.action == 'research' and start_research:
                        callback = lambda: start_research(result['task_id'].removeprefix('job:'))
                    elif body.action == 'confirm_production' and start_production:
                        callback = lambda: start_production(body.task.removeprefix('job:'))
                    elif body.action == 'resume' and start_resume:
                        callback = lambda: start_resume(workbench.resume_request_path(body.task))
                    if body.action in {'approve_submission', 'research', 'confirm_production', 'resume'} and callback is None:
                        raise RuntimeError('当前服务器没有注册此动作执行器')
                    if callback:
                        callback()
                        workbench.mark_dispatch(result['audit_id'], 'ADMITTED')
                        result['dispatch_state'] = 'ADMITTED'
                except Exception as exc:
                    workbench.mark_dispatch(result['audit_id'], 'FAILED_OR_UNKNOWN', str(exc))
                    return JSONResponse(status_code=503, content={
                        'ok': False, 'operation_id': body.operation_id,
                        'error': '操作授权已记录，但执行器启动结果未知；请用原 operation_id 核验回执。',
                        'dispatch_state': 'FAILED_OR_UNKNOWN', 'audit_id': result.get('audit_id')})
            return {'ok': True, 'operation_id': body.operation_id, **result}
        except LookupError as exc:
            workbench.fail_pending_action(body.task, body.action, body.operation_id, str(exc))
            raise HTTPException(404, '任务不存在') from exc
        except PermissionError as exc:
            workbench.fail_pending_action(body.task, body.action, body.operation_id, str(exc))
            raise HTTPException(409, str(exc)) from exc
        except RuntimeError as exc:
            workbench.fail_pending_action(body.task, body.action, body.operation_id, str(exc))
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            workbench.fail_pending_action(body.task, body.action, body.operation_id, str(exc))
            raise HTTPException(422, str(exc)) from exc
        except (OSError, sqlite3.Error) as exc:
            workbench.fail_pending_action(body.task, body.action, body.operation_id, str(exc))
            raise HTTPException(503, '操作未能完成，请使用原 operation_id 核验结果') from exc

    return router
