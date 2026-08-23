"""Highlight Job 的文件边界与候选计划服务。

该服务只读取源字幕、写入 Highlight 专属工作目录并调用 DAL。它不导入
PipelineManager，不调用下载、渲染或发布链路，因此不会改变既有视频处理流程。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.1 | 2026-08-20 | Codex | 对显式指定源片提供候选分析前的时间轴字幕可用性检查 |
| 1.0.0 | 2026-08-20 | Codex | 新增独立 Highlight Job 的候选分析和计划落盘服务 |
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from video_processing.db.database import PipelineDB

from .miner import mine_candidates, parse_webvtt_cues

logger = logging.getLogger(__name__)


class HighlightJobService:
    """只读源片、独立落盘的 Highlight Job 服务。"""

    def __init__(self, db: PipelineDB, project_root: Path | None = None):
        self.db = db
        self.project_root = Path(project_root) if project_root else Path(__file__).resolve().parents[3]
        self.output_dir = self.project_root / "output"

    def list_sources(self, *, limit: int = 10, offset: int = 0) -> list[dict[str, Any]]:
        """附加本地字幕/源片可用性，仅用于显式选择界面。"""
        rows = self.db.list_highlight_source_videos(limit=limit, offset=offset)
        for row in rows:
            yid = str(row["youtube_id"])
            subtitle_path = self._find_source_subtitle(yid)
            video_path = self._find_source_video(yid)
            row["source_subtitle_available"] = subtitle_path is not None
            row["source_video_available"] = video_path is not None
            row["can_analyze"] = subtitle_path is not None
            row["can_render_later"] = subtitle_path is not None and video_path is not None
        return rows

    def has_source_subtitle(self, youtube_id: str) -> bool:
        """判断源片是否已有可供候选分析的带时间轴字幕。"""
        return self._find_source_subtitle(youtube_id) is not None

    def analyze(self, job_id: str) -> dict[str, Any] | None:
        """领取并分析一个 Highlight Job；同一 Job 只会被一个调用者执行。"""
        job = self.db.claim_highlight_job_for_analysis(job_id)
        if job is None:
            return None
        try:
            yid = str(job["youtube_id"])
            subtitle_path = self._find_source_subtitle(yid)
            if subtitle_path is None:
                raise RuntimeError("未找到带时间轴的源字幕，无法生成 Highlight 候选")
            raw_subtitle = subtitle_path.read_text(encoding="utf-8-sig", errors="replace")
            cues = parse_webvtt_cues(raw_subtitle)
            if len(cues) < 2:
                raise RuntimeError("源字幕缺少可用时间轴，无法生成 Highlight 候选")
            clips = mine_candidates(
                cues,
                max_clips=int(job["max_clips"]),
                min_duration_sec=float(job["min_duration_sec"]),
                max_duration_sec=float(job["max_duration_sec"]),
            )
            if not clips:
                raise RuntimeError("源字幕未形成满足时长与语义完整度的候选片段")
            workspace = self.output_dir / "highlights" / yid / str(job["id"])
            workspace.mkdir(parents=True, exist_ok=True)
            subtitle_sha256 = _sha256(subtitle_path)
            plan_path = workspace / "highlight_plan.json"
            payload = {
                "schema_version": "1.0",
                "job_id": job["id"],
                "source": {
                    "youtube_id": yid,
                    "subtitle_path": str(subtitle_path),
                    "subtitle_sha256": subtitle_sha256,
                    "scoring_version": "heuristic-v0",
                },
                "config": {
                    "max_clips": int(job["max_clips"]),
                    "min_duration_sec": float(job["min_duration_sec"]),
                    "max_duration_sec": float(job["max_duration_sec"]),
                },
                "clips": clips,
            }
            _write_json_atomically(plan_path, payload)
            self.db.complete_highlight_job_analysis(
                str(job["id"]),
                source_subtitle_sha256=subtitle_sha256,
                workspace_path=str(workspace),
                plan_path=str(plan_path),
                clips=clips,
            )
            logger.info("[Highlight] candidates ready: job=%s clips=%s", job["id"], len(clips))
            return self.db.get_highlight_job(str(job["id"]))
        except Exception as exc:
            logger.exception("[Highlight] candidate analysis failed: job=%s", job_id)
            self.db.fail_highlight_job(job_id, str(exc))
            return self.db.get_highlight_job(job_id)

    def _find_source_subtitle(self, youtube_id: str) -> Path | None:
        prefix = f"{youtube_id}_source_subtitle"
        candidates = sorted(
            path for path in self.output_dir.glob(f"{prefix}*.vtt")
            if path.name == f"{prefix}.vtt" or path.name.startswith(f"{prefix}.")
        )
        for path in candidates:
            try:
                if path.is_file() and path.stat().st_size > 100:
                    return path
            except OSError:
                continue
        return None

    def _find_source_video(self, youtube_id: str) -> Path | None:
        from video_processing.utils.file_utils import find_downloaded_video

        path = find_downloaded_video(
            self.output_dir,
            youtube_id,
            archive_dir=self.output_dir / "original_video",
        )
        return Path(path) if path else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_atomically(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)
