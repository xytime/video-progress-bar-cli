"""真实浏览器验证原生组件身份和状态范围，不按标题或列表位置绑定。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-10-10 | Codex | 验证原生 nonce 和已发表日期同一卡片绑定及时间拒绝边界。 |
| 1.0.0 | 2026-10-03 | Codex | 验证组件原生 ID、独立状态标签、隐藏和重复记录的拒绝。 |
"""
from tests.browser_fixtures import chromium
from scripts.wechat_uploader import _collect_management_cards, _management_public_time


def test_native_component_binds_own_status_without_description_spoof(chromium):
    page = chromium.new_page()
    try:
        page.set_content('''<div class="post-feed-item"><p>标题：已发布</p>
            <div class="bandage-list">审核中</div></div>
            <div class="post-feed-item" style="display:none"><div class="bandage-list">已发布</div></div>''')
        page.locator('.post-feed-item').evaluate_all('''nodes => nodes.forEach((node,i) => {
            node.__vue__ = {$props: {post: {objectId: i ? 'hidden' : 'native-id', exportId: 'export-id',objectNonce:'12345678901234567890'}}};
        })''')
        cards = _collect_management_cards(page)
        assert list(cards) == ['native-id']
        assert cards['native-id']['status_text'] == '审核中'
        assert cards['native-id']['platform_export_id'] == 'export-id'
        assert cards['native-id']['platform_object_nonce'] == '12345678901234567890'
        page.locator('.post-feed-item').first.evaluate('node => node.__vue__.$props.post.objectNonce=12345678901234567890')
        assert 'platform_object_nonce' not in _collect_management_cards(page)['native-id']
    finally:
        page.close()


def test_public_date_is_bound_to_same_native_component(chromium):
    page=chromium.new_page()
    try:
        page.set_content('<div class="post-feed-item"><div class="posted-info"></div></div>')
        page.locator('.post-feed-item').evaluate('''node => {
            const stamp=1791579858,d=new Date(stamp*1000);
            node.querySelector('.posted-info').innerText=`${d.getFullYear()}年${d.getMonth()+1}月${d.getDate()}日 ${d.getHours()}:${String(d.getMinutes()).padStart(2,'0')}`;
            node.__vue__={$props:{post:{objectId:'native',createTime:stamp,visibleType:0}},
                VisibleType:{public:0},isPostHasPosted:true,isPostProcessSuccess:true,
                isPostProcessing:false,isTimePublish:false};
        }''')
        record=_collect_management_cards(page)['native']
        assert _management_public_time(record,'PUBLISHED')['platform_public_at']==1791579858
        assert _management_public_time(record,'UNDER_REVIEW')=={}
        assert _management_public_time({**record,'native_time_parts':[2020,1,1,0,0]},'PUBLISHED')=={}
        assert _management_public_time({**record,'native_create_time':'1791579858'},'PUBLISHED')=={}
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
