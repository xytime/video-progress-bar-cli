"""视频号原创声明的源发布时间判定。

原创声明只在源视频发布时间可验证且未超过 24 小时时自动勾选；时间缺失、
非法或未来时采取保守策略，不作原创声明。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-23 | Codex | 新增基于精确源发布时间的原创声明判定，避免日期粒度误判 |
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


_ORIGINAL_DECLARATION_MAX_AGE = timedelta(hours=24)


@dataclass(frozen=True)
class OriginalDeclarationDecision:
    """一次上传前原创声明判断的可审计结果。"""

    declare_original: bool
    reason: str
    source_published_at: str | None
    evaluated_at: str
    age_seconds: int | None


def decide_original_declaration(
    source_published_at: str | None,
    *,
    now: datetime | None = None,
) -> OriginalDeclarationDecision:
    """按 UTC 精确时间决定是否自动声明原创。"""
    evaluated_at = _as_utc(now or datetime.now(timezone.utc))
    canonical_now = _format_utc(evaluated_at)
    if not source_published_at or not source_published_at.strip():
        return OriginalDeclarationDecision(False, "source_publish_time_missing", None, canonical_now, None)

    try:
        published_at = _parse_utc(source_published_at)
    except ValueError:
        return OriginalDeclarationDecision(
            False, "source_publish_time_invalid", source_published_at, canonical_now, None,
        )

    age = evaluated_at - published_at
    age_seconds = int(age.total_seconds())
    canonical_source = _format_utc(published_at)
    if age.total_seconds() < 0:
        return OriginalDeclarationDecision(
            False, "source_publish_time_in_future", canonical_source, canonical_now, age_seconds,
        )
    if age > _ORIGINAL_DECLARATION_MAX_AGE:
        return OriginalDeclarationDecision(
            False, "source_older_than_24_hours", canonical_source, canonical_now, age_seconds,
        )
    return OriginalDeclarationDecision(
        True, "source_within_24_hours", canonical_source, canonical_now, age_seconds,
    )


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("source publication time must include a timezone")
    return _as_utc(parsed)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("evaluation time must include a timezone")
    return value.astimezone(timezone.utc)


def _format_utc(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")
