"""tests/unit/test_telegram_bot.py — Telegram Bot 消息路由与参数解析单元测试

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-05-27 | Gemini_3.5_Flash_planning | 初始创建，实现 Telegram URL 路由与裁剪参数提取的 TDD 单元测试 |
| 1.1.0 | 2026-05-27 | Gemini_3.5_Flash_planning | 新增 /whole 与 /slice 核心指令测试，验证默认不切片与强制切片策略的路由传导 |
| 1.2.0 | 2026-07-28 | Codex | 覆盖 /status 只读质检报告和 Telegram 快捷菜单 |
| 1.3.0 | 2026-08-18 | Codex | 覆盖 Bot API 传输日志不写入鉴权 URL |
| 1.5.0 | 2026-08-20 | Codex | 覆盖 Highlight 候选显式选定及独立发布主体提示 |
| 1.4.0 | 2026-08-20 | Codex | 覆盖 /highlight 的显式二次确认入口与菜单可见性 |
| 1.6.0 | 2026-08-21 | Codex | 覆盖英语世界候选研究入口不走普通 URL 自动入队。 |
| 1.7.0 | 2026-08-23 | Codex | 覆盖英语世界审核项的唯一投稿批准按钮不退回通用发布命令。 |
"""
import logging
import re
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

# 确保 src/ 目录在 sys.path 中
_src = str(Path(__file__).parent.parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from bot.telegram_bot import _BOT_COMMANDS, _YOUTUBE_RE, cmd_status, handle_youtube_url, parse_trim_params


def test_transport_loggers_do_not_emit_bot_api_info_urls():
    """httpx 的请求 INFO 日志会包含完整 Bot API 鉴权 URL。"""
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
    assert logging.getLogger("httpcore").getEffectiveLevel() >= logging.WARNING


class TestTelegramBotRouting(unittest.IsolatedAsyncioTestCase):
    """测试 Telegram Bot 的消息提取、路由及 URL 校验逻辑"""

    def test_youtube_regex_matching_success(self):
        """[Gemini_3.5_Flash_planning] 验证正则正确匹配各种有效的 YouTube URL 变体"""
        valid_urls = [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "http://youtube.com/watch?v=dQw4w9WgXcQ",
            "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ",
            "https://www.youtube.com/shorts/dQw4w9WgXcQ",
            # 新增支持的 live/ 直播录播回放链接
            "https://www.youtube.com/live/dQw4w9WgXcQ",
            "https://youtube.com/live/dQw4w9WgXcQ",
            # 携带其它查询参数的 URL
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10s",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&feature=share",
            "https://www.youtube.com/watch?time_continue=1&v=dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ?t=10",
            "https://youtube.com/live/dQw4w9WgXcQ?feature=share",
        ]
        for url in valid_urls:
            with self.subTest(url=url):
                match = _YOUTUBE_RE.search(url)
                self.assertIsNotNone(match, f"Failed to match valid URL: {url}")
                # 正则匹配出的内容应尽可能包含完整的 URL 路径与参数以方便后续切分
                self.assertEqual(match.group(0), url)

    def test_youtube_regex_matching_failure(self):
        """[Gemini_3.5_Flash_planning] 验证正则应拒绝非法域名或非视频链接"""
        invalid_urls = [
            "https://evil.com/youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtube.com.evil.com/watch?v=dQw4w9WgXcQ",
            "https://www.youtube.com/channel/UCS_tq7IKjgive1RpIm7O",
            "https://www.youtube.com/@TheVerge",
            "just plain text with no link",
        ]
        for url in invalid_urls:
            with self.subTest(url=url):
                match = _YOUTUBE_RE.search(url)
                self.assertIsNone(match, f"Incorrectly matched invalid URL: {url}")

    def test_youtube_regex_lookbehind_punctuation(self):
        """[Gemini_3.5_Flash_planning] 验证正则在自然语言中提取 URL 时能正确排除末尾的标点符号"""
        cases = [
            (
                "看看这个视频 https://www.youtube.com/watch?v=dQw4w9WgXcQ, 非常精彩",
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            ),
            (
                "请检查这个链接：https://www.youtube.com/live/dQw4w9WgXcQ. 这是一个直播回放。",
                "https://www.youtube.com/live/dQw4w9WgXcQ",
            ),
            (
                "你看了吗？https://youtu.be/dQw4w9WgXcQ?t=10s!",
                "https://youtu.be/dQw4w9WgXcQ?t=10s",
            ),
        ]
        for text, expected_url in cases:
            with self.subTest(text=text):
                match = _YOUTUBE_RE.search(text)
                self.assertIsNotNone(match)
                self.assertEqual(match.group(0), expected_url)

    @patch("bot.telegram_bot._api")
    async def test_handle_youtube_url_integration_with_query_params(self, mock_api_client):
        """[Gemini_3.5_Flash_planning] 验证当链接携带查询参数时，裁剪参数仍然能被正确提取且不被干扰"""
        # 模拟 API 客户端返回值
        mock_api_client.add_video = AsyncMock(return_value={"success": True, "title": "Test", "video_id": "vid123"})

        # 模拟 Telegram Update & Context
        update = MagicMock()
        update.effective_user.id = 12345
        update.message.text = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10s 30 60"
        update.message.reply_text = AsyncMock()
        
        # 绕过管理员鉴权
        with patch("bot.telegram_bot._check_admin", return_value=True):
            await handle_youtube_url(update, MagicMock())

            # 验证 add_video 调用的参数是否准确
            mock_api_client.add_video.assert_called_once_with(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10s",
                trim_start="30",
                trim_end="60",
                disable_slicing=True
            )

    @patch("bot.telegram_bot._api")
    async def test_cmd_whole_routing(self, mock_api_client):
        """[Gemini_3.5_Flash_planning] 验证 /whole 指令能正确拦截并传导 disable_slicing=True"""
        mock_api_client.add_video = AsyncMock(return_value={"success": True, "title": "Test Whole", "video_id": "vid123"})
        update = MagicMock()
        update.effective_user.id = 12345
        update.message.text = "/whole https://www.youtube.com/watch?v=dQw4w9WgXcQ 10 20"
        update.message.reply_text = AsyncMock()

        # CommandHandler 将命令参数分配到 context.args 
        context = MagicMock()
        context.args = ["https://www.youtube.com/watch?v=dQw4w9WgXcQ", "10", "20"]

        from bot.telegram_bot import cmd_whole
        with patch("bot.telegram_bot._check_admin", return_value=True):
            await cmd_whole(update, context)

            mock_api_client.add_video.assert_called_once_with(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                trim_start="10",
                trim_end="20",
                disable_slicing=True
            )

    @patch("bot.telegram_bot._api")
    async def test_cmd_slice_routing(self, mock_api_client):
        """[Gemini_3.5_Flash_planning] 验证 /slice 指令能正确拦截并传导 disable_slicing=False"""
        mock_api_client.add_video = AsyncMock(return_value={"success": True, "title": "Test Slice", "video_id": "vid123"})
        update = MagicMock()
        update.effective_user.id = 12345
        update.message.text = "/slice https://www.youtube.com/watch?v=dQw4w9WgXcQ 15 35"
        update.message.reply_text = AsyncMock()

        context = MagicMock()
        context.args = ["https://www.youtube.com/watch?v=dQw4w9WgXcQ", "15", "35"]

        from bot.telegram_bot import cmd_slice
        with patch("bot.telegram_bot._check_admin", return_value=True):
            await cmd_slice(update, context)

            mock_api_client.add_video.assert_called_once_with(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                trim_start="15",
                trim_end="35",
                disable_slicing=False
            )

    @patch("bot.telegram_bot._api")
    async def test_handle_youtube_url_default_disable_slicing(self, mock_api_client):
        """[Gemini_3.5_Flash_planning] 验证默认直接发送 URL 时，应默认传导 disable_slicing=True 以启用整片发布"""
        mock_api_client.add_video = AsyncMock(return_value={"success": True, "title": "Test Default", "video_id": "vid123"})
        update = MagicMock()
        update.effective_user.id = 12345
        update.message.text = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        update.message.reply_text = AsyncMock()

        with patch("bot.telegram_bot._check_admin", return_value=True):
            await handle_youtube_url(update, MagicMock())

            mock_api_client.add_video.assert_called_once_with(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                trim_start=None,
                trim_end=None,
                disable_slicing=True
            )

    async def test_cmd_status_uses_quality_report_with_keyboard(self):
        update = MagicMock()
        update.effective_user.id = 12345
        update.message.reply_text = AsyncMock()

        with patch("bot.telegram_bot._check_admin", return_value=True), patch(
            "bot.telegram_bot.collect_quality_report", return_value="<b>🟢 正常：有可发队列</b>"
        ):
            await cmd_status(update, MagicMock())

        update.message.reply_text.assert_awaited_once()
        _, kwargs = update.message.reply_text.call_args
        self.assertEqual(kwargs["parse_mode"], "HTML")
        self.assertEqual(kwargs["reply_markup"].keyboard[0][0].text, "/status")

    def test_bot_command_menu_includes_status_first(self):
        self.assertEqual(_BOT_COMMANDS[0].command, "status")
        self.assertIn("质检", _BOT_COMMANDS[0].description)

    async def test_cmd_highlight_id_requires_confirmation_before_creating_job(self):
        from bot.telegram_bot import cmd_highlight

        update = MagicMock()
        update.effective_user.id = 12345
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.args = ["dQw4w9WgXcQ"]

        with patch("bot.telegram_bot._check_admin", return_value=True):
            await cmd_highlight(update, context)

        update.message.reply_text.assert_awaited_once()
        _, kwargs = update.message.reply_text.call_args
        self.assertEqual(kwargs["parse_mode"], "HTML")
        self.assertEqual(kwargs["reply_markup"].inline_keyboard[0][0].callback_data, "hl:create:dQw4w9WgXcQ")

    def test_bot_command_menu_includes_highlight(self):
        self.assertIn("highlight", [command.command for command in _BOT_COMMANDS])

    @patch("bot.telegram_bot._api")
    async def test_english_world_command_starts_research_without_generic_add_video(self, mock_api_client):
        from bot.telegram_bot import cmd_english_world

        mock_api_client.create_english_world_research = AsyncMock(return_value={
            "success": True, "job": {"id": "a" * 32},
        })
        mock_api_client.add_video = AsyncMock()
        update = MagicMock()
        update.effective_user.id = 12345
        update.effective_chat.id = 67890
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.args = []

        created = []

        def discard_task(coro):
            created.append(coro)
            coro.close()

        with patch("bot.telegram_bot._check_admin", return_value=True), patch(
            "bot.telegram_bot.asyncio.create_task", side_effect=discard_task
        ) as create_task:
            await cmd_english_world(update, context)

        mock_api_client.create_english_world_research.assert_awaited_once_with(
            requested_by="telegram", notification_target="67890", source_url=None,
        )
        mock_api_client.add_video.assert_not_called()
        create_task.assert_called_once()
        assert len(created) == 1

    def test_bot_command_menu_includes_english_world(self):
        self.assertIn("english_world", [command.command for command in _BOT_COMMANDS])

    @patch("bot.telegram_bot._api")
    async def test_english_world_review_approval_uses_bound_review_id(self, mock_api_client):
        from bot.telegram_bot import handle_english_world_callback

        review_id = "c" * 32
        mock_api_client.approve_english_world_submission = AsyncMock(return_value={
            "success": True, "item": {"id": review_id, "state": "SUBMISSION_APPROVED"},
        })
        query = MagicMock()
        query.data = f"ew:r:{review_id}"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock()
        update.effective_user.id = 12345
        update.callback_query = query

        with patch("bot.telegram_bot._check_admin", return_value=True):
            await handle_english_world_callback(update, MagicMock())

        mock_api_client.approve_english_world_submission.assert_awaited_once_with(review_id)
        text = query.edit_message_text.call_args.args[0]
        self.assertIn("已接收本条投稿批准", text)
        self.assertNotIn("/process", text)

    @patch("bot.telegram_bot._api")
    async def test_highlight_clip_selection_only_creates_subject(self, mock_api_client):
        from bot.telegram_bot import handle_highlight_callback

        clip_id = "a" * 32
        mock_api_client.select_highlight_clip = AsyncMock(return_value={
            "success": True,
            "clip": {"id": clip_id, "publication_subject_id": f"highlight_clip:{clip_id}"},
        })
        query = MagicMock()
        query.data = f"hl:select:{clip_id}"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock()
        update.effective_user.id = 12345
        update.callback_query = query

        with patch("bot.telegram_bot._check_admin", return_value=True):
            await handle_highlight_callback(update, MagicMock())

        mock_api_client.select_highlight_clip.assert_awaited_once_with(clip_id)
        query.edit_message_text.assert_awaited_once()
        text = query.edit_message_text.call_args.args[0]
        self.assertIn("尚未渲染、上传或发布", text)


if __name__ == "__main__":
    unittest.main()
