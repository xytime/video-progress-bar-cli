"""抖音 UI 失败熔断的阶段策略。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.1 | 2026-09-02 | Codex | 熔断账本的损坏条目统一视为未知活动阶段，禁止格式异常导致 fail-open。 |
| 1.0.0 | 2026-09-02 | Codex | 将投稿页与作品管理页失败按作用域隔离，未知阶段保持 fail-closed。 |
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


DOUYIN_UI_STAGE_PUBLISH_PRE_SUBMIT = "publish_pre_submit"
DOUYIN_UI_STAGE_MANAGEMENT_VERIFY = "management_verify"
_DOUYIN_UI_STAGE_MALFORMED = "__malformed_ui_guard_record__"


def active_douyin_ui_failure_stages(
    streaks: Iterable[Mapping[str, Any]],
    *,
    recording_threshold: int,
) -> set[str]:
    """返回达到录屏阈值的活动 UI 阶段。"""
    threshold = max(1, int(recording_threshold or 1))
    active_stages: set[str] = set()
    for row in streaks:
        if not isinstance(row, Mapping):
            return {_DOUYIN_UI_STAGE_MALFORMED}
        stage = row.get("stage")
        active = row.get("active")
        failures = row.get("consecutive_failures")
        if (
            not isinstance(stage, str)
            or not stage.strip()
            or isinstance(active, bool)
            or not isinstance(active, int)
            or active not in {0, 1}
            or isinstance(failures, bool)
            or not isinstance(failures, int)
            or failures < 0
        ):
            return {_DOUYIN_UI_STAGE_MALFORMED}
        if active == 1 and failures >= threshold:
            active_stages.add(stage.strip())
    return active_stages


def douyin_management_verify_is_blocked(active_stages: Iterable[str]) -> bool:
    """任一活动 UI 熔断都停止作品管理页回查，避免重复打开后台。"""
    return bool(set(active_stages))


def douyin_publish_is_blocked(active_stages: Iterable[str]) -> bool:
    """仅管理页核验失败不阻断新投稿；投稿页或未知阶段保持 fail-closed。"""
    return any(
        str(stage).strip() != DOUYIN_UI_STAGE_MANAGEMENT_VERIFY
        for stage in active_stages
    )
