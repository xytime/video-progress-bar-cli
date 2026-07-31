"""专门生成封面的单元测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-07-30 | Codex | 验证配音角标仅由受限音轨版本字段决定 |
| 1.2.0 | 2026-07-31 | Codex | 验证普通话译制彩带角标完整绘制 |
| 1.3.0 | 2026-07-31 | Codex | 禁止视频帧封面，并验证专门生成封面来源清单 |
| 1.4.0 | 2026-07-31 | Codex | 覆盖专属主视觉资产的哈希绑定来源证明 |
| 1.5.0 | 2026-07-31 | Codex | 封面简报必须记录实际生效的渲染规划 |
| 1.6.0 | 2026-07-31 | Codex | 独立主视觉合成失败时禁止默认封面回退 |
"""

from pathlib import Path
import json
import sys

from PIL import Image
import pytest

from scripts import cover_generator
from video_processing.pipeline_manager import _cover_audio_edition


def test_cover_provenance_marks_generated_asset_as_non_frame(tmp_path):
    output = tmp_path / "cover.jpg"
    output.write_bytes(b"dedicated-image")
    provenance = tmp_path / "cover_provenance.json"

    cover_generator._write_cover_provenance(
        str(output), str(provenance), {"audio_edition": "mandarin_dubbed"}
    )

    payload = json.loads(provenance.read_text(encoding="utf-8"))
    assert payload["cover_kind"] == "dedicated_generated_image"
    assert payload["uses_video_frame"] is False
    assert payload["cover_filename"] == "cover.jpg"
    assert len(payload["cover_sha256"]) == 64


def test_cover_provenance_binds_dedicated_visual_asset(tmp_path):
    output = tmp_path / "cover.jpg"
    visual = tmp_path / "visual.png"
    provenance = tmp_path / "cover_provenance.json"
    output.write_bytes(b"composed-cover")
    visual.write_bytes(b"independent-generated-visual")

    cover_generator._write_cover_provenance(
        str(output),
        str(provenance),
        {"visual_asset_path": str(visual)},
    )

    payload = json.loads(provenance.read_text(encoding="utf-8"))
    assert payload["visual_asset"] == {
        "filename": "visual.png",
        "sha256": "53900a9815a35033211838d47a95a14d3a68a5fa9e37580f9e3f53a136446543",
        "kind": "dedicated_generated_visual",
    }


def test_visual_asset_render_failure_never_falls_back_to_default_cover(tmp_path, monkeypatch):
    visual = tmp_path / "visual.png"
    output = tmp_path / "cover.jpg"
    provenance = tmp_path / "cover_provenance.json"
    Image.new("RGB", (720, 960), "white").save(visual)

    class FailingCoverEngine:
        def generate(self, payload, output_path):
            raise RuntimeError("browser unavailable")

    import cover

    monkeypatch.setattr(cover, "CoverEngine", FailingCoverEngine)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "cover_generator.py",
            "--payload",
            json.dumps({"title": "测试", "visual_asset_path": str(visual)}),
            "--output",
            str(output),
            "--provenance-output",
            str(provenance),
        ],
    )

    with pytest.raises(RuntimeError, match="refusing to fall back"):
        cover_generator.main()

    assert not output.exists()
    assert not provenance.exists()


def test_applied_creative_brief_uses_actual_render_plan():
    brief = cover_generator._applied_creative_brief(
        {"content_hints": ["mindset"], "visual_direction": "分岔道路"},
        {
            "style_id": "mindset_growth",
            "badge": "人生哲学",
            "template_variant": "cover_minimal",
            "headline_position": "upper_left",
            "has_visual_asset": True,
            "visual_asset_path": "/tmp/success-self-defined.png",
        },
    )

    assert brief == {
        "schema_version": 1,
        "style_id": "mindset_growth",
        "badge": "人生哲学",
        "template_variant": "cover_minimal",
        "headline_position": "upper_left",
        "has_visual_asset": True,
        "visual_asset_filename": "success-self-defined.png",
        "visual_keywords": ["mindset"],
        "visual_direction": "分岔道路",
    }


def test_edition_label_is_absent_without_confirmed_mandarin_dub():
    assert cover_generator.resolve_edition_label({"audio_edition": "original_audio_subtitled"}) == ""
    assert cover_generator.resolve_edition_label({"audio_edition": "untrusted_free_text"}) == ""
    assert cover_generator.resolve_edition_label({"audio_edition": "mandarin_dubbed"}) == "普通话译制"


def test_edition_label_draws_only_for_confirmed_mandarin_dub():
    image = Image.new("RGB", (1080, 1260), "black")

    cover_generator._draw_edition_label(image, "")
    assert image.getpixel((1000, 40)) == (0, 0, 0)

    cover_generator._draw_edition_label(image, "普通话译制")
    red, green, blue = image.getpixel((842, 52))
    assert red > 100 and red > green * 2 and red > blue * 1.5
    bbox = image.getbbox()
    assert bbox is not None
    assert bbox[0] >= 810 and bbox[2] <= 1080


def test_cover_audio_edition_only_accepts_providers_that_activate_tts():
    assert _cover_audio_edition(None) == "original_audio_subtitled"
    assert _cover_audio_edition("unknown-provider") == "original_audio_subtitled"
    assert _cover_audio_edition("Edge") == "original_audio_subtitled"
    assert _cover_audio_edition("edge") == "mandarin_dubbed"
    assert _cover_audio_edition("cosyvoice") == "mandarin_dubbed"


def test_video_frame_option_is_rejected(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "cover_generator.py",
            "--video", "rendered.mp4",
        ],
    )

    with pytest.raises(SystemExit):
        cover_generator.main()


def test_minimal_template_uses_the_actual_category_not_a_hard_coded_tech_label():
    template_path = (
        Path(__file__).resolve().parents[2]
        / "resources"
        / "cover"
        / "template"
        / "cover_minimal.html.j2"
    )
    template = template_path.read_text(encoding="utf-8")

    assert '<div class="watermark">{{ badge }}</div>' in template
    assert "科技前沿" not in template
    assert "visual_asset_url" in template
