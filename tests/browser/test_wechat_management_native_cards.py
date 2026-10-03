"""真实浏览器验证原生组件身份和状态范围，不按标题或列表位置绑定。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-03 | Codex | 验证组件原生 ID、独立状态标签、隐藏和重复记录的拒绝。 |
"""
from tests.browser_fixtures import chromium
from scripts.wechat_uploader import _collect_management_cards


def test_native_component_binds_own_status_without_description_spoof(chromium):
    page = chromium.new_page()
    try:
        page.set_content('''<div class="post-feed-item"><p>标题：已发布</p>
            <div class="bandage-list">审核中</div></div>
            <div class="post-feed-item" style="display:none"><div class="bandage-list">已发布</div></div>''')
        page.locator('.post-feed-item').evaluate_all('''nodes => nodes.forEach((node,i) => {
            node.__vue__ = {$props: {post: {objectId: i ? 'hidden' : 'native-id', exportId: 'export-id'}}};
        })''')
        cards = _collect_management_cards(page)
        assert list(cards) == ['native-id']
        assert cards['native-id']['status_text'] == '审核中'
        assert cards['native-id']['platform_export_id'] == 'export-id'
    finally:
        page.close()


def test_native_component_rejects_duplicate_and_missing_identity(chromium):
    page = chromium.new_page()
    try:
        page.set_content('<div class="post-feed-item">审核中</div>' * 3)
        page.locator('.post-feed-item').evaluate_all('''nodes => nodes.forEach((node,i) => {
            node.__vue__ = {$props: {post: i === 2 ? {} : {objectId: 'duplicate'}}};
        })''')
        assert _collect_management_cards(page) == {}
    finally:
        page.close()
