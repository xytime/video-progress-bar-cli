"""通过真实 Uvicorn ASGI 配置验证英语世界只信任真实回环对端。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-10-25 | Codex | 覆盖英语世界配置的HTTPS Origin、secure会话cookie、CSRF与其它路由隔离。 |
| 1.0.0 | 2026-10-25 | Codex | 覆盖 Uvicorn 转发头关闭配置及英语世界 Host、Origin、会话和 CSRF 边界。 |
"""
import ast
import hashlib
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest
import uvicorn

from config.settings import Settings
from video_processing.db.database import PipelineDB
from web.english_world_console import create_english_console_router
from web.local_runtime_access import create_runtime_access


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ORIGIN = "http://127.0.0.1:9100"
PUBLIC_ORIGIN = "https://v.optionbank.us"
PUBLIC_HOST = "v.optionbank.us"


def _configured_proxy_headers_value():
    """读取生产入口传给 uvicorn.run 的显式值，避免测试复制默认配置。"""
    tree = ast.parse((PROJECT_ROOT / "src/web/app.py").read_text())
    calls = [node for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
             and isinstance(node.func.value, ast.Name) and node.func.value.id == "uvicorn"
             and node.func.attr == "run"]
    assert len(calls) == 1
    configured = next((item.value for item in calls[0].keywords if item.arg == "proxy_headers"), None)
    assert isinstance(configured, ast.Constant)
    return configured.value


@pytest.fixture
def routed_app(tmp_path, monkeypatch):
    import web.app as dashboard

    monkeypatch.setattr(dashboard.settings, "dashboard_english_world_public_origin", PUBLIC_ORIGIN)
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    db.topic_initialize()
    output = tmp_path / "output"
    output.mkdir()
    app = FastAPI()
    app.middleware("http")(dashboard.reject_untrusted_browser_origins)

    @app.get("/api/english-world/middleware-probe")
    def middleware_probe():
        return {"ok": True}

    app.include_router(create_english_console_router(
        db, port=9100, output=output, public_origin=PUBLIC_ORIGIN,
    ))

    other_boundary, _, _ = create_runtime_access(db, 9100)

    @app.get("/other-settings", dependencies=[Depends(other_boundary)])
    def other_settings():
        return {"ok": True}

    return app


@pytest.mark.parametrize(
    ("peer", "forwarded_for", "expected_status"),
    [
        ("127.0.0.1", "198.51.100.44", 200),
        ("198.51.100.45", "127.0.0.1", 403),
    ],
)
def test_english_world_uses_socket_peer_with_real_uvicorn_config(
    routed_app, peer, forwarded_for, expected_status,
):
    """X-Forwarded-For 不能把真实本机请求变远端，也不能把远端伪装成本机。"""
    proxy_headers = _configured_proxy_headers_value()
    assert proxy_headers is False

    config = uvicorn.Config(routed_app, proxy_headers=proxy_headers)
    config.load()
    client = TestClient(config.loaded_app, base_url=ORIGIN, client=(peer, 50000))
    headers = {
        "Host": "127.0.0.1:9100",
        "Origin": ORIGIN,
        "X-Forwarded-For": forwarded_for,
    }

    page = client.get("/english-world", headers=headers)
    assert page.status_code == expected_status
    if peer != "127.0.0.1":
        return

    assert client.cookies.get("runtime_local_session")
    listing = client.get("/api/english-world/workbench", headers=headers)
    assert listing.status_code == 200

    body = {
        "task": "new",
        "action": "unsupported-test-action",
        "revision": "test-revision",
        "operation_id": "proxy-peer-check-0001",
        "payload": {},
    }
    bad_csrf = client.post("/api/english-world/workbench/actions", headers=headers, json=body)
    assert bad_csrf.status_code == 403

    token = client.cookies["runtime_local_session"]
    csrf = hashlib.sha256(("runtime-csrf:" + token).encode()).hexdigest()
    accepted_csrf = client.post(
        "/api/english-world/workbench/actions",
        headers={**headers, "X-Runtime-CSRF": csrf},
        json=body,
    )
    # 422 means the request passed session, Origin and CSRF checks and reached
    # action validation; the unsupported action is rejected before any mutation.
    assert accepted_csrf.status_code == 422


def test_english_world_still_rejects_invalid_host_and_origin(routed_app):
    config = uvicorn.Config(routed_app, proxy_headers=_configured_proxy_headers_value())
    config.load()
    client = TestClient(config.loaded_app, base_url=ORIGIN, client=("127.0.0.1", 50000))

    bad_host = client.get("/english-world", headers={"Host": "attacker.invalid:9100"})
    assert bad_host.status_code == 403
    assert client.get("/english-world").status_code == 200
    bad_origin = client.get(
        "/api/english-world/workbench",
        headers={"Origin": "https://attacker.invalid"},
    )
    assert bad_origin.status_code == 403


def test_configured_public_origin_is_validated_as_exact_https_origin():
    assert Settings(_env_file=None).dashboard_english_world_public_origin == ""
    assert Settings(
        _env_file=None,
        dashboard_english_world_public_origin=PUBLIC_ORIGIN,
    ).dashboard_english_world_public_origin == PUBLIC_ORIGIN
    for invalid in (
        "http://v.optionbank.us",
        "https://v.optionbank.us/",
        "https://v.optionbank.us/path",
        "https://v.optionbank.us?x=1",
        "https://v.optionbank.us#fragment",
        "https://user@v.optionbank.us",
        "https://v.optionbank.us\\evil",
        "https://bad_host.optionbank.us",
        "https://bad..optionbank.us",
        "https://v.optionbank.us:0443",
        "https://v.optionbank.us:bad",
    ):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, dashboard_english_world_public_origin=invalid)


def test_public_english_world_origin_works_over_http_origin_with_secure_session_and_csrf(routed_app):
    config = uvicorn.Config(routed_app, proxy_headers=_configured_proxy_headers_value())
    config.load()
    # TLS terminates before the ASGI app. Keep the backend request scheme HTTP while
    # sending the browser's exact public HTTPS Origin.
    client = TestClient(config.loaded_app, base_url="http://v.optionbank.us", client=("127.0.0.1", 50000))
    headers = {
        "Host": PUBLIC_HOST,
        "Origin": PUBLIC_ORIGIN,
        "Sec-Fetch-Site": "same-origin",
    }
    unauthenticated = TestClient(config.loaded_app, base_url="http://v.optionbank.us", client=("127.0.0.1", 50001))
    assert unauthenticated.get(
        "/api/english-world/workbench",
        headers=headers,
    ).status_code == 403

    page = client.get("/english-world", headers=headers)
    assert page.status_code == 200
    session = page.cookies.get("runtime_local_session")
    assert session and len(session) == 64
    assert "secure" in page.headers["set-cookie"].lower()

    cookie_headers = {**headers, "Cookie": f"runtime_local_session={session}"}
    listing = client.get("/api/english-world/workbench", headers=cookie_headers)
    assert listing.status_code == 200

    body = {
        "task": "new",
        "action": "unsupported-test-action",
        "revision": "test-revision",
        "operation_id": "public-origin-check-0001",
        "payload": {},
    }
    assert client.post(
        "/api/english-world/workbench/actions",
        headers=cookie_headers,
        json=body,
    ).status_code == 403
    assert client.post(
        "/api/english-world/workbench/actions",
        headers={**cookie_headers, "Origin": "http://v.optionbank.us"},
        json=body,
    ).status_code == 403
    csrf = hashlib.sha256(("runtime-csrf:" + session).encode()).hexdigest()
    accepted = client.post(
        "/api/english-world/workbench/actions",
        headers={**cookie_headers, "X-Runtime-CSRF": csrf},
        json=body,
    )
    assert accepted.status_code == 422


def test_public_origin_does_not_trust_forwarded_peer_or_expand_other_routes(routed_app):
    config = uvicorn.Config(routed_app, proxy_headers=_configured_proxy_headers_value())
    config.load()
    remote = TestClient(config.loaded_app, base_url="http://v.optionbank.us", client=("198.51.100.45", 50000))
    public_headers = {
        "Host": PUBLIC_HOST,
        "Origin": PUBLIC_ORIGIN,
        "X-Forwarded-For": "127.0.0.1",
        "X-Forwarded-Proto": "https",
    }
    assert remote.get("/api/english-world/middleware-probe", headers=public_headers).status_code == 403
    assert remote.get("/english-world", headers=public_headers).status_code == 403

    local = TestClient(config.loaded_app, base_url="http://v.optionbank.us", client=("127.0.0.1", 50000))
    assert local.get("/api/english-world/middleware-probe", headers=public_headers).status_code == 200
    assert local.get(
        "/english-world",
        headers={**public_headers, "Origin": "https://attacker.invalid"},
    ).status_code == 403
    assert local.get("/other-settings", headers=public_headers).status_code == 403
    assert local.get(
        "/english-world",
        headers={**public_headers, "Host": "attacker.invalid"},
    ).status_code == 403
    assert local.get("/other-settings", headers={"Host": PUBLIC_HOST}).status_code == 403
