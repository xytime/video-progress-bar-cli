# -*- coding: utf-8 -*-
"""Unit tests for deepseek_translation.

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-05 | Codex  | 初始创建：覆盖 DeepSeek provider 无 key 跳过与响应解析 |
| 1.1.0   | 2026-07-06 | Codex  | 覆盖 DeepSeek payload 注入全局上下文硬约束与金融翻译规则 |
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

_src_root = Path(__file__).parent.parent.parent / "src"
if str(_src_root) not in sys.path:
    sys.path.insert(0, str(_src_root))

from video_processing.utils.deepseek_translation import (  # noqa: E402
    _build_payload,
    translate_batch_deepseek,
)


class _Settings:
    deepseek_api_key = ""
    deepseek_base_url = "https://api.deepseek.test"
    deepseek_model = "deepseek-v4-flash"


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


def test_deepseek_returns_none_without_key():
    settings = _Settings()
    settings.deepseek_api_key = ""

    with patch("urllib.request.urlopen") as mock_urlopen:
        result = translate_batch_deepseek(["Hello"], settings_obj=settings)

    assert result is None
    mock_urlopen.assert_not_called()


def test_deepseek_parses_id_aligned_translations():
    settings = _Settings()
    settings.deepseek_api_key = "test-key"
    payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        [
                            {"id": 1, "translation": "世界"},
                            {"id": 0, "translation": "你好"},
                        ],
                        ensure_ascii=False,
                    )
                }
            }
        ]
    }

    with patch("urllib.request.urlopen", return_value=_Response(payload)):
        result = translate_batch_deepseek(["Hello", "World"], settings_obj=settings)

    assert result == ["你好", "世界"]


def test_deepseek_payload_uses_context_as_hard_constraints():
    payload = _build_payload(
        ["MGX announced the final close of Fund I at US$49bn."],
        context_text=(
            "Global video context for subtitle translation:\n"
            "- Domain: finance/technology\n"
            "- Source facts to preserve:\n"
            "  - Preserve USD amount magnitudes exactly where mentioned: $49B."
        ),
        model="deepseek-test",
    )

    user_prompt = payload["messages"][1]["content"]

    assert payload["model"] == "deepseek-test"
    assert "Global context and hard constraints" in user_prompt
    assert "Treat the global context as hard constraints" in user_prompt
    assert "close/final close usually means 完成募集/最终关账" in user_prompt
    assert "billion/bn = 十亿美元" in user_prompt
    assert "$49B" in user_prompt
