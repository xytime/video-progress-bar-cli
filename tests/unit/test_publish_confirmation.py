"""发布确认与防重复发布 (BUG-2 / #11) 单元测试

两部分：
1. classify_publish_result —— 上传器「提交响应」纯函数判定：列表跳转不再等同最终发布；
   公开视频必须另由作品管理页确认。
2. purge_stale_tasks —— PUBLISHING 不被自动重置回 PENDING（发布是对外不可逆动作，
   崩溃窗口自动重排队会导致重复公开发布）。

# Modification History
| Version | Date       | Author          | Description                          |
|---------|------------|-----------------|--------------------------------------|
| 1.4.0   | 2026-08-21 | Codex | 提交后异常路径读取账本保护，禁止降级为可自动重传状态 |
| 1.0.0   | 2026-06-15 | Claude_Opus_4.8 | 初始创建：锁定 BUG-2 发布确认 + 防重复发布行为 |
| 1.1.0   | 2026-08-11 | Codex | 列表跳转降级为提交受理，锁定不得据此写公开视频成功 |
| 1.3.0   | 2026-08-20 | Codex | 覆盖同会话前后平台 ID 差分绑定，拒绝标题截断、多候选和无平台 ID 的回查 |
| 1.2.0   | 2026-08-20 | Codex | 覆盖作品管理页的已发布、审核中、驳回和不可判定映射 |
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'scripts'))

from wechat_uploader import (
    MANAGEMENT_PUBLISHED,
    MANAGEMENT_REJECTED,
    MANAGEMENT_UNCERTAIN,
    MANAGEMENT_UNDER_REVIEW,
    classify_management_publication,
    classify_publish_result,
    resolve_submission_platform_identity,
    run_uploader,
)
from video_processing.db.database import PipelineDB
from video_processing.pipeline_manager import PipelineManager


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


class TestClassifyManagementPublication:
    def test_explicit_published_status(self):
        assert classify_management_publication("作品状态：已发布") == MANAGEMENT_PUBLISHED

    def test_review_and_rejection_are_distinct(self):
        assert classify_management_publication("当前状态：审核中") == MANAGEMENT_UNDER_REVIEW
        assert classify_management_publication("审核未通过，请修改后重试") == MANAGEMENT_REJECTED

    def test_unknown_management_text_stays_uncertain(self):
        assert classify_management_publication("作品详情") == MANAGEMENT_UNCERTAIN


class TestExactSubmissionIdentity:
    def test_unique_platform_id_delta_with_full_title_binds(self):
        before = {"old-post": {"platform_post_id": "old-post", "card_text": "历史作品"}}
        after = {
            **before,
            "new-post": {
                "platform_post_id": "new-post",
                "platform_url": "https://example.test/post/new-post",
                "card_text": "本次唯一完整标题\n审核中",
            },
        }

        receipt = resolve_submission_platform_identity(before, after, "本次唯一完整标题")

        assert receipt and receipt["platform_post_id"] == "new-post"
        assert receipt["matched_by"].startswith("same_session_before_after")

    @pytest.mark.parametrize(
        "after",
        [
            {"new-post": {"platform_post_id": "new-post", "card_text": "标题被截断..."}},
            {
                "new-post-a": {"platform_post_id": "new-post-a", "card_text": "本次唯一完整标题"},
                "new-post-b": {"platform_post_id": "new-post-b", "card_text": "本次唯一完整标题"},
            },
        ],
    )
    def test_ambiguous_or_incomplete_platform_evidence_stays_unbound(self, after):
        assert resolve_submission_platform_identity({}, after, "本次唯一完整标题") is None

    def test_title_based_verify_command_without_platform_id_is_rejected_before_browser(self, tmp_path):
        assert run_uploader(
            state_path=str(tmp_path / "wechat_state.json"),
            verify_only=True,
        ) == 1

    def test_title_substring_in_another_title_cannot_bind_platform_id(self):
        after = {
            "new-post": {
                "platform_post_id": "new-post",
                "card_text": "本次唯一完整标题的续集\n审核中",
            },
        }

        assert resolve_submission_platform_identity({}, after, "本次唯一完整标题") is None


def test_submission_ledger_prevents_post_submit_exception_downgrade(temp_db):
    db = PipelineDB(temp_db)
    assert db.add_video("post-submit-guard", "title", "channel", score=80)
    db.update_video_status("post-submit-guard", "SUBMITTED_UNBOUND")
    db.record_wechat_publication_confirmation(
        "post-submit-guard", evidence_path=None, state="SUBMITTED_UNBOUND",
        error_message="submission accepted",
    )

    manager = PipelineManager(db_path=temp_db)

    assert manager._has_wechat_submission_terminal_state("post-submit-guard") is True


def test_unknown_upload_result_is_terminal_uncertain_not_submitted(temp_db):
    db = PipelineDB(temp_db)
    assert db.add_video("unknown-submit", "title", "channel", score=80)
    manager = PipelineManager(db_path=temp_db)
    manager._OUT_DIR = Path(tempfile.mkdtemp())

    manager._mark_wechat_submission_under_review(
        "unknown-submit", "unknown-submit", evidence_path=None,
        reason="upload timed out", submission_confirmed=False,
    )

    assert db.get_video_by_youtube_id("unknown-submit")["status"] == "UNCERTAIN"
    assert db.get_wechat_publication("unknown-submit")["state"] == "UNCERTAIN"


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
