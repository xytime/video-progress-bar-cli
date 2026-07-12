# -*- coding: utf-8 -*-
"""Unit tests for deepseek_translation.

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-05 | Codex  | 初始创建：覆盖 DeepSeek provider 无 key 跳过与响应解析 |
| 1.1.0   | 2026-07-06 | Codex  | 覆盖 DeepSeek payload 注入全局上下文硬约束与金融翻译规则 |
| 1.2.0   | 2026-07-06 | Codex  | 覆盖 DeepSeek payload 复用共享翻译硬约束 |
| 1.3.0   | 2026-07-06 | Codex  | 覆盖 DeepSeek 响应顶层 translations 包装解析 |
| 1.4.0   | 2026-07-13 | Codex  | 覆盖翻译+vocabulary JSON 对齐和长视频分批调用 |
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
    _build_vocab_payload,
    translate_batch_with_vocab_deepseek,
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


def test_deepseek_translation_vocab_parses_and_filters_non_substrings():
    settings = _Settings()
    settings.deepseek_api_key = "test-key"
    payload = {
        "choices": [{"message": {"content": json.dumps([
            {"id": 1, "translation": "市场出现波动", "vocab": {"volatility": "波动", "wrong": "不存在"}},
            {"id": 0, "translation": "完成募集", "vocab": {"fund close": "完成募集"}},
        ], ensure_ascii=False)}}]
    }
    with patch("urllib.request.urlopen", return_value=_Response(payload)):
        result = translate_batch_with_vocab_deepseek(
            ["Fund closed", "Market volatility"], settings_obj=settings
        )
    assert result == [
        {"translation": "完成募集", "vocab": {"fund close": "完成募集"}},
        {"translation": "市场出现波动", "vocab": {"volatility": "波动"}},
    ]
    assert "exact substring" in _build_vocab_payload(["Fund closed"], context_text="", model="test")["messages"][1]["content"]


def test_deepseek_vocab_prompt_uses_pet_and_keeps_proper_nouns():
    prompt = _build_vocab_payload(["Wall Street researchers use AI agents."], context_text="", model="test")["messages"][1]["content"]
    assert "CEFR B1 (PET)" in prompt
    assert "Always extract proper nouns" in prompt


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


def test_deepseek_parses_wrapped_translations_response():
    settings = _Settings()
    settings.deepseek_api_key = "test-key"
    payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "translations": [
                                {"id": 0, "translation": "你好"},
                                {"id": 1, "translation": "世界"},
                            ]
                        },
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
    assert "Global context:" in user_prompt
    assert "Treat the global context as hard constraints" in user_prompt
    assert "close/final close usually means 完成募集/最终关账" in user_prompt
    assert "billion/bn = 十亿美元" in user_prompt
    assert "$49B" in user_prompt


def test_deepseek_translation_vocab_batches_long_input():
    settings = _Settings()
    settings.deepseek_api_key = "test-key"
    first = [{"id": i, "translation": f"译文{i}", "vocab": {}} for i in range(25)]
    second = [{"id": 0, "translation": "译文25", "vocab": {}}]
    payloads = [
        {"choices": [{"message": {"content": json.dumps(first, ensure_ascii=False)}}]},
        {"choices": [{"message": {"content": json.dumps(second, ensure_ascii=False)}}]},
    ]

    with patch("urllib.request.urlopen", side_effect=[_Response(payload) for payload in payloads]) as mocked:
        result = translate_batch_with_vocab_deepseek(
            [f"segment {i}" for i in range(26)],
            settings_obj=settings,
        )

    assert result is not None
    assert len(result) == 26
    assert result[-1]["translation"] == "译文25"
    assert mocked.call_count == 2
