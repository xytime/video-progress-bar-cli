"""快手创作者中心上传器的登录与成功判据测试。"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.kuaishou_uploader import (
    EXIT_BANNED,
    EXIT_LOGIN_REQUIRED,
    EXIT_NOT_CALIBRATED,
    KUAISHOU_VIDEO_INPUT_SELECTOR,
    KUAISHOU_DESCRIPTION_SELECTOR,
    apply_cover,
    dismiss_onboarding_if_present,
    is_upload_in_progress,
    fill_description_for_review,
    capture_submission_area,
    get_publish_button,
    wait_for_publish_confirmation,
    upload_for_calibration,
    wait_for_upload_completion,
    wait_for_video_upload_input,
    get_video_upload_input,
    is_confirmed_submission,
    get_publish_failure_reason,
    adapt_copy_for_kuaishou,
    is_visible_in_management,
    get_management_submission_state,
    MANAGEMENT_PUBLISHED,
    MANAGEMENT_UNDER_REVIEW,
    is_creator_publish_url,
    is_login_required,
    is_account_banned_text,
    prepare_kuaishou_cover_upload_file,
    run_uploader,
    verify_submission_in_management,
)


def test_creator_publish_url_is_strict():
    assert is_creator_publish_url("https://cp.kuaishou.com/article/publish/video")
    assert not is_creator_publish_url("https://cp.kuaishou.com/article/manage/video")
    assert not is_creator_publish_url("https://passport.kuaishou.com/pc/account/login/")


def test_login_detection_includes_embedded_passport_and_landing_page():
    assert is_login_required(
        "https://cp.kuaishou.com/article/publish/video",
        "快手创作者服务平台 立即登录",
    )
    assert is_login_required(
        "https://cp.kuaishou.com/article/publish/video",
        frame_urls=["https://passport.kuaishou.com/pc/account/login/"],
    )
    assert not is_login_required("https://cp.kuaishou.com/article/publish/video", "上传视频")


def test_account_ban_is_not_login_required_or_publish_success():
    banned_text = "TA\n账号已被封禁\n该账号因违规操作已受到限制，无法访问创作者中心"

    assert is_account_banned_text(banned_text)
    assert not is_login_required("https://cp.kuaishou.com/profile", banned_text)


def test_submission_requires_explicit_success_evidence():
    assert is_confirmed_submission(redirected=True, page_text="", draft=False)
    assert is_confirmed_submission(redirected=False, page_text="发布成功", draft=False)
    assert not is_confirmed_submission(redirected=False, page_text="正在发布", draft=False)
    assert not is_confirmed_submission(redirected=False, page_text="发布不成功", draft=False)


def test_publish_validation_failure_reason_is_extracted():
    assert get_publish_failure_reason("内容发布失败: 话题标签数量超过上限：4") == "话题标签数量超过上限：4"
    assert get_publish_failure_reason("正在发布") is None


def test_kuaishou_copy_keeps_only_first_four_topic_tags():
    original = "正文。#一 #二 #三 #四 #五 关注我"
    adapted, removed = adapt_copy_for_kuaishou(original)

    assert adapted == "正文。#一 #二 #三 #四 关注我"
    assert removed == 1
    assert original.endswith("#五 关注我")


def test_video_input_requires_exactly_one_observed_control():
    page = MagicMock()
    locator = MagicMock()
    locator.count.return_value = 1
    page.locator.return_value = locator

    assert get_video_upload_input(page) is locator
    page.locator.assert_called_once_with(KUAISHOU_VIDEO_INPUT_SELECTOR)

    locator.count.return_value = 2
    assert get_video_upload_input(page) is None


def test_wait_for_video_input_retries_until_spa_has_rendered():
    page = MagicMock()
    locator = MagicMock()
    locator.count.side_effect = [0, 1]
    page.locator.return_value = locator

    assert wait_for_video_upload_input(page, timeout_seconds=2) is locator
    page.wait_for_timeout.assert_called_once_with(1_000)


def test_calibration_upload_collects_controls_without_submitting(tmp_path: Path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    upload_input = MagicMock()
    upload_input.count.return_value = 1
    controls = MagicMock()
    controls.evaluate_all.return_value = [{"tag": "textarea", "placeholder": "添加描述"}]
    controls.inner_text.return_value = "作品描述"
    page = MagicMock()
    page.locator.side_effect = lambda selector: upload_input if selector == KUAISHOU_VIDEO_INPUT_SELECTOR else controls

    assert upload_for_calibration(page, str(video), tmp_path)
    upload_input.set_input_files.assert_called_once_with(str(video.resolve()))
    assert (tmp_path / "kuaishou_post_upload_controls.json").exists()
    page.screenshot.assert_called_once()


def test_calibration_advances_only_when_next_step_is_unique(tmp_path: Path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    upload_input = MagicMock()
    upload_input.count.return_value = 1
    controls = MagicMock()
    controls.evaluate_all.return_value = []
    controls.inner_text.return_value = "作品描述"
    next_step = MagicMock()
    next_step.count.return_value = 1
    page = MagicMock()
    page.locator.side_effect = lambda selector: upload_input if selector == KUAISHOU_VIDEO_INPUT_SELECTOR else controls
    page.get_by_text.return_value = next_step

    assert upload_for_calibration(page, str(video), tmp_path, advance_form_once=True)
    next_step.click.assert_called_once()
    assert (tmp_path / "kuaishou_next_step_controls.json").exists()


def test_onboarding_skip_is_closed_only_when_unique():
    page = MagicMock()
    skip = MagicMock()
    skip.count.return_value = 1
    page.locator.return_value = skip

    assert dismiss_onboarding_if_present(page)
    skip.click.assert_called_once()

    skip.count.return_value = 2
    assert not dismiss_onboarding_if_present(page)


def test_upload_completion_waits_for_progress_to_disappear():
    page = MagicMock()
    body = MagicMock()
    body.inner_text.side_effect = ["上传中 90%", "上传中 90%", "作品描述"]
    page.locator.return_value = body

    assert is_upload_in_progress(page)
    assert wait_for_upload_completion(page, timeout_seconds=2)
    page.wait_for_timeout.assert_called_once_with(1_000)


def test_description_is_filled_without_draft_or_publish(tmp_path: Path):
    editor = MagicMock()
    editor.count.return_value = 1
    editor.evaluate_all.return_value = []
    page = MagicMock()
    page.locator.return_value = editor

    assert fill_description_for_review(page, "测试文案", tmp_path)
    page.locator.assert_any_call(KUAISHOU_DESCRIPTION_SELECTOR)
    editor.fill.assert_called_once_with("测试文案")
    assert (tmp_path / "kuaishou_ready_to_submit_controls.json").exists()


def test_submission_area_is_scrolled_for_read_only_capture(tmp_path: Path):
    controls = MagicMock()
    controls.evaluate_all.return_value = []
    page = MagicMock()
    page.locator.return_value = controls

    capture_submission_area(page, tmp_path)
    page.evaluate.assert_called_once()
    assert (tmp_path / "kuaishou_submission_area_controls.json").exists()


def test_publish_button_requires_one_enabled_exact_match():
    page = MagicMock()
    button = MagicMock()
    button.count.return_value = 1
    button.is_enabled.return_value = True
    page.get_by_text.return_value = button

    assert get_publish_button(page) is button
    page.get_by_text.assert_called_once_with("发布", exact=True)

    button.count.return_value = 2
    assert get_publish_button(page) is None


def test_publish_confirmation_requires_success_text_or_management_redirect():
    page = MagicMock()
    body = MagicMock()
    page.locator.return_value = body
    page.url = "https://cp.kuaishou.com/article/publish/video"
    body.inner_text.return_value = "发布成功"
    assert wait_for_publish_confirmation(page, timeout_seconds=1)

    page.url = "https://cp.kuaishou.com/article/manage/video"
    body.inner_text.return_value = "视频管理"
    assert wait_for_publish_confirmation(page, timeout_seconds=1)


def test_management_verification_requires_the_actual_copy_marker():
    assert is_visible_in_management("作品管理\n测试  文案\n刚刚发布", "测试文案")
    assert not is_visible_in_management("作品管理\n另一条作品", "测试文案")


def test_management_state_is_scoped_to_the_current_copy():
    review_page = "其他作品 已发布 测试文案 审核中"
    published_page = "测试文案 已发布 其他作品 审核中"
    assert get_management_submission_state(review_page, "测试文案") == MANAGEMENT_UNDER_REVIEW
    assert get_management_submission_state(published_page, "测试文案") == MANAGEMENT_PUBLISHED


def test_management_state_accepts_truncated_long_copy_marker():
    copy_text = "美国经济一片繁荣景象，GDP增长喜人，但奇怪的是，就业市场却前所未有的冷清，工作机会难觅。后续长文案"
    management_page = "作品管理 美国经济一片繁荣景象，GDP增长喜人，但奇怪的是，就业市场却 审核中"

    assert is_visible_in_management(management_page, copy_text)
    assert get_management_submission_state(management_page, copy_text) == MANAGEMENT_UNDER_REVIEW


def test_verify_only_maps_review_state_without_uploading():
    page = MagicMock()
    with patch(
        "scripts.kuaishou_uploader.wait_for_management_submission_state",
        return_value=MANAGEMENT_UNDER_REVIEW,
    ):
        assert verify_submission_in_management(page, "测试文案") == 6


def test_verify_only_maps_account_banned_state_without_uploading():
    page = MagicMock()
    with patch(
        "scripts.kuaishou_uploader.wait_for_management_submission_state",
        return_value="BANNED",
    ):
        assert verify_submission_in_management(page, "测试文案") == EXIT_BANNED


def test_automatic_upload_fast_fails_when_login_is_required(tmp_path: Path):
    video = tmp_path / "video.mp4"
    copy = tmp_path / "copy.txt"
    video.write_bytes(b"video")
    copy.write_text("copy", encoding="utf-8")

    page = MagicMock()
    page.url = "https://cp.kuaishou.com/article/publish/video"
    page.locator.return_value.inner_text.return_value = "快手创作者服务平台 立即登录"
    page.frames = []
    context = MagicMock()
    context.new_page.return_value = page
    browser = MagicMock()
    browser.new_context.return_value = context
    playwright = MagicMock()
    playwright.__enter__.return_value.chromium.launch.return_value = browser

    with patch("scripts.kuaishou_uploader.sync_playwright", return_value=playwright):
        result = run_uploader(
            video_path=str(video),
            copy_path=str(copy),
            state_path=str(tmp_path / "kuaishou_state.json"),
            fail_fast_login=True,
        )

    assert result == EXIT_LOGIN_REQUIRED
    browser.close.assert_called_once()


def test_logged_in_upload_stops_before_uncalibrated_submission(tmp_path: Path):
    video = tmp_path / "video.mp4"
    copy = tmp_path / "copy.txt"
    video.write_bytes(b"video")
    copy.write_text("copy", encoding="utf-8")

    page = MagicMock()
    page.url = "https://cp.kuaishou.com/article/publish/video"
    page.locator.return_value.inner_text.return_value = "上传视频"
    page.locator.return_value.count.return_value = 1
    page.frames = []
    context = MagicMock()
    context.new_page.return_value = page
    browser = MagicMock()
    browser.new_context.return_value = context
    playwright = MagicMock()
    playwright.__enter__.return_value.chromium.launch.return_value = browser

    with patch("scripts.kuaishou_uploader.sync_playwright", return_value=playwright):
        result = run_uploader(video_path=str(video), copy_path=str(copy), state_path=str(tmp_path / "kuaishou_state.json"))

    assert result == EXIT_NOT_CALIBRATED
    context.storage_state.assert_called_once()


def test_kuaishou_apply_cover_returns_false_when_cover_missing(tmp_path: Path):
    page = MagicMock()
    missing_file = str(tmp_path / "non_existent.jpg")
    assert not apply_cover(page, missing_file)


def test_prepare_kuaishou_cover_upload_file_scales_small_cover(tmp_path: Path):
    from PIL import Image

    cover = tmp_path / "cover.jpg"
    Image.new("RGB", (1080, 1260), "black").save(cover)

    prepared = prepare_kuaishou_cover_upload_file(str(cover))
    assert prepared is not None
    with Image.open(prepared) as image:
        width, height = image.size
    assert (width, height) == (1280, 2276)
    assert Path(prepared).name == "cover_kuaishou.jpg"


def test_kuaishou_apply_cover_success_with_input_file(tmp_path: Path):
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"cover_bytes")

    entry_el = MagicMock()
    entry_el.is_visible.return_value = True

    tab_el = MagicMock()
    tab_el.is_visible.return_value = True

    file_input = MagicMock()
    file_input.get_attribute.return_value = "image/jpeg,image/png"

    confirm_btn = MagicMock()
    confirm_btn.is_visible.return_value = True
    confirm_btn.is_enabled.return_value = True
    dialog_scope = MagicMock()
    dialog_scope.is_visible.return_value = True

    def page_locator_side_effect(sel):
        if "封面设置" in sel or "设置封面" in sel or "编辑封面" in sel:
            m = MagicMock()
            m.first = entry_el
            return m
        if "dialog" in sel or "ant-modal" in sel or "el-dialog" in sel or "ant-drawer" in sel:
            m = MagicMock()
            m.first = dialog_scope
            return m
        return MagicMock()

    def dialog_locator_side_effect(sel):
        if "本地上传" in sel:
            m = MagicMock()
            m.first = tab_el
            return m
        if "input[type='file']" in sel:
            m = MagicMock()
            m.count.return_value = 1
            m.nth.return_value = file_input
            return m
        if "确定" in sel or "完成" in sel:
            m = MagicMock()
            m.first = confirm_btn
            return m
        return MagicMock()

    page = MagicMock()
    page.locator.side_effect = page_locator_side_effect
    dialog_scope.locator.side_effect = dialog_locator_side_effect

    with patch("scripts.kuaishou_uploader._is_inline_cover_applied", return_value=True):
        assert apply_cover(page, str(cover))
    file_input.set_input_files.assert_called_once_with(str(cover.resolve()), timeout=2000)
    confirm_btn.click.assert_called_once()


def test_kuaishou_apply_cover_refuses_global_file_input_when_entry_missing(tmp_path: Path):
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"cover_bytes")
    hidden_video_input = MagicMock()
    hidden_video_input.get_attribute.return_value = "video/mp4"
    hidden_video_input.is_visible.return_value = False

    def locator_side_effect(sel):
        locator = MagicMock()
        if "input[type='file']" in sel:
            locator.count.return_value = 1
            locator.nth.return_value = hidden_video_input
        locator.first.is_visible.return_value = False
        return locator

    page = MagicMock()
    page.locator.side_effect = locator_side_effect

    assert not apply_cover(page, str(cover))
    hidden_video_input.set_input_files.assert_not_called()


def test_kuaishou_apply_cover_rejects_page_input_without_commit_control(tmp_path: Path):
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"cover_bytes")

    entry_el = MagicMock()
    entry_el.is_visible.return_value = True
    file_input = MagicMock()
    file_input.get_attribute.return_value = "image/jpeg,image/png"

    def hidden_locator():
        locator = MagicMock()
        locator.first.is_visible.return_value = False
        locator.count.return_value = 0
        return locator

    def locator_side_effect(sel):
        locator = hidden_locator()
        if "封面设置" in sel or "设置封面" in sel or "编辑封面" in sel:
            locator.first = entry_el
        elif "input[type='file'][accept*='image']" in sel:
            locator.count.return_value = 1
            locator.nth.return_value = file_input
        return locator

    page = MagicMock()
    page.locator.side_effect = locator_side_effect

    assert not apply_cover(page, str(cover))
    file_input.set_input_files.assert_called_once_with(str(cover.resolve()), timeout=2000)


def test_upload_stops_when_required_cover_cannot_be_applied(tmp_path: Path):
    video = tmp_path / "video.mp4"
    cover = tmp_path / "cover.jpg"
    video.write_bytes(b"video")
    cover.write_bytes(b"cover")
    upload_input = MagicMock()

    page = MagicMock()
    with patch("scripts.kuaishou_uploader.get_video_upload_input", return_value=upload_input), patch(
        "scripts.kuaishou_uploader.wait_for_upload_completion",
        return_value=True,
    ), patch("scripts.kuaishou_uploader._capture_form_controls"), patch(
        "scripts.kuaishou_uploader.apply_cover",
        return_value=False,
    ), patch("scripts.kuaishou_uploader.publish_after_review") as publish_after_review:
        assert not upload_for_calibration(
            page,
            str(video),
            tmp_path,
            publish=True,
            cover_path=str(cover),
        )

    publish_after_review.assert_not_called()


def test_upload_captures_evidence_after_cover_is_applied(tmp_path: Path):
    video = tmp_path / "video.mp4"
    cover = tmp_path / "cover.jpg"
    video.write_bytes(b"video")
    cover.write_bytes(b"cover")
    upload_input = MagicMock()

    captured_names = []

    def capture_side_effect(page, artifact_dir, artifact_name):
        captured_names.append(artifact_name)

    page = MagicMock()
    with patch("scripts.kuaishou_uploader.get_video_upload_input", return_value=upload_input), patch(
        "scripts.kuaishou_uploader.wait_for_upload_completion",
        return_value=True,
    ), patch("scripts.kuaishou_uploader._capture_form_controls", side_effect=capture_side_effect), patch(
        "scripts.kuaishou_uploader.prepare_kuaishou_cover_upload_file",
        return_value=str(cover),
    ), patch(
        "scripts.kuaishou_uploader.apply_cover",
        return_value=True,
    ):
        assert upload_for_calibration(
            page,
            str(video),
            tmp_path,
            cover_path=str(cover),
        )

    assert "kuaishou_cover_applied" in captured_names
