"""TDD test cases for WeChat Channels collection/category selector and publish sandbox controls.

# Modification History
| Version | Date       | Author                         | Description                                            |
|---------|------------|--------------------------------|--------------------------------------------------------|
| 1.1.1   | 2026-05-27 | Gemini_3.5_Flash_High_planning | 修复 Playwright .first/.last 链式调用导致的 Mock 崩溃错误 |
"""

import pytest
from unittest.mock import patch, MagicMock
from scripts.wechat_uploader import _select_category, _select_collection

def create_locator_mock(count=1, visible=True, inner_text=""):
    """辅助创建链式调用的 Playwright Locator Mock"""
    loc = MagicMock()
    loc.count.return_value = count
    loc.is_visible.return_value = visible
    loc.inner_text.return_value = inner_text
    
    # 链式自引用
    loc.first = loc
    loc.last = loc
    loc.nth.return_value = loc
    loc.locator.return_value = loc
    return loc

def test_select_category_success():
    """测试分类选择成功分支"""
    mock_page = MagicMock()
    
    # 1. 模拟 weui-desktop-form__item
    mock_item = create_locator_mock(count=1, visible=True, inner_text="视频分类")
    mock_form_items = create_locator_mock(count=1)
    mock_form_items.nth.return_value = mock_item
    
    # 2. 模拟下拉触发器和列表
    mock_trigger = create_locator_mock(count=1, visible=True)
    mock_item.locator.return_value = mock_trigger
    
    mock_container = create_locator_mock(count=1, visible=True)
    mock_option = create_locator_mock(count=1, visible=True)
    mock_container.locator.return_value = mock_option
    
    def locator_side_effect(selector):
        if ".weui-desktop-form__item" in selector:
            return mock_form_items
        elif ".weui-desktop-dropdown__list" in selector:
            return mock_container
        return create_locator_mock(count=0, visible=False)
        
    mock_page.locator.side_effect = locator_side_effect
    
    with patch("scripts.wechat_uploader.human_click", return_value=True) as mock_click:
        result = _select_category(mock_page, "科技")
        assert result is True
        mock_trigger.click.assert_called_once()
        mock_click.assert_called_once_with(mock_page, mock_option)

def test_select_collection_exists():
    """测试合集存在时的选中分支"""
    mock_page = MagicMock()
    
    # 1. 模拟 weui-desktop-form__item
    mock_item = create_locator_mock(count=1, visible=True, inner_text="添加到合集")
    mock_form_items = create_locator_mock(count=1)
    mock_form_items.nth.return_value = mock_item
    
    # 2. 模拟触发按钮
    mock_trigger = create_locator_mock(count=1, visible=True)
    mock_item.locator.return_value = mock_trigger
    
    # 3. 模拟合集列表与选项
    mock_container = create_locator_mock(count=1, visible=True)
    mock_option = create_locator_mock(count=1, visible=True)
    
    # 模拟 option 内部没有 checkbox，导致 count() == 0 从而直接点击 option
    mock_checkbox = create_locator_mock(count=0, visible=False)
    
    # 区分 locator 内部调用
    def option_locator_side_effect(selector):
        if "checkbox" in selector:
            return mock_checkbox
        return create_locator_mock(count=0, visible=False)
    mock_option.locator.side_effect = option_locator_side_effect
    
    mock_container.locator.return_value = mock_option
    
    def locator_side_effect(selector):
        if ".weui-desktop-form__item" in selector:
            return mock_form_items
        elif ".weui-desktop-dropdown__list" in selector:
            return mock_container
        return create_locator_mock(count=0, visible=False)
        
    mock_page.locator.side_effect = locator_side_effect
    
    with patch("scripts.wechat_uploader.human_click", return_value=True) as mock_click:
        result = _select_collection(mock_page, "AI内幕")
        assert result is True
        mock_trigger.click.assert_called_once()
        mock_click.assert_called_once_with(mock_page, mock_option)

def test_select_collection_create_new():
    """测试合集不存在时自动新建的分支"""
    mock_page = MagicMock()
    
    # 1. 模拟 weui-desktop-form__item
    mock_item = create_locator_mock(count=1, visible=True, inner_text="添加到合集")
    mock_form_items = create_locator_mock(count=1)
    mock_form_items.nth.return_value = mock_item
    
    # 2. 模拟触发按钮
    mock_trigger = create_locator_mock(count=1, visible=True)
    mock_item.locator.return_value = mock_trigger
    
    # 3. 模拟列表容器，但找不到对应的选项 (count=0)
    mock_container = create_locator_mock(count=1, visible=True)
    mock_option = create_locator_mock(count=0, visible=False)
    mock_container.locator.return_value = mock_option
    
    # 4. 模拟新建按钮
    mock_create_btn = create_locator_mock(count=1, visible=True)
    
    # 5. 模拟新建 Modal
    mock_modal = create_locator_mock(count=1, visible=True)
    mock_input = create_locator_mock(count=1, visible=True)
    mock_confirm_btn = create_locator_mock(count=1, visible=True)
    
    def modal_locator_side_effect(selector):
        if "input" in selector:
            return mock_input
        elif "button" in selector:
            return mock_confirm_btn
        return create_locator_mock(count=0, visible=False)
    mock_modal.locator.side_effect = modal_locator_side_effect
    
    def locator_side_effect(selector):
        if "li:has-text" in selector or "option" in selector:
            return mock_option
        elif ".weui-desktop-form__item" in selector:
            return mock_form_items
        elif ".weui-desktop-dropdown__list" in selector:
            return mock_container
        elif "新建" in selector or "创建" in selector:
            return mock_create_btn
        elif ".weui-desktop-dialog" in selector or "div[role='dialog']" in selector:
            return mock_modal
        return create_locator_mock(count=0, visible=False)
        
    mock_page.locator.side_effect = locator_side_effect
    
    with patch("scripts.wechat_uploader.human_click", return_value=True) as mock_click:
        result = _select_collection(mock_page, "AI内幕?!：长于十五个字符的超长合集标题名称")
        assert result is True
        # 验证是否触发了新建按钮点击
        mock_click.assert_any_call(mock_page, mock_create_btn)
        # 验证输入框是否被填入了清洗和截断（15个字）后的名称
        mock_input.fill.assert_called_once_with("AI内幕长于十五个字符的超长合")
        # 验证是否触发了保存确认按钮点击
        mock_click.assert_any_call(mock_page, mock_confirm_btn)
