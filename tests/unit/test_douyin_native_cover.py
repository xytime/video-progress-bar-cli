"""抖音独立横封面的底图来源与原生布局回归。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-05 | Codex | 验证来源哈希、不复用带字竖海报、横版布局及产物来源清单。 |
"""

import hashlib
import json
from unittest.mock import MagicMock

from cover.douyin import render_horizontal_cover
from video_processing.core.cover_policy import (
    compliant_cover_layout_policy, validate_dedicated_cover_file,
)


def test_native_horizontal_uses_original_not_portrait(tmp_path, monkeypatch):
    portrait = tmp_path / "video_cover.jpg"
    portrait.write_bytes(b"portrait with words")
    original = tmp_path / "finish/task/visual.png"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"verified original without words")
    manifest = {
        "cover_kind": "dedicated_generated_image", "uses_video_frame": False,
        "cover_filename": portrait.name,
        "cover_sha256": hashlib.sha256(portrait.read_bytes()).hexdigest(),
        "layout_policy": compliant_cover_layout_policy(),
        "visual_asset": {"filename": "visual.png", "sha256": hashlib.sha256(original.read_bytes()).hexdigest()},
    }
    portrait.with_name("video_cover_provenance.json").write_text(json.dumps(manifest))
    engine = MagicMock()
    engine.plan.return_value = {}
    def render(layout, path):
        from pathlib import Path
        Path(path).write_bytes(b"native landscape")
    engine.renderer.render.side_effect = render
    monkeypatch.setattr("cover.douyin.CoverEngine", lambda: engine)
    output = tmp_path / "horizontal.jpg"
    assert render_horizontal_cover(portrait, "准确标题", tmp_path / "finish", output) == output
    assert engine.plan.call_args.args[0]["visual_asset_path"] == str(original)
    assert engine.plan.call_args.args[0]["title"] == "准确标题"
    assert engine.renderer.render.call_args.args[0]["canvas_width"] == 1440
    assert engine.renderer.render.call_args.args[0]["canvas_height"] == 1080
    assert validate_dedicated_cover_file(output, tmp_path / "horizontal_provenance.json")
    original.write_bytes(b"corrupted original")
    engine.reset_mock()
    assert render_horizontal_cover(portrait, "准确标题", tmp_path / "finish", output) is None
    engine.renderer.render.assert_not_called()


def test_missing_cover_provenance_does_not_render(tmp_path):
    assert render_horizontal_cover(tmp_path / "missing.jpg", "标题", tmp_path, tmp_path / "out.jpg") is None
