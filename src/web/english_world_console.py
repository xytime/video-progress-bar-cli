"""英语世界管理路由：复用本机会话，只读任务与已有本地证据。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-25 | Codex | 独立管理入口、有限分页和固定类型报告；没有生产写接口。 |
"""
from pathlib import Path
import sqlite3
from datetime import date as Date
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from config.settings import settings
from video_processing.english_world.console import EnglishConsole
from video_processing.english_world.daily_schedule import production_slots, validate_installed_schedule
from .local_runtime_access import create_runtime_access


def create_english_console_router(db, *, port, output=None):
    router = APIRouter()
    boundary, authorized, page_response = create_runtime_access(db, port)
    service = EnglishConsole(db, output or settings.default_output_dir)

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

    return router
