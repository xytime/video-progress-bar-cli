"""src/bot/formatter.py — Telegram 消息格式化模块

高内聚：只负责将数据结构渲染为 Telegram Markdown/HTML 字符串，不依赖任何外部 I/O。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-05-22 | Claude_Sonnet_4.6_Thinking_planning | 初始创建，TDD Green phase |
| 1.1.0 | 2026-05-26 | Gemini_3.5_Flash                    | [v7.0 status] 新增 fmt_status_report 全局宏观状态渲染支持 |
| 1.2.0 | 2026-05-27 | Gemini_3.5_Flash_High_planning      | 升级 fmt_status_report 支持展现父任务与子切片细分统计 |
| 1.3.0 | 2026-05-27 | Gemini_3.5_Flash_planning           | 在 fmt_help 中增加 /whole 与 /slice 的说明 |
| 1.4.0 | 2026-05-29 | Claude_Sonnet_4.6_Thinking_planning | 在 fmt_help 中新增 /tts 命令说明 |
| 1.5.0 | 2026-06-20 | Claude_Opus_4.8                     | 在 fmt_help 中新增 /process <ID> 命令说明（确定性单条发布，忽略分数阈值） |
| 1.6.0 | 2026-07-05 | Codex                               | 在 fmt_help 中新增 /wechat_login 扫码重登命令，并说明 /retry <小时数> 支持批量重试 |
| 1.7.0 | 2026-07-05 | Codex                               | 重设计 /status 为手机值班面板：先给可发布结论、登录态、异常和下一步动作 |
| 1.7.1 | 2026-07-05 | Codex                               | /status 最近异常展示失败总数、标题、YouTube 链接、原因摘要和单条重试命令 |
| 1.7.2 | 2026-07-05 | Codex                               | /status 展示 /retry 24 将影响的任务数量，避免批量操作范围不透明 |
| 1.8.0 | 2026-08-20 | Codex | 增加 Highlight Job 的显式候选分析入口说明，不暗示会自动发布 |
| 1.7.3 | 2026-07-05 | Codex                               | /status 同时展示 /retry 24/48 影响数量，并给最近失败标注相对时间 |
| 1.8.1 | 2026-09-09 | Codex | 队列、发布列表与入队回执补充经校验的可点击 YouTube 原视频链接。 |
| 1.9.0 | 2026-09-09 | Codex | 新增 /last 的移动端发布账本卡片、时区展示和 HTML 安全链接格式化。 |
| 1.9.1 | 2026-09-09 | Codex | 限制 /last 异常历史 ID 的显示长度，确保单卡可由 Telegram 投递。 |
| 1.9.2 | 2026-09-09 | Codex | /last 的平台确认和原片发布时间均直接标注 BJ 时区。 |
"""
from __future__ import annotations
from datetime import datetime, timezone
import html
from typing import List, Optional
from zoneinfo import ZoneInfo

from config.settings import settings
from video_processing.utils.platform_events import youtube_source_url


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


def fmt_video_added(title: str, video_id: str, trim_start: Optional[str] = None, trim_end: Optional[str] = None) -> str:
    """视频成功加入加急队列"""
    trim_info = f"\n✂️ *裁剪区间*：`{trim_start or '0'}` 至 `{trim_end or 'End'}`" if (trim_start or trim_end) else ""
    source_url = youtube_source_url(video_id)
    source_line = f"\n🔗 原视频：[打开 YouTube 原视频]({source_url})" if source_url else ""
    return (
        f"✅ *已加入加急队列！*{trim_info}\n"
        f"📌 标题：`{title}`\n"
        f"🆔 ID：`{video_id}`\n"
        f"_管线将自动处理：下载 → 字幕 → 翻译 → 发布_{source_line}"
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
        source_url = youtube_source_url(str(vid))
        source_line = f"\n   🔗 [打开原视频]({source_url})" if source_url else ""
        lines.append(f"{icon} `{vid}` — {title}\n   状态：`{status}`{source_line}")

    return "\n".join(lines)


def fmt_published(videos: List[dict]) -> str:
    """渲染最近发布的视频列表"""
    if not videos:
        return "📭 暂无已发布视频。"

    lines = ["✅ *最近发布到视频号*\n"]
    for v in videos:
        vid = v.get("youtube_id", "?")
        title = v.get("title", "未知标题")[:30]
        source_url = youtube_source_url(str(vid))
        source_line = f"\n   🔗 [打开原视频]({source_url})" if source_url else ""
        lines.append(f"✅ `{vid}` — {title}{source_line}")

    return "\n".join(lines)


_LAST_PLATFORMS = ("wechat", "douyin", "kuaishou")
_LAST_PLATFORM_LABELS = {
    "wechat": "微信",
    "douyin": "抖音",
    "kuaishou": "快手",
}
_LAST_BJT = ZoneInfo("Asia/Shanghai")
_LAST_TIMEZONE_LABEL = "BJ"
_LAST_DISPLAY_ID_MAX_CHARS = 96


def _last_platform_status(platform: dict) -> str:
    """将账本状态保守地压缩成 /last 卡片的单个平台标签。"""
    if platform.get("confirmed_at"):
        return "✅ 已发布"
    state = str(platform.get("state") or "NOT_QUEUED").upper()
    if state in {"QUEUED", "UPLOADING", "DRAFT", "SUBMITTING"}:
        return "⏳ 已排队"
    if state in {"PUBLISHED", "UNDER_REVIEW", "UNCERTAIN", "SUBMITTED_BOUND", "SUBMITTED_UNBOUND", "NOT_FOUND"}:
        return "⚠️ 待核验"
    if state in {"REJECTED", "RETRYABLE_FAILED", "BANNED", "FAILED"}:
        return "❌ 发布失败"
    if state == "CANCELED":
        return "⏹ 已取消"
    if state in {"", "NOT_QUEUED", "NONE", "NULL"}:
        return "○ 未排队"
    return "? 未知"


def _format_last_timestamp(value: object) -> str:
    """将账本时间统一按 UTC 解析并转换为北京时间；无法解析时不猜测。"""
    text = str(value or "").strip()
    if not text:
        return "未知"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return "未知"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    local = parsed.astimezone(_LAST_BJT)
    if local.year == datetime.now(_LAST_BJT).year:
        return f"{local.strftime('%m-%d %H:%M')} {_LAST_TIMEZONE_LABEL}"
    return f"{local.strftime('%Y-%m-%d %H:%M')} {_LAST_TIMEZONE_LABEL}"


def _format_last_source_time(video: dict) -> str:
    """显示来源视频发布时间；仅日期元数据不虚构时分。"""
    source_published_at = str(video.get("source_published_at") or "").strip()
    if source_published_at:
        formatted = _format_last_timestamp(source_published_at)
        if formatted != "未知":
            return formatted
        for date_format in ("%Y%m%d", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(source_published_at, date_format).replace(tzinfo=_LAST_BJT)
            except ValueError:
                continue
            date_text = parsed.strftime("%m-%d") if parsed.year == datetime.now(_LAST_BJT).year else parsed.strftime("%Y-%m-%d")
            return f"{date_text} {_LAST_TIMEZONE_LABEL}"

    upload_date = str(video.get("upload_date") or "").strip()
    for date_format in ("%Y%m%d", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(upload_date, date_format).replace(tzinfo=_LAST_BJT)
        except ValueError:
            continue
        date_text = parsed.strftime("%m-%d") if parsed.year == datetime.now(_LAST_BJT).year else parsed.strftime("%Y-%m-%d")
        return f"{date_text} {_LAST_TIMEZONE_LABEL}"
    return "未知"


def _last_display_id(video: dict) -> str:
    """制作主体 ID 保留切片索引，避免同源切片在历史中混淆。"""
    youtube_id = str(video.get("youtube_id") or "?")
    try:
        slice_index = int(video.get("slice_index") or 0)
    except (TypeError, ValueError):
        slice_index = 0
    display_id = youtube_id if slice_index == 0 else f"{youtube_id}_s{slice_index}"
    if len(display_id) <= _LAST_DISPLAY_ID_MAX_CHARS:
        return display_id
    return f"{display_id[:80]}…{display_id[-12:]}"


def _last_overall_status(video: dict) -> tuple[str, str]:
    """基于三平台确认时间给出聚合状态，绝不从工作流状态推断。"""
    platforms = video.get("platforms") or {}
    confirmed_count = sum(bool((platforms.get(name) or {}).get("confirmed_at")) for name in _LAST_PLATFORMS)
    if confirmed_count == len(_LAST_PLATFORMS):
        return "🟢 全平台已发布", "PUBLISHED_ALL"
    return "🟡 部分发布", "PUBLISHED_PARTIAL"


def fmt_last_published_entry(index: int, video: dict) -> str:
    """渲染一个不可拆分的 /last 发布卡片，返回 Telegram HTML。"""
    raw_title = str(video.get("zh_title") or "(无中文标题)")
    title = html.escape(raw_title[:120] + ("…" if len(raw_title) > 120 else ""))
    platforms = video.get("platforms") or {}
    platform_line = "　".join(
        f"{_LAST_PLATFORM_LABELS[name]} {_last_platform_status(platforms.get(name) or {})}"
        for name in _LAST_PLATFORMS
    )
    overall_label, overall_code = _last_overall_status(video)
    source_url = youtube_source_url(str(video.get("youtube_id") or ""))
    source_line = (
        f"🔗 <a href=\"{html.escape(source_url, quote=True)}\">YouTube</a>"
        if source_url else "YouTube：不可用"
    )
    return (
        f"{index}. <b>{title}</b>\n"
        f"{overall_label} · {_format_last_timestamp(video.get('last_confirmed_publish_at'))}\n"
        f"{platform_line}\n"
        f"原片：{html.escape(_format_last_source_time(video))}\n"
        f"ID：<code>{html.escape(_last_display_id(video))}</code> · <code>{overall_code}</code>\n"
        f"{source_line}"
    )


def fmt_last_published_header(start: int, end: int, videos: List[dict], *, include_summary: bool) -> str:
    """渲染 /last 分包标题；摘要仅覆盖当前请求中实际返回的视频。"""
    lines = [f"📚 <b>最近发布｜第 {start}–{end} 条</b>"]
    if include_summary:
        all_published = sum(_last_overall_status(video)[1] == "PUBLISHED_ALL" for video in videos)
        partial = len(videos) - all_published
        lines.append(f"✅ {all_published} 全平台正常　⚠️ {partial} 部分发布")
    lines.append("最新在前")
    return "\n".join(lines)


def fmt_last_published_empty() -> str:
    """/last 没有任何已确认公开发布记录时的保守回复。"""
    return "📭 暂无平台账本已确认发布的视频。"


def fmt_last_published_usage() -> str:
    """/last 参数错误说明；不泄露服务端异常或查询细节。"""
    return (
        "⚠️ <b>/last 参数格式错误</b>\n"
        "用法：\n"
        "<code>/last</code>          最近 10 条\n"
        "<code>/last 30</code>       最近 30 条\n"
        "<code>/last 10-30</code>    第 10–30 条\n"
        "编号 1 表示最新发布的视频。\n"
        "单次最多返回 100 条。"
    )


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
        f"无法连接到本地 API 服务（localhost:{settings.dashboard_port}）。\n"
        "_请确认 `vp ui start` 已启动，然后重试。_"
    )


def fmt_help() -> str:
    """帮助信息，列出所有命令"""
    return (
        "🤖 *微信视频号 Bot 使用指南*\n\n"
        "📩 *发送 YouTube 链接* → 自动作为整片发布（默认不切分）\n"
        "   _💡 支持移动端极简裁剪，格式：链接 [开始时间] [结束时间]_\n"
        "   _例：链接 38 14:43 或 链接 30 (去头) 或 链接 -300 (截前段)_\n\n"
        "🎥 `/whole <url> [开始] [结束]` — 强制以完整整片加入队列\n"
        "🎬 `/slice <url> [开始] [结束]` — 允许切片（若有章节）加入队列\n"
        "✂️ `/highlight` — 选择已有视频，显式生成金句候选（不会自动发布）\n"
        "✂️ `/highlight <ID>` — 对指定已有视频确认创建 Highlight Job\n"
        "📂 `/highlight jobs` — 查看 Highlight Job 状态\n"
        "📋 `/queue` — 查看当前处理队列\n"
        "📊 `/status` — 查看全局宏观状态报告\n"
        "✅ `/published` — 查看最近发布到视频号的视频\n"
        "📚 `/last [N|A-B]` — 查看平台确认发布记录，如 `/last 30` 或 `/last 10-30`\n"
        "📥 `/getvideo <ID> [slice_index]` — 把成片发回给你（超 50MB 自动压缩）\n"
        "🗑 `/delete <ID> [slice_index]` — 删除指定视频或分集任务\n"
        "♻️ `/retry <ID> [slice_index]` — 重试失败的视频或分集任务\n"
        "♻️ `/retry <小时数>` — 批量重试最近 N 小时失败/需登录任务，如 `/retry 24`\n"
        "🔐 `/wechat_login` — 推送视频号扫码登录二维码\n"
        "🚀 `/process <ID>` — 立即处理指定视频（忽略分数阈值，单条发布）\n"
        "🏃 `/run` — 立即触发一次全量管线\n"
        "📊 `/stats` — 查看系统统计数据\n"
        "🤖 `/help` — 显示本帮助"
    )


def fmt_status_report(
    stats: dict,
    processing: List[dict],
    queue: List[dict],
    pending: List[dict],
    errors: List[dict],
    wechat: dict | None = None,
    error_total: int | None = None,
    retry24_count: int | None = None,
    retry48_count: int | None = None,
) -> str:
    """渲染手机端值班面板：先结论，再异常，再队列。"""
    total = stats.get("total", 0)
    pending_cnt = stats.get("pending", 0)
    active_cnt = stats.get("active", 0)
    published_cnt = stats.get("published", 0)
    failed_cnt = stats.get("failed", 0)
    error_total = failed_cnt if error_total is None else error_total
    retry24_count = 0 if retry24_count is None else retry24_count
    retry48_count = 0 if retry48_count is None else retry48_count
    server_time = stats.get("server_time", "--:--:--")
    breakdown = stats.get("breakdown", {})
    login_required_cnt = breakdown.get("LOGIN_REQUIRED", 0)
    
    detailed = stats.get("detailed", {})
    parents_stats = detailed.get("parents", {})
    children_stats = detailed.get("children", {})

    wechat = wechat or {}
    wechat_logged_in = bool(wechat.get("logged_in"))
    wechat_login_running = bool(wechat.get("is_running"))
    wechat_qr_exists = bool(wechat.get("qr_exists"))

    if not wechat_logged_in:
        verdict = "🔴 需要介入：微信未登录"
    elif login_required_cnt:
        verdict = f"🟠 需要重试：`{login_required_cnt}` 条等待登录恢复"
    elif failed_cnt:
        verdict = f"🟠 有失败待处理：`{failed_cnt}` 条"
    elif active_cnt:
        verdict = f"🟢 正在工作：`{active_cnt}` 条处理中"
    elif queue:
        verdict = f"🟢 可发布：`{len(queue)}` 条高分任务待调度"
    else:
        verdict = "🟢 空闲可用"

    lines = [
        f"📍 *Pipeline Status*  `{server_time}`",
        verdict,
        "",
        "*发布通道*",
        f"• 微信：{'✅ 已登录' if wechat_logged_in else '🔐 未登录'}"
            + ("（扫码中）" if wechat_login_running else "")
            + ("（二维码已生成）" if wechat_qr_exists else ""),
        f"• 运行：{'🔄 有任务执行中' if active_cnt else '⏸ 空闲'}",
        "",
        "*任务概览*",
        f"• 处理中：`{active_cnt}`",
        f"• 自动发布队列：`{len(queue)}`（本次预览）",
        f"• 待筛选/低分池：`{len(pending)}`（本次预览） / PENDING 总计 `{pending_cnt}`",
        f"• 历史异常：`{error_total}`（需登录 `{login_required_cnt}`）",
        f"• 已发布：`{published_cnt}` / 总计 `{total}`",
    ]

    if failed_cnt or not wechat_logged_in:
        lines.extend(["", "*建议动作*"])
        if not wechat_logged_in:
            lines.append("• 先发 `/wechat_login` 获取扫码二维码")
        if login_required_cnt:
            lines.append("• 登录成功后发 `/retry 24` 批量恢复")
        elif failed_cnt:
            lines.append(f"• 最近 24h 可批量重试：`{retry24_count}` 条，命令 `/retry 24`")
            lines.append(f"• 最近 48h 可批量重试：`{retry48_count}` 条，命令 `/retry 48`")
            lines.append("• 单条重试：复制下方 `/retry <ID>`")
    elif not active_cnt and queue:
        lines.extend(["", "*建议动作*", "• 发 `/run` 触发一轮调度"])
    
    lines.extend(["", "*当前任务*"])
    if processing:
        for v in processing[:3]:
            icon = _status_icon(v.get("status", ""))
            prefix = _video_prefix(v)
            title = _short_title(v.get("title", "未知标题"), 34)
            lines.append(f"• {icon} `{prefix}` {title} — `{v.get('status', '?')}`")
    else:
        lines.append("• 当前没有正在执行的视频")

    lines.append("")
    lines.append("*自动发布队列*")
    if queue:
        for v in queue[:3]:
            prefix = _video_prefix(v)
            title = _short_title(v.get("title", "未知标题"), 34)
            score = v.get("score")
            score_text = f" score `{score}`" if score is not None else ""
            lines.append(f"• ⏳ `{prefix}`{score_text} {title}")
    else:
        lines.append("• 当前没有高分待发布任务")

    if errors:
        lines.append("")
        lines.append(f"*最近异常*  `共 {error_total} 条，按更新时间`")
        for v in errors[:3]:
            prefix = _video_prefix(v)
            title = _short_title(v.get("title", "未知标题"), 42)
            status = v.get("status", "?")
            reason = _short_error(v.get("error_msg", ""))
            age = _relative_age(v.get("updated_at"))
            lines.append(f"• {_status_icon(status)} `{prefix}` — `{status}`")
            lines.append(f"  {title}" + (f"（{age}）" if age else ""))
            lines.append(f"  链接：https://youtu.be/{v.get('youtube_id', prefix)}")
            lines.append(f"  重试：`{_retry_command(v)}`")
            if reason:
                lines.append(f"  原因：{reason}")
    
    return "\n".join(lines)


def _video_prefix(video: dict) -> str:
    vid = video.get("youtube_id", "?")
    slice_idx = video.get("slice_index", 0)
    return f"{vid}_s{slice_idx}" if slice_idx else vid


def _retry_command(video: dict) -> str:
    vid = video.get("youtube_id", "?")
    slice_idx = int(video.get("slice_index") or 0)
    return f"/retry {vid} {slice_idx}" if slice_idx else f"/retry {vid}"


def _short_title(title: str, limit: int) -> str:
    title = " ".join(str(title or "").split())
    return title if len(title) <= limit else title[: limit - 1] + "…"


def _short_error(error_msg: str, limit: int = 72) -> str:
    text = " ".join(str(error_msg or "").split())
    if not text:
        return ""
    if "Sign in to confirm" in text:
        text = "YouTube 需要登录/反爬验证"
    elif "members-only" in text:
        text = "会员专属视频，无法下载"
    elif "Channel Policy Reject" in text:
        text = text.replace("Channel Policy Reject: ", "")
    elif "blacklisted channel" in text:
        text = "频道已拉黑"
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _relative_age(updated_at: str | None) -> str:
    if not updated_at:
        return ""
    try:
        dt = datetime.strptime(str(updated_at), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return ""
    seconds = max(int((datetime.utcnow() - dt).total_seconds()), 0)
    if seconds < 60:
        return f"{seconds}s前"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}min前"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}h前"
    days = hours // 24
    return f"{days}d前"
