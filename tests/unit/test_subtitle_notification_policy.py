"""字幕恢复的状态通知彼此独立，同状态仍沿用任务去重。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-27 | Codex | 覆盖字幕等待、需修复、到期升级和完成通知的独立事件键。 |
"""

import pytest

from video_processing.pipeline_manager import PipelineManager


def _policy(message):
    manager = PipelineManager.__new__(PipelineManager)
    return manager._telegram_notification_policy(message)


@pytest.mark.parametrize("marker,event", [
    ("字幕恢复：等待续跑", "subtitle_waiting"),
    ("字幕恢复：需修复", "subtitle_needs_repair"),
    ("字幕恢复需要修复", "subtitle_needs_repair"),
    ("字幕恢复完成", "subtitle_resolved"),
])
def test_subtitle_state_has_named_priority_and_task_deduplication(marker, event):
    original = f"⚠️ <b>{marker}</b>\nYouTube ID: <code>examplevideo</code>\n代码：connection"
    changed_body = original.replace("connection", "quota")
    event_type, priority, cooldown, key = _policy(original)
    assert event_type == f"pipeline.{event}"
    assert priority == "P1" and cooldown == 86400
    assert "examplevideo" in key
    assert _policy(changed_body) == _policy(original)
    assert _policy(original.replace("examplevideo", "another-video"))[3] != key


def test_waiting_repair_and_resolved_for_same_video_do_not_suppress_each_other():
    messages = [f"<b>{marker}</b>\nYouTube ID: <code>examplevideo</code>"
                for marker in ("字幕恢复：等待续跑", "字幕恢复：需修复", "字幕恢复完成")]
    policies = [_policy(message) for message in messages]
    assert len({policy[0] for policy in policies}) == 3
    assert len({policy[3] for policy in policies}) == 3


def test_generic_failure_notification_keeps_existing_24_hour_deduplication():
    message = "Video failed\nYouTube ID: <code>examplevideo</code>\nReason: network"
    assert _policy(message) == ("pipeline.video_failed", "P1", 86400,
                                "pipeline.video_failed:unknown:examplevideo")
    assert _policy(message.replace("network", "connection")) == _policy(message)
