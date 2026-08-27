"""英语世界 Telegram 回执的失败语义测试。

这些测试只替换本地投递适配器；不会调用 Telegram、不会创建投稿包，也不会触发视频号动作。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-24 | Codex | 固化英语世界未交付通知必须取得 API 回执，否则保留失败退出码。 |
| 1.1.0 | 2026-08-24 | Codex | 固化审核包只能接收实测时长严格大于 30 秒且不超过 300 秒的成片。 |
| 1.2.0 | 2026-08-26 | Codex | 覆盖自动策略只提交本次新建质检包、旧审核项绝不被自动重传。 |
| 1.3.0 | 2026-08-26 | Codex | 覆盖标准 enriched 时间线兼容和机器可读 Telegram 交付回执。 |
| 1.4.0 | 2026-08-27 | Codex | 覆盖学习卡生产器的点分隔 enriched 时间线命名。 |
"""

from __future__ import annotations

import sys
import json

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


def test_failure_notification_writes_machine_delivery_receipt(monkeypatch, tmp_path):
    receipt_path = tmp_path / "delivery.json"
    monkeypatch.setattr(
        notifier,
        "send_text",
        lambda **_kwargs: TelegramDeliveryResult(state="ACCEPTED", message_id="102"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "notify_english_world_review.py", "--title", "天气科普", "--failure", "无合格素材",
            "--delivery-receipt", str(receipt_path),
        ],
    )

    assert notifier.main() == 0
    assert json.loads(receipt_path.read_text(encoding="utf-8")) == {
        "kind": "failure_notice", "status": "ACCEPTED", "telegram_message_id": "102",
    }


@pytest.mark.parametrize("timeline_name", ["timeline_enriched.json", "timeline.enriched.json"])
def test_load_timeline_accepts_renderer_standard_enriched_name(tmp_path, timeline_name):
    manifest_path = tmp_path / "study_card.manifest.json"
    (tmp_path / timeline_name).write_text('{"headline_zh":"机器人"}', encoding="utf-8")

    assert notifier._load_timeline(manifest_path) == {"headline_zh": "机器人"}


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


def test_auto_publish_submits_only_a_new_review_item(monkeypatch):
    """自动策略的授权范围仅限当前调用刚建立的、已完成质检的成片。"""
    calls: list[object] = []

    class FakeDB:
        def approve_english_world_submission(self, review_id, *, authorization):
            calls.append(("approve", review_id, authorization))

        def get_english_world_review_item(self, review_id):
            calls.append(("read", review_id))
            return {"id": review_id, "state": "UNDER_REVIEW"}

    monkeypatch.setattr(notifier.settings, "enable_english_world_auto_publish", True)
    monkeypatch.setattr(notifier.settings, "wechat_publishing_paused", False)
    monkeypatch.setattr(notifier, "PipelineDB", FakeDB)
    monkeypatch.setattr(
        notifier.subprocess, "run", lambda *args, **kwargs: type("Result", (), {"returncode": 0})(),
    )

    result = notifier._auto_submit_new_review_item({"id": "new-review", "_created_now": True})

    assert result == "submission_worker_exit=0; state=UNDER_REVIEW"
    assert calls == [("approve", "new-review", "AUTO_POLICY"), ("read", "new-review")]


def test_auto_publish_never_retries_an_existing_review_item(monkeypatch):
    """开启新策略不能把历史 READY/UNCERTAIN 项重新提交。"""
    monkeypatch.setattr(notifier.settings, "enable_english_world_auto_publish", True)
    monkeypatch.setattr(notifier, "PipelineDB", lambda: pytest.fail("历史审核项不得读取或批准"))
    monkeypatch.setattr(notifier.subprocess, "run", lambda *args, **kwargs: pytest.fail("历史审核项不得启动投稿器"))

    assert notifier._auto_submit_new_review_item({"id": "old-review", "_created_now": False}) == "existing_item_not_retried"
