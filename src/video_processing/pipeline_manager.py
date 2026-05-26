"""自动化管线调度器 - 协调监测、评分、加工与通知流转

# Modification History
| Version | Date       | Author                              | Description                                                                    |
|---------|------------|-------------------------------------|--------------------------------------------------------------------------------|
| 1.0.0   | 2026-05-21 | Gemini_3.1_Pro_High_planning        | 初始创建 PipelineManager，实现完整的 FSM 调度                                   |
| 1.1.0   | 2026-05-21 | Gemini_3.5_Flash_planning           | 整合 Phase 5：文案生成与视频号全自动发布流                                       |
| 1.2.0   | 2026-05-21 | Claude_Sonnet_4.6_Thinking_planning | 地基重构：消灭裸 SQL + os.environ 泄漏                                           |
| 1.3.0   | 2026-05-21 | Claude_Sonnet_4.6_Thinking_planning | 专项审查：路径常量类级化、os 顶层导入、动态扩展名检测                            |
| 1.4.0   | 2026-05-22 | Claude_Sonnet_4.6_Thinking_planning | 断点续传检查点、封面生成步骤、硬重置接口、完整上传参数                           |
| 2.0.0   | 2026-05-26 | Claude_Sonnet_4.6_Thinking_planning | [v7.0 Phase 3] Popen+os.setsid 进程组隔离、PID 追踪、SIGTERM handler、评分锁防覆盖 |
| 2.0.1   | 2026-05-26 | Claude_Sonnet_4.6_Thinking_planning | [v7.0 Review Fix] BUG-1:移除线程内 signal.signal(); BUG-2:重置 _sigterm_received; BUG-3:upload 用 _run_tracked; LINT-4:math 顶层 import |
| 2.0.2   | 2026-05-26 | Gemini_3.5_Flash_planning           | [v7.0 Phase 6 CON-1] 修复 open() 成功但 flock() 失败时 lock_file 的句柄泄露 |
| 2.1.0   | 2026-05-26 | Gemini_3.5_Flash_planning           | [v7.0 Censor Engine] 整合安全过滤引擎，新增三道违禁词拦截检查点，并捕获锁异常 |
"""

import os
import math
import signal
import time
import logging
import subprocess
import requests
import fcntl
from typing import Dict, Any, Optional
from pathlib import Path

from .db import PipelineDB
from config.settings import settings

logger = logging.getLogger(__name__)

# [Claude_Sonnet_4.6_Thinking_planning] v7.0: 模块级 SIGTERM 信号处理器
# 当该进程收到 SIGTERM 时，设置此标志位，由主循环在安全点检查并执行清理退出。
# 注意：signal handler 只能做最简单的操作（设置标志位），不能在 handler 内直接操作数据库或锁。
_sigterm_received: bool = False


def _sigterm_handler(signum: int, frame) -> None:  # noqa: ANN001
    """SIGTERM 信号处理器 — 设置模块级标志位，由主流程在安全点响应。"""
    global _sigterm_received
    _sigterm_received = True
    logger.warning("[SIGTERM] Signal received. Will clean up at next safe checkpoint.")

# 非视频文件后缀（下载产物中排除）
_NON_VIDEO_SUFFIXES = {'.description', '.json', '.ytdl', '.part', '.jpg', '.png', '.webp'}
# 系统代理 key，yt-dlp 子进程清除以防代理未运行时 connection refused
_PROXY_KEYS = frozenset({
    'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY',
    'http_proxy', 'https_proxy', 'all_proxy',
})


class PipelineManager:
    # 路径常量 — 类级，避免每次调用重算
    _PRJ_ROOT    = Path(__file__).parent.parent.parent
    _SRC_DIR     = _PRJ_ROOT / "src"
    _VENV_PYTHON = str(_PRJ_ROOT / ".venv" / "bin" / "python")
    _VENV_YTDLP  = str(_PRJ_ROOT / ".venv" / "bin" / "yt-dlp")
    _OUT_DIR     = _PRJ_ROOT / "output"

    def __init__(self, db_path: str = "pipeline.db"):
        self.db = PipelineDB(db_path)
        self._OUT_DIR.mkdir(exist_ok=True)
        self.telegram_token   = settings.telegram_bot_token
        self.telegram_chat_id = settings.telegram_chat_id

    # ── Telegram 通知 ─────────────────────────────────────────────────────────

    def send_telegram_msg(self, text: str):
        if not self.telegram_token or not self.telegram_chat_id:
            logger.debug(f"Telegram not configured. Would send: {text}")
            return
        try:
            requests.post(
                f"https://api.telegram.org/bot{self.telegram_token}/sendMessage",
                json={"chat_id": self.telegram_chat_id, "text": text, "parse_mode": "HTML"},
                timeout=10,
            )
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")

    # ── 评分 ──────────────────────────────────────────────────────────────────

    def score_pending_videos(self):
        """对 PENDING 且 score < 75 的视频自动评分（不覆盖人工调分）"""
        # [Claude_Sonnet_4.6_Thinking_planning] LINT-4 修复: math 已移至模块顶层导入
        pending  = self.db.get_videos_by_status("PENDING")
        to_score = [v for v in pending if v.get('score', 0) < 75]
        skipped  = len(pending) - len(to_score)
        if skipped:
            logger.info(f"Skipping {skipped} already-prioritized videos (score >= 75).")
        if not to_score:
            return

        logger.info(f"Scoring {len(to_score)} pending videos...")
        for video in to_score:
            yid        = video['youtube_id']
            view_count = video.get('view_count') or 0
            like_count = video.get('like_count') or 0
            views      = max(0, view_count)
            likes      = max(0, like_count)

            if views <= 0:
                score = 0
            else:
                like_rate = min(100.0, likes / views * 100)
                if views > 2000 and like_rate > 3.5:
                    # [Claude_Sonnet_4.6_Thinking_planning] 满足热度门槛：对数加权评分 [80, 95]
                    v_bonus = min(10.0, 5 * math.log10(views / 2000))
                    l_bonus = min(5.0, 5 * (like_rate - 3.5) / 6.5)
                    score   = max(80, min(95, round(80 + v_bonus + l_bonus)))
                else:
                    # 未满足门槛：比例评分 [0, 70]
                    v_ratio = min(1.0, views / 2000)
                    l_ratio = min(1.0, like_rate / 3.5) if like_rate > 0 else 0.0
                    score   = max(0, min(70, round(70 * v_ratio * l_ratio)))

            logger.info(f"  [{yid}] views={views} like_rate={likes/views*100:.1f}% → score={score}" if views > 0 else f"  [{yid}] no view data → score=0")
            # force=False：自动算分，is_manually_scored=1 的记录会被 DB 层自动跳过
            self.db.update_video_score(yid, score, force=False)

    # ── 批量触发 ──────────────────────────────────────────────────────────────

    def process_high_score_videos(self, limit: int = 5):
        """拉取高分视频进入加工流转"""
        targets = self.db.get_high_score_pending_videos(min_score=75, limit=limit)
        
        # [Gemini_3.1_Pro_High] 防竞态：尝试抢占，避免与 API 手工触发冲突
        claimed_targets = []
        for video in targets:
            if self.db.claim_video_for_processing(video['youtube_id']):
                claimed_targets.append(video)
                
        if not claimed_targets:
            logger.info("No high-score videos available for processing.")
            return
            
        self.send_telegram_msg(
            f"🚀 <b>Pipeline Started</b>\nToday's quota: {len(claimed_targets)} videos."
        )
        for video in claimed_targets:
            self._process_single_video(video)

    # ── 工具方法 ──────────────────────────────────────────────────────────────

    def reset_video_artifacts(self, yid: str) -> list:
        """硬重置：删除指定视频所有产物文件，返回已删除文件名列表。
        调用后配合 db.update_video_status(yid, 'PENDING') 完成完全重置。
        """
        deleted = []
        for pat in [
            f"{yid}.*",
            f"{yid}_vertical.mp4",
            f"{yid}_copy.txt",
            f"{yid}_title.txt",
            f"{yid}_category.txt",
            f"{yid}_cover.jpg",
        ]:
            for f in self._OUT_DIR.glob(pat):
                try:
                    f.unlink()
                    deleted.append(f.name)
                    logger.info(f"[HARD RESET] Deleted: {f.name}")
                except Exception as e:
                    logger.warning(f"Cannot delete {f.name}: {e}")
        return deleted

    def _find_downloaded_video(self, yid: str) -> Optional[str]:
        """glob 查找下载后的视频主文件（排除附属文件，要求 >50KB）"""
        candidates = [
            f for f in self._OUT_DIR.glob(f"{yid}.*")
            if f.suffix not in _NON_VIDEO_SUFFIXES and f.stat().st_size > 50_000
        ]
        return str(candidates[0]) if candidates else None

    # ── 子进程辅助（v7.0: Popen + 进程组隔离）────────────────────────────────

    def _run_tracked(self, cmd: list, yid: str, **kwargs) -> subprocess.CompletedProcess:
        """以独立进程组运行命令，并将 PGID 写入数据库，供 API 层 SIGTERM 精准击杀。

        [Claude_Sonnet_4.6_Thinking_planning] v7.0 关键设计：
        - os.setsid() 在子进程建立独立的会话（Session Leader），
          使 os.killpg(pgid, SIGTERM) 只击杀该子进程组，不波及 FastAPI 父进程。
        - 仅当 settings.enable_sigterm_kill=True 时启用 PID 追踪（Feature Flag 保护）。
        """
        if settings.enable_sigterm_kill:
            proc = subprocess.Popen(
                cmd,
                preexec_fn=os.setsid,  # 建立独立进程组
                **kwargs
            )
            try:
                pgid = os.getpgid(proc.pid)
                self.db.update_process_pid(yid, pgid)
            except ProcessLookupError:
                pass  # 进程已极速退出，无需记录
            stdout, stderr = proc.communicate()
            if proc.returncode != 0:
                raise subprocess.CalledProcessError(
                    proc.returncode, cmd,
                    output=stdout, stderr=stderr,
                )
            return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
        else:
            # Feature Flag 关闭时：回退到原有 subprocess.run，零侵入
            return subprocess.run(cmd, check=True, **kwargs)

    def _check_censorship(self, yid: str, title: str, description: str = "") -> bool:
        """执行内容安全审查。如果命中违禁词，根据级别执行对应的干预动作。
        [Gemini_3.5_Flash_planning] 用于整合 CensorshipEngine 到主流程。
        返回 True 表示命中违禁（需要拦截/中断），False 表示合规通过。
        """
        if not settings.enable_censorship_engine:
            return False

        try:
            from .censor_engine import check_text, ACTION_REJECT_SIGTERM, ACTION_SUSPEND_MANUAL, ACTION_DEPRIORITIZE
            
            # 双语双通道匹配
            result = check_text(zh_text=title, en_text=f"{title} {description}")
            if result.hit:
                logger.warning(f"[Censor] Video {yid} hit censorship rule: {result}")
                # 1. 写入审计日志与数据库
                self.db.update_video_censor_status(yid, result.tag, result.score)
                
                # 2. 按动作执行系统干预
                if result.action == ACTION_REJECT_SIGTERM:
                    # P0 一票否决
                    logger.error(f"[Censor] P0 violation. Failing video {yid} and blacklisting.")
                    self.db.update_video_status(yid, "FAILED", error_msg=f"Censorship P0 Reject: {result.tag} (matched: '{result.matched}')")
                    if settings.enable_blacklist_tombstone:
                        self.db.add_to_blacklist(yid, reason=f"censor_p0_{result.matched}")
                    self.send_telegram_msg(f"🔴 <b>Censorship P0 Reject</b>\nTitle: {title}\nMatched: {result.matched}")
                    
                elif result.action == ACTION_SUSPEND_MANUAL:
                    # P1 人工挂起
                    logger.warning(f"[Censor] P1 violation. Suspending video {yid} for manual review.")
                    self.db.update_video_status(yid, "FAILED", error_msg=f"Censorship P1 Suspend: {result.tag} (matched: '{result.matched}')")
                    self.send_telegram_msg(f"🟡 <b>Censorship P1 Suspend</b>\nTitle: {title}\nMatched: {result.matched}")
                    
                elif result.action == ACTION_DEPRIORITIZE:
                    # P2 降权预警
                    logger.info(f"[Censor] P2 violation. Deprioritizing video {yid} to 0 points.")
                    self.db.update_video_score(yid, 0, force=True)
                    self.db.update_video_status(yid, "PENDING", error_msg=f"Censorship P2 Deprioritized: {result.tag}")
                    self.send_telegram_msg(f"🔵 <b>Censorship P2 Deprioritized</b>\nTitle: {title}")
                    
                return True
        except Exception as e:
            logger.error(f"[Censor] Verification process error: {e}")
            
        return False

    # ── 主处理流程 ────────────────────────────────────────────────────────────

    def _process_single_video(self, video: Dict[str, Any]):
        yid   = video['youtube_id']
        title = video['title']
        url   = f"https://youtu.be/{yid}"

        # [Claude_Sonnet_4.6_Thinking_planning] BUG-1 修复: signal.signal() 只能在主线程调用。
        # 此方法通过 daemon 线程执行，signal 注册已移至 app.py startup_event()。
        # [Claude_Sonnet_4.6_Thinking_planning] BUG-2 修复: 每个视频开始时重置标志位。
        # 若不重置，一旦 video1 收到 SIGTERM，后续所有视频将在首个 checkpoint 立即中断。
        global _sigterm_received
        _sigterm_received = False  # 每个视频独立的中断状态

        lock_path = self._OUT_DIR / "pipeline.lock"
        logger.info(f"[Lock] Waiting for pipeline lock to process {yid}...")
        lock_file = None
        try:
            try:
                lock_file = open(lock_path, "w")
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                logger.info(f"[Lock] Acquired pipeline lock. Processing {yid}...")
            except Exception as lock_err:
                # [Gemini_3.5_Flash_planning] 捕捉 lock_file open() 或 flock() 等底层锁获取异常，防止崩溃整个调度循环
                logger.error(f"Failed to acquire pipeline lock for {yid}: {lock_err}")
                self.db.update_video_status(yid, "FAILED", error_msg=f"Pipeline lock error: {lock_err}")
                self.send_telegram_msg(f"❌ <b>Video Failed</b>\nTitle: {title}\nError: Lock error: {lock_err}")
                return

            # ── 0. CENSORSHIP PRE-CHECK ───────────────────────────────────────
            # [Gemini_3.5_Flash_planning] 下载前的视频标题前置安全检查
            if self._check_censorship(yid, title):
                return

            try:
                # ── 1. DOWNLOADING ────────────────────────────────────────────────
                # [Claude_Sonnet_4.6_Thinking_planning] v7.0: SIGTERM 安全检查点
                if settings.enable_sigterm_kill and _sigterm_received:
                    logger.warning(f"[SIGTERM] Checkpoint before DOWNLOADING: aborting {yid}")
                    raise InterruptedError("SIGTERM received before download start")

                existing = self._find_downloaded_video(yid)
                if existing:
                    logger.info(f"[SKIP] Download checkpoint: {existing}")
                    self.db.update_video_status(yid, "DOWNLOADING")
                    target_file = existing
                else:
                    self.db.update_video_status(yid, "DOWNLOADING")
                    logger.info(f"Downloading {yid}...")
                    dl_cmd = [
                        self._VENV_YTDLP,
                        "-f", "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                        "--cookies-from-browser", "safari",
                        "--write-description",
                        "--remote-components", "ejs:github",
                        url, "-o", str(self._OUT_DIR / f"{yid}.%(ext)s"),
                    ]
                    env_no_proxy = {k: v for k, v in os.environ.items() if k not in _PROXY_KEYS}
                    self._run_tracked(dl_cmd, yid, capture_output=True,
                                      cwd=str(self._PRJ_ROOT), env=env_no_proxy)
                    target_file = self._find_downloaded_video(yid)
                    if not target_file:
                        raise FileNotFoundError(f"No video file found for {yid} after download")
                    logger.info(f"Downloaded: {target_file}")

                # ── 1b. CENSORSHIP DESC CHECK ─────────────────────────────────────
                # [Gemini_3.5_Flash_planning] 下载完成后，对视频简介描述进行安全检查
                desc_path = self._OUT_DIR / f"{yid}.description"
                description = ""
                if desc_path.exists():
                    try:
                        description = desc_path.read_text(encoding="utf-8").strip()
                    except Exception:
                        pass
                if self._check_censorship(yid, title, description):
                    return

                # ── 2. TRANSCRIBING & RENDERING ───────────────────────────────────
                vertical = self._OUT_DIR / f"{yid}_vertical.mp4"
                if vertical.exists() and vertical.stat().st_size > 1_000_000:
                    logger.info(f"[SKIP] Transcribe checkpoint: {vertical.name}")
                    self.db.update_video_status(yid, "TRANSCRIBING")
                else:
                    # [Claude_Sonnet_4.6_Thinking_planning] v7.0: SIGTERM 安全检查点
                    if settings.enable_sigterm_kill and _sigterm_received:
                        logger.warning(f"[SIGTERM] Checkpoint before TRANSCRIBING: aborting {yid}")
                        raise InterruptedError("SIGTERM received before transcription")
                    self.db.update_video_status(yid, "TRANSCRIBING")
                    render_cmd = [
                        "nice", "-n", "19",
                        self._VENV_PYTHON, "-m", "cli.main", "auto-caption",
                        target_file, "--vertical", "--bilingual", "--title", title,
                    ]
                    render_env = os.environ.copy()
                    render_env["PYTHONPATH"] = str(self._SRC_DIR)
                    self._run_tracked(render_cmd, yid, capture_output=True,
                                      cwd=str(self._PRJ_ROOT), env=render_env)

                # ── 2b. COPYWRITING ────────────────────────────────────────────────
                copy_file = self._OUT_DIR / f"{yid}_copy.txt"
                title_file = self._OUT_DIR / f"{yid}_title.txt"
                category_file = self._OUT_DIR / f"{yid}_category.txt"
                
                if copy_file.exists() and title_file.exists():
                    logger.info(f"[SKIP] Copywriting checkpoint: {copy_file.name}")
                    self.db.update_video_status(yid, "COPYWRITING")
                else:
                    self.db.update_video_status(yid, "COPYWRITING")
                    logger.info(f"Generating WeChat copy for {yid}...")
                    copy_cmd = [
                        self._VENV_PYTHON,
                        str(self._PRJ_ROOT / "scripts" / "copywriter.py"),
                        "--youtube-id", yid,
                        "--title", title,
                        "--desc-file", str(self._OUT_DIR / f"{yid}.description"),
                    ]
                    self._run_tracked(copy_cmd, yid, capture_output=True,
                                      cwd=str(self._PRJ_ROOT))

                # ── 2c. CENSORSHIP COPYWRITING CHECK ──────────────────────────────
                # [Gemini_3.5_Flash_planning] 文案生成后，对生成的短标题和文案正文进行安全检查
                copy_content = ""
                if copy_file.exists():
                    try:
                        copy_content = copy_file.read_text(encoding="utf-8").strip()
                    except Exception:
                        pass
                
                short_title = title
                if title_file.exists():
                    try:
                        short_title = title_file.read_text(encoding="utf-8").strip()
                    except Exception:
                        pass

                if self._check_censorship(yid, short_title, copy_content):
                    return

                # ── 3. 封面生成（非阻断，失败不影响发布）────────────────────────
                cover_file = self._OUT_DIR / f"{yid}_cover.jpg"
                if not cover_file.exists():
                    logger.info(f"Generating cover for {yid}...")
                    # 读取生成的短标题用于封面，如果读取失败则用原标题
                    cover_title = title
                    if title_file.exists():
                        try:
                            cover_title = title_file.read_text(encoding="utf-8").strip()
                        except Exception:
                            pass

                    cover_cmd = [
                        self._VENV_PYTHON,
                        str(self._PRJ_ROOT / "scripts" / "cover_generator.py"),
                        "--video", str(vertical),
                        "--title", cover_title,
                        "--output", str(cover_file),
                    ]
                    res = subprocess.run(cover_cmd, capture_output=True,
                                         cwd=str(self._PRJ_ROOT))
                    if res.returncode != 0:
                        logger.warning(f"Cover generation failed (non-fatal): "
                                       f"{res.stderr.decode()[:200]}")
                else:
                    logger.info(f"[SKIP] Cover checkpoint: {cover_file.name}")

                # ── 4. PUBLISHING ─────────────────────────────────────────────────
                self.db.update_video_status(yid, "PUBLISHING")
                logger.info(f"Uploading to WeChat Channels for {yid}...")

                upload_cmd = [
                    self._VENV_PYTHON,
                    str(self._PRJ_ROOT / "scripts" / "wechat_uploader.py"),
                    "--video",  str(vertical),
                    "--copy",   str(copy_file),
                    "--state",  str(self._OUT_DIR / "wechat_state.json"),
                    # 微信检测 headless 浏览器会重定向登录页
                    # 本地 Mac 运行，直接用可见浏览器，窗口会自动弹出并完成后关闭
                    "--no-headless",
                ]
                if cover_file.exists():
                    upload_cmd += ["--cover", str(cover_file)]
                if title_file.exists():
                    upload_cmd += ["--title-file", str(title_file)]
                if category_file.exists():
                    upload_cmd += ["--category-file", str(category_file)]

                # [Claude_Sonnet_4.6_Thinking_planning] BUG-3 修复: 使用 _run_tracked 覆盖 PUBLISHING 阶段的 PID 追踪。
                # wechat_uploader 启动 Playwright 可见浏览器 GUI；os.setsid() 不影响 GUI 进程组。
                # 特殊返回码 2 表示微信 session 过期，须单独捕获，不作为普通失败处理。
                try:
                    res = self._run_tracked(upload_cmd, yid, text=True,
                                            capture_output=True, cwd=str(self._PRJ_ROOT))
                    if res.stdout:
                        logger.debug(f"Uploader stdout:\n{res.stdout}")
                    if res.stderr:
                        logger.debug(f"Uploader stderr:\n{res.stderr}")
                except subprocess.CalledProcessError as upload_err:
                    if upload_err.returncode == 2:
                        # 登录 session 过期，非普通失败
                        logger.error(f"WeChat login required for {yid}.")
                        self.db.update_video_status(yid, "LOGIN_REQUIRED")
                        self.send_telegram_msg(
                            f"⚠️ <b>WeChat Login Required</b>\n"
                            f"Session expired: <b>{title}</b>\n"
                            f"<code>python scripts/wechat_uploader.py --login-only --no-headless</code>"
                        )
                        return
                    raise  # 其他错误上抛给外层 CalledProcessError 处理器


                # ── 5. PUBLISHED ──────────────────────────────────────────────────
                self.db.update_video_status(yid, "PUBLISHED")
                self.send_telegram_msg(
                    f"✅ <b>Video Published</b>\nTitle: {title}\n"
                    f"Platform: WeChat Channels\nScore: {video['score']}"
                )

            except InterruptedError as e:
                # [Claude_Sonnet_4.6_Thinking_planning] v7.0: SIGTERM 触发的可控退出
                logger.warning(f"[SIGTERM] Clean abort for {yid}: {e}")
                self.db.update_video_status(yid, "PENDING", error_msg="Aborted by SIGTERM")
                self.reset_video_artifacts(yid)

            except subprocess.CalledProcessError as e:
                err = e.stderr if isinstance(e.stderr, str) else (e.stderr or b"").decode()
                logger.error(f"Process failed for {yid}: {err[:500]}")
                self.db.update_video_status(yid, "FAILED", error_msg=err)
                self.send_telegram_msg(f"❌ <b>Video Failed</b>\nTitle: {title}")

            except Exception as e:
                logger.error(f"Unexpected error for {yid}: {e}")
                self.db.update_video_status(yid, "FAILED", error_msg=str(e))
                self.send_telegram_msg(f"❌ <b>Video Failed</b>\nTitle: {title}\nError: {e}")

        finally:
            # [Gemini_3.5_Flash_planning] CON-1: 无论处理成功、失败或发生任何异常，都必须释放进程锁并关闭句柄
            if lock_file is not None:
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                    logger.info(f"[Lock] Released pipeline lock for {yid}.")
                except Exception as ex:
                    logger.error(f"[Lock] Error releasing lock: {ex}")
                finally:
                    lock_file.close()
            # [Claude_Sonnet_4.6_Thinking_planning] v7.0: 清除 PID 记录（进程已终止）
            if settings.enable_sigterm_kill:
                self.db.update_process_pid(yid, None)

    # ── 每日作业 ──────────────────────────────────────────────────────────────

    def run_daily_job(self):
        """执行每日例行调度"""
        logger.info("--- Starting Daily Pipeline Job ---")
        self.score_pending_videos()
        self.process_high_score_videos(limit=5)
        logger.info("--- Daily Pipeline Job Completed ---")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    PipelineManager().run_daily_job()
