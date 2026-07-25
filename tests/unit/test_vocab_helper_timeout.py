"""vocab_helper Gemini SDK 超时配置回归测试。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-25 | Codex  | 覆盖 google-genai HttpOptions.timeout 使用毫秒单位，防止退回 90ms |
"""

from video_processing.utils import vocab_helper


def test_genai_http_timeout_is_milliseconds_not_seconds():
    assert vocab_helper._GENAI_HTTP_TIMEOUT_MS == 90_000
