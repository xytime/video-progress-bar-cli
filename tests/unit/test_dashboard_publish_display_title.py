"""仪表盘发布标题展示回归测试。

# Modification History
| Version | Date       | Author | Description |
|---------|------------|--------|-------------|
| 1.0.0   | 2026-08-04 | Codex  | 覆盖 dashboard 标题优先使用真实投递短标题 |
"""

import web.app as web_app


def test_dashboard_display_title_prefers_publish_title_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(web_app, "_OUT_DIR", tmp_path)
    (tmp_path / "abc123_title.txt").write_text("真实微信标题", encoding="utf-8")
    (tmp_path / "abc123_copy.txt").write_text("真实微信正文第一句", encoding="utf-8")

    rows = [{
        "youtube_id": "abc123",
        "slice_index": 0,
        "title": "Original YouTube Title",
        "zh_title": "旧的源标题翻译",
    }]

    web_app._attach_publish_display_fields(rows)

    assert rows[0]["published_title"] == "真实微信标题"
    assert rows[0]["display_title"] == "真实微信标题"
    assert rows[0]["published_copy_preview"] == "真实微信正文第一句"
    assert rows[0]["title_mismatch"] is True


def test_dashboard_display_title_falls_back_to_source_title(tmp_path, monkeypatch):
    monkeypatch.setattr(web_app, "_OUT_DIR", tmp_path)
    rows = [{
        "youtube_id": "abc123",
        "slice_index": 0,
        "title": "Original YouTube Title",
        "zh_title": "源标题翻译",
    }]

    web_app._attach_publish_display_fields(rows)

    assert rows[0]["published_title"] is None
    assert rows[0]["display_title"] == "源标题翻译"
    assert rows[0]["title_mismatch"] is False
