"""Web 控制中心后端 — FastAPI 仪表盘服务

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-05-21 | Claude_Sonnet_4.6_Thinking_planning | 初始创建 Dashboard API 服务 |
"""
import os
import sys
from pathlib import Path
from datetime import datetime

# 确保能导入 src 下的模块
_src = str(Path(__file__).parent.parent)
if _src not in sys.path:
    sys.path.insert(0, _src)

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

from video_processing.db.database import PipelineDB

app = FastAPI(title="Video Pipeline Control Center", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# 使用全局 DB 实例（只读查询，线程安全）
db = PipelineDB()

# 所有处于"活跃"加工中的状态
ACTIVE_STATUSES = {"DOWNLOADING", "TRANSCRIBING", "COPYWRITING", "PUBLISHING"}

# FSM 状态的显示顺序（用于排序和进度展示）
STATUS_ORDER = [
    "PENDING", "DOWNLOADING", "TRANSCRIBING",
    "COPYWRITING", "PUBLISHING", "PUBLISHED", "FAILED", "LOGIN_REQUIRED"
]


@app.get("/", response_class=HTMLResponse)
def dashboard():
    """返回仪表盘 HTML 页面"""
    template_path = Path(__file__).parent / "templates" / "index.html"
    return HTMLResponse(content=template_path.read_text(encoding="utf-8"))


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
        videos = db.get_videos_by_status(status)
        active.extend(videos)
    # 按 updated_at 倒序
    active.sort(key=lambda v: v.get("updated_at", ""), reverse=True)
    return {"queue": active, "count": len(active)}


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


@app.get("/api/activity")
def get_activity():
    """返回最近 20 条视频动态（活动流）"""
    videos = db.get_recent_videos(limit=20)
    return {"activity": videos, "count": len(videos)}


if __name__ == "__main__":
    import uvicorn
    # [Claude_Sonnet_4.6_Thinking_planning] 端口选择规则：见 PORTS.md
    # 8765 是本项目专属端口，避免与 OptionSense(8000) 等其他项目冲突
    port = int(os.environ.get("DASHBOARD_PORT", 8765))
    print(f"\n\U0001f680 Video Pipeline Control Center \u2192 http://localhost:{port}\n")
    uvicorn.run(app, host="0.0.0.0", port=port, reload=False)
