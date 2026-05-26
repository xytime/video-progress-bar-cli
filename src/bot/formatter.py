"""src/bot/formatter.py — Telegram 消息格式化模块

高内聚：只负责将数据结构渲染为 Markdown 字符串，不依赖任何外部 I/O。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-05-22 | Claude_Sonnet_4.6_Thinking_planning | 初始创建，TDD Green phase |
| 1.1.0 | 2026-05-26 | Gemini_3.5_Flash                    | [v7.0 status] 新增 fmt_status_report 全局宏观状态渲染支持 |
"""
from __future__ import annotations
from typing import List


# 状态 → Emoji 映射
_STATUS_EMOJI: dict[str, str] = {
    "PENDING":      "⏳",
    "DOWNLOADING":  "⬇️",
    "TRANSCRIBING": "🎙",
    "COPYWRITING":  "✍️",
    "PUBLISHING":   "🚀",
    "PUBLISHED":    "✅",
    "FAILED":       "❌",
    "LOGIN_REQUIRED": "🔐",
}


def _status_icon(status: str) -> str:
    return _STATUS_EMOJI.get(status, "❓")


def fmt_video_added(title: str, video_id: str) -> str:
    """视频成功加入加急队列"""
    return (
        f"✅ *已加入加急队列！*\n"
        f"📌 标题：`{title}`\n"
        f"🆔 ID：`{video_id}`\n"
        f"_管线将自动处理：下载 → 字幕 → 翻译 → 发布_"
    )


def fmt_video_exists(title: str, status: str) -> str:
    """视频已在队列中"""
    icon = _status_icon(status)
    return (
        f"ℹ️ *视频已在队列中*\n"
        f"📌 标题：`{title}`\n"
        f"📊 当前状态：{icon} `{status}`"
    )


def fmt_queue(videos: List[dict]) -> str:
    """渲染处理队列列表"""
    if not videos:
        return "📭 队列为空，当前没有正在处理或等待的视频。"

    lines = ["📋 *当前处理队列*\n"]
    for v in videos:
        icon = _status_icon(v.get("status", ""))
        vid = v.get("youtube_id", "?")
        title = v.get("title", "未知标题")[:30]
        status = v.get("status", "?")
        lines.append(f"{icon} `{vid}` — {title}\n   状态：`{status}`")

    return "\n".join(lines)


def fmt_published(videos: List[dict]) -> str:
    """渲染最近发布的视频列表"""
    if not videos:
        return "📭 暂无已发布视频。"

    lines = ["✅ *最近发布到视频号*\n"]
    for v in videos:
        vid = v.get("youtube_id", "?")
        title = v.get("title", "未知标题")[:30]
        lines.append(f"✅ `{vid}` — {title}")

    return "\n".join(lines)


def fmt_delete_success(youtube_id: str) -> str:
    """视频删除成功"""
    return f"🗑 *已彻底删除*\n🆔 ID：`{youtube_id}`\n_记录与所有产物文件已清除。_"


def fmt_error(reason: str) -> str:
    """通用错误回复"""
    return f"❌ *操作失败*\n原因：{reason}"


def fmt_api_unavailable() -> str:
    """FastAPI 断线降级回复"""
    return (
        "⚠️ *控制中心暂时不可用*\n"
        "无法连接到本地 API 服务（localhost:8765）。\n"
        "_请确认 `vp ui start` 已启动，然后重试。_"
    )


def fmt_help() -> str:
    """帮助信息，列出所有命令"""
    return (
        "🤖 *微信视频号 Bot 使用指南*\n\n"
        "📩 *发送 YouTube 链接* → 自动加入加急队列\n\n"
        "📋 `/queue` — 查看当前处理队列\n"
        "📊 `/status` — 查看全局宏观状态报告\n"
        "✅ `/published` — 查看最近发布到视频号的视频\n"
        "🗑 `/delete <ID>` — 删除指定视频任务\n"
        "♻️ `/retry <ID>` — 重试失败的视频任务\n"
        "🏃 `/run` — 立即触发一次全量管线\n"
        "📊 `/stats` — 查看系统统计数据\n"
        "❓ `/help` — 显示本帮助"
    )


def fmt_status_report(stats: dict, processing: List[dict], pending: List[dict]) -> str:
    """渲染宏观的全局状态报告
    
    # [Gemini_3.5_Flash_fast] 新增的宏观报告格式化逻辑
    """
    total = stats.get("total", 0)
    pending_cnt = stats.get("pending", 0)
    active_cnt = stats.get("active", 0)
    published_cnt = stats.get("published", 0)
    failed_cnt = stats.get("failed", 0)
    
    lines = [
        "📊 *系统全局宏观状态报告*",
        "━━━━━━━━━━━━━━━━━━━━",
        "📈 *队列统计概览*",
        f"• ⏳ 待处理 (PENDING): `{pending_cnt}`",
        f"• 🔄 处理中 (ACTIVE): `{active_cnt}`",
        f"• ✅ 已发布 (PUBLISHED): `{published_cnt}`",
        f"• ❌ 失败数 (FAILED): `{failed_cnt}`",
        f"• 📦 队列总计 (TOTAL): `{total}`",
        ""
    ]
    
    lines.append("⚙️ *当前活跃管线 (ACTIVE)*")
    if not processing:
        lines.append("   _当前无正在执行的视频加工任务_")
    else:
        for v in processing:
            icon = _status_icon(v.get("status", ""))
            vid = v.get("youtube_id", "?")
            title = v.get("title", "未知标题")[:30]
            status = v.get("status", "?")
            lines.append(f"   {icon} `{vid}` — {title}\n   └ 进度：`{status}`")
    lines.append("")
    
    lines.append("⏳ *待处理队列 (TOP 3 PENDING)*")
    if not pending:
        lines.append("   _待处理队列为空_")
    else:
        for v in pending[:3]:
            vid = v.get("youtube_id", "?")
            title = v.get("title", "未知标题")[:30]
            lines.append(f"   ⏳ `{vid}` — {title}")
            
    lines.append("")
    lines.append("💡 *提示*：发送 `/run` 立即调度，发送 `/help` 查看指令列表。")
    
    return "\n".join(lines)

