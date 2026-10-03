"""视频号保存后封面 Canvas 与指定本地文件的严格像素回读。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-03 | Codex | 复现 Croppie 按高度等比缩放，完整 RGBA 相等才接受保存后封面。 |
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path


_COMPARE = """async (canvases, expectedUrl) => {
    const visible = canvases.filter(c => {
        const r = c.getBoundingClientRect();
        return c.tagName === 'CANVAS' && r.width >= 150 && r.height >= 150;
    });
    const proof = {matched: false, visible_canvas_count: visible.length};
    if (visible.length !== 1) return proof;
    const actual = visible[0];
    if (actual.width < 720 || actual.height < 960 ||
        actual.width > 4096 || actual.height > 4096) return proof;
    const image = new Image(); image.src = expectedUrl;
    await image.decode();
    const scaledWidth = image.naturalWidth * actual.height / image.naturalHeight;
    // Croppie 的 backing canvas 宽度向下取整，drawImage 仍用未取整的等比宽度。
    if (Math.floor(scaledWidth) !== actual.width) return proof;
    const reference = document.createElement('canvas');
    reference.width = actual.width; reference.height = actual.height;
    const context = reference.getContext('2d');
    context.drawImage(image, 0, 0, scaledWidth, actual.height);
    const wanted = context.getImageData(0, 0, actual.width, actual.height).data;
    const got = actual.getContext('2d').getImageData(0, 0, actual.width, actual.height).data;
    proof.canvas_width = actual.width; proof.canvas_height = actual.height;
    if (got.length !== wanted.length) return proof;
    let different = 0;
    for (let i = 0; i < got.length; i++) if (got[i] !== wanted[i]) different++;
    proof.different_rgba_values = different;
    proof.matched = different === 0;
    return proof;
}"""


def matches_editor_canvas(dialog, cover_path: Path, evidence_dir: Path | None = None) -> bool:
    """只核对已重新打开的裁剪编辑器；不允许阈值放行，不读取远端资源。"""
    proof = {"matched": False, "contract": "wechat-cover-canvas-exact-rgba-v1"}
    try:
        content = cover_path.read_bytes()
        if not content or len(content) > 8 * 1024 * 1024:
            return False
        mime = "image/jpeg" if cover_path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
        expected_url = f"data:{mime};base64," + base64.b64encode(content).decode("ascii")
        proof["expected_file_sha256"] = hashlib.sha256(content).hexdigest()
        proof.update(dialog.locator("canvas.cr-image").evaluate_all(_COMPARE, expected_url))
        return proof.get("matched") is True
    except Exception as exc:
        proof["error_type"] = type(exc).__name__
        return False
    finally:
        if evidence_dir is not None:
            evidence_dir.mkdir(parents=True, exist_ok=True)
            (evidence_dir / "cover_editor_canvas.json").write_text(
                json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8",
            )
