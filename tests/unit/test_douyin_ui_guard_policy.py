"""抖音 UI 阶段熔断策略测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-02 | Codex | 覆盖管理页与投稿页熔断的阶段隔离及未知阶段 fail-closed。 |
"""

from video_processing.core.douyin_ui_guard_policy import (
    active_douyin_ui_failure_stages,
    douyin_management_verify_is_blocked,
    douyin_publish_is_blocked,
)


def test_management_verify_failure_blocks_only_management_verification():
    stages = active_douyin_ui_failure_stages(
        [{"stage": "management_verify", "active": 1, "consecutive_failures": 2}],
        recording_threshold=2,
    )

    assert stages == {"management_verify"}
    assert douyin_management_verify_is_blocked(stages)
    assert not douyin_publish_is_blocked(stages)


def test_publish_pre_submit_and_unknown_failures_remain_fail_closed():
    publish_stages = active_douyin_ui_failure_stages(
        [{"stage": "publish_pre_submit", "active": 1, "consecutive_failures": 2}],
        recording_threshold=2,
    )
    unknown_stages = active_douyin_ui_failure_stages(
        [{"stage": "unrecognized_stage", "active": 1, "consecutive_failures": 2}],
        recording_threshold=2,
    )

    assert douyin_management_verify_is_blocked(publish_stages)
    assert douyin_publish_is_blocked(publish_stages)
    assert douyin_management_verify_is_blocked(unknown_stages)
    assert douyin_publish_is_blocked(unknown_stages)


def test_inactive_or_below_threshold_stage_does_not_block_any_action():
    stages = active_douyin_ui_failure_stages(
        [
            {"stage": "management_verify", "active": 0, "consecutive_failures": 9},
            {"stage": "publish_pre_submit", "active": 1, "consecutive_failures": 1},
        ],
        recording_threshold=2,
    )

    assert stages == set()
    assert not douyin_management_verify_is_blocked(stages)
    assert not douyin_publish_is_blocked(stages)


def test_malformed_ui_guard_row_is_treated_as_unknown_fail_closed_stage():
    """账本条目损坏不能被静默跳过并变成“无熔断”。"""
    stages = active_douyin_ui_failure_stages(
        [{"stage": "management_verify", "active": 1, "consecutive_failures": 2}, object()],
        recording_threshold=2,
    )

    assert douyin_management_verify_is_blocked(stages)
    assert douyin_publish_is_blocked(stages)
