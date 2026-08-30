"""只读预检可独立进入抖音 NEW 的当前窗口候选。

本脚本不创建抖音账本、不领取任务、不打开浏览器，也不运行会写入违规台账的内容审查。
它只验证调度候选身份、成片可解析性、非空标题/文案、专用封面来源清单和字幕正文证据，
并把内容审查、登录、页面校准和真实提交明确保留为后续运行时闸门。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-30 | Codex | 新增抖音独立 NEW 候选只读素材预检与前后无建账证明 |
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from config.settings import settings  # noqa: E402
from video_processing.core.cover_policy import validate_dedicated_cover_file  # noqa: E402
from video_processing.db.database import PipelineDB  # noqa: E402
from video_processing.utils.file_utils import read_subtitle_text  # noqa: E402
from video_processing.utils.video_metadata import get_video_duration_ffprobe  # noqa: E402


VideoProbe = Callable[[Path], tuple[bool, float | None, str | None]]


def _prefix(youtube_id: str, slice_index: int) -> str:
    return f"{youtube_id}_s{slice_index}" if slice_index > 0 else youtube_id


def _read_nonempty(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _probe_video(path: Path) -> tuple[bool, float | None, str | None]:
    if not path.is_file():
        return False, None, "竖版成片不存在"
    try:
        duration = float(get_video_duration_ffprobe(path))
    except Exception as exc:
        return False, None, f"ffprobe 无法解析成片：{exc}"
    if duration <= 0:
        return False, duration, "成片时长必须大于 0"
    return True, duration, None


def _resolve_cover(output_dir: Path, youtube_id: str, slice_index: int) -> Path | None:
    prefix = _prefix(youtube_id, slice_index)
    for cover in (output_dir / f"{prefix}_cover.jpg", output_dir / f"{youtube_id}_cover.jpg"):
        provenance = cover.with_name(f"{cover.stem}_provenance.json")
        if validate_dedicated_cover_file(cover, provenance):
            return cover
    return None


def _subtitle_source(output_dir: Path, youtube_id: str, slice_index: int) -> tuple[str, str]:
    sources = (
        ("output", output_dir),
        ("original_video", output_dir / "original_video"),
        ("subtitle_evidence", output_dir / "subtitle_evidence" / _prefix(youtube_id, slice_index) / "ass"),
    )
    for label, directory in sources:
        text = read_subtitle_text(directory, youtube_id, slice_index=slice_index)
        if text:
            return label, text
    return "missing", ""


def inspect_independent_candidates(
    db: PipelineDB,
    *,
    output_dir: Path,
    lookback_hours: int,
    limit: int = 50,
    require_subtitle_evidence: bool = True,
    video_probe: VideoProbe = _probe_video,
) -> dict[str, Any]:
    """返回独立候选的本地素材证据；前后检查确保本函数没有建立抖音账本。"""
    safe_limit = max(1, min(int(limit), 50))
    candidates = db.get_unqueued_douyin_new_videos(
        lookback_hours=max(1, int(lookback_hours)),
        limit=safe_limit,
        require_wechat_public_confirmation=False,
    )
    identities = [
        (str(row["youtube_id"]), int(row.get("slice_index") or 0))
        for row in candidates
    ]
    ledgers_before = {
        identity: db.get_douyin_publication(identity[0], identity[1])
        for identity in identities
    }
    items: list[dict[str, Any]] = []
    for queue_order, video in enumerate(candidates, start=1):
        youtube_id = str(video["youtube_id"])
        slice_index = int(video.get("slice_index") or 0)
        prefix = _prefix(youtube_id, slice_index)
        vertical = output_dir / f"{prefix}_vertical.mp4"
        copy_file = output_dir / f"{prefix}_copy.txt"
        title_file = output_dir / f"{prefix}_title.txt"
        video_ok, duration_seconds, video_error = video_probe(vertical)
        copy_text = _read_nonempty(copy_file)
        title_text = _read_nonempty(title_file)
        cover = _resolve_cover(output_dir, youtube_id, slice_index)
        subtitle_source, subtitle_text = _subtitle_source(output_dir, youtube_id, slice_index)
        failures = []
        if not video_ok:
            failures.append(video_error or "竖版成片不可用")
        if not copy_text:
            failures.append("抖音文案缺失或为空")
        if not title_text:
            failures.append("抖音标题缺失或为空")
        if cover is None:
            failures.append("专用封面或来源清单不合规")
        if require_subtitle_evidence and not subtitle_text:
            failures.append("上传前内容审查缺少可读字幕正文")
        wechat = db.get_wechat_publication(youtube_id, slice_index=slice_index)
        items.append({
            "queue_order": queue_order,
            "youtube_id": youtube_id,
            "slice_index": slice_index,
            "local_state": str(video.get("status") or ""),
            "wechat_state": str((wechat or {}).get("state") or ""),
            "video_path": str(vertical),
            "video_bytes": vertical.stat().st_size if vertical.is_file() else 0,
            "duration_seconds": round(duration_seconds, 3) if duration_seconds is not None else None,
            "copy_chars": len(copy_text),
            "title_chars": len(title_text),
            "cover_path": str(cover) if cover else None,
            "subtitle_source": subtitle_source,
            "subtitle_chars": len(subtitle_text),
            "local_preflight_ready": not failures,
            "failures": failures,
            "remaining_runtime_gates": [
                "content_safety",
                "public_publish_window",
                "browser_login",
                "ui_calibration",
                "platform_submission_confirmation",
            ],
        })
    ledgers_after = {
        identity: db.get_douyin_publication(identity[0], identity[1])
        for identity in identities
    }
    ledger_unchanged = all(
        ledgers_before[identity] is None and ledgers_after[identity] is None
        for identity in identities
    )
    ready_count = sum(1 for item in items if item["local_preflight_ready"])
    return {
        "read_only": True,
        "lookback_hours": max(1, int(lookback_hours)),
        "candidate_count": len(items),
        "local_preflight_ready_count": ready_count,
        "ledger_unchanged": ledger_unchanged,
        "browser_opened": False,
        "publication_created": False,
        "items": items,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="只读预检抖音独立 NEW 当前窗口候选")
    parser.add_argument("--lookback-hours", type=int, default=settings.douyin_new_sync_lookback_hours)
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()
    result = inspect_independent_candidates(
        PipelineDB(),
        output_dir=PROJECT_ROOT / "output",
        lookback_hours=args.lookback_hours,
        limit=args.limit,
        require_subtitle_evidence=settings.enable_subtitle_censorship,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
