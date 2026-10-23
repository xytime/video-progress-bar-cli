"""视频号冷却与账户调度策略管理单元测试：CAS 热加载、确认平台解冻与单次跳过凭据穿透调度器。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-22 | Antigravity | 验证默认安全生产值、参数边界校验、CAS 保存热加载、Web 端确认解冻及调度器下单次跳过许可穿透 |
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from config.settings import settings
from video_processing.core import wechat_request_guard as guard_mod
from video_processing.core.wechat_request_guard import WeChatRequestDeferred, WeChatRequestGuard
from video_processing.utils import wechat_scheduler_policy as policy
from web.wechat_cooldown_settings import create_wechat_cooldown_settings_router


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    policy_path = tmp_path / "wechat_scheduler_policy.json"
    state_path = tmp_path / "wechat_state.json"
    monkeypatch.setattr(type(settings), "default_output_dir", property(lambda _: tmp_path))
    monkeypatch.setattr(settings, "wechat_scheduler_policy_path", policy_path)
    monkeypatch.setattr(settings, "wechat_account_scheduler_enabled", True)
    monkeypatch.setattr(settings, "wechat_scheduler_stable_interval_seconds", 900)
    monkeypatch.setattr(settings, "wechat_scheduler_daily_limit", 20)
    monkeypatch.setattr(settings, "wechat_scheduler_recovery_interval_seconds", 3600)
    monkeypatch.setattr(settings, "wechat_scheduler_recovery_limit", 1)
    monkeypatch.setattr(settings, "wechat_request_min_interval_seconds", 60)
    monkeypatch.setattr(settings, "wechat_rate_limit_cooldown_seconds", 1800)
    app = FastAPI()
    app.include_router(
        create_wechat_cooldown_settings_router(active=policy_path, state_path=state_path)
    )
    app.mount(
        "/static",
        StaticFiles(directory=Path(__file__).resolve().parents[2] / "src/web/static"),
        name="static",
    )
    with TestClient(app) as client:
        yield client, policy_path, state_path


def test_default_policy_values_and_strict_validation(isolated_env):
    client, _, _ = isolated_env
    res = client.get("/api/wechat-cooldown-settings")
    assert res.status_code == 200
    data = res.json()
    assert data["config"] == {
        "schema_version": 1,
        "scheduler_enabled": True,
        "stable_interval_seconds": 900,
        "daily_limit": 20,
        "recovery_interval_seconds": 3600,
        "recovery_limit": 1,
        "request_min_interval_seconds": 60,
        "rate_limit_cooldown_seconds": 1800,
    }
    assert client.get("/wechat-cooldown-settings").status_code == 200

    for bad in (
        dict(data["config"], stable_interval_seconds=30),
        dict(data["config"], daily_limit=150),
        dict(data["config"], scheduler_enabled="yes"),
        dict(data["config"], unknown_key=1),
    ):
        with pytest.raises(ValueError):
            policy.parse_policy(bad)


def test_cas_save_and_hot_reload_updates_scheduler_limits(isolated_env, monkeypatch):
    client, policy_path, state_path = isolated_env
    clock = [2_000_000.0]
    monkeypatch.setattr(guard_mod.time, "time", lambda: clock[0])

    current = client.get("/api/wechat-cooldown-settings").json()
    updated = dict(
        current["config"],
        stable_interval_seconds=180,
        daily_limit=30,
    )
    put_res = client.put(
        "/api/wechat-cooldown-settings",
        json={"config": updated, "expected_digest": current["digest"]},
    )
    assert put_res.status_code == 200
    assert settings.wechat_scheduler_stable_interval_seconds == 180
    assert settings.wechat_scheduler_daily_limit == 30
    assert policy_path.is_file()

    # 旧 digest 再次提交触发 409 CAS 冲突
    conflict = client.put(
        "/api/wechat-cooldown-settings",
        json={"config": updated, "expected_digest": current["digest"]},
    )
    assert conflict.status_code == 409

    # 跨源伪造被拒绝
    assert (
        client.put(
            "/api/wechat-cooldown-settings",
            json={"config": updated, "expected_digest": put_res.json()["digest"]},
            headers={"origin": "https://evil.invalid"},
        ).status_code
        == 403
    )

    # 验证热更新后的 180s 间隔在实际调度器中生效
    g1 = WeChatRequestGuard(state_path)
    g1.admission("发布", "video-1")
    g1.start_session("发布")

    clock[0] += 100
    with pytest.raises(WeChatRequestDeferred):
        WeChatRequestGuard(state_path).admission("发布", "video-2")

    clock[0] += 81  # 共 181s > 180s（若仍为旧 900s 则会报错）
    g2 = WeChatRequestGuard(state_path)
    g2.admission("发布", "video-2")
    g2.start_session("发布")


def test_web_unfreeze_endpoint_clears_platform_limit_and_recovery(isolated_env, monkeypatch):
    client, _, state_path = isolated_env
    clock = [3_000_000.0]
    monkeypatch.setattr(guard_mod.time, "time", lambda: clock[0])

    guard = WeChatRequestGuard(state_path)
    guard.record_limited(endpoint="/post/post_list", code=-360)

    before = client.get("/api/wechat-cooldown-settings").json()["runtime"]
    assert before["platform_frozen"] is True
    assert before["can_unfreeze"] is True
    version = before["cooldown"]["version"]

    # 错误版本拒绝解冻
    bad = client.post("/api/wechat-cooldown-settings/unfreeze", json={"version": "0" * 64})
    assert bad.status_code == 409

    # 正确版本解冻后，平台冻结与 24h 恢复期同时解除
    ok = client.post("/api/wechat-cooldown-settings/unfreeze", json={"version": version})
    assert ok.status_code == 200
    after = ok.json()["runtime"]
    assert after["platform_frozen"] is False
    assert after["recovering"] is False
    assert after["can_unfreeze"] is False

    # 解冻后立即可按稳定期发布，不受恢复期 1 次上限阻断
    g = WeChatRequestGuard(state_path)
    g.admission("发布", "after-unfreeze-1")
    g.start_session("发布")


def test_single_override_bypasses_scheduler_interval_when_scheduler_enabled(isolated_env, monkeypatch):
    _, _, state_path = isolated_env
    clock = [4_000_000.0]
    monkeypatch.setattr(guard_mod.time, "time", lambda: clock[0])

    # 先正常启动一次发布，触发 900s 稳定期间隔与 60s 会话最小间隔
    g1 = WeChatRequestGuard(state_path)
    g1.admission("发布", "video-a")
    g1.start_session("发布")

    clock[0] += 10
    # 未持单次跳过凭据的任务被拦截
    with pytest.raises(WeChatRequestDeferred):
        WeChatRequestGuard(state_path).admission("发布", "video-b")

    # 签发并消费绑定 video-b 的单次跳过凭据后，可穿透会话间隔与调度器间隔执行一次
    info = WeChatRequestGuard(state_path).cooldown()
    token = WeChatRequestGuard(state_path).issue_override("video-b", info["version"])
    g2 = WeChatRequestGuard(state_path)
    g2.consume_override(token, "video-b")
    g2.check()
    g2.admission("发布", "video-b")
    g2.start_session("发布")
