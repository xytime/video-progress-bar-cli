"""手动登录入口拒绝原因必须原样展示，且不能误作自动保活。"""
import web.app as web_app


def test_manual_login_preserves_deferred_reason(monkeypatch):
    captured = {}
    def start(**kwargs):
        captured.update(kwargs)
        return {"success": False, "deferred": True, "message": "账户冷却中"}
    monkeypatch.setattr(web_app, "_start_wechat_login_flow", start)
    result = web_app.wechat_login(headless=True)
    assert captured["reason"] == "manual"
    assert result == {"success": False, "deferred": True, "message": "账户冷却中"}


def test_manual_login_started_message_requires_success(monkeypatch):
    monkeypatch.setattr(web_app, "_start_wechat_login_flow",
                        lambda **kwargs: {"success": True})
    assert "已启动" in web_app.wechat_login(headless=True)["message"]
