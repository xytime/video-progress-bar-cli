"""英语世界 Telegram 回执的失败语义测试。

这些测试只替换本地投递适配器；不会调用 Telegram、不会创建投稿包，也不会触发视频号动作。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-24 | Codex | 固化英语世界未交付通知必须取得 API 回执，否则保留失败退出码。 |
| 1.1.0 | 2026-08-24 | Codex | 固化审核包只能接收实测时长严格大于 30 秒且不超过 300 秒的成片。 |
"""

from __future__ import annotations

import sys

import pytest

from scripts import notify_english_world_review as notifier
from video_processing.telegram_delivery import TelegramDeliveryResult


def test_failure_notification_requires_api_receipt(monkeypatch):
    """网络不确定时不能把英语世界失败通知伪装为已报告。"""
    monkeypatch.setattr(
        notifier,
        "send_text",
        lambda **_kwargs: TelegramDeliveryResult(state="UNKNOWN", error_kind="ConnectTimeout"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["notify_english_world_review.py", "--title", "天气科普", "--failure", "阅读屏微笔记不足 8 个"],
    )

    with pytest.raises(RuntimeError, match="未获 API 接受"):
        notifier.main()


def test_failure_notification_records_the_exact_operational_reason(monkeypatch):
    """已获受理时退出成功，且把实际制作失败原因传给回执层。"""
    sent: dict[str, object] = {}

    def fake_send_text(**kwargs):
        sent.update(kwargs)
        return TelegramDeliveryResult(state="ACCEPTED", message_id="101")

    monkeypatch.setattr(notifier, "send_text", fake_send_text)
    monkeypatch.setattr(
        sys,
        "argv",
        ["notify_english_world_review.py", "--title", "天气科普", "--failure", "阅读屏微笔记不足 8 个"],
    )

    assert notifier.main() == 0
    assert sent["event_type"] == "english_world.not_delivered"
    assert sent["priority"] == "P1"
    assert "阅读屏微笔记不足 8 个" in str(sent["text"])


@pytest.mark.parametrize("actual_duration", [30.0, 300.1])
def test_review_package_rejects_mp4_outside_duration_range(monkeypatch, tmp_path, actual_duration):
    """审核包是独立防线，不能让绕过渲染命令的短片进入 Telegram 审批。"""
    mp4 = tmp_path / "short.mp4"
    mp4.write_bytes(b"fixture")
    monkeypatch.setattr(notifier, "get_video_duration_ffprobe", lambda _path: actual_duration)

    with pytest.raises(ValueError, match="严格大于 30 秒"):
        notifier._validate_review_duration(
            mp4=mp4,
            manifest_payload={"duration": actual_duration},
        )


def test_review_package_requires_manifest_to_match_measured_duration(monkeypatch, tmp_path):
    mp4 = tmp_path / "study.mp4"
    mp4.write_bytes(b"fixture")
    monkeypatch.setattr(notifier, "get_video_duration_ffprobe", lambda _path: 42.0)

    with pytest.raises(ValueError, match="时长与 MP4 不一致"):
        notifier._validate_review_duration(mp4=mp4, manifest_payload={"duration": 41.0})
