"""vocab_helper Gemini SDK 超时配置回归测试。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.1.0   | 2026-08-27 | Codex  | 覆盖整片 deadline 对最后 Gemini 请求和重试前检查的硬约束。 |
| 1.0.0   | 2026-07-25 | Codex  | 覆盖 google-genai HttpOptions.timeout 使用毫秒单位，防止退回 90ms |
"""

from video_processing.utils import vocab_helper


def test_genai_http_timeout_is_milliseconds_not_seconds():
    assert vocab_helper._GENAI_HTTP_TIMEOUT_MS == 90_000


def test_remaining_request_timeout_is_capped_by_deadline(monkeypatch):
    monkeypatch.setattr(vocab_helper.time, "monotonic", lambda: 100.0)

    assert vocab_helper._remaining_request_timeout_ms(250.0) == 90_000
    assert vocab_helper._remaining_request_timeout_ms(130.0) == 30_000
    assert vocab_helper._remaining_request_timeout_ms(100.0) == 0


def test_retry_refuses_to_issue_request_after_candidate_deadline(monkeypatch):
    class Pool:
        @staticmethod
        def order(*_args, **_kwargs):
            return ["gemini-test"]

    class Client:
        class models:
            @staticmethod
            def generate_content(*_args, **_kwargs):
                raise AssertionError("deadline-exhausted candidate must not issue a request")

    monkeypatch.setattr(vocab_helper, "DynamicTranslationModelPool", lambda _path: Pool())
    monkeypatch.setattr(vocab_helper.time, "monotonic", lambda: 200.0)

    assert vocab_helper._call_with_retry(
        Client(), "prompt", object(), deadline=200.0,
    ) is None
