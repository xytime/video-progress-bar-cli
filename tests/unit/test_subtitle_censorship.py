"""字幕正文审查 (红蓝审计 症结 8) 回归测试

锁定 v3.19.0 的设计契约：

1. read_subtitle_text 单一真相源：从 .ass 读出去标签纯文本（含切片前缀隔离）。
2. 字幕正文并入【违法层 P0/P1/P2】：转录里出现真实违禁词（如 "falun gong"）→ 拦截。
   —— 这正是 症结 8 要堵的洞：标题/文案干净但语音内容敏感。
3. 字幕正文【刻意不并入 CP 共现层】：转录里出现 "ukraine … war" 这类
   「国名+冲突词」共现 *不* 拦截（否则数万字转录几乎必然误杀）；
   但同一文本若出现在 title/description，CP 仍照常拦截（证明词表本身有效，
   只有字幕通道被有意绕开）。

用真实临时 SQLite + 真实 censor_engine（不 stub 判定），证明端到端词匹配真的生效。

# Modification History
| Version | Date       | Author          | Description                                  |
|---------|------------|-----------------|----------------------------------------------|
| 1.0.0   | 2026-06-22 | Claude_Opus_4.8 | 初始创建：锁定 症结 8 字幕审查 + CP 绕开契约 |
"""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from video_processing.db.database import PipelineDB
from video_processing.pipeline_manager import PipelineManager
from video_processing.utils.file_utils import read_subtitle_text
from config.settings import settings


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    yield path
    os.close(fd)
    if os.path.exists(path):
        os.unlink(path)


def _db_with_one_video(path):
    db = PipelineDB(path)
    db.add_video(youtube_id="vidsubtitle1", title="Daily Tech Update", channel_id="c1", score=90, slice_index=0)
    db.update_video_status("vidsubtitle1", "TRANSCRIBING", slice_index=0)
    return db


def _make_pm(db):
    pm = PipelineManager.__new__(PipelineManager)
    pm.db = db
    pm.send_telegram_msg = lambda *a, **k: None
    return pm


def _enable(monkeypatch, *, censor=False, channel=False):
    monkeypatch.setattr(settings, "enable_censorship_engine", censor)
    monkeypatch.setattr(settings, "enable_channel_policy_filter", channel)
    monkeypatch.setattr(settings, "enable_blacklist_tombstone", False)


# ── 1. read_subtitle_text 单一真相源 ─────────────────────────────────────────

def test_read_subtitle_text_extracts_plaintext(tmp_path):
    pysubs2 = pytest.importorskip("pysubs2")
    subs = pysubs2.SSAFile()
    subs.append(pysubs2.SSAEvent(start=0, end=1000, text="hello world"))
    subs.append(pysubs2.SSAEvent(start=1000, end=2000, text="你好世界"))
    subs.save(str(tmp_path / "vidabc.ass"))

    text = read_subtitle_text(tmp_path, "vidabc")
    assert "hello world" in text
    assert "你好世界" in text


def test_read_subtitle_text_slice_prefix_isolation(tmp_path):
    pysubs2 = pytest.importorskip("pysubs2")
    # 父片字幕
    parent = pysubs2.SSAFile()
    parent.append(pysubs2.SSAEvent(start=0, end=1000, text="parent body"))
    parent.save(str(tmp_path / "vidabc.ass"))
    # 切片 1 字幕
    s1 = pysubs2.SSAFile()
    s1.append(pysubs2.SSAEvent(start=0, end=1000, text="slice one body"))
    s1.save(str(tmp_path / "vidabc_s1.ass"))

    s1_text = read_subtitle_text(tmp_path, "vidabc", slice_index=1)
    assert "slice one body" in s1_text
    assert "parent body" not in s1_text  # 切片不应读到父片字幕


def test_read_subtitle_text_missing_returns_empty(tmp_path):
    assert read_subtitle_text(tmp_path, "doesnotexist") == ""


def test_read_subtitle_text_parent_excludes_child_slices(tmp_path):
    """[Review Fix] 整片(slice 0) 不得读到子切片 {yid}_s*.ass，否则会把切片内容并入父片审查。"""
    pysubs2 = pytest.importorskip("pysubs2")
    for name, body in [("vidabc.ass", "parent only"),
                       ("vidabc_s1.ass", "child slice one"),
                       ("vidabc_s2.ass", "child slice two")]:
        f = pysubs2.SSAFile(); f.append(pysubs2.SSAEvent(start=0, end=1000, text=body))
        f.save(str(tmp_path / name))
    parent = read_subtitle_text(tmp_path, "vidabc", slice_index=0)
    assert "parent only" in parent
    assert "child slice" not in parent


def test_read_subtitle_text_slice_no_prefix_collision(tmp_path):
    """[Review Fix] 切片 1 的匹配不得误吞 {yid}_s11.ass（glob `_s1*` 前缀碰撞）。"""
    pysubs2 = pytest.importorskip("pysubs2")
    for name, body in [("vidabc_s1.ass", "slice one body"),
                       ("vidabc_s11.ass", "slice eleven body")]:
        f = pysubs2.SSAFile(); f.append(pysubs2.SSAEvent(start=0, end=1000, text=body))
        f.save(str(tmp_path / name))
    s1 = read_subtitle_text(tmp_path, "vidabc", slice_index=1)
    assert "slice one body" in s1
    assert "eleven" not in s1


# ── 2. 字幕正文并入违法层 P0/P1/P2（真实词匹配）──────────────────────────────

def test_subtitle_p0_word_is_blocked(temp_db, monkeypatch):
    """标题干净，但转录字幕含 P0 违禁词 → 拦截并置 FAILED（症结 8 核心修复）。"""
    db = _db_with_one_video(temp_db)
    _enable(monkeypatch, censor=True)
    pm = _make_pm(db)

    dirty_subtitle = "Today we discuss the history of falun gong and its followers."
    assert pm._check_censorship("vidsubtitle1", "Daily Tech Update",
                                subtitle_text=dirty_subtitle) is True
    assert db.get_video_by_youtube_id("vidsubtitle1", slice_index=0)["status"] == "FAILED"


def test_clean_subtitle_passes(temp_db, monkeypatch):
    """标题与字幕都干净 → 放行（无误杀）。"""
    db = _db_with_one_video(temp_db)
    _enable(monkeypatch, censor=True)
    pm = _make_pm(db)

    clean_subtitle = "Today we review the latest laptop and its battery life."
    assert pm._check_censorship("vidsubtitle1", "Daily Tech Update",
                                subtitle_text=clean_subtitle) is False
    assert db.get_video_by_youtube_id("vidsubtitle1", slice_index=0)["status"] == "TRANSCRIBING"


def test_empty_subtitle_is_noop(temp_db, monkeypatch):
    """subtitle_text 为空（开关关闭时的退化路径）→ 行为与旧版一致。"""
    db = _db_with_one_video(temp_db)
    _enable(monkeypatch, censor=True)
    pm = _make_pm(db)
    assert pm._check_censorship("vidsubtitle1", "Daily Tech Update", subtitle_text="") is False


# ── 3. 字幕正文刻意绕开 CP 共现层（防长转录误杀）──────────────────────────────

def test_subtitle_does_not_trigger_channel_policy(temp_db, monkeypatch):
    """转录含 'ukraine … war' 共现，但字幕不喂给 CP → 放行（关键设计契约）。"""
    db = _db_with_one_video(temp_db)
    _enable(monkeypatch, channel=True)  # 仅开 CP 层
    pm = _make_pm(db)

    geo_subtitle = "The startup expanded to ukraine before the price war in the chip market."
    assert pm._check_censorship("vidsubtitle1", "Chip Market Update",
                                subtitle_text=geo_subtitle) is False
    assert db.get_video_by_youtube_id("vidsubtitle1", slice_index=0)["status"] == "TRANSCRIBING"


def test_channel_policy_still_fires_on_title_control(temp_db, monkeypatch):
    """对照组：同样的 'ukraine+war' 共现出现在 description 时，CP 照常拦截，
    证明词表有效、仅字幕通道被有意绕开（而非词表失灵）。"""
    db = _db_with_one_video(temp_db)
    _enable(monkeypatch, channel=True)
    pm = _make_pm(db)

    assert pm._check_censorship("vidsubtitle1", "ukraine war coverage",
                                description="full report on the ukraine war") is True
    assert db.get_video_by_youtube_id("vidsubtitle1", slice_index=0)["status"] == "FAILED"
