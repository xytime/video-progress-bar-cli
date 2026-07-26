"""审查 slice_index 透传 (BUG-1) 回归测试

用真实临时 SQLite（不 mock DB），只 stub 审查判定 check_text/check_channel_policy，
证明：切片命中违禁词时，FAILED/降权/放行标志都写到【切片自己的行】，
而【父行】保持原状（SEGMENTED + 原分数），不再被污染。

覆盖：
- P0 命中 → 切片 FAILED，父行仍 SEGMENTED
- P2 命中 → 切片 score=0 且 PENDING，父行 score/状态不变
- 频道策略命中 → 切片 FAILED，父行不变
- bypass 按 (youtube_id, slice_index) 粒度：放行某切片不影响父/其它切片
- 默认 slice_index=0 时仍作用于父行（向后兼容）

# Modification History
| Version | Date       | Author          | Description                                |
|---------|------------|-----------------|--------------------------------------------|
| 1.2.0   | 2026-07-26 | Codex           | 收紧 bypass 回归：人工放行和频道白名单均不能绕过 P0 红线 |
| 1.1.0   | 2026-07-26 | Codex           | 新增 censorship_incidents 台账写入回归，确保违规命中可复盘 |
| 1.0.0   | 2026-06-15 | Claude_Opus_4.8 | 初始创建：锁定 BUG-1 审查 slice_index 透传行为 |
"""

import os
import sys
import tempfile
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from video_processing.db.database import PipelineDB
from video_processing.pipeline_manager import PipelineManager
from video_processing import censor_engine
from config.settings import settings


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    yield path
    os.close(fd)
    if os.path.exists(path):
        os.unlink(path)


def _db_with_parent_and_slice(path):
    """父任务(slice_index=0, SEGMENTED, 90 分) + 一个切片(slice_index=1, DOWNLOADING, 90 分)。"""
    db = PipelineDB(path)
    db.add_video(youtube_id="vid12345678", title="Parent Video", channel_id="c1", score=90, slice_index=0)
    db.update_video_status("vid12345678", "SEGMENTED", slice_index=0)
    db.add_video(youtube_id="vid12345678", title="Slice One", channel_id="c1", score=90, slice_index=1)
    db.update_video_status("vid12345678", "DOWNLOADING", slice_index=1)
    return db


def _make_pm(db):
    """绕过重型 __init__，只装配 _check_censorship 需要的依赖。"""
    pm = PipelineManager.__new__(PipelineManager)
    pm.db = db
    pm.send_telegram_msg = lambda *a, **k: None
    return pm


def _enable(monkeypatch, *, censor=False, channel=False):
    monkeypatch.setattr(settings, "enable_censorship_engine", censor)
    monkeypatch.setattr(settings, "enable_channel_policy_filter", channel)
    monkeypatch.setattr(settings, "enable_blacklist_tombstone", False)


def test_p0_hit_on_slice_fails_slice_not_parent(temp_db, monkeypatch):
    db = _db_with_parent_and_slice(temp_db)
    _enable(monkeypatch, censor=True)
    hit = SimpleNamespace(hit=True, level="P0", tag="P0_POLITICAL", score=99,
                          action=censor_engine.ACTION_REJECT_SIGTERM, matched="iran", channel="en")
    monkeypatch.setattr(censor_engine, "check_text", lambda zh_text="", en_text="": hit)

    pm = _make_pm(db)
    assert pm._check_censorship("vid12345678", "Slice One", slice_index=1) is True

    parent = db.get_video_by_youtube_id("vid12345678", slice_index=0)
    sl = db.get_video_by_youtube_id("vid12345678", slice_index=1)
    assert sl["status"] == "FAILED"          # 切片自己被置 FAILED
    assert parent["status"] == "SEGMENTED"   # 父行不被污染（旧 BUG 会变 FAILED）
    incidents = db.get_censorship_incidents("vid12345678", slice_index=1)
    assert len(incidents) == 1
    assert incidents[0]["level"] == "P0"
    assert incidents[0]["matched"] == "iran"
    assert incidents[0]["decision"] == "REJECT_FAILED"
    assert incidents[0]["title"] == "Slice One"


def test_p2_deprioritizes_slice_not_parent(temp_db, monkeypatch):
    db = _db_with_parent_and_slice(temp_db)
    _enable(monkeypatch, censor=True)
    hit = SimpleNamespace(hit=True, tag="P2_COMMERCIAL", score=10,
                          action=censor_engine.ACTION_DEPRIORITIZE, matched="casino", channel="en")
    monkeypatch.setattr(censor_engine, "check_text", lambda zh_text="", en_text="": hit)

    pm = _make_pm(db)
    assert pm._check_censorship("vid12345678", "Slice One", slice_index=1) is True

    parent = db.get_video_by_youtube_id("vid12345678", slice_index=0)
    sl = db.get_video_by_youtube_id("vid12345678", slice_index=1)
    assert sl["status"] == "PENDING" and sl["score"] == 0   # 切片被降权
    assert parent["status"] == "SEGMENTED" and parent["score"] == 90  # 父分数/状态不变


def test_channel_policy_hit_on_slice_fails_slice_not_parent(temp_db, monkeypatch):
    db = _db_with_parent_and_slice(temp_db)
    _enable(monkeypatch, channel=True)
    monkeypatch.setattr(settings, "enable_channel_policy_fail_open", False)
    cp = SimpleNamespace(hit=True, tag="CP_OUT_OF_SCOPE", matched="ukraine+war", channel="en")
    monkeypatch.setattr(censor_engine, "check_channel_policy", lambda zh_text="", en_text="": cp)

    pm = _make_pm(db)
    assert pm._check_censorship("vid12345678", "Slice One", slice_index=1) is True

    parent = db.get_video_by_youtube_id("vid12345678", slice_index=0)
    sl = db.get_video_by_youtube_id("vid12345678", slice_index=1)
    assert sl["status"] == "FAILED"
    assert parent["status"] == "SEGMENTED"
    incidents = db.get_censorship_incidents("vid12345678", slice_index=1)
    assert incidents[0]["level"] == "CP"
    assert incidents[0]["matched"] == "ukraine+war"
    assert incidents[0]["decision"] == "CHANNEL_POLICY_REJECT"


def test_default_slice_index_zero_still_targets_parent(temp_db, monkeypatch):
    db = _db_with_parent_and_slice(temp_db)
    # 把父行设回 PENDING 模拟整片(非切片)审查
    db.update_video_status("vid12345678", "PENDING", slice_index=0)
    _enable(monkeypatch, censor=True)
    hit = SimpleNamespace(hit=True, tag="P0", score=99,
                          action=censor_engine.ACTION_REJECT_SIGTERM, matched="x", channel="en")
    monkeypatch.setattr(censor_engine, "check_text", lambda zh_text="", en_text="": hit)

    pm = _make_pm(db)
    assert pm._check_censorship("vid12345678", "Parent Video") is True  # 默认 slice_index=0

    parent = db.get_video_by_youtube_id("vid12345678", slice_index=0)
    sl = db.get_video_by_youtube_id("vid12345678", slice_index=1)
    assert parent["status"] == "FAILED"        # 整片路径仍作用于父行
    assert sl["status"] == "DOWNLOADING"       # 切片不受影响


class TestBypassIsPerSlice:
    def test_bypass_on_slice_does_not_leak_to_parent(self, temp_db):
        db = _db_with_parent_and_slice(temp_db)
        db.set_bypass_censorship("vid12345678", True, slice_index=1)
        assert db.is_censorship_bypassed("vid12345678", slice_index=1) is True
        assert db.is_censorship_bypassed("vid12345678", slice_index=0) is False

    def test_bypassed_slice_skips_censorship(self, temp_db, monkeypatch):
        db = _db_with_parent_and_slice(temp_db)
        db.set_bypass_censorship("vid12345678", True, slice_index=1)
        _enable(monkeypatch, censor=True)
        # 非 P0 命中仍可由人工复核放行，P0 另有单测锁死为不可绕过。
        hit = SimpleNamespace(hit=True, level="P1", tag="P1", score=75,
                              action=censor_engine.ACTION_SUSPEND_MANUAL, matched="x", channel="en")
        monkeypatch.setattr(censor_engine, "check_text", lambda zh_text="", en_text="": hit)
        pm = _make_pm(db)

        assert pm._check_censorship("vid12345678", "Slice One", slice_index=1) is False  # 切片放行
        # 父行（未放行）仍会被拦截
        assert pm._check_censorship("vid12345678", "Parent", slice_index=0) is True

    def test_manual_bypass_does_not_skip_p0_redline(self, temp_db, monkeypatch):
        db = _db_with_parent_and_slice(temp_db)
        db.set_bypass_censorship("vid12345678", True, slice_index=1)
        _enable(monkeypatch, censor=True)
        hit = SimpleNamespace(hit=True, level="P0", tag="P0", score=99,
                              action=censor_engine.ACTION_REJECT_SIGTERM,
                              matched="xi jinping", channel="en")
        monkeypatch.setattr(censor_engine, "check_text", lambda zh_text="", en_text="": hit)
        pm = _make_pm(db)

        assert pm._check_censorship("vid12345678", "Slice One", slice_index=1) is True
        assert db.get_video_by_youtube_id("vid12345678", slice_index=1)["status"] == "FAILED"

    def test_channel_bypass_does_not_skip_p0_redline(self, temp_db, monkeypatch):
        db = _db_with_parent_and_slice(temp_db)
        _enable(monkeypatch, censor=True, channel=True)
        monkeypatch.setattr(settings, "censorship_bypass_channels", "c1")
        hit = SimpleNamespace(hit=True, level="P0", tag="P0", score=99,
                              action=censor_engine.ACTION_REJECT_SIGTERM,
                              matched="anti_china_targeted_violence", channel="en")
        monkeypatch.setattr(censor_engine, "check_text", lambda zh_text="", en_text="": hit)
        pm = _make_pm(db)

        assert pm._check_censorship("vid12345678", "Slice One", slice_index=1) is True
        assert db.get_video_by_youtube_id("vid12345678", slice_index=1)["status"] == "FAILED"
