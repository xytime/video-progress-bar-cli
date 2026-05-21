"""Web 控制中心后端 — FastAPI 仪表盘服务

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-05-21 | Claude_Sonnet_4.6_Thinking_planning | 初始创建 Dashboard API 服务 |
| 1.1.0 | 2026-05-21 | Claude_Sonnet_4.6_Thinking_planning | 新增频道管理 API：add/delete，yt-dlp 验证后入库 |
"""
import os
import sys
import shutil
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional

# 确保能导入 src 下的模块
_src = str(Path(__file__).parent.parent)
if _src not in sys.path:
    sys.path.insert(0, _src)

from fastapi import FastAPI
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


@app.get("/api/queue")
def get_queue():
    """返回当前活跃的任务队列（处理中的视频）"""
    active = []
    for status in ACTIVE_STATUSES:
        active.extend(db.get_videos_by_status(status))
    active.sort(key=lambda v: v.get("updated_at", ""), reverse=True)
    return {"queue": active, "count": len(active)}


@app.get("/api/activity")
def get_activity():
    """返回最近 20 条视频动态（活动流）"""
    videos = db.get_recent_videos(limit=20)
    return {"activity": videos, "count": len(videos)}


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
    通过 yt-dlp 验证 YouTube 频道 URL，验证通过后写入白名单。
    防止手写错误 Channel ID 的根本解法。
    """
    url = req.url.strip()
    if not url:
        return {"success": False, "error": "URL 不能为空"}

    try:
        result = subprocess.run(
            [
                _YT_DLP,
                "--print", "%(channel_id)s|%(channel)s",
                "--playlist-items", "1",
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

    # yt-dlp 对"格式不可用"会打印 ERROR 但仍能输出频道信息，
    # 只有 stdout 为空才是真正的频道不存在
    line = result.stdout.strip().split("\n")[0] if result.stdout.strip() else ""
    if not line or "|" not in line:
        err = result.stderr.strip().split("\n")[0] if result.stderr.strip() else "无法解析频道信息"
        return {"success": False, "error": err}

    channel_id, channel_name = line.split("|", 1)
    if not channel_id:
        return {"success": False, "error": "未能解析到频道 ID"}

    db.add_channel(channel_id, channel_name.strip(),
                   status="APPROVED", reason="Added via Web UI")
    return {
        "success": True,
        "channel_id": channel_id,
        "channel_name": channel_name.strip(),
    }


@app.delete("/api/channels/{channel_id}")
def remove_channel(channel_id: str):
    """从白名单中删除一个频道"""
    ok = db.delete_channel(channel_id)
    return {"success": ok}


if __name__ == "__main__":
    import uvicorn
    # 端口选择规则：见 PORTS.md
    # 8765 是本项目专属端口，避免与 OptionSense(8000) 等其他项目冲突
    port = int(os.environ.get("DASHBOARD_PORT", 8765))
    print(f"\n\U0001f680 Video Pipeline Control Center → http://localhost:{port}\n")
    uvicorn.run(app, host="0.0.0.0", port=port, reload=False)
