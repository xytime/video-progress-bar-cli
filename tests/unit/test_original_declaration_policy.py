"""原创声明源发布时间策略测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-23 | Codex | 覆盖 24 小时边界、时区归一与缺失时间的保守策略 |
"""

from datetime import datetime, timezone

import pytest

from video_processing.core.original_declaration_policy import decide_original_declaration


NOW = datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("source_published_at", "declare_original", "reason"),
    [
        ("2026-08-22T12:00:01Z", True, "source_within_24_hours"),
        ("2026-08-22T12:00:00Z", True, "source_within_24_hours"),
        ("2026-08-22T11:59:59Z", False, "source_older_than_24_hours"),
        (None, False, "source_publish_time_missing"),
        ("not-a-time", False, "source_publish_time_invalid"),
        ("2026-08-23T12:00:01Z", False, "source_publish_time_in_future"),
    ],
)
def test_original_declaration_age_boundaries(source_published_at, declare_original, reason):
    decision = decide_original_declaration(source_published_at, now=NOW)

    assert decision.declare_original is declare_original
    assert decision.reason == reason


def test_original_declaration_normalizes_offset_to_utc():
    decision = decide_original_declaration("2026-08-22T20:00:00+08:00", now=NOW)

    assert decision.declare_original is True
    assert decision.source_published_at == "2026-08-22T12:00:00Z"
    assert decision.evaluated_at == "2026-08-23T12:00:00Z"
