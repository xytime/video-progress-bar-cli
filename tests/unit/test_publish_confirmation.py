"""发布确认与防重复发布 (BUG-2 / #11) 单元测试

两部分：
1. classify_publish_result —— 上传器「提交响应」纯函数判定：列表跳转不再等同最终发布；
   公开视频必须另由作品管理页确认。
2. purge_stale_tasks —— PUBLISHING 不被自动重置回 PENDING（发布是对外不可逆动作，
   崩溃窗口自动重排队会导致重复公开发布）。

# Modification History
| Version | Date       | Author          | Description                          |
|---------|------------|-----------------|--------------------------------------|
| 1.0.0   | 2026-06-15 | Claude_Opus_4.8 | 初始创建：锁定 BUG-2 发布确认 + 防重复发布行为 |
| 1.1.0   | 2026-08-11 | Codex | 列表跳转降级为提交受理，锁定不得据此写公开视频成功 |
"""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'scripts'))

from wechat_uploader import classify_publish_result
from video_processing.db.database import PipelineDB


# ── 1. 发布确认判定（纯函数）──────────────────────────────────────────────
class TestClassifyPublishResult:
    def test_redirect_is_not_final_publish_success(self):
        assert classify_publish_result(True, "", draft=False) is False
        assert classify_publish_result(True, "任意内容", draft=True) is False

    def test_publish_success_text(self):
        assert classify_publish_result(False, "……发表成功……", draft=False) is True
        assert classify_publish_result(False, "发布成功", draft=False) is True

    def test_draft_success_text_does_not_confirm_publish(self):
        # 「保存草稿成功」不能被当作发表成功（旧 '成功' 子串判定的坑）
        assert classify_publish_result(False, "保存草稿成功", draft=False) is False

    def test_negative_marker_vetoes(self):
        assert classify_publish_result(False, "发表不成功，请重试", draft=False) is False

    def test_empty_or_unknown_is_unconfirmed(self):
        assert classify_publish_result(False, "", draft=False) is False
        assert classify_publish_result(False, "正在处理中…", draft=False) is False
        assert classify_publish_result(False, "内容审核中", draft=False) is False

    def test_draft_mode_positives(self):
        assert classify_publish_result(False, "保存草稿成功", draft=True) is True
        assert classify_publish_result(False, "保存成功", draft=True) is True
        # 发表文案不应确认草稿
        assert classify_publish_result(False, "发表成功", draft=True) is False


# ── 2. 防重复发布：purge 不重排队 PUBLISHING ───────────────────────────────
@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    yield path
    os.close(fd)
    if os.path.exists(path):
        os.unlink(path)


def _backdate(db, youtube_id, hours=3):
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE processed_videos SET updated_at = datetime('now', ?) WHERE youtube_id = ?",
            (f'-{hours} hours', youtube_id),
        )
        conn.commit()


class TestPurgeStaleDoesNotRequeuePublishing:
    def test_publishing_is_not_reset_to_pending(self, temp_db):
        db = PipelineDB(temp_db)
        db.add_video(youtube_id="pubvid12345", title="t", channel_id="c", score=90)
        db.update_video_status("pubvid12345", "PUBLISHING")
        _backdate(db, "pubvid12345", hours=3)

        db.purge_stale_tasks(stale_hours=2)

        v = db.get_video_by_youtube_id("pubvid12345")
        assert v["status"] == "PUBLISHING"  # 发布中绝不被自动重排队（防重复发布）

    def test_downloading_is_still_requeued(self, temp_db):
        # 反例：其它非终态仍应被正常清洗回 PENDING
        db = PipelineDB(temp_db)
        db.add_video(youtube_id="dlvid123456", title="t", channel_id="c", score=90)
        db.update_video_status("dlvid123456", "DOWNLOADING")
        _backdate(db, "dlvid123456", hours=3)

        db.purge_stale_tasks(stale_hours=2)

        v = db.get_video_by_youtube_id("dlvid123456")
        assert v["status"] == "PENDING"
