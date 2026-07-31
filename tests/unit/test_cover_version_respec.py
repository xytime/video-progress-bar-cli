"""音轨版本切换的封面缓存失效测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-30 | Codex | 覆盖 TTS 规格变化时只删除派生音轨/封面产物 |
| 1.1.0 | 2026-07-31 | Codex | 覆盖封面来源清单随版本切换一并失效 |
"""

from web import app as web_app


def test_audio_variant_invalidation_removes_only_derived_assets(tmp_path, monkeypatch):
    monkeypatch.setattr(web_app, "_OUT_DIR", tmp_path)
    youtube_id = "video-id"
    for suffix in ("_vertical.mp4", ".ass", "_cover.jpg", "_cover_brief.json", "_cover_provenance.json"):
        (tmp_path / f"{youtube_id}{suffix}").write_bytes(b"derived")
    source = tmp_path / f"{youtube_id}.mp4"
    copy = tmp_path / f"{youtube_id}_copy.txt"
    source.write_bytes(b"source")
    copy.write_text("copy", encoding="utf-8")

    deleted = web_app._invalidate_audio_variant_artifacts(youtube_id)

    assert deleted == [
        "video-id_vertical.mp4",
        "video-id.ass",
        "video-id_cover.jpg",
        "video-id_cover_brief.json",
        "video-id_cover_provenance.json",
    ]
    assert source.is_file()
    assert copy.is_file()
