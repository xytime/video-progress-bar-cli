"""Dashboard 局域网绑定与浏览器同源守卫回归测试。

# Modification History
| 1.2.0 | 2026-09-20 | Gemini | 验证静态资源 (/static/css/dashboard.css, /static/js/channel_manager.js) 在外部 Origin 下仍 200 放行，控制面写入 API 保持 403。 |
| 1.1.0 | 2026-09-08 | Codex | 覆盖 IPv4 通配绑定和局域网地址同源放行，第三方 Origin 仍拒绝。 |
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-29 | Codex | 覆盖禁止 0.0.0.0、同源放行及外部 Origin 在路由前拒绝。 |
"""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from config.settings import Settings


def test_dashboard_bind_host_allows_ipv4_wildcard_but_rejects_arbitrary_host():
    assert Settings(_env_file=None, dashboard_bind_host="0.0.0.0").dashboard_bind_host == "0.0.0.0"
    with pytest.raises(ValidationError):
        Settings(_env_file=None, dashboard_bind_host="192.168.1.5")


def test_dashboard_allows_local_same_origin_and_rejects_external_browser_origin():
    import web.app

    client = TestClient(web.app.app)
    local_origin = f"http://127.0.0.1:{web.app.settings.dashboard_port}"

    assert client.get("/").status_code == 200
    assert client.get("/", headers={"Origin": local_origin}).status_code == 200
    lan_origin = f"http://192.168.1.5:{web.app.settings.dashboard_port}"
    assert client.get(
        "/",
        headers={"Host": f"192.168.1.5:{web.app.settings.dashboard_port}", "Origin": lan_origin},
    ).status_code == 200
    rejected = client.post(
        "/api/pipeline/run",
        headers={"Origin": "https://example.invalid"},
    )
    assert rejected.status_code == 403
    assert rejected.json() == {"detail": "untrusted dashboard origin"}


def test_static_assets_allow_external_origin_while_mutation_api_rejected():
    import web.app

    client = TestClient(web.app.app)
    untrusted_origin = "https://malicious.attacker.com"

    css_resp = client.get(
        "/static/css/dashboard.css",
        headers={"Origin": untrusted_origin},
    )
    assert css_resp.status_code == 200
    assert "text/css" in css_resp.headers.get("content-type", "")

    js_resp = client.get(
        "/static/js/channel_manager.js",
        headers={"Origin": untrusted_origin},
    )
    assert js_resp.status_code == 200
    assert "javascript" in js_resp.headers.get("content-type", "")

    rejected = client.post(
        "/api/pipeline/run",
        headers={"Origin": untrusted_origin},
    )
    assert rejected.status_code == 403
    assert rejected.json() == {"detail": "untrusted dashboard origin"}

