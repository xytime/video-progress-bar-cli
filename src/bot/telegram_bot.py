"""src/bot/telegram_bot.py — Telegram Bot 主程序

消息路由 + admin 鉴权 + API 调用编排。
依赖 auth.py / formatter.py / api_client.py，各模块完全解耦。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-05-22 | Claude_Sonnet_4.6_Thinking_planning | 初始创建，TDD Green phase 生产代码 |
| 1.1.0 | 2026-05-24 | Gemini_3.5_Flash_High_planning | 增加 PipelineAgent 统一接管除 /help /start 以外的所有指令及文本消息 |
| 1.1.1 | 2026-05-24 | Gemini_3.5_Flash_High_planning | 调整为仅非 /help 命令交由 Agent，标准指令由程序处理 |
| 1.1.2 | 2026-05-24 | Gemini_3.5_Flash_High_planning | 将 YouTube URL 链接处理重归程序接管，不使用 Agent |
| 1.2.0 | 2026-05-26 | Gemini_3.5_Flash                    | [v7.0 status] 新增 cmd_status 宏观状态指令并调整命令路由 |
| 1.3.0 | 2026-05-27 | Gemini_3.5_Flash_High_planning      | 升级 cmd_retry 与 cmd_delete 命令，支持可选 [slice_index] 对切片子任务的操作 |
| 1.4.0   | 2026-05-27 | Gemini_3.5_Flash_planning           | 优化 YouTube URL 正则以原生支持直播回放 (live/) 与完整提取带参数链接，防止裁剪干扰 |
| 1.5.0   | 2026-05-27 | Gemini_3.5_Flash_planning           | 新增 /whole 和 /slice 指令并更新默认纯 URL 路由行为为不分集模式 |
| 1.6.0   | 2026-05-29 | Claude_Sonnet_4.6_Thinking_planning | 新增 /tts 指令：发送 /tts <url> 时以 CosyVoice TTS 配音模式加入队列；移除了默认自动 TTS 行为 |
| 1.7.0   | 2026-06-01 | Claude_Sonnet_4.6_Thinking_planning | 新增 _handle_respec helper；各命令 already_exists 分支升级：有 trim/TTS 参数时自动调用 respec 实现“以最后一次为准” |
| 1.8.0   | 2026-06-03 | Claude_Sonnet_4.6_Thinking_planning | 新增 _normalize_time() 预处理，parse_trim_params 支持 M'S 分秒格式（如 1'10 → 1:10） |
| 1.9.0   | 2026-06-14 | Claude_Opus_4.8                     | 新增 /getvideo 命令：把成片发回 Telegram，>50MB 经 video_delivery 自动压缩（转码放进 executor 不阻塞轮询） |
| 1.10.0  | 2026-07-17 | Codex                               | 当前无配音业务场景，/tts 明确停用且不再创建视频任务 |
| 1.10.0  | 2026-06-20 | Claude_Opus_4.8                     | 修「对话无响应」：builder 开 concurrent_updates(True) 消除慢 Agent 对后续消息的串行阻塞；放宽 pool_timeout=20s 等超时，避免网络抖动时 Pool timeout 发不出回复 |
| 1.11.0  | 2026-06-20 | Claude_Opus_4.8                     | 新增确定性命令 /process <youtube_id>：经 api_client.process_video → web /api/videos/{id}/process 立即处理单条视频（忽略分数阈值），不依赖 AI 编排，作为「发布某条」的可靠兜底 |
| 1.12.0  | 2026-06-27 | Claude_Opus_4.8                     | [根治崩溃循环/「无反应」] builder 显式 connection_pool_size(256) + get_updates_connection_pool_size(16)/get_updates_pool_timeout(20)：concurrent_updates(True) 下默认池仅 1 条→PoolTimeout 抛进 updater 轮询→Application 停止(频繁重启)。enlarge 后并发 handler 不再抢空连接池 |
| 1.13.0  | 2026-06-28 | Claude_Opus_4.8                     | 新增 /deploy：手机远程一键在主机上 git push 当前分支到 origin（bot 进程用主机凭据非交互推送，GIT_TERMINAL_PROMPT=0 防挂起，异步不阻塞，管理员限定）——解决「人不在电脑旁、agent 工具层拒绝 push」的远程部署缺口 |
| 1.14.0  | 2026-06-28 | Claude_Opus_4.8                     | /retry 支持小时参数：/retry <小时数>（纯数字≤3位）批量重试最近 N 小时内 FAILED 任务（如 /retry 24/48）；youtube_id 单条重试保持不变（11位含字母无歧义） |
| 1.15.0  | 2026-07-05 | Codex                               | 新增确定性 /wechat_login 命令，避免扫码重登依赖通用 Agent 兜底路由 |
| 1.16.0  | 2026-07-05 | Codex                               | /status 改为手机值班面板，合并微信登录态、自动发布队列、最近异常和建议动作 |
| 1.16.1  | 2026-07-05 | Codex                               | /status 最近异常展示失败总数、标题、YouTube 链接和单条 /retry 命令 |
| 1.16.2  | 2026-07-05 | Codex                               | /status 展示 /retry 24 只读预览数量，避免用户发出批量命令后才知道影响范围 |
| 1.16.3  | 2026-07-05 | Codex                               | /status 展示 /retry 24/48 数量，并给最近失败标注相对时间 |
| 1.17.0  | 2026-07-28 | Codex                               | /status 改接只读三秒质检报告，并增加 Telegram 命令菜单和底部快捷键 |
| 1.17.1  | 2026-08-10 | Codex                               | 今日简报自然语言直连本地只读账本，避免 TLS 波动影响运营查询 |
| 1.17.2  | 2026-08-10 | Codex                               | Bot 启动前以项目 .env 覆盖 LaunchAgent 继承环境，确保本地模型凭据一致 |
| 1.17.3  | 2026-08-18 | Codex                               | 禁用 httpx/httpcore 请求 INFO 日志，避免 Bot API 鉴权 URL 写入本地日志 |
| 1.19.0  | 2026-08-20 | Codex                               | Highlight 候选支持显式选定并创建独立发布主体；仍不触发渲染或发布 |
| 1.18.0  | 2026-08-20 | Codex                               | 新增 /highlight 的显式视频选择与候选分析入口；不触发渲染或发布 |
| 1.20.0  | 2026-08-21 | Codex                               | 新增 /english_world 候选研究、选题与二次制作确认；不触发通用队列或发布 |
| 1.21.0  | 2026-08-23 | Codex                               | 英语世界审核回执增加唯一投稿批准/搁置回调，不接受模糊文字发布指令。 |
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

# 必须早于 PipelineAgent / settings 导入：LaunchAgent 可能继承过期的同名变量。
load_dotenv(Path(__file__).parent.parent.parent / ".env", override=True)

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# 确保 src/ 在 sys.path
_src = str(Path(__file__).parent.parent)
if _src not in sys.path:
    sys.path.insert(0, _src)

from bot.auth import SecurityConfigError, is_admin, parse_admin_ids
from bot.api_client import PipelineAPIClient
from bot import formatter as fmt
from bot.pipeline_agent import PipelineAgent
from bot.video_delivery import (
    prepare_for_delivery,
    finished_video_path,
    FinishedVideoNotFound,
    CompressionError,
)
from video_processing.quality_report import collect as collect_quality_report
from video_processing.daily_brief import collect_daily_brief

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)
# httpx 的 INFO access log 会带完整 Bot API URL，其中包含鉴权 token。
# 保留本业务模块 INFO，但把传输层降到 WARNING，避免凭据落入可长期保留的 bot.log。
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("telegram_bot")

# [Gemini_3.5_Flash_planning] 优化正则匹配，包含整个带参数的 URL (排除末尾标点)，并支持 live/ 路径
_YOUTUBE_RE = re.compile(r"https?://(?:(?:www|m)\.)?(?:youtube\.com/(?:watch\?.*v=|shorts/|live/)|youtu\.be/)[^\s]+(?<![.,!?;:\)\"\'\]\}])")

_COMMAND_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["/status", "/queue"],
        ["/run", "/wechat_login"],
        ["/highlight", "/english_world"],
        ["/published", "/help"],
    ],
    resize_keyboard=True,
    is_persistent=True,
)

_BOT_COMMANDS = [
    BotCommand("status", "3秒质检：异常/卡点/遗留"),
    BotCommand("queue", "查看当前队列"),
    BotCommand("run", "触发一次管线"),
    BotCommand("wechat_login", "推送微信扫码登录"),
    BotCommand("published", "最近本地发布记录"),
    BotCommand("highlight", "Highlight Slice：选择视频生成金句候选"),
    BotCommand("english_world", "英语世界：搜索、选题与制作确认"),
    BotCommand("retry", "重试单条或最近N小时失败"),
    BotCommand("help", "显示快捷菜单"),
]


def _is_daily_brief_request(text: str) -> bool:
    """识别今日运营数据问询；命中后绝不转交会产生网络依赖的通用 Agent。"""
    normalized = re.sub(r"\s+", "", text or "").lower()
    asks_today = "今天" in normalized or "今日" in normalized
    asks_operations = any(marker in normalized for marker in (
        "简报", "采编", "敏感词", "发布数量", "发布视频", "失败数量", "发布情况",
    ))
    return asks_today and asks_operations


async def _reply_html_chunks(message, text: str, *, max_length: int = 3900) -> None:
    """按换行切分长 HTML 报告，避免 Telegram 4096 字符上限导致整份日报丢失。"""
    chunk = ""
    for line in text.splitlines(keepends=True):
        if chunk and len(chunk) + len(line) > max_length:
            await message.reply_text(chunk.rstrip(), parse_mode="HTML")
            chunk = ""
        chunk += line
    if chunk:
        await message.reply_text(chunk.rstrip(), parse_mode="HTML")


async def _configure_bot_menu(app: Application) -> None:
    """注册 Telegram 原生命令菜单；底部快捷键随 /help 和 /status 消息下发。"""
    await app.bot.set_my_commands(_BOT_COMMANDS)


def _load_config() -> tuple[str, set[int]]:
    """加载并强验证所有必要配置。Fail-Closed: 任何问题直接 sys.exit。"""

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("❌ 安全拦截：TELEGRAM_BOT_TOKEN 未配置。请在 .env 中设置。", file=sys.stderr)
        sys.exit(1)

    raw_ids = os.environ.get("TELEGRAM_ADMIN_IDS", "")
    try:
        admin_ids = parse_admin_ids(raw_ids)
    except SecurityConfigError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    logger.info(f"✅ 安全门控通过：已加载 {len(admin_ids)} 个管理员 ID")
    return token, admin_ids


# ── 全局客户端（延迟初始化，由 main() 传入）─────────────────────────────
_api: PipelineAPIClient | None = None
_admin_ids: set[int] = set()


def _check_admin(update: Update) -> bool:
    """鉴权拦截器：非管理员直接忽略（不回复，防止探测）"""
    # [Claude_Sonnet_4.6_Thinking_planning] P1修复：effective_user 在频道/匿名消息时为 None
    user = update.effective_user
    if user is None:
        logger.warning("拒绝匿名/频道消息")
        return False
    if not is_admin(user.id, _admin_ids):
        logger.warning(f"拒绝未授权请求：user_id={user.id}")
        return False
    return True


# ── 命令处理器 ───────────────────────────────────────────────────────────

_HIGHLIGHT_SOURCE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,64}$")
_HIGHLIGHT_CLIP_ID_RE = re.compile(r"^[a-f0-9]{32}$")


def _highlight_source_text(source: dict) -> str:
    """将只读源视频信息安全地收敛为 Telegram HTML 行。"""
    yid = html.escape(str(source.get("youtube_id") or "?"))
    title = str(source.get("source_zh_title") or source.get("zh_title") or source.get("title") or "未命名视频")
    title = html.escape(title[:56])
    status = html.escape(str(source.get("status") or "UNKNOWN"))
    subtitle = "字幕可用" if source.get("source_subtitle_available") else "缺带时间轴字幕"
    video = "源片可用" if source.get("source_video_available") else "源片待补"
    return f"<code>{yid}</code>｜{title}\n状态：<code>{status}</code> · {subtitle} · {video}"


async def _send_highlight_confirmation(message, youtube_id: str, *, title: str = "") -> None:
    """第二次明确确认后才创建 Highlight Job；此处不产生任何外部发布动作。"""
    clean_yid = (youtube_id or "").strip()
    if not _HIGHLIGHT_SOURCE_ID_RE.fullmatch(clean_yid):
        await message.reply_text("❌ 视频 ID 格式不合法。")
        return
    display_title = f"\n标题：{html.escape(title[:80])}" if title else ""
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("确认生成金句候选", callback_data=f"hl:create:{clean_yid}")],
        [InlineKeyboardButton("取消", callback_data="hl:cancel")],
    ])
    await message.reply_text(
        "✂️ <b>Highlight Slice</b>"
        f"\n源视频：<code>{html.escape(clean_yid)}</code>{display_title}"
        "\n\n本操作只创建独立 Highlight Job，读取现有源字幕生成候选；"
        "不会改动原视频队列、不会下载/渲染，也不会提交发布。",
        parse_mode="HTML",
        reply_markup=markup,
    )


async def _reply_highlight_sources(message) -> None:
    """显示最近源视频，并只为有时间轴字幕的项目提供确认入口。"""
    assert _api is not None
    sources = await _api.get_highlight_sources(limit=10)
    if sources is None:
        await message.reply_text(fmt.fmt_api_unavailable(), parse_mode="Markdown")
        return
    if not sources:
        await message.reply_text("📭 没有可选择的既有源视频。")
        return
    lines = ["✂️ <b>Highlight Slice</b>", "选择已有视频后，将再次请求确认。"]
    buttons: list[list[InlineKeyboardButton]] = []
    for source in sources:
        lines.append("")
        lines.append(_highlight_source_text(source))
        yid = str(source.get("youtube_id") or "")
        if source.get("can_analyze") and _HIGHLIGHT_SOURCE_ID_RE.fullmatch(yid):
            buttons.append([InlineKeyboardButton(f"选择 {yid}", callback_data=f"hl:confirm:{yid}")])
    if not buttons:
        lines.extend(["", "当前项目均缺带时间轴源字幕；不会创建无效 Highlight Job。"])
    await message.reply_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons) if buttons else None,
    )


async def _reply_highlight_jobs(message) -> None:
    """展示独立 Job 账本，不把它们归入现有视频发布队列。"""
    assert _api is not None
    jobs = await _api.get_highlight_jobs(limit=10)
    if jobs is None:
        await message.reply_text(fmt.fmt_api_unavailable(), parse_mode="Markdown")
        return
    if not jobs:
        await message.reply_text("📭 尚无 Highlight Job。发送 /highlight 选择一个已有视频。")
        return
    lines = ["✂️ <b>Highlight Jobs</b>"]
    buttons: list[list[InlineKeyboardButton]] = []
    for job in jobs:
        title = html.escape(str(job.get("source_zh_title") or job.get("source_title") or "未命名视频")[:48])
        yid = html.escape(str(job.get("youtube_id") or "?"))
        state = html.escape(str(job.get("state") or "UNKNOWN"))
        clips = int(job.get("clip_count") or 0)
        lines.append(
            f"\n<code>{str(job.get('id') or '')[:8]}</code> · <code>{state}</code>"
            f"\n<code>{yid}</code>｜{title}\n候选数：{clips}"
        )
        for clip in (job.get("clips") or [])[:3]:
            score = html.escape(str(clip.get("virality_score") or "-"))
            quote = html.escape(str(clip.get("core_quote") or "")[:96])
            start_ms = int(clip.get("raw_start_ms") or 0)
            end_ms = int(clip.get("raw_end_ms") or 0)
            lines.append(f"  • <code>{score}</code> 分 · {_format_highlight_ms(start_ms)}–{_format_highlight_ms(end_ms)}\n    {quote}")
            clip_id = str(clip.get("id") or "")
            clip_state = str(clip.get("state") or "")
            if clip_state == "CANDIDATE" and _HIGHLIGHT_CLIP_ID_RE.fullmatch(clip_id):
                buttons.append([InlineKeyboardButton(
                    f"选定候选 {score} 分（{_format_highlight_ms(start_ms)}）",
                    callback_data=f"hl:select:{clip_id}",
                )])
            elif clip.get("publication_subject_id"):
                lines.append("    已选定为独立发布主体（尚未渲染或发布）")
    lines.append("\n选定只创建独立发布主体；不会渲染、上传或发布。")
    await message.reply_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons) if buttons else None,
    )


def _format_highlight_ms(value: int) -> str:
    """将候选时间轴压缩为 Telegram 易读的 H:MM:SS。"""
    seconds = max(0, int(value) // 1000)
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


async def cmd_highlight(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/highlight [youtube_id] 或 /highlight jobs — 显式发起独立金句候选分析。"""
    if not _check_admin(update):
        return
    args = [str(item).strip() for item in (ctx.args or []) if str(item).strip()]
    if not args:
        await _reply_highlight_sources(update.message)
        return
    if args[0].lower() == "jobs" and len(args) == 1:
        await _reply_highlight_jobs(update.message)
        return
    if args[0].lower() == "slice":
        args = args[1:]
    if len(args) != 1 or not _HIGHLIGHT_SOURCE_ID_RE.fullmatch(args[0]):
        await update.message.reply_text(
            "用法：/highlight\n/highlight <video_id>\n/highlight slice <video_id>\n/highlight jobs"
        )
        return
    await _send_highlight_confirmation(update.message, args[0])


async def handle_highlight_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 Highlight 确认和候选选定；callback_data 只承载受限 ID，不承载标题或路径。"""
    if not _check_admin(update):
        return
    assert _api is not None
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    data = str(query.data or "")
    if data == "hl:cancel":
        await query.edit_message_text("已取消；未创建 Highlight Job。")
        return
    select_match = re.fullmatch(r"hl:select:([a-f0-9]{32})", data)
    if select_match:
        result = await _api.select_highlight_clip(select_match.group(1))
        if result is None:
            await query.edit_message_text("⚠️ 控制中心暂时不可用，未选定候选。")
            return
        if not result.get("success"):
            await query.edit_message_text(
                f"❌ 选定失败：{html.escape(str(result.get('error') or '未知错误'))}", parse_mode="HTML",
            )
            return
        clip = result.get("clip") or {}
        await query.edit_message_text(
            "✅ <b>Highlight 候选已选定</b>"
            f"\n片段：<code>{html.escape(str(clip.get('id') or '')[:8])}</code>"
            f"\n发布主体：<code>{html.escape(str(clip.get('publication_subject_id') or ''))}</code>"
            "\n\n仅建立独立身份；尚未渲染、上传或发布。",
            parse_mode="HTML",
        )
        return
    match = re.fullmatch(r"hl:(confirm|create):([A-Za-z0-9_-]{6,64})", data)
    if not match:
        await query.edit_message_text("❌ Highlight 操作参数无效。")
        return
    action, youtube_id = match.groups()
    if action == "confirm":
        await _send_highlight_confirmation(query.message, youtube_id)
        return
    result = await _api.create_highlight_job(youtube_id, requested_by="telegram")
    if result is None:
        await query.edit_message_text("⚠️ 控制中心暂时不可用，未创建 Highlight Job。")
        return
    if not result.get("success"):
        await query.edit_message_text(f"❌ 创建失败：{html.escape(str(result.get('error') or '未知错误'))}", parse_mode="HTML")
        return
    job = result.get("job") or {}
    job_id = html.escape(str(job.get("id") or "")[:8])
    state = html.escape(str(job.get("state") or "QUEUED"))
    await query.edit_message_text(
        "✅ <b>Highlight Job 已创建</b>"
        f"\n源视频：<code>{html.escape(youtube_id)}</code>"
        f"\n任务：<code>{job_id}</code> · <code>{state}</code>"
        "\n\n正在读取现有源字幕生成候选。不会下载、渲染或发布；稍后可发送 /highlight jobs 查看结果。",
        parse_mode="HTML",
    )


_ENGLISH_WORLD_JOB_ID_RE = re.compile(r"^[a-f0-9]{32}$")
_ENGLISH_WORLD_CANDIDATE_ID_RE = re.compile(r"^[a-f0-9]{32}$")
_ENGLISH_WORLD_REVIEW_ID_RE = re.compile(r"^[a-f0-9]{32}$")


def _format_english_world_duration(value: object) -> str:
    """将候选时长压缩为 Telegram 易读的秒数。"""
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return "时长待核验"
    return f"{seconds // 60}:{seconds % 60:02d}" if seconds >= 60 else f"{seconds}s"


def _english_world_candidate_text(candidate: dict, *, label: str) -> str:
    """把候选元数据转为安全、短小的 HTML，避免把来源说明伪装成已审核结论。"""
    title = html.escape(str(candidate.get("source_title") or "未命名视频")[:90])
    channel = html.escape(str(candidate.get("source_channel") or "未知来源")[:48])
    topic = html.escape(str(candidate.get("topic") or "life"))
    value = html.escape(str(candidate.get("learning_value") or "")[:100])
    safety = html.escape(str(candidate.get("safety_note") or "")[:110])
    subtitle = html.escape(str(candidate.get("caption_status") or "待核验"))
    return (
        f"<b>{label}. {title}</b>\n"
        f"来源：{channel} · {_format_english_world_duration(candidate.get('duration_sec'))} · {topic}\n"
        f"学习价值：{value}\n字幕：{subtitle}\n适宜性：{safety}"
    )


async def _reply_english_world_jobs(message) -> None:
    """只读展示英语世界研究及审核/投稿账本；按钮始终携带受限 ID。"""
    assert _api is not None
    jobs = await _api.get_english_world_jobs(limit=10)
    if jobs is None:
        await message.reply_text(fmt.fmt_api_unavailable(), parse_mode="Markdown")
        return
    review_items = await _api.get_english_world_review_items(limit=10)
    if not jobs and not review_items:
        await message.reply_text("📭 暂无英语世界任务。发送 /english_world 开始今日候选研究。")
        return
    lines = ["🌍 <b>英语世界短视频任务</b>"]
    buttons: list[list[InlineKeyboardButton]] = []
    for job in jobs:
        job_id = str(job.get("id") or "")
        state = html.escape(str(job.get("state") or "UNKNOWN"))
        lines.append(f"\n<code>{html.escape(job_id[:8])}</code> · <code>{state}</code>")
        for index, candidate in enumerate(job.get("candidates") or [], start=1):
            lines.append(_english_world_candidate_text(candidate, label=chr(64 + index)))
            candidate_id = str(candidate.get("id") or "")
            if job.get("state") == "CANDIDATES_READY" and _ENGLISH_WORLD_CANDIDATE_ID_RE.fullmatch(candidate_id):
                buttons.append([InlineKeyboardButton(
                    f"选择 {chr(64 + index)}", callback_data=f"ew:s:{candidate_id}",
                )])
        if job.get("state") == "CANDIDATE_SELECTED" and _ENGLISH_WORLD_JOB_ID_RE.fullmatch(job_id):
            buttons.append([InlineKeyboardButton("确认制作此选题", callback_data=f"ew:p:{job_id}")])
        if job.get("state") == "FAILED":
            lines.append(f"问题：{html.escape(str(job.get('error_message') or '未知错误')[:180])}")
    if review_items:
        lines.append("\n<b>审核与投稿回执</b>")
        for item in review_items:
            review_id = str(item.get("id") or "")
            state = html.escape(str(item.get("state") or "UNKNOWN"))
            title = html.escape(str(item.get("title") or "未命名成片")[:80])
            lines.append(f"<code>{html.escape(review_id[:8])}</code> · <code>{state}</code>\n{title}")
            if item.get("state") == "READY_FOR_REVIEW" and _ENGLISH_WORLD_REVIEW_ID_RE.fullmatch(review_id):
                buttons.append([InlineKeyboardButton(
                    f"提交视频号 · {review_id[:8]}", callback_data=f"ew:r:{review_id}",
                )])
            if item.get("state") == "UNCERTAIN" and _ENGLISH_WORLD_REVIEW_ID_RE.fullmatch(review_id):
                buttons.append([InlineKeyboardButton(
                    f"核验后重传 · {review_id[:8]}", callback_data=f"ew:rc:{review_id}",
                )])
    await _reply_html_chunks(
        message,
        "\n\n".join(lines),
    )
    if buttons:
        await message.reply_text(
            "选择候选后，还会再次要求确认制作。研究、制作和发布彼此独立。",
            reply_markup=InlineKeyboardMarkup(buttons),
        )


async def _wait_for_english_world_research(message, job_id: str) -> None:
    """在本次 Bot 进程存活期间推送研究完成/失败回执；重启后仍可由 jobs 查询。"""
    assert _api is not None
    for _ in range(20):
        await asyncio.sleep(3)
        jobs = await _api.get_english_world_jobs(limit=20)
        if jobs is None:
            continue
        job = next((item for item in jobs if item.get("id") == job_id), None)
        if job is None:
            return
        state = str(job.get("state") or "")
        if state == "CANDIDATES_READY":
            await message.reply_text("✅ <b>英语世界候选已就绪</b>\n现在可选择 A/B/C；不会自动制作或发布。", parse_mode="HTML")
            await _reply_english_world_jobs(message)
            return
        if state == "FAILED":
            await message.reply_text(
                f"❌ <b>英语世界候选研究失败</b>\n{html.escape(str(job.get('error_message') or '未知错误'))}",
                parse_mode="HTML",
            )
            return


async def cmd_english_world(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/english_world [jobs|YouTube URL] — 研究候选，且不把 URL 自动推入普通发布队列。"""
    if not _check_admin(update):
        return
    assert _api is not None
    args = [str(item).strip() for item in (ctx.args or []) if str(item).strip()]
    if args and args[0].lower() == "jobs" and len(args) == 1:
        await _reply_english_world_jobs(update.message)
        return
    if len(args) > 1 or (args and not _YOUTUBE_RE.fullmatch(args[0])):
        await update.message.reply_text("用法：/english_world\n/english_world jobs\n/english_world <YouTube URL>")
        return
    source_url = args[0] if args else None
    chat_id = str(update.effective_chat.id) if update.effective_chat else None
    result = await _api.create_english_world_research(
        requested_by="telegram", notification_target=chat_id, source_url=source_url,
    )
    if result is None:
        await update.message.reply_text(fmt.fmt_api_unavailable(), parse_mode="Markdown")
        return
    if not result.get("success"):
        await update.message.reply_text(f"❌ {result.get('error') or '候选研究未创建'}")
        return
    job = result.get("job") or {}
    job_id = str(job.get("id") or "")
    await update.message.reply_text(
        "🔎 <b>英语世界候选研究已启动</b>"
        f"\n任务：<code>{html.escape(job_id[:8])}</code> · <code>RESEARCHING</code>"
        "\n将基于公开元数据筛除明显不适宜题材；不会下载、制作、入通用队列或发布。",
        parse_mode="HTML",
    )
    if _ENGLISH_WORLD_JOB_ID_RE.fullmatch(job_id):
        asyncio.create_task(_wait_for_english_world_research(update.message, job_id))


async def handle_english_world_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """处理英语世界选题、制作确认与唯一审核项投稿批准；callback 不携带 URL/路径。"""
    if not _check_admin(update):
        return
    assert _api is not None
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    data = str(query.data or "")
    retry_confirm = re.fullmatch(r"ew:rc:([a-f0-9]{32})", data)
    if retry_confirm:
        review_id = retry_confirm.group(1)
        await query.edit_message_text(
            "⚠️ <b>确认未发布后重传</b>\n"
            f"审核编号：<code>{review_id[:8]}</code>\n"
            "仅当你已在视频号后台确认本条未发布时继续；将保留首次未确认证据，"
            "并只重传这一审核项。",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("确认未发布，重传本条", callback_data=f"ew:rr:{review_id}"),
            ]]),
        )
        return
    retry_execute = re.fullmatch(r"ew:rr:([a-f0-9]{32})", data)
    if retry_execute:
        result = await _api.reopen_uncertain_english_world_submission(retry_execute.group(1))
        if result is None or not result.get("success"):
            await query.edit_message_text("⚠️ 重传未启动；请刷新 /english_world jobs 查看状态。")
            return
        await query.edit_message_text(
            "✅ <b>已启动本条人工确认重传</b>\n"
            f"审核编号：<code>{retry_execute.group(1)[:8]}</code>\n"
            "仅提交绑定成片；后续以视频号平台回执为准。",
            parse_mode="HTML",
        )
        return
    review_approval = re.fullmatch(r"ew:r:([a-f0-9]{32})", data)
    if review_approval:
        result = await _api.approve_english_world_submission(review_approval.group(1))
        if result is None:
            await query.edit_message_text("⚠️ 控制中心暂时不可用，未记录投稿批准。")
            return
        if not result.get("success"):
            await query.edit_message_text(
                f"❌ 投稿批准未生效：{html.escape(str(result.get('error') or '未知错误'))}", parse_mode="HTML",
            )
            return
        item = result.get("item") or {}
        state = html.escape(str(item.get("state") or "SUBMISSION_APPROVED"))
        await query.edit_message_text(
            "✅ <b>已接收本条投稿批准</b>\n"
            f"审核编号：<code>{review_approval.group(1)[:8]}</code>\n"
            f"当前状态：<code>{state}</code>\n"
            "正在发起视频号提交；后续将以“已受理 / 审核中 / 未确认”等平台回执为准，"
            "不会将提交受理误报为公开发布，也不会自动重传。",
            parse_mode="HTML",
        )
        return
    review_hold = re.fullmatch(r"ew:[mh]:([a-f0-9]{32})", data)
    if review_hold:
        result = await _api.hold_english_world_review_item(review_hold.group(1))
        if result is None:
            await query.edit_message_text("⚠️ 控制中心暂时不可用，未搁置审核项。")
            return
        if not result.get("success"):
            await query.edit_message_text(
                f"❌ 操作未生效：{html.escape(str(result.get('error') or '未知错误'))}", parse_mode="HTML",
            )
            return
        await query.edit_message_text(
            "⏸ <b>审核项已搁置</b>\n"
            f"审核编号：<code>{review_hold.group(1)[:8]}</code>\n"
            "未提交视频号。若要修改，请在 Telegram 说明修改点后重新生成审核成片。",
            parse_mode="HTML",
        )
        return
    selected = re.fullmatch(r"ew:s:([a-f0-9]{32})", data)
    if selected:
        result = await _api.select_english_world_candidate(selected.group(1))
        if result is None:
            await query.edit_message_text("⚠️ 控制中心暂时不可用，未选定候选。")
            return
        if not result.get("success"):
            await query.edit_message_text(f"❌ 选定失败：{html.escape(str(result.get('error') or '未知错误'))}", parse_mode="HTML")
            return
        candidate = result.get("candidate") or {}
        job = result.get("job") or {}
        job_id = str(job.get("id") or candidate.get("job_id") or "")
        markup = InlineKeyboardMarkup([[InlineKeyboardButton(
            "确认制作", callback_data=f"ew:p:{job_id}",
        )]]) if _ENGLISH_WORLD_JOB_ID_RE.fullmatch(job_id) else None
        await query.edit_message_text(
            "✅ <b>候选已选定</b>\n"
            + _english_world_candidate_text(candidate, label="已选")
            + "\n\n请再次确认制作。此动作不会提交视频号。",
            parse_mode="HTML", reply_markup=markup,
        )
        return
    production = re.fullmatch(r"ew:p:([a-f0-9]{32})", data)
    if not production:
        await query.edit_message_text("❌ 英语世界操作参数无效。")
        return
    result = await _api.request_english_world_production(production.group(1))
    if result is None:
        await query.edit_message_text("⚠️ 控制中心暂时不可用，未登记制作请求。")
        return
    if not result.get("success"):
        await query.edit_message_text(f"❌ 制作确认失败：{html.escape(str(result.get('error') or '未知错误'))}", parse_mode="HTML")
        return
    await query.edit_message_text(
        "✅ <b>制作请求已登记</b>\n"
        "状态：<code>PRODUCTION_REQUESTED</code>\n"
        "当前会等待英语学习卡生产协调器接手；尚未下载、渲染或发布，因此不会伪报成片完成。",
        parse_mode="HTML",
    )

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _check_admin(update):
        return
    await update.message.reply_text(fmt.fmt_help(), parse_mode="Markdown", reply_markup=_COMMAND_KEYBOARD)  # type: ignore


async def cmd_queue(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _check_admin(update):
        return
    assert _api is not None
    # 同时取 waitlist（PENDING）和 processing（活跃中）的视频
    # [Gemini_3.1_Pro_High] P0修复：get_videos 断线返回 None，用长度+stats 双重判断
    stats = await _api.get_stats()
    if stats is None:
        await update.message.reply_text(fmt.fmt_api_unavailable(), parse_mode="Markdown")  # type: ignore
        return
    pending = await _api.get_videos(tab="waitlist", size=10)
    processing = await _api.get_videos(tab="active", size=5)
    
    if pending is None or processing is None:
        await update.message.reply_text(fmt.fmt_api_unavailable(), parse_mode="Markdown")  # type: ignore
        return
        
    videos = processing + pending
    await update.message.reply_text(fmt.fmt_queue(videos), parse_mode="Markdown")  # type: ignore


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/status 指令：三秒可读的只读质检面板。"""
    if not _check_admin(update):
        return
    try:
        msg = await asyncio.to_thread(collect_quality_report)
    except Exception as e:  # noqa: BLE001
        logger.exception("status quality report failed")
        await update.message.reply_text(fmt.fmt_error(f"质检报告生成失败：{e}"), parse_mode="Markdown")  # type: ignore
        return
    await update.message.reply_text(msg, parse_mode="HTML", reply_markup=_COMMAND_KEYBOARD)  # type: ignore


async def cmd_wechat_login(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/wechat_login — 确定性启动微信视频号扫码重登流程。"""
    if not _check_admin(update):
        return

    notice = await update.message.reply_text(  # type: ignore
        "🔐 *正在启动微信视频号扫码登录...*\n二维码稍后会推送到这里。",
        parse_mode="Markdown",
    )
    try:
        agent = PipelineAgent(bot=ctx.bot, loop=asyncio.get_running_loop(), chat_id=update.effective_chat.id)
        raw = await asyncio.to_thread(agent.trigger_wechat_login)
        result = json.loads(raw)
    except Exception as e:  # noqa: BLE001
        logger.exception("wechat_login command failed")
        await notice.edit_text(fmt.fmt_error(f"启动微信登录失败：{e}"), parse_mode="Markdown")
        return

    if result.get("ok"):
        await notice.edit_text(
            "🔐 *微信登录流程已启动*\n请等待二维码图片推送，然后用手机微信扫码。扫码成功后会自动保存登录态。",
            parse_mode="Markdown",
        )
    else:
        await notice.edit_text(fmt.fmt_error(result.get("error", "启动微信登录失败")), parse_mode="Markdown")


async def cmd_published(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _check_admin(update):
        return
    assert _api is not None
    videos = await _api.get_videos(tab="completed", size=5)
    if videos is None:
        await update.message.reply_text(fmt.fmt_api_unavailable(), parse_mode="Markdown")  # type: ignore
        return
    await update.message.reply_text(fmt.fmt_published(videos), parse_mode="Markdown")  # type: ignore


async def cmd_getvideo(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/getvideo <youtube_id> [slice_index] — 把制作好的成片发回当前对话。

    成片 = output/{prefix}_vertical.mp4。>50MB（Telegram 上限）时由 video_delivery
    自动压缩出一份 ≤50MB 的副本再发。转码阻塞，放进 to_thread 以免卡住轮询。
    """
    if not _check_admin(update):
        return
    args = ctx.args  # type: ignore
    if not args:
        await update.message.reply_text(fmt.fmt_error("用法：/getvideo <youtube_id> [slice_index]"), parse_mode="Markdown")  # type: ignore
        return

    youtube_id = args[0].strip()
    slice_index = 0
    if len(args) >= 2:
        try:
            slice_index = int(args[1].strip())
        except ValueError:
            await update.message.reply_text(fmt.fmt_error("分集索引 slice_index 必须为整数"), parse_mode="Markdown")  # type: ignore
            return

    notice = await update.message.reply_text(  # type: ignore
        "📦 *正在准备成片…*\n_大文件会自动压缩，可能需要几分钟，请稍候。_",
        parse_mode="Markdown",
    )

    try:
        prepared = await asyncio.to_thread(prepare_for_delivery, youtube_id, slice_index)
    except FinishedVideoNotFound:
        await notice.edit_text(
            fmt.fmt_error(f"没找到 `{youtube_id}` 的成片，可能尚未制作完成或已被清理。"),
            parse_mode="Markdown",
        )
        return
    except CompressionError as e:
        src = finished_video_path(youtube_id, slice_index)
        await notice.edit_text(
            fmt.fmt_error(f"成片过大且压缩失败：{e}\n本机路径：`{src}`"),
            parse_mode="Markdown",
        )
        return
    except Exception as e:  # noqa: BLE001
        logger.exception("getvideo 准备失败")
        await notice.edit_text(fmt.fmt_error(f"准备成片出错：{e}"), parse_mode="Markdown")
        return

    tag = f"{youtube_id}" + (f"_s{slice_index}" if slice_index else "")
    caption = f"🎬 <b>{tag}</b> 成片　{prepared.size_mb:.1f}MB"
    if prepared.compressed:
        caption += "（已压缩）"

    try:
        with prepared.path.open("rb") as fh:
            await update.message.reply_video(  # type: ignore
                video=fh,
                caption=caption,
                parse_mode="HTML",
                supports_streaming=True,
                read_timeout=120,
                write_timeout=600,
                connect_timeout=60,
                pool_timeout=60,
            )
        await notice.delete()
    except Exception as e:  # noqa: BLE001
        logger.exception("getvideo 发送失败")
        await notice.edit_text(
            fmt.fmt_error(f"发送失败：{e}\n本机路径：`{prepared.path}`"),
            parse_mode="Markdown",
        )


async def cmd_delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _check_admin(update):
        return
    assert _api is not None
    args = ctx.args  # type: ignore
    if not args:
        await update.message.reply_text(fmt.fmt_error("用法：/delete <youtube_id> [slice_index]"), parse_mode="Markdown")  # type: ignore
        return

    youtube_id = args[0].strip()
    slice_index = None
    if len(args) >= 2:
        try:
            slice_index = int(args[1].strip())
        except ValueError:
            await update.message.reply_text(fmt.fmt_error("分集索引 slice_index 必须为整数"), parse_mode="Markdown")  # type: ignore
            return

    if slice_index is not None:
        result = await _api.delete_slice(youtube_id, slice_index)
    else:
        result = await _api.delete_video(youtube_id)

    if result is None:
        await update.message.reply_text(fmt.fmt_api_unavailable(), parse_mode="Markdown")  # type: ignore
        return
    if result.get("success"):
        target_name = f"{youtube_id}_s{slice_index}" if slice_index is not None else youtube_id
        await update.message.reply_text(fmt.fmt_delete_success(target_name), parse_mode="Markdown")  # type: ignore
    else:
        await update.message.reply_text(fmt.fmt_error(result.get("error", "未知错误")), parse_mode="Markdown")  # type: ignore


async def cmd_retry(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _check_admin(update):
        return
    assert _api is not None
    args = ctx.args  # type: ignore
    if not args:
        await update.message.reply_text(fmt.fmt_error("用法：/retry <youtube_id> [slice_index]  或  /retry <小时数>（批量重试最近N小时失败，如 `/retry 24`）"), parse_mode="Markdown")  # type: ignore
        return

    arg0 = args[0].strip()
    # [Claude_Opus_4.8] /retry <小时数>：纯数字(≤3位)→批量重试最近 N 小时内 FAILED；否则按 youtube_id 单条。
    # youtube_id 恒为 11 位含字母，绝不会是 ≤3 位纯数字，故无歧义。
    if arg0.isdigit() and len(arg0) <= 3:
        hours = int(arg0)
        result = await _api.retry_recent(hours)
        if result is None:
            await update.message.reply_text(fmt.fmt_api_unavailable(), parse_mode="Markdown")  # type: ignore
            return
        if result.get("success"):
            n = result.get("count", 0)
            if n:
                items = result.get("items", [])
                sample = "\n".join(f"· {t}" for t in items)
                more = f"\n…等共 {n} 条" if n > len(items) else ""
                msg = f"♻️ *批量重试最近 {hours}h 失败任务*\n已重置 `{n}` 条为 PENDING（≥75 分将由调度器自动重发）。\n{sample}{more}"
            else:
                msg = f"✅ 最近 {hours}h 没有失败任务，无需重试。"
            await update.message.reply_text(msg, parse_mode="Markdown")  # type: ignore
        else:
            await update.message.reply_text(fmt.fmt_error(result.get("error", "未知错误")), parse_mode="Markdown")  # type: ignore
        return

    youtube_id = arg0
    slice_index = None
    if len(args) >= 2:
        try:
            slice_index = int(args[1].strip())
        except ValueError:
            await update.message.reply_text(fmt.fmt_error("分集索引 slice_index 必须为整数"), parse_mode="Markdown")  # type: ignore
            return

    if slice_index is not None:
        result = await _api.retry_slice(youtube_id, slice_index)
    else:
        result = await _api.retry_video(youtube_id)

    if result is None:
        await update.message.reply_text(fmt.fmt_api_unavailable(), parse_mode="Markdown")  # type: ignore
        return
    if result.get("success"):
        if slice_index is not None:
            msg = f"♻️ *切片重试已触发*\n🆔 ID：`{youtube_id}`\n🔢 分集：第 `{slice_index}` 集\n_切片任务已重置为 PENDING，将在满足前导条件后重新触发。_"
        else:
            msg = f"♻️ *重试已触发*\n🆔 ID：`{youtube_id}`\n_视频已重置为 PENDING，管线将在下次调度时处理。_"
        await update.message.reply_text(msg, parse_mode="Markdown")  # type: ignore
    else:
        await update.message.reply_text(fmt.fmt_error(result.get("error", "未知错误")), parse_mode="Markdown")  # type: ignore


async def cmd_tts(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """TTS 当前无业务场景，命令保留为明确提示，绝不创建或改写任务。"""
    if not _check_admin(update):
        return
    await update.message.reply_text(
        "🎙 配音功能当前未启用；视频将保持原声发布。",
        parse_mode="Markdown",
    )  # type: ignore


async def cmd_process(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    # [Claude_Opus_4.8] 确定性单条发布：不经 AI 编排，直接走 web /api/videos/{id}/process
    # （claim 原子抢占 + DISCOVERY 守卫 + 稳健后台 _process_single_video，忽略分数阈值）。
    if not _check_admin(update):
        return
    assert _api is not None
    args = ctx.args  # type: ignore
    if not args:
        await update.message.reply_text(  # type: ignore
            fmt.fmt_error("用法：/process <youtube_id>\n例：/process NSn6uQoPO5U"),
            parse_mode="Markdown",
        )
        return
    youtube_id = args[0].strip()
    result = await _api.process_video(youtube_id)
    if result is None:
        await update.message.reply_text(fmt.fmt_api_unavailable(), parse_mode="Markdown")  # type: ignore
        return
    if result.get("success"):
        await update.message.reply_text(  # type: ignore
            f"🚀 *已开始处理* `{youtube_id}`\n_{result.get('message', '后台执行中，进度见 /queue。')}_",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(  # type: ignore
            fmt.fmt_error(result.get("error", "未知错误")),
            parse_mode="Markdown",
        )


async def cmd_run(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _check_admin(update):
        return
    assert _api is not None
    result = await _api.run_pipeline()
    if result is None:
        await update.message.reply_text(fmt.fmt_api_unavailable(), parse_mode="Markdown")  # type: ignore
        return
    await update.message.reply_text(  # type: ignore
        "🔥 *全量管线已触发*\n_监控频道 → 下载 → 字幕 → 翻译 → 发布，全程在后台执行。_",
        parse_mode="Markdown"
    )


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _check_admin(update):
        return
    assert _api is not None
    stats = await _api.get_stats()
    if stats is None:
        await update.message.reply_text(fmt.fmt_api_unavailable(), parse_mode="Markdown")  # type: ignore
        return
    msg = (
        f"📊 *系统统计*\n\n"
        f"📦 总计：`{stats.get('total', 0)}`\n"
        f"⏳ 待处理：`{stats.get('pending', 0)}`\n"
        f"🔄 处理中：`{stats.get('active', 0)}`\n"
        f"✅ 已发布：`{stats.get('published', 0)}`\n"
        f"❌ 失败：`{stats.get('failed', 0)}`"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")  # type: ignore


async def cmd_deploy(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """[Claude_Opus_4.8] /deploy — 手机远程一键：在主机上把当前分支 git push 到 origin。

    bot 进程跑在主机，用主机 git 凭据非交互推送；GIT_TERMINAL_PROMPT=0 防止无凭据时挂起。
    异步子进程，不阻塞事件循环。仅管理员可用。
    """
    if not _check_admin(update):
        return
    prj_root = str(Path(__file__).parent.parent.parent)
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    await update.message.reply_text("🚀 正在推送当前分支到 origin…", parse_mode="Markdown")  # type: ignore
    try:
        p = await asyncio.create_subprocess_exec(
            "git", "rev-parse", "--abbrev-ref", "HEAD",
            cwd=prj_root, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        out, _ = await p.communicate()
        branch = out.decode(errors="ignore").strip() or "HEAD"
        p = await asyncio.create_subprocess_exec(
            "git", "push", "-u", "origin", branch,
            cwd=prj_root, env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        out, _ = await asyncio.wait_for(p.communicate(), timeout=120)
        tail = out.decode(errors="ignore").strip()[-700:] or "(no output)"
        head = "✅ 已推送" if p.returncode == 0 else f"❌ 推送失败 (exit {p.returncode})"
        # 纯文本回复：git 输出含特殊字符会破坏 Markdown 解析
        await update.message.reply_text(f"{head}  分支 {branch}\n\n{tail}")  # type: ignore
    except asyncio.TimeoutError:
        await update.message.reply_text(  # type: ignore
            "❌ 推送超时(120s)——多半是主机 git 未存凭据在等输入。请在主机配置 credential helper / token 后重试。")
    except Exception as e:  # noqa: BLE001
        await update.message.reply_text(f"❌ /deploy 异常：{e}")  # type: ignore


async def cmd_whole(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/whole <url> [开始时间] [结束时间] — 强制不分集发布"""
    if not _check_admin(update):
        return
    assert _api is not None
    args = ctx.args  # type: ignore
    if not args:
        await update.message.reply_text(fmt.fmt_error("用法：/whole <youtube_url> [开始时间] [结束时间]"), parse_mode="Markdown")  # type: ignore
        return

    url_input = args[0].strip()
    match = _YOUTUBE_RE.search(url_input)
    if not match:
        await update.message.reply_text(fmt.fmt_error("请输入有效的 YouTube 视频链接！"), parse_mode="Markdown")  # type: ignore
        return
    url = match.group(0)

    trim_start, trim_end = None, None
    if len(args) >= 2:
        remaining_text = " ".join(args[1:])
        trim_start, trim_end = parse_trim_params(remaining_text)

    await update.message.reply_text(f"🔍 *正在验证视频并设置为整片制作...*\n`{url}`", parse_mode="Markdown")  # type: ignore

    result = await _api.add_video(url, trim_start=trim_start, trim_end=trim_end, disable_slicing=True)

    if result is None:
        await update.message.reply_text(fmt.fmt_api_unavailable(), parse_mode="Markdown")  # type: ignore
        return

    if result.get("success"):
        t_start = result.get("trim_start")
        t_end = result.get("trim_end")
        await update.message.reply_text(  # type: ignore
            f"✅ *已加入队列（整片制作/不切片）！*\n"
            f"📌 标题：`{result['title']}`\n"
            f"🆔 ID：`{result['video_id']}`\n"
            f"⏱ 裁剪：`{t_start or '0'} - {t_end or 'End'}`",
            parse_mode="Markdown"
        )
    elif result.get("already_exists"):
        video_id = result.get("video_id")
        # [Claude_Sonnet_4.6_Thinking_planning] /whole: 有 trim 参数时 respec（保持整片模式）
        if (trim_start or trim_end) and video_id:
            await _handle_respec(update, _api, video_id, trim_start, trim_end, disable_slicing=True)
        else:
            await update.message.reply_text(  # type: ignore
                fmt.fmt_video_exists(
                    title=result.get("error", ""),
                    status=result.get("current_status", "UNKNOWN"),
                ),
                parse_mode="Markdown",
            )
    else:
        await update.message.reply_text(fmt.fmt_error(result.get("error", "未知错误")), parse_mode="Markdown")  # type: ignore


async def cmd_slice(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/slice <url> [开始时间] [结束时间] — 强制允许切片发布（若支持）"""
    if not _check_admin(update):
        return
    assert _api is not None
    args = ctx.args  # type: ignore
    if not args:
        await update.message.reply_text(fmt.fmt_error("用法：/slice <youtube_url> [开始时间] [结束时间]"), parse_mode="Markdown")  # type: ignore
        return

    url_input = args[0].strip()
    match = _YOUTUBE_RE.search(url_input)
    if not match:
        await update.message.reply_text(fmt.fmt_error("请输入有效的 YouTube 视频链接！"), parse_mode="Markdown")  # type: ignore
        return
    url = match.group(0)

    trim_start, trim_end = None, None
    if len(args) >= 2:
        remaining_text = " ".join(args[1:])
        trim_start, trim_end = parse_trim_params(remaining_text)

    await update.message.reply_text(f"🔍 *正在验证视频并设置为切片制作...*\n`{url}`", parse_mode="Markdown")  # type: ignore

    result = await _api.add_video(url, trim_start=trim_start, trim_end=trim_end, disable_slicing=False)

    if result is None:
        await update.message.reply_text(fmt.fmt_api_unavailable(), parse_mode="Markdown")  # type: ignore
        return

    if result.get("success"):
        t_start = result.get("trim_start")
        t_end = result.get("trim_end")
        await update.message.reply_text(  # type: ignore
            f"✅ *已加入队列（允许切片分集）！*\n"
            f"📌 标题：`{result['title']}`\n"
            f"🆔 ID：`{result['video_id']}`\n"
            f"⏱ 裁剪：`{t_start or '0'} - {t_end or 'End'}`",
            parse_mode="Markdown"
        )
    elif result.get("already_exists"):
        video_id = result.get("video_id")
        # [Claude_Sonnet_4.6_Thinking_planning] /slice: 有 trim 参数时 respec（保持切片模式）
        if (trim_start or trim_end) and video_id:
            await _handle_respec(update, _api, video_id, trim_start, trim_end, disable_slicing=False)
        else:
            await update.message.reply_text(  # type: ignore
                fmt.fmt_video_exists(
                    title=result.get("error", ""),
                    status=result.get("current_status", "UNKNOWN"),
                ),
                parse_mode="Markdown",
            )
    else:
        await update.message.reply_text(fmt.fmt_error(result.get("error", "未知错误")), parse_mode="Markdown")  # type: ignore


def _normalize_time(t: str) -> str:
    """[Claude_Sonnet_4.6_Thinking_planning] 将 M'S 格式标准化为 M:S（冒号格式）。

    例：\"1'10\" → \"1:10\"，\"2'05\" → \"2:05\"
    对已是标准格式（如 \"70\"、\"1:10\"）的字符串无副作用。
    """
    return re.sub(r"(\d+)'(\d+)", r"\1:\2", t)


def parse_trim_params(text: str) -> tuple[str | None, str | None]:
    """[v1.3.0] 智能提取移动端极简裁剪参数

    支持格式：
      - 链接 38 14:43 (空格分隔，推荐)
      - 链接 38 883 (纯秒数)
      - 链接 30 (仅设起始时间)
      - 链接 -300 (仅设结束时间)
      - 链接 30 到 120 (自然语言)
      - 链接 38-14:43 (传统连字符)
      - 链接 0 1'10 (M'S 分秒格式，移动端友好) [Claude_Sonnet_4.6_Thinking_planning]
    """
    text = text.strip()
    if not text:
        return None, None

    # Case 1: 仅设置结束时间，如 "-14:43" 或 "-883"
    if text.startswith('-') or text.startswith('~') or text.startswith('to') or text.startswith('到'):
        clean = re.sub(r'^[\s\-~to到,，]+', '', text)
        clean = _normalize_time(clean)  # [Claude_Sonnet_4.6_Thinking_planning] 支持 M'S 格式
        return None, (clean if re.match(r'^[0-9:.]+$', clean) else None)

    # Case 2: 分隔符拆分，支持 空格、连字符、中文"到"、英文"to"、逗号等
    parts = [p.strip() for p in re.split(r'[\s\-—~to到,，]+', text) if p.strip()]
    if len(parts) >= 2:
        start, end = parts[0], parts[1]
        start = _normalize_time(start)  # [Claude_Sonnet_4.6_Thinking_planning] 支持 M'S 格式
        end   = _normalize_time(end)
        start = start if re.match(r'^[0-9:.]+$', start) else None
        end   = end   if re.match(r'^[0-9:.]+$', end)   else None
        return start, end
    elif len(parts) == 1:
        # 仅设置开始时间
        start = _normalize_time(parts[0])  # [Claude_Sonnet_4.6_Thinking_planning] 支持 M'S 格式
        start = start if re.match(r'^[0-9:.]+$', start) else None
        return start, None

    return None, None



async def _handle_respec(
    update: Update,
    api: PipelineAPIClient,
    video_id: str,
    trim_start: str | None,
    trim_end: str | None,
    disable_slicing: bool = True,
    tts_provider: str | None = None,
) -> None:
    """[Claude_Sonnet_4.6_Thinking_planning] 统一处理 respec 响应并回复用户。

    小工具函数，封装调用 respec API、解析结果、回复用户的全流程。
    由 handle_youtube_url / cmd_whole / cmd_slice / cmd_tts 共用。
    """
    respec = await api.respec_video(
        video_id,
        trim_start=trim_start,
        trim_end=trim_end,
        disable_slicing=disable_slicing,
        tts_provider=tts_provider,
    )
    if respec is None:
        await update.message.reply_text(fmt.fmt_api_unavailable(), parse_mode="Markdown")  # type: ignore
        return
    if respec.get("success"):
        t_start   = respec.get("trim_start")
        t_end     = respec.get("trim_end")
        stop_note = "⚠️ _原进程已中止_\n" if respec.get("was_stopped") else ""
        tts_note  = f"🎙 配音：`{tts_provider}`\n" if tts_provider else ""
        await update.message.reply_text(  # type: ignore
            f"🔄 *规格已更新，重新触发！*\n"
            f"{stop_note}"
            f"📌 标题：`{respec.get('title', '')}`\n"
            f"⏱ 裁剪：`{t_start or '0'}` 至 `{t_end or 'End'}`\n"
            f"{tts_note}",
            parse_mode="Markdown",
        )
    else:
        err = respec.get("error", "未知错误")
        await update.message.reply_text(  # type: ignore
            fmt.fmt_error(f"规格更新失败：{err}"),
            parse_mode="Markdown",
        )


async def handle_youtube_url(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """监听所有消息，检测 YouTube URL，自动提交加急队列。"""
    if not _check_admin(update):
        return
    assert _api is not None
    text = update.message.text or update.message.caption or ""
    logger.info(f"收到文本: {text}")
    
    match = _YOUTUBE_RE.search(text)
    if not match:
        logger.info("未检测到有效 YouTube URL")
        return

    url = match.group(0)
    
    # 提取裁剪区间：从文本中剔除 URL 后进行智能解析
    remaining_text = text.replace(url, "").strip()
    trim_start, trim_end = parse_trim_params(remaining_text)
    if trim_start or trim_end:
        logger.info(f"Telegram 智能解析到裁剪区间: start={trim_start}, end={trim_end}")

    await update.message.reply_text(f"🔍 *正在验证视频...*\n`{url}`", parse_mode="Markdown")  # type: ignore

    result = await _api.add_video(url, trim_start=trim_start, trim_end=trim_end, disable_slicing=True)

    if result is None:
        await update.message.reply_text(fmt.fmt_api_unavailable(), parse_mode="Markdown")  # type: ignore
        return

    if result.get("success"):
        t_start = result.get("trim_start")
        t_end = result.get("trim_end")
        await update.message.reply_text(  # type: ignore
            fmt.fmt_video_added(result["title"], result["video_id"], trim_start=t_start, trim_end=t_end),
            parse_mode="Markdown"
        )
    elif result.get("already_exists"):
        video_id       = result.get("video_id")
        current_status = result.get("current_status", "UNKNOWN")
        # [Claude_Sonnet_4.6_Thinking_planning] 有裁剪参数 + 状态可覆盖 → 自动 respec
        if (trim_start or trim_end) and video_id:
            await _handle_respec(update, _api, video_id, trim_start, trim_end, disable_slicing=True)
        else:
            await update.message.reply_text(  # type: ignore
                fmt.fmt_video_exists(
                    title=result.get("error", ""),
                    status=current_status,
                ),
                parse_mode="Markdown",
            )
    else:
        await update.message.reply_text(  # type: ignore
            fmt.fmt_error(result.get("error", "未知错误")),
            parse_mode="Markdown"
        )


# ── AI Agent 消息接收与响应 ───────────────────────────────────────────────

_busy_chats: set[int] = set()


async def handle_agent_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """接收 Telegram 的任何消息，由 AI Agent 直接接收并响应（除 /help 和 /start 外）"""
    if not _check_admin(update):
        return

    chat_id = update.effective_chat.id
    user_message = update.message.text or update.message.caption or ""
    if not user_message.strip():
        return

    if _is_daily_brief_request(user_message):
        try:
            report = await asyncio.to_thread(collect_daily_brief)
            await _reply_html_chunks(update.message, report)
        except Exception as e:  # noqa: BLE001
            logger.exception("daily brief generation failed")
            await update.message.reply_text(
                fmt.fmt_error(f"今日简报生成失败：{type(e).__name__}"),
                parse_mode="Markdown",
            )
        return

    # 并发锁：如果该 chat 已经在运行 Agent 任务，提示等待
    if chat_id in _busy_chats:
        await update.message.reply_text(
            "⏳ *AI Agent 正在处理前一个任务。* 请稍候，处理完成后再发送新消息。",
            parse_mode="Markdown"
        )
        return

    _busy_chats.add(chat_id)
    # [Gemini_3.5_Flash_High_planning] 发送初始状态提示
    ack_msg = await update.message.reply_text(
        "🧠 *AI Agent 已接收指令，正在决策...*",
        parse_mode="Markdown"
    )

    try:
        # 在独立的线程中执行 Agent function calling 循环，防止阻碍 bot 的事件循环
        agent = PipelineAgent(bot=ctx.bot, loop=asyncio.get_running_loop(), chat_id=chat_id)
        response_text = await asyncio.to_thread(agent.run, user_message)

        if response_text:
            try:
                # 尝试以 HTML 格式回复（Agent 生成的消息中可能包含 HTML 样式）
                await update.message.reply_text(response_text, parse_mode="HTML")
            except Exception as html_err:
                logger.warning(f"Failed to send agent response as HTML: {html_err}, falling back to plain text")
                # 兜底：纯文本模式
                await update.message.reply_text(response_text)
    except Exception as e:
        logger.error(f"Agent execution error: {e}")
        await update.message.reply_text(f"❌ *AI Agent 运行异常*:\n`{e}`", parse_mode="Markdown")
    finally:
        _busy_chats.discard(chat_id)
        try:
            # 尝试删除最初的提示消息，保持聊天界面整洁
            await ack_msg.delete()
        except Exception:
            pass


# ── 入口 ─────────────────────────────────────────────────────────────────

def main() -> None:
    global _api, _admin_ids

    token, _admin_ids = _load_config()
    _api = PipelineAPIClient()

    logger.info(f"🤖 Bot 正在启动，管理员白名单：{_admin_ids}")

    # [Claude_Opus_4.8] concurrent_updates(True)：默认串行处理 update，一条 14s 的
    # AI Agent 消息会把后续所有消息/命令(含忙提示)压住十几秒 → 表现为「无响应」。
    # 开并发后每条 update 独立成 task，慢 agent 不再 head-of-line 阻塞其它消息。
    # pool_timeout 默认仅 1s，网络/代理一抖就抛 Pool timeout 导致回复发不出，放宽到 20s。
    # [Claude_Opus_4.8] 根治 httpx PoolTimeout 崩溃循环：concurrent_updates(True) 下多 handler 并发，
    # 但默认连接池仅 1 条 → getUpdates/sendMessage 抢不到连接 → PoolTimeout 抛进 updater 轮询循环 →
    # Application 停止（日志「Application is stopping」+ 频繁重启 487 次，表现为「/命令无反应」）。
    # 显式放大主连接池(256)与 getUpdates 专用池(16)，并放宽各自 pool_timeout。
    app = (
        Application.builder()
        .token(token)
        .concurrent_updates(True)
        .post_init(_configure_bot_menu)
        .connection_pool_size(256)
        .pool_timeout(20)
        .get_updates_connection_pool_size(16)
        .get_updates_pool_timeout(20)
        .read_timeout(30)
        .write_timeout(60)
        .connect_timeout(15)
        .build()
    )

    # 注册命令（直接由程序接管，不消耗 API 限额）
    app.add_handler(CommandHandler("start", cmd_help))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("queue", cmd_queue))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("wechat_login", cmd_wechat_login))
    app.add_handler(CommandHandler("published", cmd_published))
    app.add_handler(CommandHandler("getvideo", cmd_getvideo))  # [Claude_Opus_4.8] 发回成片（超 50MB 自动压缩）
    app.add_handler(CommandHandler("delete", cmd_delete))
    app.add_handler(CommandHandler("retry", cmd_retry))
    app.add_handler(CommandHandler("process", cmd_process))  # [Claude_Opus_4.8] 确定性单条发布：/process <youtube_id>
    app.add_handler(CommandHandler("run", cmd_run))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("deploy", cmd_deploy))  # [Claude_Opus_4.8] 手机远程一键 git push 当前分支
    app.add_handler(CommandHandler("whole", cmd_whole))
    app.add_handler(CommandHandler("slice", cmd_slice))
    app.add_handler(CommandHandler("highlight", cmd_highlight))
    app.add_handler(CommandHandler("english_world", cmd_english_world))
    app.add_handler(CommandHandler("tts", cmd_tts))  # [Claude_Sonnet_4.6_Thinking_planning] 按需 TTS 配音命令
    app.add_handler(CallbackQueryHandler(handle_highlight_callback, pattern=r"^hl:"))
    app.add_handler(CallbackQueryHandler(handle_english_world_callback, pattern=r"^ew:"))

    # 监听 YouTube URL 并由程序接管自动提交（不消耗 API 限额）
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(_YOUTUBE_RE), handle_youtube_url))

    # 监听所有其他文本消息（由 AI Agent 统一接收并处理，如闲聊问答）
    app.add_handler(MessageHandler(filters.TEXT, handle_agent_message))

    logger.info("✅ Bot 已就绪，开始轮询...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
