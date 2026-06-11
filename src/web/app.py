"""Web 控制中心后端 — FastAPI 仪表盘服务

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
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
"""
import os
import re  # [Gemini_3.5_Flash_planning] 统一导入正则模块
import sys
import signal
import time
import shutil
import subprocess
import threading
from pathlib import Path
from datetime import datetime
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
from config.settings import settings  # [Claude_Sonnet_4.6_Thinking_planning] v7.0: 模块顶层导入，避免函数体内重复 import
from video_processing.utils.translation_helper import translate_text as _translate_text  # [Claude_Sonnet_4.6_planning] 统一翻译入口

app = FastAPI(title="Video Pipeline Control Center", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

# 使用全局 DB 实例（每次方法调用内部创建新连接，线程安全）
db = PipelineDB()

def _translate_title_task(youtube_id: str, english_title: str):
    """后台任务：调用翻译接口（阿里云 MT 优先）翻译标题并更新数据库。

    [Claude_Sonnet_4.6_planning] 改用 translation_helper.translate_text，
    使标题翻译与字幕翻译共享相同的阿里云 MT 优先策略。
    """
    try:
        zh_title = _translate_text(english_title, src_lang="auto", target_lang="zh-CN")
        if zh_title and zh_title != english_title:
            with db.get_connection() as conn:
                conn.execute(
                    "UPDATE processed_videos SET zh_title = ? WHERE youtube_id = ?",
                    (zh_title, youtube_id)
                )
                conn.commit()
            print(f"[Translator] {youtube_id} translated: {zh_title}")
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

def _auto_pipeline_loop():
    """后台循环任务：启动后延迟10秒执行首次管线，之后每4小时执行一次"""
    import time
    time.sleep(10)
    while True:
        try:
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
            # [Claude_Sonnet_4.6_Thinking_planning] v3.1.0: 每轮先清理卡在非终态的任务
            # 将卡在 DOWNLOADING/PROCESSING 超过 2 小时的死锁任务重置回 PENDING
            # 这解决了历史任务卡死后永久占用队列、幹操新任务调度的问题
            purged = db.purge_stale_tasks(stale_hours=2)
            if purged > 0:
                import logging
                logging.getLogger(__name__).info(
                    f"[Scheduler] Purged {purged} stale task(s) back to PENDING"
                )

            # 1. 检查是否有 >=75 的 PENDING 视频
            pending_videos = db.get_high_score_pending_videos(min_score=75, limit=1)
            if pending_videos:
                # 2. 检查当前是否有活跃的 pipeline 线程正在运行
                active_threads = threading.enumerate()
                is_pipeline_running = any(
                    t.name in ("full-pipeline", "queue-pipeline") or t.name.startswith("pipeline-")
                    for t in active_threads
                )

                if not is_pipeline_running:
                    print(f"[Scheduler] Found pending high-score video {pending_videos[0]['youtube_id']}, auto-triggering queue pipeline...")
                    threading.Thread(target=_run_pipeline_manager, daemon=True, name="queue-pipeline").start()
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"[Scheduler] Queue runner loop error: {e}")
        time.sleep(15)


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


# 所有处于"活跃"加工中的状态
ACTIVE_STATUSES = {"DOWNLOADING", "TRANSCRIBING", "COPYWRITING", "PUBLISHING"}

# FSM 状态的显示顺序
STATUS_ORDER = [
    "PENDING", "DOWNLOADING", "TRANSCRIBING",
    "COPYWRITING", "PUBLISHING", "PUBLISHED", "FAILED", "LOGIN_REQUIRED"
]


# ── Pydantic 请求体 ──────────────────────────────────────────────────────
class AddChannelRequest(BaseModel):
    url: str
    promote: Optional[bool] = False


class BatchDeleteRequest(BaseModel):  # [Gemini_2.5_Pro_planning]
    youtube_ids: list[str]
    delete_files: bool = False


_OUT_DIR = Path(__file__).parent.parent.parent / "output"


# ── 页面路由 ─────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def dashboard():
    """返回仪表盘 HTML 页面"""
    template_path = Path(__file__).parent / "templates" / "index.html"
    return HTMLResponse(content=template_path.read_text(encoding="utf-8"))


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
    active = sum(v for k, v in counts.items() if k in ACTIVE_STATUSES)
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


@app.get("/api/videos")
def get_videos(tab: str = "waitlist", page: int = 1, size: int = 20):
    """返回分页和分类后的视频列表，以及各个 Tab 的计数"""
    page = max(1, page)
    size = max(1, min(100, size))
    videos, total_count = db.get_paginated_videos(tab, page, size)
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
    return {"slices": slices}


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
                "--cookies-from-browser", "safari",
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
                "--cookies-from-browser", "safari",
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
    }



# ── 优先级调整 API ────────────────────────────────────────────────────────
class PriorityRequest(BaseModel):
    action: str          # "increase" | "decrease" | "set"
    value: Optional[int] = None   # 仅 action="set" 时使用


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


@app.patch("/api/videos/{youtube_id}/priority")
def update_video_priority(youtube_id: str, req: PriorityRequest):
    """
    调整视频优先级（即 score 字段）。
    若调整后 score >= 75 且视频仍是 PENDING，立即在后台启动处理管线。
    """
    video = db.get_video_by_youtube_id(youtube_id)
    if not video:
        return {"success": False, "error": "视频不存在"}

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
    if not is_discovery and new_score >= 75 and db.claim_video_for_processing(youtube_id):
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


@app.post("/api/videos/{youtube_id}/retry")
def retry_video(youtube_id: str):
    """
    重试/强制重置视频状态为 PENDING。
    - FAILED / LOGIN_REQUIRED：正常重试，清除错误信息
    - DOWNLOADING/TRANSCRIBING/COPYWRITING/PUBLISHING：服务器重启后卡死的任务，强制重置
    若当前分数 >= 75，重置后立即自动重新触发。
    """
    video = db.get_video_by_youtube_id(youtube_id)
    if not video:
        return {"success": False, "error": "视频不存在"}

    retryable = {"FAILED", "LOGIN_REQUIRED", "DOWNLOADING", "TRANSCRIBING", "COPYWRITING", "PUBLISHING"}
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


@app.post("/api/videos/{youtube_id}/slices/{slice_index}/retry")
def retry_slice(youtube_id: str, slice_index: int):
    """[Gemini_3.5_Flash_High_planning] 针对单个切片子任务执行重置与重试"""
    video = db.get_video_by_youtube_id(youtube_id, slice_index=slice_index)
    if not video:
        raise HTTPException(status_code=404, detail="切片任务不存在")

    retryable = {"FAILED", "LOGIN_REQUIRED", "DOWNLOADING", "TRANSCRIBING", "COPYWRITING", "PUBLISHING"}
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
    """
    # 获取待筛选列表所有 ID（不分页，全量）
    with db.get_connection() as conn:
        cursor = conn.execute(
            "SELECT youtube_id FROM processed_videos WHERE status = 'PENDING' AND score < 75"
        )
        all_ids = [row["youtube_id"] for row in cursor.fetchall()]

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
    for yid in req.youtube_ids:
        parent = db.get_video_by_youtube_id(yid, slice_index=0)
        slices = db.get_slices_by_parent_yid(yid)
        targets = ([parent] if parent else []) + slices
        if any(t.get("status") in ACTIVE_STATUSES for t in targets):
            active_ids.append(yid)

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
    - DOWNLOADING / TRANSCRIBING / COPYWRITING / PUBLISHING → kill 进程后更新
    - PENDING / FAILED → 直接更新规格，重置 PENDING
    物理文件：不删除。pipeline_manager 将检测现有文件并以新 trim 参数重新处理。
    """
    video = db.get_video_by_youtube_id(youtube_id)
    if not video:
        return {"success": False, "error": "视频不存在"}

    status = video.get("status", "")

    # ── 1. 终态拒绝 ─────────────────────────────────────────────
    _TERMINAL_STATUSES = {"PUBLISHED", "SEGMENTED", "IGNORED", "COMPLETED"}
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
        "triggered": triggered,
    }


@app.post("/api/videos/{youtube_id}/stop")
def stop_video(youtube_id: str, slice_index: Optional[int] = None):
    """
    停止正在运行的任务进程，并将数据库中的状态置为 FAILED (用户手动停止)。

    # Modification History
    | Version | Date | Author | Description |
    | --- | --- | --- | --- |
    | 1.0.0 | 2026-05-28 | Gemini_3.5_Flash_planning | 初始创建，实现 SIGTERM/SIGKILL 阶梯强杀与状态流转 |

    [Gemini_3.5_Flash_planning]:
    - 支持通过 slice_index 定向停止子切片或停止父视频及其所有切片。
    - 使用 SIGTERM -> wait 2s -> SIGKILL 强杀正在运行的进程组。
    - 将相关任务在数据库中的状态更新为 FAILED，并记录 error_msg 为 "用户手动停止"。
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

    # 过滤出处于活跃状态的任务 [Gemini_3.5_Flash_planning]
    active_targets = [t for t in targets if t.get("status") in ACTIVE_STATUSES]
    if not active_targets:
        return {"success": False, "error": "相关视频/切片当前不处于运行状态"}

    if not settings.enable_sigterm_kill:
        return {"success": False, "error": "未启用进程强杀机制，无法强制停止任务"}

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

    # 将数据库状态更新为 FAILED 并设置错误信息
    for t in active_targets:
        db.update_video_status(
            t["youtube_id"],
            "FAILED",
            error_msg="用户手动停止",
            slice_index=t.get("slice_index", 0)
        )

    return {
        "success": True,
        "message": f"成功停止 {len(active_targets)} 个活跃任务，状态已置为 FAILED"
    }


@app.post("/api/wechat/login")
def wechat_login(headless: bool = True):
    """
    启动微信登录。默认以无头模式运行并生成二维码图片以供前端扫码；
    也可以传递 headless=false 以便在本地有图形界面的机器上弹出浏览器。
    # [Gemini_2.0_Flash_fast]
    """
    prj_root = Path(__file__).parent.parent.parent
    python   = str(prj_root / ".venv" / "bin" / "python")
    script   = str(prj_root / "scripts" / "wechat_uploader.py")
    state    = str(prj_root / "output" / "wechat_state.json")

    # 启动前先清理可能存在的旧二维码
    qr_path = prj_root / "output" / "login_qr.png"
    if qr_path.exists():
        try:
            os.remove(qr_path)
        except Exception:
            pass

    args = [python, script, "--login-only", "--state", state]
    if not headless:
        args.append("--no-headless")

    def _run():
        try:
            subprocess.run(args, cwd=str(prj_root))
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"WeChat login subprocess failed: {e}")

    threading.Thread(target=_run, daemon=True, name="wechat-login").start()
    return {
        "success": True, 
        "message": "无头登录程序已启动，正在获取二维码，请等待浮层刷新" if headless else "已在本机启动浏览器，请在弹出窗口中扫码"
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
    qr_path = prj_root / "output" / "login_qr.png"
    
    is_running = any(t.name == "wechat-login" for t in threading.enumerate())
    
    return {
        "logged_in": state_path.exists(),
        "qr_exists": qr_path.exists(),
        "is_running": is_running,
    }


def _is_pipeline_manager_running() -> bool:
    """[Gemini_3.5_Flash_planning] 通过尝试获取文件锁来非阻塞检测当前是否已有 pipeline_manager 正在运行"""
    lock_path = Path(__file__).parent.parent.parent / "output" / "pipeline.lock"
    if not lock_path.exists():
        return False
    try:
        with open(lock_path, "r") as f:
            import fcntl
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


if __name__ == "__main__":
    import uvicorn
    # 端口选择规则：见 PORTS.md
    # 8765 是本项目专属端口，避免与 OptionSense(8000) 等其他项目冲突
    port = int(os.environ.get("DASHBOARD_PORT", 8765))
    print(f"\n\U0001f680 Video Pipeline Control Center → http://localhost:{port}\n")
    uvicorn.run(app, host="0.0.0.0", port=port, reload=False)
