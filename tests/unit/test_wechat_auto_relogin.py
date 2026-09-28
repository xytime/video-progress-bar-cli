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


def test_get_wechat_status_failed_keepalive_not_green_despite_active_marker(tmp_path, monkeypatch):
    """即使历史 marker 存在且在 23h 内，若最近保活失败（如 LOGIN_REQUIRED 或 INVALID_ORIGIN），状态绝不报绿。"""
    output = _prepare_project(tmp_path, monkeypatch)
    state_file = output / "wechat_state.json"
    marker_file = output / "wechat_login_at.txt"

    from video_processing.core.wechat_auth_state import (
        record_wechat_authorization,
        record_wechat_keepalive_result,
    )

    now = time.time()
    marker_file.write_text(str(int(now)))  # 活跃 marker
    record_wechat_authorization(state_file, method="scan_qr", timestamp=now - 1000)

    # 1. 模拟保活失败 LOGIN_REQUIRED
    record_wechat_keepalive_result(state_file, status="LOGIN_REQUIRED", timestamp=now - 10)
    status = web_app.get_wechat_status()
    assert status["logged_in"] is False
    assert status["login_marker_active"] is False
    assert "❌ 会话已失效" in status["status_label"]

    # 2. 模拟保活失败 INVALID_ORIGIN
    record_wechat_keepalive_result(state_file, status="INVALID_ORIGIN", timestamp=now - 5)
    status = web_app.get_wechat_status()
    assert status["logged_in"] is False
    assert status["login_marker_active"] is False
    assert "❌ 来源异常" in status["status_label"]


def test_start_wechat_login_flow_failed_code_does_not_resume(tmp_path, monkeypatch):
    """登录子进程退出码非 0 时，即使旧 marker 存在，绝不能误报授权成功，绝不恢复任务。"""
    from unittest.mock import MagicMock, patch
    output = _prepare_project(tmp_path, monkeypatch)
    state_file = output / "wechat_state.json"
    marker_file = output / "wechat_login_at.txt"

    from video_processing.core.wechat_auth_state import record_wechat_authorization

    old_auth_time = time.time() - 7200
    marker_file.write_text(str(int(old_auth_time)))
    record_wechat_authorization(state_file, method="scan_qr", timestamp=old_auth_time)

    mock_restore = MagicMock()
    monkeypatch.setattr(web_app, "_restore_login_required_after_wechat_login", mock_restore)
    monkeypatch.setattr(web_app, "_resume_eligible_english_world_after_wechat_login", MagicMock())
    monkeypatch.setattr(web_app, "_is_wechat_login_running", lambda: False)

    with patch("subprocess.run", return_value=MagicMock(returncode=1)):
        res = web_app._start_wechat_login_flow(headless=True, preserve_marker=False)
        assert res["success"] is True
        if web_app._wechat_login_thread:
            web_app._wechat_login_thread.join(timeout=2.0)
    assert not mock_restore.called


def test_start_wechat_login_flow_unmodified_auth_does_not_resume(tmp_path, monkeypatch):
    """子进程 returncode=0 但未写入新的 authorized_at 时，绝不触发任务恢复。"""
    from unittest.mock import MagicMock, patch
    output = _prepare_project(tmp_path, monkeypatch)
    state_file = output / "wechat_state.json"
    marker_file = output / "wechat_login_at.txt"

    from video_processing.core.wechat_auth_state import record_wechat_authorization

    old_auth_time = time.time() - 7200
    marker_file.write_text(str(int(old_auth_time)))
    record_wechat_authorization(state_file, method="scan_qr", timestamp=old_auth_time)

    mock_restore = MagicMock()
    monkeypatch.setattr(web_app, "_restore_login_required_after_wechat_login", mock_restore)
    monkeypatch.setattr(web_app, "_resume_eligible_english_world_after_wechat_login", MagicMock())
    monkeypatch.setattr(web_app, "_is_wechat_login_running", lambda: False)

    with patch("subprocess.run", return_value=MagicMock(returncode=0)):
        res = web_app._start_wechat_login_flow(headless=True, preserve_marker=False)
        assert res["success"] is True
        if web_app._wechat_login_thread:
            web_app._wechat_login_thread.join(timeout=2.0)
    assert not mock_restore.called


def test_start_wechat_login_flow_fresh_auth_resumes_tasks(tmp_path, monkeypatch):
    """子进程 returncode=0 且真实写入了新的 authorized_at 时，成功触发任务恢复。"""
    from unittest.mock import MagicMock, patch
    output = _prepare_project(tmp_path, monkeypatch)
    state_file = output / "wechat_state.json"
    marker_file = output / "wechat_login_at.txt"

    from video_processing.core.wechat_auth_state import record_wechat_authorization

    old_auth_time = time.time() - 7200
    marker_file.write_text(str(int(old_auth_time)))
    record_wechat_authorization(state_file, method="scan_qr", timestamp=old_auth_time)

    mock_restore = MagicMock()
    monkeypatch.setattr(web_app, "_restore_login_required_after_wechat_login", mock_restore)
    monkeypatch.setattr(web_app, "_resume_eligible_english_world_after_wechat_login", MagicMock())
    monkeypatch.setattr(web_app, "_is_wechat_login_running", lambda: False)

    def fake_success_run(*args, **kwargs):
        record_wechat_authorization(state_file, method="desktop_quick", timestamp=time.time())
        return MagicMock(returncode=0)

    with patch("subprocess.run", side_effect=fake_success_run):
        res = web_app._start_wechat_login_flow(headless=True, preserve_marker=False)
        assert res["success"] is True
        if web_app._wechat_login_thread:
            web_app._wechat_login_thread.join(timeout=2.0)
    assert mock_restore.called

