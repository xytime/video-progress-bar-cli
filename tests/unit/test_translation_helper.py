# -*- coding: utf-8 -*-
"""翻译终级兜底单元测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-10-05 | Codex | 逐段限流恢复、节流和跨次检查点保留。 |
| 1.0.0 | 2026-08-31 | Codex | 覆盖 Google 终级兜底的受信 TLS、单请求时限与整片预算边界。 |
"""

from pathlib import Path
from unittest.mock import MagicMock, patch
import sys

import requests
import pytest

_src_root = Path(__file__).parent.parent.parent / "src"
if str(_src_root) not in sys.path:
    sys.path.insert(0, str(_src_root))

import video_processing.utils.translation_helper as th


def test_translate_batch_uses_google_directly():
    with patch.object(th, "_google_translate_batch", return_value=["谷歌译文"]) as mock_google:
        assert th.translate_batch(["Hello"]) == ["谷歌译文"]
    mock_google.assert_called_once()


def test_translate_text_keeps_original_on_failed_fallback():
    with patch.object(th, "_google_translate_batch", return_value=[""]):
        assert th.translate_text("Stoicism") == "Stoicism"


def test_google_batch_filters_error_pages_and_keeps_length():
    translator = MagicMock()
    translator.translate.side_effect = ["<html>Error</html>", "正常译文"]
    with patch.object(th, "GoogleTranslator", return_value=translator):
        assert th._google_translate_batch(["a", "b"]) == ["", "正常译文"]


def test_google_batch_filters_plain_text_google_500_page():
    translator = MagicMock()
    translator.translate.side_effect = [
        "Error 500 (Server Error)!!1500. That's an error. There was an error. "
        "Please try again later. That's all we know.",
    ]
    with patch.object(th, "GoogleTranslator", return_value=translator):
        assert th._google_translate_batch(["His patient, let's call her Anna"]) == [""]


def test_google_batch_returns_empty_entries_when_unavailable():
    with patch.object(th, "GoogleTranslator", None):
        assert th._google_translate_batch(["a", "b"]) == ["", ""]


def test_google_batch_uses_verified_tls_and_bounded_timeout(monkeypatch):
    response = MagicMock(status_code=200, text='<div class="result-container">你好</div>')
    captured = {}

    def fake_get(*args, **kwargs):
        captured.update(kwargs)
        return response

    monkeypatch.setattr(th.settings, "google_translate_request_timeout_seconds", 45)
    monkeypatch.setattr(th.settings, "google_translate_total_timeout_seconds", 120)
    monkeypatch.setattr(th.requests, "get", fake_get)

    assert th._google_translate_batch(["Hello"]) == ["你好"]
    assert captured["verify"] is True
    assert captured["timeout"] == (20, 45)
    response.close.assert_called_once()


def test_google_request_clamps_to_remaining_batch_budget(monkeypatch):
    captured = {}

    def fake_get(*args, **kwargs):
        captured.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(th.settings, "google_translate_request_timeout_seconds", 90)
    monkeypatch.setattr(th.requests, "get", fake_get)
    monkeypatch.setattr(th.time, "monotonic", lambda: 100.0)

    th._VerifiedGoogleRequests(deadline=105.0).get("https://example.invalid")

    assert captured["verify"] is True
    assert captured["timeout"] == (2.5, 2.5)


def test_google_request_refuses_expired_batch_budget(monkeypatch):
    monkeypatch.setattr(th.time, "monotonic", lambda: 100.0)

    with pytest.raises(requests.Timeout, match="batch budget exhausted"):
        th._VerifiedGoogleRequests(deadline=100.0).get("https://example.invalid")


def test_caption_processor_does_not_replace_requests_session_method():
    import video_processing.processors.caption_processor  # noqa: F401

    assert requests.Session.request.__module__ == "requests.sessions"


def test_mid_batch_rate_limit_recovers_without_retranslating_completed_segments(monkeypatch):
    now = [100.0]
    waits = []
    monkeypatch.setattr(th.time, "monotonic", lambda: now[0])
    def sleep(seconds):
        waits.append(seconds)
        now[0] += seconds
    monkeypatch.setattr(th.time, "sleep", sleep)
    translator = MagicMock()
    translator.translate.side_effect = ["第一段", RuntimeError("429 Too Many Requests"), "第二段", "第三段"]
    monkeypatch.setattr(th, "GoogleTranslator", lambda **kwargs: translator)
    assert th._google_translate_batch(["one", "two", "three"]) == ["第一段", "第二段", "第三段"]
    assert [call.args[0] for call in translator.translate.call_args_list] == ["one", "two", "two", "three"]
    assert min(waits) >= th.settings.google_translate_interval_seconds
    assert max(waits) == 2.0


def test_failed_batch_retains_completed_cache_and_can_resume(tmp_path, monkeypatch):
    translator = MagicMock()
    translator.translate.side_effect = ["第一段", requests.Timeout("timeout"), requests.Timeout("timeout"), requests.Timeout("timeout")]
    monkeypatch.setattr(th, "GoogleTranslator", lambda **kwargs: translator)
    monkeypatch.setattr(th.time, "sleep", lambda seconds: None)
    errors = []
    assert th._google_translate_batch(["one", "two"], cache_dir=tmp_path, error_out=errors) == ["第一段", ""]
    assert "segment 2/2" in errors[-1]
    translator.translate.reset_mock()
    translator.translate.side_effect = ["第二段"]
    assert th._google_translate_batch(["one", "two"], cache_dir=tmp_path) == ["第一段", "第二段"]
    translator.translate.assert_called_once_with("two")


def test_shared_deadline_stops_google_before_any_request(monkeypatch):
    translator = MagicMock()
    monkeypatch.setattr(th, "GoogleTranslator", lambda **kwargs: translator)
    monkeypatch.setattr(th.time, "monotonic", lambda: 100.0)
    errors = []
    assert th._google_translate_batch(["one"], deadline=99.0, error_out=errors) == [""]
    translator.translate.assert_not_called()
    assert "budget exhausted" in errors[-1]
