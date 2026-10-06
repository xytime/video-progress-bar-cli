"""真实卡片结构与限制回账的回归测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-06 | Codex | 拒绝跨卡片与歧义匹配；平台限制不释放已提交额度。 |
"""
from pathlib import Path

import pytest

from video_processing.core.douyin_management_state import get_management_publication_state
from video_processing.db.database import PipelineDB
from video_processing.english_world.package_integrity import calculate_package_hashes


TITLE = "专家探讨人工智能失控风险与威胁"
COPY = "随着人工智能不断自我学习与进化，其潜在的安全隐患引发了广泛关注。"


@pytest.mark.parametrize("label,state", [
    ("不适宜公开", "REJECTED"), ("不通过", "REJECTED"),
    ("流量减少", "RESTRICTED"), ("已发布", "PUBLISHED"), ("审核中", "UNDER_REVIEW"),
])
def test_card_without_permissions_menu(label, state):
    card = TITLE + COPY + " 编辑作品 作品置顶 删除作品 2026年09月29日 07:55 " + label
    other = "其他作品 编辑作品 设置权限 2026年09月29日 07:56 已发布"
    assert get_management_publication_state(card + other, COPY, TITLE) == state


def test_unknown_state_does_not_borrow_next_card_status():
    card = TITLE + COPY + " 编辑作品 作品置顶 删除作品 2026年09月29日 07:55 未知状态"
    other = "其他作品 编辑作品 设置权限 2026年09月29日 07:56 已发布"
    assert get_management_publication_state(card + other, COPY, TITLE) is None


def test_two_matching_cards_remain_ambiguous_even_with_same_state():
    card = TITLE + COPY + " 编辑作品 设置权限 2026年09月29日 07:55 已发布"
    assert get_management_publication_state(card + card, COPY, TITLE) is None


def test_restricted_generic_submission_keeps_daily_quota_and_cannot_requeue(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    for index in (1, 2):
        db.add_video(f"source-{index}", TITLE, "channel", score=80)
        db.create_douyin_publication(f"source-{index}", str(index) * 64, f"/tmp/{index}.mp4", source_kind="NEW")
    first = db.claim_next_douyin_publication("NEW", daily_limit=1)
    db.update_douyin_publication_state(first["id"], "BANNED", error_message="不适宜公开，禁止重传")
    assert db.claim_next_douyin_publication("NEW", daily_limit=1) is None
    with pytest.raises(ValueError):
        db.requeue_canceled_douyin_publication(first["id"])


@pytest.mark.parametrize("observed", ["REJECTED", "RESTRICTED"])
def test_english_negative_result_preserves_accepted_attempt_and_shared_limit(tmp_path: Path, observed):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    paths = {}
    for field in ("mp4", "manifest", "title", "copy", "cover", "cover_provenance"):
        path = tmp_path / f"{field}.bin"
        path.write_text(field)
        paths[f"{field}_path"] = str(path)
    item = db.create_english_world_review_item(title=TITLE, **paths, **calculate_package_hashes(paths))
    db.approve_english_world_submission(item["id"], authorization="AUTO_POLICY")
    wechat = db.claim_english_world_submission(item["id"], evidence_dir="/wechat")
    db.complete_english_world_submission(
        item["id"], state="UNDER_REVIEW", uploader_exit_code=6, evidence_dir="/wechat",
        attempt_id=wechat["_attempt_id"], platform_post_id="export/native",
    )
    db.ensure_english_world_douyin_publication(item["id"])
    dy = db.claim_english_world_douyin_publication(item["id"], daily_limit=1, evidence_dir="/douyin")
    db.complete_english_world_douyin_publication(
        item["id"], attempt_id=dy["_attempt_id"], state="UNDER_REVIEW",
        uploader_exit_code=6, evidence_dir="/douyin", message="已受理",
    )
    updated = db.record_english_world_douyin_reconciliation(
        item["id"], platform_state=observed, evidence_dir="/readback", message="平台限制，禁止重传",
    )
    assert updated["state"] == "CANCELED"
    assert updated["platform_state"] == observed
    assert updated["reconciliation_failures"] == 0
    assert db.list_english_world_douyin_attempts(item["id"])[0]["state"] == "UNDER_REVIEW"
    assert db.claim_english_world_douyin_publication(item["id"], daily_limit=20, evidence_dir="/retry") is None
    db.add_video("generic-new", TITLE, "channel", score=80)
    db.create_douyin_publication("generic-new", "f" * 64, "/tmp/next.mp4", source_kind="NEW")
    assert db.claim_next_douyin_publication("NEW", daily_limit=1) is None
