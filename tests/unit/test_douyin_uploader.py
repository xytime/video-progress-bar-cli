"""抖音创作者中心上传器的登录、控件校准与 fail-closed 测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-23 | Codex | 覆盖抖音登录判定、唯一上传控件、上传校准与未校准发布保护 |
| 1.1.0 | 2026-07-23 | Codex | 覆盖上传校准期间页面关闭的未确认返回 |
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.douyin_uploader import (
    DOUYIN_DESCRIPTION_SELECTOR,
    DOUYIN_TITLE_SELECTOR,
    DOUYIN_VIDEO_INPUT_SELECTOR,
    EXIT_UNDER_REVIEW,
    apply_cover,
    fill_publish_fields,
    get_description_editor,
    get_publish_button,
    get_title_input,
    get_video_upload_input,
    has_post_upload_form,
    is_login_required,
    is_upload_in_progress,
    prepare_douyin_cover_upload_file,
    prepare_douyin_horizontal_cover_upload_file,
    publish_after_review,
    upload_for_calibration,
    upload_and_publish,
    wait_for_upload_completion,
    wait_for_video_upload_input,
)


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
    body.inner_text.side_effect = ["上传中 90%", "视频处理中", "发布设置"]
    page.locator.return_value = body

    assert is_upload_in_progress(page)
    assert wait_for_upload_completion(page, timeout_seconds=2)
    page.wait_for_timeout.assert_called_once_with(1_000)


def test_douyin_upload_is_complete_when_post_upload_form_is_visible():
    page = MagicMock()
    controls = MagicMock()
    controls.evaluate_all.return_value = [{"placeholder": "请输入标题", "text": ""}]
    page.locator.return_value = controls

    assert has_post_upload_form(page)
    assert not is_upload_in_progress(page)


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
    editor = MagicMock()
    editor.count.return_value = 1
    controls = MagicMock()
    controls.evaluate_all.return_value = []
    page = MagicMock()
    page.locator.side_effect = lambda selector: (
        title if selector == DOUYIN_TITLE_SELECTOR
        else editor if selector == DOUYIN_DESCRIPTION_SELECTOR
        else controls
    )

    assert fill_publish_fields(page, "一个测试标题", "一段测试描述", tmp_path)
    title.fill.assert_called_once_with("一个测试标题")
    editor.fill.assert_called_once_with("一段测试描述")
    assert (tmp_path / "douyin_ready_to_submit_controls.json").exists()


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


def test_douyin_upload_and_publish_returns_under_review(tmp_path: Path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    upload_input = MagicMock()
    upload_input.count.return_value = 1
    title = MagicMock()
    title.count.return_value = 1
    editor = MagicMock()
    editor.count.return_value = 1
    button = MagicMock()
    button.count.return_value = 1
    button.is_enabled.return_value = True
    controls = MagicMock()
    controls.evaluate_all.return_value = [{"placeholder": "请输入标题", "text": ""}]
    body = MagicMock()
    body.inner_text.return_value = "发布成功 等待审核 标题"
    page = MagicMock()
    page.locator.side_effect = lambda selector: (
        upload_input if selector == DOUYIN_VIDEO_INPUT_SELECTOR
        else title if selector == DOUYIN_TITLE_SELECTOR
        else editor if selector == DOUYIN_DESCRIPTION_SELECTOR
        else body if selector == "body"
        else controls
    )
    page.get_by_text.return_value = button

    assert upload_and_publish(
        page,
        str(video),
        tmp_path,
        upload_wait_seconds=1,
        title_text="标题",
        description_text="描述",
    ) == EXIT_UNDER_REVIEW


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
    modal.is_visible.return_value = True

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
        "scripts.douyin_uploader._is_cover_preview_matched",
        return_value=True,
    ):
        assert apply_cover(page, str(cover))
    input_el.set_input_files.assert_called_once_with(str(cover.resolve()), timeout=3000)
    confirm_btn.click.assert_called_once()


def test_douyin_publish_fields_stop_when_required_cover_fails(tmp_path: Path):
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"cover")
    title = MagicMock()
    title.count.return_value = 1
    editor = MagicMock()
    editor.count.return_value = 1
    controls = MagicMock()
    controls.evaluate_all.return_value = []
    page = MagicMock()
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
