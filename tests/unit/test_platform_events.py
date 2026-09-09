"""平台事件格式化测试。

# Modification History
| Version | Date       | Author | Description |
|---------|------------|--------|-------------|
| 1.1.0   | 2026-09-09 | Codex  | 覆盖合法 YouTube ID 的可点击来源链接与非法值拒绝。 |
| 1.0.0   | 2026-07-27 | Codex  | 覆盖多平台告警 HTML 格式与 HTML 转义 |
"""

from video_processing.utils.platform_events import (
    PlatformEvent,
    format_platform_event_html,
    format_youtube_source_link_html,
    youtube_source_url,
)


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


def test_platform_event_links_valid_youtube_source_and_rejects_untrusted_ids():
    youtube_id = "ODhae8RmBIc"
    msg = format_platform_event_html(PlatformEvent(
        platform="Douyin",
        youtube_id=youtube_id,
        reason="作品管理已确认",
    ))

    assert 'href="https://www.youtube.com/watch?v=ODhae8RmBIc"' in msg
    assert "打开 YouTube 原视频" in msg
    assert youtube_source_url(youtube_id) == "https://www.youtube.com/watch?v=ODhae8RmBIc"
    assert format_youtube_source_link_html('ODhae8RmBIc\"><b>injected') == ""
    assert youtube_source_url('ODhae8RmBIc\"><b>injected') == ""
