"""从已验收原创底图重新排版抖音横封面，不对带字竖海报补边。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-05 | Codex | 哈希校验原始底图，复用原生 HTML 排版生成全幅 4:3 海报。 |
"""

import hashlib
import json
from pathlib import Path

from .engine import CoverEngine
from video_processing.core.cover_policy import validate_dedicated_cover_file


def render_horizontal_cover(
    source_cover: Path, title: str, finish_dir: Path, output: Path,
) -> Path | None:
    """仅复用与已验收竖封面来源哈希一致的无字底图；缺证据不猜测。"""
    provenance_path = source_cover.with_name(f"{source_cover.stem}_provenance.json")
    if not title.strip() or not validate_dedicated_cover_file(source_cover, provenance_path):
        return None
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    visual = provenance.get("visual_asset") or {}
    expected_hash = visual.get("sha256")
    filename = str(visual.get("filename") or "")
    if not expected_hash or not filename or Path(filename).name != filename:
        return None
    original = next((
        path for path in finish_dir.glob(f"*/{filename}")
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == expected_hash
    ), None)
    if original is None:
        return None
    engine = CoverEngine()
    layout = engine.plan({
        "title": title.strip(), "visual_asset_path": str(original.resolve()),
        "headline_position": "upper_left",
    })
    # 横版重新排版不猜分类；只有原标题与已验收底图是当前函数的权威输入。
    layout.update(canvas_width=1440, canvas_height=1080, template_variant="cover", badge="")
    temporary = output.with_name(f".{output.stem}.rendering.jpg")
    engine.renderer.render(layout, str(temporary))
    temporary.replace(output)
    provenance.update(
        cover_filename=output.name,
        cover_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
        source_cover=str(source_cover),
        aspect_ratio="4:3", rendering="native_html_reflow",
    )
    output.with_name(f"{output.stem}_provenance.json").write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    return output
