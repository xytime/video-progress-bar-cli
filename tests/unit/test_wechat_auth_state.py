"""Unit tests for WeChat structured auth state management (wechat_auth_state.py).

# Modification History
| Version | Date       | Author      | Description                              |
|---------|------------|-------------|------------------------------------------|
| 1.2.0   | 2026-09-28 | Antigravity | 测试完整文件名派生、身份核验拒绝、未来时间异常、保活失败时序覆盖与排期持久化 |
| 1.1.0   | 2026-09-28 | Antigravity | 升级至 1.1.0 契约：测试唯一派生、无伪造保活、脱敏白名单、非绿异常判定及无标记已验证会话 |
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
    record_wechat_auth_attempt,
    record_wechat_keepalive_result,
    record_wechat_keepalive_schedule,
)


def test_canonical_path_derivation_unique(tmp_path: Path):
    """验证元数据路径严格按完整文件名派生，wechat.json 与 wechat_state.json 绝不冲突。"""
    state_file = tmp_path / "wechat_state.json"
    derived = canonical_wechat_auth_state_path(state_file)
    assert derived.name == "wechat_state.json.auth_state.json"
    assert derived.parent == tmp_path

    other_state = tmp_path / "wechat.json"
    other_derived = canonical_wechat_auth_state_path(other_state)
    assert other_derived.name == "wechat.json.auth_state.json"
    assert derived != other_derived

    custom_state = tmp_path / "custom.tmp"
    assert canonical_wechat_auth_state_path(custom_state).name == "custom.tmp.auth_state.json"


def test_custom_state_does_not_pollute_production_markers(tmp_path: Path):
    """验证自定义/测试 state 路径绝不污染或清空生产 legacy marker 和 flags。"""
    custom_state = tmp_path / "test_state.json"
    started_flag = tmp_path / "wechat_auto_relogin_started.flag"
    warned_flag = tmp_path / "wechat_login_warned.flag"
    legacy_file = tmp_path / "wechat_login_at.txt"

    started_flag.write_text("1")
    warned_flag.write_text("1")

    record_wechat_authorization(custom_state, method="desktop_quick", timestamp=1720000000.0)

    # 自定义路径不会写入同级 wechat_login_at.txt，也不会误删同级 flags
    assert not legacy_file.exists()
    assert started_flag.exists()
    assert warned_flag.exists()


def test_custom_directory_same_filename_wechat_state_not_treated_as_production(tmp_path: Path):
    """同名不同目录的 wechat_state.json 绝不能被误判为生产会话目标，不得污染同目录 marker 或 flags。"""
    from video_processing.core.wechat_auth_state import is_wechat_state_target
    from config.settings import settings

    # 1. 验证 is_wechat_state_target 路径判据：同名但位于自定义目录拒绝
    custom_state = tmp_path / "wechat_state.json"
    assert is_wechat_state_target(custom_state) is False

    prod_state = settings.project_root / "output" / "wechat_state.json"
    assert is_wechat_state_target(prod_state) is True
    assert is_wechat_state_target("output/wechat_state.json") is True

    # 2. 授权写入隔离验证：同名自定义 state 绝不生成 legacy marker 或删除 flags
    started_flag = tmp_path / "wechat_auto_relogin_started.flag"
    warned_flag = tmp_path / "wechat_login_warned.flag"
    legacy_file = tmp_path / "wechat_login_at.txt"

    started_flag.write_text("1")
    warned_flag.write_text("1")

    record_wechat_authorization(custom_state, method="desktop_quick", timestamp=1720000000.0)

    assert not legacy_file.exists()
    assert started_flag.exists()
    assert warned_flag.exists()


def test_read_rejects_missing_or_mismatched_canonical_identity(tmp_path: Path):
    """验证读取时严格校验 canonical_state_path 身份，缺失或不匹配的元数据拒绝通过。"""
    state_file = tmp_path / "custom_state.json"
    auth_meta = canonical_wechat_auth_state_path(state_file)

    # 1. 缺失 canonical_state_path 身份
    auth_meta.write_text(json.dumps({
        "version": AUTH_STATE_VERSION,
        "authorized_at": 1720000000.0,
        "auth_method": "auto",
        "last_verified_at": 1720000000.0,
    }), encoding="utf-8")

    state_data = read_wechat_auth_state(state_file)
    assert state_data["authorized_at"] is None
    assert state_data["last_verified_at"] is None

    # 2. 身份与请求路径不匹配（冒充）
    auth_meta.write_text(json.dumps({
        "version": AUTH_STATE_VERSION,
        "canonical_state_path": "/other/path/wechat_state.json",
        "authorized_at": 1720000000.0,
        "auth_method": "auto",
        "last_verified_at": 1720000000.0,
    }), encoding="utf-8")

    state_data2 = read_wechat_auth_state(state_file)
    assert state_data2["authorized_at"] is None
    assert state_data2["last_verified_at"] is None


def test_record_wechat_authorization_does_not_forge_keepalive(tmp_path: Path):
    """验证记录授权成功事件只更新授权与最近验证时间，绝不伪造保活记录。"""
    state_file = tmp_path / "wechat_state.json"
    t0 = 1720000000.0
    rec = record_wechat_authorization(state_file, method="desktop_quick", timestamp=t0)

    assert rec["version"] == AUTH_STATE_VERSION
    assert rec["authorized_at"] == t0
    assert rec["auth_method"] == "desktop_quick"
    assert rec["last_verified_at"] == t0
    assert rec["last_keepalive_at"] is None  # 严禁伪造保活时间
    assert rec["last_keepalive_status"] is None  # 严禁伪造保活状态
    assert rec["last_failure"] is None


def test_keepalive_sanitizes_failure_and_preserves_authorized_at(tmp_path: Path):
    """验证保活失败时使用固定白名单分类与脱敏摘要，绝不暴露 URL 参数或自由文本。"""
    state_file = tmp_path / "wechat_state.json"
    t_auth = 1720000000.0
    record_wechat_authorization(state_file, method="scan_qr", timestamp=t_auth)

    t_keepalive = t_auth + 3600.0
    ka_rec = record_wechat_keepalive_result(state_file, status="SUCCESS", timestamp=t_keepalive)
    assert ka_rec["authorized_at"] == t_auth
    assert ka_rec["last_verified_at"] == t_keepalive
    assert ka_rec["last_keepalive_at"] == t_keepalive
    assert ka_rec["last_keepalive_status"] == "SUCCESS"

    # 失败记录：含敏感 query 的 URL 与非白名单字段
    t_fail = t_keepalive + 1800.0
    fail_rec = record_wechat_keepalive_result(
        state_file,
        status="NETWORK_TIMEOUT",
        failure={
            "stage": "navigation",
            "error_type": "NETWORK_TIMEOUT",
            "detail": "https://channels.weixin.qq.com/platform/post/create?token=secret123&uid=999\nTraceback...",
            "secret_token": "leak_me",
        },
        timestamp=t_fail,
    )

    assert fail_rec["authorized_at"] == t_auth
    assert fail_rec["last_verified_at"] == t_keepalive  # 保持上次成功时间
    assert fail_rec["last_keepalive_status"] == "NETWORK_TIMEOUT"
    assert fail_rec["last_failure"]["error_type"] == "NETWORK_TIMEOUT"
    # 固定分类脱敏摘要
    assert fail_rec["last_failure"]["summary"] == "网络请求超时未响应"
    assert "token" not in fail_rec["last_failure"]["summary"]
    assert "secret_token" not in fail_rec["last_failure"]


def test_fresh_authorization_supersedes_historical_keepalive_failure(tmp_path: Path):
    """回归验证：真实授权成功后，更新的验证时间应覆盖旧的保活失败，不再误报失败。"""
    state_file = tmp_path / "wechat_state.json"
    t1 = 1720000000.0

    # 1. 历史保活检测到 LOGIN_REQUIRED
    record_wechat_keepalive_result(
        state_file,
        status="LOGIN_REQUIRED",
        failure={"stage": "auth", "error_type": "LOGIN_REQUIRED"},
        timestamp=t1,
    )

    eval_before = evaluate_wechat_session_status(
        auth_state=read_wechat_auth_state(state_file),
        state_file_exists=True,
        now_ts=t1 + 60,
    )
    assert eval_before["status_label"] == "❌ 会话已失效（需重新登录）"

    # 2. 用户通过重新授权成功，更新 authorized_at 与 last_verified_at
    t2 = t1 + 300.0
    record_wechat_authorization(state_file, method="scan_qr", timestamp=t2)

    # 3. 评定：授权成功后，旧保活被判定为 superseded，会话转为健康绿色
    eval_after = evaluate_wechat_session_status(
        auth_state=read_wechat_auth_state(state_file),
        state_file_exists=True,
        now_ts=t2 + 60,
        warn_hours=22.0,
    )
    assert eval_after["is_keepalive_superseded"] is True
    assert eval_after["status_label"] == "✅ 授权且已验证"
    assert eval_after["last_keepalive_status"] == "LOGIN_REQUIRED"  # 历史保留不擦除

    # 4. 后续新的保活如果在 t3 再次失败，则应重新生效
    t3 = t2 + 3600.0
    record_wechat_keepalive_result(
        state_file,
        status="LOGIN_REQUIRED",
        failure={"stage": "auth", "error_type": "LOGIN_REQUIRED"},
        timestamp=t3,
    )
    eval_t3 = evaluate_wechat_session_status(
        auth_state=read_wechat_auth_state(state_file),
        state_file_exists=True,
        now_ts=t3 + 60,
    )
    assert eval_t3["is_keepalive_superseded"] is False
    assert eval_t3["status_label"] == "❌ 会话已失效（需重新登录）"


def test_future_timestamp_rejected_as_anomaly():
    """验证未来时间戳绝不能 clamp age=0 后报绿色，必须显式报错。"""
    now = 1720000000.0
    future_auth = evaluate_wechat_session_status(
        auth_state={
            "authorized_at": now + 3600.0,  # 未来 1 小时
            "last_verified_at": now - 100,
            "last_keepalive_status": "SUCCESS",
        },
        state_file_exists=True,
        now_ts=now,
    )
    assert future_auth["status_label"] == "❌ 时间戳异常（未来时间戳）"
    assert "时间戳异常" in future_auth["relative_age"]


def test_keepalive_schedule_persistence(tmp_path: Path):
    """验证下一次检查实际随机选定时间的持久化与评定展示。"""
    state_file = tmp_path / "wechat_state.json"
    now = 1720000000.0
    record_wechat_authorization(state_file, method="auto", timestamp=now - 3600)

    target_schedule = now + 1800.0  # 30 分钟后
    record_wechat_keepalive_schedule(state_file, scheduled_at=target_schedule)

    read_state = read_wechat_auth_state(state_file)
    assert read_state["next_keepalive_scheduled_at"] == target_schedule

    evaluated = evaluate_wechat_session_status(
        auth_state=read_state,
        state_file_exists=True,
        now_ts=now,
        enable_keepalive=True,
    )
    assert "实际计划时刻" in evaluated["next_keepalive_estimate"]


def test_evaluate_wechat_session_status_rigorous_scenarios():
    now = 1720000000.0

    # 场景 1: 未经验证的会话（即使有授权 marker，也绝不能报绿）
    unverified = evaluate_wechat_session_status(
        auth_state={"authorized_at": now - 3600, "last_verified_at": None},
        state_file_exists=True,
        now_ts=now,
    )
    assert unverified["status_label"] == "⚠️ 未经验证（待保活验证）"

    # 场景 2: 验证已陈旧（超过 4 小时未成功保活，绝不能报绿）
    stale_ver = evaluate_wechat_session_status(
        auth_state={
            "authorized_at": now - 3600 * 10,
            "last_verified_at": now - 3600 * 5,  # 5 小时前验证
            "last_keepalive_at": now - 3600 * 5,
            "last_keepalive_status": "SUCCESS",
        },
        state_file_exists=True,
        now_ts=now,
    )
    assert stale_ver["status_label"] == "⚠️ 验证已陈旧（超期未验证）"

    # 场景 3: 非官方域名重定向（INVALID_ORIGIN 绝不能报绿）
    wrong_origin = evaluate_wechat_session_status(
        auth_state={
            "authorized_at": now - 3600,
            "last_verified_at": now - 1800,
            "last_keepalive_at": now - 100,
            "last_keepalive_status": "INVALID_ORIGIN",
        },
        state_file_exists=True,
        now_ts=now,
    )
    assert wrong_origin["status_label"] == "❌ 来源异常（非官方域名）"

    # 场景 4: 无授权 marker 但已验证会话（不能武断报未授权）
    verified_no_marker = evaluate_wechat_session_status(
        auth_state={
            "authorized_at": None,
            "last_verified_at": now - 600,
            "last_keepalive_at": now - 600,
            "last_keepalive_status": "SUCCESS",
        },
        state_file_exists=True,
        now_ts=now,
    )
    assert verified_no_marker["status_label"] == "🟡 会话已验证（授权时间未知）"

    # 场景 5: UNKNOWN 状态必须保留并降级
    unknown_eval = evaluate_wechat_session_status(
        auth_state={
            "authorized_at": now - 3600,
            "last_verified_at": now - 1800,
            "last_keepalive_at": now - 300,
            "last_keepalive_status": "UNKNOWN",
        },
        state_file_exists=True,
        now_ts=now,
    )
    assert unknown_eval["status_label"] == "⚠️ 状态未知（检查未分类）"

    # 场景 6: 网络超时判定（不能声称不影响会话）
    timeout_eval = evaluate_wechat_session_status(
        auth_state={
            "authorized_at": now - 3600 * 10,
            "last_verified_at": now - 3600 * 2,
            "last_keepalive_at": now - 300,
            "last_keepalive_status": "NETWORK_TIMEOUT",
            "last_failure": {"timestamp": now - 300, "error_type": "NETWORK_TIMEOUT", "summary": "网络请求超时未响应"},
        },
        state_file_exists=True,
        now_ts=now,
    )
    assert timeout_eval["status_label"] == "⚠️ 检查失败（网络超时）"
    assert "不影响现有会话" not in "".join(timeout_eval["suggestions"])
    assert "平台真实状态未知" in timeout_eval["suggestions"][0]

    # 场景 7: 正常授权且近期已验证（绿色）
    normal_active = evaluate_wechat_session_status(
        auth_state={
            "authorized_at": now - 3600 * 5,
            "last_verified_at": now - 1800,
            "last_keepalive_at": now - 1800,
            "last_keepalive_status": "SUCCESS",
        },
        state_file_exists=True,
        now_ts=now,
        warn_hours=22.0,
        enable_auto_relogin=True,
    )
    assert normal_active["status_label"] == "✅ 授权且已验证"
    assert "计划重登" in normal_active["schedule_estimate"]

    # 场景 8: 调度开关禁用时的提示
    disabled_auto = evaluate_wechat_session_status(
        auth_state={
            "authorized_at": now - 3600 * 23,
            "last_verified_at": now - 600,
            "last_keepalive_at": now - 600,
            "last_keepalive_status": "SUCCESS",
        },
        state_file_exists=True,
        now_ts=now,
        enable_auto_relogin=False,
    )
    assert "自动重登未开启" in disabled_auto["schedule_estimate"]


def test_auth_attempt_tracking_and_failure_display(tmp_path: Path):
    """验证记录授权尝试（涵盖成功与失败），失败可查分类原因并结构化展示。"""
    state_file = tmp_path / "wechat_state.json"
    now = 1720000000.0

    # 1. 尝试失败
    record_wechat_auth_attempt(
        state_file,
        method="desktop_quick",
        success=False,
        reason="PAGE_UNREADY",
        timestamp=now,
    )

    data = read_wechat_auth_state(state_file)
    assert data["last_auth_attempt_at"] == now
    assert data["last_auth_attempt_method"] == "desktop_quick"
    assert data["last_auth_attempt_status"] == "FAILED"
    assert data["last_auth_attempt_reason"] == "PAGE_UNREADY"

    evaluated = evaluate_wechat_session_status(data, state_file_exists=True, now_ts=now + 60)
    assert evaluated["last_auth_attempt_display"] is not None
    assert "授权尝试失败" in evaluated["last_auth_attempt_display"]
    assert "正向视频发布控件未就绪" in evaluated["last_auth_attempt_display"]

    # 2. 尝试成功（通过 record_wechat_authorization 同步更新）
    t_succ = now + 300.0
    record_wechat_authorization(state_file, method="scan_qr", timestamp=t_succ)
    data_succ = read_wechat_auth_state(state_file)
    assert data_succ["last_auth_attempt_at"] == t_succ
    assert data_succ["last_auth_attempt_status"] == "SUCCESS"
    assert data_succ["last_auth_attempt_reason"] is None

    eval_succ = evaluate_wechat_session_status(data_succ, state_file_exists=True, now_ts=t_succ + 60)
    assert "授权尝试成功" in eval_succ["last_auth_attempt_display"]


def test_auto_relogin_started_copy_does_not_claim_active_process():
    """验证 auto_relogin_started 为 True 时，提示近期已触发，不把 flag 误作活跃进程。"""
    res = evaluate_wechat_session_status(
        auth_state={},
        state_file_exists=True,
        enable_auto_relogin=True,
        auto_relogin_started=True,
    )
    assert res["schedule_estimate"] == "自动重登近期已触发，结果以最近授权记录为准"


def test_official_wechat_frame_origin_contract():
    """验证官方授权 frame 严格拒绝携带 userinfo 或非默认端口。"""
    from video_processing.core.wechat_page_contract import is_official_wechat_frame_origin
    from scripts.wechat_uploader import _trusted_wechat_login_frame
    from unittest.mock import MagicMock

    # 1. 允许合法的官方源
    assert is_official_wechat_frame_origin("https://open.weixin.qq.com/connect/login") is True
    assert is_official_wechat_frame_origin("https://channels.weixin.qq.com/platform/login") is True

    # 2. 拒绝带有 userinfo 或非默认端口
    assert is_official_wechat_frame_origin("https://admin:secret@open.weixin.qq.com/connect/login") is False
    assert is_official_wechat_frame_origin("https://open.weixin.qq.com:8443/connect/login") is False
    assert is_official_wechat_frame_origin("http://open.weixin.qq.com/connect/login") is False
    assert is_official_wechat_frame_origin("https://evil.com/connect/login") is False

    # 3. _trusted_wechat_login_frame 判据与零点击
    frame_bad_port = MagicMock()
    frame_bad_port.url = "https://open.weixin.qq.com:8443/connect/login"
    assert _trusted_wechat_login_frame(frame_bad_port) is False

    frame_userinfo = MagicMock()
    frame_userinfo.url = "https://user:pwd@open.weixin.qq.com/connect/login"
    assert _trusted_wechat_login_frame(frame_userinfo) is False

    from scripts.wechat_uploader import _click_visible_frame_button
    fake_page = MagicMock()
    fake_page.frames = [frame_bad_port, frame_userinfo]
    # 零点击：不点击任何按钮，直接返回 False
    clicked = _click_visible_frame_button(fake_page, "允许")
    assert clicked is False


