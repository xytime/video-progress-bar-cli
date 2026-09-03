"""英语世界抖音专属封面测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-04 | Codex | 验证横竖海报封面与来源清单独立于视频号审核包生成。 |
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image

from video_processing.english_world.douyin_cover import SERIES_LABEL, prepare_douyin_cover_package


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_prepare_douyin_cover_package_generates_two_poster_covers_without_changing_review_cover(tmp_path):
    mp4 = tmp_path / "study-card.mp4"
    source_cover = tmp_path / "wechat_cover.jpg"
    title = tmp_path / "title.txt"
    provenance = tmp_path / "cover_provenance.json"
    visual = tmp_path / "variant-a" / "visual.png"
    manifest = tmp_path / "candidate_manifest.json"
    mp4.write_bytes(b"video")
    title.write_text("冰雹是怎样形成的？", encoding="utf-8")
    visual.parent.mkdir()
    Image.new("RGB", (1080, 1260), "#B7D7E5").save(visual)
    Image.new("RGB", (1080, 1260), "#E9E1CE").save(source_cover)
    manifest.write_text("{}", encoding="utf-8")
    provenance.write_text(json.dumps({
        "uses_video_frame": False,
        "visual_asset": {
            "kind": "dedicated_generated_visual",
            "filename": visual.name,
            "sha256": _digest(visual),
            "manifest": str(manifest),
        },
    }), encoding="utf-8")
    source_before = _digest(source_cover)

    package = prepare_douyin_cover_package({
        "mp4_path": str(mp4),
        "cover_path": str(source_cover),
        "cover_provenance_path": str(provenance),
        "title_path": str(title),
    })

    vertical = Path(package["vertical_cover_path"])
    horizontal = Path(package["horizontal_cover_path"])
    record = json.loads(Path(package["provenance_path"]).read_text(encoding="utf-8"))
    assert Image.open(vertical).size == (1080, 1440)
    assert Image.open(horizontal).size == (1440, 1080)
    assert record["series_label"] == SERIES_LABEL
    assert record["uses_video_frame"] is False
    assert record["vertical"]["sha256"] == _digest(vertical)
    assert record["horizontal"]["sha256"] == _digest(horizontal)
    assert _digest(source_cover) == source_before

    assert prepare_douyin_cover_package({
        "mp4_path": str(mp4),
        "cover_path": str(source_cover),
        "cover_provenance_path": str(provenance),
        "title_path": str(title),
    }) == package
