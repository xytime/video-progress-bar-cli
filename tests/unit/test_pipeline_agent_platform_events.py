"""PipelineAgent 多平台事件工具测试。

# Modification History
| Version | Date       | Author | Description |
|---------|------------|--------|-------------|
| 1.0.0   | 2026-07-27 | Codex  | 覆盖助手 bot 接入共享 PlatformEvent 告警格式 |
"""

import json
from unittest.mock import MagicMock

from bot.pipeline_agent import PipelineAgent


def test_pipeline_agent_exposes_platform_event_formatter(monkeypatch):
    monkeypatch.setattr("bot.pipeline_agent.settings.gemini_api_key", "fake-key")
    agent = PipelineAgent(bot=MagicMock(), loop=MagicMock(), chat_id=123)

    tool_names = {tool.__name__ for tool in agent.tools}
    assert "format_platform_event_alert" in tool_names
    assert "Douyin and Kuaishou" in agent.system_prompt

    result = json.loads(agent.format_platform_event_alert(
        platform="Douyin",
        youtube_id="abc123",
        state="UNDER_REVIEW",
        source_kind="NEW",
        action="停止自动重试",
        reason="作品管理未确认",
        severity="critical",
    ))

    assert result["ok"] is True
    assert "Douyin Platform Alert" in result["message"]
    assert "Severity: <code>CRITICAL</code>" in result["message"]
    assert "停止自动重试" in result["message"]
