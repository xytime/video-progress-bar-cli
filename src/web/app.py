"""Web 控制中心后端 — FastAPI 仪表盘服务

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 3.23.0 | 2026-08-21 | Codex | 控制台对视频号生命周期 fail-closed：中止/孤儿发布先落未绑定账本，禁用无删除证明的重发，并阻断通用重试、改规格、删除和硬重置 |
| 3.24.0 | 2026-08-21 | Codex | 回收无存活进程的预提交孤儿任务；提交后状态继续 fail-closed，且待绑定提交进入待核验而非加工队列 |
| 3.25.0 | 2026-08-21 | Codex | 新增英语世界短视频候选研究与二次制作确认 API；不接入通用队列或发布入口 |
| 3.26.0 | 2026-08-23 | Codex | 新增英语世界 Telegram 审核项的显式投稿批准入口与独立 worker，不复用通用队列 |
| 3.27.0 | 2026-08-28 | Codex | 微信重登后仅续投一条登录前明确失败的自动英语世界项；已受理、未确认和历史项继续禁止自动重传。 |
| 3.28.0 | 2026-08-29 | Codex | 新增 Telegram 单任务微信发布 lease 候选、签发与立即启动 API；两小时一次性授权不扩散到自动队列。 |
| 3.22.0 | 2026-08-20 | Codex | 新增 Highlight 候选人工选定 API，并创建独立发布主体但不触发渲染或发布 |
| 3.21.0 | 2026-08-20 | Codex | 新增手动 Highlight Job 候选分析 API；独立于既有视频状态机和任何发布入口 |
| 3.20.0 | 2026-08-20 | Codex | 禁止视频号标题回查接口启动浏览器；仅允许发布链写入平台原生 ID 后进入精确确认流程 |
| 3.19.0 | 2026-08-20 | Codex | 视频号待确认增加作品管理页受控回查入口；通用重试拒绝绕过在途/成功视频号账本 |
| 1.0.0 | 2026-05-21 | Claude_Sonnet_4.6_Thinking_planning | 初始创建 Dashboard API 服务 |
| 1.1.0 | 2026-05-21 | Claude_Sonnet_4.6_Thinking_planning | 新增频道管理 API：add/delete，yt-dlp 验证后入库 |
| 1.2.0 | 2026-05-22 | Gemini_3.5_Flash_fast | 修复手工添加视频（含 TG Bot 提交）卡在 PENDING 不自动触发的问题 |
| 2.0.0 | 2026-05-26 | Claude_Sonnet_4.6_Thinking_planning | [v7.0 Phase 3+4] SIGTERM 强杀+黑名单墓碑、人工调分锁、频道手动隔离(MANUAL_ONLY) |
| 2.0.1 | 2026-05-26 | Claude_Sonnet_4.6_Thinking_planning | [v7.0 Review Fix] BUG-1: SIGTERM 注册移至主线程 startup_event；清理函数内重复 import |
| 2.1.0 | 2026-05-26 | Claude_Sonnet_4.6_Thinking_planning | [v7.0 Phase 6] SEC-1: urlparse 严格 netloc 校验替换 in-string 旁路；SEC-2: add_channel 覆盖 MANUAL_ONLY 防隐式提升 |
| 2.1.1 | 2026-05-26 | Gemini_3.5_Flash_planning           | [v7.0 macOS Fix] 解决 killpg(pid, 0) 对未收割僵尸进程返回 EPERM 导致误报的 macOS 特有行为 |
| 2.2.0 | 2026-05-27 | Gemini_3.5_Flash                    | 新增 trim_start/trim_end 请求参数接收与安全校验 |
| 2.3.0 | 2026-05-27 | Gemini_2.0_Flash_fast               | 适配微信扫码登录 QR 服务与状态查询 API |
| 2.3.1 | 2026-05-27 | Gemini_3.5_Flash_planning           | 修复由于缺少 re 模块导致的视频添加接口 500 报错 |
| 2.4.0 | 2026-05-27 | Gemini_3.5_Flash_High_planning      | 升级 delete_video 接口支持单个 slice 物理删除；新增获取所有 slices 与重试单个 slice 的 API |
| 2.5.0 | 2026-05-27 | Unknown_Model_planning              | 新增 process_slice_now 接口以支持立即强制执行切片子任务 |
| 2.6.0 | 2026-05-28 | Gemini_3.5_Flash_planning           | 新增 stop_video 接口以支持真实停止进程并状态置为 FAILED |
| 2.7.0 | 2026-05-28 | Gemini_3.5_Flash_planning           | 新增后台队列自动轮询器 _queue_runner_loop 自动执行切片/高分任务 |
| 2.8.0 | 2026-05-28 | Gemini_3.5_Flash_planning           | 使用 python -u 启动子进程以实现 pipeline.log 实时无缓冲日志输出 |
| 2.9.0 | 2026-06-01 | Claude_Sonnet_4.6_Thinking_planning | 新增 respec_video 端点：停止当前处理、覆盖规格并重新入队；add_video_manual 重复检测补充 video_id/title 返回 |
| 3.0.0 | 2026-06-07 | Claude_Sonnet_4.6_Thinking_planning | 新增 /api/trending-keywords 端点，整合 HN 热词注入功能到后台 Web UI 热词监控 Tab |
| 3.1.0 | 2026-06-07 | Claude_Sonnet_4.6_Thinking_planning | [BugFix+防卡] _run_pipeline_manager 使用 settings.get_active_proxies() 动态代理注入；_queue_runner_loop 新增 purge_stale_tasks() 自动清理卡死 DOWNLOADING 任务 |
| 3.2.0 | 2026-06-08 | Claude_Sonnet_4.6_Thinking_planning | 新增 _wechat_keepalive_loop：定期局动 wechat_keepalive.py 子进程刷新 Session，防止闲置掉线 |
| 3.3.0 | 2026-06-09 | Gemini_2.5_Pro_planning             | 修复 DISCOVERY 源视频被 process_video_now / update_video_priority 误触发自动处理的 Bug；API 层防火墙 |
| 3.4.0 | 2026-06-11 | Gemini_3.5_Flash_planning           | [高赞+防泄露] 新增 _is_pipeline_manager_running；全量管线去重，防止并发阻塞导致进程泄露 |
| 3.4.1 | 2026-06-11 | Claude_Opus_4.6_Thinking_planning   | [P0修复] _run()闭包缺少global声明导致刷新按钮一次性失效；fcntl提升为top-level import |
| 3.5.0 | 2026-06-13 | Claude_Opus_4.8                     | 新增 promote_video 端点 (/api/videos/{id}/promote)：高赞发现视频一键转 MANUAL(100) 并立即触发管线，替代删除+重粘的绕路 |
| 3.6.0 | 2026-06-13 | Claude_Opus_4.8                     | 新增 censor_keywords + bypass_censor 端点：审查失败视频「🔓 复核放行」——返回命中词/标题+字幕关键词标签云，确认后置 bypass 标志并重新触发管线 |
| 3.7.0 | 2026-06-13 | Claude_Opus_4.8                     | 新增 download_progress 端点：轮询 output/{yid}.f* 临时文件大小 + info.json.filesize_approx 估算下载进度/速度/ETA（下载器无关，零侵入下载流程） |
| 3.8.0 | 2026-06-13 | Claude_Opus_4.8                     | 新增 republish_video 端点 (/api/videos/{id}/republish)：已完成视频「🔁 再次发布」——重置 PENDING 重新触发，复用 GC 保留的成片/封面/文案 checkpoint 秒级重发 |
| 3.9.0 | 2026-06-15 | Claude_Opus_4.8                     | [BUG-1 配套] bypass_censor / censor_keywords / _read_subtitle_text 增加 slice_index 粒度，与管线侧透传对齐，使审查类失败的切片可按 (id,slice) 单独放行 |
| 3.10.0 | 2026-06-15 | Claude_Opus_4.8                    | [BUG-5] clear_waitlist 改走 DAL get_waitlist_clearable_ids（排除 DISCOVERY），消除业务层裸 SQL，修复一键清空击穿发现防火墙 |
| 3.11.0 | 2026-06-18 | Claude_Opus_4.8                    | [盘中重负载保护] 新增 _in_us_market_window()；_auto_pipeline_loop 与 _queue_runner_loop 在美股盘中(ET 09:15–16:15,工作日,自动夏/冬令时)暂停重型管线，避免抢占共享主机实盘行情管线 CPU；开关 settings.enable_market_hours_guard；仪表盘端口默认 8765→9100 |
| 3.12.0 | 2026-06-28 | Claude_Opus_4.8                    | 新增 POST /api/videos/retry-recent?hours=N：批量重置最近 N 小时 FAILED 为 PENDING（不逐条触发，交调度器按节奏重发），供 Telegram /retry <小时数> |
| 3.13.0 | 2026-07-04 | Gemini_3.5_Flash_planning           | [anduchencang] 新增 /demo 交互式英文精读体验页路由 |
| 3.14.0 | 2026-07-05 | Codex                               | 修复微信扫码状态假阳性：状态接口改信真实登录成功标记，并阻止 Web 端重复启动并发登录进程 |
| 3.14.1 | 2026-07-05 | Codex                               | /api/videos/retry-recent 批量重试纳入 LOGIN_REQUIRED，覆盖微信登录过期恢复场景 |
| 3.14.2 | 2026-07-05 | Codex                               | 新增 /api/videos/retry-recent/preview 只读预览，供 Telegram /status 展示批量重试会影响几条 |
| 3.14.3 | 2026-07-07 | Codex                               | 微信扫码登录启动前先失效旧登录标记，并在状态接口中显式返回登录流程是否仍在进行，避免后台误把旧态判成成功 |
| 3.14.4 | 2026-07-08 | Codex                               | 调度器新增孤儿 PUBLISHING 回收：发现发布进程已死但状态长时间未回收时，保守降级为 FAILED 并提示先核对视频号后台，避免队列被无限卡住 |
| 3.15.0 | 2026-07-10 | Codex                               | 会话临期自动预热重登：保留旧 state，提前经 Telegram 推送二维码，扫码成功后才替换会话 |
| 3.16.0 | 2026-07-13 | Codex                               | 新增 AI 处理审计 API，后台可读取 provider 尝试、降级和质量结果 |
| 3.17.0 | 2026-07-23 | Codex                               | 新增三平台补录预览与抖音补录确认入队 API |
| 3.18.0 | 2026-07-24 | Codex                               | [新任务启动保护] _in_us_market_window 跟随 settings 的 ET 08:15–16:15 窗口，仅阻止调度器启动新管线 |
| 3.18.1 | 2026-07-27 | Codex                               | 微信扫码登录成功后自动恢复 LOGIN_REQUIRED 为 PENDING，交由既有队列调度器按分数线重发 |
| 3.18.2 | 2026-07-30 | Codex                               | 音轨规格改变时失效竖版成片与封面缓存，避免配音版继续复用原声封面       |
| 3.18.3 | 2026-07-31 | Codex                               | 同步删除封面来源清单，防止音轨规格切换后遗留哈希失配的封面证明         |
| 3.18.4 | 2026-08-04 | Codex                               | 仪表盘列表优先展示真实投递短标题，避免本地 zh_title 与微信后台标题错位 |
| 3.18.5 | 2026-08-05 | Codex                               | 后台标题翻译拒绝 Error 500 响应并改走 zh_title DAL，防止列表源译名污染 |
| 3.18.6 | 2026-08-07 | Codex                               | 新增抖音 CANCELED 账本的显式人工重新入队 API，保留原失败记录供审计 |
| 3.18.7 | 2026-08-09 | Codex                               | 手动入队显式接收内容生产类型，支持英语世界短视频的持久化标识 |
| 3.18.8 | 2026-08-11 | Codex                               | 视频号平台已受理但未公开的任务展示为 UNDER_REVIEW，禁止将其作为可重试或已完成状态 |
| 3.18.9 | 2026-08-14 | Codex                               | 将平台待确认状态从实际加工计数中分离，避免仪表盘把已提交待回查误报为处理中 |
| 3.18.10 | 2026-08-26 | Codex                              | 所有微信登录入口统一使用带平台提交证据保护的任务恢复逻辑 |
"""
import hashlib
import logging
import os
import re  # [Gemini_3.5_Flash_planning] 统一导入正则模块
import fcntl  # [Claude_Opus_4.6_Thinking_planning] 用于 _is_pipeline_manager_running() 非阻塞锁探测
import sys
import signal
import time
import shutil
import subprocess
import threading
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlparse

# 确保能导入 src 下的模块
_src = str(Path(__file__).parent.parent)
if _src not in sys.path:
    sys.path.insert(0, _src)

from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from video_processing.db.database import PipelineDB
from video_processing.content_types import CONTENT_TYPE_GENERAL, normalize_content_type
from config.settings import settings  # [Claude_Sonnet_4.6_Thinking_planning] v7.0: 模块顶层导入，避免函数体内重复 import
from video_processing.utils.translation_helper import translate_text as _translate_text  # [Claude_Sonnet_4.6_planning] 统一翻译入口
from video_processing.utils.generated_content_validation import is_upstream_error_response
from video_processing.highlight import HighlightJobService
from video_processing.english_world import EnglishWorldResearchService
from web.listening_transcriber import router as listening_transcriber_router

app = FastAPI(title="Video Pipeline Control Center", version="1.1.0")
app.include_router(listening_transcriber_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

# 使用全局 DB 实例（每次方法调用内部创建新连接，线程安全）
db = PipelineDB()
_wechat_login_thread: Optional[threading.Thread] = None
_WECHAT_AUTO_RELOGIN_FLAG = "wechat_auto_relogin_started.flag"


def _start_highlight_analysis(job_id: str) -> None:
    """独立启动轻量候选分析；不调用 PipelineManager，也不启动下载/渲染/发布。"""
    def _run() -> None:
        service = HighlightJobService(db, Path(__file__).parent.parent.parent)
        service.analyze(job_id)

    threading.Thread(
        target=_run,
        daemon=True,
        name=f"highlight-plan-{job_id[:8]}",
    ).start()


def _start_english_world_research(job_id: str) -> None:
    """异步进行只读元数据研究；不会下载媒体、渲染学习卡或提交任何平台。"""
    def _run() -> None:
        EnglishWorldResearchService(db).research(job_id)

    threading.Thread(
        target=_run,
        daemon=True,
        name=f"english-world-research-{job_id[:8]}",
    ).start()


def _start_english_world_submission(review_id: str) -> None:
    """仅启动某一已批准审核项的专用投稿器；领取动作在子进程内原子完成。"""
    project_root = Path(__file__).parent.parent.parent
    python_bin = project_root / ".venv" / "bin" / "python"
    runner = project_root / "scripts" / "submit_english_world_review.py"

    def _run() -> None:
        try:
            result = subprocess.run(
                [str(python_bin), str(runner), "--review-id", review_id],
                cwd=str(project_root), timeout=30 * 60, text=True, capture_output=True,
            )
            if result.returncode:
                logging.getLogger(__name__).error(
                    "[EnglishWorld] submission worker returned %s for %s: %s",
                    result.returncode, review_id[:8], result.stderr[-500:],
                )
        except subprocess.TimeoutExpired:
            logging.getLogger(__name__).error(
                "[EnglishWorld] submission worker timed out for %s; inspect its independent review ledger",
                review_id[:8],
            )
        except OSError as exc:
            logging.getLogger(__name__).exception(
                "[EnglishWorld] failed to launch submission worker for %s: %s", review_id[:8], exc,
            )

    threading.Thread(
        target=_run,
        daemon=True,
        name=f"english-world-submit-{review_id[:8]}",
    ).start()


def _wechat_login_env() -> dict:
    """构建登录子进程环境，确保 Telegram 凭据随设置注入而不是依赖父进程环境。"""
    proxy_keys = frozenset({
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
        "http_proxy", "https_proxy", "all_proxy",
    })
    env = {k: v for k, v in os.environ.items() if k not in proxy_keys}
    env["PYTHONPATH"] = str(Path(__file__).parent.parent)
    if settings.telegram_bot_token:
        env["TELEGRAM_BOT_TOKEN"] = settings.telegram_bot_token
    if settings.active_telegram_chat_id:
        env["TELEGRAM_CHAT_ID"] = settings.active_telegram_chat_id
    if settings.telegram_admin_ids:
        env["TELEGRAM_ADMIN_IDS"] = settings.telegram_admin_ids
    return env


def _restore_login_required_after_wechat_login() -> int:
    """微信重登成功后恢复因登录态失效暂停的任务，让既有调度器按分数线重发。"""
    import logging

    restore = getattr(db, "restore_login_required_videos", None)
    if restore is not None:
        count = restore()
        if count:
            logging.getLogger(__name__).info(
                "[WeChatLogin] Restored %s LOGIN_REQUIRED task(s) to PENDING after login success.",
                count,
            )
        return count

    # 兼容精简测试替身/旧外部调用者；生产 PipelineDB 始终走上面的原子 DAL 方法。
    rows = db.get_videos_by_status("LOGIN_REQUIRED")
    count = 0
    for row in rows:
        db.update_video_status(
            row["youtube_id"],
            "PENDING",
            error_msg=None,
            slice_index=int(row.get("slice_index") or 0),
        )
        count += 1
    if count:
        logging.getLogger(__name__).info(
            "[WeChatLogin] Restored %s LOGIN_REQUIRED task(s) to PENDING after login success.",
            count,
        )
    return count


def _resume_eligible_english_world_after_wechat_login() -> Optional[dict]:
    """登录成功后续投一条可证明未触达平台的英语世界自动任务。

    领取规则在 DAL 内原子执行：仅 ``AUTO_POLICY``、``exit=2``、近期且此前
    未恢复过一次的记录可通过。此处不扫描历史项，也不触碰 ``UNCERTAIN`` 或
    已受理记录。
    """
    if not settings.enable_english_world_auto_publish or settings.wechat_publishing_paused:
        return None
    claim = getattr(db, "claim_english_world_login_recovery", None)
    if claim is None:
        return None
    item = claim(max_age_hours=12)
    if item:
        _start_english_world_submission(str(item["id"]))
        logging.getLogger(__name__).info(
            "[EnglishWorld] Resuming one pre-login failure after WeChat login: %s",
            str(item["id"])[:8],
        )
    return item


def _start_wechat_login_flow(*, headless: bool = True, preserve_marker: bool = False, reason: str = "manual") -> dict:
    """启动单实例微信登录；自动预热时保留旧登录标记和 state，避免提前把现行会话判死。"""
    prj_root = Path(__file__).parent.parent.parent
    python = str(prj_root / ".venv" / "bin" / "python")
    script = str(prj_root / "scripts" / "wechat_uploader.py")
    state = prj_root / "output" / "wechat_state.json"
    qr_path = prj_root / "output" / "login_qr.png"
    login_at_path = prj_root / "output" / "wechat_login_at.txt"
    auto_flag = prj_root / "output" / _WECHAT_AUTO_RELOGIN_FLAG

    if _is_wechat_login_running():
        return {"success": True, "already_running": True, "message": "微信登录程序已在运行"}

    if auto_flag.exists():
        try:
            # 未扫码的登录流程最多保留 15 分钟，避免一次失败永久阻塞后续预热。
            if time.time() - auto_flag.stat().st_mtime < 15 * 60:
                return {"success": True, "already_running": True, "message": "自动重登二维码仍在有效等待期"}
            auto_flag.unlink()
        except Exception:
            pass

    if not preserve_marker:
        try:
            login_at_path.unlink()
        except FileNotFoundError:
            pass
    try:
        qr_path.unlink()
    except FileNotFoundError:
        pass

    args = [python, script, "--login-only", "--relogin", "--state", str(state)]
    if not headless:
        args.append("--no-headless")
    if preserve_marker:
        try:
            auto_flag.write_text(str(int(time.time())), encoding="utf-8")
        except Exception:
            pass

    def _run():
        try:
            result = subprocess.run(args, cwd=str(prj_root), env=_wechat_login_env())
            if result.returncode == 0 and _wechat_login_marker_active(login_at_path):
                _restore_login_required_after_wechat_login()
                _resume_eligible_english_world_after_wechat_login()
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error(f"WeChat login subprocess failed ({reason}): {exc}")

    global _wechat_login_thread
    _wechat_login_thread = threading.Thread(target=_run, daemon=True, name="wechat-login")
    _wechat_login_thread.start()
    return {"success": True, "message": "微信登录流程已启动"}


def _wechat_session_needs_auto_relogin() -> bool:
    """判断是否已接近服务端绝对会话上限，且当前没有进行中的自动重登。"""
    if not settings.wechat_auto_relogin_enabled or not settings.wechat_keepalive_enabled:
        return False
    prj_root = Path(__file__).parent.parent.parent
    login_at = prj_root / "output" / "wechat_login_at.txt"
    auto_flag = prj_root / "output" / _WECHAT_AUTO_RELOGIN_FLAG
    try:
        if auto_flag.exists() and time.time() - auto_flag.stat().st_mtime < 15 * 60:
            return False
        stamp = int(login_at.read_text(encoding="utf-8").strip())
        return (time.time() - stamp) / 3600.0 >= settings.wechat_session_warn_hours
    except Exception:
        return False

def _translate_title_task(youtube_id: str, english_title: str):
    """后台任务：调用翻译接口（阿里云 MT 优先）翻译标题并更新数据库。

    [Claude_Sonnet_4.6_planning] 改用 translation_helper.translate_text，
    使标题翻译与字幕翻译共享相同的阿里云 MT 优先策略。
    """
    try:
        zh_title = _translate_text(english_title, src_lang="auto", target_lang="zh-CN")
        if zh_title and zh_title != english_title and not is_upstream_error_response(zh_title):
            db.update_video_zh_title(youtube_id, zh_title)
            print(f"[Translator] {youtube_id} translated: {zh_title}")
        elif is_upstream_error_response(zh_title):
            existing = db.get_video_by_youtube_id(youtube_id)
            if existing and is_upstream_error_response(existing.get("zh_title") or ""):
                db.update_video_zh_title(youtube_id, english_title)
            print(f"[Translator] {youtube_id} returned upstream error page; keeping source title")
    except Exception as e:
        print(f"[Translator] Failed to translate {youtube_id}: {e}")
    finally:
        # [Gemini_3.1_Pro_High] 手工加急视频翻译完成后立即触发异步处理管线，通过 claim_video_for_processing 防止竞态
        try:
            if db.claim_video_for_processing(youtube_id):
                video = db.get_video_by_youtube_id(youtube_id)
                if video:
                    print(f"[Scheduler] Auto-triggering pipeline for manual video: {youtube_id}")
                    _trigger_video_async(video)
        except Exception as trigger_err:
            import logging
            logging.getLogger(__name__).error(f"[Scheduler] Failed to auto-trigger video {youtube_id}: {trigger_err}")

def _in_us_market_window() -> bool:
    """[Claude_Opus_4.8] 美股盘中重负载保护窗口判定，委托 settings 单一真相源
    （ET 08:15–16:15 工作日，自动夏/冬令时；与 pipeline_manager 共用同一实现）。"""
    return settings.is_us_market_guard_window()


def _auto_pipeline_loop():
    """后台循环任务：启动后延迟10秒执行首次管线，之后每4小时执行一次"""
    import time
    time.sleep(10)
    while True:
        try:
            # [Claude_Opus_4.8] 美股盘中保护：盘中跳过重型全量管线，避免抢占实盘行情管线 CPU
            if _in_us_market_window():
                print("[Scheduler] 美股盘中，跳过全量管线（重负载保护）。")
            else:
                # 复用已有的全量管线触发逻辑
                run_full_pipeline()
                print("[Scheduler] Auto-triggered full pipeline run.")
        except Exception as e:
            print(f"[Scheduler] Auto pipeline error: {e}")
        time.sleep(14400)  # 4 小时 = 14400 秒


def _run_pipeline_manager():
    """[Gemini_3.5_Flash_planning] 后台运行 pipeline_manager 进程处理高分视频"""
    prj_root = Path(__file__).parent.parent.parent
    python = str(prj_root / ".venv" / "bin" / "python")
    src_dir = str(prj_root / "src")
    log_path = prj_root / "output" / "pipeline.log"
    log_path.parent.mkdir(exist_ok=True)
    # [Claude_Sonnet_4.6_Thinking_planning] v3.1.0: 动态代理注入策略
    # 1. 先清除老代理变量，防止某些历史变量影响子进程
    # 2. 再检测当前代理可用性，就绣将代理注入，不就绣则不注入
    _proxy_keys = frozenset({'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy'})
    env_clean = {k: v for k, v in os.environ.items() if k not in _proxy_keys}
    env_clean.update(settings.get_active_proxies())  # 就绣注入，不就绣空 update（无副作用）

    import subprocess as sp
    try:
        with open(log_path, "a") as f:
            f.write("\n=== Auto-triggered queue pipeline run ===\n")
            # [Gemini_3.5_Flash_planning] 使用 -u 启用无缓冲输出
            sp.run([python, "-u", "-m", "video_processing.pipeline_manager"],
                   cwd=src_dir, stdout=f, stderr=f, env=env_clean)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"_run_pipeline_manager failed: {e}")


def _queue_runner_loop():
    """[Gemini_3.5_Flash_planning] 每15秒巡检一次：如果有 >=75 分且状态为 PENDING 的任务，且当前没有管线任务在运行，则自动启动管线处理"""
    import time
    # [Gemini_3.5_Flash_planning] 自动执行队列轮询逻辑，解决切片子任务需要手动点击的痛点
    time.sleep(5)
    while True:
        try:
            recovered = _recover_orphaned_publishing_tasks(stale_minutes=30)
            if recovered > 0:
                logging.getLogger(__name__).warning(
                    f"[Scheduler] Recovered {recovered} orphaned PUBLISHING task(s) to SUBMITTED_UNBOUND"
                )

            recovered_pre_submission = _recover_orphaned_pre_submission_tasks(stale_minutes=20)
            if recovered_pre_submission > 0:
                logging.getLogger(__name__).warning(
                    "[Scheduler] Recovered %s orphaned pre-submission task(s)",
                    recovered_pre_submission,
                )

            # [Claude_Sonnet_4.6_Thinking_planning] v3.1.0: 每轮先清理卡在非终态的任务
            # 将卡在 DOWNLOADING/PROCESSING 超过 2 小时的死锁任务重置回 PENDING
            # 这解决了历史任务卡死后永久占用队列、幹操新任务调度的问题
            purged = db.purge_stale_tasks(stale_hours=2)
            if purged > 0:
                logging.getLogger(__name__).info(
                    f"[Scheduler] Purged {purged} stale task(s) back to PENDING"
                )

            # [Claude_Opus_4.8] 美股盘中保护：盘中不启动重型队列管线（下载/Whisper/渲染），
            # 避免抢占与实盘交易行情管线共用的整机 CPU。盘后（北京 04:15 起）自动恢复。
            if _in_us_market_window():
                time.sleep(15)
                continue

            # 队列执行者只负责窗口内提交；非窗口由受管 cron 的后台预加工入口
            # 拉取字幕并完成重活，避免仪表盘每 15 秒反复启动完整管线进程。
            if not settings.is_public_publish_window():
                time.sleep(15)
                continue

            # 1. 普通频道 >=75；演讲/TED/高校频道 >= speech_publish_score_line
            pending_videos = db.get_high_score_pending_videos(
                min_score=75,
                limit=1,
                channel_min_scores=settings.auto_publish_channel_min_scores,
            )
            if pending_videos:
                # 同时检查本进程线程和跨进程 pipeline.lock；cron 的受管巡航不在
                # 仪表盘线程枚举中，遗漏锁检查会额外拉起一个等待锁的重复管线。
                if _queue_pipeline_launch_allowed():
                    print(f"[Scheduler] Found pending high-score video {pending_videos[0]['youtube_id']}, auto-triggering queue pipeline...")
                    threading.Thread(target=_run_pipeline_manager, daemon=True, name="queue-pipeline").start()
        except Exception as e:
            logging.getLogger(__name__).error(f"[Scheduler] Queue runner loop error: {e}")
        time.sleep(15)


def _queue_pipeline_launch_allowed() -> bool:
    """仅在本进程及其它进程均没有流水线持锁时允许队列启动新任务。"""
    active_threads = threading.enumerate()
    has_local_pipeline = any(
        thread.name in ("full-pipeline", "queue-pipeline") or thread.name.startswith("pipeline-")
        for thread in active_threads
    )
    return not has_local_pipeline and not _is_pipeline_manager_running()


def _process_group_alive(pid: Optional[int]) -> bool:
    """保守判断进程组是否仍活着。

    优先使用 ps 实证，而不是单纯依赖 killpg(pid, 0)，避免 macOS 上僵尸/权限细节造成误判。
    """
    if not pid:
        return False
    try:
        result = subprocess.run(
            ["ps", "-axo", "pgid=,stat=,command="],
            cwd=str(Path(__file__).parent.parent.parent),
            capture_output=True,
            text=True,
            timeout=3,
        )
    except Exception:
        return True

    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 2:
            continue
        try:
            pgid = int(parts[0])
        except ValueError:
            continue
        stat = parts[1]
        if pgid == int(pid) and "Z" not in stat:
            return True
    return False


def _recover_orphaned_publishing_tasks(stale_minutes: int = 30) -> int:
    """将已死发布进程转为未绑定提交，保留平台结果未知的 fail-closed 边界。"""
    recovered = 0
    candidates = db.get_stale_publishing_videos(stale_minutes=stale_minutes)
    for video in candidates:
        pid = video.get("process_pid")
        if _process_group_alive(pid):
            continue

        yid = video.get("youtube_id")
        slice_index = int(video.get("slice_index") or 0)
        reason = (
            "发布进程已结束，但数据库仍停留在 PUBLISHING；平台可能已受理。"
            "已停止自动重传，等待视频号后台按平台记录核验。"
        )
        try:
            db.record_wechat_publication_confirmation(
                yid, evidence_path=None, state="SUBMITTED_UNBOUND",
                error_message=reason, slice_index=slice_index,
            )
            db.record_wechat_submission_attempt(
                yid, evidence_path=None, final_title=video.get("title"), slice_index=slice_index,
            )
            db.cancel_queued_downstream_publications_for_unconfirmed_wechat(
                yid, reason=reason, slice_index=slice_index,
            )
        except Exception:
            logger.exception("[Scheduler] 无法为孤儿发布任务写入未确认账本：%s", yid)
            # 不写 FAILED/PENDING；下一轮仍会尝试补写账本，期间不会放行重传。
            db.update_process_pid(yid, None, slice_index=slice_index)
            continue
        db.update_video_status(yid, "SUBMITTED_UNBOUND", error_msg=reason, slice_index=slice_index)
        db.update_process_pid(yid, None, slice_index=slice_index)
        recovered += 1
    return recovered


def _recover_orphaned_pre_submission_tasks(stale_minutes: int = 20) -> int:
    """回收无存活进程的预提交孤儿任务；视频号发布阶段绝不走此路径。"""
    recovered = 0
    for video in db.get_stale_pre_submission_processing_videos(stale_minutes=stale_minutes):
        pid = video.get("process_pid")
        if _process_group_alive(pid):
            continue

        yid = str(video.get("youtube_id") or "")
        slice_index = int(video.get("slice_index") or 0)
        stage = str(video.get("status") or "预提交加工")
        next_status = db.recover_orphaned_pre_submission_task(
            yid,
            expected_process_pid=pid,
            error_msg=f"{stage} 子进程已不存在；自动有界回收，尚未触发视频号提交。",
            slice_index=slice_index,
        )
        if not next_status:
            continue
        recovered += 1
        logging.getLogger(__name__).warning(
            "[Scheduler] %s#%s orphaned %s -> %s", yid, slice_index, stage, next_status,
        )
    return recovered


def _wechat_keepalive_loop():
    """[Claude_Sonnet_4.6_Thinking_planning] v3.2.0: WeChat Session 看门狗循环。

    每隔随机的 min~max 分钟（可通过 settings 配置），启动一个独立子进程
    （wechat_keepalive.py）无感访问微信视频号发布页，停留指定秒数后保存刷新的 Cookie。

    互斥保护：若检测到微信上传任务正在运行，则跳过本轮，避免两个
    Playwright 进程共享 Session 文件产生竞态。
    """
    import random
    import logging
    log = logging.getLogger(__name__)

    prj_root = Path(__file__).parent.parent.parent
    python = str(prj_root / ".venv" / "bin" / "python")
    state_file = str(prj_root / "output" / "wechat_state.json")
    keepalive_script = str(prj_root / "scripts" / "wechat_keepalive.py")

    import subprocess as _sp
    import threading as _threading

    while True:
        # 随机等待 min~max 分钟
        min_s = settings.wechat_keepalive_min_interval * 60
        max_s = settings.wechat_keepalive_max_interval * 60
        interval = random.randint(min_s, max_s)
        log.info(f"[Keepalive] Next keepalive scheduled in {interval // 60}m{interval % 60}s.")
        time.sleep(interval)

        # 开关检查（sleep 后判断，支持运行时热更新配置）
        if not settings.wechat_keepalive_enabled:
            log.debug("[Keepalive] Keepalive disabled by settings, skipping.")
            continue

        # 互斥检测：若有微信上传相关线程正在运行，跳过本轮 keepalive
        # [Claude_Sonnet_4.6_Thinking_planning] 防止两个 Playwright 进程并发读写
        # wechat_state.json 产生 Cookie 竞态（两个进程同时 storage_state() 相互覆盖）
        active_threads = _threading.enumerate()
        upload_running = any(
            "wechat-uploader" in t.name or "upload" in t.name.lower()
            for t in active_threads
        )
        if upload_running:
            log.info("[Keepalive] Upload in progress, skipping keepalive this round.")
            continue

        # 微信服务端会话存在约 24 小时绝对寿命；在临期窗口提前推送二维码，
        # 保留旧 state 直到扫码成功，避免发布时才被动发现 LOGIN_REQUIRED。
        # 必须在上传互斥之后执行，避免登录成功写回 state 与上传并发。
        if _wechat_session_needs_auto_relogin():
            started = _start_wechat_login_flow(
                headless=True,
                preserve_marker=True,
                reason="automatic pre-expiry relogin",
            )
            log.warning(f"[Keepalive] Automatic pre-expiry relogin triggered: {started}")
            continue

        log.info("[Keepalive] Triggering WeChat session keepalive...")

        # 构建子进程环境：不注入代理（与 wechat_uploader 一致），注入 Telegram 凭据
        _proxy_keys = frozenset({
            'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY',
            'http_proxy', 'https_proxy', 'all_proxy'
        })
        env = {k: v for k, v in os.environ.items() if k not in _proxy_keys}
        if settings.telegram_bot_token:
            env["TELEGRAM_BOT_TOKEN"] = settings.telegram_bot_token
        if settings.active_telegram_chat_id:
            env["TELEGRAM_CHAT_ID"] = settings.active_telegram_chat_id
        if settings.telegram_admin_ids:
            env["TELEGRAM_ADMIN_IDS"] = settings.telegram_admin_ids

        try:
            result = _sp.run(
                [
                    python, keepalive_script,
                    "--state", state_file,
                    "--dwell", str(settings.wechat_keepalive_dwell),
                ],
                env=env,
                timeout=120,  # 子进程最大 120 秒超时保护
            )
            if result.returncode == 0:
                log.info("[Keepalive] WeChat session refreshed successfully.")
            elif result.returncode == 2:
                log.warning("[Keepalive] WeChat session expired (LOGIN_REQUIRED). Telegram alert sent.")
            else:
                log.warning(f"[Keepalive] Keepalive subprocess returned code: {result.returncode}.")
        except _sp.TimeoutExpired:
            log.error("[Keepalive] Keepalive subprocess timed out after 120s.")
        except FileNotFoundError:
            log.error(f"[Keepalive] Keepalive script not found: {keepalive_script}")
        except Exception as e:
            log.error(f"[Keepalive] Unexpected error: {e}")


@app.on_event("startup")
def startup_event():
    """FastAPI 启动时自动运行后台调度器，并在主线程注册信号处理器。

    [Claude_Sonnet_4.6_Thinking_planning] BUG-1 修复：signal.signal() 只能在主线程调用。
    _process_single_video经由 daemon 线程执行，无法在内部注册信号。
    将 SIGTERM handler 注册移至此处（FastAPI startup 在主线程运行）。
    """
    # [Claude_Sonnet_4.6_Thinking_planning] BUG-1: 在主线程注册 SIGTERM handler
    if settings.enable_sigterm_kill:
        from video_processing import pipeline_manager as _pm
        signal.signal(signal.SIGTERM, _pm._sigterm_handler)

    import threading
    threading.Thread(target=_auto_pipeline_loop, daemon=True, name="auto-pipeline-scheduler").start()
    print("[Scheduler] Background pipeline scheduler started.")

    threading.Thread(target=_queue_runner_loop, daemon=True, name="queue-runner-scheduler").start()
    print("[Scheduler] Queue runner scheduler started.")

    # [Claude_Sonnet_4.6_Thinking_planning] v3.2.0: WeChat Session 看门狗
    threading.Thread(target=_wechat_keepalive_loop, daemon=True, name="wechat-keepalive-watchdog").start()
    print("[Scheduler] WeChat session keepalive watchdog started.")

# 优先用 PATH 里的 yt-dlp，其次用 venv 里的
_YT_DLP = shutil.which("yt-dlp") or str(
    Path(__file__).parent.parent.parent / ".venv" / "bin" / "yt-dlp"
)

# [Claude_Sonnet_4.6_Thinking_planning] SEC-1 修复：严格 YouTube 域名白名单。
# 旧方案 `any(d in url ...)` 可被路径、子域名、data URI 等 5 种向量绕过。
# urlparse().netloc 精准提取 host，不受路径/查询串/协议影响。
_ALLOWED_YOUTUBE_HOSTS: frozenset = frozenset({
    "www.youtube.com",
    "youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
})


def _is_youtube_url(url: str) -> bool:
    """严格校验 URL 是否属于 YouTube 官方域名（netloc 级别匹配）。

    防御向量：
    - https://evil.com/youtube.com       → netloc=evil.com → BLOCKED
    - https://youtube.com.evil.com/      → netloc=youtube.com.evil.com → BLOCKED
    - data:text/html,youtube.com         → netloc='' → BLOCKED
    - https://www.youtube.com/watch?v=x  → netloc=www.youtube.com → ALLOWED
    """
    try:
        host = urlparse(url).netloc.lower().split(":")[0]  # 去端口号
        return host in _ALLOWED_YOUTUBE_HOSTS
    except Exception:
        return False


# 实际占用管线执行资源的状态；平台已受理待确认不属于加工中。
PROCESSING_STATUSES = {"DOWNLOADING", "TRANSCRIBING", "COPYWRITING", "PUBLISHING"}

# 保留既有安全保护：UNDER_REVIEW 不可被删除/停止接口当作普通终态处理，
# 以免为修正展示语义而误删已提交的平台作品证据。
ACTIVE_STATUSES = PROCESSING_STATUSES | {"UNDER_REVIEW"}

# 视频号平台状态是不可逆外部事实：任何本地平台生命周期状态或账本均不能被
# 通用重试/重置接口回写为 PENDING。只有专用、人工确认的发布流程可另行处理。
_WECHAT_SUBMISSION_GUARD_STATUSES = frozenset({
    "PUBLISHING", "UNDER_REVIEW", "SUBMITTED_UNBOUND", "SUBMITTED_BOUND", "UNCERTAIN",
    "PUBLISHED", "REJECTED", "NOT_FOUND", "HISTORICAL_UNRESOLVED",
})


def _wechat_submission_guard_reason(video: dict) -> Optional[str]:
    """返回阻止通用重试的原因；账本读取失败也按 fail-closed 处理。"""
    status = str(video.get("status") or "").upper()
    if status in _WECHAT_SUBMISSION_GUARD_STATUSES:
        return f"视频号当前为 {status}，提交结果未获公开发布证明，禁止通用重试或重置。"
    try:
        publication = db.get_wechat_publication(
            str(video["youtube_id"]), slice_index=int(video.get("slice_index") or 0),
        )
    except Exception as exc:
        logger.error("读取视频号确认账本失败，拒绝重置 %s: %s", video.get("youtube_id"), exc)
        return "无法读取视频号确认账本；为防止重复提交，拒绝重试或重置。"
    if publication:
        return f"视频号存在 {publication.get('state') or 'UNKNOWN'} 平台账本，禁止通用重试或重置。"
    return None

# FSM 状态的显示顺序
STATUS_ORDER = [
    "PENDING", "DOWNLOADING", "TRANSCRIBING", "COPYWRITING", "PUBLISHING",
    "SUBMITTED_UNBOUND", "SUBMITTED_BOUND", "UNDER_REVIEW", "UNCERTAIN",
    "PUBLISHED", "FAILED", "LOGIN_REQUIRED",
]


# ── Pydantic 请求体 ──────────────────────────────────────────────────────
class AddChannelRequest(BaseModel):
    url: str
    promote: Optional[bool] = False


class BatchDeleteRequest(BaseModel):  # [Gemini_2.5_Pro_planning]
    youtube_ids: list[str]
    delete_files: bool = False


class PlatformBackfillQueueRequest(BaseModel):
    platform: str
    since_upload_date: Optional[str] = None
    wall_street_days: int = 10
    daily_limit: int = 5
    youtube_ids: Optional[list[str]] = None


class DouyinPublicationRequeueRequest(BaseModel):
    publication_id: int


_OUT_DIR = Path(__file__).parent.parent.parent / "output"


def _invalidate_audio_variant_artifacts(youtube_id: str) -> list[str]:
    """删除音轨规格切换后必然失真的派生产物，保留下载源和文案检查点。"""
    deleted: list[str] = []
    for suffix in ("_vertical.mp4", ".ass", "_cover.jpg", "_cover_brief.json", "_cover_provenance.json"):
        path = _OUT_DIR / f"{youtube_id}{suffix}"
        if not path.is_file():
            continue
        try:
            path.unlink()
            deleted.append(path.name)
        except OSError as exc:
            logging.getLogger(__name__).warning("音轨规格变更时无法清理 %s: %s", path.name, exc)
    return deleted


def _default_backfill_since_upload_date(days: int = 10) -> str:
    return (datetime.now().date() - timedelta(days=max(0, int(days)))).strftime("%Y%m%d")


def _normalize_backfill_since(since_upload_date: Optional[str], wall_street_days: int) -> str:
    since = (since_upload_date or "").strip() or _default_backfill_since_upload_date(wall_street_days)
    if not re.match(r"^\d{8}$", since):
        raise HTTPException(status_code=400, detail="since_upload_date must be YYYYMMDD")
    return since


def _backfill_asset_paths(youtube_id: str, slice_index: int) -> dict[str, Path]:
    prefix = f"{youtube_id}_s{slice_index}" if slice_index > 0 else youtube_id
    return {
        "video": _OUT_DIR / f"{prefix}_vertical.mp4",
        "copy": _OUT_DIR / f"{prefix}_copy.txt",
        "title": _OUT_DIR / f"{prefix}_title.txt",
    }


def _read_publish_text(path: Path, *, max_chars: int = 800) -> Optional[str]:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    except Exception as exc:
        logging.getLogger(__name__).warning("[Dashboard] Failed to read publish artifact %s: %s", path, exc)
        return None
    if not text:
        return None
    if len(text) > max_chars:
        return text[:max_chars].rstrip() + "..."
    return text


def _attach_publish_display_fields(rows: list[dict]) -> list[dict]:
    """为仪表盘行补齐真实投递标题，保证后台列表与平台发布标题一致。"""
    for row in rows:
        yid = row.get("youtube_id")
        if not yid:
            continue
        slice_index = int(row.get("slice_index") or 0)
        paths = _backfill_asset_paths(yid, slice_index)
        published_title = _read_publish_text(paths["title"], max_chars=120)
        published_copy_preview = _read_publish_text(paths["copy"], max_chars=280)
        source_zh_title = (row.get("zh_title") or "").strip()

        row["published_title"] = published_title
        row["published_copy_preview"] = published_copy_preview
        row["display_title"] = (
            published_title
            or source_zh_title
            or (row.get("title") or "").strip()
            or yid
        )
        row["title_mismatch"] = bool(
            published_title
            and source_zh_title
            and published_title != source_zh_title
        )
    return rows


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _backfill_row_payload(row: dict) -> dict:
    yid = row.get("youtube_id")
    slice_index = int(row.get("slice_index") or 0)
    paths = _backfill_asset_paths(yid, slice_index)
    return {
        **row,
        "slice_index": slice_index,
        "rules": [
            label for flag, label in (
                (row.get("is_speech_or_interview"), "访谈/演讲"),
                (row.get("is_recent_wall_street"), "Wall Street Truthbombs 最近窗口"),
            )
            if int(flag or 0)
        ],
        "assets": {name: path.is_file() for name, path in paths.items()},
    }


def _build_backfill_preview_payload(
    *,
    since_upload_date: str,
    wechat_daily_limit: int,
    wechat_max_daily_limit: int,
    douyin_daily_limit: int,
    limit: int,
) -> dict:
    platform_limits = {
        "wechat": {"label": "微信", "daily_limit": max(1, min(int(wechat_daily_limit), 50))},
        "douyin": {"label": "抖音", "daily_limit": max(1, min(int(douyin_daily_limit), 50))},
    }
    payload = {
        "success": True,
        "since_upload_date": since_upload_date,
        "wechat_max_daily_limit": max(1, min(int(wechat_max_daily_limit), 50)),
        "platforms": {},
    }
    for platform, meta in platform_limits.items():
        rows = [
            _backfill_row_payload(row)
            for row in db.get_platform_backfill_preview_candidates(
                platform,
                wall_street_since_upload_date=since_upload_date,
                limit=max(1, min(int(limit), 5000)),
            )
        ]
        daily_limit = meta["daily_limit"]
        batches = [rows[index:index + daily_limit] for index in range(0, len(rows), daily_limit)]
        payload["platforms"][platform] = {
            "label": meta["label"],
            "daily_limit": daily_limit,
            "candidate_count": len(rows),
            "queueable_count": sum(1 for row in rows if row["assets"]["video"]),
            "estimated_days": len(batches),
            "batches": [
                {"day": index + 1, "items": batch}
                for index, batch in enumerate(batches[:3])
            ],
        }
    return payload


# ── 页面路由 ─────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def dashboard():
    """返回仪表盘 HTML 页面"""
    template_path = Path(__file__).parent / "templates" / "index.html"
    return HTMLResponse(content=template_path.read_text(encoding="utf-8"))


@app.get("/api/ai-audit/summary")
def get_ai_audit_summary(hours: int = 168):
    """AI 字幕调用概览：近期开销、失败与降级统计。"""
    return db.get_ai_audit_summary(hours=hours)


@app.get("/api/ai-audit/videos/{youtube_id}")
def get_ai_audit_video(youtube_id: str, slice_index: int = 0, limit: int = 20):
    """指定视频的 AI 处理运行与 provider 尝试时间线。"""
    if not re.match(r'^[A-Za-z0-9_\-]+$', youtube_id):
        raise HTTPException(status_code=400, detail="Invalid youtube_id")
    return {
        "youtube_id": youtube_id,
        "slice_index": slice_index,
        "runs": db.get_ai_audit_for_video(youtube_id, slice_index=slice_index, limit=limit),
    }


# ── 封面图片 API ─────────────────────────────────────────────────────────
@app.get("/api/covers/{youtube_id}")
def get_cover(youtube_id: str):
    """[Gemini_2.5_Pro_planning] 返回指定视频 ID 的封面图片（JPEG）。
    若封面文件不存在则返回 404，前端可据此显示占位符。
    """
    # 安全校验：youtube_id 只允许字母/数字/连字符/下划线
    if not re.match(r'^[A-Za-z0-9_\-]+$', youtube_id):
        raise HTTPException(status_code=400, detail="Invalid youtube_id")
    cover_path = _OUT_DIR / f"{youtube_id}_cover.jpg"
    if not cover_path.exists():
        raise HTTPException(status_code=404, detail="Cover not found")
    return FileResponse(
        str(cover_path),
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=3600"},
    )


# ── 统计 API ─────────────────────────────────────────────────────────────
@app.get("/api/stats")
def get_stats():
    """返回各状态视频数量，用于顶部统计卡片"""
    counts = db.get_status_counts()
    total = sum(counts.values())
    active = sum(v for k, v in counts.items() if k in PROCESSING_STATUSES)
    detailed = db.get_detailed_stats()
    return {
        "total": total,
        "pending": counts.get("PENDING", 0),
        "active": active,
        "published": counts.get("PUBLISHED", 0),
        "failed": counts.get("FAILED", 0) + counts.get("LOGIN_REQUIRED", 0),
        "breakdown": {s: counts.get(s, 0) for s in STATUS_ORDER},
        "detailed": detailed,
        "server_time": datetime.now().strftime("%H:%M:%S"),
    }


@app.get("/api/platform-backfill/preview")
def platform_backfill_preview(
    since_upload_date: Optional[str] = None,
    wall_street_days: int = 10,
    wechat_daily_limit: int = 5,
    wechat_max_daily_limit: int = 8,
    douyin_daily_limit: int = 20,
    limit: int = 500,
):
    """只读预览微信/抖音补录候选和日批次，不创建任何发布任务。"""
    since = _normalize_backfill_since(since_upload_date, wall_street_days)
    return _build_backfill_preview_payload(
        since_upload_date=since,
        wechat_daily_limit=wechat_daily_limit,
        wechat_max_daily_limit=wechat_max_daily_limit,
        douyin_daily_limit=douyin_daily_limit,
        limit=limit,
    )


@app.post("/api/platform-backfill/queue")
def queue_platform_backfill(req: PlatformBackfillQueueRequest):
    """确认补录入队。

    微信：WECHAT_DEFERRED 本身就是恢复队列，确认接口只返回首批清单。
    抖音：把首批候选写入 douyin_publications(HISTORY)，等待每日迁移任务按限额发布。
    """
    platform = (req.platform or "").lower()
    if platform not in {"wechat", "douyin"}:
        return {"success": False, "error": "platform 仅支持 wechat / douyin"}
    since = _normalize_backfill_since(req.since_upload_date, req.wall_street_days)
    daily_limit = max(1, min(int(req.daily_limit), 50))
    requested_ids = set(req.youtube_ids or [])
    rows = db.get_platform_backfill_preview_candidates(
        platform,
        wall_street_since_upload_date=since,
        limit=5000,
    )
    if requested_ids:
        rows = [row for row in rows if row.get("youtube_id") in requested_ids]
    rows = rows[:daily_limit]

    queued = []
    skipped = []
    if platform == "wechat":
        for row in rows:
            payload = _backfill_row_payload(row)
            queued.append({
                "youtube_id": payload["youtube_id"],
                "slice_index": payload["slice_index"],
                "state": payload["wechat_status"],
                "message": "已在微信恢复队列，等待每日任务按限额补发",
            })
        return {
            "success": True,
            "platform": platform,
            "since_upload_date": since,
            "queued_count": len(queued),
            "skipped_count": 0,
            "queued": queued,
            "skipped": skipped,
        }

    for row in rows:
        yid = row.get("youtube_id")
        slice_index = int(row.get("slice_index") or 0)
        paths = _backfill_asset_paths(yid, slice_index)
        missing = [name for name, path in paths.items() if not path.is_file()]
        if missing:
            skipped.append({
                "youtube_id": yid,
                "slice_index": slice_index,
                "reason": "缺少抖音投递产物：" + ",".join(missing),
            })
            continue
        publication = db.create_douyin_publication(
            yid,
            _sha256_file(paths["video"]),
            str(paths["video"]),
            source_kind="HISTORY",
            slice_index=slice_index,
        )
        queued.append({
            "youtube_id": yid,
            "slice_index": slice_index,
            "publication_id": publication.get("id"),
            "state": publication.get("state"),
            "attempt_number": publication.get("attempt_number"),
        })
    return {
        "success": True,
        "platform": platform,
        "since_upload_date": since,
        "queued_count": len(queued),
        "skipped_count": len(skipped),
        "queued": queued,
        "skipped": skipped,
    }


@app.post("/api/douyin/publications/requeue")
def requeue_canceled_douyin_publication(req: DouyinPublicationRequeueRequest):
    """人工确认抖音页面与投递产物已修复后，创建一条新的可审计队列记录。"""
    publication = db.get_douyin_publication_by_id(req.publication_id)
    if not publication:
        return {"success": False, "error": "抖音投递记录不存在"}
    if publication.get("state") != "CANCELED":
        return {"success": False, "error": "仅 CANCELED 的抖音记录允许人工重新入队"}
    video_path = Path(str(publication.get("video_path") or ""))
    if not video_path.is_file():
        return {"success": False, "error": "成片不存在，不能重新入队"}
    try:
        requeued = db.requeue_canceled_douyin_publication(req.publication_id)
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    return {
        "success": True,
        "publication_id": requeued["id"],
        "attempt_number": requeued["attempt_number"],
        "state": requeued["state"],
    }


@app.get("/api/videos")
def get_videos(tab: str = "waitlist", page: int = 1, size: int = 20):
    """返回分页和分类后的视频列表，以及各个 Tab 的计数"""
    page = max(1, page)
    size = max(1, min(100, size))
    videos, total_count = db.get_paginated_videos(tab, page, size)
    _attach_publish_display_fields(videos)
    tab_counts = db.get_tab_counts()
    return {
        "videos": videos,
        "total_count": total_count,
        "page": page,
        "size": size,
        "total_pages": (total_count + size - 1) // size,
        "tab_counts": tab_counts
    }


@app.get("/api/videos/{youtube_id}/slices")
def get_slices(youtube_id: str):
    """[Gemini_3.5_Flash_High_planning] 获取指定 YouTube ID 的所有切片子任务"""
    slices = db.get_slices_by_parent_yid(youtube_id)
    _attach_publish_display_fields(slices)
    return {"slices": slices}


# ── Highlight Job（显式候选与人工选定；不接既有管线或发布）────────────────────
class CreateHighlightJobRequest(BaseModel):
    source_youtube_id: str
    max_clips: int = 3
    min_duration_sec: float = 35
    max_duration_sec: float = 90
    requested_by: str = "manual"


def _highlight_job_payload(job: dict) -> dict:
    """对外仅暴露 Highlight 自身状态与只读源标识，避免伪装成原视频任务。"""
    payload = dict(job)
    payload["clips"] = db.get_highlight_clips(str(job["id"]))
    return payload


@app.get("/api/highlights/sources")
def list_highlight_sources(limit: int = 10, offset: int = 0):
    """列出最近源视频及本地字幕可用性；接口本身绝不创建任务。"""
    service = HighlightJobService(db, Path(__file__).parent.parent.parent)
    return {"sources": service.list_sources(limit=limit, offset=offset)}


@app.post("/api/highlights/jobs")
def create_highlight_job(req: CreateHighlightJobRequest):
    """显式创建一个独立 Highlight Job，并只启动本地候选分析。"""
    source_youtube_id = (req.source_youtube_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,64}", source_youtube_id):
        return {"success": False, "error": "source_youtube_id 格式不合法"}
    service = HighlightJobService(db, Path(__file__).parent.parent.parent)
    if not service.has_source_subtitle(source_youtube_id):
        return {
            "success": False,
            "error": "该视频没有可用的带时间轴源字幕，暂不能生成 Highlight 候选",
        }
    try:
        job, created = db.create_highlight_job(
            source_youtube_id,
            max_clips=req.max_clips,
            min_duration_sec=req.min_duration_sec,
            max_duration_sec=req.max_duration_sec,
            requested_by=req.requested_by,
        )
    except (TypeError, ValueError) as exc:
        return {"success": False, "error": str(exc)}
    _start_highlight_analysis(str(job["id"]))
    return {
        "success": True,
        "created": created,
        "message": "已开始生成金句候选；不会下载、渲染或发布任何视频。" if created
                   else "该源视频已有进行中的 Highlight Job；已返回现有任务。",
        "job": _highlight_job_payload(job),
    }


@app.post("/api/highlights/clips/{clip_id}/select")
def select_highlight_clip(clip_id: str):
    """显式选定一个 Highlight 候选并创建独立发布主体；不渲染、不上传、不发布。"""
    if not re.fullmatch(r"[a-f0-9]{32}", clip_id or ""):
        return {"success": False, "error": "Highlight Clip ID 格式不合法"}
    try:
        clip = db.select_highlight_clip_for_publication(clip_id)
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    return {
        "success": True,
        "message": "已选定候选并创建独立发布主体；尚未渲染、上传或发布。",
        "clip": clip,
    }


@app.get("/api/highlights/jobs")
def list_highlight_jobs(limit: int = 20):
    """读取 Highlight Job 列表；不触发任何分析、渲染或发布。"""
    return {"jobs": [_highlight_job_payload(job) for job in db.list_highlight_jobs(limit=limit)]}


@app.get("/api/highlights/jobs/{job_id}")
def get_highlight_job(job_id: str):
    """读取一个独立 Highlight Job 及其候选，不修改其状态。"""
    if not re.fullmatch(r"[a-f0-9]{32}", job_id or ""):
        raise HTTPException(status_code=404, detail="Highlight Job 不存在")
    job = db.get_highlight_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Highlight Job 不存在")
    return _highlight_job_payload(job)


# ── English World research（独立选题/制作请求；不接通用队列或发布）────────────
class CreateEnglishWorldResearchRequest(BaseModel):
    requested_by: str = "manual"
    notification_target: Optional[str] = None
    source_url: Optional[str] = None


def _english_world_job_payload(job: dict) -> dict:
    """只暴露英语世界自己的候选和状态，避免被误读为普通视频或平台发布任务。"""
    payload = dict(job)
    payload["candidates"] = db.get_english_world_candidates(str(job["id"]))
    return payload


@app.post("/api/english-world/research")
def create_english_world_research(req: CreateEnglishWorldResearchRequest):
    """创建只读候选研究任务并异步启动；不会下载、制作、入队或发布。"""
    source_url = (req.source_url or "").strip() or None
    if source_url and not _is_youtube_url(source_url):
        return {"success": False, "error": "指定来源必须是 youtube.com 或 youtu.be 视频 URL"}
    try:
        job = db.create_english_world_research_job(
            requested_by=req.requested_by,
            notification_target=req.notification_target,
            source_url=source_url,
        )
    except (TypeError, ValueError) as exc:
        return {"success": False, "error": str(exc)}
    _start_english_world_research(str(job["id"]))
    return {
        "success": True,
        "message": "已开始英语世界候选研究；不会下载、制作或发布。",
        "job": _english_world_job_payload(job),
    }


@app.get("/api/english-world/jobs")
def list_english_world_jobs(limit: int = 20):
    """读取英语世界独立任务账本；不触发网络研究、制作或平台提交。"""
    return {"jobs": [_english_world_job_payload(job) for job in db.list_english_world_jobs(limit=limit)]}


@app.get("/api/english-world/jobs/{job_id}")
def get_english_world_job(job_id: str):
    """读取单个英语世界任务及候选；只读。"""
    if not re.fullmatch(r"[a-f0-9]{32}", job_id or ""):
        raise HTTPException(status_code=404, detail="英语世界任务不存在")
    job = db.get_english_world_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="英语世界任务不存在")
    return _english_world_job_payload(job)


@app.post("/api/english-world/candidates/{candidate_id}/select")
def select_english_world_candidate(candidate_id: str):
    """选定研究候选；只进入二次制作确认，不下载、渲染或发布。"""
    if not re.fullmatch(r"[a-f0-9]{32}", candidate_id or ""):
        return {"success": False, "error": "英语世界候选 ID 格式不合法"}
    try:
        candidate = db.select_english_world_candidate(candidate_id)
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    job = db.get_english_world_job(str(candidate["job_id"]))
    return {
        "success": True,
        "message": "候选已选定；需要再次确认后才会登记生产请求。",
        "candidate": candidate,
        "job": _english_world_job_payload(job) if job else None,
    }


@app.post("/api/english-world/jobs/{job_id}/request-production")
def request_english_world_production(job_id: str):
    """登记第二次制作确认；不伪装为自动渲染完成，更不触发平台发布。"""
    if not re.fullmatch(r"[a-f0-9]{32}", job_id or ""):
        return {"success": False, "error": "英语世界任务 ID 格式不合法"}
    try:
        job = db.request_english_world_production(job_id)
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    return {
        "success": True,
        "message": "已登记生产请求；当前等待英语学习卡生产协调器接手，尚未下载、渲染或发布。",
        "job": _english_world_job_payload(job),
    }


@app.post("/api/english-world/review-items/{review_id}/approve-submission")
def approve_english_world_submission(review_id: str):
    """接收 Telegram 对一条审核成片的唯一投稿授权，并启动独立投稿 worker。"""
    if not re.fullmatch(r"[a-f0-9]{32}", review_id or ""):
        return {"success": False, "error": "英语世界审核编号格式不合法"}
    if settings.wechat_publishing_paused:
        return {"success": False, "error": "视频号投稿当前已暂停；未记录批准，也未启动上传。"}
    item = db.get_english_world_review_item(review_id)
    if not item:
        return {"success": False, "error": "英语世界审核项不存在"}
    state = str(item.get("state") or "")
    try:
        if state == "READY_FOR_REVIEW":
            item = db.approve_english_world_submission(review_id)
            _start_english_world_submission(review_id)
        elif state == "SUBMISSION_APPROVED":
            # API 进程可能刚好在首次批准后重启；再次点击只允许唤起同一审核项，领取仍原子防重。
            _start_english_world_submission(review_id)
            item = db.get_english_world_review_item(review_id) or item
        elif state in {"SUBMITTING", "UNDER_REVIEW", "UNCERTAIN", "LOGIN_REQUIRED", "FAILED", "HELD"}:
            return {
                "success": True,
                "message": f"该审核项当前为 {state}；未创建新的投稿尝试。",
                "item": item,
            }
        else:
            return {"success": False, "error": f"审核项状态异常：{state}"}
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    return {
        "success": True,
        "message": "已记录本条审核项的投稿批准，正在发起视频号提交；后续以平台回执为准。",
        "item": item,
    }


@app.get("/api/english-world/review-items")
def list_english_world_review_items(limit: int = 20):
    """只读返回英语世界学习卡的审核/投稿状态，不启动任何操作。"""
    return {"items": db.list_english_world_review_items(limit=limit)}


@app.post("/api/english-world/recover-login-required")
def recover_english_world_login_required_submission():
    """在已确认登录恢复后，领取唯一合格的登录前失败英语世界自动任务。"""
    if not _wechat_login_marker_active(Path(__file__).parent.parent.parent / "output" / "wechat_login_at.txt"):
        return {"success": False, "error": "视频号登录尚未确认恢复；未创建投稿尝试"}
    item = _resume_eligible_english_world_after_wechat_login()
    if item is None:
        return {"success": True, "message": "没有可安全自动续投的英语世界登录失败项。"}
    return {
        "success": True,
        "message": "已领取一条登录前失败项并启动一次自动续投；后续以平台回执为准。",
        "item": item,
    }


@app.post("/api/english-world/review-items/{review_id}/confirm-not-published-retry")
def reopen_uncertain_english_world_submission(review_id: str):
    """仅在 Telegram 二次确认后重开同一英语世界审核项，绝不走通用视频重试。"""
    if not re.fullmatch(r"[a-f0-9]{32}", review_id or ""):
        return {"success": False, "error": "英语世界审核编号格式不合法"}
    try:
        item = db.reopen_uncertain_english_world_submission(review_id)
        _start_english_world_submission(review_id)
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    return {"success": True, "message": "已重开同一审核项的一次人工确认重传。", "item": item}


@app.post("/api/english-world/review-items/{review_id}/hold")
def hold_english_world_review_item(review_id: str):
    """显式搁置某条待审核学习卡；不触发制作或投稿。"""
    if not re.fullmatch(r"[a-f0-9]{32}", review_id or ""):
        return {"success": False, "error": "英语世界审核编号格式不合法"}
    try:
        item = db.hold_english_world_review_item(review_id)
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    return {"success": True, "message": "已搁置本条审核项，未提交视频号。", "item": item}


# ── 频道管理 API ──────────────────────────────────────────────────────────
@app.get("/api/channels")
def get_channels():
    """返回频道白名单"""
    approved = db.get_approved_channels()
    pending = db.get_pending_channels()
    return {
        "approved": approved,
        "pending": pending,
        "total_approved": len(approved),
    }


@app.post("/api/channels/add")
def add_channel(req: AddChannelRequest):
    """
    通过 yt-dlp 严格验证 YouTube 频道 URL，验证通过后写入白名单。

    验证链：
      1. URL 格式必须是 YouTube 域名
      2. yt-dlp --flat-playlist 获取频道元数据（不触发视频格式检查）
      3. Channel ID 必须符合 YouTube 规范（UC 开头，24字符）
      4. 重复检测：已存在的 APPROVED 频道直接提示，不重复写入
    """
    url = req.url.strip()
    if not url:
        return {"success": False, "error": "URL 不能为空"}

    # ── 1. 前置 URL 格式校验（拒绝非 YouTube 输入）──────────────────────
    # [Claude_Sonnet_4.6_Thinking_planning] SEC-1: 使用 _is_youtube_url() 严格 netloc 匹配
    if not _is_youtube_url(url):
        return {
            "success": False,
            "error": "请输入有效的 YouTube 频道 URL（必须来自 youtube.com 或 youtu.be）"
        }

    # ── 2. 调用 yt-dlp 获取频道元数据 ─────────────────────────────────
    # 关键：使用 --flat-playlist 只获取列表元数据，不触发视频格式解析，
    # 避免 "Requested format is not available" 导致的误报失败
    try:
        result = subprocess.run(
            [
                _YT_DLP,
                "--flat-playlist",          # 不解析视频格式，只取列表元数据
                "--playlist-items", "1",    # 只取第一条，快速返回
                "--print", "%(channel_id)s|%(channel)s",
                "--no-warnings",
                *settings.get_yt_cookie_args(),
                url,
            ],
            capture_output=True, text=True, timeout=30
        )
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "yt-dlp 请求超时（30s），请检查网络"}
    except FileNotFoundError:
        return {"success": False, "error": f"找不到 yt-dlp 可执行文件：{_YT_DLP}"}

    # ── 3. 解析输出（stdout 有内容 = 频道存在，与 returncode 无关）───────
    raw_line = result.stdout.strip().split("\n")[0] if result.stdout.strip() else ""
    if not raw_line or "|" not in raw_line:
        # 真正的频道不存在：stdout 为空
        first_err = result.stderr.strip().split("\n")[0] if result.stderr.strip() else ""
        # 过滤掉格式错误（这类错误不代表频道不存在）
        if "format" in first_err.lower():
            first_err = "频道不存在或无法通过当前 Cookie 访问"
        return {"success": False, "error": first_err or "无法解析频道信息，请检查 URL"}

    channel_id, channel_name = raw_line.split("|", 1)
    channel_id   = channel_id.strip()
    channel_name = channel_name.strip()

    # ── 4. Channel ID 格式校验 ─────────────────────────────────────────
    # YouTube 频道 ID 固定以 "UC" 开头，长度 24 个字符
    if not channel_id.startswith("UC") or len(channel_id) != 24:
        return {
            "success": False,
            "error": f"解析到的频道 ID 格式异常（{channel_id}），请确认这是一个频道页面而非单个视频链接"
        }

    # ── 5. 重复检测 ───────────────────────────────────────────────────
    # [Claude_Sonnet_4.6_Thinking_planning] SEC-2 修复：覆盖所有已存在状态，防止 MANUAL_ONLY → APPROVED 隐式提升。
    # 旧逻辑只检测 APPROVED，MANUAL_ONLY 频道被放行后 INSERT OR REPLACE 会静默覆盖为 APPROVED，
    # 导致用户手动下载某视频后其频道被意外加入爬虫白名单，直接破坏频道隔离设计。
    existing = db.get_channel_by_id(channel_id)
    if existing:
        status = existing.get("status")
        if status == "APPROVED":
            return {
                "success": False,
                "error": f"该频道已在白名单中：{existing['channel_name']}（{channel_id}）",
                "already_exists": True,
            }
        elif status == "MANUAL_ONLY":
            if not req.promote:
                # 该频道曾通过手动视频下载注册，需用户明确确认才能提升为自动爬取白名单
                return {
                    "success": False,
                    "error": (
                        f"频道《{existing['channel_name']}》（{channel_id}）已通过手动视频下载注册（MANUAL_ONLY），"
                        "不会被自动爬取。是否确认将其状态提升为 APPROVED（加入自动监控白名单）？"
                    ),
                    "requires_promotion": True,
                    "channel_id": channel_id,
                    "channel_name": existing['channel_name'],
                }
            # 用户确认了 promote，允许通过
        # 其他状态（PENDING/REJECTED 等）：允许覆盖写入 APPROVED

    # ── 6. 全部通过，写入 ──────────────────────────────────────────────
    db.add_channel(channel_id, channel_name, status="APPROVED", reason="Added via Web UI")
    return {"success": True, "channel_id": channel_id, "channel_name": channel_name}



@app.delete("/api/channels/{channel_id}")
def remove_channel(channel_id: str):
    """从白名单中删除一个频道"""
    ok = db.delete_channel(channel_id)
    return {"success": ok}


# ── 手动添加视频 API ──────────────────────────────────────────────────────
class AddVideoRequest(BaseModel):
    url: str
    trim_start: Optional[str] = None
    trim_end: Optional[str] = None
    disable_slicing: Optional[bool] = True  # [Gemini_3.5_Flash_planning] 默认不分片 (整片模式)
    tts_provider: Optional[str] = None      # [Claude_Sonnet_4.6_Thinking_planning] TTS 配音引擎，nullable
    content_type: str = CONTENT_TYPE_GENERAL


@app.post("/api/videos/add")
def add_video_manual(req: AddVideoRequest, bg_tasks: BackgroundTasks):
    """
    手动将一条 YouTube 视频链接加入处理队列（状态：PENDING）。

    验证链：
      1. URL 必须是 YouTube 域名
      2. 校验裁剪时间参数格式
      3. yt-dlp 获取 video_id / title / channel_id / channel_name / duration / views / likes / upload_date
      4. 重复检测：已存在则返回当前状态，不重复写入
      5. 通过 DAL 写入 processed_videos，评分 100（手工加急），触发异步翻译
    """
    url = req.url.strip()
    if not url:
        return {"success": False, "error": "URL 不能为空"}

    # ── 1. 裁剪时间参数校验与格式清洗 ──────────────────────────────────
    trim_start = req.trim_start.strip() if req.trim_start else None
    trim_end = req.trim_end.strip() if req.trim_end else None
    try:
        content_type = normalize_content_type(req.content_type)
    except ValueError as exc:
        return {"success": False, "error": str(exc)}

    # 正则防注入校验 (只允许数字、冒号、点)
    time_pattern = re.compile(r"^[0-9:.]*$")
    if trim_start and not time_pattern.match(trim_start):
        return {"success": False, "error": "开始时间格式不合法，仅支持数字、冒号和点"}
    if trim_end and not time_pattern.match(trim_end):
        return {"success": False, "error": "结束时间格式不合法，仅支持数字、冒号和点"}

    # ── 2. 前置 URL 格式校验 ─────────────────────────────────────────
    # [Claude_Sonnet_4.6_Thinking_planning] SEC-1: 使用 _is_youtube_url() 严格 netloc 匹配
    if not _is_youtube_url(url):
        return {"success": False, "error": "请输入有效的 YouTube 视频 URL（必须来自 youtube.com 或 youtu.be）"}

    # ── 3. yt-dlp 获取视频元数据 ─────────────────────────────────────
    try:
        result = subprocess.run(
            [
                _YT_DLP,
                "--print", "%(id)s|||%(title)s|||%(channel_id)s|||%(channel)s|||%(duration)s|||%(view_count)s|||%(like_count)s|||%(upload_date)s",
                "--no-playlist",
                "--no-warnings",
                *settings.get_yt_cookie_args(),
                url,
            ],
            capture_output=True, text=True, timeout=30
        )
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "yt-dlp 请求超时（30s），请检查网络"}
    except FileNotFoundError:
        return {"success": False, "error": f"找不到 yt-dlp：{_YT_DLP}"}

    raw = result.stdout.strip().split("\n")[0] if result.stdout.strip() else ""
    if not raw or raw.count("|||") < 3:
        err = result.stderr.strip().split("\n")[0] if result.stderr.strip() else "无法解析视频信息"
        return {"success": False, "error": f"视频不存在或无法访问：{err}"}

    parts = raw.split("|||", 7)
    video_id    = parts[0].strip()
    title       = parts[1].strip()
    channel_id  = parts[2].strip()
    channel_name = parts[3].strip()
    # 容错处理：字段可能是 "NA" 或空
    def _int_or_none(v): 
        try: return int(v)
        except: return None
    duration_sec  = _int_or_none(parts[4]) if len(parts) > 4 else None
    view_count    = _int_or_none(parts[5]) if len(parts) > 5 else None
    like_count    = _int_or_none(parts[6]) if len(parts) > 6 else None
    upload_date   = parts[7].strip() if len(parts) > 7 and parts[7].strip() not in ("NA", "") else None

    if not video_id or len(video_id) != 11:
        return {"success": False, "error": f"解析到的视频 ID 格式异常（{video_id}），请检查链接"}

    # ── 4. 重复检测 ───────────────────────────────────────────────────
    existing = db.get_video_by_youtube_id(video_id)
    if existing:
        return {
            "success": False,
            "error": f"视频已在队列中（当前状态：{existing['status']}）：{existing['title']}",
            "already_exists": True,
            "current_status": existing["status"],
            "video_id": video_id,        # [Claude_Sonnet_4.6_Thinking_planning] 供 Bot 侧 respec 直接使用
            "title": existing["title"],  # [Claude_Sonnet_4.6_Thinking_planning] 供 Bot 侧特显提示展示
        }

    # ── 5. 写入队列（手工添加） ───────────────────────────────────────
    # [Claude_Sonnet_4.6_Thinking_planning] v7.0 Phase 4: 手动添加视频时，频道写入 MANUAL_ONLY
    # 而非 APPROVED，避免单视频下载导致频道被自动爬虫拉取
    if not db.get_channel_by_id(channel_id):
        db.add_channel(channel_id, channel_name,
                       status="MANUAL_ONLY", reason="Auto-registered via manual video add — NOT whitelisted")

    # 手工添加给100分加急
    disable_slicing_val = 1 if req.disable_slicing else 0
    db.add_video(
        video_id, title, channel_id, score=100, source="MANUAL",
        duration_sec=duration_sec, view_count=view_count,
        like_count=like_count, upload_date=upload_date,
        trim_start=trim_start, trim_end=trim_end,
        disable_slicing=disable_slicing_val,
        tts_provider=req.tts_provider or None,  # [Claude_Sonnet_4.6_Thinking_planning] 传递 TTS 配音引擎设置
        content_type=content_type,
    )
    bg_tasks.add_task(_translate_title_task, video_id, title)
    
    return {
        "success": True,
        "video_id": video_id,
        "title": title,
        "channel_name": channel_name,
        "trim_start": trim_start,
        "trim_end": trim_end,
        "disable_slicing": req.disable_slicing,
        "tts_provider": req.tts_provider,  # [Claude_Sonnet_4.6_Thinking_planning]
        "content_type": content_type,
    }



# ── 优先级调整 API ────────────────────────────────────────────────────────
class PriorityRequest(BaseModel):
    action: str          # "increase" | "decrease" | "set"
    value: Optional[int] = None   # 仅 action="set" 时使用


class CreateManualPublishLeaseRequest(BaseModel):
    youtube_id: str
    slice_index: int = 0
    issued_by: str
    issued_via: str = "telegram"
    ttl_minutes: int = 120


def _trigger_video_async(video: dict) -> None:
    """
    在独立子进程中处理单个视频，避免相对导入和 CWD 问题。
    输出写入 output/pipeline.log 与 vp job logs 共享。
    """
    def _run():
        prj_root = Path(__file__).parent.parent.parent
        python   = str(prj_root / ".venv" / "bin" / "python")
        src_dir  = str(prj_root / "src")
        log_path = prj_root / "output" / "pipeline.log"
        log_path.parent.mkdir(exist_ok=True)

        # 内联脚本：改用 JSON 通过 stdin 传递数据，避免 repr() 带来的代码注入风险
        import json
        video_json = json.dumps(dict(video))
        inline = (
            f"import sys, json; sys.path.insert(0, {repr(src_dir)})\n"
            f"from video_processing.pipeline_manager import PipelineManager\n"
            f"pm = PipelineManager()\n"
            f"pm._process_single_video(json.loads(sys.stdin.read()))\n"
        )
        try:
            with open(log_path, "a") as f:
                import subprocess as sp
                # [Gemini_3.5_Flash_planning] 使用 -u 启用无缓冲输出
                sp.run([python, "-u", "-c", inline], input=video_json, text=True,
                       cwd=str(prj_root), stdout=f, stderr=f)
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"_trigger_video_async failed: {e}")

    threading.Thread(target=_run, daemon=True,
                     name=f"pipeline-{video.get('youtube_id','?')[:8]}").start()


@app.get("/api/publication-leases/candidates")
def list_manual_publish_lease_candidates(limit: int = 8):
    """只读返回手机端可选择的单任务候选和当前未消费 lease。"""
    candidates = db.list_manual_publish_lease_candidates(limit=limit)
    market_guard_active = settings.is_us_market_guard_window()
    if market_guard_active:
        candidates = [item for item in candidates if item.get("preparation_ready")]
    return {
        "candidates": candidates,
        "active_leases": db.list_active_manual_publish_leases(limit=limit),
        "ttl_minutes": 120,
        "market_guard_active": market_guard_active,
    }


@app.post("/api/publication-leases")
def create_manual_publish_lease(req: CreateManualPublishLeaseRequest):
    """签发两小时单任务微信 lease，并原子领取后启动既有安全管线。"""
    youtube_id = (req.youtube_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,64}", youtube_id):
        return {"success": False, "error": "youtube_id 格式不合法"}
    if req.slice_index < 0:
        return {"success": False, "error": "slice_index 不能为负数"}
    video = db.get_video_by_youtube_id(youtube_id, slice_index=req.slice_index)
    if not video:
        return {"success": False, "error": "任务不存在"}
    if settings.is_us_market_guard_window() and not video.get("preparation_ready"):
        return {
            "success": False,
            "error": "美股盘中仅允许已完成预加工的成片签发发布 lease",
        }
    try:
        lease = db.issue_manual_publish_lease(
            youtube_id,
            slice_index=req.slice_index,
            issued_by=req.issued_by,
            issued_via=req.issued_via,
            ttl_minutes=req.ttl_minutes,
            claim_video=True,
        )
    except (TypeError, ValueError) as exc:
        return {"success": False, "error": str(exc)}

    fresh = db.get_video_by_youtube_id(youtube_id, slice_index=req.slice_index)
    if not fresh:
        return {"success": False, "error": "任务领取后读取失败；lease 未消费", "lease": lease}
    _trigger_video_async(fresh)
    return {
        "success": True,
        "message": "两小时单任务 lease 已签发，安全管线已启动",
        "lease": lease,
        "video": fresh,
    }

@app.patch("/api/videos/{youtube_id}/priority")
def update_video_priority(youtube_id: str, req: PriorityRequest):
    """
    调整视频优先级（即 score 字段）。
    若调整后 score >= 75 且视频仍是 PENDING，立即在后台启动处理管线。
    """
    video = db.get_video_by_youtube_id(youtube_id)
    if not video:
        return {"success": False, "error": "视频不存在"}

    wechat_publication = db.get_wechat_publication(youtube_id)
    if wechat_publication and wechat_publication.get("state") in {"PUBLISHED", "UNDER_REVIEW", "UNCERTAIN", "REJECTED"}:
        return {
            "success": False,
            "error": f"视频号账本当前为 {wechat_publication['state']}；请先运行作品管理页回查，禁止绕过账本直接重传。",
        }

    # [Gemini_2.5_Pro_planning] v3.3.0: DISCOVERY 源视频禁止通过评分按钮触发管线
    # 用户可以在 high_likes tab 浏览，但不能通过调分间接发起下载/发布
    is_discovery = video.get("source") == "DISCOVERY"

    current = video.get("score", 0)
    if req.action == "increase":
        new_score = min(100, current + 10)
    elif req.action == "decrease":
        new_score = max(0, current - 10)
    elif req.action == "set" and req.value is not None:
        new_score = max(0, min(100, req.value))
    else:
        return {"success": False, "error": f"未知操作：{req.action}"}

    # [Claude_Sonnet_4.6_Thinking_planning] v7.0 Phase 3+4:
    # 人工调分使用 force=True 打上手动锁，防止自动算分覆盖
    db.update_video_score(youtube_id, new_score, force=True)

    # 若打分为 0，将视频加入黑名单（Flag 保护）
    # [Gemini_2.5_Pro_planning] DISCOVERY 视频打 0 分只删除记录，不加黑名单（发现列表和业务黑名单隔离）
    if new_score == 0 and settings.enable_blacklist_tombstone and not is_discovery:
        db.add_to_blacklist(youtube_id, reason="manually_scored_zero")  # LINT-3: 去除多余 f-string
        db.delete_video_record(youtube_id)
        return {"success": True, "youtube_id": youtube_id, "score": 0,
                "triggered": False, "blacklisted": True,
                "message": "已打 0 分并移入黑名单，该视频不会被自动爬虫再次拉取"}
    elif new_score == 0 and is_discovery:
        db.delete_video_record(youtube_id)
        return {"success": True, "youtube_id": youtube_id, "score": 0,
                "triggered": False, "blacklisted": False,
                "message": "已从高赞发现列表中删除该条目"}

    # 自动触发：score 越过调度线，且抢占成功（原状态为 PENDING）
    # [Gemini_2.5_Pro_planning] DISCOVERY 视频不允许通过调分触发管线，防火墙保护
    triggered = False
    publish_line = settings.speech_publish_score_line if video.get("channel_id") in settings.speech_channel_id_set else 75
    if not is_discovery and new_score >= publish_line and db.claim_video_for_processing(youtube_id):
        fresh = db.get_video_by_youtube_id(youtube_id)
        if fresh:
            _trigger_video_async(fresh)
            triggered = True

    return {"success": True, "youtube_id": youtube_id, "score": new_score, "triggered": triggered}


@app.post("/api/videos/{youtube_id}/process")
def process_video_now(youtube_id: str):
    """立即处理指定视频，忽略分数阈值。"""
    video = db.get_video_by_youtube_id(youtube_id)
    if not video:
        return {"success": False, "error": "视频不存在"}
    # [Gemini_2.5_Pro_planning] v3.3.0: DISCOVERY 源视频仅供浏览，禁止通过 API 直接触发自动处理管线
    if video.get("source") == "DISCOVERY":
        return {"success": False, "error": "DISCOVERY 来源视频不允许自动处理，请手动添加后再执行"}
    if not db.claim_video_for_processing(youtube_id):
        return {"success": False, "error": f"视频当前状态不是 PENDING，或者已被其他进程抢占处理"}

    fresh = db.get_video_by_youtube_id(youtube_id)
    if fresh:
        _trigger_video_async(fresh)

    return {"success": True, "message": f"已在后台启动处理：{video['title']}"}


@app.post("/api/videos/{youtube_id}/promote")
def promote_video(youtube_id: str):
    """[Claude_Opus_4.8] 将高赞发现(DISCOVERY)视频一键「加入队列」并立即发布。

    把 source 提升为 MANUAL、score=100 后立即触发完整处理管线，
    替代原先「删除 DISCOVERY 条目 → 手动重新粘贴链接」的三步绕路：
    保留已抓取的元数据/zh_title，且不经过黑名单墓碑。
    仅 DISCOVERY 源视频可被提升（其余来源已在正式队列中，应使用 ⚡执行/重试）。
    """
    video = db.get_video_by_youtube_id(youtube_id)
    if not video:
        return {"success": False, "error": "视频不存在"}

    if video.get("source") != "DISCOVERY":
        return {"success": False,
                "error": f"仅高赞发现视频可加入队列（当前来源：{video.get('source')}）"}

    # 原子转换：DISCOVERY → MANUAL，score=100，并打手动评分锁
    if not db.promote_to_manual(youtube_id, score=100):
        return {"success": False, "error": "转换失败：该视频可能已被处理或来源已变更"}

    # 立即触发管线：抢占 PENDING → DOWNLOADING 后异步执行
    triggered = False
    if db.claim_video_for_processing(youtube_id):
        fresh = db.get_video_by_youtube_id(youtube_id)
        if fresh:
            _trigger_video_async(fresh)
            triggered = True

    return {
        "success": True,
        "youtube_id": youtube_id,
        "triggered": triggered,
        "message": "已加入队列并立即开始处理" if triggered
                   else "已加入队列（score=100），等待调度器触发",
    }


@app.post("/api/platforms/wechat/reconcile")
def reconcile_wechat_publications():
    """拒绝历史标题回查，避免把不同视频号作品错误关联。"""
    return {
        "success": False,
        "message": "自动回查已停用：必须先绑定视频号平台原生 post_id，禁止按标题或时间匹配。",
    }


# ── 审查复核：关键词标签云 + 一键放行 ───────────────────────────────────────
# [Claude_Opus_4.8] 供「🔓 复核放行」按钮：把命中词与字幕关键词摊给人看，知情后绕过审查。
_EN_STOPWORDS = {
    "the","a","an","and","or","but","of","to","in","on","for","with","at","by","from",
    "is","are","was","were","be","been","being","this","that","these","those","it","its",
    "as","if","so","than","then","there","here","not","no","you","your","yours","we","our",
    "they","he","she","his","her","him","i","me","my","us","them","what","which","who","how",
    "when","where","why","will","would","can","could","should","may","might","must","do","does",
    "did","done","have","has","had","about","into","over","under","after","before","up","down",
    "out","off","just","like","get","got","now","all","one","two","more","most","some","any",
    "very","also","only","even","because","while","such","each","other","many","much","they're",
}


def _read_subtitle_text(youtube_id: str, slice_index: int = 0, max_chars: int = 40000) -> str:
    """读取该视频（或指定切片）所有 .ass 双语字幕的纯文本（去 ASS 标签）并拼接。失败时返回空串。

    [Claude_Opus_4.8] 实现已下沉至 utils.file_utils.read_subtitle_text（单一真相源，
    与管线字幕审查共用）；此处保留薄封装以兼容 Web 复核 UI 既有调用点。
    """
    from video_processing.utils.file_utils import read_subtitle_text
    return read_subtitle_text(_OUT_DIR, youtube_id, slice_index=slice_index, max_chars=max_chars)


def _censor_layer_from_error(error_msg: str):
    """从 error_msg 反推审查层级与告警严重度。返回 (layer, label, severity)。"""
    em = error_msg or ""
    if "Censorship P0" in em:
        return ("P0", "P0 · 政治安全违禁", "critical")
    if "Censorship P1" in em:
        return ("P1", "P1 · 敏感内容挂起", "high")
    if "Censorship P2" in em:
        return ("P2", "P2 · 商业合规降权", "medium")
    if "Channel Policy" in em:
        return ("CP", "频道策略限制", "low")
    return (None, "未知审查层", "low")


def _build_keyword_cloud(text_zh: str, text_en: str, matched_terms: list, top_k: int = 40) -> list:
    """jieba(中文 TF-IDF) + 英文词频 → [{word, weight, flagged}]，命中词置顶并高亮。"""
    cloud: dict = {}
    # 中文关键词（TF-IDF）
    try:
        import jieba.analyse
        for word, weight in jieba.analyse.extract_tags(text_zh, topK=top_k, withWeight=True):
            w = (word or "").strip()
            if len(w) >= 2:
                cloud[w] = max(cloud.get(w, 0.0), float(weight))
    except Exception:
        pass
    # 英文词频（归一化到与 TF-IDF 量级接近的区间）
    try:
        from collections import Counter
        words = [w for w in re.findall(r"[a-zA-Z][a-zA-Z'\-]{2,}", text_en.lower())
                 if w not in _EN_STOPWORDS]
        if words:
            cnt = Counter(words)
            mx = max(cnt.values())
            for w, c in cnt.most_common(top_k):
                cloud[w] = max(cloud.get(w, 0.0), 0.15 + 0.5 * (c / mx))
    except Exception:
        pass

    matched_lower = [str(m.get("term", "")).lower() for m in matched_terms if m.get("term")]
    # 命中词强制注入，权重置顶，确保即使未被 TF-IDF 选中也出现在云里
    for m in matched_terms:
        t = str(m.get("term", "")).strip()
        if t:
            cloud[t] = max(cloud.get(t, 0.0), 1.0)

    def _is_flagged(word: str) -> bool:
        wl = word.lower()
        return any(mt and (mt in wl or wl in mt) for mt in matched_lower)

    items = [{"word": w, "weight": round(wt, 4), "flagged": _is_flagged(w)} for w, wt in cloud.items()]
    items.sort(key=lambda x: (not x["flagged"], -x["weight"]))  # 命中词置顶，其余按权重降序
    return items[:top_k]


@app.get("/api/videos/{youtube_id}/censor-keywords")
def censor_keywords(youtube_id: str, slice_index: int = 0):
    """[Claude_Opus_4.8] 「复核放行」弹窗数据：审查层级、全部命中词、标题+字幕关键词标签云。"""
    if not re.match(r'^[A-Za-z0-9_\-]+$', youtube_id):
        raise HTTPException(status_code=400, detail="Invalid youtube_id")
    video = db.get_video_by_youtube_id(youtube_id, slice_index=slice_index)
    if not video:
        return {"success": False, "error": "视频不存在"}

    title = video.get("title") or ""
    zh_title = video.get("zh_title") or ""
    subtitle = _read_subtitle_text(youtube_id, slice_index=slice_index)

    has_zh = bool(re.search(r"[一-龥]", title))
    text_zh = "\n".join(filter(None, [zh_title or (title if has_zh else ""), subtitle]))
    text_en = "\n".join(filter(None, [title, subtitle]))

    from video_processing.censor_engine import scan_all_matches
    matched = scan_all_matches(zh_text=text_zh, en_text=text_en)
    layer, layer_label, severity = _censor_layer_from_error(video.get("error_msg"))
    keywords = _build_keyword_cloud(text_zh, text_en, matched)

    return {
        "success": True,
        "youtube_id": youtube_id,
        "title": title,
        "zh_title": zh_title,
        "error_msg": video.get("error_msg") or "",
        "censor_tag": video.get("censor_tag") or "",
        "layer": layer,
        "layer_label": layer_label,
        "severity": severity,
        "matched": matched,
        "keywords": keywords,
        "has_subtitle": bool(subtitle),
        "subtitle_chars": len(subtitle),
    }


@app.post("/api/videos/{youtube_id}/bypass-censor")
def bypass_censor(youtube_id: str, slice_index: int = 0):
    """[Claude_Opus_4.8] 人工复核放行：对审查类失败视频置 bypass 标志，解黑名单、过线、重置并重新触发。

    仅 FAILED 且失败原因为审查（Censorship P0/P1 或 Channel Policy）的视频可放行。
    放行后管线 _check_censorship 会跳过全部审查层（用户已知情确认）。

    [Claude_Opus_4.8] BUG-1 配套：bypass 现按 (youtube_id, slice_index) 粒度放行——
    与管线侧 _check_censorship 透传 slice_index 对齐，避免「放行父视频即静默放行全部切片」。
    切片任务（slice_index>0）须由调用方传入对应 slice_index 才能释放该切片本身。
    """
    video = db.get_video_by_youtube_id(youtube_id, slice_index=slice_index)
    if not video:
        return {"success": False, "error": "视频不存在"}

    em = video.get("error_msg") or ""
    is_censor_fail = ("Censorship" in em) or ("Channel Policy" in em) or bool(video.get("censor_tag"))
    if video.get("status") != "FAILED" or not is_censor_fail:
        return {"success": False,
                "error": f"仅审查类失败(FAILED)的视频可复核放行（当前状态：{video.get('status')}）"}

    layer, _label, _sev = _censor_layer_from_error(em)

    # 1) 置放行标志（管线据此跳过全部审查层）——按当前 (yid, slice_index) 粒度
    db.set_bypass_censorship(youtube_id, True, slice_index=slice_index)
    # 2) 若 P0 曾写入黑名单墓碑，移除以允许继续处理（黑名单按视频 ID 维度，无切片粒度）
    db.remove_from_blacklist(youtube_id)
    # 3) 确保分数过调度线（P2 曾降权至 0；其余一般已过线）
    if (video.get("score") or 0) < 75:
        db.update_video_score(youtube_id, 100, force=True, slice_index=slice_index)
    # 4) 重置为 PENDING 并清除错误信息
    db.update_video_status(youtube_id, "PENDING", error_msg=None, slice_index=slice_index)
    # 5) 立即抢占并触发管线
    triggered = False
    if db.claim_video_for_processing(youtube_id, slice_index=slice_index):
        fresh = db.get_video_by_youtube_id(youtube_id, slice_index=slice_index)
        if fresh:
            _trigger_video_async(fresh)
            triggered = True

    return {
        "success": True,
        "youtube_id": youtube_id,
        "slice_index": slice_index,
        "layer": layer,
        "triggered": triggered,
        "message": "已复核放行并重新触发管线" if triggered else "已复核放行（score=100），等待调度器触发",
    }


# ── 下载进度估算（磁盘轮询，下载器无关）─────────────────────────────────────
# [Claude_Opus_4.8] yt-dlp 用 curl 外部下载器，其进度模板/钩子对外部下载不生效；
# 改为轮询 output/{yid}.f* 临时分片文件大小估算已下字节，info.json.filesize_approx 为总量，
# 两次轮询的字节差 / 时间差即为速度。完全不侵入 pipeline_manager 的下载流程。
_DL_SAMPLES: dict = {}   # {yid: (monotonic_ts, downloaded_bytes)} 用于速度估算


def _dl_downloaded_bytes(yid: str) -> int:
    """累加 output/{yid}.f*（视频流/音频流/分片，含 .part）的大小作为已下字节数。"""
    total = 0
    for p in _OUT_DIR.glob(f"{yid}.f*"):
        try:
            total += p.stat().st_size
        except OSError:
            pass
    return total


def _dl_total_bytes(yid: str):
    """从 output/{yid}.info.json 读取选定格式的总大小（filesize 优先，回退 filesize_approx）。"""
    info = _OUT_DIR / f"{yid}.info.json"
    if not info.exists():
        return None
    try:
        import json
        d = json.loads(info.read_text(encoding="utf-8"))
        return d.get("filesize") or d.get("filesize_approx")
    except Exception:
        return None


@app.get("/api/videos/{youtube_id}/download-progress")
def download_progress(youtube_id: str):
    """[Claude_Opus_4.8] 估算 DOWNLOADING 视频的下载进度/速度/ETA。

    返回 active=False 表示当前不在下载态（前端据此停止显示进度条）。
    percent 为 None 表示拿不到总量（info.json 缺 filesize_*），此时仍返回已下字节与速度。
    """
    if not re.match(r'^[A-Za-z0-9_\-]+$', youtube_id):
        raise HTTPException(status_code=400, detail="Invalid youtube_id")
    video = db.get_video_by_youtube_id(youtube_id)
    if not video:
        return {"success": False, "error": "视频不存在"}
    if video.get("status") != "DOWNLOADING":
        _DL_SAMPLES.pop(youtube_id, None)
        return {"success": True, "active": False, "phase": "idle"}

    downloaded = _dl_downloaded_bytes(youtube_id)
    total = _dl_total_bytes(youtube_id)

    # 速度：与上次采样比较（dt ≥ 0.5s 才更新采样，避免多标签页高频轮询导致抖动）
    now = time.monotonic()
    speed_bps = None
    prev = _DL_SAMPLES.get(youtube_id)
    if prev:
        dt = now - prev[0]
        delta = downloaded - prev[1]
        if dt >= 0.5:
            if delta >= 0:
                speed_bps = delta / dt
            _DL_SAMPLES[youtube_id] = (now, downloaded)
    else:
        _DL_SAMPLES[youtube_id] = (now, downloaded)

    if downloaded <= 0:
        return {"success": True, "active": True, "phase": "starting",
                "downloaded_bytes": 0, "total_bytes": total,
                "percent": None, "speed_bps": int(speed_bps) if speed_bps else None, "eta_sec": None}

    percent = None
    eta_sec = None
    if total and total > 0:
        percent = max(0.0, min(99.0, downloaded / total * 100.0))
        if speed_bps and speed_bps > 0:
            eta_sec = max(0, int((total - downloaded) / speed_bps))

    return {
        "success": True, "active": True, "phase": "downloading",
        "downloaded_bytes": downloaded, "total_bytes": total,
        "percent": round(percent, 1) if percent is not None else None,
        "speed_bps": int(speed_bps) if speed_bps else None,
        "eta_sec": eta_sec,
    }


@app.post("/api/videos/{youtube_id}/republish")
def republish_video(youtube_id: str):
    """再次发布入口暂时 fail-closed，避免本地状态被误当作平台删除证明。"""
    video = db.get_video_by_youtube_id(youtube_id)
    if not video:
        return {"success": False, "error": "视频不存在"}
    if video.get("status") not in ("PUBLISHED", "COMPLETED"):
        return {"success": False,
                "error": f"仅已完成/已发布的视频可再次发布（当前状态：{video.get('status')}）"}

    publication = db.get_wechat_publication(youtube_id)
    if not publication or publication.get("state") != "PUBLISHED" or not all(
        publication.get(field) for field in ("confirmed_at", "evidence_path", "platform_post_id")
    ):
        return {
            "success": False,
            "error": "缺少按原生平台 ID 确认的公开视频账本，拒绝再次发布以避免重复提交。",
        }
    return {
        "success": False,
        "error": "平台作品是否已删除尚无按原生 ID 的可审计证明；再次发布入口已暂停，禁止自动重传。",
    }


@app.post("/api/videos/{youtube_id}/retry")
def retry_video(youtube_id: str):
    """
    重试/强制重置视频状态为 PENDING。
    - FAILED / LOGIN_REQUIRED：正常重试，清除错误信息
    - DOWNLOADING/TRANSCRIBING/COPYWRITING：服务器重启后卡死的预提交任务，强制重置
    若当前分数 >= 75，重置后立即自动重新触发。
    """
    video = db.get_video_by_youtube_id(youtube_id)
    if not video:
        return {"success": False, "error": "视频不存在"}

    submission_guard = _wechat_submission_guard_reason(video)
    if submission_guard:
        return {"success": False, "error": submission_guard}

    retryable = {"FAILED", "LOGIN_REQUIRED", "DOWNLOADING", "TRANSCRIBING", "COPYWRITING"}
    if video.get("status") not in retryable:
        return {
            "success": False,
            "error": f"只有 FAILED / LOGIN_REQUIRED / 各活跃状态可重置（当前：{video['status']}）"
        }

    db.update_video_status(youtube_id, "PENDING", error_msg=None)

    triggered = False
    if video.get("score", 0) >= 75 and db.claim_video_for_processing(youtube_id):
        fresh = db.get_video_by_youtube_id(youtube_id)
        if fresh:
            _trigger_video_async(fresh)
            triggered = True

    return {
        "success": True,
        "triggered": triggered,
        "message": "已重置并立即重新触发" if triggered else "已重置为 PENDING，请将优先级提升至 ≥75 后触发",
    }


@app.post("/api/videos/retry-recent")
def retry_recent(hours: int = 24):
    """批量重试最近 N 小时内 FAILED / LOGIN_REQUIRED 的任务：重置为 PENDING（复用 GC 保留的
    成片/封面/文案 checkpoint，秒级重跑）。供 Telegram /retry <hours>。

    仅重置状态、不在此逐条触发（避免一次性 spawn 过多进程）；score>=75 的会被仪表盘调度器
    在下次巡检自动重新发布（盘中重负载护栏仍生效）。
    """
    if hours <= 0 or hours > 720:
        return {"success": False, "error": "hours 需在 1~720 之间"}
    rows = db.get_failed_videos_since(hours)
    safe_rows = [row for row in rows if not _wechat_submission_guard_reason(row)]
    count = 0
    for r in safe_rows:
        db.update_video_status(
            r["youtube_id"], "PENDING", error_msg=None,
            slice_index=int(r.get("slice_index") or 0),
        )
        count += 1
    return {
        "success": True,
        "count": count,
        "skipped_platform_guard": len(rows) - count,
        "hours": hours,
        "items": [(r.get("title") or "")[:42] for r in safe_rows[:10]],
    }


@app.get("/api/videos/retry-recent/preview")
def retry_recent_preview(hours: int = 24):
    """只读预览最近 N 小时内 /retry <hours> 会重置的任务。"""
    if hours <= 0 or hours > 720:
        return {"success": False, "error": "hours 需在 1~720 之间"}
    rows = db.get_failed_videos_since(hours)
    safe_rows = [row for row in rows if not _wechat_submission_guard_reason(row)]
    return {
        "success": True,
        "count": len(safe_rows),
        "skipped_platform_guard": len(rows) - len(safe_rows),
        "hours": hours,
        "items": [
            {
                "youtube_id": r.get("youtube_id"),
                "slice_index": int(r.get("slice_index") or 0),
                "title": (r.get("title") or "")[:80],
                "status": r.get("status"),
            }
            for r in safe_rows[:10]
        ],
    }


@app.post("/api/videos/{youtube_id}/slices/{slice_index}/retry")
def retry_slice(youtube_id: str, slice_index: int):
    """[Gemini_3.5_Flash_High_planning] 针对单个切片子任务执行重置与重试"""
    video = db.get_video_by_youtube_id(youtube_id, slice_index=slice_index)
    if not video:
        raise HTTPException(status_code=404, detail="切片任务不存在")

    submission_guard = _wechat_submission_guard_reason(video)
    if submission_guard:
        return {"success": False, "error": submission_guard}

    retryable = {"FAILED", "LOGIN_REQUIRED", "DOWNLOADING", "TRANSCRIBING", "COPYWRITING"}
    if video.get("status") not in retryable:
        return {
            "success": False,
            "error": f"只有 FAILED / LOGIN_REQUIRED / 各活跃状态可重置（当前：{video['status']}）"
        }

    db.update_video_status(youtube_id, "PENDING", error_msg=None, slice_index=slice_index)

    triggered = False
    # 手动重试：若分数 >= 75 且父视频存在，并且满足 Sequence Lock（前序子任务均已发布），则立即触发
    if video.get("score", 0) >= 75:
        from video_processing.pipeline_manager import PipelineManager
        pm = PipelineManager()
        parent_file = pm._find_downloaded_video(youtube_id)
        
        all_slices = db.get_slices_by_parent_yid(youtube_id)
        prev_not_published = [s for s in all_slices if s['slice_index'] < slice_index and s['status'] != 'PUBLISHED']
        
        if parent_file and not prev_not_published:
            if db.claim_video_for_processing(youtube_id, slice_index=slice_index):
                fresh = db.get_video_by_youtube_id(youtube_id, slice_index=slice_index)
                if fresh:
                    _trigger_video_async(fresh)
                    triggered = True

    return {
        "success": True,
        "triggered": triggered,
        "message": "已重置并立即重新触发" if triggered else "已重置为 PENDING，等待父任务下载或前导分集发布",
    }


@app.post("/api/videos/{youtube_id}/slices/{slice_index}/process")
def process_slice_now(youtube_id: str, slice_index: int):
    """[Unknown_Model_planning] 立即处理指定切片子任务，忽略分数。"""
    video = db.get_video_by_youtube_id(youtube_id, slice_index=slice_index)
    if not video:
        raise HTTPException(status_code=404, detail="切片任务不存在")

    if video.get("status") != "PENDING":
        return {
            "success": False,
            "error": f"只有 PENDING 状态的切片可以启动（当前：{video['status']}）"
        }

    # 检查父视频文件是否下载就绪
    from video_processing.pipeline_manager import PipelineManager
    pm = PipelineManager()
    parent_file = pm._find_downloaded_video(youtube_id)
    if not parent_file:
        return {"success": False, "error": "父视频主文件尚未就绪，请先下载或重试父视频。"}

    # 检查顺序锁（前序子任务是否已发布）
    all_slices = db.get_slices_by_parent_yid(youtube_id)
    prev_not_published = [s for s in all_slices if s['slice_index'] < slice_index and s['status'] not in ('PUBLISHED', 'IGNORED', 'COMPLETED')]
    if prev_not_published:
        prev_indices = [s['slice_index'] for s in prev_not_published]
        return {
            "success": False,
            "error": f"前序切片 {prev_indices} 尚未发布/跳过/手动上传，当前切片已被顺序锁阻断。"
        }

    # 抢占任务
    if not db.claim_video_for_processing(youtube_id, slice_index=slice_index):
        return {"success": False, "error": "切片已被其他进程抢占。"}

    fresh = db.get_video_by_youtube_id(youtube_id, slice_index=slice_index)
    if fresh:
        _trigger_video_async(fresh)

    return {
        "success": True,
        "message": f"已在后台启动切片子任务 [{youtube_id} s{slice_index}] 处理"
    }


@app.post("/api/videos/{youtube_id}/reset-hard")
def reset_video_hard(youtube_id: str):
    """
    硬重置：删除该视频所有本地产物文件（mp4/vertical/copy/cover/title/category），
    然后重置状态为 PENDING。若分数 >= 75 立即重新触发完整管线（从下载开始）。
    """
    video = db.get_video_by_youtube_id(youtube_id)
    if not video:
        return {"success": False, "error": "视频不存在"}

    submission_guard = _wechat_submission_guard_reason(video)
    if submission_guard:
        return {"success": False, "error": submission_guard}

    # 调用 PipelineManager 的硬重置方法删除产物文件
    from video_processing.pipeline_manager import PipelineManager
    pm = PipelineManager()
    deleted = pm.reset_video_artifacts(youtube_id)

    db.update_video_status(youtube_id, "PENDING", error_msg=None)

    triggered = False
    if video.get("score", 0) >= 75 and db.claim_video_for_processing(youtube_id):
        fresh = db.get_video_by_youtube_id(youtube_id)
        if fresh:
            _trigger_video_async(fresh)
            triggered = True

    return {
        "success": True,
        "deleted_files": deleted,
        "triggered": triggered,
        "message": f"已删除 {len(deleted)} 个产物文件，重置为 PENDING" + ("并重新触发" if triggered else ""),
    }


# [Gemini_2.5_Pro_planning] 注意：此路由必须在 /api/videos/{youtube_id} 之前注册，
# 否则 FastAPI 会将 'waitlist' 当成 youtube_id 参数，导致 404。
@app.delete("/api/videos/waitlist/all")
def clear_waitlist():
    """[Gemini_2.5_Pro_planning] 清空待筛选列表（全部 PENDING 且分数 < 75 的视频）。

    清空后会写入黑名单墓碑，爬虫不会再次拉取这些视频。

    [Claude_Opus_4.8] BUG-5: 改走 DAL get_waitlist_clearable_ids()，显式排除 DISCOVERY，
    避免一键清空误删/拉黑高赞发现条目（击穿发现防火墙）。
    """
    # 获取待筛选列表所有可清空 ID（DAL 集中谓词，排除 DISCOVERY）
    all_ids = db.get_waitlist_clearable_ids()

    if not all_ids:
        return {"success": True, "deleted_count": 0, "message": "待筛选列表已经是空的"}

    tombstone = settings.enable_blacklist_tombstone
    deleted_count, failed_ids = db.batch_delete_video_records(all_ids, tombstone=tombstone)

    msg = f"共清空 {deleted_count} 条待筛选视频"
    if tombstone:
        msg += "（已全部写入黑名单，爬虫不会再次抓取）"
    return {
        "success": not failed_ids,
        "deleted_count": deleted_count,
        "failed_ids": failed_ids,
        "message": msg,
    }


@app.delete("/api/videos")
def batch_delete_videos(req: BatchDeleteRequest):
    """[Gemini_2.5_Pro_planning]    批量删除视频记录（不含物理文件，除非可选）。
    
    # Modification History
    | Version | Date | Author | Description |
    | --- | --- | --- | --- |
    | 1.0.0 | 2026-05-24 | Unknown_Model | Initial creation |
    | 1.1.0 | 2026-05-27 | Unknown_Model_planning | 修复未清理活跃切片任务进程和产物文件的 bug |
    
    不支持删除正处于活跃状态的视频（ACTIVE_STATUSES）——需先停止进程再删除。
    """
    if not req.youtube_ids:
        return {"success": False, "error": "请提供要删除的视频 ID 列表"}

    # 安全校验：拒绝删除活跃任务
    invalid = [yid for yid in req.youtube_ids if not re.match(r'^[A-Za-z0-9_\-]+$', yid)]
    if invalid:
        return {"success": False, "error": f"非法 ID: {invalid}"}

    active_ids = []
    protected_ids = []
    for yid in req.youtube_ids:
        parent = db.get_video_by_youtube_id(yid, slice_index=0)
        slices = db.get_slices_by_parent_yid(yid)
        targets = ([parent] if parent else []) + slices
        if any(_wechat_submission_guard_reason(target) for target in targets):
            protected_ids.append(yid)
        if any(t.get("status") in ACTIVE_STATUSES for t in targets):
            active_ids.append(yid)

    if protected_ids:
        return {
            "success": False,
            "error": f"以下视频存在视频号平台账本，禁止删除以保留防重传审计：{protected_ids}",
        }

    if active_ids:
        return {
            "success": False,
            "error": f"以下视频（或其切片）正在处理中，无法批量删除：{active_ids}",
        }

    # 可选删除产物文件
    deleted_files_total: list[str] = []
    if req.delete_files:
        from video_processing.pipeline_manager import PipelineManager
        pm = PipelineManager()
        for yid in req.youtube_ids:
            deleted_files_total.extend(pm.reset_video_artifacts(yid))
            slices = db.get_slices_by_parent_yid(yid)
            for s in slices:
                deleted_files_total.extend(pm.reset_video_artifacts(f"{yid}_s{s['slice_index']}"))

    tombstone = settings.enable_blacklist_tombstone
    deleted_count, failed_ids = db.batch_delete_video_records(req.youtube_ids, tombstone=tombstone)

    msg = f"共删除 {deleted_count} 条视频记录"
    if tombstone:
        msg += "（已写入黑名单，爬虫不会再次抓取）"
    if req.delete_files:
        msg += f"，并清理了 {len(deleted_files_total)} 个产物文件"
    if failed_ids:
        msg += f"。失败: {failed_ids}"

    return {
        "success": not failed_ids,
        "deleted_count": deleted_count,
        "failed_ids": failed_ids,
        "deleted_files": deleted_files_total,
        "message": msg,
    }


@app.delete("/api/videos/{youtube_id}")
def delete_video(youtube_id: str, delete_files: bool = False, slice_index: Optional[int] = None):
    """
    删除任务记录并可选写入黑名单墓碑。
    如果 delete_files=True，同时删除相关的本地产物文件。

    # Modification History
    | Version | Date | Author | Description |
    | --- | --- | --- | --- |
    | 1.0.0 | 2026-05-24 | Unknown_Model | Initial creation |
    | 1.1.0 | 2026-05-27 | Gemini_3.5_Flash_High_planning | 支持定向删除 slice_index，加入 SIGTERM 强杀逻辑 |
    | 1.2.0 | 2026-05-27 | Unknown_Model_planning | [Bugfix] 删除父视频时，连带强杀所有活跃切片子进程并删除产物 |

    [Gemini_3.5_Flash_High_planning] 升级：
    - 支持通过 slice_index 参数定向物理删除子任务。
    - 如果视频处于活跃状态且 settings.enable_sigterm_kill=True，
      会向其进程组发 SIGTERM 优雅终止，超时 2s 后强杀。
    - 删除后（若是父视频）将 youtube_id 写入 blacklisted_videos 墓碑表，
      防止爬虫二次拉取。
    """
    if slice_index is not None:
        targets = [db.get_video_by_youtube_id(youtube_id, slice_index=slice_index)]
    else:
        parent = db.get_video_by_youtube_id(youtube_id, slice_index=0)
        slices = db.get_slices_by_parent_yid(youtube_id)
        targets = ([parent] if parent else []) + slices

    targets = [t for t in targets if t]
    if not targets:
        return {"success": False, "error": "视频不存在"}

    if any(_wechat_submission_guard_reason(target) for target in targets):
        return {
            "success": False,
            "error": "视频号存在平台账本或待确认提交，禁止删除以保留防重传审计。",
        }

    # ── 1. 处理活跃任务：SIGTERM 阶梯强杀 ───────────────────────
    active_targets = [t for t in targets if t.get("status") in ACTIVE_STATUSES]
    
    if active_targets:
        if not settings.enable_sigterm_kill:
            # Flag 未开启：保持原有行为，拒绝删除活跃任务
            active_statuses = {str(t.get("status")) for t in active_targets}
            return {"success": False,
                    "error": f"安全拦截：相关视频/切片正处于执行状态（{', '.join(active_statuses)}）。"
                             "请等待完成或变为 FAILED。"}

        # Flag 开启：SIGTERM 阶梯强杀
        pids_to_kill = [t.get("process_pid") for t in active_targets if t.get("process_pid")]
        if pids_to_kill:
            for pid in pids_to_kill:
                try:
                    os.killpg(pid, signal.SIGTERM)   # 优雅终止信号
                except (ProcessLookupError, PermissionError):
                    pass
            
            time.sleep(2.0)                  # 等待 2 秒自退（time 已顶层导入）
            
            for pid in pids_to_kill:
                try:
                    os.killpg(pid, 0)            # 检查进程是否仍存活
                    os.killpg(pid, signal.SIGKILL)
                    import logging as _logging   # 局部别名，避免覆盖模块级 logger
                    _logging.getLogger(__name__).warning(
                        f"[SIGKILL] Process group {pid} did not exit after SIGTERM, force killed.")
                except (ProcessLookupError, PermissionError):
                    pass  # 进程已自退或在 macOS 下已变为僵尸进程，视为正常退出

    # ── 2. 删除产物文件 ─────────────────────────────────────────
    deleted_files = []
    if delete_files:
        from video_processing.pipeline_manager import PipelineManager
        pm = PipelineManager()
        if slice_index is not None:
            prefix = f"{youtube_id}_s{slice_index}" if slice_index > 0 else youtube_id
            deleted_files.extend(pm.reset_video_artifacts(prefix))
        else:
            deleted_files.extend(pm.reset_video_artifacts(youtube_id))
            for t in targets:
                idx = t.get("slice_index")
                if idx and idx > 0:
                    deleted_files.extend(pm.reset_video_artifacts(f"{youtube_id}_s{idx}"))

    # ── 3. 黑名单墓碑 + 删除主表记录 ──────────────────────────
    # [Gemini_3.5_Flash_High_planning] 仅当删除父视频（非 slice 子任务）时，才写入黑名单墓碑
    if settings.enable_blacklist_tombstone and not slice_index:
        db.add_to_blacklist(youtube_id, reason="user_deleted")
        
    db.delete_video_record(youtube_id, slice_index=slice_index)

    msg = "已彻底清除该任务记录"
    if settings.enable_blacklist_tombstone and not slice_index:
        msg += "（已写入黑名单，爬虫不会再次拉取）"
    if delete_files:
        msg += f"，并清理了 {len(deleted_files)} 个关联产物文件"

    return {
        "success": True,
        "deleted_files": deleted_files,
        "message": msg,
    }


class RespecVideoRequest(BaseModel):
    trim_start: Optional[str] = None
    trim_end: Optional[str] = None
    disable_slicing: Optional[bool] = True
    tts_provider: Optional[str] = None


@app.post("/api/videos/{youtube_id}/respec")
def respec_video(youtube_id: str, req: RespecVideoRequest):
    """规格覆盖：停止当前处理（如有），更新规格字段，重新入队并触发。

    适用于：用户发现裁剪参数有误，重发同一 URL + 新参数后的自动修正流程。

    # Modification History
    | Version | Date       | Author                              | Description  |
    | ------- | ---------- | ----------------------------------- | ------------ |
    | 1.0.0   | 2026-06-01 | Claude_Sonnet_4.6_Thinking_planning | 初始创建     |

    状态处理规则：
    - PUBLISHED / SEGMENTED / IGNORED / COMPLETED → 拒绝（终态，不可覆盖）
    - DOWNLOADING / TRANSCRIBING / COPYWRITING → kill 进程后更新
    - PUBLISHING / 视频号待确认账本 → 拒绝，避免中断后自动重传
    - PENDING / FAILED → 直接更新规格，重置 PENDING
    物理文件：通常不删除；但 TTS 音轨规格变化时，会失效竖版成片和封面，
    防止新版本继续复用原声版缓存。
    """
    video = db.get_video_by_youtube_id(youtube_id)
    if not video:
        return {"success": False, "error": "视频不存在"}

    status = video.get("status", "")

    submission_guard = _wechat_submission_guard_reason(video)
    if submission_guard:
        return {"success": False, "error": submission_guard, "current_status": status}

    # ── 1. 终态拒绝 ─────────────────────────────────────────────
    _TERMINAL_STATUSES = {"PUBLISHED", "UNDER_REVIEW", "SEGMENTED", "IGNORED", "COMPLETED"}
    if status in _TERMINAL_STATUSES:
        return {
            "success": False,
            "error": f"视频当前状态为 {status}，无法覆盖规格（终态保护）",
            "current_status": status,
        }

    # ── 2. 活跃状态：杀进程 ────────────────────────────────────
    was_stopped = False
    if status in ACTIVE_STATUSES:
        if not settings.enable_sigterm_kill:
            return {
                "success": False,
                "error": "进程强杀未启用（enable_sigterm_kill=False），无法中止活跃任务",
            }
        pid = video.get("process_pid")
        if pid:
            try:
                os.killpg(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
            time.sleep(2.0)
            try:
                os.killpg(pid, 0)              # 检查进程是否仍存活
                os.killpg(pid, signal.SIGKILL)  # 残存 → 强杀
                import logging as _log
                _log.getLogger(__name__).warning(
                    f"[SIGKILL] respec forced kill pid={pid} for {youtube_id}"
                )
            except (ProcessLookupError, PermissionError):
                pass  # 已自行退出，正常
        was_stopped = True

    # ── 3. 校验裁剪参数 ─────────────────────────────────────
    _time_re = re.compile(r"^[0-9:.]*$")
    trim_start = req.trim_start.strip() if req.trim_start else None
    trim_end   = req.trim_end.strip()   if req.trim_end   else None
    if trim_start and not _time_re.match(trim_start):
        return {"success": False, "error": "开始时间格式不合法，仅支持数字、冒号和点"}
    if trim_end and not _time_re.match(trim_end):
        return {"success": False, "error": "结束时间格式不合法，仅支持数字、冒号和点"}

    disable_slicing_val = 1 if req.disable_slicing else 0
    previous_tts_provider = str(video.get("tts_provider") or "").strip()
    requested_tts_provider = str(req.tts_provider or "").strip()
    invalidated_artifacts: list[str] = []
    if previous_tts_provider != requested_tts_provider:
        invalidated_artifacts = _invalidate_audio_variant_artifacts(youtube_id)

    # ── 4. 更新规格 ─────────────────────────────────────────────
    db.update_video_spec(
        youtube_id,
        trim_start=trim_start,
        trim_end=trim_end,
        disable_slicing=disable_slicing_val,
        tts_provider=req.tts_provider,
    )

    # ── 5. 重置状态并触发 ────────────────────────────────────────
    db.update_video_status(youtube_id, "PENDING", error_msg=None)

    triggered = False
    if db.claim_video_for_processing(youtube_id):
        fresh = db.get_video_by_youtube_id(youtube_id)
        if fresh:
            _trigger_video_async(fresh)
            triggered = True

    return {
        "success": True,
        "youtube_id": youtube_id,
        "title": video.get("title"),
        "trim_start": trim_start,
        "trim_end": trim_end,
        "disable_slicing": req.disable_slicing,
        "tts_provider": req.tts_provider,
        "was_stopped": was_stopped,
        "invalidated_artifacts": invalidated_artifacts,
        "triggered": triggered,
    }


@app.post("/api/videos/{youtube_id}/stop")
def stop_video(youtube_id: str, slice_index: Optional[int] = None):
    """
    停止仍可安全中止的任务；PUBLISHING 一律转入未绑定提交账本，禁止重发。

    # Modification History
    | Version | Date | Author | Description |
    | --- | --- | --- | --- |
    | 1.1.0 | 2026-08-21 | Codex | 发布中手动中止先记 SUBMITTED_UNBOUND；审核中不再误置 FAILED |
    | 1.0.0 | 2026-05-28 | Gemini_3.5_Flash_planning | 初始创建，实现 SIGTERM/SIGKILL 阶梯强杀与状态流转 |

    [Gemini_3.5_Flash_planning]:
    - 支持通过 slice_index 定向停止子切片或停止父视频及其所有切片。
    - 使用 SIGTERM -> wait 2s -> SIGKILL 强杀正在运行的进程组。
    - 预提交任务更新为 FAILED；PUBLISHING 先写未绑定提交账本再停止，绝不自动重传。
    """
    if slice_index is not None:
        targets = [db.get_video_by_youtube_id(youtube_id, slice_index=slice_index)]
    else:
        parent = db.get_video_by_youtube_id(youtube_id, slice_index=0)
        slices = db.get_slices_by_parent_yid(youtube_id)
        targets = ([parent] if parent else []) + slices

    targets = [t for t in targets if t]
    if not targets:
        return {"success": False, "error": "视频不存在"}

    # UNDER_REVIEW 没有可安全终止的本地提交动作；把它改为 FAILED 会使通用重试绕过平台核验。
    protected_targets = [
        t for t in targets
        if str(t.get("status") or "").upper() in {"UNDER_REVIEW", "SUBMITTED_UNBOUND", "SUBMITTED_BOUND", "UNCERTAIN"}
    ]
    if protected_targets:
        return {
            "success": False,
            "error": "相关视频号提交正在等待平台核验，禁止中止或改写为 FAILED。",
        }

    # 过滤出处于可中止处理阶段的任务；PUBLISHING 仍可停止，但会 fail-closed 落账。
    active_targets = [t for t in targets if t.get("status") in ACTIVE_STATUSES]
    if not active_targets:
        return {"success": False, "error": "相关视频/切片当前不处于运行状态"}

    if not settings.enable_sigterm_kill:
        return {"success": False, "error": "未启用进程强杀机制，无法强制停止任务"}

    publishing_targets = [t for t in active_targets if t.get("status") == "PUBLISHING"]
    if publishing_targets:
        reason = "用户在 PUBLISHING 阶段中止本地进程；平台可能已受理，已停止自动重传并等待核验。"
        try:
            for t in publishing_targets:
                db.record_wechat_publication_confirmation(
                    t["youtube_id"], evidence_path=None, state="SUBMITTED_UNBOUND",
                    error_message=reason, slice_index=t.get("slice_index", 0),
                )
                db.record_wechat_submission_attempt(
                    t["youtube_id"], evidence_path=None, final_title=t.get("title"),
                    slice_index=t.get("slice_index", 0),
                )
                db.cancel_queued_downstream_publications_for_unconfirmed_wechat(
                    t["youtube_id"], reason=reason, slice_index=t.get("slice_index", 0),
                )
        except Exception as exc:
            logger.exception("停止发布前无法写入视频号未确认账本")
            return {"success": False, "error": f"无法写入视频号未确认账本，拒绝中止：{exc}"}

    pids_to_kill = [t.get("process_pid") for t in active_targets if t.get("process_pid")]
    if pids_to_kill:
        for pid in pids_to_kill:
            try:
                os.killpg(pid, signal.SIGTERM)   # 优雅终止信号
            except (ProcessLookupError, PermissionError):
                pass
        
        time.sleep(2.0)                  # 等待 2 秒自退 [Gemini_3.5_Flash_planning]
        
        for pid in pids_to_kill:
            try:
                os.killpg(pid, 0)            # 检查进程是否仍存活
                os.killpg(pid, signal.SIGKILL)
                import logging as _logging
                _logging.getLogger(__name__).warning(
                    f"[SIGKILL] Process group {pid} did not exit after SIGTERM, force killed.")
            except (ProcessLookupError, PermissionError):
                pass

    # 仅预提交阶段可标记 FAILED；发布中被终止时平台状态未知，必须保持 fail-closed。
    for t in active_targets:
        if t.get("status") == "PUBLISHING":
            db.update_video_status(
                t["youtube_id"], "SUBMITTED_UNBOUND",
                error_msg="用户在 PUBLISHING 阶段中止；平台可能已受理，禁止自动重传。",
                slice_index=t.get("slice_index", 0),
            )
            continue
        db.update_video_status(
            t["youtube_id"],
            "FAILED",
            error_msg="用户手动停止",
            slice_index=t.get("slice_index", 0)
        )

    return {
        "success": True,
        "message": f"成功停止 {len(active_targets)} 个活跃任务；发布中任务已转未确认账本，其余已置为 FAILED"
    }


@app.post("/api/wechat/login")
def wechat_login(headless: bool = True):
    """
    启动微信登录。默认以无头模式运行并生成二维码图片以供前端扫码；
    也可以传递 headless=false 以便在本地有图形界面的机器上弹出浏览器。
    # [Gemini_2.0_Flash_fast]
    """
    started = _start_wechat_login_flow(headless=headless, preserve_marker=False, reason="manual login")
    if started.get("already_running"):
        started["message"] = "微信登录程序已在运行，请使用当前二维码扫码"
    return {
        **started,
        "message": (
            "无头登录程序已启动，正在获取二维码，请等待浮层刷新"
            if headless and not started.get("already_running")
            else ("已在本机启动浏览器，请在弹出窗口中扫码" if not headless and not started.get("already_running") else started["message"])
        ),
    }


@app.get("/api/wechat/qr")
def get_wechat_qr():
    """[Gemini_2.0_Flash_fast] 返回微信扫码登录的临时二维码图片"""
    prj_root = Path(__file__).parent.parent.parent
    qr_path = prj_root / "output" / "login_qr.png"
    if not qr_path.exists():
        raise HTTPException(status_code=404, detail="QR code not found")
    return FileResponse(
        str(qr_path),
        media_type="image/png",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/api/wechat/status")
def get_wechat_status():
    """[Gemini_2.0_Flash_fast] 获取当前微信登录状态与后台登录子进程状态"""
    prj_root = Path(__file__).parent.parent.parent
    state_path = prj_root / "output" / "wechat_state.json"
    login_at_path = prj_root / "output" / "wechat_login_at.txt"
    qr_path = prj_root / "output" / "login_qr.png"
    
    is_running = _is_wechat_login_running()
    login_marker_active = _wechat_login_marker_active(login_at_path)
    login_flow_active = is_running or qr_path.exists()
    
    return {
        "logged_in": state_path.exists() and login_marker_active,
        "state_exists": state_path.exists(),
        "login_marker_active": login_marker_active,
        "qr_exists": qr_path.exists(),
        "is_running": is_running,
        "login_flow_active": login_flow_active,
    }


def _is_wechat_login_running() -> bool:
    """判断是否已有 Web/TG 触发的微信登录进程在等待扫码，避免二维码互相覆盖。"""
    if _wechat_login_thread and _wechat_login_thread.is_alive():
        return True
    try:
        result = subprocess.run(
            ["ps", "-axo", "pid=,command="],
            cwd=str(Path(__file__).parent.parent.parent),
            capture_output=True,
            text=True,
            timeout=2,
        )
        return any(
            ".venv/bin/python" in line and "scripts/wechat_uploader.py" in line and "--login-only" in line
            for line in result.stdout.splitlines()
        )
    except Exception:
        return False


def _wechat_login_marker_active(login_at_path: Path, max_age_hours: int = 23) -> bool:
    """仅把真实扫码成功后写入且未超龄的标记视为登录有效。"""
    try:
        login_at = int(login_at_path.read_text().strip())
    except Exception:
        return False
    return (time.time() - login_at) < max_age_hours * 3600


def _is_pipeline_manager_running() -> bool:
    """[Gemini_3.5_Flash_planning] 通过尝试获取文件锁来非阻塞检测当前是否已有 pipeline_manager 正在运行"""
    lock_path = Path(__file__).parent.parent.parent / "output" / "pipeline.lock"
    if not lock_path.exists():
        return False
    try:
        with open(lock_path, "r") as f:
            try:
                # 尝试获取排他锁（非阻塞）
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                # 能够获取到锁，说明当前没有进程持有锁，释放并返回 False
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                return False
            except (BlockingIOError, OSError):
                # 无法获取锁，说明已被其他处理进程占用
                return True
    except Exception:
        return False


@app.post("/api/pipeline/run")
def run_full_pipeline():
    """触发完整管线：monitor_channels + pipeline_manager。等价于 vp job run，全程后台执行。"""
    def _run():
        prj_root = Path(__file__).parent.parent.parent
        python   = str(prj_root / ".venv" / "bin" / "python")
        src_dir  = str(prj_root / "src")
        log_path = prj_root / "output" / "pipeline.log"
        log_path.parent.mkdir(exist_ok=True)
        # BUG-5 修复：清除代理环境变量，防止代理未运行时 monitor_channels 失败
        _proxy = frozenset({'HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy'})
        env_clean = {k: v for k, v in os.environ.items() if k not in _proxy}

        import subprocess as sp
        with open(log_path, "a") as f:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"\n=== Web-triggered pipeline run ({now_str}) ===\n")
            # [Gemini_3.5_Flash_planning] 使用 -u 启用无缓冲输出
            sp.run([python, "-u", str(prj_root / "scripts" / "monitor_channels.py")],
                   cwd=str(prj_root), stdout=f, stderr=f, env=env_clean)
            
            # [Gemini_3.5_Flash_planning] 校验引擎排他锁以防并发阻塞导致进程堆积泄露
            if _is_pipeline_manager_running():
                f.write("[Scheduler] pipeline_manager is already running (pipeline.lock is held). Skipping duplicate run to prevent process leaks.\n")
                f.flush()
            else:
                sp.run([python, "-u", "-m", "video_processing.pipeline_manager"],
                       cwd=src_dir, stdout=f, stderr=f, env=env_clean)

    threading.Thread(target=_run, daemon=True, name="full-pipeline").start()
    return {"success": True, "message": "全量管线已在后台启动，请关注仪表盘进度"}



# ── 热词监控 API ─────────────────────────────────────────────────────────
@app.get("/api/trending-keywords")
def get_trending_keywords(force_refresh: bool = False):
    """[Claude_Sonnet_4.6_Thinking_planning] 返回当前动态热词列表及元数据

    响应结构:
      enabled: bool          — settings.enable_dynamic_keywords
      source: str            — 'cache' | 'live' | 'static'
      keywords: list[dict]   — 每条含 keyword/type/hn_score/signal/title/yt_url
      updated_at: float|None — 缓存 Unix 时间戳
      hn_top_n: int          — 从 HN 抓取的条数
    """
    import json as _json
    import time as _time

    prj_root = Path(__file__).parent.parent.parent
    scripts_dir = str(prj_root / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    # 静态兜底词
    STATIC_KWS = ["AI interview", "tech keynote 2026", "business podcast", "founder speech"]

    if not settings.enable_dynamic_keywords:
        return {
            "enabled": False,
            "source": "static",
            "keywords": [{"keyword": kw, "type": "static", "hn_score": None,
                          "signal": None, "title": None, "yt_url": None} for kw in STATIC_KWS],
            "updated_at": None,
            "hn_top_n": 0,
        }

    cache_path = prj_root / "output" / "trending_keywords.json"
    cache_age  = None
    cached_kws = []

    # 读缓存
    if cache_path.exists() and not force_refresh:
        try:
            data = _json.loads(cache_path.read_text(encoding="utf-8"))
            age  = _time.time() - data.get("updated_at", 0)
            if age < 3600:  # 1 小时内有效
                cached_kws  = data.get("keywords", [])
                cache_age   = data.get("updated_at")
        except Exception:
            pass

    source = "cache" if cached_kws else "live"

    # 需要实时拉取（无缓存 or 强制刷新）
    if not cached_kws or force_refresh:
        try:
            from fetch_trending_keywords import fetch_hn_trending_keywords
            top_n     = getattr(settings, "hn_top_n", 30)
            cached_kws = fetch_hn_trending_keywords(top_n=top_n)
            cache_age  = _time.time()
            cache_path.write_text(_json.dumps({
                "updated_at": cache_age,
                "keywords":   cached_kws,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            source = "live"
        except Exception as e:
            print(f"[HotwordsAPI] fetch failed: {e}")
            source = "error"

    # 静态词永远追加在后面
    dynamic_set = set(cached_kws)
    result_kws  = [
        {"keyword": kw, "type": "dynamic", "hn_score": None,
         "signal": None, "title": None,
         "yt_url": f"https://www.youtube.com/results?search_query={kw.replace(' ', '+')}"
         } for kw in cached_kws
    ] + [
        {"keyword": kw, "type": "static",  "hn_score": None,
         "signal": None, "title": None,
         "yt_url": f"https://www.youtube.com/results?search_query={kw.replace(' ', '+')}"
         } for kw in STATIC_KWS if kw not in dynamic_set
    ]

    return {
        "enabled":    True,
        "source":     source,
        "keywords":   result_kws,
        "updated_at": cache_age,
        "hn_top_n":   getattr(settings, "hn_top_n", 30),
    }


@app.post("/api/trending-keywords/refresh")
def refresh_trending_keywords():
    """[Claude_Sonnet_4.6_Thinking_planning] 强制刷新 HN 热词缓存（忽略 1h TTL）"""
    return get_trending_keywords(force_refresh=True)


# ── [Claude_Sonnet_4.6_Thinking_planning] v3.4.0: 高赞内容手动刷新 ──────────────
_high_likes_refresh_running = False  # 全局互斥锁，防止重复触发

@app.post("/api/high-likes/refresh")
def refresh_high_likes():
    """在后台线程中执行 discover_high_like_videos()，立即返回状态。

    discover_high_like_videos() 需要通过 yt-dlp 搜索多个关键词（约 1~3 分钟），
    因此采用异步触发而非同步阻塞，前端轮询或刷新 Tab 即可获取最新数据。
    """
    global _high_likes_refresh_running
    if _high_likes_refresh_running:
        return {"started": False, "message": "刷新任务已在进行中，请稍候..."}

    _high_likes_refresh_running = True  # 在启动线程前置位，避免竞态

    def _run():
        global _high_likes_refresh_running  # [Claude_Opus_4.6_Thinking_planning] P0修复：闭包必须声明global才能写入模块级变量
        try:
            import sys as _sys
            _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
            from monitor_channels import discover_high_like_videos  # [Claude_Sonnet_4.6_Thinking_planning]
            discover_high_like_videos(db)
        except Exception as e:
            import logging as _log
            _log.getLogger(__name__).error(f"[HighLikes] refresh failed: {e}")
        finally:
            _high_likes_refresh_running = False

    threading.Thread(target=_run, daemon=True, name="high-likes-refresh").start()
    return {"started": True, "message": "已在后台开始刷新，1~3 分钟后刷新页面查看结果"}


@app.get("/api/high-likes/status")
def high_likes_refresh_status():
    """查询高赞刷新任务是否正在运行"""
    return {"running": _high_likes_refresh_running}


@app.get("/demo", response_class=HTMLResponse)
def get_interactive_demo():
    """[Gemini_3.5_Flash_planning] 返回交互式财经英文原声精读体验页 (Anduchencang Demo)"""
    from web.study_demo_html import HTML_CONTENT
    return HTML_CONTENT


if __name__ == "__main__":
    import uvicorn
    # 端口选择规则：见 PORTS.md
    # 9100-9199 为本项目专属区间，避开 :8080（其他项目）等。端口为单一真相源 settings.dashboard_port，
    # 可经环境变量 DASHBOARD_PORT 覆盖（见 src/config/settings.py）。
    port = settings.dashboard_port
    print(f"\n\U0001f680 Video Pipeline Control Center → http://localhost:{port}\n")
    uvicorn.run(app, host="0.0.0.0", port=port, reload=False)
