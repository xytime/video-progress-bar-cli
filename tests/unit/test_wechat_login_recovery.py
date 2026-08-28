"""微信登录恢复测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-27 | Codex | 覆盖微信重登成功后 LOGIN_REQUIRED 自动恢复为 PENDING 的最小行为 |
| 1.1.0 | 2026-08-26 | Codex | 提交受理未绑定/已绑定账本也必须阻断登录恢复与批量失败重试。 |
| 1.2.0 | 2026-08-28 | Codex | 覆盖英语世界仅恢复一条登录前明确失败的自动投稿项。 |
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


def test_login_recovery_starts_only_the_dal_claimed_english_world_item(monkeypatch):
    import web.app

    class FakeDB:
        def claim_english_world_login_recovery(self, *, max_age_hours):
            assert max_age_hours == 12
            return {"id": "a" * 32, "state": "SUBMISSION_APPROVED"}

    started: list[str] = []
    monkeypatch.setattr(web.app, "db", FakeDB())
    monkeypatch.setattr(web.app.settings, "enable_english_world_auto_publish", True)
    monkeypatch.setattr(web.app.settings, "wechat_publishing_paused", False)
    monkeypatch.setattr(web.app, "_start_english_world_submission", started.append)

    item = web.app._resume_eligible_english_world_after_wechat_login()

    assert item and item["id"] == "a" * 32
    assert started == ["a" * 32]


def test_dal_restore_login_required_skips_submission_evidence(tmp_path):
    from video_processing.db.database import PipelineDB

    db = PipelineDB(str(tmp_path / "pipeline.db"))
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO processed_videos "
            "(youtube_id, title, channel_id, status, score) VALUES (?, ?, ?, ?, ?)",
            ("safe-video", "Safe", "channel", "LOGIN_REQUIRED", 81),
        )
        conn.execute(
            "INSERT INTO processed_videos "
            "(youtube_id, title, channel_id, status, score) VALUES (?, ?, ?, ?, ?)",
            ("submitted-video", "Submitted", "channel", "LOGIN_REQUIRED", 90),
        )
        submitted_id = conn.execute(
            "SELECT id FROM processed_videos WHERE youtube_id = 'submitted-video'"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO publication_subjects (id, kind, video_id) VALUES (?, ?, ?)",
            ("submitted-video", "VIDEO_ITEM", submitted_id),
        )
        conn.execute(
            "INSERT INTO wechat_publications "
            "(video_id, subject_id, state) VALUES (?, ?, ?)",
            (submitted_id, "submitted-video", "UNDER_REVIEW"),
        )
        conn.execute(
            "INSERT INTO processed_videos "
            "(youtube_id, title, channel_id, status, score) VALUES (?, ?, ?, ?, ?)",
            ("unbound-video", "Unbound", "channel", "LOGIN_REQUIRED", 90),
        )
        unbound_id = conn.execute(
            "SELECT id FROM processed_videos WHERE youtube_id = 'unbound-video'"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO publication_subjects (id, kind, video_id) VALUES (?, ?, ?)",
            ("unbound-video", "VIDEO_ITEM", unbound_id),
        )
        conn.execute(
            "INSERT INTO wechat_publications "
            "(video_id, subject_id, state) VALUES (?, ?, ?)",
            (unbound_id, "unbound-video", "SUBMITTED_UNBOUND"),
        )
        conn.commit()

    assert db.restore_login_required_videos() == 1
    with db.get_connection() as conn:
        statuses = dict(conn.execute(
            "SELECT youtube_id, status FROM processed_videos ORDER BY youtube_id"
        ).fetchall())
    assert statuses == {
        "safe-video": "PENDING",
        "submitted-video": "LOGIN_REQUIRED",
        "unbound-video": "LOGIN_REQUIRED",
    }
def test_uploader_login_only_restores_tasks_after_existing_session_check(tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    from scripts import wechat_uploader

    page = MagicMock()
    page.url = wechat_uploader.WECHAT_CREATE_URL
    context = MagicMock()
    context.new_page.return_value = page
    browser = MagicMock()
    browser.new_context.return_value = context
    playwright = MagicMock()
    playwright.__enter__.return_value.chromium.launch.return_value = browser
    restored = MagicMock(return_value=2)

    monkeypatch.setattr(wechat_uploader, "sync_playwright", lambda: playwright)
    monkeypatch.setattr(wechat_uploader, "_restore_login_required_tasks_after_login", restored)

    assert wechat_uploader.run_uploader(
        state_path=str(tmp_path / "wechat_state.json"),
        login_only=True,
    ) == 0
    restored.assert_called_once_with()
    browser.close.assert_called_once()
