"""DeepSeek 字幕候选时间预算回归测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-27 | Codex | 锁定长片候选预算耗尽时不得继续发起请求 |
"""

from types import SimpleNamespace

from video_processing.utils import deepseek_translation


def test_vocab_candidate_stops_before_request_when_total_budget_is_exhausted(monkeypatch):
    settings = SimpleNamespace(
        deepseek_api_key="test-key",
        deepseek_base_url="https://api.deepseek.com",
        deepseek_model="deepseek-test",
        deepseek_subtitle_total_timeout_seconds=30,
    )
    monotonic_values = iter((100.0, 130.0))
    monkeypatch.setattr(deepseek_translation.time, "monotonic", lambda: next(monotonic_values))
    urlopen_calls = []

    def fail_if_called(*_args, **_kwargs):
        urlopen_calls.append(True)
        raise AssertionError("budget-exhausted candidate must not issue another HTTP request")

    monkeypatch.setattr(deepseek_translation.urllib.request, "urlopen", fail_if_called)
    errors = []

    result = deepseek_translation.translate_batch_with_vocab_deepseek(
        ["A subtitle segment."], settings_obj=settings, error_out=errors,
    )

    assert result is None
    assert urlopen_calls == []
    assert errors == ["DeepSeek subtitle candidate budget exceeded (30s)"]
