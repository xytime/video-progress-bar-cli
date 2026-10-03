"""真实 Chromium 验证保存后封面 Canvas，任何像素或目标歧义均拒绝。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-03 | Codex | 验证 Croppie 小数缩放、错误标题、单像素变更、隐藏或歧义 Canvas 与 uploader 接入。 |
"""
import base64
import json

import pytest
from PIL import Image, ImageDraw

from tests.browser_fixtures import chromium
from scripts.wechat_uploader import _wechat_cover_editor_matches_file
from video_processing.utils.wechat_cover_canvas import matches_editor_canvas


def _cover(tmp_path, title="EXPECTED COVER"):
    path = tmp_path / ("expected.png" if title == "EXPECTED COVER" else "wrong.png")
    image = Image.new("RGB", (1080, 1260), "#345678")
    draw = ImageDraw.Draw(image)
    draw.rectangle((50, 600, 1029, 1199), fill="#aabbcc")
    draw.text((200, 800), title, fill="black", stroke_width=2)
    draw.line((0, 0, 1080, 1260), fill="#123456", width=19)
    image.save(path)
    return path


def _render(page, path, *, integer_width=False):
    src = "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()
    page.set_content('<div id="dialog"><canvas class="cr-image" width="925" height="1080"></canvas></div>')
    page.locator("canvas").evaluate("""async (canvas, args) => {
        const image = new Image(); image.src = args.src; await image.decode();
        const width = args.integer_width ? canvas.width : image.naturalWidth * canvas.height / image.naturalHeight;
        canvas.getContext('2d').drawImage(image, 0, 0, width, canvas.height);
    }""", {"src": src, "integer_width": integer_width})
    return page.locator("#dialog")


def test_canvas_full_pixels_match_and_uploader_accepts(chromium, tmp_path):
    cover = _cover(tmp_path)
    page = chromium.new_page()
    try:
        dialog = _render(page, cover)
        assert matches_editor_canvas(dialog, cover, tmp_path / "evidence")
        proof = json.loads((tmp_path / "evidence/cover_editor_canvas.json").read_text())
        assert proof["different_rgba_values"] == 0
        assert proof["canvas_width"] == 925
        assert "data:" not in json.dumps(proof)
        assert _wechat_cover_editor_matches_file(dialog, cover, tmp_path)
    finally:
        page.close()


@pytest.mark.parametrize("change", ["wrong_title", "one_pixel", "integer_resize", "blank", "hidden", "ambiguous", "small", "missing"])
def test_canvas_rejects_any_difference_or_ambiguous_target(chromium, tmp_path, change):
    cover = _cover(tmp_path)
    page = chromium.new_page()
    try:
        dialog = _render(page, _cover(tmp_path, "WRONG TITLE") if change == "wrong_title" else cover,
                         integer_width=change == "integer_resize")
        changes = {
            "one_pixel": "const c = node.getContext('2d'); const p = c.getImageData(500,500,1,1); p.data[0] ^= 1; c.putImageData(p,500,500);",
            "blank": "node.getContext('2d').clearRect(0,0,node.width,node.height);",
            "hidden": "node.style.display = 'none';",
            "ambiguous": "node.after(node.cloneNode());",
            "small": "node.width = 300; node.height = 150;",
            "missing": "node.remove();",
        }
        if change in changes:
            dialog.locator("canvas").evaluate("node => {" + changes[change] + "}")
        assert not matches_editor_canvas(dialog, cover, tmp_path)
    finally:
        page.close()


def test_canvas_invalid_local_image_fails_closed(chromium, tmp_path):
    cover = _cover(tmp_path)
    page = chromium.new_page()
    try:
        dialog = _render(page, cover)
        cover.write_bytes(b"invalid image")
        assert not matches_editor_canvas(dialog, cover, tmp_path)
        proof = json.loads((tmp_path / "cover_editor_canvas.json").read_text())
        assert not proof["matched"]
        assert proof["error_type"]
    finally:
        page.close()
