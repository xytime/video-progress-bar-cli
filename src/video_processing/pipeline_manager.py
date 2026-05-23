"""自动化管线调度器 - 协调监测、评分、加工与通知流转

# Modification History
| Version | Date       | Author                              | Description                                           |
|---------|------------|-------------------------------------|-------------------------------------------------------|
| 1.0.0   | 2026-05-21 | Gemini_3.1_Pro_High_planning        | 初始创建 PipelineManager，实现完整的 FSM 调度          |
| 1.1.0   | 2026-05-21 | Gemini_3.5_Flash_planning           | 整合 Phase 5：文案生成与视频号全自动发布流             |
| 1.2.0   | 2026-05-21 | Claude_Sonnet_4.6_Thinking_planning | 地基重构：消灭裸 SQL + os.environ 泄漏                 |
| 1.3.0   | 2026-05-21 | Claude_Sonnet_4.6_Thinking_planning | 专项审查：路径常量类级化、os 顶层导入、动态扩展名检测  |
| 1.4.0   | 2026-05-22 | Claude_Sonnet_4.6_Thinking_planning | 断点续传检查点、封面生成步骤、硬重置接口、完整上传参数 |
"""

import os
import logging
import subprocess
import requests
from typing import Dict, Any, Optional
from pathlib import Path

from .db import PipelineDB
from config.settings import settings

logger = logging.getLogger(__name__)

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
        pending  = self.db.get_videos_by_status("PENDING")
        to_score = [v for v in pending if v.get('score', 0) < 75]
        skipped  = len(pending) - len(to_score)
        if skipped:
            logger.info(f"Skipping {skipped} already-prioritized videos (score >= 75).")
        if not to_score:
            return

        logger.info(f"Scoring {len(to_score)} pending videos...")
        for video in to_score:
            title = video['title'].lower()
            score = 60
            if any(k in title for k in ['ai', 'future', 'speech', 'interview', 'ceo']):
                score += 20
            logger.info(f"  '{title}' → {score}")
            self.db.update_video_score(video['youtube_id'], score)

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

    # ── 主处理流程 ────────────────────────────────────────────────────────────

    def _process_single_video(self, video: Dict[str, Any]):
        yid   = video['youtube_id']
        title = video['title']
        url   = f"https://youtu.be/{yid}"

        try:
            # ── 1. DOWNLOADING ────────────────────────────────────────────────
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
                subprocess.run(dl_cmd, check=True, capture_output=True,
                               cwd=str(self._PRJ_ROOT), env=env_no_proxy)
                target_file = self._find_downloaded_video(yid)
                if not target_file:
                    raise FileNotFoundError(f"No video file found for {yid} after download")
                logger.info(f"Downloaded: {target_file}")

            # ── 2. TRANSCRIBING & RENDERING ───────────────────────────────────
            vertical = self._OUT_DIR / f"{yid}_vertical.mp4"
            if vertical.exists() and vertical.stat().st_size > 1_000_000:
                logger.info(f"[SKIP] Transcribe checkpoint: {vertical.name}")
                self.db.update_video_status(yid, "TRANSCRIBING")
            else:
                self.db.update_video_status(yid, "TRANSCRIBING")
                render_cmd = [
                    "nice", "-n", "19",
                    self._VENV_PYTHON, "-m", "cli.main", "auto-caption",
                    target_file, "--vertical", "--bilingual", "--title", title,
                ]
                render_env = os.environ.copy()
                render_env["PYTHONPATH"] = str(self._SRC_DIR)
                subprocess.run(render_cmd, check=True, capture_output=True,
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
                subprocess.run(copy_cmd, check=True, capture_output=True,
                               cwd=str(self._PRJ_ROOT))

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

            # 使用 capture_output 获取上传器日志
            res = subprocess.run(upload_cmd, text=True, capture_output=True, cwd=str(self._PRJ_ROOT))
            
            if res.stdout:
                logger.debug(f"Uploader stdout:\n{res.stdout}")
            if res.stderr:
                logger.debug(f"Uploader stderr:\n{res.stderr}")

            if res.returncode == 2:
                logger.error(f"WeChat login required for {yid}.")
                self.db.update_video_status(yid, "LOGIN_REQUIRED")
                self.send_telegram_msg(
                    f"⚠️ <b>WeChat Login Required</b>\n"
                    f"Session expired: <b>{title}</b>\n"
                    f"<code>python scripts/wechat_uploader.py --login-only --no-headless</code>"
                )
                return
            elif res.returncode != 0:
                raise subprocess.CalledProcessError(
                    res.returncode, upload_cmd,
                    stderr=res.stderr.encode() if isinstance(res.stderr, str) else res.stderr,
                )

            # ── 5. PUBLISHED ──────────────────────────────────────────────────
            self.db.update_video_status(yid, "PUBLISHED")
            self.send_telegram_msg(
                f"✅ <b>Video Published</b>\nTitle: {title}\n"
                f"Platform: WeChat Channels\nScore: {video['score']}"
            )

        except subprocess.CalledProcessError as e:
            err = e.stderr if isinstance(e.stderr, str) else (e.stderr or b"").decode()
            logger.error(f"Process failed for {yid}: {err[:500]}")
            self.db.update_video_status(yid, "FAILED", error_msg=err)
            self.send_telegram_msg(f"❌ <b>Video Failed</b>\nTitle: {title}")

        except Exception as e:
            logger.error(f"Unexpected error for {yid}: {e}")
            self.db.update_video_status(yid, "FAILED", error_msg=str(e))
            self.send_telegram_msg(f"❌ <b>Video Failed</b>\nTitle: {title}\nError: {e}")

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
