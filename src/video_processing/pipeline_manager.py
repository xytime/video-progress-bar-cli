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
| 2.1.1   | 2026-05-26 | Gemini_3.5_Flash                    | [v7.0 Fix] 修复 _run_tracked 传入 subprocess.Popen 时不支持 capture_output 等 kwargs 的问题 |
| 2.2.0   | 2026-05-26 | Gemini_3.5_Flash_planning           | 封面引擎 2.0 联动：读取短标题/副标题/内容 hints，组装 payload 传给生成器 |
| 2.3.0   | 2026-05-27 | Gemini_3.5_Flash                    | 新增下载后立即裁剪功能 (FFmpeg 流复制裁剪，支持 trim_start/trim_end) |
| 2.3.1   | 2026-05-27 | Unknown_Model_planning              | 修复分片时无法导入 copywriter 的 ModuleNotFoundError 问题                      |
| 2.3.2   | 2026-05-27 | Unknown_Model_planning              | 修复 slice_index > 0 时未执行导入代码导致的 UnboundLocalError 异常          |
| 2.4.0   | 2026-05-27 | Unknown_Model_planning              | 强制子分片封面副标题显示：主标题 + {当前集}/{总集数} 集                      |
| 2.5.0   | 2026-05-27 | Gemini_3.5_Flash_planning           | 支持 disable_slicing == 1 时强制跳过章节切片，保留整片制作发布流程 |
| 2.9.0   | 2026-05-28 | Claude_Sonnet_4.6_Thinking_planning | 多切片视频头部标题追加集数进度（如"AI写代码 3/9"），整片视频不受影响 |
| 2.8.0   | 2026-05-28 | Claude_Sonnet_4.6_Thinking_planning | 前移 COPYWRITING 至 TRANSCRIBING 之前，用中文短标题渲染，使视频头部与封面标题一致 |
| 2.7.0   | 2026-05-28 | Gemini_3.5_Flash_planning           | 改进 process_high_score_videos 支持连续批处理以自动完成所有切片与排队任务 |
| 2.6.0   | 2026-05-27 | Unknown_Model_planning              | 红蓝博弈安全性与容错性审计修复 (P1/P2) |
| 2.10.0  | 2026-05-29 | Claude_Sonnet_4.6_Thinking_planning | 从 video dict 读取 tts_provider 并在 render_cmd 中按需附加 --tts-cosy 参数，实现按需 TTS 配音而非默认自动开启 |
| 2.11.0  | 2026-06-01 | Gemini_2.5_Flash_planning           | [Censor Hardening] 修复 zh_text 参数 Bug（中文通道现在真正检测中文）；集成频道策略层；三处调用点传入 zh_title |
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
        """拉取高分视频进入加工流转，自动循环处理全部队列和切片任务直至清空。

        # Modification History
        | Version | Date | Author | Description |
        | --- | --- | --- | --- |
        | 1.0.0 | 2026-05-28 | Gemini_3.5_Flash_planning | 实现批次自动循环调度，彻底消除切片子任务需要手动执行的痛点 |
        """
        # [Gemini_3.5_Flash_planning] 连续拉取高分视频直至全部处理完成，避免切片或排队任务需要频繁手动执行
        logger.info(f"Starting pipeline run loop (batch limit={limit}).")
        total_processed = 0
        
        while True:
            # 拉取多一点以备过滤父视频就绪与发布顺序锁 [Gemini_3.5_Flash_planning]
            targets = self.db.get_high_score_pending_videos(min_score=75, limit=limit * 3)
            if not targets:
                logger.info("No more high-score videos available for processing.")
                break

            claimed_targets = []
            for video in targets:
                yid = video['youtube_id']
                slice_index = video.get('slice_index', 0)
                
                if slice_index > 0:
                    # 1. 检查父视频文件是否下载就绪
                    parent_file = self._find_downloaded_video(yid)
                    if not parent_file:
                        logger.info(f"Sub-task [{yid} s{slice_index}] skipped: Parent video file not ready.")
                        continue
                    
                    # 2. 检查前序子任务是否已发布 (Sequence Locking)
                    all_slices = self.db.get_slices_by_parent_yid(yid)
                    prev_not_published = [s for s in all_slices if s['slice_index'] < slice_index and s['status'] not in ('PUBLISHED', 'IGNORED', 'COMPLETED')]
                    if prev_not_published:
                        prev_indices = [s['slice_index'] for s in prev_not_published]
                        logger.info(f"Sub-task [{yid} s{slice_index}] skipped: Waiting for previous slices {prev_indices} to publish.")
                        continue
                
                # 防竞态：尝试抢占 [Gemini_3.5_Flash_planning]
                if self.db.claim_video_for_processing(yid, slice_index=slice_index):
                    claimed_targets.append(video)
                    if len(claimed_targets) >= limit:
                        break

            if not claimed_targets:
                logger.info("No claimable high-score videos in this batch. Exiting loop.")
                break

            logger.info(f"Processing a batch of {len(claimed_targets)} video(s).")
            self.send_telegram_msg(
                f"🚀 <b>Pipeline Batch Started</b>\nProcessing {len(claimed_targets)} videos in this batch."
            )
            for video in claimed_targets:
                self._process_single_video(video)
                total_processed += 1

        logger.info(f"Pipeline run loop completed. Total processed: {total_processed}")

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

    def _run_tracked(self, cmd: list, yid: str, slice_index: int = 0, **kwargs) -> subprocess.CompletedProcess:
        """以独立进程组运行命令，并将 PGID 写入数据库，供 API 层 SIGTERM 精准击杀。

        [Claude_Sonnet_4.6_Thinking_planning] v7.0 关键设计：
        - os.setsid() 在子进程建立独立的会话（Session Leader），
          使 os.killpg(pgid, SIGTERM) 只击杀该子进程组，不波及 FastAPI 父进程。
        - 仅当 settings.enable_sigterm_kill=True 时启用 PID 追踪（Feature Flag 保护）。
        """
        # [Gemini_3.5_Flash_fast] 避免 Popen 收到不支持的 capture_output 和 check 参数
        popen_kwargs = kwargs.copy()
        if popen_kwargs.pop("capture_output", False):
            popen_kwargs["stdout"] = subprocess.PIPE
            popen_kwargs["stderr"] = subprocess.PIPE
        popen_kwargs.pop("check", None)

        if settings.enable_sigterm_kill:
            proc = subprocess.Popen(
                cmd,
                preexec_fn=os.setsid,  # 建立独立进程组
                **popen_kwargs
            )
            try:
                pgid = os.getpgid(proc.pid)
                self.db.update_process_pid(yid, pgid, slice_index=slice_index)
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

    def _run_garbage_collection(self, yid: str, slice_index: int, status: str):
        """[Unknown_Model_planning] GC 自动清理器：
        - 支持子任务 (slice_index > 0) 或整片任务 (slice_index == 0) 发布成功后，清理其对应的临时媒体文件与文本/字幕/语音夹。
        - 当所有子任务均进入终态，清理父任务的超大原始 MP4 视频与 info.json 等临时文件。
        """
        import shutil
        
        # 1. 如果任务发布成功，清理其关联的临时文件
        if status == "PUBLISHED":
            prefix = f"{yid}_s{slice_index}" if slice_index > 0 else yid
            # 需要清理的中间文件和中间产物后缀
            suffixes = [
                ".mp4",
                "_vertical.mp4",
                ".ass",
                "_subtitle.txt",
                "_copy.txt",
                "_title.txt",
                "_category.txt",
                "_cover.jpg",
                ".description"
            ]
            
            for suffix in suffixes:
                file_path = self._OUT_DIR / f"{prefix}{suffix}"
                if file_path.exists():
                    try:
                        file_path.unlink()
                        logger.info(f"[GC] Deleted artifact: {file_path.name}")
                    except Exception as e:
                        logger.warning(f"[GC] Failed to delete artifact {file_path.name}: {e}")
            
            # 清理 Edge TTS 生成的临时语音目录
            audio_gen_dir = self._OUT_DIR / f"{prefix}_audio_gen"
            if audio_gen_dir.exists() and audio_gen_dir.is_dir():
                try:
                    shutil.rmtree(audio_gen_dir)
                    logger.info(f"[GC] Deleted audio gen folder: {audio_gen_dir.name}")
                except Exception as e:
                    logger.warning(f"[GC] Failed to delete audio gen folder {audio_gen_dir.name}: {e}")
                        
        # 2. 检查兄弟子任务状态以判断是否清理父文件
        if slice_index > 0:
            all_slices = self.db.get_slices_by_parent_yid(yid)
            if all_slices:
                all_finished = all(s["status"] in ("PUBLISHED", "FAILED", "IGNORED", "COMPLETED") for s in all_slices)
                if all_finished:
                    logger.info(f"[GC] All slices for parent {yid} are finished. Cleaning up parent artifacts...")
                    parent_suffixes = [
                        ".mp4",
                        ".info.json",
                        ".description",
                        "_subtitle.txt",
                        "_copy.txt",
                        "_title.txt",
                        "_category.txt",
                        "_cover.jpg",
                        ".ass"
                    ]
                    for suffix in parent_suffixes:
                        file_path = self._OUT_DIR / f"{yid}{suffix}"
                        if file_path.exists():
                            try:
                                file_path.unlink()
                                logger.info(f"[GC] Deleted parent artifact: {file_path.name}")
                            except Exception as e:
                                logger.warning(f"[GC] Failed to delete parent artifact {file_path.name}: {e}")
                    
                    # 清理父级语音临时目录
                    parent_audio_dir = self._OUT_DIR / f"{yid}_audio_gen"
                    if parent_audio_dir.exists() and parent_audio_dir.is_dir():
                        try:
                            shutil.rmtree(parent_audio_dir)
                            logger.info(f"[GC] Deleted parent audio gen folder: {parent_audio_dir.name}")
                        except Exception as e:
                            logger.warning(f"[GC] Failed to delete parent audio gen folder {parent_audio_dir.name}: {e}")

    def _check_censorship(self, yid: str, title: str, description: str = "", zh_title: str = "") -> bool:
        """执行内容安全审查（违法层）+ 频道内容策略检查（运营层）。

        [Gemini_2.5_Flash_planning] v2.11.0 修复：
        - 修复 zh_text 参数 Bug：原来错误地将英文 title 传给 zh 通道，现在使用 zh_title。
        - 集成频道内容策略层（check_channel_policy），由 enable_channel_policy_filter 控制。
        - 手动触发与自动触发统一走同一套审查流程，无例外。

        返回 True 表示命中（任意层）→ 需要拦截/中断，False 表示全部通过。
        """
        if not settings.enable_censorship_engine and not settings.enable_channel_policy_filter:
            return False

        try:
            from .censor_engine import (
                check_text, check_channel_policy,
                ACTION_REJECT_SIGTERM, ACTION_SUSPEND_MANUAL,
                ACTION_DEPRIORITIZE, ACTION_CHANNEL_POLICY,
            )

            # ── A. 违法内容审查（P0/P1/P2） ────────────────────────────────
            if settings.enable_censorship_engine:
                # [Gemini_2.5_Flash_planning] BUG FIX: zh_text 使用中文标题，en_text 使用英文标题+描述
                # 原来错误地将英文 title 传给 zh_text，导致中文规则库从未真正生效
                zh_for_censor = zh_title or ""  # 中文标题（爬虫翻译或 AI 生成），为空时中文通道跳过
                en_for_censor = f"{title} {description}".strip()
                result = check_text(zh_text=zh_for_censor, en_text=en_for_censor)
                if result.hit:
                    logger.warning(f"[Censor] Video {yid} hit censorship rule: {result}")
                    self.db.update_video_censor_status(yid, result.tag, result.score)

                    if result.action == ACTION_REJECT_SIGTERM:
                        logger.error(f"[Censor] P0 violation. Failing video {yid} and blacklisting.")
                        self.db.update_video_status(yid, "FAILED", error_msg=f"Censorship P0 Reject: {result.tag} (matched: '{result.matched}')")
                        if settings.enable_blacklist_tombstone:
                            self.db.add_to_blacklist(yid, reason=f"censor_p0_{result.matched}")
                        self.send_telegram_msg(
                            f"\U0001f534 <b>Censorship P0 Reject</b>"
                            f"\nTitle: {title}\nMatched: <code>{result.matched}</code> (via {result.channel})"
                        )
                        return True

                    elif result.action == ACTION_SUSPEND_MANUAL:
                        logger.warning(f"[Censor] P1 violation. Suspending video {yid} for manual review.")
                        self.db.update_video_status(yid, "FAILED", error_msg=f"Censorship P1 Suspend: {result.tag} (matched: '{result.matched}')")
                        self.send_telegram_msg(
                            f"\U0001f7e1 <b>Censorship P1 Suspend</b>"
                            f"\nTitle: {title}\nMatched: <code>{result.matched}</code> (via {result.channel})"
                        )
                        return True

                    elif result.action == ACTION_DEPRIORITIZE:
                        logger.info(f"[Censor] P2 violation. Deprioritizing video {yid} to 0 points.")
                        self.db.update_video_score(yid, 0, force=True)
                        self.db.update_video_status(yid, "PENDING", error_msg=f"Censorship P2 Deprioritized: {result.tag}")
                        self.send_telegram_msg(
                            f"\U0001f535 <b>Censorship P2 Deprioritized</b>"
                            f"\nTitle: {title}\nMatched: <code>{result.matched}</code>"
                        )
                        return True

            # ── B. 频道内容策略检查（CP 层） ────────────────────────────────
            if settings.enable_channel_policy_filter:
                # [Gemini_2.5_Flash_planning] 运营策略层：检测超出频道内容定位的话题
                # zh_title 优先；description 也纳入英文通道，防止标题无命中但描述已暴露
                zh_for_policy = zh_title or ""
                en_for_policy = f"{title} {description}".strip()
                cp_result = check_channel_policy(zh_text=zh_for_policy, en_text=en_for_policy)
                if cp_result.hit:
                    logger.warning(f"[ChannelPolicy] Video {yid} hit channel policy: {cp_result}")
                    # [Gemini_2.5_Flash_planning] Code Review Fix: CP 层也写入 censor_tag，与 P0/P1 审计行为保持一致
                    self.db.update_video_censor_status(yid, cp_result.tag, score=0)
                    self.db.update_video_status(
                        yid, "FAILED",
                        error_msg=f"Channel Policy Reject: {cp_result.tag} (matched: '{cp_result.matched}' via {cp_result.channel})"
                    )
                    self.send_telegram_msg(
                        f"\U0001f6ab <b>Channel Policy Reject</b>"
                        f"\nTitle: {title}"
                        f"\nMatched: <code>{cp_result.matched}</code> (via {cp_result.channel})"
                        f"\n\n\u26a0\ufe0f \u6b64\u89c6\u9891\u8d85\u51fa\u9891\u9053\u5185\u5bb9\u5b9a\u4f4d\u8fb9\u754c\uff0c\u5df2\u62d2\u7edd\u5904\u7406\u3002"
                    )
                    return True

        except Exception as e:
            logger.error(f"[Censor] Verification process error: {e}")

        return False

    # ── 主处理流程 ────────────────────────────────────────────────────────────

    def _process_single_video(self, video: Dict[str, Any]):
        # [Unknown_Model_planning] 动态导入 scripts/copywriter.py 以获取截断算法（置于顶层以避免 UnboundLocalError）
        import sys as _sys
        _scripts_dir = str(self._PRJ_ROOT / "scripts")
        if _scripts_dir not in _sys.path:
            _sys.path.insert(0, _scripts_dir)
        from copywriter import graceful_truncate_title

        yid   = video['youtube_id']
        title = video['title']
        url   = f"https://youtu.be/{yid}"
        trim_start = video.get('trim_start')
        trim_end   = video.get('trim_end')
        slice_index = video.get('slice_index', 0)
        prefix = f"{yid}_s{slice_index}" if slice_index > 0 else yid

        # [Claude_Sonnet_4.6_Thinking_planning] BUG-1 修复: signal.signal() 只能在主线程调用。
        # 此方法通过 daemon 线程执行，signal 注册已移至 app.py startup_event()。
        # [Claude_Sonnet_4.6_Thinking_planning] BUG-2 修复: 每个视频开始时重置标志位。
        # 若不重置，一旦 video1 收到 SIGTERM，后续所有视频将在首个 checkpoint 立即中断。
        global _sigterm_received
        _sigterm_received = False  # 每个视频独立的中断状态

        lock_path = self._OUT_DIR / "pipeline.lock"
        logger.info(f"[Lock] Waiting for pipeline lock to process {prefix}...")
        lock_file = None
        try:
            try:
                lock_file = open(lock_path, "w")
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                logger.info(f"[Lock] Acquired pipeline lock. Processing {prefix}...")
            except Exception as lock_err:
                logger.error(f"Failed to acquire pipeline lock for {prefix}: {lock_err}")
                self.db.update_video_status(yid, "FAILED", error_msg=f"Pipeline lock error: {lock_err}", slice_index=slice_index)
                self.send_telegram_msg(f"❌ <b>Video Failed</b>\nTitle: {title}\nError: Lock error: {lock_err}")
                return

            # ── 0. CENSORSHIP PRE-CHECK ───────────────────────────────────────
            # [Gemini_2.5_Flash_planning] v2.11.0: 手动/自动任务统一走同一套审查流程
            # zh_title 来自 DB，爬虫入库时已翻译；手动添加视频若翻译任务尚未完成则为空（回退到英文通道）
            zh_title_for_check = video.get('zh_title') or ""
            if self._check_censorship(yid, title, zh_title=zh_title_for_check):
                return

            try:
                # ── 1. DOWNLOADING / SLICING ──────────────────────────────────────
                if settings.enable_sigterm_kill and _sigterm_received:
                    logger.warning(f"[SIGTERM] Checkpoint before DOWNLOADING: aborting {prefix}")
                    raise InterruptedError("SIGTERM received before download/slice start")

                if slice_index > 0:
                    # 子任务：无需下载，只需从父任务的视频执行切片操作
                    target_file = self._OUT_DIR / f"{prefix}.mp4"
                    if target_file.exists() and target_file.stat().st_size > 50_000:
                        logger.info(f"[SKIP] Slice checkpoint: {target_file.name}")
                    else:
                        parent_file = self._find_downloaded_video(yid)
                        if not parent_file:
                            raise FileNotFoundError(f"Parent video file not found for slice {prefix}")
                        
                        self.db.update_video_status(yid, "DOWNLOADING", slice_index=slice_index)
                        from .processors.slicer import VideoSlicer
                        slicer = VideoSlicer(Path(parent_file), self._OUT_DIR)
                        
                        # 毫秒精度寻求解析
                        trim_start_val = float(video.get("trim_start", 0.0) or 0.0)
                        trim_end_val = float(video.get("trim_end", 0.0) or 0.0)
                        
                        logger.info(f"Slicing parent {parent_file} -> {target_file} ({trim_start_val} -> {trim_end_val})")
                        success = slicer.slice_video(trim_start_val, trim_end_val, Path(target_file))
                        if not success or not target_file.exists():
                            raise RuntimeError(f"Failed to slice parent video for {prefix}")
                else:
                    # 主任务：常规下载逻辑
                    existing = self._find_downloaded_video(yid)
                    if existing:
                        logger.info(f"[SKIP] Download checkpoint: {existing}")
                        self.db.update_video_status(yid, "DOWNLOADING", slice_index=slice_index)
                        target_file = existing
                    else:
                        self.db.update_video_status(yid, "DOWNLOADING", slice_index=slice_index)
                        logger.info(f"Downloading {yid}...")
                        dl_cmd = [
                            self._VENV_YTDLP,
                            "-f", "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                            "--cookies-from-browser", "safari",
                            "--write-description",
                            "--write-info-json",  # 新增：写 info.json 便于 chapters 提取
                            "--remote-components", "ejs:github",
                            url, "-o", str(self._OUT_DIR / f"{yid}.%(ext)s"),
                        ]
                        env_no_proxy = {k: v for k, v in os.environ.items() if k not in _PROXY_KEYS}
                        self._run_tracked(dl_cmd, yid, slice_index=slice_index, capture_output=True,
                                          cwd=str(self._PRJ_ROOT), env=env_no_proxy)
                        target_file = self._find_downloaded_video(yid)
                        if not target_file:
                            raise FileNotFoundError(f"No video file found for {yid} after download")
                        logger.info(f"Downloaded: {target_file}")

                        if trim_start or trim_end:
                            logger.info(f"Trimming main video {yid} to range: {trim_start or '0'} -> {trim_end or 'End'}")
                            temp_trimmed = self._OUT_DIR / f"{yid}_trimmed.mp4"
                            
                            import imageio_ffmpeg
                            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
                            
                            trim_cmd = [ffmpeg_exe, "-y"]
                            if trim_start:
                                trim_cmd += ["-ss", trim_start]
                            if trim_end:
                                trim_cmd += ["-to", trim_end]
                            trim_cmd += ["-i", str(target_file), "-c", "copy", str(temp_trimmed)]
                            
                            res = subprocess.run(trim_cmd, capture_output=True, text=True, cwd=str(self._PRJ_ROOT))
                            if res.returncode != 0:
                                raise subprocess.CalledProcessError(res.returncode, trim_cmd, output=res.stdout, stderr=res.stderr)
                            
                            if temp_trimmed.exists():
                                Path(target_file).unlink()
                                temp_trimmed.rename(target_file)

                # ── 1a. CHAPTERS EXTRACTION (仅针对主任务) ────────────────────────
                if slice_index == 0:
                    enable_chapters = getattr(settings, "enable_chapters_slicing", True)
                    if video.get("disable_slicing") == 1:
                        enable_chapters = False
                        logger.info(f"[Pipeline] Slicing explicitly disabled for {yid} (disable_slicing=1)")
                    
                    if enable_chapters:
                        from .processors.chapters_extractor import ChaptersExtractor
                        extractor = ChaptersExtractor()
                        info_json_path = self._OUT_DIR / f"{yid}.info.json"
                        
                        chapters = []
                        if info_json_path.exists():
                            chapters = extractor.extract_from_metadata(info_json_path)
                            
                        if len(chapters) > 1:
                            logger.info(f"Found {len(chapters)} native chapters. Slicing enabled.")
                            parent_video = self.db.get_video_by_youtube_id(yid, 0)
                            parent_id = parent_video["id"] if parent_video else None
                            
                            # [Unknown_Model_planning] 强制先清理已存在的陈旧切片，规避 Unique constraint 冲突
                            if parent_id is not None:
                                logger.info(f"Purging old slices for parent task ID {parent_id} before recreation.")
                                self.db.delete_slices_by_parent_id(parent_id)

                            slice_tasks = []
                            for idx, ch in enumerate(chapters, start=1):
                                prefix_title = graceful_truncate_title(title, max_len=6)
                                ch_title = ch["title"]
                                import re as _re
                                ch_title_clean = _re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9\s]', '', ch_title).strip()
                                sub_title = f"【{prefix_title} {idx:02d}】{ch_title_clean}"
                                sub_title = graceful_truncate_title(sub_title, max_len=16)
                                
                                slice_tasks.append({
                                    "youtube_id": yid,
                                    "slice_index": idx,
                                    "parent_id": parent_id,
                                    "title": sub_title,
                                    "channel_id": video.get("channel_id", ""),
                                    "score": video.get("score", 0),
                                    "source": video.get("source", "AUTO"),
                                    "duration_sec": int(ch["end_time"] - ch["start_time"]),
                                    "trim_start": f"{ch['start_time']:.3f}",
                                    "trim_end": f"{ch['end_time']:.3f}",
                                    "disable_slicing": 1,  # [Unknown_Model_planning] 切片任务本身必须禁用分片
                                })
                                
                            # [Unknown_Model_planning] 强制抛出异常以防默默回退整视频处理
                            if not self.db.batch_add_videos(slice_tasks):
                                raise RuntimeError(f"batch_add_videos failed to insert slice tasks for parent {yid}")
                                
                            self.db.update_video_status(yid, "SEGMENTED", slice_index=0)
                            self.send_telegram_msg(
                                f"📦 <b>Video Segmented</b>\nParent: {title}\n"
                                f"Generated {len(slice_tasks)} slices to publish."
                            )
                            return

                # ── 1b. CENSORSHIP DESC CHECK ─────────────────────────────────────
                desc_path = self._OUT_DIR / f"{yid}.description"
                description = ""
                if desc_path.exists():
                    try:
                        description = desc_path.read_text(encoding="utf-8").strip()
                    except Exception:
                        pass
                if self._check_censorship(yid, title, description, zh_title=zh_title_for_check):
                    return

                # ── 2a. COPYWRITING ────────────────────────────────────────────────
                # [Claude_Sonnet_4.6_Thinking_planning] v2.8.0 前移至 TRANSCRIBING 之前：
                # Copywriter 仅依赖 YouTube ID + 原始标题 + description，不需要 transcript。
                # 先生成中文短标题，TRANSCRIBING 步骤再读取，确保视频头部标题与封面一致。
                copy_file = self._OUT_DIR / f"{prefix}_copy.txt"
                title_file = self._OUT_DIR / f"{prefix}_title.txt"
                category_file = self._OUT_DIR / f"{prefix}_category.txt"

                if copy_file.exists() and title_file.exists():
                    logger.info(f"[SKIP] Copywriting checkpoint: {copy_file.name}")
                    self.db.update_video_status(yid, "COPYWRITING", slice_index=slice_index)
                else:
                    self.db.update_video_status(yid, "COPYWRITING", slice_index=slice_index)
                    logger.info(f"Generating WeChat copy for {prefix}...")
                    copy_cmd = [
                        self._VENV_PYTHON,
                        str(self._PRJ_ROOT / "scripts" / "copywriter.py"),
                        "--youtube-id", prefix,
                        "--title", title,
                        "--desc-file", str(self._OUT_DIR / f"{yid}.description"),
                    ]
                    self._run_tracked(copy_cmd, yid, slice_index=slice_index, capture_output=True,
                                      cwd=str(self._PRJ_ROOT))

                # ── 2b. TRANSCRIBING & RENDERING ──────────────────────────────────
                # [Claude_Sonnet_4.6_Thinking_planning] v2.8.0 读取 copywriter 生成的中文短标题
                # 作为渲染标题，使视频头部 title 与封面 title 保持一致。
                render_title = title  # fallback：若 title_file 不存在则用 DB 原始标题
                if title_file.exists():
                    try:
                        _rt = title_file.read_text(encoding="utf-8").strip()
                        if _rt:
                            render_title = _rt
                    except Exception:
                        pass

                # [Claude_Sonnet_4.6_Thinking_planning] v2.9.0 多切片视频：在视频头部标题追加集数进度
                # 格式："{短标题} {当前集}/{总集数}"，如 "AI写代码 3/9"
                # 整片视频（slice_index == 0）不追加，避免干扰。
                if slice_index > 0:
                    all_slices = self.db.get_slices_by_parent_yid(yid)
                    total_cnt = len(all_slices) if all_slices else 1
                    render_title = f"{render_title} {slice_index}/{total_cnt}"
                logger.info(f"[Render] Using title for video header: {render_title!r}")


                vertical = self._OUT_DIR / f"{prefix}_vertical.mp4"
                if vertical.exists() and vertical.stat().st_size > 1_000_000:
                    logger.info(f"[SKIP] Transcribe checkpoint: {vertical.name}")
                    self.db.update_video_status(yid, "TRANSCRIBING", slice_index=slice_index)
                else:
                    if settings.enable_sigterm_kill and _sigterm_received:
                        logger.warning(f"[SIGTERM] Checkpoint before TRANSCRIBING: aborting {prefix}")
                        raise InterruptedError("SIGTERM received before transcription")
                    self.db.update_video_status(yid, "TRANSCRIBING", slice_index=slice_index)
                    render_cmd = [
                        "nice", "-n", "19",
                        self._VENV_PYTHON, "-m", "cli.main", "auto-caption",
                        str(target_file), "--vertical", "--bilingual", "--title", render_title,
                    ]
                    # [Claude_Sonnet_4.6_Thinking_planning] v2.10.0: 按需附加 TTS 参数
                    # 只有 tts_provider 非空时才开启，默认流程不开启 TTS
                    _tts_provider = video.get("tts_provider") or None
                    if _tts_provider == "cosyvoice":
                        render_cmd += ["--tts-cosy"]
                        logger.info(f"[TTS] Activating CosyVoice for {prefix} (stored tts_provider={_tts_provider})")
                    elif _tts_provider == "edge":
                        render_cmd += ["--tts"]
                        logger.info(f"[TTS] Activating Edge TTS for {prefix} (stored tts_provider={_tts_provider})")
                    elif _tts_provider:
                        logger.warning(f"[TTS] Unknown tts_provider={_tts_provider!r} for {prefix}, skipping TTS")
                    render_env = os.environ.copy()
                    render_env["PYTHONPATH"] = str(self._SRC_DIR)
                    self._run_tracked(render_cmd, yid, slice_index=slice_index, capture_output=True,
                                      cwd=str(self._PRJ_ROOT), env=render_env)

                # ── 2c. CENSORSHIP COPYWRITING CHECK ──────────────────────────────
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

                # [Gemini_2.5_Flash_planning] v2.11.0: 文案检测使用 AI 生成的中文短标题作为 zh_title
                # short_title 此时已是文案阶段生成的中文标题，直接作为 zh 通道输入
                if self._check_censorship(yid, short_title, copy_content, zh_title=short_title):
                    return


                # ── 3. 封面生成 ──────────────────────────────────────────────────
                cover_file = self._OUT_DIR / f"{prefix}_cover.jpg"
                if not cover_file.exists():
                    logger.info(f"Generating cover for {prefix}...")
                    cover_title = title
                    if title_file.exists():
                        try:
                            cover_title = title_file.read_text(encoding="utf-8").strip()
                        except Exception:
                            pass

                    import json
                    cover_payload = {
                        "title": cover_title,
                        "subtitle": "",
                        "category": "",
                        "content_hints": []
                    }
                    subtitle_file = self._OUT_DIR / f"{prefix}_subtitle.txt"
                    
                    # [Unknown_Model_planning] 强制子分段视频封面副标题：整体的标题 + {当前集}/{总集数} 集
                    if slice_index > 0:
                        parent_video = self.db.get_video_by_youtube_id(yid, 0)
                        if parent_video:
                            parent_zh = parent_video.get("zh_title") or parent_video.get("title") or ""
                            # 剔除括号以防止副标题过长
                            import re as _re
                            parent_zh_clean = _re.sub(r'\([^)]*\)|（[^）]*）|\[[^\]]*\]|【[^】]*】', '', parent_zh).strip()
                            
                            parent_title_file = self._OUT_DIR / f"{yid}_title.txt"
                            if parent_title_file.exists():
                                try:
                                    parent_short = parent_title_file.read_text(encoding="utf-8").strip()
                                except Exception:
                                    parent_short = graceful_truncate_title(parent_zh_clean, max_len=14)
                            else:
                                parent_short = graceful_truncate_title(parent_zh_clean, max_len=14)
                                
                            all_slices = self.db.get_slices_by_parent_yid(yid)
                            total_cnt = len(all_slices) if all_slices else 1
                            slice_subtitle = f"{parent_short} {slice_index}/{total_cnt}集"
                            try:
                                subtitle_file.write_text(slice_subtitle, encoding="utf-8")
                                logger.info(f"Enforced slice subtitle: {slice_subtitle}")
                            except Exception as e:
                                logger.error(f"Failed to write slice subtitle file: {e}")

                    if subtitle_file.exists():
                        try:
                            cover_payload["subtitle"] = subtitle_file.read_text(encoding="utf-8").strip()
                        except Exception:
                            pass
                    category_file = self._OUT_DIR / f"{prefix}_category.txt"
                    if category_file.exists():
                        try:
                            cover_payload["category"] = category_file.read_text(encoding="utf-8").strip()
                        except Exception:
                            pass
                    hints_file = self._OUT_DIR / f"{prefix}_content_hints.json"
                    if hints_file.exists():
                        try:
                            cover_payload["content_hints"] = json.loads(hints_file.read_text(encoding="utf-8"))
                        except Exception:
                            pass

                    cover_cmd = [
                        self._VENV_PYTHON,
                        str(self._PRJ_ROOT / "scripts" / "cover_generator.py"),
                        "--video", str(vertical),
                        "--payload", json.dumps(cover_payload, ensure_ascii=False),
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
                # Sequence Locking 二次校验（防止在 queue 排队期间状态改变）
                if slice_index > 0:
                    all_slices = self.db.get_slices_by_parent_yid(yid)
                    # [Unknown_Model_planning] 放宽顺序锁：跳过处于已发布/跳过/手动上传状态的切片任务
                    prev_not_published = [s for s in all_slices if s['slice_index'] < slice_index and s['status'] not in ('PUBLISHED', 'IGNORED', 'COMPLETED')]
                    if prev_not_published:
                        logger.warning(f"Sequence Lock active: slice {slice_index} waiting for previous slices. Resetting to PENDING.")
                        self.db.update_video_status(yid, "PENDING", slice_index=slice_index)
                        return

                self.db.update_video_status(yid, "PUBLISHING", slice_index=slice_index)
                logger.info(f"Uploading to WeChat Channels for {prefix}...")

                # [Claude_Sonnet_4.6_Thinking_planning] BUG-FIX: 合集名称必须来自父视频标题
                # 使用切片自身的 title 会导致每个切片合集名不同（如"【01】引言"vs"【02】发展"），
                # WeChat 会将它们识别为不同合集而无法归并。
                # 修复：当 slice_index > 0 时，从父视频 (slice_index=0) 获取 zh_title 作为合集名。
                collection_name = ""
                if slice_index > 0:
                    import re as _re
                    parent_video_for_coll = self.db.get_video_by_youtube_id(yid, 0)
                    if parent_video_for_coll:
                        parent_zh_coll = (
                            parent_video_for_coll.get("zh_title")
                            or parent_video_for_coll.get("title")
                            or ""
                        )
                        # 剔除括号内容防止合集名过长
                        parent_zh_coll = _re.sub(
                            r'\([^)]*\)|（[^）]*）|\[[^\]]*\]|【[^】]*】', '', parent_zh_coll
                        ).strip()
                        # 尝试从父任务的 title_file 读取已生成的短标题
                        parent_title_file_coll = self._OUT_DIR / f"{yid}_title.txt"
                        if parent_title_file_coll.exists():
                            try:
                                parent_zh_coll = parent_title_file_coll.read_text(encoding="utf-8").strip()
                            except Exception:
                                pass
                        collection_name = graceful_truncate_title(parent_zh_coll, max_len=15)
                    else:
                        # fallback: 不设合集，总比设一个错误合集名好
                        logger.warning(f"[Collection] Parent video (slice_index=0) not found for {yid}, skipping collection.")

                upload_cmd = [
                    self._VENV_PYTHON,
                    str(self._PRJ_ROOT / "scripts" / "wechat_uploader.py"),
                    "--video",  str(vertical),
                    "--copy",   str(copy_file),
                    "--state",  str(self._OUT_DIR / "wechat_state.json"),
                    "--no-headless",
                ]
                if cover_file.exists():
                    upload_cmd += ["--cover", str(cover_file)]
                if title_file.exists():
                    upload_cmd += ["--title-file", str(title_file)]
                if category_file.exists():
                    upload_cmd += ["--category-file", str(category_file)]
                if slice_index > 0 and collection_name:
                    upload_cmd += ["--collection", collection_name]

                try:
                    res = self._run_tracked(upload_cmd, yid, slice_index=slice_index, text=True,
                                            capture_output=True, cwd=str(self._PRJ_ROOT))
                    if res.stdout:
                        logger.debug(f"Uploader stdout:\n{res.stdout}")
                    if res.stderr:
                        logger.debug(f"Uploader stderr:\n{res.stderr}")
                except subprocess.CalledProcessError as upload_err:
                    if upload_err.returncode == 2:
                        logger.error(f"WeChat login required for {prefix}.")
                        self.db.update_video_status(yid, "LOGIN_REQUIRED", slice_index=slice_index)
                        self.send_telegram_msg(
                            f"⚠️ <b>WeChat Login Required</b>\n"
                            f"Session expired: <b>{prefix}</b>\n"
                            f"<code>python scripts/wechat_uploader.py --login-only --no-headless</code>"
                        )
                        return
                    raise

                # ── 5. PUBLISHED ──────────────────────────────────────────────────
                self.db.update_video_status(yid, "PUBLISHED", slice_index=slice_index)
                self.send_telegram_msg(
                    f"✅ <b>Video Published</b>\nTitle: {short_title}\n"
                    f"Platform: WeChat Channels\nScore: {video['score']}"
                )
                
                # 触发 GC 清理该子任务的临时文件
                self._run_garbage_collection(yid, slice_index, "PUBLISHED")

            except InterruptedError as e:
                logger.warning(f"[SIGTERM] Clean abort for {prefix}: {e}")
                self.db.update_video_status(yid, "PENDING", error_msg="Aborted by SIGTERM", slice_index=slice_index)
                self.reset_video_artifacts(prefix)

            except subprocess.CalledProcessError as e:
                err = e.stderr if isinstance(e.stderr, str) else (e.stderr or b"").decode()
                logger.error(f"Process failed for {prefix}: {err[:500]}")
                self.db.update_video_status(yid, "FAILED", error_msg=err, slice_index=slice_index)
                self.send_telegram_msg(f"❌ <b>Video Failed</b>\nTitle: {title}")
                self._run_garbage_collection(yid, slice_index, "FAILED")

            except Exception as e:
                logger.error(f"Unexpected error for {prefix}: {e}")
                self.db.update_video_status(yid, "FAILED", error_msg=str(e), slice_index=slice_index)
                self.send_telegram_msg(f"❌ <b>Video Failed</b>\nTitle: {title}\nError: {e}")
                self._run_garbage_collection(yid, slice_index, "FAILED")

        finally:
            if lock_file is not None:
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                    logger.info(f"[Lock] Released pipeline lock for {prefix}.")
                except Exception as ex:
                    logger.error(f"[Lock] Error releasing lock: {ex}")
                finally:
                    lock_file.close()
            if settings.enable_sigterm_kill:
                self.db.update_process_pid(yid, None, slice_index=slice_index)

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
