"""长片翻译批次进度：按源 cue 指纹落盘，续跑只计未译段落预算。

裸跑（无进度）时 require_single_video_budget 行为不变：614 段仍在审计前
触发 translation_budget_preflight。有进度或显式开启分窗续翻时，每次只
翻译当前窗口内能装下的段落并落盘，耗尽窗口后以可恢复等待结束。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-06 | Grok Bot | 失败队列长片 translation_budget_preflight 根因修复。 |
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

LOG = logging.getLogger(__name__)
PROGRESS_VERSION = 1


def cue_fingerprint(segments: Sequence[Dict[str, Any]]) -> str:
    """源段落指纹：start/end/text，不含译文。"""
    payload = [
        {
            "start": float(seg.get("start", 0) or 0),
            "end": float(seg.get("end", 0) or 0),
            "text": str(seg.get("text", "")),
        }
        for seg in segments
    ]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()


def progress_path(output_dir: Path, youtube_id: str, source_fp: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in (youtube_id or "unknown"))
    return Path(output_dir) / "translation_batch_progress" / safe / f"{source_fp[:24]}.json"


def _atomic_write(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".tbp_", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def load_progress(path: Path, source_fp: str, expected_count: int) -> Optional[Dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if (
        payload.get("version") != PROGRESS_VERSION
        or payload.get("source_fp") != source_fp
        or int(payload.get("segment_count") or -1) != expected_count
        or not isinstance(payload.get("translations"), list)
        or len(payload["translations"]) != expected_count
    ):
        return None
    return payload


def save_progress(
    path: Path,
    *,
    youtube_id: str,
    source_fp: str,
    segments: Sequence[Dict[str, Any]],
    translations: Sequence[Optional[str]],
    done_indices: Sequence[int],
) -> None:
    if len(translations) != len(segments):
        raise ValueError("translations length mismatch")
    payload = {
        "version": PROGRESS_VERSION,
        "youtube_id": youtube_id,
        "source_fp": source_fp,
        "segment_count": len(segments),
        "done_indices": sorted(set(int(i) for i in done_indices)),
        "done_count": len(set(int(i) for i in done_indices)),
        "translations": list(translations),
    }
    _atomic_write(path, payload)
    LOG.info(
        "[TranslationBatchProgress] saved %s done=%s/%s",
        path,
        payload["done_count"],
        payload["segment_count"],
    )


def max_segments_for_budget(config) -> int:
    """当前自适应预算下，单次窗口最多可翻译的段数。"""
    from .subtitle_provider_window import adaptive_translation_budget_seconds

    batch = max(30, min(int(getattr(config, "codex_subtitle_batch_size", 40)), 50))
    request = float(getattr(config, "codex_text_request_timeout_seconds", 120))
    quality = float(getattr(config, "subtitle_translation_quality_reserve_seconds", 120))
    budget = adaptive_translation_budget_seconds(10**9, config)  # hit absolute cap
    available = max(0.0, float(budget) - quality)
    if request <= 0:
        return batch
    batches = max(1, int(math.floor(available / request)))
    return max(batch, batches * batch)


def apply_progress_to_segments(
    segments: List[Dict[str, Any]], translations: Sequence[Optional[str]]
) -> List[int]:
    """把已译 zh_text 写回段落，返回仍缺译文的下标。"""
    remaining = []
    for index, segment in enumerate(segments):
        text = translations[index] if index < len(translations) else None
        if isinstance(text, str) and text.strip():
            segment["zh_text"] = text
        else:
            remaining.append(index)
    return remaining


def merge_window_translations(
    translations: List[Optional[str]],
    window_indices: Sequence[int],
    window_texts: Sequence[str],
) -> List[int]:
    done = []
    for offset, index in enumerate(window_indices):
        value = window_texts[offset] if offset < len(window_texts) else None
        if isinstance(value, str) and value.strip():
            translations[index] = value
            done.append(index)
    return done


def select_work_indices(remaining_indices, max_window, windowed):
    """返回 (work_indices, partial_run)。"""
    remaining = list(remaining_indices)
    if windowed and len(remaining) > max_window:
        return remaining[:max_window], True
    return remaining, False
