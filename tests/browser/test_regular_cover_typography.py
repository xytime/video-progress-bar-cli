"""普通封面 B 方案真实渲染验收，必须使用隔离 runner --browser。

依赖方向：本测试 → CoverEngine / 来源校验；只写隔离临时目录。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-20 | Codex | 验证实底对比度、完整词界、字号下限、横竖安全区和超长拒绝。 |
"""

import json

from PIL import Image
import pytest

from cover.engine import CoverEngine
from scripts.cover_generator import _write_cover_provenance
from video_processing.core.cover_policy import CoverReadabilityError, validate_dedicated_cover_file


@pytest.mark.parametrize("variant", ["cover", "cover_minimal", "cover_drama"])
@pytest.mark.parametrize(("width", "height"), [(1080, 1260), (1440, 1080)])
def test_regular_templates_render_readable_complete_titles(tmp_path, variant, width, height):
    engine = CoverEngine()
    # 亮背景与暗背景均不能透过标题底板影响文字对比度。
    visual = tmp_path / "visual.png"
    Image.new("RGB", (width, height), "white" if variant == "cover" else "black").save(visual)
    title = "人工智能重塑信息现实"
    layout = engine.plan({"title": title, "subtitle": "共同事实还能被守住吗", "category": "资讯",
                          "visual_asset_path": str(visual)})
    layout.update(template_variant=variant, canvas_width=width, canvas_height=height)
    output = tmp_path / "cover.jpg"
    report = engine.renderer.render(layout, str(output))

    assert "".join(report["lines"]) == title
    assert any("人工智能" in line for line in report["lines"])
    assert 1 <= len(report["lines"]) <= 2
    assert report["font_size"] >= 128
    assert report["font_size"] * 180 / width >= 16
    with Image.open(output) as rendered:
        assert rendered.size == (width, height)
        for box in report["bounds"]:
            assert box["x"] >= width * .05
            assert box["x"] + box["width"] <= width * .93 + 1
            assert box["y"] >= height * .12 - 1
            assert box["y"] + box["height"] <= height * .88 + 1
            if box["text"] in report["lines"]:
                pixel = rendered.getpixel((int(box["x"] + 5), int(box["y"] + 5)))
                assert max(abs(a - b) for a, b in zip(pixel, (20, 35, 49))) <= 5
    assert not list(tmp_path.glob("temp_*.html"))


@pytest.mark.parametrize(("title", "expected", "font_size"), [
    ("重新理解什么是聪明", ["重新理解", "什么是聪明"], 144),
    ("非洲如何教会人工智能", ["非洲如何教会", "人工智能"], 144),
    ("人工智能重塑信息现实", ["人工智能", "重塑信息现实"], 144),
    ("每个人都是公共健康参与者", ["每个人都是", "公共健康参与者"], 128),
    ("AI & <未来>", ["AI & <未来>"], 144),
])
def test_engine_preserves_complete_text_and_records_actual_typography(tmp_path, title, expected, font_size):
    output = tmp_path / "cover.jpg"
    payload = {"title": title, "subtitle": "看见变化，理解未来", "category": "观察"}
    layout = CoverEngine().generate(payload, str(output))
    report = layout["rendered_typography"]
    assert report["lines"] == expected
    assert report["font_size"] == font_size
    assert layout["headline_position"] == report["headline_position"]

    provenance = tmp_path / "cover_provenance.json"
    _write_cover_provenance(str(output), str(provenance), payload, layout)
    stored = json.loads(provenance.read_text())
    assert stored["rendered_typography"] == report
    assert stored["layout_policy"]["policy_version"] == "opaque_title_strips_v1"
    assert validate_dedicated_cover_file(output, provenance)


@pytest.mark.parametrize(("payload", "message"), [
    ({"title": "人工智能改变世界并深刻影响每一个人的未来工作与生活"}, "主标题无法"),
    ({"title": "未来", "subtitle": "人工智能改变生活" * 8}, "副标题超过两行"),
    ({"title": "未来", "category": "公共健康人工智能宏观经济观察" * 3}, "超出安全区"),
])
def test_overflow_fails_before_writing_cover(tmp_path, payload, message):
    output = tmp_path / "cover.jpg"
    with pytest.raises(CoverReadabilityError, match=message):
        CoverEngine().generate(payload, str(output))
    assert not output.exists()
    assert not list(tmp_path.glob("temp_*.html"))
