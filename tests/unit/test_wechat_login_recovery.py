"""微信登录恢复测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-27 | Codex | 覆盖微信重登成功后 LOGIN_REQUIRED 自动恢复为 PENDING 的最小行为 |
"""


def test_restore_login_required_after_wechat_login_resets_all_rows(monkeypatch):
    import web.app

    class FakeDB:
        def __init__(self):
            self.updated = []

        def get_videos_by_status(self, status):
            assert status == "LOGIN_REQUIRED"
            return [
                {"youtube_id": "main-video", "slice_index": 0},
                {"youtube_id": "slice-video", "slice_index": 2},
            ]

        def update_video_status(self, youtube_id, status, error_msg=None, slice_index=0):
            self.updated.append((youtube_id, status, error_msg, slice_index))

    fake_db = FakeDB()
    monkeypatch.setattr(web.app, "db", fake_db)

    assert web.app._restore_login_required_after_wechat_login() == 2
    assert fake_db.updated == [
        ("main-video", "PENDING", None, 0),
        ("slice-video", "PENDING", None, 2),
    ]
