"""仪表盘标题翻译错误页防护回归测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-05 | Codex | 覆盖后台翻译错误页不写入，并清理既有污染译名 |
"""

from web import app as web_app


class _FakeDB:
    def __init__(self, existing_zh_title: str):
        self.existing_zh_title = existing_zh_title
        self.updated: list[tuple[str, str]] = []

    def get_video_by_youtube_id(self, _youtube_id: str):
        return {"zh_title": self.existing_zh_title}

    def update_video_zh_title(self, youtube_id: str, zh_title: str):
        self.updated.append((youtube_id, zh_title))
        return True

    def claim_video_for_processing(self, _youtube_id: str):
        return False


def test_dashboard_title_translation_replaces_existing_error_page_with_source(monkeypatch):
    source = "SPACEX EARNINGS PREVIEW"
    error_page = (
        "Error 500 (Server Error)!!1500. That's an error. There was an error. "
        "Please try again later. That's all we know."
    )
    fake_db = _FakeDB(error_page)
    monkeypatch.setattr(web_app, "db", fake_db)
    monkeypatch.setattr(web_app, "_translate_text", lambda *_args, **_kwargs: error_page)

    web_app._translate_title_task("test-video", source)

    assert fake_db.updated == [("test-video", source)]
