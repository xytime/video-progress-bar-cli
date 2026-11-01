"""grok CLI 字幕供应商的边界测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-01 | Grok Bot | 验证无工具单轮调用参数、结构化输出提取、脱敏错误与字幕候选接入。 |
"""
import json
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from video_processing.utils import grok_provider
from video_processing.utils.grok_provider import GrokProviderError, run_grok_structured
from video_processing.processors.caption_processor import AutoCaptionProcessor

SCHEMA = {"type": "object", "properties": {"items": {"type": "array"}}}


def _completed(stdout="", stderr="", code=0):
    return subprocess.CompletedProcess(args=[], returncode=code, stdout=stdout, stderr=stderr)


def test_runs_single_turn_without_tools_and_returns_structured_output(monkeypatch):
    seen = {}

    def fake_run(args, **kwargs):
        seen.update(args=args, kwargs=kwargs)
        return _completed(json.dumps({"text": "{}", "structuredOutput": {"items": [1]}}))

    monkeypatch.setattr(grok_provider.subprocess, "run", fake_run)
    result = run_grok_structured("译", schema=SCHEMA, command="grok", timeout_sec=30,
                                 environment={"HTTPS_PROXY": "http://127.0.0.1:1"})
    args = seen["args"]
    assert result == {"items": [1]}
    assert args[args.index("--tools") + 1] == ""
    assert {"--no-subagents", "--disable-web-search"} <= set(args)
    assert args[args.index("--max-turns") + 1] == "1"
    assert "--model" not in args
    assert seen["kwargs"]["env"] == {"HTTPS_PROXY": "http://127.0.0.1:1"}
    assert seen["kwargs"]["timeout"] == 30


def test_missing_structured_output_and_nonzero_exit_are_sanitized(monkeypatch):
    monkeypatch.setattr(grok_provider.subprocess, "run",
                        lambda args, **kw: _completed(json.dumps({"text": "secret prompt echo"})))
    with pytest.raises(GrokProviderError, match="no structuredOutput"):
        run_grok_structured("p", schema=SCHEMA, command="grok", timeout_sec=5)
    monkeypatch.setattr(grok_provider.subprocess, "run",
                        lambda args, **kw: _completed(stderr="429 quota secret prompt", code=2))
    with pytest.raises(GrokProviderError) as error:
        run_grok_structured("p", schema=SCHEMA, command="grok", timeout_sec=5)
    assert str(error.value) == "grok exit 2: rate limit"


def test_timeout_and_missing_binary(monkeypatch):
    def timeout(args, **kw):
        raise subprocess.TimeoutExpired(args, 5)
    monkeypatch.setattr(grok_provider.subprocess, "run", timeout)
    with pytest.raises(GrokProviderError, match="timed out"):
        run_grok_structured("p", schema=SCHEMA, command="grok", timeout_sec=5)

    def missing(args, **kw):
        raise FileNotFoundError(args[0])
    monkeypatch.setattr(grok_provider.subprocess, "run", missing)
    with pytest.raises(GrokProviderError, match="command not found"):
        run_grok_structured("p", schema=SCHEMA, command="grok", timeout_sec=5)


@patch("video_processing.processors.caption_processor.run_agy_structured")
@patch("video_processing.processors.caption_processor.run_grok_structured")
def test_caption_grok_candidate_reuses_agy_contract(mock_grok, mock_agy):
    mock_grok.return_value = {"items": [
        {"id": 0, "translation": "市场波动正在加剧。", "vocab": {"volatility": "波动", "bad": "不存在"}},
    ]}
    processor = AutoCaptionProcessor.__new__(AutoCaptionProcessor)
    processor._last_provider_error = ""
    processor._remaining_translation_budget = lambda: 300

    candidate = processor._build_translation_candidate("grok", ["Market volatility is intensifying."], "")

    assert candidate is not None and candidate.provider == "grok"
    assert candidate.vocabs == [{"volatility": "波动"}]
    assert mock_agy.call_count == 0
    kwargs = mock_grok.call_args.kwargs
    assert kwargs["timeout_sec"] <= 150 and "environment" in kwargs
