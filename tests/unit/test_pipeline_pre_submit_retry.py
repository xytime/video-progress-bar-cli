"""上传前瞬态失败重试与文案金额告警测试。

# Modification History
| Version | Date | Author | Description |
| ------- | ---- | ------ | ----------- |
| 1.0.0 | 2026-08-05 | Codex | 覆盖可安全自动重试边界、提交证据保护和 Telegram 数字告警 |
| 1.1.0 | 2026-08-05 | Codex | 覆盖 curl SSL 超时重试及 Telegram 管理员回退会话 |
"""

import json

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


def test_manager_uses_active_telegram_chat_id_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "telegram_chat_id", None)
    monkeypatch.setattr(settings, "telegram_admin_ids", "fallback-chat,another-admin")

    manager = _manager(tmp_path, "telegram-fallback-video")

    assert manager.telegram_chat_id == "fallback-chat"


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
