"""src/bot/pipeline_agent.py — AI Agent based on Gemini 2.5 Flash for orchestrating video processing pipeline.

This module implements the PipelineAgent class which utilizes Function Calling in google-generativeai
to execute pipeline tools (downloading, captioning, copywriting, uploading, status updating)
based on incoming Telegram messages and commands.

# Modification History
| Version | Date       | Author                         | Description                                                                              |
| ------- | ---------- | ------------------------------ | ---------------------------------------------------------------------------------------- |
| 1.0.0   | 2026-05-24 | Gemini_3.5_Flash_High_planning | 初始创建 PipelineAgent，支持 Gemini 2.5 Flash Agentic Pipeline 执行与自定义 Telegram 交互路由 |
| 1.1.0   | 2026-05-24 | Gemini_3.5_Flash_High_planning | 将模型切换为 gemini-flash-latest 以免受限于 2.5 预览版 20 RPD 的严格限制 |
| 1.2.0   | 2026-05-24 | Gemini_3.5_Flash_High_planning | 将模型切换为 gemini-flash-lite-latest，并加入 429 频率限额指数避让重试机制 |
| 1.3.0   | 2026-05-25 | Gemini_3.5_Flash_High_planning | 在 5 个核心工具中加入 fcntl 跨进程排他锁，强制实现串行执行 |
| 1.3.1   | 2026-06-04 | Gemini_3.5_Flash_planning      | [下载优化] yt-dlp 增加 --downloader curl 参数，解决在代理环境下载大文件时 Python ssl.c 的 UNEXPECTED_EOF_WHILE_READING 报错 |
"""
import os
import sys
import json
import logging
import asyncio
import subprocess
import fcntl
from pathlib import Path
from typing import Optional, List, Dict, Any

import google.generativeai as genai

# Ensure src/ is in sys.path
_src = str(Path(__file__).parent.parent)
if _src not in sys.path:
    sys.path.insert(0, _src)

from config.settings import settings
from video_processing.db import PipelineDB
from bot.api_client import PipelineAPIClient

logger = logging.getLogger("pipeline_agent")


class PipelineAgent:
    """AI Agent that orchestrates the video processing pipeline using Gemini Function Calling.

    Runs in a synchronous thread (via asyncio.to_thread) to prevent blocking the async Telegram event loop,
    and communicates back to the main loop to send messages or call API clients.
    """

    def __init__(self, bot, loop, chat_id: int):
        self.bot = bot
        self.loop = loop
        self.chat_id = chat_id
        
        # Paths
        self.project_root = Path(__file__).parent.parent.parent
        self.src_dir = self.project_root / "src"
        self.venv_python = str(self.project_root / ".venv" / "bin" / "python")
        self.venv_ytdlp = str(self.project_root / ".venv" / "bin" / "yt-dlp")
        self.output_dir = self.project_root / "output"
        self.output_dir.mkdir(exist_ok=True)

        # Clients
        self.db = PipelineDB()
        self.api_client = PipelineAPIClient()

        # Configure Gemini
        api_key = settings.gemini_api_key
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not configured in settings.")
        genai.configure(api_key=api_key)

        # Expose tools for Gemini Function Calling
        self.tools = [
            self.send_telegram_message,
            self.list_pending_videos,
            self.list_videos,
            self.get_video_details,
            self.add_video_to_queue,
            self.download_video,
            self.transcribe_and_caption_video,
            self.generate_wechat_copy,
            self.generate_video_cover,
            self.upload_to_wechat,
            self.update_video_status,
            self.delete_video_from_db,
            self.retry_video_in_db,
            self.get_system_stats,
            self.trigger_wechat_login
        ]

        self.system_prompt = (
            "You are an intelligent Video Pipeline Agent. You manage a pipeline that downloads, processes, "
            "transcribes, copywrites, and uploads YouTube videos to WeChat Channels.\n\n"
            "Your environment has specific tools to control this pipeline. Use them to execute the tasks.\n\n"
            "Rules of operation:\n"
            "1. When the user sends '/run' (or indicates running the whole pipeline), you must:\n"
            "   - Call send_telegram_message to announce you are starting.\n"
            "   - Call list_videos(tab='queue', size=3) to fetch high-score pending videos.\n"
            "   - If empty, report that there are no videos in the queue.\n"
            "   - Otherwise, process up to 3 videos sequentially. For each video:\n"
            "     * Update status to 'DOWNLOADING' via update_video_status, then run download_video. "
            "If download fails, update status to 'FAILED', record the error, send a Telegram alert, and proceed to the next video.\n"
            "     * Update status to 'TRANSCRIBING', then run transcribe_and_caption_video. "
            "If transcription fails, update status to 'FAILED', record the error, send a Telegram alert, and proceed.\n"
            "     * Update status to 'COPYWRITING', then run generate_wechat_copy. "
            "If copywriting fails, update status to 'FAILED', record the error, send a Telegram alert, and proceed.\n"
            "     * Run generate_video_cover (non-fatal, ignore errors).\n"
            "     * Update status to 'PUBLISHING', then run upload_to_wechat.\n"
            "       - If it returns error 'WECHAT_LOGIN_EXPIRED', update status to 'LOGIN_REQUIRED' in DB, "
            "send a high-priority Telegram message alerting the user to run /wechat_login or scan the QR code to log in, "
            "and IMMEDIATELY stop processing further videos (abort pipeline) and finish.\n"
            "       - If it fails with other errors, update status to 'FAILED', record the error, send a Telegram alert, and proceed.\n"
            "       - If it succeeds, update status to 'PUBLISHED', send a success message to Telegram.\n"
            "   - At the end of the run, compile a summary of what succeeded, failed, or was skipped, and present it to the user.\n\n"
            "2. When the user sends '/process <youtube_id>', follow the same sequence as above but ONLY for the single specified video ID. "
            "If its status is not PENDING, claim it anyway or reset it to PENDING first, and proceed.\n\n"
            "3. When the user sends a YouTube URL, call add_video_to_queue(url). If the video is added successfully, reply to the user "
            "confirming it and show the parsed video details. Inform them they can run /process <youtube_id> to process it immediately.\n\n"
            "4. When the user sends '/queue', '/status', or asks 'what is in the queue?', call list_videos(tab='queue') and "
            "list_videos(tab='active'), then present the queue status to the user.\n\n"
            "5. When the user sends '/stats', call get_system_stats and format a nice statistical report.\n\n"
            "6. When the user sends '/delete <youtube_id>', call delete_video_from_db.\n\n"
            "7. When the user sends '/retry <youtube_id>', call retry_video_in_db.\n\n"
            "8. When the user sends '/wechat_login' (or requests logging in to WeChat), call trigger_wechat_login to pop up the QR code window.\n\n"
            "9. For any other message, respond directly and concisely. If the user asks a question, call the relevant query tool "
            "to get facts before answering. Avoid guessing or hallucinating facts.\n\n"
            "IMPORTANT formatting rule: Keep all Telegram messages concise. Use HTML tags (e.g., <b>bold</b>, <i>italic</i>, "
            "<code>code</code>) for layout. Never output raw Markdown to send_telegram_message, as it expects HTML!"
        )

    # ── Tools Implementation ──────────────────────────────────────────────────

    def send_telegram_message(self, message: str) -> str:
        """Sends a notification or progress message to the user via Telegram.

        Args:
            message: HTML formatted message string to be sent to Telegram.
        """
        # [Gemini_3.5_Flash_High_planning]
        coro = self.bot.send_message(
            chat_id=self.chat_id,
            text=message,
            parse_mode="HTML"
        )
        try:
            future = asyncio.run_coroutine_threadsafe(coro, self.loop)
            future.result(timeout=10)
            return "Message sent successfully."
        except Exception as e:
            logger.error(f"Failed to send telegram message: {e}")
            return f"Error sending message: {e}"

    def list_pending_videos(self) -> str:
        """Lists all pending videos in the queue ordered by score descending."""
        # [Gemini_3.5_Flash_High_planning]
        try:
            videos = self.db.get_videos_by_status("PENDING")
            return json.dumps({"ok": True, "videos": videos})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    def list_videos(self, tab: str = "waitlist", size: int = 10) -> str:
        """Retrieves a list of videos matching a specific tab category from the database.

        Args:
            tab: The category name. Choices: 'queue', 'waitlist', 'active', 'completed', 'error'.
            size: Number of records to return.
        """
        # [Gemini_3.5_Flash_High_planning]
        try:
            videos, _ = self.db.get_paginated_videos(tab=tab, page=1, size=size)
            # Row objects are not JSON serializable, get_paginated_videos returns list of dicts
            return json.dumps({"ok": True, "videos": videos})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    def get_video_details(self, youtube_id: str) -> str:
        """Gets status and other details of a video from the database.

        Args:
            youtube_id: The 11-character YouTube video ID.
        """
        # [Gemini_3.5_Flash_High_planning]
        try:
            video = self.db.get_video_by_youtube_id(youtube_id)
            if video:
                return json.dumps({"ok": True, "video": dict(video)})
            return json.dumps({"ok": False, "error": "Video not found in database"})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    def add_video_to_queue(self, url: str) -> str:
        """Parses a YouTube URL and queues it in the database as PENDING.

        Args:
            url: The YouTube video URL (e.g. watch link or Shorts link).
        """
        # [Gemini_3.5_Flash_High_planning]
        coro = self.api_client.add_video(url)
        try:
            future = asyncio.run_coroutine_threadsafe(coro, self.loop)
            res = future.result(timeout=45)
            if res is None:
                return json.dumps({"ok": False, "error": "FastAPI server did not respond or returned error"})
            return json.dumps({"ok": True, "data": res})
        except Exception as e:
            return json.dumps({"ok": False, "error": f"Exception calling add_video API: {e}"})

    def download_video(self, youtube_id: str) -> str:
        """Downloads a YouTube video using yt-dlp.

        Args:
            youtube_id: The 11-character YouTube video ID.
        """
        # [Gemini_3.5_Flash_High_planning]
        lock_path = self.output_dir / "pipeline.lock"
        logger.info(f"[Lock] Waiting for pipeline lock to download {youtube_id}...")
        lock_file = open(lock_path, "w")
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        logger.info(f"[Lock] Acquired pipeline lock to download {youtube_id}.")
        try:
            existing = self._find_downloaded_video(youtube_id)
            if existing:
                return json.dumps({"ok": True, "message": f"Video already downloaded", "path": existing})

            # [Gemini_3.5_Flash_planning] v1.3.1: 针对代理环境下的 SSL UNEXPECTED_EOF_WHILE_READING 报错，
            # 引入 --downloader curl 将大文件下载转交给 curl 处理，其代理兼容性和 TLS 握手比 python ssl 模块更稳定。
            dl_cmd = [
                self.venv_ytdlp,
                "-f", "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                "--cookies-from-browser", "safari",
                "--write-description",
                "--remote-components", "ejs:github",
                "--downloader", "curl",
                url, "-o", str(self.output_dir / f"{youtube_id}.%(ext)s"),
            ]
            _PROXY_KEYS = {'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy'}
            env_no_proxy = {k: v for k, v in os.environ.items() if k not in _PROXY_KEYS}

            try:
                subprocess.run(dl_cmd, check=True, capture_output=True, text=True, cwd=str(self.project_root), env=env_no_proxy)
                target_file = self._find_downloaded_video(youtube_id)
                if not target_file:
                    return json.dumps({"ok": False, "error": "No video file found after download completed"})
                return json.dumps({"ok": True, "message": "Download successful", "path": target_file})
            except subprocess.CalledProcessError as e:
                return json.dumps({"ok": False, "error": f"yt-dlp download failed: {e.stderr}"})
            except Exception as e:
                return json.dumps({"ok": False, "error": f"Unexpected download error: {e}"})
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            lock_file.close()
            logger.info(f"[Lock] Released pipeline lock after download {youtube_id}.")

    def transcribe_and_caption_video(self, youtube_id: str) -> str:
        """Runs the transcription and bilingual caption rendering on the downloaded video.

        Args:
            youtube_id: The 11-character YouTube video ID.
        """
        # [Gemini_3.5_Flash_High_planning]
        lock_path = self.output_dir / "pipeline.lock"
        logger.info(f"[Lock] Waiting for pipeline lock to transcribe {youtube_id}...")
        lock_file = open(lock_path, "w")
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        logger.info(f"[Lock] Acquired pipeline lock to transcribe {youtube_id}.")
        try:
            video_file = self._find_downloaded_video(youtube_id)
            if not video_file:
                return json.dumps({"ok": False, "error": "Downloaded video file not found. Download it first."})

            vertical = self.output_dir / f"{youtube_id}_vertical.mp4"
            if vertical.exists() and vertical.stat().st_size > 1_000_000:
                return json.dumps({"ok": True, "message": "Video already transcribed and captioned", "path": str(vertical)})

            video_rec = self.db.get_video_by_youtube_id(youtube_id)
            title = video_rec["title"] if video_rec else "Video"

            render_cmd = [
                "nice", "-n", "19",
                self.venv_python, "-m", "cli.main", "auto-caption",
                video_file, "--vertical", "--bilingual", "--title", title,
            ]
            render_env = os.environ.copy()
            render_env["PYTHONPATH"] = str(self.src_dir)

            try:
                subprocess.run(render_cmd, check=True, capture_output=True, text=True, cwd=str(self.project_root), env=render_env)
                if vertical.exists() and vertical.stat().st_size > 1_000_000:
                    return json.dumps({"ok": True, "message": "Transcription and caption rendering successful", "path": str(vertical)})
                return json.dumps({"ok": False, "error": "Rendered vertical video not found or too small after transcription"})
            except subprocess.CalledProcessError as e:
                return json.dumps({"ok": False, "error": f"Transcription process failed: {e.stderr}"})
            except Exception as e:
                return json.dumps({"ok": False, "error": f"Unexpected transcription error: {e}"})
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            lock_file.close()
            logger.info(f"[Lock] Released pipeline lock after transcribe {youtube_id}.")

    def generate_wechat_copy(self, youtube_id: str) -> str:
        """Generates WeChat Channels copy (title, body description, category) using Gemini/DeepTranslator.

        Args:
            youtube_id: The 11-character YouTube video ID.
        """
        # [Gemini_3.5_Flash_High_planning]
        lock_path = self.output_dir / "pipeline.lock"
        logger.info(f"[Lock] Waiting for pipeline lock to generate copy for {youtube_id}...")
        lock_file = open(lock_path, "w")
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        logger.info(f"[Lock] Acquired pipeline lock to generate copy for {youtube_id}.")
        try:
            copy_file = self.output_dir / f"{youtube_id}_copy.txt"
            title_file = self.output_dir / f"{youtube_id}_title.txt"
            category_file = self.output_dir / f"{youtube_id}_category.txt"

            if copy_file.exists() and title_file.exists():
                return json.dumps({
                    "ok": True,
                    "message": "WeChat copy already generated",
                    "copy_path": str(copy_file),
                    "title_path": str(title_file)
                })

            video_rec = self.db.get_video_by_youtube_id(youtube_id)
            if not video_rec:
                return json.dumps({"ok": False, "error": "Video record not found in database"})

            title = video_rec["title"]
            desc_file = self.output_dir / f"{youtube_id}.description"
            if not desc_file.exists():
                desc_file.write_text("", encoding="utf-8")

            copy_cmd = [
                self.venv_python,
                str(self.project_root / "scripts" / "copywriter.py"),
                "--youtube-id", youtube_id,
                "--title", title,
                "--desc-file", str(desc_file),
            ]
            try:
                subprocess.run(copy_cmd, check=True, capture_output=True, text=True, cwd=str(self.project_root))
                if copy_file.exists() and title_file.exists():
                    return json.dumps({
                        "ok": True,
                        "message": "WeChat copy generated successfully",
                        "copy_path": str(copy_file),
                        "title_path": str(title_file)
                    })
                return json.dumps({"ok": False, "error": "Copy files were not created by copywriter.py"})
            except subprocess.CalledProcessError as e:
                return json.dumps({"ok": False, "error": f"Copywriter failed: {e.stderr}"})
            except Exception as e:
                return json.dumps({"ok": False, "error": f"Unexpected copywriter error: {e}"})
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            lock_file.close()
            logger.info(f"[Lock] Released pipeline lock after copy generation for {youtube_id}.")

    def generate_video_cover(self, youtube_id: str) -> str:
        """Generates a cover image for WeChat Channels from the vertical video.

        Args:
            youtube_id: The 11-character YouTube video ID.
        """
        # [Gemini_3.5_Flash_High_planning]
        lock_path = self.output_dir / "pipeline.lock"
        logger.info(f"[Lock] Waiting for pipeline lock to generate cover for {youtube_id}...")
        lock_file = open(lock_path, "w")
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        logger.info(f"[Lock] Acquired pipeline lock to generate cover for {youtube_id}.")
        try:
            vertical = self.output_dir / f"{youtube_id}_vertical.mp4"
            if not vertical.exists():
                return json.dumps({"ok": False, "error": "Vertical video not found. Run transcription first."})

            cover_file = self.output_dir / f"{youtube_id}_cover.jpg"
            if cover_file.exists():
                return json.dumps({"ok": True, "message": "Cover already exists", "path": str(cover_file)})

            title_file = self.output_dir / f"{youtube_id}_title.txt"
            cover_title = ""
            if title_file.exists():
                try:
                    cover_title = title_file.read_text(encoding="utf-8").strip()
                except Exception:
                    pass
            if not cover_title:
                video_rec = self.db.get_video_by_youtube_id(youtube_id)
                cover_title = video_rec["title"] if video_rec else "Video"

            cover_cmd = [
                self.venv_python,
                str(self.project_root / "scripts" / "cover_generator.py"),
                "--video", str(vertical),
                "--title", cover_title,
                "--output", str(cover_file),
            ]
            try:
                res = subprocess.run(cover_cmd, check=False, capture_output=True, text=True, cwd=str(self.project_root))
                if res.returncode != 0:
                    return json.dumps({"ok": False, "error": f"Cover generator failed: {res.stderr}"})
                if cover_file.exists():
                    return json.dumps({"ok": True, "message": "Cover generated successfully", "path": str(cover_file)})
                return json.dumps({"ok": False, "error": "Cover file was not created by cover_generator.py"})
            except Exception as e:
                return json.dumps({"ok": False, "error": f"Cover generator encountered unexpected error: {e}"})
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            lock_file.close()
            logger.info(f"[Lock] Released pipeline lock after cover generation for {youtube_id}.")

    def upload_to_wechat(self, youtube_id: str) -> str:
        """Uploads the video, cover, copy, and category to WeChat Channels using Playwright.

        Args:
            youtube_id: The 11-character YouTube video ID.
        """
        # [Gemini_3.5_Flash_High_planning]
        lock_path = self.output_dir / "pipeline.lock"
        logger.info(f"[Lock] Waiting for pipeline lock to upload {youtube_id}...")
        lock_file = open(lock_path, "w")
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        logger.info(f"[Lock] Acquired pipeline lock to upload {youtube_id}.")
        try:
            vertical = self.output_dir / f"{youtube_id}_vertical.mp4"
            if not vertical.exists():
                return json.dumps({"ok": False, "error": "Vertical video not found. Run transcription first."})

            copy_file = self.output_dir / f"{youtube_id}_copy.txt"
            if not copy_file.exists():
                return json.dumps({"ok": False, "error": "WeChat copy file not found. Run copywriter first."})

            cover_file = self.output_dir / f"{youtube_id}_cover.jpg"
            title_file = self.output_dir / f"{youtube_id}_title.txt"
            category_file = self.output_dir / f"{youtube_id}_category.txt"

            upload_cmd = [
                self.venv_python,
                str(self.project_root / "scripts" / "wechat_uploader.py"),
                "--video", str(vertical),
                "--copy", str(copy_file),
                "--state", str(self.output_dir / "wechat_state.json"),
                "--no-headless",
            ]
            if cover_file.exists():
                upload_cmd += ["--cover", str(cover_file)]
            if title_file.exists():
                upload_cmd += ["--title-file", str(title_file)]
            if category_file.exists():
                upload_cmd += ["--category-file", str(category_file)]

            try:
                res = subprocess.run(upload_cmd, capture_output=True, text=True, cwd=str(self.project_root))
                if res.returncode == 2:
                    return json.dumps({
                        "ok": False,
                        "error": "WECHAT_LOGIN_EXPIRED",
                        "message": "WeChat login session has expired. Human scanning is required."
                    })
                elif res.returncode != 0:
                    return json.dumps({
                        "ok": False,
                        "error": f"Upload process failed with exit code {res.returncode}",
                        "details": res.stderr
                    })
                return json.dumps({"ok": True, "message": "Uploaded to WeChat Channels successfully"})
            except Exception as e:
                return json.dumps({"ok": False, "error": f"Unexpected error during upload: {e}"})
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            lock_file.close()
            logger.info(f"[Lock] Released pipeline lock after upload {youtube_id}.")

    def update_video_status(self, youtube_id: str, status: str, error_msg: Optional[str] = None) -> str:
        """Updates the processing status of a video in the database.

        Args:
            youtube_id: The 11-character YouTube video ID.
            status: The new status (PENDING, DOWNLOADING, TRANSCRIBING, COPYWRITING, PUBLISHING, PUBLISHED, FAILED, etc.).
            error_msg: Optional error description to save if status is FAILED or LOGIN_REQUIRED.
        """
        # [Gemini_3.5_Flash_High_planning]
        try:
            err = error_msg if error_msg else None
            self.db.update_video_status(youtube_id, status, error_msg=err)
            return json.dumps({"ok": True, "message": f"Status updated to {status}"})
        except Exception as e:
            return json.dumps({"ok": False, "error": f"Failed to update status: {e}"})

    def delete_video_from_db(self, youtube_id: str, delete_files: bool = True) -> str:
        """Deletes a video record and its associated local files.

        Args:
            youtube_id: The 11-character YouTube video ID.
            delete_files: Whether to physically delete local output files.
        """
        # [Gemini_3.5_Flash_High_planning]
        try:
            deleted_files = []
            if delete_files:
                from video_processing.pipeline_manager import PipelineManager
                pm = PipelineManager()
                deleted_files = pm.reset_video_artifacts(youtube_id)

            success = self.db.delete_video_record(youtube_id)
            if success:
                return json.dumps({"ok": True, "message": f"Successfully deleted video {youtube_id}", "deleted_files": deleted_files})
            return json.dumps({"ok": False, "error": "Failed to delete video record from DB"})
        except Exception as e:
            return json.dumps({"ok": False, "error": f"Exception during deletion: {e}"})

    def retry_video_in_db(self, youtube_id: str) -> str:
        """Resets a video's status back to PENDING and clears errors, so it can be re-run.

        Args:
            youtube_id: The 11-character YouTube video ID.
        """
        # [Gemini_3.5_Flash_High_planning]
        try:
            self.db.update_video_status(youtube_id, "PENDING", error_msg=None)
            return json.dumps({"ok": True, "message": f"Video {youtube_id} reset to PENDING"})
        except Exception as e:
            return json.dumps({"ok": False, "error": f"Failed to reset video: {e}"})

    def get_system_stats(self) -> str:
        """Gets overall system statistics from the database (counts by category)."""
        # [Gemini_3.5_Flash_High_planning]
        try:
            counts = self.db.get_tab_counts()
            return json.dumps({"ok": True, "stats": counts})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    def trigger_wechat_login(self) -> str:
        """Launches a local visible browser window to guide the user to scan and log in to WeChat Channels.

        This pops up a browser window on the MacMini host.
        """
        # [Gemini_3.5_Flash_High_planning]
        script = str(self.project_root / "scripts" / "wechat_uploader.py")
        state = str(self.output_dir / "wechat_state.json")
        login_cmd = [
            self.venv_python,
            script,
            "--login-only",
            "--no-headless",
            "--state",
            state
        ]
        try:
            subprocess.Popen(login_cmd, cwd=str(self.project_root))
            return json.dumps({"ok": True, "message": "WeChat login window launched. Please scan the QR code on the screen."})
        except Exception as e:
            return json.dumps({"ok": False, "error": f"Failed to launch WeChat login process: {e}"})

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _find_downloaded_video(self, yid: str) -> Optional[str]:
        _NON_VIDEO_SUFFIXES = {'.description', '.json', '.ytdl', '.part', '.jpg', '.png', '.webp'}
        candidates = [
            f for f in self.output_dir.glob(f"{yid}.*")
            if f.suffix not in _NON_VIDEO_SUFFIXES and f.stat().st_size > 50_000
        ]
        return str(candidates[0]) if candidates else None

    # ── Main Run Entrypoint ───────────────────────────────────────────────────

    def run(self, prompt: str) -> str:
        """Starts a GenerativeModel chat session and processes the prompt using Function Calling.

        This method is blocking and must be run via asyncio.to_thread in the handler.
        """
        # [Gemini_3.5_Flash_High_planning]
        model = genai.GenerativeModel(
            model_name="gemini-flash-lite-latest",
            tools=self.tools,
            system_instruction=self.system_prompt
        )
        chat = model.start_chat(enable_automatic_function_calling=True)
        
        import time
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = chat.send_message(prompt)
                return response.text
            except Exception as e:
                err_str = str(e).lower()
                if "429" in err_str or "quota" in err_str or "exhausted" in err_str:
                    if attempt < max_retries - 1:
                        wait_sec = (attempt + 1) * 5
                        logger.warning(f"Gemini API 429 rate limit hit, retrying in {wait_sec} seconds (attempt {attempt + 1}/{max_retries})...")
                        time.sleep(wait_sec)
                        continue
                logger.error(f"Gemini execution failed: {e}")
                self.send_telegram_message(f"❌ <b>AI Agent Error</b>: {e}")
                return f"Execution failed: {e}"
