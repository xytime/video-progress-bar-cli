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
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application,
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)
logger = logging.getLogger("telegram_bot")

_YOUTUBE_RE = re.compile(r"https?://(?:(?:www|m)\.)?(?:youtube\.com/(?:watch\?.*v=|shorts/)|youtu\.be/)[\w\-]+")


def _load_config() -> tuple[str, set[int]]:
    """加载并强验证所有必要配置。Fail-Closed: 任何问题直接 sys.exit。"""
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent.parent / ".env")

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

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _check_admin(update):
        return
    await update.message.reply_text(fmt.fmt_help(), parse_mode="Markdown")  # type: ignore


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
    """/status 指令：宏观的全局状态汇报
    
    # [Gemini_3.5_Flash_fast] 新增的宏观状态指令逻辑
    """
    if not _check_admin(update):
        return
    assert _api is not None
    stats = await _api.get_stats()
    if stats is None:
        await update.message.reply_text(fmt.fmt_api_unavailable(), parse_mode="Markdown")  # type: ignore
        return
    pending = await _api.get_videos(tab="waitlist", size=5)
    processing = await _api.get_videos(tab="active", size=5)
    
    if pending is None or processing is None:
        await update.message.reply_text(fmt.fmt_api_unavailable(), parse_mode="Markdown")  # type: ignore
        return
        
    msg = fmt.fmt_status_report(stats, processing, pending)
    await update.message.reply_text(msg, parse_mode="Markdown")



async def cmd_published(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _check_admin(update):
        return
    assert _api is not None
    videos = await _api.get_videos(tab="completed", size=5)
    if videos is None:
        await update.message.reply_text(fmt.fmt_api_unavailable(), parse_mode="Markdown")  # type: ignore
        return
    await update.message.reply_text(fmt.fmt_published(videos), parse_mode="Markdown")  # type: ignore


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
        await update.message.reply_text(fmt.fmt_error("用法：/retry <youtube_id> [slice_index]"), parse_mode="Markdown")  # type: ignore
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


def parse_trim_params(text: str) -> tuple[str | None, str | None]:
    """[v1.3.0] 智能提取移动端极简裁剪参数

    支持格式：
      - 链接 38 14:43 (空格分隔，推荐)
      - 链接 38 883 (纯秒数)
      - 链接 30 (仅设起始时间)
      - 链接 -300 (仅设结束时间)
      - 链接 30 到 120 (自然语言)
      - 链接 38-14:43 (传统连字符)
    """
    text = text.strip()
    if not text:
        return None, None

    # Case 1: 仅设置结束时间，如 "-14:43" 或 "-883"
    if text.startswith('-') or text.startswith('~') or text.startswith('to') or text.startswith('到'):
        clean = re.sub(r'^[\s\-~to到,，]+', '', text)
        return None, (clean if re.match(r'^[0-9:.]+$', clean) else None)

    # Case 2: 分隔符拆分，支持 空格、连字符、中文"到"、英文"to"、逗号等
    parts = [p.strip() for p in re.split(r'[\s\-—~to到,，]+', text) if p.strip()]
    if len(parts) >= 2:
        start, end = parts[0], parts[1]
        start = start if re.match(r'^[0-9:.]+$', start) else None
        end = end if re.match(r'^[0-9:.]+$', end) else None
        return start, end
    elif len(parts) == 1:
        # 仅设置开始时间
        start = parts[0]
        start = start if re.match(r'^[0-9:.]+$', start) else None
        return start, None

    return None, None


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

    result = await _api.add_video(url, trim_start=trim_start, trim_end=trim_end)

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
        # [Claude_Sonnet_4.6_Thinking_planning] P0修复：error 字段是错误描述，不是标题
        # 用 current_status 展示状态，标题从 error 字段中提取或降级显示
        raw_error = result.get("error", "")
        # API 返回格式："视频已在队列中（当前状态：XXX）：[Title]"
        # 安全降级：直接展示 error 原文作为标题上下文
        await update.message.reply_text(  # type: ignore
            fmt.fmt_video_exists(
                title=raw_error,
                status=result.get("current_status", "UNKNOWN")
            ),
            parse_mode="Markdown"
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

    app = Application.builder().token(token).build()

    # 注册命令（直接由程序接管，不消耗 API 限额）
    app.add_handler(CommandHandler("start", cmd_help))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("queue", cmd_queue))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("published", cmd_published))
    app.add_handler(CommandHandler("delete", cmd_delete))
    app.add_handler(CommandHandler("retry", cmd_retry))
    app.add_handler(CommandHandler("run", cmd_run))
    app.add_handler(CommandHandler("stats", cmd_stats))

    # 监听 YouTube URL 并由程序接管自动提交（不消耗 API 限额）
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(_YOUTUBE_RE), handle_youtube_url))

    # 监听所有其他文本消息（由 AI Agent 统一接收并处理，如闲聊问答）
    app.add_handler(MessageHandler(filters.TEXT, handle_agent_message))

    logger.info("✅ Bot 已就绪，开始轮询...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
