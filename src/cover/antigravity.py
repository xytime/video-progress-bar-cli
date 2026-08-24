"""Gemini Antigravity 英语世界封面主视觉契约。

本模块只处理无字主视觉的 brief、候选验收和标准化，不让图像模型决定封面文字。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-24 | Codex | 新增 agy 主视觉 brief、OCR 门禁与标准化工具。 |
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping

from PIL import Image, ImageOps


_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})
_CANVAS_SIZE = (1080, 1260)


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """原子写入可审计 JSON。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_visual_brief(timeline: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
    """只把已验证的来源事实交给 Gemini，不传视频帧或未审材料。"""
    source = timeline.get("source_provenance")
    source = source if isinstance(source, Mapping) else {}
    return {
        "schema_version": 1,
        "content_type": "ENGLISH_WORLD_SHORT",
        "title": str(payload["title"]),
        "source_title": str(source.get("source_title") or "").strip(),
        "publisher": str(source.get("publisher") or source.get("source_channel") or "").strip(),
        "quote_en": str(payload["quote_en"]),
        "visual_direction": "温暖克制的报刊编辑插画；以本期英语新闻主题为核心，适合儿童与家庭学习者。",
        "composition": {
            "ratio": "6:7 portrait",
            "subject_placement": "lower half or right side",
            "safe_zone": "upper and left areas remain bright, calm, and free of focal detail",
            "template_slot": "bottom editorial illustration window; no text may appear in the image",
        },
        "prohibitions": [
            "text", "letters", "numbers", "logo", "watermark", "UI", "screenshot",
            "video frame", "thumbnail", "readable symbol", "celebrity likeness",
        ],
    }


def build_agy_prompt(brief: Mapping[str, Any], target: Path) -> str:
    """生成单次无字主视觉任务；输出路径必须位于本次隔离工作目录。"""
    return (
        "You are the image-generation worker for an English news learning-card cover. "
        "Read cover_brief.json in the current directory and use only its stated facts. "
        "Call the generate_image tool exactly once. Create one original, text-free, 6:7 portrait "
        "editorial illustration. Keep the upper and left areas bright and quiet for local typography; "
        "place the focal subject in the lower half or right side. Do not use any video frame, screenshot, "
        "thumbnail, real logo, watermark, UI, text, letters, numbers, readable symbol, or title card. "
        "Absolutely no text of any kind may appear in the image. "
        f"Save the actual image as {target.name} in the current directory. "
        "After saving it, return JSON only with status, asset_path, and a one-sentence visual description."
    )


def generated_images(work_dir: Path, *, excluded: set[Path] | None = None) -> list[Path]:
    """列出生成器在隔离目录写入的候选位图。"""
    excluded = excluded or set()
    return sorted(
        (path for path in work_dir.rglob("*") if path.is_file() and path.suffix.lower() in _IMAGE_SUFFIXES and path not in excluded),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )


def _ocr_text(path: Path) -> str:
    result = subprocess.run(
        ["tesseract", str(path), "stdout", "--psm", "11"],
        capture_output=True,
        text=True,
        check=False,
        timeout=45,
    )
    if result.returncode != 0:
        raise RuntimeError(f"OCR validation failed: {result.stderr[-300:]}")
    return " ".join(result.stdout.split())


def accept_and_normalize(
    source: Path,
    destination: Path,
    *,
    human_reviewed_no_text: bool = False,
) -> dict[str, Any]:
    """拒绝可读文本；只有显式人工确认后才允许 OCR 疑似噪声继续。"""
    with Image.open(source) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        if image.width < 720 or image.height < 840:
            raise ValueError(f"候选尺寸不足：{image.width}x{image.height}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        ImageOps.fit(image, _CANVAS_SIZE, method=Image.Resampling.LANCZOS).save(destination, format="PNG")
    ocr_text = _ocr_text(destination)
    readable_tokens = re.findall(r"[A-Za-z0-9]{3,}", ocr_text)
    if readable_tokens and not human_reviewed_no_text:
        destination.unlink(missing_ok=True)
        raise ValueError(f"OCR 检出可读文字：{' '.join(readable_tokens[:8])}")
    with Image.open(destination) as normalized:
        width, height = normalized.size
    return {
        "source_artifact": str(source.resolve()),
        "sha256": sha256_file(destination),
        "dimensions": {"width": width, "height": height},
        "machine_visual_review": "ocr_empty" if not ocr_text else "ocr_suspect_human_approved",
        "ocr_text": ocr_text,
        "human_visual_review": "reviewed_no_text" if human_reviewed_no_text else None,
        "requires_human_visual_review": not human_reviewed_no_text,
        "uses_video_frame": False,
    }
