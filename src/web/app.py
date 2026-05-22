"""Web 控制中心后端 — FastAPI 仪表盘服务

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-05-21 | Claude_Sonnet_4.6_Thinking_planning | 初始创建 Dashboard API 服务 |
| 1.1.0 | 2026-05-21 | Claude_Sonnet_4.6_Thinking_planning | 新增频道管理 API：add/delete，yt-dlp 验证后入库 |
| 1.2.0 | 2026-05-22 | Gemini_3.5_Flash_fast | 修复手工添加视频（含 TG Bot 提交）卡在 PENDING 不自动触发的问题 |
"""
import os
import sys
import shutil
import subprocess
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional

# 确保能导入 src 下的模块
_src = str(Path(__file__).parent.parent)
if _src not in sys.path:
    sys.path.insert(0, _src)

from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from video_processing.db.database import PipelineDB

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
    """FastAPI 启动时自动运行后台调度器"""
    import threading
    threading.Thread(target=_auto_pipeline_loop, daemon=True, name="auto-pipeline-scheduler").start()
    print("[Scheduler] Background pipeline scheduler started.")

# 优先用 PATH 里的 yt-dlp，其次用 venv 里的
_YT_DLP = shutil.which("yt-dlp") or str(
    Path(__file__).parent.parent.parent / ".venv" / "bin" / "yt-dlp"
)

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


# ── 页面路由 ─────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def dashboard():
    """返回仪表盘 HTML 页面"""
    template_path = Path(__file__).parent / "templates" / "index.html"
    return HTMLResponse(content=template_path.read_text(encoding="utf-8"))


# ── 统计 API ─────────────────────────────────────────────────────────────
@app.get("/api/stats")
def get_stats():
    """返回各状态视频数量，用于顶部统计卡片"""
    counts = db.get_status_counts()
    total = sum(counts.values())
    active = sum(v for k, v in counts.items() if k in ACTIVE_STATUSES)
    return {
        "total": total,
        "pending": counts.get("PENDING", 0),
        "active": active,
        "published": counts.get("PUBLISHED", 0),
        "failed": counts.get("FAILED", 0) + counts.get("LOGIN_REQUIRED", 0),
        "breakdown": {s: counts.get(s, 0) for s in STATUS_ORDER},
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
    if not any(d in url for d in ("youtube.com", "youtu.be")):
        return {
            "success": False,
            "error": "请输入有效的 YouTube 频道 URL（需包含 youtube.com 或 youtu.be）"
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
    existing = db.get_channel_by_id(channel_id)
    if existing and existing.get("status") == "APPROVED":
        return {
            "success": False,
            "error": f"该频道已在白名单中：{existing['channel_name']}（{channel_id}）",
            "already_exists": True,
        }

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


@app.post("/api/videos/add")
def add_video_manual(req: AddVideoRequest, bg_tasks: BackgroundTasks):
    """
    手动将一条 YouTube 视频链接加入处理队列（状态：PENDING）。

    验证链：
      1. URL 必须是 YouTube 域名
      2. yt-dlp 获取 video_id / title / channel_id / channel_name / duration / views / likes / upload_date
      3. 重复检测：已存在则返回当前状态，不重复写入
      4. 通过 DAL 写入 processed_videos，评分 100（手工加急），触发异步翻译
    """
    url = req.url.strip()
    if not url:
        return {"success": False, "error": "URL 不能为空"}

    # ── 1. 前置 URL 格式校验 ─────────────────────────────────────────
    if not any(d in url for d in ("youtube.com", "youtu.be")):
        return {"success": False, "error": "请输入有效的 YouTube 视频 URL"}

    # ── 2. yt-dlp 获取视频元数据 ─────────────────────────────────────
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

    # ── 3. 重复检测 ───────────────────────────────────────────────────
    existing = db.get_video_by_youtube_id(video_id)
    if existing:
        return {
            "success": False,
            "error": f"视频已在队列中（当前状态：{existing['status']}）：{existing['title']}",
            "already_exists": True,
            "current_status": existing["status"],
        }

    # ── 4. 写入队列（手工添加） ───────────────────────────────────────
    if not db.get_channel_by_id(channel_id):
        db.add_channel(channel_id, channel_name,
                       status="APPROVED", reason="Auto-registered via manual video add")

    # 手工添加给100分加急
    db.add_video(
        video_id, title, channel_id, score=100, source="MANUAL",
        duration_sec=duration_sec, view_count=view_count,
        like_count=like_count, upload_date=upload_date,
    )
    bg_tasks.add_task(_translate_title_task, video_id, title)
    
    return {
        "success": True,
        "video_id": video_id,
        "title": title,
        "channel_name": channel_name,
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

    db.update_video_score(youtube_id, new_score)

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


@app.delete("/api/videos/{youtube_id}")
def delete_video(youtube_id: str, delete_files: bool = False):
    """
    物理删除任务记录。
    如果 delete_files=True，同时删除相关的本地产物文件。
    注意：物理删除后，如果原视频仍在频道的最新列表中，监控爬虫可能会重新将其加入队列。
    """
    video = db.get_video_by_youtube_id(youtube_id)
    if not video:
        return {"success": False, "error": "视频不存在"}

    if video.get("status") in ACTIVE_STATUSES:
        return {"success": False, "error": f"安全拦截：视频正处于执行状态（{video['status']}），无法强制物理删除，请等待其执行结束或变为 FAILED。"}

    deleted_files = []
    if delete_files:
        from video_processing.pipeline_manager import PipelineManager
        pm = PipelineManager()
        deleted_files = pm.reset_video_artifacts(youtube_id)

    db.delete_video_record(youtube_id)

    msg = "已彻底清除该任务记录"
    if delete_files:
        msg += f"，并清理了 {len(deleted_files)} 个关联产物文件"

    return {
        "success": True,
        "deleted_files": deleted_files,
        "message": msg,
    }


@app.post("/api/wechat/login")
def wechat_login():
    """
    在本机弹出可见浏览器窗口，引导用户扫码登录微信视频号。
    登录成功后 Playwright 自动保存 Session 到 output/wechat_state.json。
    此接口立即返回（后台线程执行），前端通过 Toast 提示用户扫码。
    """
    prj_root = Path(__file__).parent.parent.parent
    python   = str(prj_root / ".venv" / "bin" / "python")
    script   = str(prj_root / "scripts" / "wechat_uploader.py")
    state    = str(prj_root / "output" / "wechat_state.json")

    def _run():
        try:
            # 注意：不使用 capture_output，GUI 浏览器窗口需要真实 display
            subprocess.run(
                [python, script, "--login-only", "--no-headless", "--state", state],
                cwd=str(prj_root),
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"WeChat login subprocess failed: {e}")

    threading.Thread(target=_run, daemon=True, name="wechat-login").start()
    return {"success": True, "message": "浏览器已在后台启动，请在弹出窗口中扫码"}


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
