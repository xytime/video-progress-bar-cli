# -*- coding: utf-8 -*-
"""学习卡时间线与源字幕边界的静态校验。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0 | 2026-09-01 | Codex | 校验相对时间轴的末词不能越过源字幕中的下一句。 |
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


def validate_source_caption_boundary(
    payload: Mapping[str, Any], *, timeline_path: Path | None = None,
) -> None:
    """拒绝末词结束时间覆盖源字幕下一词/下一句的时间线。

    学习卡 ``words`` 使用相对于选段起点的秒数，而 json3 字幕使用源视频绝对秒数。
    当两者混用时，渲染器会合法地产生一个包含下一句的音频尾段；这里在渲染和交付
    两个入口复用同一条边界检查。
    """
    words = payload.get("words")
    provenance = payload.get("source_provenance")
    if not isinstance(words, list) or not words or not isinstance(provenance, Mapping):
        return
    artifact_ref = str(provenance.get("caption_artifact") or "").strip()
    if not artifact_ref:
        return
    caption_path = Path(artifact_ref).expanduser()
    if not caption_path.is_absolute():
        if timeline_path is None:
            return
        caption_path = timeline_path.expanduser().resolve().parent / caption_path
    if not caption_path.is_file():
        raise ValueError(f"源字幕边界校验找不到 caption_artifact: {caption_path}")
    try:
        source_start = float(provenance.get("source_start_seconds", 0.0))
        final_start = source_start + float(words[-1]["start"])
        final_end = source_start + float(words[-1]["end"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("源字幕边界校验需要可解析的 source_start_seconds 和末词时间") from exc

    try:
        caption_payload = json.loads(caption_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"源字幕边界校验无法读取 caption_artifact: {caption_path}") from exc
    next_caption_start = _next_caption_start(caption_payload, final_start)
    if next_caption_start is not None and final_end > next_caption_start + 0.05:
        raise ValueError(
            "时间线末词越过源字幕边界："
            f"末词结束={final_end:.3f}s，下一字幕开始={next_caption_start:.3f}s；"
            "请将绝对字幕时间转换为相对选段时间"
        )


def _next_caption_start(payload: Any, after: float) -> float | None:
    starts: list[float] = []
    for event in payload.get("events", []) if isinstance(payload, Mapping) else []:
        if not isinstance(event, Mapping):
            continue
        try:
            event_start = float(event.get("tStartMs", 0.0)) / 1000.0
        except (TypeError, ValueError):
            continue
        for segment in event.get("segs") or []:
            if not isinstance(segment, Mapping) or not str(segment.get("utf8", "")).strip():
                continue
            try:
                starts.append(event_start + float(segment.get("tOffsetMs", 0.0)) / 1000.0)
            except (TypeError, ValueError):
                continue
    return min((start for start in starts if start > after + 0.001), default=None)
