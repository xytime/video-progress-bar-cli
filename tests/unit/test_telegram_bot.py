"""tests/unit/test_telegram_bot.py — Telegram Bot 消息路由与参数解析单元测试

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-05-27 | Gemini_3.5_Flash_planning | 初始创建，实现 Telegram URL 路由与裁剪参数提取的 TDD 单元测试 |
"""
import re
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

# 确保 src/ 目录在 sys.path 中
_src = str(Path(__file__).parent.parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from bot.telegram_bot import _YOUTUBE_RE, parse_trim_params, handle_youtube_url


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
                trim_end="60"
            )


if __name__ == "__main__":
    unittest.main()
