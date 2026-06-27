"""WeChat 会话临期预警（无痛重登 §五#1 deliverable）单测。

覆盖 wechat_keepalive 的会话龄追踪 + 临期预警：
- 年轻会话不预警；
- 龄超阈值预警一次，本登录周期不重复；
- 过期重置 + 重扫后重新计时（age 归零）。

Telegram 发送被 stub，不发真消息（mock 1 个 + monkeypatch 1 个，满足 mock-gate≤3）。

# Modification History
| Version | Date       | Author          | Description                          |
|---------|------------|-----------------|--------------------------------------|
| 1.0.0   | 2026-06-27 | Claude_Opus_4.8 | 新增：会话龄追踪/临期预警/重置重计时 |
"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

keepalive = pytest.importorskip("wechat_keepalive")  # 跳过：无 playwright 环境


@pytest.fixture
def captured(monkeypatch):
    msgs = []
    monkeypatch.setattr(keepalive, "_send_telegram", lambda html: msgs.append(html))
    monkeypatch.setattr(keepalive.settings, "wechat_session_warn_hours", 22.0)
    return msgs


def test_stamp_then_young_session_no_warn(tmp_path, captured):
    login_at = tmp_path / "login_at.txt"
    warned = tmp_path / "warned.flag"
    keepalive._stamp_login_if_absent(login_at)
    assert login_at.exists()
    keepalive._maybe_warn_expiry(login_at, warned)
    assert captured == [] and not warned.exists()


def test_aged_session_warns_once(tmp_path, captured):
    login_at = tmp_path / "login_at.txt"
    warned = tmp_path / "warned.flag"
    login_at.write_text(str(int(time.time()) - int(23 * 3600)))  # 23h 前登录
    keepalive._maybe_warn_expiry(login_at, warned)
    assert len(captured) == 1 and warned.exists()
    # 同一登录周期再次巡检不应重复预警
    keepalive._maybe_warn_expiry(login_at, warned)
    assert len(captured) == 1


def test_reset_on_expiry_then_rescan_retimes(tmp_path, captured):
    login_at = tmp_path / "login_at.txt"
    warned = tmp_path / "warned.flag"
    login_at.write_text(str(int(time.time()) - int(23 * 3600)))
    warned.write_text("1")
    keepalive._reset_login_markers(login_at, warned)
    assert not login_at.exists() and not warned.exists()
    # 重扫后重新计时 → 年轻会话 → 不预警
    keepalive._stamp_login_if_absent(login_at)
    keepalive._maybe_warn_expiry(login_at, warned)
    assert captured == []


def test_stamp_does_not_reset_existing_age(tmp_path, captured):
    """看门狗刷新（active 但 marker 已存在）不得重置会话龄。"""
    login_at = tmp_path / "login_at.txt"
    old = str(int(time.time()) - int(10 * 3600))
    login_at.write_text(old)
    keepalive._stamp_login_if_absent(login_at)  # 已存在 → 不动
    assert login_at.read_text() == old
