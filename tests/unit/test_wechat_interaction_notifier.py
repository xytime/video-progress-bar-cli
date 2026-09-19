"""互动通知保持状态准确，不误把 JSON 回执上传为照片。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-19 | Codex | 通知证据类型与 HTML 转义回归 |
"""

from types import SimpleNamespace
from unittest.mock import patch

from video_processing.interaction.notifier import InteractionNotifier


def test_uncertain_json_receipt_uses_text(tmp_path):
    receipt = tmp_path / "receipt.json"
    receipt.write_text("{}", encoding="utf-8")
    notifier = InteractionNotifier(db=object())
    with patch("video_processing.interaction.notifier.send_photo") as photo, patch(
        "video_processing.interaction.notifier.send_text",
        return_value=SimpleNamespace(state="ACCEPTED"),
    ) as text:
        assert notifier.notify_interaction_result(
            video_title="<title>", platform_post_id="post-1", status="UNCERTAIN",
            draft=None, evidence_path=str(receipt), error_message="<unknown>",
        )
        photo.assert_not_called()
        message = text.call_args.kwargs["text"]
        assert "禁止重发" in message
        assert "&lt;title&gt;" in message
        assert "&lt;unknown&gt;" in message


def test_png_evidence_uses_photo(tmp_path):
    screenshot = tmp_path / "final.png"
    screenshot.write_bytes(b"fixture")
    notifier = InteractionNotifier(db=object())
    with patch("video_processing.interaction.notifier.send_photo",
               return_value=SimpleNamespace(state="ACCEPTED")) as photo:
        assert notifier.notify_interaction_result(
            video_title="title", platform_post_id="post-1", status="COMMENTED",
            draft=None, evidence_path=str(screenshot),
        )
        assert photo.call_args.kwargs["path"] == screenshot
