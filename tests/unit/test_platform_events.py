"""平台事件格式化测试。

# Modification History
| Version | Date       | Author | Description |
|---------|------------|--------|-------------|
| 1.0.0   | 2026-07-27 | Codex  | 覆盖多平台告警 HTML 格式与 HTML 转义 |
"""

from video_processing.utils.platform_events import PlatformEvent, format_platform_event_html


def test_platform_event_html_contains_shared_fields_and_escapes_reason():
    msg = format_platform_event_html(PlatformEvent(
        platform="Douyin",
        youtube_id="abc123",
        state="UNDER_REVIEW",
        source_kind="NEW",
        action="停止自动回查",
        reason="作品管理异常 <script>",
        severity="critical",
    ))

    assert "Douyin Platform Alert" in msg
    assert "Severity: <code>CRITICAL</code>" in msg
    assert "ID: <code>abc123</code>" in msg
    assert "State: <code>UNDER_REVIEW</code>" in msg
    assert "Source: <code>NEW</code>" in msg
    assert "停止自动回查" in msg
    assert "&lt;script&gt;" in msg
