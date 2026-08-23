"""Highlight Clip 的独立资产渲染服务。

此模块只消费已人工选定的 Highlight Clip。它的输出、失败状态和发布主体均属于
Clip，不修改 ``processed_videos``，也不会调用视频号上传器；发布仍必须经过单独的
人工审核和平台回执流程。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-20 | Codex | 新增独立 Clip 渲染、文案、专用封面和可审计资产清单服务 |
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

import imageio_ffmpeg

from video_processing.db.database import PipelineDB

logger = logging.getLogger(__name__)


class HighlightRenderService:
    """为已经显式选定的 Clip 创建独立、可审计的发布前资产。"""

    def __init__(self, db: PipelineDB, project_root: Path | None = None):
        self.db = db
        self.project_root = Path(project_root) if project_root else Path(__file__).resolve().parents[3]
        self.output_dir = self.project_root / "output"
        self.python = self.project_root / ".venv" / "bin" / "python"

    def render(self, clip_id: str) -> dict[str, Any] | None:
        """领取并渲染一个选定 Clip；重复调用不会重复创建资产。"""
        clip = self.db.claim_highlight_clip_for_rendering(clip_id)
        if clip is None:
            return self.db.get_highlight_clip_assets(clip_id)
        try:
            result = self._render_claimed_clip(clip)
            logger.info("[Highlight] assets ready: clip=%s", clip_id)
            return result
        except Exception as exc:
            logger.exception("[Highlight] render failed: clip=%s", clip_id)
            self.db.fail_highlight_clip_rendering(clip_id, str(exc))
            return self.db.get_highlight_clip_assets(clip_id)

    def _render_claimed_clip(self, clip: dict[str, Any]) -> dict[str, Any]:
        clip_id = str(clip["id"])
        source_youtube_id = str(clip["source_youtube_id"])
        workspace = Path(str(clip["workspace_path"])) / f"clip-{int(clip['ordinal']):02d}"
        workspace.mkdir(parents=True, exist_ok=True)
        evidence_dir = workspace / "evidence"
        evidence_dir.mkdir(parents=True, exist_ok=True)

        source_path, source_kind = self._find_render_source(source_youtube_id)
        if source_path is None:
            raise RuntimeError("未找到可用源视频；不会下载或改动原视频任务")
        source_sha256 = _sha256(source_path)

        rendered_video_path = workspace / "highlight.mp4"
        self._render_video(
            source_path,
            rendered_video_path,
            start_ms=int(clip["snapped_start_ms"] or clip["raw_start_ms"]),
            end_ms=int(clip["snapped_end_ms"] or clip["raw_end_ms"]),
        )
        media = _validate_vertical_mp4(rendered_video_path)

        excerpt_path = workspace / "source_excerpt.en.txt"
        excerpt_path.write_text(str(clip.get("source_text") or "").strip() + "\n", encoding="utf-8")
        title = str(clip.get("source_title") or clip.get("source_zh_title") or source_youtube_id).strip()
        self._generate_copy(clip_id, title, excerpt_path, workspace)
        title_path = workspace / f"{clip_id}_title.txt"
        copy_path = workspace / f"{clip_id}_copy.txt"
        category_path = workspace / f"{clip_id}_category.txt"
        if not title_path.is_file() or not copy_path.is_file():
            raise RuntimeError("文案生成未产出标题或正文，拒绝生成待发布资产")
        short_title = title_path.read_text(encoding="utf-8").strip()
        if not short_title or len(short_title) < 6 or len(short_title) > 16:
            raise RuntimeError("Highlight 短标题不符合视频号 6–16 字要求")
        if not copy_path.read_text(encoding="utf-8").strip():
            raise RuntimeError("Highlight 文案为空")

        cover_path = workspace / "cover.jpg"
        cover_provenance_path = workspace / "cover_provenance.json"
        self._generate_cover(short_title, cover_path, cover_provenance_path)
        _validate_dedicated_cover(cover_path, cover_provenance_path)

        manifest_path = workspace / "asset_manifest.json"
        manifest = {
            "schema_version": "1.0",
            "clip_id": clip_id,
            "publication_subject_id": f"highlight_clip:{clip_id}",
            "source": {
                "youtube_id": source_youtube_id,
                "path": str(source_path),
                "sha256": source_sha256,
                "kind": source_kind,
                "raw_start_ms": int(clip["raw_start_ms"]),
                "raw_end_ms": int(clip["raw_end_ms"]),
                "snapped_start_ms": clip.get("snapped_start_ms"),
                "snapped_end_ms": clip.get("snapped_end_ms"),
            },
            "assets": {
                "video": _file_manifest(rendered_video_path, media),
                "title": _file_manifest(title_path),
                "copy": _file_manifest(copy_path),
                "category": _file_manifest(category_path) if category_path.is_file() else None,
                "cover": _file_manifest(cover_path),
                "cover_provenance": _file_manifest(cover_provenance_path),
            },
            "publication": {
                "review_required": True,
                "declare_original": False,
                "platform_state": "NOT_SUBMITTED",
            },
        }
        _write_json_atomically(manifest_path, manifest)
        return self.db.complete_highlight_clip_rendering(
            clip_id,
            source_video_path=str(source_path),
            source_video_sha256=source_sha256,
            source_video_kind=source_kind,
            rendered_video_path=str(rendered_video_path),
            title_path=str(title_path),
            copy_path=str(copy_path),
            category_path=str(category_path) if category_path.is_file() else None,
            cover_path=str(cover_path),
            cover_provenance_path=str(cover_provenance_path),
            artifact_manifest_path=str(manifest_path),
            evidence_dir=str(evidence_dir),
        )

    def _find_render_source(self, youtube_id: str) -> tuple[Path | None, str]:
        """优先用原始下载；仅在已有竖版成片时允许明确标注其派生产物身份。"""
        from video_processing.utils.file_utils import find_downloaded_video

        primary = find_downloaded_video(
            self.output_dir,
            youtube_id,
            archive_dir=self.output_dir / "original_video",
        )
        if primary:
            path = Path(primary)
            if _usable_file(path):
                return path, "source_download"
        derived_vertical = self.output_dir / f"{youtube_id}_vertical.mp4"
        if _usable_file(derived_vertical):
            return derived_vertical, "existing_vertical_derivative"
        return None, ""

    def _render_video(self, source_path: Path, output_path: Path, *, start_ms: int, end_ms: int) -> None:
        duration_ms = end_ms - start_ms
        if duration_ms < 10_000:
            raise ValueError("Highlight 片段时长低于 10 秒，拒绝渲染")
        temporary_path = output_path.with_suffix(".tmp.mp4")
        if temporary_path.exists():
            temporary_path.unlink()
        command = [
            imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-y",
            "-i", str(source_path),
            "-ss", f"{start_ms / 1000:.3f}", "-t", f"{duration_ms / 1000:.3f}",
            "-map", "0:v:0", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
            str(temporary_path),
        ]
        self._run(command, timeout=600, label="Highlight 视频切片")
        if not _usable_file(temporary_path):
            raise RuntimeError("Highlight 视频渲染未生成有效文件")
        temporary_path.replace(output_path)

    def _generate_copy(self, clip_id: str, title: str, excerpt_path: Path, workspace: Path) -> None:
        self._run(
            [
                str(self.python), "scripts/copywriter.py", "--youtube-id", clip_id,
                "--title", title, "--desc-file", str(excerpt_path), "--output-dir", str(workspace),
            ],
            timeout=240,
            label="Highlight 文案生成",
        )

    def _generate_cover(self, title: str, cover_path: Path, provenance_path: Path) -> None:
        self._run(
            [
                str(self.python), "scripts/cover_generator.py", "--title", title,
                "--output", str(cover_path), "--provenance-output", str(provenance_path),
            ],
            timeout=180,
            label="Highlight 专用封面生成",
        )

    def _run(self, command: list[str], *, timeout: int, label: str) -> None:
        try:
            result = subprocess.run(
                command,
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"{label}超时") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip().splitlines()[-1:] or ["未知错误"]
            raise RuntimeError(f"{label}失败：{detail[0][:400]}")


def _usable_file(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 1024
    except OSError:
        return False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_vertical_mp4(path: Path) -> dict[str, Any]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe 不可用，无法验证 Highlight 成片")
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("ffprobe 无法读取 Highlight 成片")
    payload = json.loads(result.stdout or "{}")
    streams = payload.get("streams") or []
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    if not video or int(video.get("height") or 0) <= int(video.get("width") or 0):
        raise RuntimeError("Highlight 成片不是竖版视频")
    duration = float((payload.get("format") or {}).get("duration") or 0)
    if duration < 9:
        raise RuntimeError("Highlight 成片时长异常")
    return {"duration_sec": round(duration, 3), "width": int(video["width"]), "height": int(video["height"])}


def _validate_dedicated_cover(cover_path: Path, provenance_path: Path) -> None:
    if not _usable_file(cover_path):
        raise RuntimeError("Highlight 专用封面或来源证明缺失")
    try:
        if not provenance_path.is_file() or provenance_path.stat().st_size < 100:
            raise RuntimeError("Highlight 专用封面或来源证明缺失")
    except OSError as exc:
        raise RuntimeError("Highlight 专用封面或来源证明缺失") from exc
    payload = json.loads(provenance_path.read_text(encoding="utf-8"))
    if payload.get("cover_kind") != "dedicated_generated_image" or payload.get("uses_video_frame") is not False:
        raise RuntimeError("Highlight 封面来源不满足专用非截帧要求")


def _file_manifest(path: Path, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"path": str(path), "sha256": _sha256(path), "bytes": path.stat().st_size}
    if extra:
        payload.update(extra)
    return payload


def _write_json_atomically(path: Path, payload: dict[str, Any]) -> None:
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temporary_path.replace(path)
