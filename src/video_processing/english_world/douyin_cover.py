"""英语世界抖音专属横竖封面。

视频号审核包中的学习卡封面保留为历史不可变证据；抖音投稿时由本模块另外生成
海报式横竖封面，避免拿课程页、视频帧或截图充当抖音封面。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-04 | Codex | 新增英语世界抖音横竖海报封面及来源清单，保留视频号审核包不变。 |
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import textwrap
from typing import Any, Mapping

from PIL import Image, ImageDraw, ImageFont, ImageOps

from video_processing.core.cover_policy import compliant_cover_layout_policy


SERIES_LABEL = "英语视觉短视频"
_VERTICAL_SIZE = (1080, 1440)
_HORIZONTAL_SIZE = (1440, 1080)
_FONT_PATHS = (
    Path("/System/Library/Fonts/PingFang.ttc"),
    Path("/System/Library/Fonts/STHeiti Light.ttc"),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _FONT_PATHS:
        if not path.is_file():
            continue
        try:
            return ImageFont.truetype(str(path), size, index=5 if bold and "PingFang" in path.name else 0)
        except OSError:
            continue
    return ImageFont.load_default()


def _fit_background(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    return ImageOps.fit(image.convert("RGB"), size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.55))


def _source_visual(item: Mapping[str, Any]) -> tuple[Image.Image | None, dict[str, str] | None]:
    """只复用已声明为非视频帧的无字主视觉；无法验证时转为本地原创插画。"""
    provenance_path = Path(str(item.get("cover_provenance_path") or ""))
    if not provenance_path.is_file():
        return None, None
    try:
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        visual = provenance.get("visual_asset")
        if provenance.get("uses_video_frame") is not False or not isinstance(visual, Mapping):
            return None, None
        manifest_path = Path(str(visual.get("manifest") or ""))
        filename = str(visual.get("filename") or "").strip()
        expected_sha = str(visual.get("sha256") or "").strip().lower()
        visual_path = manifest_path.parent / "variant-a" / filename
        if not filename or not visual_path.is_file() or _sha256(visual_path) != expected_sha:
            return None, None
        with Image.open(visual_path) as source:
            return source.convert("RGB").copy(), {
                "path": str(visual_path),
                "sha256": expected_sha,
                "kind": str(visual.get("kind") or "dedicated_generated_visual"),
            }
    except (OSError, ValueError, json.JSONDecodeError):
        return None, None


def _fallback_visual(size: tuple[int, int], title: str) -> Image.Image:
    """生成无字概念插画，确保缺少旧主视觉时也不会退回视频帧或课程页。"""
    width, height = size
    image = Image.new("RGB", size, "#E8F1F4")
    draw = ImageDraw.Draw(image)
    seed = int(hashlib.sha256(title.encode("utf-8")).hexdigest()[:8], 16)
    palette = (("#F5C78D", "#D76C4B"), ("#93B9C9", "#E8A064"), ("#CBB7D7", "#558B7A"))[seed % 3]
    draw.ellipse((-width // 4, height // 2, width * 3 // 4, height * 5 // 4), fill=palette[0])
    draw.ellipse((width // 2, -height // 7, width * 6 // 5, height * 3 // 5), fill=palette[1])
    for offset in range(-height // 5, height, height // 6):
        draw.line((0, offset, width, offset - height // 4), fill="#F9F5EA", width=18)
    return image


def _title_lines(title: str, *, limit: int) -> list[str]:
    text = "".join(str(title or "英语世界").split())
    return textwrap.wrap(text, width=limit, break_long_words=True, break_on_hyphens=False)[:2] or ["英语世界"]


def _render_poster(background: Image.Image, *, size: tuple[int, int], title: str) -> Image.Image:
    image = _fit_background(background, size)
    draw = ImageDraw.Draw(image)
    width, height = size
    margin = 62 if width == _VERTICAL_SIZE[0] else 72
    label_font = _font(36 if width == _VERTICAL_SIZE[0] else 34, bold=True)
    title_font = _font(96 if width == _VERTICAL_SIZE[0] else 86, bold=True)
    meta_font = _font(29 if width == _VERTICAL_SIZE[0] else 25, bold=True)

    label_box = draw.textbbox((0, 0), SERIES_LABEL, font=label_font)
    label_width = label_box[2] - label_box[0] + 44
    label_height = label_box[3] - label_box[1] + 30
    draw.rounded_rectangle((margin, margin, margin + label_width, margin + label_height), radius=12, fill="#15354A")
    draw.text((margin + 22, margin + 13), SERIES_LABEL, font=label_font, fill="#FFFFFF")
    draw.text((margin, margin + label_height + 24), "ENGLISH · VISUAL SHORTS", font=meta_font, fill="#15354A", stroke_width=2, stroke_fill="#FFFFFF")

    title_y = margin + label_height + 83
    for line in _title_lines(title, limit=10 if width == _VERTICAL_SIZE[0] else 15):
        draw.text(
            (margin, title_y), line, font=title_font, fill="#102633",
            stroke_width=5, stroke_fill="#FFFFFF",
        )
        title_y += title_font.size + 22

    footer = "原声双语精读"
    footer_box = draw.textbbox((0, 0), footer, font=meta_font)
    footer_width = footer_box[2] - footer_box[0] + 42
    footer_height = footer_box[3] - footer_box[1] + 26
    footer_y = height - margin - footer_height
    draw.rounded_rectangle((margin, footer_y, margin + footer_width, footer_y + footer_height), radius=10, fill="#FFFFFF")
    draw.text((margin + 21, footer_y + 11), footer, font=meta_font, fill="#15354A")
    return image


def _atomic_save(image: Image.Image, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.with_suffix(f".staging{destination.suffix}")
    image.save(staging, format="JPEG", quality=95, optimize=True)
    os.replace(staging, destination)


def _valid_cached_package(vertical: Path, horizontal: Path, provenance: Path, source_cover_sha256: str) -> bool:
    if not all(path.is_file() and path.stat().st_size > 0 for path in (vertical, horizontal, provenance)):
        return False
    try:
        record = json.loads(provenance.read_text(encoding="utf-8"))
        return (
            record.get("source_review_cover_sha256") == source_cover_sha256
            and record.get("series_label") == SERIES_LABEL
            and record.get("uses_video_frame") is False
            and record.get("vertical", {}).get("sha256") == _sha256(vertical)
            and record.get("horizontal", {}).get("sha256") == _sha256(horizontal)
        )
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def prepare_douyin_cover_package(item: Mapping[str, Any]) -> dict[str, str]:
    """生成并返回抖音横竖封面；不修改英语世界审核包的任何文件或哈希。"""
    mp4_path = Path(str(item.get("mp4_path") or ""))
    source_cover = Path(str(item.get("cover_path") or ""))
    if not mp4_path.is_file() or not source_cover.is_file():
        raise FileNotFoundError("英语世界抖音封面缺少已审核成片或原始封面")
    source_cover_sha256 = _sha256(source_cover)
    output_dir = mp4_path.parent / "douyin_submission"
    vertical = output_dir / "cover_vertical.jpg"
    horizontal = output_dir / "cover_horizontal.jpg"
    provenance = output_dir / "cover_provenance.json"
    if _valid_cached_package(vertical, horizontal, provenance, source_cover_sha256):
        return {
            "vertical_cover_path": str(vertical),
            "horizontal_cover_path": str(horizontal),
            "provenance_path": str(provenance),
        }

    title = str(item.get("title") or "").strip()
    if not title:
        title_path = Path(str(item.get("title_path") or ""))
        title = title_path.read_text(encoding="utf-8").strip() if title_path.is_file() else "英语世界"
    source_visual, visual_record = _source_visual(item)
    vertical_background = source_visual or _fallback_visual(_VERTICAL_SIZE, title)
    horizontal_background = source_visual or _fallback_visual(_HORIZONTAL_SIZE, title)
    _atomic_save(_render_poster(vertical_background, size=_VERTICAL_SIZE, title=title), vertical)
    _atomic_save(_render_poster(horizontal_background, size=_HORIZONTAL_SIZE, title=title), horizontal)
    record = {
        "schema_version": 1,
        "cover_kind": "dedicated_generated_image",
        "uses_video_frame": False,
        "series_label": SERIES_LABEL,
        "source_review_cover_sha256": source_cover_sha256,
        "visual_asset": visual_record,
        "fallback_visual": visual_record is None,
        "layout_policy": compliant_cover_layout_policy(),
        "vertical": {"filename": vertical.name, "sha256": _sha256(vertical), "width": _VERTICAL_SIZE[0], "height": _VERTICAL_SIZE[1]},
        "horizontal": {"filename": horizontal.name, "sha256": _sha256(horizontal), "width": _HORIZONTAL_SIZE[0], "height": _HORIZONTAL_SIZE[1]},
        "generator": "video_processing.english_world.douyin_cover@1.0.0",
    }
    staging = provenance.with_suffix(".staging.json")
    staging.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(staging, provenance)
    return {
        "vertical_cover_path": str(vertical),
        "horizontal_cover_path": str(horizontal),
        "provenance_path": str(provenance),
    }
