"""P2 商业合规预警 × 手动评分锁 的交互测试 + 'gamble' 误杀回归守护。

覆盖 2026-06-25 修复：
- 手动锁定(is_manually_scored=1)视频命中 P2 → 挂起人工复核(FAILED)，分数保留，不 force 清零回弹；
- 非锁定视频命中 P2 → 维持原 deprioritize（score=0, PENDING）；
- 描述里的英文隐喻 'gamble'（豪赌）不再误命中 P2（已从词表移除 gamble/betting）；
- PipelineDB.is_manually_scored 取数语义。

用真实临时 PipelineDB，不打桩（遵守 mock-gate≤3 约束）。

# Modification History
| Version | Date       | Author          | Description                                  |
|---------|------------|-----------------|----------------------------------------------|
| 1.0.0   | 2026-06-25 | Claude_Opus_4.8 | 新增：P2×手动锁挂起、非锁定降权、gamble 回归、is_manually_scored |
"""
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from video_processing.db.database import PipelineDB
from video_processing.pipeline_manager import PipelineManager
from config.settings import settings


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    yield path
    os.close(fd)
    if os.path.exists(path):
        os.unlink(path)


def _db_with_one_video(path, *, status="COPYWRITING"):
    db = PipelineDB(path)
    db.add_video(youtube_id="vidp2", title="Daily Tech Update", channel_id="c1", score=90, slice_index=0)
    db.update_video_status("vidp2", status, slice_index=0)
    return db


def _make_pm(db):
    pm = PipelineManager.__new__(PipelineManager)
    pm.db = db
    pm.send_telegram_msg = lambda *a, **k: None
    return pm


def _enable_censor(monkeypatch):
    monkeypatch.setattr(settings, "enable_censorship_engine", True)
    monkeypatch.setattr(settings, "enable_channel_policy_filter", False)
    monkeypatch.setattr(settings, "enable_blacklist_tombstone", False)


# ── 1. 非锁定视频命中 P2 → 原 deprioritize（score=0, PENDING）────────────────

def test_p2_unlocked_video_deprioritized_to_zero(temp_db, monkeypatch):
    db = _db_with_one_video(temp_db)
    _enable_censor(monkeypatch)
    pm = _make_pm(db)

    # 标题含 P2 词 "get rich quick" → ACTION_DEPRIORITIZE
    assert pm._check_censorship("vidp2", "Get rich quick scheme exposed") is True
    row = db.get_video_by_youtube_id("vidp2", slice_index=0)
    assert row["status"] == "PENDING"
    assert row["score"] == 0


# ── 2. 手动锁定视频命中 P2 → 挂起人工复核(FAILED)，分数保留 ───────────────────

def test_p2_manually_scored_video_suspended_not_zeroed(temp_db, monkeypatch):
    db = _db_with_one_video(temp_db)
    _enable_censor(monkeypatch)
    pm = _make_pm(db)

    # 人工调分加锁：score=80, is_manually_scored=1
    db.update_video_score("vidp2", 80, force=True)
    assert db.is_manually_scored("vidp2") is True

    # 标题含 P2 词 + HTML 特殊字符（顺带验证 notify 的 html.escape 不抛错）
    assert pm._check_censorship("vidp2", "Get rich quick & <fast> riches") is True

    row = db.get_video_by_youtube_id("vidp2", slice_index=0)
    assert row["status"] == "FAILED"          # 挂起人工复核
    assert row["score"] == 80                  # 分数保留，未被 force 清零
    assert row["is_manually_scored"] == 1      # 手动锁仍在


# ── 3. 'gamble'（财经隐喻）不再误命中 P2 —— 原始 bug 回归守护 ────────────────

def test_gamble_metaphor_no_longer_triggers_p2(temp_db, monkeypatch):
    db = _db_with_one_video(temp_db)
    _enable_censor(monkeypatch)
    pm = _make_pm(db)

    # 复刻事故描述：'The $400 billion AI infrastructure gamble'
    assert pm._check_censorship(
        "vidp2",
        "Wall Street FINALLY QUESTIONS The AI BOOM",
        description="The $400 billion AI infrastructure gamble is a risky bet on AI.",
    ) is False
    row = db.get_video_by_youtube_id("vidp2", slice_index=0)
    assert row["status"] == "COPYWRITING"      # 未被改动
    assert row["score"] == 90


def test_real_gambling_still_triggers_p2(temp_db, monkeypatch):
    """对照组：真正的 'gambling' 仍应命中 P2，证明只精准移除了隐喻词。"""
    db = _db_with_one_video(temp_db)
    _enable_censor(monkeypatch)
    pm = _make_pm(db)

    assert pm._check_censorship("vidp2", "Best online gambling sites review") is True


# ── 4. PipelineDB.is_manually_scored 取数语义 ────────────────────────────────

def test_is_manually_scored_semantics(temp_db):
    db = PipelineDB(temp_db)
    db.add_video(youtube_id="vidlock", title="t", channel_id="c1", score=10, slice_index=0)

    assert db.is_manually_scored("vidlock") is False        # 默认未锁
    assert db.is_manually_scored("nonexistent") is False     # 不存在 → False

    db.update_video_score("vidlock", 88, force=True)         # 加锁
    assert db.is_manually_scored("vidlock") is True

    # 自动算分（force=False）不应改变锁状态，且被 DB 层跳过
    db.update_video_score("vidlock", 50, force=False)
    assert db.is_manually_scored("vidlock") is True
    assert db.get_video_by_youtube_id("vidlock", slice_index=0)["score"] == 88
