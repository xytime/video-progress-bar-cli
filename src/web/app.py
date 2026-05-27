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
    """后台任务：调用 deep-translator 翻译标题并更新数据库"""
    try:
        from deep_translator import GoogleTranslator
        zh_title = GoogleTranslator(source='auto', target='zh-CN').translate(english_title)
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

@app.on_event("startup")
def startup_event():
    """FastAPI 启动时自动运行后台调度器，并在主线程注册信号处理器。

    [Claude_Sonnet_4.6_Thinking_planning] BUG-1 修复：signal.signal() 只能在主线程调用。
    _process_single_video 经由 daemon 线程执行，无法在内部注册信号。
    将 SIGTERM handler 注册移至此处（FastAPI startup 在主线程运行）。
    """
    # [Claude_Sonnet_4.6_Thinking_planning] BUG-1: 在主线程注册 SIGTERM handler
    if settings.enable_sigterm_kill:
        from video_processing import pipeline_manager as _pm
        signal.signal(signal.SIGTERM, _pm._sigterm_handler)

    import threading
    threading.Thread(target=_auto_pipeline_loop, daemon=True, name="auto-pipeline-scheduler").start()
    print("[Scheduler] Background pipeline scheduler started.")

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
                sp.run([python, "-c", inline], input=video_json, text=True,
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
    if new_score == 0 and settings.enable_blacklist_tombstone:
        db.add_to_blacklist(youtube_id, reason="manually_scored_zero")  # LINT-3: 去除多余 f-string
        db.delete_video_record(youtube_id)
        return {"success": True, "youtube_id": youtube_id, "score": 0,
                "triggered": False, "blacklisted": True,
                "message": "已打 0 分并移入黑名单，该视频不会被自动爬虫再次拉取"}

    # 自动触发：score 越过调度线，且抢占成功（原状态为 PENDING）
    triggered = False
    if new_score >= 75 and db.claim_video_for_processing(youtube_id):
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
    """[Gemini_2.5_Pro_planning] 批量删除视频记录并写入黑名单墓碑。

    不支持删除正处于活跃状态的视频（ACTIVE_STATUSES）——需先停止进程再删除。
    """
    if not req.youtube_ids:
        return {"success": False, "error": "请提供要删除的视频 ID 列表"}

    # 安全校验：拒绝删除活跃任务
    invalid = [yid for yid in req.youtube_ids if not re.match(r'^[A-Za-z0-9_\-]+$', yid)]
    if invalid:
        return {"success": False, "error": f"非法 ID: {invalid}"}

    active_ids = [
        yid for yid in req.youtube_ids
        if (v := db.get_video_by_youtube_id(yid)) and v.get("status") in ACTIVE_STATUSES
    ]
    if active_ids:
        return {
            "success": False,
            "error": f"以下视频正在处理中，无法批量删除：{active_ids}",
        }

    # 可选删除产物文件
    deleted_files_total: list[str] = []
    if req.delete_files:
        from video_processing.pipeline_manager import PipelineManager
        pm = PipelineManager()
        for yid in req.youtube_ids:
            deleted_files_total.extend(pm.reset_video_artifacts(yid))

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

    [Gemini_3.5_Flash_High_planning] 升级：
    - 支持通过 slice_index 参数定向物理删除子任务。
    - 如果视频处于活跃状态且 settings.enable_sigterm_kill=True，
      会向其进程组发 SIGTERM 优雅终止，超时 2s 后强杀。
    - 删除后（若是父视频）将 youtube_id 写入 blacklisted_videos 墓碑表，
      防止爬虫二次拉取。
    """
    video = db.get_video_by_youtube_id(youtube_id, slice_index=slice_index or 0)
    if not video:
        return {"success": False, "error": "视频不存在"}

    # ── 1. 处理活跃任务：SIGTERM 阶梯强杀 ───────────────────────
    if video.get("status") in ACTIVE_STATUSES:
        if not settings.enable_sigterm_kill:
            # Flag 未开启：保持原有行为，拒绝删除活跃任务
            return {"success": False,
                    "error": f"安全拦截：视频正处于执行状态（{video['status']}）。"
                             "请等待完成或变为 FAILED。"}

        # Flag 开启：SIGTERM 阶梯强杀
        pid = video.get("process_pid")
        if pid:
            try:
                os.killpg(pid, signal.SIGTERM)   # 优雅终止信号
                time.sleep(2.0)                  # 等待 2 秒自退（time 已顶层导入）
                try:
                    os.killpg(pid, 0)            # 检查进程是否仍存活
                    os.killpg(pid, signal.SIGKILL)
                    import logging as _logging   # 局部别名，避免覆盖模块级 logger
                    _logging.getLogger(__name__).warning(
                        f"[SIGKILL] Process group {pid} did not exit after SIGTERM, force killed.")
                except (ProcessLookupError, PermissionError):
                    pass  # 进程已自退或在 macOS 下已变为僵尸进程，视为正常退出
            except ProcessLookupError:
                pass  # PID 已不存在（进程组消亡）
            except PermissionError as e:
                import logging as _logging
                _logging.getLogger(__name__).error(f"[SIGTERM] Permission error killing pid {pid}: {e}")

    # ── 2. 删除产物文件 ─────────────────────────────────────────
    deleted_files = []
    if delete_files:
        from video_processing.pipeline_manager import PipelineManager
        pm = PipelineManager()
        prefix = f"{youtube_id}_s{slice_index}" if (slice_index and slice_index > 0) else youtube_id
        deleted_files = pm.reset_video_artifacts(prefix)

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
            f.write("\n=== Web-triggered pipeline run ===\n")
            sp.run([python, str(prj_root / "scripts" / "monitor_channels.py")],
                   cwd=str(prj_root), stdout=f, stderr=f, env=env_clean)
            sp.run([python, "-m", "video_processing.pipeline_manager"],
                   cwd=src_dir, stdout=f, stderr=f, env=env_clean)

    threading.Thread(target=_run, daemon=True, name="full-pipeline").start()
    return {"success": True, "message": "全量管线已在后台启动，请关注仪表盘进度"}



if __name__ == "__main__":
    import uvicorn
    # 端口选择规则：见 PORTS.md
    # 8765 是本项目专属端口，避免与 OptionSense(8000) 等其他项目冲突
    port = int(os.environ.get("DASHBOARD_PORT", 8765))
    print(f"\n\U0001f680 Video Pipeline Control Center → http://localhost:{port}\n")
    uvicorn.run(app, host="0.0.0.0", port=port, reload=False)
