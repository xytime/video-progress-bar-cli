"""src/bot/telegram_bot.py — Telegram Bot 主程序

消息路由 + admin 鉴权 + API 调用编排。
依赖 auth.py / formatter.py / api_client.py，各模块完全解耦。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-05-22 | Claude_Sonnet_4.6_Thinking_planning | 初始创建，TDD Green phase 生产代码 |
"""
from __future__ import annotations

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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)
logger = logging.getLogger("telegram_bot")

_YOUTUBE_RE = re.compile(r"https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)[\w\-]+")


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
    # [Claude_Sonnet_4.6_Thinking_planning] P0修复：get_videos 断线返回 []，用长度+stats 双重判断
    stats = await _api.get_stats()
    if stats is None:
        await update.message.reply_text(fmt.fmt_api_unavailable(), parse_mode="Markdown")  # type: ignore
        return
    pending = await _api.get_videos(tab="waitlist", size=10)
    processing = await _api.get_videos(tab="processing", size=5)
    videos = processing + pending
    await update.message.reply_text(fmt.fmt_queue(videos), parse_mode="Markdown")  # type: ignore


async def cmd_published(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _check_admin(update):
        return
    assert _api is not None
    videos = await _api.get_videos(tab="published", size=5)
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
        await update.message.reply_text(fmt.fmt_error("用法：/delete <youtube_id>"), parse_mode="Markdown")  # type: ignore
        return

    youtube_id = args[0].strip()
    result = await _api.delete_video(youtube_id)
    if result is None:
        await update.message.reply_text(fmt.fmt_api_unavailable(), parse_mode="Markdown")  # type: ignore
        return
    if result.get("success"):
        await update.message.reply_text(fmt.fmt_delete_success(youtube_id), parse_mode="Markdown")  # type: ignore
    else:
        await update.message.reply_text(fmt.fmt_error(result.get("error", "未知错误")), parse_mode="Markdown")  # type: ignore


async def cmd_retry(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _check_admin(update):
        return
    assert _api is not None
    args = ctx.args  # type: ignore
    if not args:
        await update.message.reply_text(fmt.fmt_error("用法：/retry <youtube_id>"), parse_mode="Markdown")  # type: ignore
        return

    youtube_id = args[0].strip()
    result = await _api.retry_video(youtube_id)
    if result is None:
        await update.message.reply_text(fmt.fmt_api_unavailable(), parse_mode="Markdown")  # type: ignore
        return
    if result.get("success"):
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


# ── YouTube URL 无感提交 ─────────────────────────────────────────────────

async def handle_youtube_url(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """监听所有消息，检测 YouTube URL，自动提交加急队列。"""
    if not _check_admin(update):
        return
    assert _api is not None
    text = update.message.text or ""  # type: ignore
    match = _YOUTUBE_RE.search(text)
    if not match:
        return

    url = match.group(0)
    await update.message.reply_text(f"🔍 *正在验证视频...*\n`{url}`", parse_mode="Markdown")  # type: ignore

    result = await _api.add_video(url)

    if result is None:
        await update.message.reply_text(fmt.fmt_api_unavailable(), parse_mode="Markdown")  # type: ignore
        return

    if result.get("success"):
        await update.message.reply_text(  # type: ignore
            fmt.fmt_video_added(result["title"], result["video_id"]),
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


# ── 入口 ─────────────────────────────────────────────────────────────────

def main() -> None:
    global _api, _admin_ids

    token, _admin_ids = _load_config()
    _api = PipelineAPIClient()

    logger.info(f"🤖 Bot 正在启动，管理员白名单：{_admin_ids}")

    app = Application.builder().token(token).build()

    # 注册命令
    app.add_handler(CommandHandler("start", cmd_help))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("queue", cmd_queue))
    app.add_handler(CommandHandler("status", cmd_queue))
    app.add_handler(CommandHandler("published", cmd_published))
    app.add_handler(CommandHandler("delete", cmd_delete))
    app.add_handler(CommandHandler("retry", cmd_retry))
    app.add_handler(CommandHandler("run", cmd_run))
    app.add_handler(CommandHandler("stats", cmd_stats))

    # 监听所有文本消息（YouTube URL 无感提交），优先级低于命令处理器
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_youtube_url))

    logger.info("✅ Bot 已就绪，开始轮询...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
