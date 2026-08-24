"""抖音创作者中心上传器的登录、控件校准与 fail-closed 测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
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
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.douyin_uploader import (
    DOUYIN_DESCRIPTION_SELECTOR,
    DOUYIN_SELF_DECLARATION_OPTION_TEXT,
    DOUYIN_TITLE_SELECTOR,
    DOUYIN_VIDEO_INPUT_SELECTOR,
    EXIT_UNDER_REVIEW,
    EXIT_SUBMISSION_UNCONFIRMED,
    _click_cover_confirm,
    apply_cover,
    fill_publish_fields,
    get_description_editor,
    get_management_publication_state,
    get_publish_button,
    get_title_input,
    get_video_upload_input,
    has_active_upload_progress,
    has_post_upload_form,
    is_login_required,
    is_upload_in_progress,
    prepare_douyin_cover_upload_file,
    prepare_douyin_horizontal_cover_upload_file,
    publish_after_review,
    select_self_declaration,
    upload_for_calibration,
    upload_and_publish,
    wait_for_upload_completion,
    wait_for_publish_submission,
    wait_for_cover_validation,
    wait_for_video_upload_input,
)


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
    body.inner_text.side_effect = ["上传中 90%", "当前速度：5.4MB/s 剩余时间：8秒", "发布设置"]
    page.locator.return_value = body

    assert is_upload_in_progress(page)
    assert wait_for_upload_completion(page, timeout_seconds=2)
    page.wait_for_timeout.assert_called_once_with(1_000)


def test_douyin_upload_is_complete_when_post_upload_form_is_visible():
    page = MagicMock()
    body = MagicMock()
    body.inner_text.return_value = "发布设置"
    controls = MagicMock()
    controls.evaluate_all.return_value = [{"placeholder": "请输入标题", "text": ""}]
    page.locator.side_effect = lambda selector: body if selector == "body" else controls

    assert has_post_upload_form(page)
    assert not is_upload_in_progress(page)


def test_douyin_upload_still_in_progress_when_percent_visible_with_form():
    page = MagicMock()
    body = MagicMock()
    body.inner_text.return_value = "发布设置 已上传：26.4MB/65.1MB 当前速度：5.4MB/s 剩余时间：8秒 40%"
    controls = MagicMock()
    controls.evaluate_all.return_value = [{"placeholder": "请输入标题", "text": "发布"}]
    page.locator.side_effect = lambda selector: body if selector == "body" else controls

    assert has_post_upload_form(page)
    assert is_upload_in_progress(page)


def test_douyin_upload_static_publish_notice_is_not_active_progress():
    text = "点击发布后，如作品还在上传中，请勿关闭页面，等待上传发布完成。 发布设置"

    assert not has_active_upload_progress(text)


def test_douyin_preview_transcoding_notice_does_not_block_submit():
    text = "预览转码中，请稍后 转码过程也可以发布作品 发布设置 点击发布后，如作品还在上传中，请勿关闭页面"

    assert not has_active_upload_progress(text)


def test_douyin_cover_validation_waits_for_detection_to_finish():
    page = MagicMock()
    body = MagicMock()
    body.inner_text.side_effect = ["设置封面 封面检测中40%", "设置封面"]
    page.locator.return_value = body

    assert wait_for_cover_validation(page, timeout_seconds=2)
    page.wait_for_timeout.assert_called_once_with(1_000)


def test_douyin_cover_validation_fails_closed_on_rejection():
    page = MagicMock()
    body = MagicMock()
    body.inner_text.return_value = "封面检测未通过，请重新设置封面"
    page.locator.return_value = body

    assert not wait_for_cover_validation(page, timeout_seconds=1)


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
    controls.inner_text.return_value = "发布设置"
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
    assert (tmp_path / "douyin_ready_to_submit_controls.json").exists()


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

    assert publish_after_review(page, tmp_path, title_text="一个测试标题", description_text="一段测试描述")
    button.click.assert_called_once()
    assert (tmp_path / "douyin_post_submit_controls.json").exists()


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
        "审核中 一个测试标题",
    ]
    controls = MagicMock()
    controls.evaluate_all.return_value = []
    page.locator.side_effect = lambda selector: body if selector == "body" else controls

    assert publish_after_review(page, tmp_path, title_text="一个测试标题", description_text="一段测试描述")
    assert body.inner_text.call_count == 3


def test_douyin_publish_wait_accepts_manage_page_success_toast():
    page = MagicMock()
    page.url = "https://creator.douyin.com/creator-micro/content/manage"
    body = MagicMock()
    body.inner_text.return_value = "作品管理 全部作品 审核中 发布成功 共 0 个作品"
    page.locator.return_value = body

    assert wait_for_publish_submission(page, title_text="标题", description_text="描述", timeout_seconds=1)


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
    body.inner_text.return_value = "发布成功 等待审核 标题"
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
        "scripts.douyin_uploader.publish_after_review", return_value=False
    ):
        assert upload_and_publish(
            page,
            str(video),
            tmp_path,
            upload_wait_seconds=1,
            title_text="标题",
            description_text="描述",
            cover_path="cover.jpg",
        ) == EXIT_SUBMISSION_UNCONFIRMED


def test_douyin_apply_cover_returns_false_when_cover_file_missing(tmp_path: Path):
    page = MagicMock()
    missing_file = str(tmp_path / "non_existent_cover.jpg")
    assert not apply_cover(page, missing_file)


def test_prepare_douyin_cover_upload_file_creates_vertical_safe_cover(tmp_path: Path):
    from PIL import Image

    cover = tmp_path / "cover.jpg"
    Image.new("RGB", (1080, 1260), "black").save(cover)

    prepared = prepare_douyin_cover_upload_file(str(cover))
    assert prepared is not None
    with Image.open(prepared) as image:
        assert image.size == (1080, 1440)
    assert Path(prepared).name == "cover_douyin.png"


def test_prepare_douyin_horizontal_cover_upload_file_creates_4x3_safe_cover(tmp_path: Path):
    from PIL import Image

    cover = tmp_path / "cover.jpg"
    Image.new("RGB", (1080, 1260), "black").save(cover)

    prepared = prepare_douyin_horizontal_cover_upload_file(str(cover))
    assert prepared is not None
    with Image.open(prepared) as image:
        assert image.size == (1280, 960)
    assert Path(prepared).name == "cover_douyin_horizontal.png"


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
        if "选择封面" in sel or "设置封面" in sel:
            m = MagicMock()
            m.first = entry_el
            return m
        if "modal" in sel or "dialog" in sel:
            return modal_locators
        return MagicMock()

    page = MagicMock()
    page.locator.side_effect = page_locator_side_effect
    page.expect_file_chooser.side_effect = RuntimeError("no chooser")

    with patch("scripts.douyin_uploader._click_matching_cover_thumbnail", return_value=True), patch(
        "scripts.douyin_uploader._is_cover_preview_matched", return_value=True
    ), patch("scripts.douyin_uploader._saved_cover_slots_present", return_value=True), patch(
        "scripts.douyin_uploader.wait_for_cover_validation", return_value=True
    ):
        assert apply_cover(page, str(cover))
    input_el.set_input_files.assert_called_once_with(str(cover.resolve()), timeout=3000)
    confirm_btn.click.assert_called_once()
    page.locator.assert_any_call(".dy-creator-content-modal-body")


def test_douyin_cover_confirm_refuses_disabled_button():
    page = MagicMock()
    button = MagicMock()
    button.is_enabled.return_value = False
    modal = MagicMock()

    with patch("scripts.douyin_uploader._find_visible_element", return_value=button):
        assert not _click_cover_confirm(page, modal, timeout_seconds=1)
    button.click.assert_not_called()


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
