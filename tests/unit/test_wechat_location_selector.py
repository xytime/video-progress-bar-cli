"""视频号发布页位置选择测试。

# Modification History
| Version | Date       | Author | Description |
|---------|------------|--------|-------------|
| 1.0.0   | 2026-09-20 | Codex  | 覆盖“不显示位置”的幂等选择、成功回读与失败阻断。 |
"""

from unittest.mock import MagicMock

from scripts.wechat_uploader import _select_no_location


def _locator(*, count=1, visible=True, text=""):
    locator = MagicMock()
    locator.first = locator
    locator.count.return_value = count
    locator.is_visible.return_value = visible
    locator.inner_text.return_value = text
    locator.nth.return_value = locator
    locator.filter.return_value = locator
    return locator


def test_select_no_location_is_idempotent_when_already_selected():
    page = MagicMock()
    display = _locator(text="不显示位置")
    page.locator.return_value = display

    assert _select_no_location(page) is True

    display.click.assert_not_called()
    page.wait_for_selector.assert_not_called()


def test_select_no_location_clicks_exact_option_and_confirms_display():
    page = MagicMock()
    trigger = _locator()
    option = _locator(text="不显示位置")
    displays = iter([_locator(text="北京市"), _locator(text="不显示位置")])

    def locate(selector):
        if selector.endswith(".location-name"):
            return next(displays)
        if selector.endswith(".position-display"):
            return trigger
        if selector.endswith(".option-item"):
            return option
        return _locator(count=0, visible=False)

    page.locator.side_effect = locate

    assert _select_no_location(page) is True

    trigger.click.assert_called_once_with(timeout=2_000)
    page.wait_for_selector.assert_called_once_with(
        ".post-position-wrap .location-filter-wrap .option-item",
        state="visible",
        timeout=5_000,
    )
    page.get_by_text.assert_called_once_with("不显示位置", exact=True)
    option.click.assert_called_once_with(timeout=2_000)


def test_select_no_location_rejects_missing_selector():
    page = MagicMock()
    page.locator.return_value = _locator(count=0, visible=False)

    assert _select_no_location(page) is False

    page.get_by_text.assert_not_called()


def test_select_no_location_rejects_click_without_display_confirmation():
    page = MagicMock()
    display = _locator(text="北京市")
    trigger = _locator()
    option = _locator(text="不显示位置")

    def locate(selector):
        if selector.endswith(".location-name"):
            return display
        if selector.endswith(".position-display"):
            return trigger
        if selector.endswith(".option-item"):
            return option
        return _locator(count=0, visible=False)

    page.locator.side_effect = locate

    assert _select_no_location(page) is False

    option.click.assert_called_once_with(timeout=2_000)
    assert page.wait_for_timeout.call_count == 12
