"""Anti-gravity 自动封面执行器的失败诊断测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-24 | Codex | 防止 SDK 配额错误被压缩为无产物 |
"""

from __future__ import annotations

from scripts.run_antigravity_cover_doer import _diagnostic_text


class Text:
    def __init__(self, *, text: str = "", error: str = "") -> None:
        self.text = text
        self.error = error


def test_diagnostic_text_prefers_tool_error_and_limits_length():
    message = _diagnostic_text([Text(text="visible"), Text(error="RESOURCE_EXHAUSTED")])

    assert "visible" in message
    assert "RESOURCE_EXHAUSTED" in message
    assert len(_diagnostic_text([Text(text="x" * 700)])) == 500
