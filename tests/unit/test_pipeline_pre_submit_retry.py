"""上传前瞬态失败重试与文案金额告警测试。

# Modification History
| Version | Date | Author | Description |
| ------- | ---- | ------ | ----------- |
| 1.3.0 | 2026-08-22 | Codex | 覆盖 Telegram 手机审核视频的 HTTP 回执与视频上传载荷。 |
| 1.0.0 | 2026-08-05 | Codex | 覆盖可安全自动重试边界、提交证据保护和 Telegram 数字告警 |
| 1.1.0 | 2026-08-05 | Codex | 覆盖 curl SSL 超时重试及 Telegram 管理员回退会话 |
| 1.2.0 | 2026-08-05 | Codex | 验证 Telegram 告警 HTTP 回执，而非将调用本身视作送达 |
| 1.4.0 | 2026-08-24 | Codex | 验证 Bot API ok/message_id 回执与重复 P1 通知抑制。 |
| 1.5.0 | 2026-08-24 | Codex | UNKNOWN 不能抑制重要通知；同一任务的变动原因仍遵循稳定去重键。 |
| 1.6.0 | 2026-08-27 | Codex | 所有字幕翻译提供方暂时失败应走提交前有界重试，不得直接沉没为 FAILED。 |
"""

import json

import requests

from config.settings import settings
from video_processing.pipeline_manager import PipelineManager


def _manager(tmp_path, youtube_id: str = "retryable-video") -> PipelineManager:
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager._OUT_DIR = tmp_path
    assert manager.db.add_video(youtube_id, "测试标题", "test-channel", score=80)
    return manager


def test_transient_pre_submit_failure_requeues_with_bounded_attempt(tmp_path):
    manager = _manager(tmp_path)
    manager.db.update_video_status("retryable-video", "COPYWRITING")
    messages = []
    manager.send_telegram_msg = messages.append

    assert manager._requeue_transient_pre_submission_failure(
        "retryable-video",
        "测试标题",
        "GeneratedContentValidationError: upstream HTTP error 500",
    )

    row = manager.db.get_video_by_youtube_id("retryable-video")
    assert row["status"] == "PENDING"
    assert row["retry_count"] == 1
    assert "自动重试 1/2" in row["error_msg"]
    assert len(messages) == 1
    assert "Pre-submit auto retry scheduled" in messages[0]


def test_curl_ssl_timeout_is_a_retryable_pre_submit_failure(tmp_path):
    manager = _manager(tmp_path, "curl-timeout-video")
    manager.db.update_video_status("curl-timeout-video", "DOWNLOADING")
    manager.send_telegram_msg = lambda _message: None

    assert manager._requeue_transient_pre_submission_failure(
        "curl-timeout-video", "测试标题", "curl: (28) SSL connection timeout"
    )

    row = manager.db.get_video_by_youtube_id("curl-timeout-video")
    assert row["status"] == "PENDING"
    assert row["retry_count"] == 1


def test_all_subtitle_translation_providers_failure_is_retryable_before_submission(tmp_path):
    manager = _manager(tmp_path, "subtitle-provider-outage")
    manager.db.update_video_status("subtitle-provider-outage", "TRANSCRIBING")
    manager.send_telegram_msg = lambda _message: None

    assert manager._requeue_transient_pre_submission_failure(
        "subtitle-provider-outage",
        "测试标题",
        "All subtitle translation providers failed or were blocked.",
    )

    row = manager.db.get_video_by_youtube_id("subtitle-provider-outage")
    assert row["status"] == "PENDING"
    assert row["retry_count"] == 1


def test_manager_uses_active_telegram_chat_id_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "telegram_chat_id", None)
    monkeypatch.setattr(settings, "telegram_admin_ids", "fallback-chat,another-admin")

    manager = _manager(tmp_path, "telegram-fallback-video")

    assert manager.telegram_chat_id == "fallback-chat"


def test_telegram_send_checks_http_success(monkeypatch, tmp_path):
    manager = _manager(tmp_path, "telegram-send-video")
    manager.telegram_token = "test-token"
    manager.telegram_chat_id = "test-chat"
    calls = []

    class Response:
        ok = True
        status_code = 200

        @staticmethod
        def json():
            return {"ok": True, "result": {"message_id": 101}}

    def fake_post(*args, **kwargs):
        calls.append((args, kwargs))
        return Response()

    monkeypatch.setattr("video_processing.telegram_delivery.requests.post", fake_post)

    assert manager.send_telegram_msg("测试告警") is True
    assert len(calls) == 1


def test_telegram_review_video_checks_http_success(monkeypatch, tmp_path):
    manager = _manager(tmp_path, "telegram-review-video")
    manager.telegram_token = "test-token"
    manager.telegram_chat_id = "test-chat"
    video = tmp_path / "telegram-review-video_vertical.mp4"
    video.write_bytes(b"review-video")
    calls = []

    class Response:
        ok = True
        status_code = 200

        @staticmethod
        def json():
            return {"ok": True, "result": {"message_id": 102}}

    def fake_post(*args, **kwargs):
        calls.append((args, kwargs))
        return Response()

    monkeypatch.setattr("video_processing.telegram_delivery.requests.post", fake_post)

    assert manager.send_telegram_video(video, "审核副本") is True
    request_args, request_kwargs = calls[0]
    assert request_args[0].endswith("/sendVideo")
    assert request_kwargs["data"]["chat_id"] == "test-chat"
    assert request_kwargs["files"]["video"][0] == video.name


def test_manager_suppresses_duplicate_p1_notification(monkeypatch, tmp_path):
    manager = _manager(tmp_path, "telegram-dedupe")
    manager.telegram_token = "test-token"
    manager.telegram_chat_id = "test-chat"
    calls = []

    class Response:
        ok = True
        status_code = 200

        @staticmethod
        def json():
            return {"ok": True, "result": {"message_id": 103}}

    def fake_post(*args, **kwargs):
        calls.append((args, kwargs))
        return Response()

    monkeypatch.setattr("video_processing.telegram_delivery.requests.post", fake_post)

    assert manager.send_telegram_msg("❌ <b>Video Failed</b>\\nID: <code>telegram-dedupe</code>")
    assert not manager.send_telegram_msg("❌ <b>Video Failed</b>\\nID: <code>telegram-dedupe</code>")
    assert len(calls) == 1


def test_manager_retries_unknown_notification_instead_of_treating_it_as_delivered(monkeypatch, tmp_path):
    manager = _manager(tmp_path, "telegram-unknown")
    manager.telegram_token = "test-token"
    manager.telegram_chat_id = "test-chat"
    calls = []

    class Response:
        ok = True
        status_code = 200

        @staticmethod
        def json():
            return {"ok": True, "result": {"message_id": 104}}

    def fake_post(*_args, **_kwargs):
        calls.append(True)
        if len(calls) == 1:
            raise requests.Timeout("network timeout")
        return Response()

    monkeypatch.setattr("video_processing.telegram_delivery.requests.post", fake_post)
    message = "❌ <b>Video Failed</b>\\nID: <code>telegram-unknown</code>\\nReason: timeout"

    assert not manager.send_telegram_msg(message)
    assert manager.send_telegram_msg(message)
    assert len(calls) == 2


def test_manager_dedupes_same_task_when_failure_reason_changes(monkeypatch, tmp_path):
    manager = _manager(tmp_path, "telegram-stable-key")
    manager.telegram_token = "test-token"
    manager.telegram_chat_id = "test-chat"
    calls = []

    class Response:
        ok = True
        status_code = 200

        @staticmethod
        def json():
            return {"ok": True, "result": {"message_id": 105}}

    def fake_post(*_args, **_kwargs):
        calls.append(True)
        return Response()

    monkeypatch.setattr("video_processing.telegram_delivery.requests.post", fake_post)
    first = "❌ <b>Video Failed</b>\\nID: <code>telegram-stable-key</code>\\nReason: timeout"
    second = "❌ <b>Video Failed</b>\\nID: <code>telegram-stable-key</code>\\nReason: upstream 500"

    assert manager.send_telegram_msg(first)
    assert not manager.send_telegram_msg(second)
    assert len(calls) == 1


def test_manager_rejects_ok_response_without_message_id(monkeypatch, tmp_path):
    manager = _manager(tmp_path, "telegram-no-message-id")
    manager.telegram_token = "test-token"
    manager.telegram_chat_id = "test-chat"

    class Response:
        ok = True
        status_code = 200

        @staticmethod
        def json():
            return {"ok": True, "result": {}}

    monkeypatch.setattr("video_processing.telegram_delivery.requests.post", lambda *_args, **_kwargs: Response())

    assert not manager.send_telegram_msg("❌ <b>Video Failed</b>\\nID: <code>telegram-no-message-id</code>")


def test_transient_retry_refuses_existing_wechat_submission_evidence(tmp_path):
    manager = _manager(tmp_path, "submitted-video")
    manager.db.update_video_status("submitted-video", "DOWNLOADING")
    evidence = tmp_path / "wechat_evidence" / "submitted-video" / "123"
    evidence.mkdir(parents=True)
    (evidence / "post_list_after_submission.png").write_bytes(b"evidence")

    assert not manager._requeue_transient_pre_submission_failure(
        "submitted-video", "测试标题", "curl exited with code 18"
    )

    row = manager.db.get_video_by_youtube_id("submitted-video")
    assert row["status"] == "DOWNLOADING"
    assert row["retry_count"] == 0


def test_copy_numeric_warning_is_sent_to_telegram_without_blocking(tmp_path):
    manager = _manager(tmp_path, "numeric-video")
    (tmp_path / "numeric-video_copy_quality.json").write_text(
        json.dumps(
            {
                "events": [
                    {
                        "selected": True,
                        "warning_issues": [
                            {
                                "code": "NUMBER_MAGNITUDE_MISMATCH",
                                "source_signal": "$1,060",
                                "translation_signal": "$20B",
                            }
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    messages = []
    manager.send_telegram_msg = messages.append

    manager._notify_copy_numeric_warnings("numeric-video", "测试标题", "numeric-video")

    assert len(messages) == 1
    assert "Copy numeric review" in messages[0]
    assert "$1,060 → $20B" in messages[0]
