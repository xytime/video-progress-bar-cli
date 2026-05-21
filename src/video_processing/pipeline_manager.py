"""自动化管线调度器 - 协调监测、评分、加工与通知流转

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-05-21 | Gemini_3.1_Pro_High_planning | 初始创建 PipelineManager，实现完整的 FSM 调度 |
| 1.1.0 | 2026-05-21 | Gemini_3.5_Flash_planning | 整合 Phase 5：加入文案生成与视频号全自动发布流，处理登录失效状态 |
| 1.2.0 | 2026-05-21 | Claude_Sonnet_4.6_Thinking_planning | 地基重构：消灭 2 处裸 SQL + os.environ 泄漏，统一通过 settings 和 DAL 方法 |

"""
import time
import logging
import subprocess
import requests
from typing import List, Dict, Any
from pathlib import Path

from .db import PipelineDB
from config.settings import settings  # [Claude_Sonnet_4.6_Thinking_planning] 统一通过 settings 读取配置

logger = logging.getLogger(__name__)

class PipelineManager:
    def __init__(self, db_path: str = "pipeline.db"):
        self.db = PipelineDB(db_path)
        # [Claude_Sonnet_4.6_Thinking_planning] 从 settings 注入，不直接访问 os.environ
        self.telegram_token = settings.telegram_bot_token
        self.telegram_chat_id = settings.telegram_chat_id
        
    def send_telegram_msg(self, text: str):
        if not self.telegram_token or not self.telegram_chat_id:
            logger.debug(f"Telegram Config Missing. Would have sent: {text}")
            return
            
        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        payload = {"chat_id": self.telegram_chat_id, "text": text, "parse_mode": "HTML"}
        try:
            requests.post(url, json=payload, timeout=10)
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")

    def score_pending_videos(self):
        """对 PENDING 状态的视频调用 LLM 进行评分并更新

        规则：
        - 已被手动设置高分（score >= 75）的视频跳过，不覆盖用户意图
        - score < 75 的视频才进行自动评分
        """
        pending = self.db.get_videos_by_status("PENDING")
        if not pending:
            return

        to_score = [v for v in pending if v.get('score', 0) < 75]
        skipped  = len(pending) - len(to_score)
        if skipped:
            logger.info(f"Skipping {skipped} already-prioritized videos (score >= 75).")
        if not to_score:
            return

        logger.info(f"Scoring {len(to_score)} pending videos...")
        for video in to_score:
            title = video['title'].lower()
            score = 60  # 基础分

            # 关键词加分
            if any(k in title for k in ['ai', 'future', 'speech', 'interview', 'ceo']):
                score += 20

            logger.info(f"Video '{title}' scored {score}")
            self.db.update_video_score(video['youtube_id'], score)


    def process_high_score_videos(self, limit: int = 5):
        """拉取高分视频进入加工流转"""
        # [Claude_Sonnet_4.6_Thinking_planning] 原裸 SQL 已移至 db.get_high_score_pending_videos()
        targets = self.db.get_high_score_pending_videos(min_score=75, limit=limit)
            
        if not targets:
            logger.info("No high-score videos available for processing today.")
            return
            
        self.send_telegram_msg(f"🚀 <b>Pipeline Started</b>\nToday's quota: {len(targets)} videos.")
        
        for video in targets:
            self._process_single_video(video)
            
    def _process_single_video(self, video: Dict[str, Any]):
        yid   = video['youtube_id']
        title = video['title']
        url   = f"https://youtu.be/{yid}"

        # [Claude_Sonnet_4.6_Thinking_planning] 绝对路径常量，防止 CWD 漂移导致的
        # "python not found" / "ModuleNotFoundError: pydantic_settings" 等问题
        PRJ_ROOT    = Path(__file__).parent.parent.parent
        SRC_DIR     = PRJ_ROOT / "src"
        VENV_PYTHON = str(PRJ_ROOT / ".venv" / "bin" / "python")
        VENV_YTDLP  = str(PRJ_ROOT / ".venv" / "bin" / "yt-dlp")
        OUT_DIR     = PRJ_ROOT / "output"
        OUT_DIR.mkdir(exist_ok=True)

        try:
            # 1. DOWNLOADING
            self.db.update_video_status(yid, "DOWNLOADING")
            logger.info(f"Downloading {yid}...")

            dl_cmd = [
                VENV_YTDLP,
                "-f", "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                "--cookies-from-browser", "safari",
                "--write-description",
                "--remote-components", "ejs:github",   # deno EJS JS challenge solver
                url, "-o", str(OUT_DIR / f"{yid}.%(ext)s"),
            ]
            # 清除代理环境变量，防止系统代理未启动时导致 connection refused
            # yt-dlp 凭 Safari cookies 直连 YouTube，无需走额外代理
            import os as _os
            _PROXY_KEYS = {'HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy'}
            env_no_proxy = {k: v for k, v in _os.environ.items() if k not in _PROXY_KEYS}
            subprocess.run(dl_cmd, check=True, capture_output=True,
                           cwd=str(PRJ_ROOT), env=env_no_proxy)


            # 2. TRANSCRIBING & RENDERING（cli.main 需要 PYTHONPATH=src）
            self.db.update_video_status(yid, "TRANSCRIBING")

            target_file = str(OUT_DIR / f"{yid}.mp4")
            render_cmd = [
                "nice", "-n", "19",
                VENV_PYTHON, "-m", "cli.main", "auto-caption",
                target_file, "--vertical", "--bilingual", "--title", title,
            ]
            env = {"PYTHONPATH": str(SRC_DIR), "PATH": "/usr/bin:/bin:/usr/local/bin"}
            subprocess.run(render_cmd, check=True, capture_output=True,
                           cwd=str(PRJ_ROOT), env={**__import__('os').environ, **env})

            # 3. COPYWRITING
            self.db.update_video_status(yid, "COPYWRITING")
            logger.info(f"Generating WeChat copy for {yid}...")
            desc_file = str(OUT_DIR / f"{yid}.description")
            copy_cmd = [
                VENV_PYTHON, str(PRJ_ROOT / "scripts" / "copywriter.py"),
                "--youtube-id", yid,
                "--title", title,
                "--desc-file", desc_file,
            ]
            subprocess.run(copy_cmd, check=True, capture_output=True, cwd=str(PRJ_ROOT))

            # 4. PUBLISHING
            self.db.update_video_status(yid, "PUBLISHING")
            logger.info(f"Uploading to WeChat Channels for {yid}...")
            vertical_video  = str(OUT_DIR / f"{yid}_vertical.mp4")
            copy_text_file  = str(OUT_DIR / f"{yid}_copy.txt")

            upload_cmd = [
                VENV_PYTHON, str(PRJ_ROOT / "scripts" / "wechat_uploader.py"),
                "--video", vertical_video,
                "--copy", copy_text_file,
                "--state", str(OUT_DIR / "wechat_state.json"),
            ]

            res = subprocess.run(upload_cmd, capture_output=True, text=True)
            
            if res.returncode == 2:
                # [Gemini_3.5_Flash_planning] WeChat login expired. Signal for manual scan login.
                logger.error(f"WeChat login required for {yid}.")
                self.db.update_video_status(yid, "LOGIN_REQUIRED")
                self.send_telegram_msg(
                    f"⚠️ <b>WeChat Login Required</b>\n"
                    f"Session expired while publishing video: <b>{title}</b>.\n"
                    f"Please run the following command on your local machine to log in:\n"
                    f"<code>python scripts/wechat_uploader.py --login-only --no-headless</code>"
                )
                return
            elif res.returncode != 0:
                raise subprocess.CalledProcessError(res.returncode, upload_cmd, stderr=res.stderr)
            
            # 5. PUBLISHED (Successfully uploaded and posted)
            self.db.update_video_status(yid, "PUBLISHED")
            self.send_telegram_msg(
                f"✅ <b>Video Published</b>\n"
                f"Title: {title}\n"
                f"Platform: WeChat Channels\n"
                f"Score: {video['score']}"
            )
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to process {yid}. Error: {e.stderr}")
            self.db.update_video_status(yid, "FAILED", error_msg=str(e.stderr))
            self.send_telegram_msg(f"❌ <b>Video Failed</b>\nTitle: {title}\nError: Subprocess failed.")
            
        except Exception as e:
            logger.error(f"Unexpected error on {yid}: {e}")
            self.db.update_video_status(yid, "FAILED", error_msg=str(e))
            self.send_telegram_msg(f"❌ <b>Video Failed</b>\nTitle: {title}\nError: {str(e)}")

    def run_daily_job(self):
        """执行每日例行调度"""
        logger.info("--- Starting Daily Pipeline Job ---")
        self.score_pending_videos()
        self.process_high_score_videos(limit=5)
        logger.info("--- Daily Pipeline Job Completed ---")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    manager = PipelineManager()
    manager.run_daily_job()
