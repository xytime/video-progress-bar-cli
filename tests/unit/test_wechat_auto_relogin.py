"""微信自动重登的会话龄判定回归。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-25 | Codex | 覆盖标记缺失和自动登录等待期，防止会话过期后静默停止恢复。 |
"""

import time

import web.app as web_app


def _prepare_project(tmp_path, monkeypatch):
    fake_app = tmp_path / "src" / "web" / "app.py"
    fake_app.parent.mkdir(parents=True)
    output = tmp_path / "output"
    output.mkdir()
    (output / "wechat_state.json").write_text("{}")
    monkeypatch.setattr(web_app, "__file__", str(fake_app))
    monkeypatch.setattr(web_app.settings, "wechat_auto_relogin_enabled", True)
    monkeypatch.setattr(web_app.settings, "wechat_keepalive_enabled", True)
    return output


def test_missing_login_marker_with_saved_session_requests_relogin(tmp_path, monkeypatch):
    output = _prepare_project(tmp_path, monkeypatch)
    assert web_app._wechat_session_needs_auto_relogin() is True

    (output / "wechat_auto_relogin_started.flag").write_text("1")
    assert web_app._wechat_session_needs_auto_relogin() is False


def test_expired_login_marker_requests_relogin(tmp_path, monkeypatch):
    output = _prepare_project(tmp_path, monkeypatch)
    monkeypatch.setattr(web_app.settings, "wechat_session_warn_hours", 22.0)
    (output / "wechat_login_at.txt").write_text(str(int(time.time()) - 23 * 3600))
    assert web_app._wechat_session_needs_auto_relogin() is True
