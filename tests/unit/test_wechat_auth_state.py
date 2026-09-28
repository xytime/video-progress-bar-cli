"""Unit tests for WeChat structured auth state management (wechat_auth_state.py).

# Modification History
| Version | Date       | Author      | Description                              |
|---------|------------|-------------|------------------------------------------|
| 1.0.0   | 2026-09-28 | Antigravity | 初始创建：覆盖结构化授权状态原子读写、白名单字段、调度评估与边界场景 |
"""

import json
import time
from pathlib import Path

import pytest

from video_processing.core.wechat_auth_state import (
    AUTH_STATE_VERSION,
    canonical_wechat_auth_state_path,
    evaluate_wechat_session_status,
    read_wechat_auth_state,
    record_wechat_authorization,
    record_wechat_keepalive_result,
)


def test_canonical_path_derivation(tmp_path: Path):
    state_file = tmp_path / "wechat_state.json"
    derived = canonical_wechat_auth_state_path(state_file)
    assert derived.name == "wechat_auth_state.json"
    assert derived.parent == tmp_path

    custom_state = tmp_path / "custom.json"
    assert canonical_wechat_auth_state_path(custom_state).name == "custom_auth_state.json"


def test_read_missing_state_falls_back_to_legacy(tmp_path: Path):
    state_file = tmp_path / "wechat_state.json"
    # 既无 auth_state.json 也无 wechat_login_at.txt
    res = read_wechat_auth_state(state_file)
    assert res["authorized_at"] is None
    assert res["auth_method"] is None
    assert res["last_verified_at"] is None

    # 有 legacy wechat_login_at.txt
    legacy = tmp_path / "wechat_login_at.txt"
    legacy.write_text("1700000000\n", encoding="utf-8")
    res_legacy = read_wechat_auth_state(state_file)
    assert res_legacy["authorized_at"] == 1700000000.0
    assert res_legacy["auth_method"] == "legacy"
    assert res_legacy["last_verified_at"] is None


def test_record_wechat_authorization_atomic(tmp_path: Path):
    state_file = tmp_path / "wechat_state.json"
    started_flag = tmp_path / "wechat_auto_relogin_started.flag"
    warned_flag = tmp_path / "wechat_login_warned.flag"
    started_flag.write_text("1")
    warned_flag.write_text("1")

    t0 = 1720000000.0
    rec = record_wechat_authorization(state_file, method="desktop_quick", timestamp=t0)

    assert rec["version"] == AUTH_STATE_VERSION
    assert rec["authorized_at"] == t0
    assert rec["auth_method"] == "desktop_quick"
    assert rec["last_verified_at"] == t0
    assert rec["last_keepalive_status"] == "SUCCESS"
    assert rec["last_failure"] is None

    # 验证磁盘文件
    auth_file = canonical_wechat_auth_state_path(state_file)
    assert auth_file.is_file()
    saved = json.loads(auth_file.read_text(encoding="utf-8"))
    assert saved["authorized_at"] == t0
    assert saved["auth_method"] == "desktop_quick"

    # 验证兼容遗留文件与标记清理
    legacy_file = tmp_path / "wechat_login_at.txt"
    assert legacy_file.is_file()
    assert legacy_file.read_text().strip() == str(int(t0))
    assert not started_flag.exists()
    assert not warned_flag.exists()


def test_keepalive_never_forges_or_resets_authorized_at(tmp_path: Path):
    state_file = tmp_path / "wechat_state.json"
    t_auth = 1720000000.0
    record_wechat_authorization(state_file, method="scan_qr", timestamp=t_auth)

    t_keepalive = t_auth + 3600.0
    ka_rec = record_wechat_keepalive_result(state_file, status="SUCCESS", timestamp=t_keepalive)

    # 授权时间保持不变，仅更新最近验证时间
    assert ka_rec["authorized_at"] == t_auth
    assert ka_rec["last_verified_at"] == t_keepalive
    assert ka_rec["last_keepalive_at"] == t_keepalive
    assert ka_rec["last_keepalive_status"] == "SUCCESS"
    assert ka_rec["last_failure"] is None

    # 失败时不覆盖已验证时间，仅记录白名单失败证据
    t_fail = t_keepalive + 1800.0
    fail_rec = record_wechat_keepalive_result(
        state_file,
        status="NETWORK_TIMEOUT",
        failure={"stage": "navigation", "error_type": "NETWORK_TIMEOUT", "detail": "Page.goto timeout 25s", "secret": "leaked_token"},
        timestamp=t_fail,
    )

    assert fail_rec["authorized_at"] == t_auth
    assert fail_rec["last_verified_at"] == t_keepalive  # 依然保持上次成功时间
    assert fail_rec["last_keepalive_status"] == "NETWORK_TIMEOUT"
    assert fail_rec["last_failure"]["error_type"] == "NETWORK_TIMEOUT"
    assert "secret" not in fail_rec["last_failure"]  # 白名单过滤敏感字段


def test_evaluate_wechat_session_status_scenarios():
    # 场景 1: 未授权
    unauth = evaluate_wechat_session_status(
        auth_state={"authorized_at": None, "last_verified_at": None},
        state_file_exists=False,
    )
    assert unauth["status_label"] == "❌ 未授权"
    assert "尚未检测到有效登录记录" in unauth["suggestions"][0]

    # 场景 2: 授权期内且已成功保活
    now = 1720000000.0
    active = evaluate_wechat_session_status(
        auth_state={
            "authorized_at": now - 3600 * 5,  # 5 小时前授权
            "auth_method": "desktop_quick",
            "last_verified_at": now - 1800,   # 30 分钟前保活
            "last_keepalive_status": "SUCCESS",
            "last_failure": None,
        },
        state_file_exists=True,
        now_ts=now,
        warn_hours=22.0,
    )
    assert active["status_label"] == "✅ 授权期内"
    assert active["hours_to_threshold"] == pytest.approx(17.0)
    assert "调度估算，不代表平台剩余寿命" in active["schedule_estimate"]

    # 场景 3: 达到 22 小时重登阈值
    aged = evaluate_wechat_session_status(
        auth_state={
            "authorized_at": now - 3600 * 22.5,  # 22.5 小时前
            "auth_method": "scan_qr",
            "last_verified_at": now - 3600,
            "last_keepalive_status": "SUCCESS",
        },
        state_file_exists=True,
        now_ts=now,
        warn_hours=22.0,
    )
    assert aged["status_label"] == "🟡 已达重登阈值"
    assert aged["threshold_reached"] is True
    assert "已达 22.0h 调度阈值" in aged["schedule_estimate"]

    # 场景 4: 最近保活网络超时（不判死会话，显示检查失败）
    timeout_eval = evaluate_wechat_session_status(
        auth_state={
            "authorized_at": now - 3600 * 10,
            "last_verified_at": now - 3600 * 2,
            "last_keepalive_status": "NETWORK_TIMEOUT",
            "last_failure": {"timestamp": now - 300, "error_type": "NETWORK_TIMEOUT", "detail": "timeout"},
        },
        state_file_exists=True,
        now_ts=now,
        warn_hours=22.0,
    )
    assert timeout_eval["status_label"] == "⚠️ 检查失败（网络超时）"
    assert "不影响现有会话" in timeout_eval["suggestions"][0]
    assert "NETWORK_TIMEOUT" in timeout_eval["last_failure_display"]

    # 场景 5: 明确 LOGIN_REQUIRED（确认为会话失效）
    expired = evaluate_wechat_session_status(
        auth_state={
            "authorized_at": now - 3600 * 10,
            "last_verified_at": now - 3600 * 2,
            "last_keepalive_status": "LOGIN_REQUIRED",
        },
        state_file_exists=True,
        now_ts=now,
    )
    assert expired["status_label"] == "❌ 会话已失效（需重新登录）"

    # 场景 6: 锁被占用
    locked = evaluate_wechat_session_status(
        auth_state={"authorized_at": now - 3600, "last_verified_at": now - 300},
        state_file_exists=True,
        lock_owner={"pid": 9999, "stage": "发布"},
        now_ts=now,
    )
    assert "占用中 (PID 9999 · 发布)" in locked["lock_status"]
