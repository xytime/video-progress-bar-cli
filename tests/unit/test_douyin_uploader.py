"""抖音创作者中心上传器的登录、控件校准与 fail-closed 测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.5.46 | 2026-09-04 | Codex | 覆盖发布前闸门与发布后不确定退出码的状态边界。 |
| 1.5.47 | 2026-09-04 | Codex | 覆盖内容管理页精确标题检索的只读回查路径。 |
| 1.5.48 | 2026-09-04 | Codex | 覆盖含话题的原文填写不点击平台候选，防止候选扩写文案。 |
| 1.5.49 | 2026-09-04 | Codex | 覆盖末尾同源话题的平台限定词扩写，标题或正文改写继续拒绝。 |
| 1.5.50 | 2026-09-04 | Codex | 覆盖横竖封面各自保存闭窗的次序和双封面缺失的封面阶段阻断。 |
| 1.5.51 | 2026-09-04 | Codex | 覆盖保存后卡槽缩略图必须切换，弹窗关闭不能作为封面落库证据。 |
| 1.5.52 | 2026-09-04 | Codex | 覆盖新上传封面候选图必须在当前弹窗内选中，不误点发布页预览。 |
| 1.5.53 | 2026-09-04 | Codex | 覆盖竖封面保存后返回主页面时，横封面必须从 4:3 卡槽重新打开。 |
| 1.5.56 | 2026-09-04 | Codex | 覆盖横封面保存后平台要求设置竖封面时，必须重入同一编辑器而非选择暂不设置。 |
| 1.5.54 | 2026-09-04 | Codex | 覆盖横封面保存后的竖封面建议层必须精确以“暂不设置”收口。 |
| 1.5.55 | 2026-09-04 | Codex | 覆盖平台快速检测单侧横/竖封面缺失必须阻断最终发布。 |
| 1.5.57 | 2026-09-04 | Codex | 覆盖空投稿页的标题/发布静态表单不得被误认作视频上传完成。 |
| 1.5.58 | 2026-09-04 | Codex | 覆盖封面卡槽点击异常后已实际打开编辑器的结果态回读。 |
| 1.5.59 | 2026-09-04 | Codex | 覆盖竖封面保存后同一编辑器内的横封面推荐切换。 |
| 1.5.60 | 2026-09-04 | Codex | 覆盖上传完成后固定预览说明中的“已上传”不触发动态进度。 |
| 1.5.61 | 2026-09-04 | Codex | 覆盖封面成功态与异步遗留缺失提示并存时优先采用成功态。 |
| 1.0.0 | 2026-07-23 | Codex | 覆盖抖音登录判定、唯一上传控件、上传校准与未校准发布保护 |
| 1.1.0 | 2026-07-23 | Codex | 覆盖上传校准期间页面关闭的未确认返回 |
| 1.2.0 | 2026-07-29 | Codex | 覆盖抖音自主声明选择、确认与失败阻断发布 |
| 1.3.0 | 2026-07-29 | Codex | 覆盖上传固定提示与真实进度区分、作品管理发布成功吐司识别 |
| 1.3.1 | 2026-07-29 | Codex | 覆盖抖音允许发布的预览转码提示不阻塞最终提交 |
| 1.3.2 | 2026-07-29 | Codex | 覆盖标题、文案和封面回读确认，防止元信息未落地时提交 |
| 1.3.3 | 2026-07-29 | Codex | 覆盖抖音编辑器插入零宽字符时的正文回读兼容 |
| 1.3.4 | 2026-07-29 | Codex | 覆盖封面检测完成、失败和超时均按 fail-closed 处理 |
| 1.3.5 | 2026-07-29 | Codex | 覆盖自主声明可见唯一控件的 Playwright 点击路径 |
| 1.3.6 | 2026-07-29 | Codex | 覆盖最终发布点击后未确认与发布前闸门失败的退出码区分 |
| 1.3.7 | 2026-07-29 | Codex | 覆盖自主声明弹窗单选项及确定按钮的完整确认流程 |
| 1.3.8 | 2026-08-08 | Codex | 覆盖作品管理页须精确匹配正文指纹后才读取本作品的发布状态 |
| 1.3.9 | 2026-08-24 | Codex | 覆盖封面完成按钮不可用时 fail-closed，且正常路径必须确认编辑器已关闭。 |
| 1.3.11 | 2026-08-30 | Codex | 覆盖含话题文案填充后关闭标签建议浮层，避免遮挡封面入口。 |
| 1.3.10 | 2026-08-30 | Codex | 覆盖作品列表标题回查、真实加载等待、原表单不算提交回执及最终按钮单次点击 |
| 1.3.12 | 2026-08-31 | Codex | 覆盖独立横封面传入与快速检测风险提示的提交前阻断。 |
| 1.3.13 | 2026-08-31 | Codex | 覆盖无 modal 类名时封面保存后的整页回退，避免错误调用 page.is_visible。 |
| 1.3.14 | 2026-08-31 | Codex | 覆盖横封面推荐弹窗必须先确认关闭，且竖封面阶段不得提前等待“完成”。 |
| 1.3.15 | 2026-08-31 | Codex | 覆盖封面图片仅通过当前 input 直接注入，禁止回退打开 Finder。 |
| 1.3.16 | 2026-08-31 | Codex | 覆盖最终提交前预检通过仅生成证据，绝不触发发布按钮。 |
| 1.3.17 | 2026-08-31 | Codex | 覆盖快速检测“检测中”不能被当作通过，必须等待至终态。 |
| 1.3.18 | 2026-08-31 | Codex | 固化封面确认拒绝无文本通用主按钮，避免误触非保存动作。 |
| 1.3.19 | 2026-08-31 | Codex | 覆盖检测服务拥堵的精确例外，且任何并存的封面风险仍阻断提交。 |
| 1.3.20 | 2026-09-02 | Codex | 覆盖底层上传器在启动浏览器前复核持久 UI 熔断，恢复校准只允许非最终提交的显式证据采集。 |
| 1.3.21 | 2026-09-02 | Codex | 覆盖管理页熔断期间最终提交必须显式标识 NEW，阻断 HISTORY/未知来源穿透低层守卫。 |
| 1.3.22 | 2026-09-02 | Codex | 覆盖管理页熔断下仅接受数据库签发的一次性投稿启动凭据，拒绝来源参数伪造、历史预检和重放。 |
| 1.3.23 | 2026-09-02 | Codex | 覆盖无凭据旧进程、默认快照和普通校准均不能绕过活动 UI 熔断。 |
| 1.3.24 | 2026-09-02 | Codex | 保留管理页熔断下无上传动作的登录恢复，避免 NEW 领取因过期会话被永久封死。 |
| 1.3.25 | 2026-09-02 | Codex | 覆盖缺失封面在 Playwright 启动前停止，避免无意义投稿页动作。 |
"""

import json
import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from video_processing.core.douyin_launch_context import douyin_submission_payload_sha256
from scripts.douyin_uploader import (
    _search_management_title,
    DOUYIN_DESCRIPTION_SELECTOR,
    DOUYIN_SELF_DECLARATION_OPTION_TEXT,
    DOUYIN_TITLE_SELECTOR,
    DOUYIN_VIDEO_INPUT_SELECTOR,
    EXIT_FAILED,
    EXIT_NOT_CALIBRATED,
    EXIT_UNDER_REVIEW,
    EXIT_SUBMISSION_UNCONFIRMED,
    _guard_before_browser,
    _click_cover_entry,
    _click_cover_confirm,
    _select_new_cover_candidate,
    _wait_for_cover_slot_source_change,
    apply_cover,
    fill_publish_fields,
    final_metadata_matches,
    get_description_editor,
    get_management_publication_state,
    get_publish_button,
    get_title_input,
    get_video_upload_input,
    has_active_upload_progress,
    has_post_upload_form,
    is_login_required,
    is_upload_in_progress,
    main,
    prepare_douyin_cover_upload_file,
    prepare_douyin_horizontal_cover_upload_file,
    publish_after_review,
    quick_detection_allows_submission,
    select_self_declaration,
    submission_preflight_allows_publish,
    upload_for_calibration,
    upload_and_publish,
    wait_for_management_content,
    wait_for_upload_completion,
    wait_for_publish_submission,
    wait_for_cover_validation,
    wait_for_video_upload_input,
)


def _raw_uploader_args(*, tmp_path: Path, verify_only: bool = False) -> SimpleNamespace:
    """构造仅供 main() 守卫测试的完整命令参数，避免调用真实浏览器。"""
    copy_file = tmp_path / "copy.txt"
    copy_file.write_text("用于精确回查的足够长文案", encoding="utf-8")
    return SimpleNamespace(
        video=None,
        cover=None,
        horizontal_cover=None,
        copy=copy_file,
        title_file=None,
        state=tmp_path / "douyin_state.json",
        evidence_dir=None,
        no_headless=False,
        fail_fast_login=True,
        login_only=False,
        calibrate=False,
        calibrate_after_upload=False,
        upload_wait_seconds=900,
        prepare_description=False,
        preflight_only=False,
        publish=False,
        verify_only=verify_only,
        douyin_launch_ticket_id=None,
        douyin_launch_token=None,
        operator_recovery_stage=None,
        operator_recovery_reason=None,
    )


def test_raw_uploader_verify_guard_stops_before_playwright(tmp_path: Path):
    """低层脚本不能仅靠调用方约定；管理熔断时必须在 Chromium 前返回。"""
    args = _raw_uploader_args(tmp_path=tmp_path, verify_only=True)
    with patch("scripts.douyin_uploader.parse_args", return_value=args), patch(
        "scripts.douyin_uploader._read_active_persistent_douyin_ui_failure_stages",
        return_value={"management_verify"},
    ), patch("scripts.douyin_uploader.sync_playwright") as playwright:
        assert main() == EXIT_NOT_CALIBRATED

    playwright.assert_not_called()


def test_raw_uploader_missing_cover_stops_before_playwright(tmp_path: Path):
    """直接调用也必须在浏览器前验证必需封面，不能依赖页面内失败。"""
    args = _raw_uploader_args(tmp_path=tmp_path)
    video = tmp_path / "video.mp4"
    title = tmp_path / "title.txt"
    video.write_bytes(b"video")
    title.write_text("标题", encoding="utf-8")
    args.video = video
    args.title_file = title
    args.cover = tmp_path / "missing-cover.jpg"
    args.publish = True
    with patch("scripts.douyin_uploader.parse_args", return_value=args), patch(
        "scripts.douyin_uploader.sync_playwright"
    ) as playwright:
        assert main() == EXIT_FAILED

    playwright.assert_not_called()


def test_raw_uploader_publish_always_requires_a_ticket_even_without_an_active_fuse(
    tmp_path: Path,
):
    """熔断为空不能把低层 CLI 退回为可匿名最终投稿的旁路。"""
    args = _raw_uploader_args(tmp_path=tmp_path)
    video = tmp_path / "ticketless.mp4"
    title = tmp_path / "title.txt"
    cover = tmp_path / "cover.jpg"
    video.write_bytes(b"ticketless-video")
    title.write_text("无凭据投稿", encoding="utf-8")
    cover.write_bytes(b"cover")
    args.video = video
    args.title_file = title
    args.cover = cover
    args.publish = True
    db = MagicMock()
    db.get_platform_ui_failure_streaks.return_value = []

    assert _guard_before_browser(args, db=db) == EXIT_NOT_CALIBRATED
    db.begin_douyin_browser_launch.assert_not_called()


def test_raw_uploader_guard_keeps_management_failure_out_of_new_submission(tmp_path: Path):
    """管理页熔断仍不应误停独立投稿前闸门保护的新稿。"""
    video = tmp_path / "new-submission.mp4"
    video.write_bytes(b"new-submission")
    copy = tmp_path / "copy.txt"
    title = tmp_path / "title.txt"
    cover = tmp_path / "cover.jpg"
    for path, content in ((copy, b"copy"), (title, b"title"), (cover, b"cover")):
        path.write_bytes(content)
    args = SimpleNamespace(
        video=video,
        copy=copy,
        title_file=title,
        cover=cover,
        horizontal_cover=None,
        publish=True,
        preflight_only=False,
        calibrate_after_upload=False,
        verify_only=False,
        douyin_launch_ticket_id="ticket-1",
        douyin_launch_token="launch-token-1",
        operator_recovery_stage=None,
        operator_recovery_reason=None,
        evidence_dir=None,
    )
    db = MagicMock()
    db.get_platform_ui_failure_streaks.return_value = [{
        "stage": "management_verify", "active": 1, "consecutive_failures": 99,
    }]
    db.begin_douyin_browser_launch.return_value = True
    payload = douyin_submission_payload_sha256(
        video_path=video, copy_path=copy, title_path=title, cover_path=cover,
    )
    assert payload

    assert _guard_before_browser(args, db=db) is None
    db.begin_douyin_browser_launch.assert_called_once_with(
        "ticket-1",
        "launch-token-1",
            video_path=str(video.resolve()),
            asset_sha256=hashlib.sha256(video.read_bytes()).hexdigest(),
            payload_sha256=payload,
            require_new_source=True,
    )
    # 即使外部调用者仍偷偷附带已废弃的 source_kind=NEW，也不能替代账本凭据。
    args.source_kind = "NEW"
    db.begin_douyin_browser_launch.return_value = False
    assert _guard_before_browser(args, db=db) == EXIT_NOT_CALIBRATED


def test_raw_uploader_management_guard_rejects_history_preflight_without_ticket(tmp_path: Path):
    """管理页熔断必须同时阻断 HISTORY 的上传式预检，不能只挡最终按钮。"""
    video = tmp_path / "history.mp4"
    video.write_bytes(b"history")
    args = SimpleNamespace(
        video=video,
        publish=False,
        preflight_only=True,
        calibrate_after_upload=False,
        verify_only=False,
        douyin_launch_ticket_id=None,
        douyin_launch_token=None,
        operator_recovery_stage=None,
        operator_recovery_reason=None,
        evidence_dir=None,
    )
    db = MagicMock()
    db.get_platform_ui_failure_streaks.return_value = [{
        "stage": "management_verify", "active": 1, "consecutive_failures": 99,
    }]
    assert _guard_before_browser(args, db=db) == EXIT_NOT_CALIBRATED
    db.begin_douyin_browser_launch.assert_not_called()


def test_raw_uploader_management_guard_rejects_ticketless_old_publish(tmp_path: Path):
    """遗留的 NEW+UPLOADING 行不等于可信投稿包，不能成为无限期发布桥。"""
    args = _raw_uploader_args(tmp_path=tmp_path)
    video = tmp_path / "old-new.mp4"
    title = tmp_path / "old-title.txt"
    cover = tmp_path / "old-cover.jpg"
    video.write_bytes(b"old-new")
    title.write_text("旧父进程标题", encoding="utf-8")
    cover.write_bytes(b"old-cover")
    args.video = video
    args.title_file = title
    args.cover = cover
    args.publish = True
    args.source_kind = "NEW"  # 已废弃参数即使被旧调用者带上，也没有任何授权作用。
    db = MagicMock()
    db.get_platform_ui_failure_streaks.return_value = [{
        "stage": "management_verify", "active": 1, "consecutive_failures": 99,
    }]

    assert _guard_before_browser(args, db=db) == EXIT_NOT_CALIBRATED
    db.begin_douyin_browser_launch.assert_not_called()


def test_raw_uploader_publish_fuse_blocks_ordinary_calibration_and_default_snapshot(tmp_path: Path):
    """所有会打开投稿页的动作都要过熔断，不能让无 action 的默认快照成为旁路。"""
    db = MagicMock()
    db.get_platform_ui_failure_streaks.return_value = [{
        "stage": "publish_pre_submit", "active": 1, "consecutive_failures": 99,
    }]
    calibration_args = _raw_uploader_args(tmp_path=tmp_path)
    calibration_args.calibrate = True
    default_args = _raw_uploader_args(tmp_path=tmp_path)

    assert _guard_before_browser(calibration_args, db=db) == EXIT_NOT_CALIBRATED
    assert _guard_before_browser(default_args, db=db) == EXIT_NOT_CALIBRATED


def test_raw_uploader_management_fuse_keeps_login_only_available_for_new_ticket_recovery(tmp_path: Path):
    """管理页 selector 漂移不能阻止无上传的会话恢复，否则新片无法再使用已签 ticket。"""
    args = _raw_uploader_args(tmp_path=tmp_path)
    args.login_only = True
    db = MagicMock()
    db.get_platform_ui_failure_streaks.return_value = [{
        "stage": "management_verify", "active": 1, "consecutive_failures": 99,
    }]

    assert _guard_before_browser(args, db=db) is None


def test_raw_uploader_unreadable_or_malformed_guard_refuses_before_browser():
    """账本读取异常和损坏条目都必须收敛到同一个无浏览器 fail-closed 结果。"""
    args = SimpleNamespace(
        publish=False,
        preflight_only=False,
        calibrate_after_upload=False,
        verify_only=True,
        operator_recovery_stage=None,
        operator_recovery_reason=None,
        evidence_dir=None,
    )
    unreadable_db = MagicMock()
    unreadable_db.get_platform_ui_failure_streaks.side_effect = RuntimeError("db unavailable")
    malformed_db = MagicMock()
    malformed_db.get_platform_ui_failure_streaks.return_value = [{
        "stage": "management_verify", "active": True, "consecutive_failures": 99,
    }]

    assert _guard_before_browser(args, db=unreadable_db) == EXIT_NOT_CALIBRATED
    assert _guard_before_browser(args, db=malformed_db) == EXIT_NOT_CALIBRATED


def test_raw_uploader_recovery_calibration_is_audited_but_never_bypasses_publish(
    tmp_path: Path,
):
    """恢复只放行带阶段、理由和独立证据目录的非最终校准动作。"""
    evidence_dir = tmp_path / "output" / "douyin_calibration" / "recovery-1"
    db = MagicMock()
    db.get_platform_ui_failure_streaks.return_value = [{
        "stage": "publish_pre_submit", "active": 1, "consecutive_failures": 99,
    }]
    recovery_args = SimpleNamespace(
        publish=False,
        preflight_only=True,
        calibrate_after_upload=False,
        verify_only=False,
        operator_recovery_stage="publish_pre_submit",
        operator_recovery_reason="修复投稿页控件校准",
        evidence_dir=evidence_dir,
    )

    assert _guard_before_browser(
        recovery_args,
        db=db,
        calibration_root=evidence_dir.parent,
    ) is None
    audit = json.loads((evidence_dir / "operator_recovery_calibration.json").read_text(encoding="utf-8"))
    assert audit["stage"] == "publish_pre_submit"
    assert audit["final_publish"] is False

    recovery_args.publish = True
    recovery_args.preflight_only = False
    assert _guard_before_browser(recovery_args, db=db) == EXIT_FAILED


def test_raw_uploader_recovery_allows_audited_publish_page_snapshot(tmp_path: Path):
    """被熔断的投稿页可用带阶段和证据目录的 --calibrate 受控采集。"""
    evidence_dir = tmp_path / "output" / "douyin_calibration" / "snapshot-recovery"
    db = MagicMock()
    db.get_platform_ui_failure_streaks.return_value = [{
        "stage": "publish_pre_submit", "active": 1, "consecutive_failures": 99,
    }]
    args = _raw_uploader_args(tmp_path=tmp_path)
    args.calibrate = True
    args.operator_recovery_stage = "publish_pre_submit"
    args.operator_recovery_reason = "重新采集投稿页控件证据"
    args.evidence_dir = evidence_dir

    assert _guard_before_browser(args, db=db, calibration_root=evidence_dir.parent) is None
    assert (evidence_dir / "operator_recovery_calibration.json").is_file()


def test_management_state_requires_exact_copy_identity_and_local_card_status():
    copy_text = "这是一段足够长、可唯一识别当前作品的正文内容，用于验证作品管理页状态。"
    page_text = (
        "作品管理已发布其他作品 "
        + copy_text
        + " 编辑作品 设置权限 2026年08月08日 已发布 播放 12"
    )

    assert get_management_publication_state(page_text, copy_text) == "PUBLISHED"
    assert get_management_publication_state("作品管理 已发布其他作品", copy_text) is None


def test_management_state_keeps_exactly_matched_work_under_review():
    copy_text = "这是一段足够长、可唯一识别当前作品的正文内容，用于验证审核状态。"
    page_text = copy_text + " 编辑作品 设置权限 2026年08月08日 审核中"

    assert get_management_publication_state(page_text, copy_text) == "UNDER_REVIEW"


def test_management_state_uses_exact_title_when_current_list_hides_copy():
    title = "AI短片人物不连戏？这招帮你搞定"
    copy_text = "管理页当前不展示的长正文内容。" * 8
    page_text = (
        "作品(114)全部已发布审核中不通过 "
        + title
        + " 编辑作品 设置权限 2026年08月24日 22:00 审核中 播放 -"
    )

    assert get_management_publication_state(page_text, copy_text, title) == "UNDER_REVIEW"
    assert get_management_publication_state(page_text, copy_text, title + "不同") is None


def test_management_state_reads_long_description_but_not_next_card():
    title = "这是一条足够独特的完整标题"
    copy = "这段长简介包含审核中一词但不是平台状态。" * 40
    card = title + copy + "编辑作品 设置权限 作品置顶 删除作品 2026年09月05日 10:58 "
    assert get_management_publication_state(card + "已发布", copy, title) == "PUBLISHED"
    next_card = "另一作品 编辑作品 设置权限 2026年09月05日 已发布"
    assert get_management_publication_state(card + "流量减少 播放 3 " + next_card, copy, title) is None


def test_management_wait_ignores_empty_shell_until_list_or_target_loads():
    page = MagicMock()
    body = MagicMock()
    body.inner_text.side_effect = [
        "作品发布 首页 内容管理 数据中心",
        "作品发布 首页 内容管理 加载中",
        "作品(114) 全部 已发布 审核中 搜索作品 精确标题",
    ]
    page.locator.return_value = body

    text = wait_for_management_content(page, timeout_ms=2_000, expected_markers=["精确标题"])

    assert "精确标题" in text
    assert page.wait_for_timeout.call_count == 2


def test_management_title_search_is_exact_and_read_only():
    page = MagicMock()
    search = MagicMock()
    search.count.return_value = 1
    search.is_visible.return_value = True
    search.nth.return_value = search
    page.locator.return_value = search

    assert _search_management_title(page, "北极运动：一场跨越世代的平衡挑战")
    search.first.wait_for.assert_called_once_with(state="visible", timeout=15_000)
    search.fill.assert_called_once_with("北极运动：一场跨越世代的平衡挑战", timeout=3_000)
    search.press.assert_called_once_with("Enter", timeout=3_000)
    page.wait_for_timeout.assert_called_once_with(1_000)


def test_login_detection_includes_passport_and_creator_login_text():
    assert is_login_required(
        "https://creator.douyin.com/creator-micro/content/upload",
        "抖音创作者中心 扫码登录",
    )
    assert is_login_required(
        "https://creator.douyin.com/creator-micro/content/upload",
        frame_urls=["https://sso.douyin.com/login/"],
    )
    assert not is_login_required(
        "https://creator.douyin.com/creator-micro/content/upload",
        "点击上传 或直接将视频文件拖入此区域",
    )


def test_douyin_video_input_requires_exactly_one_observed_control():
    page = MagicMock()
    locator = MagicMock()
    locator.count.return_value = 1
    page.locator.return_value = locator

    assert get_video_upload_input(page) is locator
    page.locator.assert_called_once_with(DOUYIN_VIDEO_INPUT_SELECTOR)

    locator.count.return_value = 2
    assert get_video_upload_input(page) is None


def test_douyin_title_and_description_controls_must_be_unique():
    page = MagicMock()
    title = MagicMock()
    title.count.return_value = 1
    editor = MagicMock()
    editor.count.return_value = 1
    page.locator.side_effect = lambda selector: title if selector == DOUYIN_TITLE_SELECTOR else editor

    assert get_title_input(page) is title
    assert get_description_editor(page) is editor

    title.count.return_value = 2
    assert get_title_input(page) is None


def test_wait_for_douyin_video_input_retries_until_spa_has_rendered():
    page = MagicMock()
    locator = MagicMock()
    locator.count.side_effect = [0, 1]
    page.locator.return_value = locator

    assert wait_for_video_upload_input(page, timeout_seconds=2) is locator
    page.wait_for_timeout.assert_called_once_with(1_000)


def test_douyin_upload_completion_waits_for_progress_to_disappear():
    page = MagicMock()
    body = MagicMock()
    body.inner_text.side_effect = [
        "上传中 90%",
        "当前速度：5.4MB/s 剩余时间：8秒",
        "预览视频 重新上传 发布设置",
    ]
    page.locator.return_value = body

    assert is_upload_in_progress(page)
    assert wait_for_upload_completion(page, timeout_seconds=2)
    page.wait_for_timeout.assert_called_once_with(1_000)


def test_douyin_upload_is_complete_only_when_video_preview_is_visible():
    page = MagicMock()
    body = MagicMock()
    body.inner_text.return_value = "预览视频 重新上传 发布设置"
    page.locator.return_value = body

    assert has_post_upload_form(page)
    assert not is_upload_in_progress(page)


def test_douyin_empty_publish_form_is_not_video_upload_completion():
    page = MagicMock()
    body = MagicMock()
    body.inner_text.return_value = "填写作品标题 发布设置 点击上传 或直接将视频文件拖入此区域"
    page.locator.return_value = body

    assert not has_post_upload_form(page)
    assert is_upload_in_progress(page)


def test_douyin_upload_still_in_progress_when_percent_visible_with_form():
    page = MagicMock()
    body = MagicMock()
    body.inner_text.return_value = "发布设置 已上传：26.4MB/65.1MB 当前速度：5.4MB/s 剩余时间：8秒 40%"
    page.locator.return_value = body

    assert not has_post_upload_form(page)
    assert is_upload_in_progress(page)


def test_douyin_upload_static_publish_notice_is_not_active_progress():
    text = "点击发布后，如作品还在上传中，请勿关闭页面，等待上传发布完成。 发布设置"

    assert not has_active_upload_progress(text)


def test_douyin_preview_transcoding_notice_does_not_block_submit():
    text = "预览转码中，请稍后 转码过程也可以发布作品 发布设置 点击发布后，如作品还在上传中，请勿关闭页面"

    assert not has_active_upload_progress(text)


def test_douyin_uploaded_preview_explanation_is_not_active_progress():
    text = (
        "预览视频 重新上传 视频素材已按原始分辨率上传，为保证预览体验，"
        "视频会被压缩预览，实际播放时根据环境自动选组最佳分辨率播放。"
    )

    assert not has_active_upload_progress(text)


def test_douyin_cover_validation_waits_for_detection_to_finish():
    page = MagicMock()
    body = MagicMock()
    body.inner_text.side_effect = ["设置封面 封面检测中40%", "封面效果检测通过"]
    page.locator.return_value = body

    assert wait_for_cover_validation(page, timeout_seconds=2)
    page.wait_for_timeout.assert_called_once_with(1_000)


def test_douyin_cover_validation_fails_closed_on_rejection():
    page = MagicMock()
    body = MagicMock()
    body.inner_text.return_value = "封面检测未通过，请重新设置封面"
    page.locator.return_value = body

    assert not wait_for_cover_validation(page, timeout_seconds=1)


def test_cover_validation_refreshes_stale_missing_once_then_waits():
    page = MagicMock()
    body = MagicMock()
    body.inner_text.side_effect = ["横封面缺失"] * 5 + ["封面效果检测通过"]
    page.locator.return_value = body
    refresh = MagicMock()
    with patch("scripts.douyin_uploader._find_visible_element", return_value=refresh):
        assert wait_for_cover_validation(page, timeout_seconds=6)
    refresh.click.assert_called_once()


def test_cover_validation_absent_result_does_not_mean_success():
    page = MagicMock()
    page.locator.return_value.inner_text.return_value = "设置封面 Ai智能推荐封面生成中"
    assert not wait_for_cover_validation(page, timeout_seconds=2)


def test_douyin_cover_validation_accepts_explicit_success_over_stale_missing_notice():
    page = MagicMock()
    body = MagicMock()
    body.inner_text.return_value = "横/竖双封面缺失 封面效果检测通过 暂未发现封面低质问题"
    page.locator.return_value = body

    assert wait_for_cover_validation(page, timeout_seconds=1)


def test_douyin_upload_completion_returns_false_when_page_closes():
    page = MagicMock()
    body = MagicMock()
    body.inner_text.return_value = "上传中 90%"
    page.locator.return_value = body
    page.wait_for_timeout.side_effect = RuntimeError("Target closed")

    assert not wait_for_upload_completion(page, timeout_seconds=2)


def test_douyin_calibration_upload_collects_controls_without_submitting(tmp_path: Path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    upload_input = MagicMock()
    upload_input.count.return_value = 1
    controls = MagicMock()
    controls.evaluate_all.return_value = [{"tag": "textarea", "placeholder": "请输入标题"}]
    controls.inner_text.return_value = "预览视频 重新上传 发布设置"
    page = MagicMock()
    page.locator.side_effect = lambda selector: upload_input if selector == DOUYIN_VIDEO_INPUT_SELECTOR else controls

    assert upload_for_calibration(page, str(video), tmp_path, upload_wait_seconds=1)
    upload_input.set_input_files.assert_called_once_with(str(video.resolve()))
    assert (tmp_path / "douyin_post_upload_controls.json").exists()
    page.screenshot.assert_called_once()


def test_douyin_publish_fields_are_filled_without_submit(tmp_path: Path):
    title = MagicMock()
    title.count.return_value = 1
    title.input_value.return_value = "一个测试标题"
    editor = MagicMock()
    editor.count.return_value = 1
    editor.inner_text.return_value = "一段测试描述"
    controls = MagicMock()
    controls.evaluate_all.return_value = []
    page = MagicMock()
    page.evaluate.return_value = True
    page.locator.side_effect = lambda selector: (
        title if selector == DOUYIN_TITLE_SELECTOR
        else editor if selector == DOUYIN_DESCRIPTION_SELECTOR
        else controls
    )

    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"cover")
    with patch("scripts.douyin_uploader.prepare_douyin_cover_upload_file", return_value=str(cover)), patch(
        "scripts.douyin_uploader.prepare_douyin_horizontal_cover_upload_file", return_value=str(cover)
    ), patch("scripts.douyin_uploader.apply_cover", return_value=True):
        assert fill_publish_fields(page, "一个测试标题", "一段测试描述", tmp_path, cover_path=str(cover))
    title.fill.assert_called_once_with("一个测试标题")
    editor.fill.assert_called_once_with("一段测试描述")
    editor.press.assert_called_once_with("Escape")
    editor.evaluate.assert_called_once_with("element => element.blur()")
    page.keyboard.press.assert_called_once_with("Escape")
    assert (tmp_path / "douyin_ready_to_submit_controls.json").exists()


def test_douyin_publish_fields_use_independent_horizontal_cover(tmp_path: Path):
    vertical_cover = tmp_path / "vertical.png"
    horizontal_cover = tmp_path / "horizontal.png"
    vertical_cover.write_bytes(b"vertical")
    horizontal_cover.write_bytes(b"horizontal")
    title = MagicMock()
    title.count.return_value = 1
    title.input_value.return_value = "标题"
    editor = MagicMock()
    editor.count.return_value = 1
    editor.inner_text.return_value = "描述"
    controls = MagicMock()
    controls.evaluate_all.return_value = []
    page = MagicMock()
    page.evaluate.return_value = True
    page.locator.side_effect = lambda selector: (
        title if selector == DOUYIN_TITLE_SELECTOR else editor if selector == DOUYIN_DESCRIPTION_SELECTOR else controls
    )

    with patch("scripts.douyin_uploader.prepare_douyin_cover_upload_file", return_value=str(vertical_cover)), patch(
        "scripts.douyin_uploader.prepare_douyin_horizontal_cover_upload_file", return_value=str(horizontal_cover)
    ) as prepare_horizontal, patch("scripts.douyin_uploader.apply_cover", return_value=True) as apply_cover_mock:
        assert fill_publish_fields(
            page,
            "标题",
            "描述",
            tmp_path,
            cover_path=str(vertical_cover),
            horizontal_cover_path=str(horizontal_cover),
        )

    prepare_horizontal.assert_called_once_with(str(horizontal_cover))
    apply_cover_mock.assert_called_once_with(
        page,
        str(vertical_cover),
        artifact_dir=tmp_path,
        horizontal_cover_path=str(horizontal_cover),
    )


def test_douyin_fill_fields_never_clicks_hashtag_suggestion(tmp_path: Path):
    cover = tmp_path / "cover.png"
    cover.write_bytes(b"cover")
    title = MagicMock()
    title.count.return_value = 1
    title.input_value.return_value = "标题"
    editor = MagicMock()
    editor.count.return_value = 1
    editor.inner_text.return_value = "正文 #英文阅读"
    controls = MagicMock()
    controls.evaluate_all.return_value = []
    page = MagicMock()
    page.evaluate.return_value = True
    page.locator.side_effect = lambda selector: (
        title if selector == DOUYIN_TITLE_SELECTOR else editor if selector == DOUYIN_DESCRIPTION_SELECTOR else controls
    )

    with patch("scripts.douyin_uploader.prepare_douyin_cover_upload_file", return_value=str(cover)), patch(
        "scripts.douyin_uploader.prepare_douyin_horizontal_cover_upload_file", return_value=str(cover)
    ), patch("scripts.douyin_uploader.apply_cover", return_value=True):
        assert fill_publish_fields(page, "标题", "正文 #英文阅读", tmp_path, cover_path=str(cover))

    page.get_by_text.assert_not_called()


def test_final_metadata_accepts_platform_terminal_hashtag_expansion_only():
    title = MagicMock()
    title.count.return_value = 1
    title.input_value.return_value = "标题"
    editor = MagicMock()
    editor.count.return_value = 1
    editor.inner_text.return_value = "正文 #英文阅读书单"
    page = MagicMock()
    page.locator.side_effect = lambda selector: title if selector == DOUYIN_TITLE_SELECTOR else editor

    assert final_metadata_matches(page, "标题", "正文 #英文阅读")


def test_final_metadata_rejects_platform_replaced_hashtag_with_new_base_topic():
    title = MagicMock()
    title.count.return_value = 1
    title.input_value.return_value = "标题"
    editor = MagicMock()
    editor.count.return_value = 1
    editor.inner_text.return_value = "正文 #英语书写"
    page = MagicMock()
    page.locator.side_effect = lambda selector: title if selector == DOUYIN_TITLE_SELECTOR else editor

    assert not final_metadata_matches(page, "标题", "正文 #英文阅读")


def test_douyin_self_declaration_passes_when_already_selected(tmp_path: Path):
    page = MagicMock()
    page.evaluate.return_value = True

    assert select_self_declaration(page, tmp_path)
    page.wait_for_timeout.assert_not_called()


def test_douyin_self_declaration_selects_required_option(tmp_path: Path):
    page = MagicMock()
    page.evaluate.side_effect = [False, True, True, True]

    assert select_self_declaration(page, tmp_path)
    assert page.evaluate.call_count == 4
    assert any(DOUYIN_SELF_DECLARATION_OPTION_TEXT in str(call) for call in page.evaluate.call_args_list)
    assert page.wait_for_timeout.call_count == 2


def test_douyin_self_declaration_clicks_unique_visible_placeholder(tmp_path: Path):
    page = MagicMock()
    placeholder = MagicMock()
    placeholder.count.return_value = 1
    placeholder.is_visible.return_value = True
    missing = MagicMock()
    missing.count.return_value = 0
    page.get_by_text.side_effect = lambda text, exact=True: placeholder if text == "请选择自主声明" else missing
    page.evaluate.side_effect = [False, True, True]

    assert select_self_declaration(page, tmp_path)
    page.get_by_text.assert_any_call("请选择自主声明", exact=True)
    placeholder.click.assert_called_once_with(timeout=2_000, force=True)


def test_douyin_self_declaration_confirms_modal_option(tmp_path: Path):
    page = MagicMock()
    placeholder = MagicMock()
    placeholder.count.return_value = 1
    placeholder.is_visible.return_value = True
    option = MagicMock()
    option.count.return_value = 1
    option.is_visible.return_value = True
    confirm = MagicMock()
    confirm.count.return_value = 1
    confirm.is_visible.return_value = True
    confirm.is_enabled.return_value = True
    page.get_by_text.side_effect = lambda text, exact=True: {
        "请选择自主声明": placeholder,
        DOUYIN_SELF_DECLARATION_OPTION_TEXT: option,
        "确定": confirm,
    }[text]
    page.evaluate.side_effect = [False, True]

    assert select_self_declaration(page, tmp_path)
    option.click.assert_called_once_with(timeout=2_000, force=True)
    confirm.click.assert_called_once_with(timeout=2_000, force=True)


def test_douyin_self_declaration_failure_stops_before_submit(tmp_path: Path):
    title = MagicMock()
    title.count.return_value = 1
    title.input_value.return_value = "标题"
    editor = MagicMock()
    editor.count.return_value = 1
    editor.inner_text.return_value = "描述"
    controls = MagicMock()
    controls.evaluate_all.return_value = []
    page = MagicMock()
    page.evaluate.side_effect = [False, False]
    page.locator.side_effect = lambda selector: (
        title if selector == DOUYIN_TITLE_SELECTOR
        else editor if selector == DOUYIN_DESCRIPTION_SELECTOR
        else controls
    )

    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"cover")
    with patch("scripts.douyin_uploader.prepare_douyin_cover_upload_file", return_value=str(cover)), patch(
        "scripts.douyin_uploader.prepare_douyin_horizontal_cover_upload_file", return_value=str(cover)
    ), patch("scripts.douyin_uploader.apply_cover", return_value=True):
        assert not fill_publish_fields(page, "标题", "描述", tmp_path, cover_path=str(cover))
    assert (tmp_path / "douyin_self_declaration_failed_controls.json").exists()
    assert not (tmp_path / "douyin_ready_to_submit_controls.json").exists()


def test_douyin_publish_button_requires_one_enabled_exact_match():
    page = MagicMock()
    button = MagicMock()
    button.count.return_value = 1
    button.is_enabled.return_value = True
    page.get_by_text.return_value = button

    assert get_publish_button(page) is button
    page.get_by_text.assert_called_once_with("发布", exact=True)

    button.count.return_value = 2
    assert get_publish_button(page) is None


def test_douyin_publish_after_review_returns_submission_not_final_publish(tmp_path: Path):
    page = MagicMock()
    page.evaluate.return_value = True
    button = MagicMock()
    button.count.return_value = 1
    button.is_enabled.return_value = True
    page.get_by_text.return_value = button
    body = MagicMock()
    body.inner_text.return_value = "发布成功 等待审核 一个测试标题"
    controls = MagicMock()
    controls.evaluate_all.return_value = []
    page.locator.side_effect = lambda selector: body if selector == "body" else controls

    with patch("scripts.douyin_uploader.final_metadata_matches", return_value=True):
        assert publish_after_review(page, tmp_path, title_text="一个测试标题", description_text="一段测试描述")
    button.click.assert_called_once()
    assert (tmp_path / "douyin_post_submit_controls.json").exists()


def test_douyin_quick_detection_allows_exact_capacity_congestion_failure():
    page = MagicMock()
    body = MagicMock()
    body.inner_text.return_value = "快速检测 作品检测失败 抱歉，当前检测人数过多，请稍后再试"
    page.locator.return_value = body

    assert quick_detection_allows_submission(page)


def test_douyin_quick_detection_blocks_capacity_failure_when_cover_risk_coexists():
    page = MagicMock()
    body = MagicMock()
    body.inner_text.return_value = (
        "快速检测 作品检测失败 抱歉，当前检测人数过多，请稍后再试 封面检测未通过"
    )
    page.locator.return_value = body

    assert not quick_detection_allows_submission(page)


def test_douyin_quick_detection_retests_before_accepting_clean_result():
    page = MagicMock()
    retry_button = MagicMock()
    retry_button.count.return_value = 1
    retry_button.is_visible.return_value = True
    retry_button.is_enabled.return_value = True
    body = MagicMock()
    body.inner_text.side_effect = [
        "快速检测 横/竖双封面缺失",
        "快速检测 作品未见异常",
    ]
    page.get_by_text.return_value = retry_button
    page.locator.return_value = body

    assert quick_detection_allows_submission(page, timeout_seconds=2)
    retry_button.click.assert_called_once_with(timeout=2_000)


def test_douyin_quick_detection_waits_for_running_state_to_finish():
    page = MagicMock()
    retry_button = MagicMock()
    retry_button.count.return_value = 0
    body = MagicMock()
    body.inner_text.side_effect = [
        "快速检测 检测中 1%",
        "快速检测 作品未见异常",
    ]
    page.get_by_text.return_value = retry_button
    page.locator.return_value = body

    assert quick_detection_allows_submission(page, timeout_seconds=2)
    page.wait_for_timeout.assert_called_once_with(1_000)


def test_douyin_publish_after_review_stops_before_click_when_quick_detection_blocks(tmp_path: Path):
    page = MagicMock()
    page.evaluate.return_value = True
    body = MagicMock()
    body.inner_text.return_value = "快速检测 横/竖双封面缺失"
    controls = MagicMock()
    controls.evaluate_all.return_value = []
    page.locator.side_effect = lambda selector: body if selector == "body" else controls

    with patch("scripts.douyin_uploader.final_metadata_matches", return_value=True):
        assert not publish_after_review(page, tmp_path, title_text="标题", description_text="描述")
    page.get_by_text.assert_called_once_with("重新检测", exact=True)
    assert (tmp_path / "douyin_quick_detection_blocked_controls.json").exists()


def test_douyin_submission_preflight_passes_without_clicking_publish(tmp_path: Path):
    page = MagicMock()
    with patch("scripts.douyin_uploader.select_self_declaration", return_value=True), patch(
        "scripts.douyin_uploader.final_metadata_matches", return_value=True
    ), patch("scripts.douyin_uploader.quick_detection_allows_submission", return_value=True), patch(
        "scripts.douyin_uploader.capture_controls"
    ) as capture:
        assert submission_preflight_allows_publish(
            page,
            tmp_path,
            title_text="标题",
            description_text="描述",
        )

    capture.assert_called_once_with(page, tmp_path, "douyin_preflight_ready")
    page.get_by_text.assert_not_called()


def test_douyin_publish_wait_ignores_old_work_status_until_current_marker_appears(tmp_path: Path):
    page = MagicMock()
    page.evaluate.return_value = True
    button = MagicMock()
    button.count.return_value = 1
    button.is_enabled.return_value = True
    page.get_by_text.return_value = button
    body = MagicMock()
    body.inner_text.side_effect = [
        "作品上传中，请勿关闭页面 78% 已发布 旧作品标题",
        "已发布 旧作品标题",
        "提交成功 一个测试标题",
    ]
    controls = MagicMock()
    controls.evaluate_all.return_value = []
    page.locator.side_effect = lambda selector: body if selector == "body" else controls

    with patch("scripts.douyin_uploader.final_metadata_matches", return_value=True):
        assert publish_after_review(page, tmp_path, title_text="一个测试标题", description_text="一段测试描述")
    assert body.inner_text.call_count == 3


def test_douyin_publish_wait_accepts_manage_page_success_toast():
    page = MagicMock()
    page.url = "https://creator.douyin.com/creator-micro/content/manage"
    body = MagicMock()
    body.inner_text.return_value = "作品管理 全部作品 审核中 发布成功 共 0 个作品"
    page.locator.return_value = body

    assert wait_for_publish_submission(page, title_text="标题", description_text="描述", timeout_seconds=1)


def test_douyin_publish_wait_does_not_treat_unchanged_form_as_submission():
    page = MagicMock()
    page.url = "https://creator.douyin.com/creator-micro/content/upload"
    body = MagicMock()
    body.inner_text.return_value = "作品描述 一个测试标题 一段测试描述 发布"
    page.locator.return_value = body

    assert not wait_for_publish_submission(
        page,
        title_text="一个测试标题",
        description_text="一段测试描述",
        timeout_seconds=2,
    )
    assert page.wait_for_timeout.call_count == 2


def test_douyin_publish_click_failure_is_not_force_retried(tmp_path: Path):
    page = MagicMock()
    page.evaluate.return_value = True
    button = MagicMock()
    button.count.return_value = 1
    button.is_enabled.return_value = True
    button.click.side_effect = RuntimeError("overlay changed")
    page.get_by_text.return_value = button
    controls = MagicMock()
    controls.evaluate_all.return_value = []
    body = MagicMock()
    body.inner_text.return_value = "快速检测正常 标题 描述"
    page.locator.side_effect = lambda selector: body if selector == "body" else controls

    with patch("scripts.douyin_uploader.final_metadata_matches", return_value=True):
        assert not publish_after_review(page, tmp_path, title_text="标题", description_text="描述")
    button.click.assert_called_once_with(timeout=5000)
    assert (tmp_path / "douyin_submit_click_failed_controls.json").exists()


def test_douyin_upload_and_publish_returns_under_review(tmp_path: Path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    upload_input = MagicMock()
    upload_input.count.return_value = 1
    title = MagicMock()
    title.count.return_value = 1
    title.input_value.return_value = "标题"
    editor = MagicMock()
    editor.count.return_value = 1
    editor.inner_text.return_value = "描述"
    button = MagicMock()
    button.count.return_value = 1
    button.is_enabled.return_value = True
    controls = MagicMock()
    controls.evaluate_all.return_value = [{"placeholder": "请输入标题", "text": ""}]
    body = MagicMock()
    body.inner_text.return_value = "预览视频 重新上传 发布成功 等待审核 标题"
    page = MagicMock()
    page.evaluate.return_value = True
    page.locator.side_effect = lambda selector: (
        upload_input if selector == DOUYIN_VIDEO_INPUT_SELECTOR
        else title if selector == DOUYIN_TITLE_SELECTOR
        else editor if selector == DOUYIN_DESCRIPTION_SELECTOR
        else body if selector == "body"
        else controls
    )
    page.get_by_text.return_value = button

    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"cover")
    with patch("scripts.douyin_uploader.prepare_douyin_cover_upload_file", return_value=str(cover)), patch(
        "scripts.douyin_uploader.prepare_douyin_horizontal_cover_upload_file", return_value=str(cover)
    ), patch("scripts.douyin_uploader.apply_cover", return_value=True):
        assert upload_and_publish(
            page,
            str(video),
            tmp_path,
            upload_wait_seconds=1,
            title_text="标题",
            description_text="描述",
            cover_path=str(cover),
        ) == EXIT_UNDER_REVIEW


def test_douyin_upload_and_publish_marks_post_click_unconfirmed_separately(tmp_path: Path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    page = MagicMock()
    with patch("scripts.douyin_uploader.upload_for_calibration", return_value=True), patch(
        "scripts.douyin_uploader.submission_preflight_allows_publish", return_value=True
    ), patch("scripts.douyin_uploader.publish_after_review", return_value=False):
        assert upload_and_publish(
            page,
            str(video),
            tmp_path,
            upload_wait_seconds=1,
            title_text="标题",
            description_text="描述",
            cover_path="cover.jpg",
        ) == EXIT_SUBMISSION_UNCONFIRMED


def test_douyin_upload_and_publish_returns_pre_submit_unconfirmed_without_click(tmp_path: Path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    page = MagicMock()
    with patch("scripts.douyin_uploader.upload_for_calibration", return_value=True), patch(
        "scripts.douyin_uploader.submission_preflight_allows_publish", return_value=False
    ), patch("scripts.douyin_uploader.publish_after_review") as publish_after_review:
        assert upload_and_publish(
            page,
            str(video),
            tmp_path,
            upload_wait_seconds=1,
            title_text="标题",
            description_text="描述",
            cover_path="cover.jpg",
        ) == 3
    publish_after_review.assert_not_called()


def test_douyin_apply_cover_returns_false_when_cover_file_missing(tmp_path: Path):
    page = MagicMock()
    missing_file = str(tmp_path / "non_existent_cover.jpg")
    assert not apply_cover(page, missing_file)


def test_douyin_cover_entry_accepts_editor_already_open_after_click_timeout():
    """平台重绘可让点击报超时，但不能覆盖已经打开的编辑器结果态。"""
    page = MagicMock()
    entry = MagicMock()
    entry.click.side_effect = RuntimeError("element detached after click")
    editor = MagicMock()

    with patch("scripts.douyin_uploader._find_visible_element", return_value=entry), patch(
        "scripts.douyin_uploader._find_active_modal", return_value=editor
    ):
        assert _click_cover_entry(
            page,
            ["text=竖封面3:4"],
            artifact_dir=None,
            artifact_name="vertical",
            cover_path_abs="/tmp/cover.jpg",
        ) is editor

    entry.click.assert_called_once_with(timeout=2_000)


def test_prepare_douyin_cover_upload_file_creates_vertical_safe_cover(tmp_path: Path):
    from PIL import Image

    cover = tmp_path / "cover.jpg"
    Image.new("RGB", (1080, 1260), "black").save(cover)

    prepared = prepare_douyin_cover_upload_file(str(cover))
    assert prepared is not None
    with Image.open(prepared) as image:
        assert image.size == (1080, 1440)
    assert Path(prepared).name == "cover_douyin.jpg"


def test_prepare_douyin_horizontal_cover_upload_file_creates_4x3_safe_cover(tmp_path: Path):
    from PIL import Image

    cover = tmp_path / "cover.jpg"
    Image.new("RGB", (1080, 1260), "black").save(cover)

    prepared = prepare_douyin_horizontal_cover_upload_file(str(cover))
    assert prepared is not None
    with Image.open(prepared) as image:
        assert image.size == (1280, 960)
    assert Path(prepared).name == "cover_douyin_horizontal.jpg"


def test_douyin_apply_cover_success_with_modal_input(tmp_path: Path):
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"cover_bytes")

    entry_el = MagicMock()
    entry_el.is_visible.return_value = True

    tab_el = MagicMock()
    tab_el.is_visible.return_value = True

    input_el = MagicMock()
    input_el.get_attribute.return_value = "image/png,image/jpeg,image/jpg"

    confirm_btn = MagicMock()
    confirm_btn.is_visible.return_value = True
    confirm_btn.is_enabled.return_value = True

    modal_locators = MagicMock()
    modal_locators.count.return_value = 1
    modal = MagicMock()
    modal.is_visible.side_effect = [True, False, False]

    def modal_locator_side_effect(sel):
        if "上传封面" in sel or "本地上传" in sel:
            m = MagicMock()
            m.first = tab_el
            return m
        if "input[type='file']" in sel:
            m = MagicMock()
            m.count.return_value = 1
            m.nth.return_value = input_el
            return m
        if "完成" in sel or "确定" in sel:
            m = MagicMock()
            m.first = confirm_btn
            return m
        return MagicMock()

    modal.locator.side_effect = modal_locator_side_effect
    modal_locators.nth.return_value = modal

    def page_locator_side_effect(sel):
        if "封面" in sel:
            m = MagicMock()
            m.first = entry_el
            return m
        if "modal" in sel or "dialog" in sel:
            return modal_locators
        return MagicMock()

    page = MagicMock()
    page.locator.side_effect = page_locator_side_effect
    page.expect_file_chooser.side_effect = RuntimeError("no chooser")

    with patch("scripts.douyin_uploader._visible_cover_slot_image_sources", side_effect=[
        {"vertical": "before-vertical"}, {"vertical": "after-vertical"}, {"vertical": "after-vertical"},
    ]), patch("scripts.douyin_uploader._click_matching_cover_thumbnail", return_value=True), patch(
        "scripts.douyin_uploader._select_new_cover_candidate", return_value=True
    ) as select_new_candidate, patch(
        "scripts.douyin_uploader._is_cover_preview_matched", return_value=True
    ), patch(
        "scripts.douyin_uploader.wait_for_cover_validation", return_value=True
    ):
        assert apply_cover(page, str(cover))
    input_el.set_input_files.assert_called_once_with(str(cover.resolve()), timeout=3000)
    page.expect_file_chooser.assert_not_called()
    entry_el.scroll_into_view_if_needed.assert_called_once_with(timeout=2_000)
    confirm_btn.click.assert_called_once()
    select_new_candidate.assert_called_once()
    page.locator.assert_any_call(".dy-creator-content-modal-body")


def test_douyin_new_cover_candidate_uses_only_new_small_modal_thumbnail():
    """大裁剪预览与页面预览均不应被当作本次上传候选图。"""
    page = MagicMock()
    modal = MagicMock()
    modal.evaluate.return_value = [
        {"source": "old", "x": 500, "y": 300, "width": 200, "height": 300, "visible": True},
        {"source": "new-large", "x": 440, "y": 260, "width": 265, "height": 375, "visible": True},
        {"source": "new-small", "x": 770, "y": 310, "width": 94, "height": 110, "visible": True},
    ]

    assert _select_new_cover_candidate(page, modal, {"old"})

    page.mouse.click.assert_called_once_with(817.0, 365.0)


def test_douyin_apply_cover_page_fallback_does_not_call_page_is_visible(tmp_path: Path):
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"cover_bytes")
    page = MagicMock()
    page.is_visible = MagicMock()
    page.locator.side_effect = lambda selector: MagicMock()
    page.expect_file_chooser.side_effect = RuntimeError("no chooser")

    with patch("scripts.douyin_uploader._find_visible_element", side_effect=[MagicMock(), None, None, MagicMock(), None, None]), patch(
        "scripts.douyin_uploader._find_active_modal", return_value=page
    ), patch("scripts.douyin_uploader._apply_cover_in_current_panel", return_value=True), patch(
        "scripts.douyin_uploader._click_cover_confirm", return_value=True), patch(
        "scripts.douyin_uploader._visible_cover_slot_image_sources", side_effect=[
            {"vertical": "before-vertical"}, {"vertical": "after-vertical"}, {"vertical": "after-vertical"},
        ]), patch(
        "scripts.douyin_uploader.wait_for_cover_validation", return_value=True):
        assert apply_cover(page, str(cover))

    page.is_visible.assert_not_called()


def test_douyin_apply_cover_reopens_horizontal_slot_after_vertical_editor_closes(tmp_path: Path):
    vertical_cover = tmp_path / "vertical.jpg"
    horizontal_cover = tmp_path / "horizontal.jpg"
    vertical_cover.write_bytes(b"vertical")
    horizontal_cover.write_bytes(b"horizontal")
    page = MagicMock()
    vertical_modal = MagicMock()
    horizontal_modal = MagicMock()

    with patch(
        "scripts.douyin_uploader._click_cover_entry",
        side_effect=[vertical_modal, horizontal_modal],
    ) as click_entry, patch(
        "scripts.douyin_uploader._apply_cover_in_current_panel", side_effect=[True, True]
    ) as apply_panel, patch(
        "scripts.douyin_uploader._accept_horizontal_cover_recommendation", return_value=True
    ) as accept_recommendation, patch(
        "scripts.douyin_uploader._find_active_modal", return_value=page
    ), patch("scripts.douyin_uploader._click_cover_confirm", return_value=True) as confirm, patch(
        "scripts.douyin_uploader._continue_saved_horizontal_to_vertical_cover", return_value=False
    ) as continue_vertical_recommendation, patch(
        "scripts.douyin_uploader._wait_for_cover_editor_closed", return_value=True
    ), patch("scripts.douyin_uploader._visible_cover_slot_image_sources", side_effect=[
        {"vertical": "before-vertical", "horizontal": "before-horizontal"},
        {"vertical": "after-vertical", "horizontal": "before-horizontal"},
        {"vertical": "after-vertical", "horizontal": "after-horizontal"},
        {"vertical": "after-vertical", "horizontal": "after-horizontal"},
    ]), patch(
        "scripts.douyin_uploader.wait_for_cover_validation", return_value=True
    ):
        assert apply_cover(page, str(vertical_cover), horizontal_cover_path=str(horizontal_cover))

    assert apply_panel.call_args_list[0].args[2] == str(vertical_cover.resolve())
    assert apply_panel.call_args_list[1].args[2] == str(horizontal_cover.resolve())
    accept_recommendation.assert_called_once_with(page)
    assert confirm.call_args_list == [call(page, vertical_modal), call(page, horizontal_modal)]
    continue_vertical_recommendation.assert_called_once_with(page)
    assert click_entry.call_count == 2
    assert "横封面4:3" in click_entry.call_args_list[1].args[1][0]


def test_douyin_apply_cover_uses_same_editor_after_vertical_cover_recommendation(tmp_path: Path):
    """竖封面保存后的推荐层关闭后，横封面要复用仍打开的编辑器。"""
    vertical_cover = tmp_path / "vertical.jpg"
    horizontal_cover = tmp_path / "horizontal.jpg"
    vertical_cover.write_bytes(b"vertical")
    horizontal_cover.write_bytes(b"horizontal")
    page = MagicMock()
    shared_editor = MagicMock()

    with patch("scripts.douyin_uploader._click_cover_entry", return_value=shared_editor) as click_entry, patch(
        "scripts.douyin_uploader._apply_cover_in_current_panel", side_effect=[True, True]
    ) as apply_panel, patch(
        "scripts.douyin_uploader._accept_horizontal_cover_recommendation", return_value=True
    ) as accept_recommendation, patch(
        "scripts.douyin_uploader._find_active_modal", return_value=shared_editor
    ), patch("scripts.douyin_uploader._click_cover_confirm", return_value=True), patch(
        "scripts.douyin_uploader._continue_saved_horizontal_to_vertical_cover", return_value=False
    ), patch("scripts.douyin_uploader._wait_for_cover_editor_closed", return_value=True), patch(
        "scripts.douyin_uploader._visible_cover_slot_image_sources", side_effect=[
            {"vertical": "before-vertical", "horizontal": "before-horizontal"},
            {"vertical": "after-vertical", "horizontal": "before-horizontal"},
            {"vertical": "after-vertical", "horizontal": "after-horizontal"},
            {"vertical": "after-vertical", "horizontal": "after-horizontal"},
        ]
    ), patch("scripts.douyin_uploader.wait_for_cover_validation", return_value=True):
        assert apply_cover(page, str(vertical_cover), horizontal_cover_path=str(horizontal_cover))

    click_entry.assert_called_once()
    accept_recommendation.assert_called_once_with(page)
    assert apply_panel.call_args_list[1].args[1] is shared_editor
    assert apply_panel.call_args_list[1].args[2] == str(horizontal_cover.resolve())


def test_douyin_apply_cover_reapplies_vertical_when_platform_requires_it(tmp_path: Path):
    """横封面保存后的明确竖封面建议，必须在保留的编辑器中完成而非忽略。"""
    vertical_cover = tmp_path / "vertical.jpg"
    horizontal_cover = tmp_path / "horizontal.jpg"
    vertical_cover.write_bytes(b"vertical")
    horizontal_cover.write_bytes(b"horizontal")
    page = MagicMock()
    vertical_modal = MagicMock()
    horizontal_modal = MagicMock()
    required_vertical_modal = MagicMock()

    with patch(
        "scripts.douyin_uploader._click_cover_entry",
        side_effect=[vertical_modal, horizontal_modal],
    ) as click_entry, patch(
        "scripts.douyin_uploader._apply_cover_in_current_panel", side_effect=[True, True, True]
    ) as apply_panel, patch(
        "scripts.douyin_uploader._accept_horizontal_cover_recommendation", return_value=True
    ), patch(
        "scripts.douyin_uploader._find_active_modal", side_effect=[page, required_vertical_modal]
    ), patch("scripts.douyin_uploader._click_cover_confirm", return_value=True) as confirm, patch(
        "scripts.douyin_uploader._continue_saved_horizontal_to_vertical_cover", return_value=True
    ), patch("scripts.douyin_uploader._wait_for_cover_editor_closed", return_value=True), patch(
        "scripts.douyin_uploader._visible_cover_slot_image_sources", side_effect=[
            {"vertical": "before-vertical", "horizontal": "before-horizontal"},
            {"vertical": "after-vertical", "horizontal": "before-horizontal"},
            {"vertical": "after-vertical", "horizontal": "after-horizontal"},
            {"vertical": "after-vertical", "horizontal": "after-horizontal"},
        ]
    ), patch("scripts.douyin_uploader.wait_for_cover_validation", return_value=True):
        assert apply_cover(page, str(vertical_cover), horizontal_cover_path=str(horizontal_cover))

    assert click_entry.call_count == 2
    assert apply_panel.call_args_list[2].args[1] is required_vertical_modal
    assert apply_panel.call_args_list[2].args[2] == str(vertical_cover.resolve())
    assert confirm.call_count == 3


def test_douyin_apply_cover_stops_when_horizontal_recommendation_cannot_be_confirmed(tmp_path: Path):
    vertical_cover = tmp_path / "vertical.jpg"
    horizontal_cover = tmp_path / "horizontal.jpg"
    vertical_cover.write_bytes(b"vertical")
    horizontal_cover.write_bytes(b"horizontal")
    page = MagicMock()
    modal = MagicMock()

    with patch("scripts.douyin_uploader._click_cover_entry", return_value=modal), patch(
        "scripts.douyin_uploader._apply_cover_in_current_panel", return_value=True
    ) as apply_panel, patch(
        "scripts.douyin_uploader._accept_horizontal_cover_recommendation", return_value=False
    ), patch("scripts.douyin_uploader._click_cover_confirm", return_value=True) as confirm, patch(
        "scripts.douyin_uploader._wait_for_cover_editor_closed", return_value=True,
    ), patch("scripts.douyin_uploader._visible_cover_slot_image_sources", side_effect=[
        {"vertical": "before-vertical", "horizontal": "before-horizontal"},
        {"vertical": "after-vertical", "horizontal": "before-horizontal"},
    ]):
        assert not apply_cover(page, str(vertical_cover), horizontal_cover_path=str(horizontal_cover))

    assert apply_panel.call_count == 1
    confirm.assert_called_once_with(page, modal)


def test_douyin_cover_validation_rejects_missing_dual_cover_before_final_preflight():
    page = MagicMock()
    body = MagicMock()
    body.inner_text.return_value = "快速检测 横/竖双封面缺失 建议同时设置横版和竖版的封面"
    page.locator.return_value = body

    assert not wait_for_cover_validation(page, timeout_seconds=1)


def test_douyin_cover_validation_rejects_single_vertical_cover_missing_before_final_preflight():
    page = MagicMock()
    body = MagicMock()
    body.inner_text.return_value = "快速检测 封面优化建议 竖封面缺失"
    page.locator.return_value = body

    assert not wait_for_cover_validation(page, timeout_seconds=1)


def test_douyin_cover_slot_persistence_requires_a_changed_thumbnail_source():
    page = MagicMock()
    with patch(
        "scripts.douyin_uploader._visible_cover_slot_image_sources",
        side_effect=[{"vertical": "before"}, {"vertical": "before"}],
    ):
        assert not _wait_for_cover_slot_source_change(
            page, slot="vertical", original_source="before", timeout_seconds=2,
        )

    assert page.wait_for_timeout.call_count == 2


def test_douyin_cover_confirm_refuses_disabled_button():
    page = MagicMock()
    button = MagicMock()
    button.is_enabled.return_value = False
    modal = MagicMock()

    with patch("scripts.douyin_uploader._find_visible_element", return_value=button):
        assert not _click_cover_confirm(page, modal, timeout_seconds=1)
    button.click.assert_not_called()


def test_douyin_cover_confirm_recognizes_observed_save_button():
    page = MagicMock()
    button = MagicMock()
    button.is_enabled.return_value = True
    modal = MagicMock()

    with patch("scripts.douyin_uploader._find_visible_element", return_value=button) as find_visible:
        assert _click_cover_confirm(page, modal, timeout_seconds=1)

    selectors = find_visible.call_args.args[1]
    assert "button:has-text('保存')" in selectors
    assert "button.semi-button-primary" not in selectors
    button.click.assert_called_once_with(timeout=2000)


def test_douyin_publish_fields_stop_when_required_cover_fails(tmp_path: Path):
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"cover")
    title = MagicMock()
    title.count.return_value = 1
    title.input_value.return_value = "标题"
    editor = MagicMock()
    editor.count.return_value = 1
    editor.inner_text.return_value = "描述"
    controls = MagicMock()
    controls.evaluate_all.return_value = []
    page = MagicMock()
    page.evaluate.return_value = True
    page.locator.side_effect = lambda selector: (
        title if selector == DOUYIN_TITLE_SELECTOR
        else editor if selector == DOUYIN_DESCRIPTION_SELECTOR
        else controls
    )

    with patch("scripts.douyin_uploader.prepare_douyin_cover_upload_file", return_value=str(cover)), patch(
        "scripts.douyin_uploader.prepare_douyin_horizontal_cover_upload_file",
        return_value=str(cover),
    ), patch("scripts.douyin_uploader.apply_cover", return_value=False) as apply_cover_mock:
        assert not fill_publish_fields(page, "标题", "描述", tmp_path, cover_path=str(cover))
    apply_cover_mock.assert_called_once_with(
        page,
        str(cover),
        artifact_dir=tmp_path,
        horizontal_cover_path=str(cover),
    )


def test_douyin_publish_fields_refuse_unconfirmed_title_or_description(tmp_path: Path):
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"cover")
    title = MagicMock()
    title.count.return_value = 1
    title.input_value.return_value = "被页面清空"
    editor = MagicMock()
    editor.count.return_value = 1
    editor.inner_text.return_value = "描述"
    page = MagicMock()
    page.locator.side_effect = lambda selector: title if selector == DOUYIN_TITLE_SELECTOR else editor

    assert not fill_publish_fields(page, "标题", "描述", tmp_path, cover_path=str(cover))
    editor.fill.assert_called_once_with("描述")


def test_douyin_publish_fields_accept_editor_zero_width_formatting(tmp_path: Path):
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"cover")
    title = MagicMock()
    title.count.return_value = 1
    title.input_value.return_value = "标题"
    editor = MagicMock()
    editor.count.return_value = 1
    editor.inner_text.return_value = "描述\u200b正文"
    controls = MagicMock()
    controls.evaluate_all.return_value = []
    page = MagicMock()
    page.evaluate.return_value = True
    page.locator.side_effect = lambda selector: (
        title if selector == DOUYIN_TITLE_SELECTOR else editor if selector == DOUYIN_DESCRIPTION_SELECTOR else controls
    )

    with patch("scripts.douyin_uploader.prepare_douyin_cover_upload_file", return_value=str(cover)), patch(
        "scripts.douyin_uploader.prepare_douyin_horizontal_cover_upload_file", return_value=str(cover)
    ), patch("scripts.douyin_uploader.apply_cover", return_value=True):
        assert fill_publish_fields(page, "标题", "描述正文", tmp_path, cover_path=str(cover))


def test_douyin_publish_fields_refuse_missing_required_metadata(tmp_path: Path):
    page = MagicMock()
    title = MagicMock()
    title.count.return_value = 1
    editor = MagicMock()
    editor.count.return_value = 1
    page.locator.side_effect = lambda selector: title if selector == DOUYIN_TITLE_SELECTOR else editor

    assert not fill_publish_fields(page, "", "描述", tmp_path)
    title.fill.assert_not_called()
