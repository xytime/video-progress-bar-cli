"""TDD test cases for WeChat Channels collection selector.

# Modification History
| Version | Date       | Author                              | Description                                              |
|---------|------------|-------------------------------------|----------------------------------------------------------|
| 1.1.2   | 2026-05-27 | Unknown_Model_planning              | 移除已弃用的微信视频号分类选择测试                        |
| 1.1.1   | 2026-05-27 | Gemini_3.5_Flash_High_planning      | 修复 Playwright .first/.last 链式调用导致的 Mock 崩溃     |
| 1.2.0   | 2026-06-02 | Claude_Sonnet_4.6_Thinking_planning | 全面重写：适配 v1.9.0 新选择器（.post-album-display-wrap / .option-item / .create a） |
"""

import pytest
from unittest.mock import patch, MagicMock, call
from scripts.wechat_uploader import _select_collection


# ── 辅助工厂 ─────────────────────────────────────────────────────────────────

def create_locator_mock(count=1, visible=True, inner_text="", cls=""):
    """辅助创建链式调用的 Playwright Locator Mock。

    # [Claude_Sonnet_4.6_Thinking_planning]
    """
    loc = MagicMock()
    loc.count.return_value = count
    loc.is_visible.return_value = visible
    loc.inner_text.return_value = inner_text
    loc.get_attribute.return_value = cls  # class 属性

    # 链式自引用（.first / .last 返回自身）
    loc.first = loc
    loc.last = loc
    loc.nth.return_value = loc
    loc.locator.return_value = loc
    return loc


# ── Test 1: 合集已存在 → 直接选中 ────────────────────────────────────────────

def test_select_collection_exists():
    """选择已存在的合集：点触发器 → 等下拉 → 找到 option-item → 点击选中"""
    mock_page = MagicMock()

    # 触发器：.post-album-display-wrap
    mock_trigger = create_locator_mock(count=1, visible=True)

    # 合集条目：.filter-wrap .option-item（has= 匹配到目标）
    # get_attribute("class") 第一次返回 ""（非active），第二次返回 "option-item active"
    mock_item = create_locator_mock(count=1, visible=True)
    mock_item.get_attribute.side_effect = ["", "option-item active"]

    # page.locator 路由
    def locator_side_effect(selector, **kwargs):
        if ".post-album-display-wrap" in selector:
            return mock_trigger
        if ".filter-wrap .option-item" in selector:
            return mock_item
        # 兜底：count=0
        return create_locator_mock(count=0, visible=False)

    mock_page.locator.side_effect = locator_side_effect
    # wait_for_selector 默认不抛异常 → 模拟下拉出现

    result = _select_collection(mock_page, "AI内幕")

    assert result is True
    mock_trigger.click.assert_called_once()
    mock_page.wait_for_selector.assert_called_once_with("text=创建新合集", timeout=5000)
    mock_item.click.assert_called_once()


# ── Test 2: 合集已选中 → 去重返回 ────────────────────────────────────────────

def test_select_collection_dedup():
    """合集已为 active 状态时，直接按 Escape 关闭并返回 True"""
    mock_page = MagicMock()

    mock_trigger = create_locator_mock(count=1, visible=True)
    mock_item = create_locator_mock(count=1, visible=True, cls="option-item active")

    def locator_side_effect(selector, **kwargs):
        if ".post-album-display-wrap" in selector:
            return mock_trigger
        if ".filter-wrap .option-item" in selector:
            return mock_item
        return create_locator_mock(count=0, visible=False)

    mock_page.locator.side_effect = locator_side_effect

    result = _select_collection(mock_page, "AI内幕")

    assert result is True
    mock_item.click.assert_not_called()          # 已 active 不需要再点
    mock_page.keyboard.press.assert_called_with("Escape")


# ── Test 3: 合集不存在 → 自动新建 ─────────────────────────────────────────────

def test_select_collection_create_new():
    """合集不存在时：点「创建新合集」→ 填 Modal → 确认"""
    mock_page = MagicMock()

    mock_trigger = create_locator_mock(count=1, visible=True)
    mock_no_item = create_locator_mock(count=0, visible=False)   # 首次找不到对应合集
    mock_created_item = create_locator_mock(count=1, visible=True, cls="option-item")
    mock_created_item.get_attribute.side_effect = ["option-item", "option-item active"]
    item_lookup_count = 0

    # 「创建新合集」按钮
    mock_create_btn = create_locator_mock(count=1, visible=True)

    # 新建 Modal
    mock_modal = create_locator_mock(count=1, visible=True)
    mock_input = create_locator_mock(count=1, visible=True)
    mock_confirm = create_locator_mock(count=1, visible=True)

    def modal_locator_side_effect(selector):
        if "input" in selector:
            return mock_input
        if "button" in selector:
            return mock_confirm
        return create_locator_mock(count=0, visible=False)
    mock_modal.locator.side_effect = modal_locator_side_effect

    def locator_side_effect(selector, **kwargs):
        if ".post-album-display-wrap" in selector:
            return mock_trigger
        nonlocal_item = selector
        if ".filter-wrap .option-item" in nonlocal_item:
            nonlocal item_lookup_count
            item_lookup_count += 1
            # 前 10 轮各有精确/模糊两次查询；创建完成后才返回新合集。
            return mock_no_item if item_lookup_count <= 20 else mock_created_item
        if ".filter-wrap .create a" in nonlocal_item:
            return mock_create_btn
        if ".weui-desktop-dialog" in selector:
            return mock_modal
        return create_locator_mock(count=0, visible=False)

    mock_page.locator.side_effect = locator_side_effect

    with patch("scripts.wechat_uploader.human_click", return_value=True) as mock_hc:
        result = _select_collection(mock_page, "AI内幕?!：长于十五个字符的超长合集标题名称")

    assert result is True

    # 触发器被点击
    mock_trigger.click.assert_called_once()
    # 创建按钮被点击
    mock_create_btn.click.assert_called_once()
    # 输入框填入清洗并截断后的名称（去掉特殊字符，保留15个字）
    # "AI内幕长于十五个字符的超长合" - 特殊字符清除 + 15字截断
    mock_input.fill.assert_called_once()
    filled_name = mock_input.fill.call_args[0][0]
    assert len(filled_name) <= 15, f"Filled name too long: {filled_name!r}"
    assert "?!" not in filled_name, "Special chars not cleaned"
    # 确认按钮被点击
    mock_hc.assert_called_with(mock_page, mock_confirm)
    mock_created_item.click.assert_called_once()


# ── Test 4: 触发器找不到 → 返回 False ────────────────────────────────────────

def test_select_collection_no_trigger():
    """找不到触发器时优雅返回 False"""
    mock_page = MagicMock()
    mock_page.locator.return_value = create_locator_mock(count=0, visible=False)

    result = _select_collection(mock_page, "AI内幕")
    assert result is False


# ── Test 5: 空 collection_name → 直接返回 True ───────────────────────────────

def test_select_collection_empty_name():
    """空合集名称时跳过整个流程"""
    mock_page = MagicMock()
    result = _select_collection(mock_page, "")
    assert result is True
    mock_page.locator.assert_not_called()
