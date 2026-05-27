# -*- coding: utf-8 -*-
"""Unit tests for video trimming and parsing logic.

# Modification History
| Version | Date       | Author           | Description |
|---------|------------|------------------|-------------|
| 1.0.0   | 2026-05-27 | Gemini_3.5_Flash | 初始创建，实现全套裁剪与解析逻辑测试 |
"""

import sys
import unittest
from pathlib import Path
from typing import Optional
from pydantic import ValidationError

# Ensure src/ is in sys.path
_src = str(Path(__file__).parent.parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from bot.telegram_bot import parse_trim_params
from web.app import AddVideoRequest


class TestTrimAndParsing(unittest.TestCase):

    def test_parse_trim_params_success(self):
        """测试不同形式的极简交互语法解析"""
        cases = [
            # (输入文本, 预期结果)
            ("38 14:43", ("38", "14:43")),
            ("38 883", ("38", "883")),
            ("30", ("30", None)),
            ("-300", (None, "300")),
            ("-14:43", (None, "14:43")),
            ("30 到 120", ("30", "120")),
            ("38-14:43", ("38", "14:43")),
            ("  30  to   1:20:30  ", ("30", "1:20:30")),
            ("invalid text", (None, None)),
            ("", (None, None)),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(parse_trim_params(text), expected)

    def test_pydantic_validation(self):
        """测试 FastAPI 的 AddVideoRequest Pydantic 模型接收可选参数"""
        # 1. 仅有 URL
        req = AddVideoRequest(url="https://youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertEqual(req.url, "https://youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertIsNone(req.trim_start)
        self.assertIsNone(req.trim_end)

        # 2. 携带 trim 参数
        req_trim = AddVideoRequest(
            url="https://youtube.com/watch?v=dQw4w9WgXcQ",
            trim_start="38",
            trim_end="14:43"
        )
        self.assertEqual(req_trim.trim_start, "38")
        self.assertEqual(req_trim.trim_end, "14:43")


if __name__ == "__main__":
    unittest.main()
