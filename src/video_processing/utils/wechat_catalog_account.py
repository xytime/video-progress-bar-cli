"""从官方首页公开的「视频号ID」读取稳定账号；不使用昵称、Cookie 或 profile。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-02 | Codex | 根据已存首页 DOM 校准可见 ID 与复制属性双读，采集前后同会话核对。 |
"""
import re
from time import monotonic

SELECTOR = '.finder-uniq-id-wrap .finder-uniq-id[data-clipboard-text]'


def read_home_id(page):
    nodes = page.locator(SELECTOR + ':visible')
    if nodes.count() != 1:
        return None
    values = nodes.evaluate_all('''es=>es.map(e=>({text:e.innerText.trim(),value:e.getAttribute('data-clipboard-text'),
        label:e.closest('.finder-uniq-id-wrap').innerText}))''')
    row = values[0]
    if (row['text'] != row['value'] or not re.fullmatch(r'sph[A-Za-z0-9_-]{5,125}', row['value'] or '')
            or not re.search(r'视频号\s*ID\s*[:：]', row['label'])):
        return None
    return {'kind':'PUBLIC_DOM_STABLE_ID', 'value':row['value'], 'selector':SELECTOR,
            'attribute':'data-clipboard-text'}


def visit_home_account(page, *, timeout_ms, diagnostics, clock=monotonic):
    """只点击历史公开页面中验证过的首页菜单；不进入切换账号或触发登录。"""
    end = clock() + timeout_ms / 1000
    menu = page.locator('a.finder-ui-desktop-menu__link:visible').filter(has_text=re.compile(r'^首页$'))
    # 先以取消关闭商品弹窗，避免遮挡首页；绝不点击添加/确认。
    from .wechat_product_picker import PlaywrightProductPicker
    context = PlaywrightProductPicker(page)._get_content_frame()
    dialogs = context.locator('.weui-desktop-dialog:visible, .ant-modal:visible, [role=dialog]:visible').filter(has_text='从橱窗添加商品')
    if dialogs.count():
        cancel = dialogs.get_by_role('button', name='取消', exact=True)
        if dialogs.count() != 1 or cancel.count() != 1:
            diagnostics['dialog_close'] = 'UNVERIFIED'
            return None
        cancel.click(timeout=max(1, int((end-clock())*1000)))
        diagnostics['dialog_close'] = 'CANCELLED_WITHOUT_SELECTION'
    while clock() < end and menu.count() != 1:
        page.wait_for_timeout(min(50, max(1, int((end-clock())*1000))))
    diagnostics['home_menu_count'] = menu.count()
    if menu.count() != 1:
        return None
    menu.click(timeout=max(1, int((end-clock())*1000)))
    while clock() < end:
        evidence = read_home_id(page)
        if evidence:
            diagnostics['stable_id_observed'] = True
            return evidence
        page.wait_for_timeout(min(50, max(1, int((end-clock())*1000))))
    diagnostics['stable_id_observed'] = False
    return None
