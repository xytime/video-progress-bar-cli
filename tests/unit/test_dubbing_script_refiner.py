"""DeepSeek 普通话脚本精修的边界测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-29 | Codex | 验证 thinking 请求、逐段对齐及不完整响应阻断 |
| 1.1.0 | 2026-08-01 | Codex | 覆盖时长失配片段的短写 JSON 合约 |
"""

import json
from unittest.mock import Mock

import pytest

from video_processing.dubbing.script_refiner import DubbingScriptRefiner


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_refiner_sends_thinking_request_and_preserves_chunk_order(monkeypatch):
    from config.settings import settings
    import video_processing.dubbing.script_refiner as module

    monkeypatch.setattr(settings, "deepseek_api_key", "test-key")
    monkeypatch.setattr(settings, "dubbing_deepseek_thinking_enabled", True)
    captured = {}

    def fake_urlopen(request, timeout):
        captured.update(json.loads(request.data.decode("utf-8")))
        return _Response({"choices": [{"message": {"content": json.dumps({"items": [{"id": 0, "zh_text": "第一句。"}, {"id": 1, "zh_text": "第二句。"}]}, ensure_ascii=False)}}]})

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
    chunks = [{"source_text": "First.", "zh_text": "第一句"}, {"source_text": "Second.", "zh_text": "第二句"}]

    refined = DubbingScriptRefiner().refine(chunks, video_title="测试标题")

    assert [item["zh_text"] for item in refined] == ["第一句。", "第二句。"]
    assert captured["thinking"] == {"type": "enabled"}
    assert captured["response_format"] == {"type": "json_object"}


def test_refiner_rejects_incomplete_alignment(monkeypatch):
    from config.settings import settings
    import video_processing.dubbing.script_refiner as module

    monkeypatch.setattr(settings, "deepseek_api_key", "test-key")
    monkeypatch.setattr(module.urllib.request, "urlopen", Mock(return_value=_Response({"choices": [{"message": {"content": '{"items":[{"id":0,"zh_text":"第一句。"}]}'}}]})))

    with pytest.raises(RuntimeError, match="数量或 ID 不完整"):
        DubbingScriptRefiner().refine(
            [{"source_text": "First.", "zh_text": "第一句"}, {"source_text": "Second.", "zh_text": "第二句"}],
            video_title="测试标题",
        )


def test_refiner_shortens_single_timing_mismatch(monkeypatch):
    from config.settings import settings
    import video_processing.dubbing.script_refiner as module

    monkeypatch.setattr(settings, "deepseek_api_key", "test-key")
    captured = {}

    def fake_urlopen(request, timeout):
        captured.update(json.loads(request.data.decode("utf-8")))
        return _Response({"choices": [{"message": {"content": '{"zh_text":"每天看华尔街真相炸弹，抢先懂市场。"}'}}]})

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)

    rewritten = DubbingScriptRefiner().shorten_for_timing(
        {
            "source_text": "Join me every day for Wall Street Truth Bombs before the market figures them out",
            "zh_text": "朋友们，每天来和我一起看《华尔街真相炸弹》。我会在市场弄明白之前，就在这里把真相炸弹抛出来。",
        },
        video_title="测试标题",
        actual_ms=6800,
        target_ms=4880,
    )

    assert rewritten == "每天看华尔街真相炸弹，抢先懂市场。"
    assert "previous synthesized duration ms: 6800" in captured["messages"][1]["content"]
