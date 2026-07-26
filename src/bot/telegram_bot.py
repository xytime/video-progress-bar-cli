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
"""
from __future__ import annotations

import asyncio
import json
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
from bot.video_delivery import (
    prepare_for_delivery,
    finished_video_path,
    FinishedVideoNotFound,
    CompressionError,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)
logger = logging.getLogger("telegram_bot")

# [Gemini_3.5_Flash_planning] 优化正则匹配，包含整个带参数的 URL (排除末尾标点)，并支持 live/ 路径
_YOUTUBE_RE = re.compile(r"https?://(?:(?:www|m)\.)?(?:youtube\.com/(?:watch\?.*v=|shorts/|live/)|youtu\.be/)[^\s]+(?<![.,!?;:\)\"\'\]\}])")


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
    """/status 指令：手机端值班面板。"""
    if not _check_admin(update):
        return
    assert _api is not None
    stats = await _api.get_stats()
    if stats is None:
        await update.message.reply_text(fmt.fmt_api_unavailable(), parse_mode="Markdown")  # type: ignore
        return
    wechat = await _api.get_wechat_status()
    queue = await _api.get_videos(tab="queue", size=5)
    pending = await _api.get_videos(tab="waitlist", size=5)
    processing = await _api.get_videos(tab="active", size=5)
    error_page = await _api.get_video_page(tab="error", size=3)
    retry24_preview = await _api.retry_recent_preview(24)
    retry48_preview = await _api.retry_recent_preview(48)
    
    if queue is None or pending is None or processing is None or error_page is None or retry24_preview is None or retry48_preview is None:
        await update.message.reply_text(fmt.fmt_api_unavailable(), parse_mode="Markdown")  # type: ignore
        return
        
    msg = fmt.fmt_status_report(
        stats,
        processing,
        queue,
        pending,
        error_page.get("videos", []),
        wechat,
        error_total=error_page.get("total_count", 0),
        retry24_count=retry24_preview.get("count", 0),
        retry48_count=retry48_preview.get("count", 0),
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


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
    app.add_handler(CommandHandler("tts", cmd_tts))  # [Claude_Sonnet_4.6_Thinking_planning] 按需 TTS 配音命令

    # 监听 YouTube URL 并由程序接管自动提交（不消耗 API 限额）
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(_YOUTUBE_RE), handle_youtube_url))

    # 监听所有其他文本消息（由 AI Agent 统一接收并处理，如闲聊问答）
    app.add_handler(MessageHandler(filters.TEXT, handle_agent_message))

    logger.info("✅ Bot 已就绪，开始轮询...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
