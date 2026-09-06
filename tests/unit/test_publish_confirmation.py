"""发布确认与防重复发布 (BUG-2 / #11) 单元测试

两部分：
1. classify_publish_result —— 上传器「提交响应」纯函数判定：列表跳转不再等同最终发布；
   公开视频必须另由作品管理页确认。
2. purge_stale_tasks —— PUBLISHING 不被自动重置回 PENDING（发布是对外不可逆动作，
   崩溃窗口自动重排队会导致重复公开发布）。

# Modification History
| Version | Date       | Author          | Description                          |
|---------|------------|-----------------|--------------------------------------|
| 1.11.0 | 2026-09-07 | Codex | 覆盖接口正文与页面状态隔离，以及失败通知保留末尾异常。 |
| 1.8.0   | 2026-08-27 | Codex | 覆盖作品管理原生 post_list 的唯一新增 objectId 绑定，避免长描述与短标题不一致漏绑。 |
| 1.9.0   | 2026-08-31 | Codex | 覆盖管理卡片标题/正文中的普通“不可见”等词不得伪造平台审核驳回。 |
| 1.10.0  | 2026-08-31 | Codex | 覆盖管理状态仅接受独立状态行或具名状态标签，正文中的发布/审核词保持未判定。 |
| 1.7.0   | 2026-08-27 | Codex | 锁定作品管理页 networkidle 超时后仍按路由和卡片证据读取。 |
| 1.6.0   | 2026-08-27 | Codex | 覆盖新标签页作品管理基线失败时的同页回退与创建页恢复。 |
| 1.5.0   | 2026-08-27 | Codex | 覆盖提交后作品管理卡片异步加载时的同会话原生 ID 轮询绑定 |
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
    capture_submission_identity_baseline,
    _collect_management_cards_from_post_list_payload,
    _load_management_cards,
    resolve_submission_platform_identity,
    resolve_submission_platform_identity_after_publish,
    run_uploader,
    verify_management_publication_by_id,
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


@pytest.mark.parametrize("reason, expected", [
    ("INFO request started\n" * 30 + "Traceback (most recent call last):\nValueError: title contract blocked <invalid>\n", "ValueError: title contract blocked &lt;invalid&gt;"),
    ("download failed <403>", "download failed &lt;403&gt;"),
    ("   \n", ""),
], ids=["traceback-after-info", "single-line", "whitespace"])
def test_failure_notification_keeps_terminal_error_instead_of_info_prefix(reason, expected):
    from types import SimpleNamespace
    messages = []
    manager = SimpleNamespace(send_telegram_msg=messages.append)
    PipelineManager._notify_failed(manager, "test-video", "测试标题", reason)
    assert expected in messages[0]
    assert "INFO request started" not in messages[0]


class TestClassifyManagementPublication:
    @pytest.mark.parametrize("description", ["已发布", "审核未通过", "审核中"])
    def test_api_description_is_never_publication_status(self, monkeypatch, tmp_path, description):
        cards = _collect_management_cards_from_post_list_payload({
            "data": {"list": [{"objectId": "native-post", "desc": description, "status": 0}]},
        })
        monkeypatch.setattr("wechat_uploader._load_management_cards", lambda _: (cards, True))
        monkeypatch.setattr("wechat_uploader._capture_wechat_evidence", lambda *_: None)
        state, _ = verify_management_publication_by_id(object(), tmp_path, "native-post")
        assert state == MANAGEMENT_UNCERTAIN
        import json
        evidence = json.loads((tmp_path / "management_readback.json").read_text())
        assert evidence["platform_status"] == "0"
        assert evidence["reason"] == "API_STATUS_UNMAPPED"

    def test_api_card_does_not_replace_same_id_dom_status(self, monkeypatch, tmp_path):
        from types import SimpleNamespace

        class Page:
            url = "https://channels.weixin.qq.com/platform/post/list"

            def on(self, _event, callback):
                self.callback = callback

            def remove_listener(self, *_args):
                pass

            def goto(self, *_args, **_kwargs):
                self.callback(SimpleNamespace(
                    url="https://channels.weixin.qq.com/cgi-bin/mmfinderassistant-bin/post/post_list",
                    json=lambda: {"data": {"list": [{"objectId": "native-post", "desc": "普通正文", "status": 3}]}},
                ))

            def wait_for_load_state(self, *_args, **_kwargs):
                pass

            def wait_for_timeout(self, *_args):
                pass

        monkeypatch.setattr("wechat_uploader._collect_management_cards", lambda _: {
            "native-post": {"platform_post_id": "native-post", "card_text": "普通正文\n作品状态：审核中", "platform_url": "https://example.test/post/native-post"},
        })
        monkeypatch.setattr("wechat_uploader._capture_wechat_evidence", lambda *_: None)
        state, url = verify_management_publication_by_id(Page(), tmp_path, "native-post")
        assert state == MANAGEMENT_UNDER_REVIEW
        assert url == "https://example.test/post/native-post"

    def test_explicit_published_status(self):
        assert classify_management_publication("作品状态：已发布") == MANAGEMENT_PUBLISHED

    def test_review_and_rejection_are_distinct(self):
        assert classify_management_publication("当前状态：审核中") == MANAGEMENT_UNDER_REVIEW
        assert classify_management_publication("审核未通过，请修改后重试") == MANAGEMENT_REJECTED

    def test_content_words_do_not_override_an_explicit_review_state(self):
        card = "英语世界｜新望远镜如何看见不可见的宇宙？\n当前状态：审核中"
        assert classify_management_publication(card) == MANAGEMENT_UNDER_REVIEW

    def test_content_words_without_a_status_line_stay_uncertain(self):
        card = "一篇讨论已发布内容为何仍在审核中的科普正文"
        assert classify_management_publication(card) == MANAGEMENT_UNCERTAIN

    def test_wrapped_original_review_status_is_recognized(self):
        assert classify_management_publication("标题\n原创审核\n中") == MANAGEMENT_UNDER_REVIEW

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

    def test_unique_post_list_object_id_delta_binds_without_short_title_in_long_description(self):
        after = {
            "new-post": {
                "platform_post_id": "new-post",
                "card_text": "这是一篇不会包含投稿短标题的完整长描述",
                "identity_source": "post_list_api",
            },
        }

        receipt = resolve_submission_platform_identity({}, after, "本次唯一完整标题")

        assert receipt and receipt["platform_post_id"] == "new-post"
        assert receipt["matched_by"] == "same_session_before_after_unique_post_list_object_id_delta"

    def test_post_list_payload_exposes_only_native_object_ids(self):
        cards = _collect_management_cards_from_post_list_payload({
            "data": {
                "list": [
                    {"objectId": "native-post-1", "desc": "完整描述", "status": 3},
                    {"desc": "没有原生 ID，必须忽略"},
                ],
            },
        })

        assert cards == {
            "native-post-1": {
                "platform_post_id": "native-post-1",
                "platform_url": "",
                "card_text": "完整描述",
                "identity_source": "post_list_api",
                "platform_status": "3",
            },
        }

    def test_post_submit_identity_waits_for_async_management_card(self, monkeypatch):
        before = {"old-post": {"platform_post_id": "old-post", "card_text": "历史作品"}}
        delayed_cards = iter([{
            **before,
            "new-post": {
                "platform_post_id": "new-post",
                "platform_url": "https://example.test/post/new-post",
                "card_text": "本次唯一完整标题\n审核中",
            },
        }])

        class Page:
            def __init__(self):
                self.waits = []

            def wait_for_timeout(self, milliseconds):
                self.waits.append(milliseconds)

        page = Page()
        monkeypatch.setattr("wechat_uploader._load_management_cards", lambda _page: (before, True))
        monkeypatch.setattr("wechat_uploader._collect_management_cards", lambda _page: next(delayed_cards))

        receipt = resolve_submission_platform_identity_after_publish(
            page, before, "本次唯一完整标题", attempts=2, retry_delay_ms=1,
        )

        assert receipt and receipt["platform_post_id"] == "new-post"
        assert page.waits == [1]

    def test_baseline_falls_back_to_same_page_and_restores_create_page(self, monkeypatch):
        baseline = {"old-post": {"platform_post_id": "old-post", "card_text": "历史作品"}}

        class SecondaryPage:
            closed = False

            def close(self):
                self.closed = True

        class Context:
            def __init__(self):
                self.secondary = SecondaryPage()

            def new_page(self):
                return self.secondary

        class PrimaryPage:
            def __init__(self):
                self.url = "https://channels.weixin.qq.com/platform/post/create"
                self.goto_urls = []

            def goto(self, url, **_kwargs):
                self.goto_urls.append(url)
                self.url = url

            def wait_for_load_state(self, *_args, **_kwargs):
                return None

            def wait_for_timeout(self, *_args, **_kwargs):
                return None

        context = Context()
        page = PrimaryPage()
        monkeypatch.setattr(
            "wechat_uploader._load_management_cards",
            lambda candidate: (baseline, candidate is page),
        )

        actual, ready = capture_submission_identity_baseline(context, page)

        assert ready is True
        assert actual == baseline
        assert context.secondary.closed is True
        assert page.goto_urls == ["https://channels.weixin.qq.com/platform/post/create"]

    def test_management_cards_remain_usable_after_networkidle_timeout(self, monkeypatch):
        expected_cards = {"post-1": {"platform_post_id": "post-1", "card_text": "审核中"}}

        class Page:
            url = "https://channels.weixin.qq.com/platform/post/list"

            def goto(self, _url, **_kwargs):
                return None

            def wait_for_load_state(self, *_args, **_kwargs):
                raise RuntimeError("persistent websocket prevents network idle")

            def wait_for_timeout(self, *_args, **_kwargs):
                return None

        monkeypatch.setattr("wechat_uploader._collect_management_cards", lambda _page: expected_cards)

        actual, ready = _load_management_cards(Page())

        assert ready is True
        assert actual == expected_cards

    def test_bound_id_readback_retries_once_before_staying_uncertain(self, monkeypatch, tmp_path):
        waits = []

        class Page:
            def wait_for_timeout(self, milliseconds):
                waits.append(milliseconds)

        delayed_cards = iter([
            ({}, False),
            ({"native-post": {
                "platform_post_id": "native-post",
                "platform_url": "https://example.test/post/native-post",
                "card_text": "审核中",
            }}, True),
        ])
        monkeypatch.setattr("wechat_uploader._load_management_cards", lambda _page: next(delayed_cards))
        monkeypatch.setattr("wechat_uploader._capture_wechat_evidence", lambda *_args: None)

        state, platform_url = verify_management_publication_by_id(
            Page(), tmp_path, "native-post",
        )

        assert state == MANAGEMENT_UNDER_REVIEW
        assert platform_url == "https://example.test/post/native-post"
        assert len(waits) == 1


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
