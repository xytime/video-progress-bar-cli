"""PipelineAgent 传输层短暂失败的回归测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-10 | Codex | 覆盖 Gemini TLS EOF 有限重试和最终单条友好降级 |
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from bot.pipeline_agent import PipelineAgent, _is_transient_gemini_error


def _agent_with_chat(chat: MagicMock) -> PipelineAgent:
    agent = PipelineAgent.__new__(PipelineAgent)
    agent._genai_client = SimpleNamespace(chats=SimpleNamespace(create=MagicMock(return_value=chat)))
    agent.tools = []
    agent.system_prompt = "test"
    agent._deepseek_client = None
    return agent


def test_tls_eof_is_a_transient_gemini_failure():
    assert _is_transient_gemini_error(
        OSError("[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol")
    )


def test_pipeline_agent_retries_tls_eof_then_returns_response():
    chat = MagicMock()
    chat.send_message.side_effect = [
        OSError("[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol"),
        SimpleNamespace(text="已恢复"),
    ]
    agent = _agent_with_chat(chat)

    with patch("bot.pipeline_agent.time.sleep") as sleep:
        result = agent.run("测试")

    assert result == "已恢复"
    assert chat.send_message.call_count == 2
    sleep.assert_called_once_with(1)


def test_pipeline_agent_uses_deepseek_after_retries_exhausted():
    chat = MagicMock()
    chat.send_message.side_effect = OSError("[SSL: UNEXPECTED_EOF_WHILE_READING]")
    agent = _agent_with_chat(chat)
    agent._run_deepseek_fallback = MagicMock(return_value="DeepSeek 已接管")

    with patch("bot.pipeline_agent.time.sleep"):
        result = agent.run("测试")

    assert result == "DeepSeek 已接管"
    assert chat.send_message.call_count == 3
    agent._run_deepseek_fallback.assert_called_once_with("测试")


def test_deepseek_fallback_returns_model_text(monkeypatch):
    message = SimpleNamespace(content="DeepSeek 回答", tool_calls=[])
    client = MagicMock()
    client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(message=message)])
    agent = _agent_with_chat(MagicMock())
    agent._deepseek_client = client
    monkeypatch.setattr("bot.pipeline_agent.settings.deepseek_api_key", "fake-key")

    assert agent._run_deepseek_fallback("你好") == "DeepSeek 回答"
    assert client.chat.completions.create.call_count == 1
