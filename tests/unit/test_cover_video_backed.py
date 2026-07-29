"""视频贴合封面的单元测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-29 | Codex | 验证真实成片头部被保留、字幕区不进入 6:7 封面 |
"""

from pathlib import Path
import json
import sys

from PIL import Image

from cover.creative_brief import build_cover_creative_brief
from scripts import cover_generator


def test_video_backed_cover_draws_header_and_excludes_subtitle_area(tmp_path, monkeypatch):
    frame = Image.new("RGB", (1080, 1920), "black")
    # 模拟历史成片的空片头、实际画面和底部字幕三个层，最后一层不得出现在封面清晰主体内。
    frame.paste("blue", (0, 350, 1080, 960))
    frame.paste("yellow", (0, 1040, 1080, 1500))
    monkeypatch.setattr(cover_generator, "_extract_cover_frame", lambda _: frame)
    output = tmp_path / "cover.jpg"

    cover_generator.generate_video_backed_cover("rendered.mp4", output, title="内容贴合封面")

    with Image.open(output) as cover:
        assert cover.size == (1080, 1260)
        header = cover.crop((0, 0, 1080, 330))
        assert max(header.convert("L").getdata()) > 160
        # 未启用内容贴合策划时，旧封面的黑色片头不得出现新的强调条。
        assert max(cover.getpixel((48, 180))) < 30
        pixel = cover.getpixel((540, 600))
        assert pixel[2] > pixel[0] and pixel[2] > pixel[1]
        footer = cover.getpixel((540, 1120))
        assert footer[0] < 120 and footer[1] < 120


def test_video_backed_cover_applies_creative_brief_colors(tmp_path, monkeypatch):
    frame = Image.new("RGB", (1080, 1920), "white")
    monkeypatch.setattr(cover_generator, "_extract_cover_frame", lambda _: frame)
    output = tmp_path / "market_cover.jpg"
    brief = build_cover_creative_brief(
        {"title": "芯片股暴跌", "content_hints": ["market", "chip"]}
    ).to_dict()

    cover_generator.generate_video_backed_cover("rendered.mp4", output, title="芯片股暴跌", brief=brief)

    with Image.open(output) as cover:
        # 市场冲击风格的片头是深灰，左侧强调条保持红色，证明策划已进入像素渲染层。
        assert max(cover.getpixel((900, 180))) < 60
        red, green, blue = cover.getpixel((48, 180))
        assert red > green * 1.6 and red > blue * 1.6


def test_content_aware_cli_passes_brief_to_video_renderer_and_persists_it(tmp_path, monkeypatch):
    output = tmp_path / "cover.jpg"
    brief_output = tmp_path / "cover_brief.json"
    captured = {}

    def fake_render(video_path, output_path, *, title, brief):
        captured.update(video_path=video_path, output_path=output_path, title=title, brief=brief)

    monkeypatch.setattr(cover_generator, "generate_video_backed_cover", fake_render)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "cover_generator.py",
            "--video", "rendered.mp4",
            "--payload", json.dumps({"title": "芯片股暴跌", "content_hints": ["market", "chip"]}),
            "--content-aware",
            "--brief-output", str(brief_output),
            "--output", str(output),
        ],
    )

    cover_generator.main()

    assert captured["brief"]["style_id"] == "market_shock"
    assert json.loads(brief_output.read_text(encoding="utf-8"))["badge"] == "市场警报"
