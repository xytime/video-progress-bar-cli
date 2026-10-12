"""只在合成 DOM 中验证真实 Chromium 行为，不访问外部网络或微信。

验证：
1. 公众号文章选择器在微前端/DOM 中的注入、跨主体确认与回读；
2. 文章身份冲突拦截与安全清退；
3. 商品选择器 B02 缺陷修复（空搜索容器无 .name 时 cancel_and_clear 顺利销毁）；
4. 商品与文章挂接状态互斥识别；
5. 一期全流程在真实无头浏览器中的端到端闭环。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-12 | Codex | 初始实现：文章选择器交互、跨主体确认、清退核验与 B02 缺陷修复隔离验证。 |
"""

import json
import pytest

from tests.browser_fixtures import chromium
from video_processing.core.wechat_article_policy import ArticleIdentity
from video_processing.core.wechat_product_policy import ProductIdentity
from video_processing.utils.wechat_article_picker import PlaywrightArticlePicker
from video_processing.utils.wechat_product_picker import PlaywrightProductPicker, BindingIdentityUnavailable
from video_processing.utils.wechat_article_execution import (
    execute_article_task,
    finalize_article_before_submit,
    finalize_none_before_submit,
)


ARTICLE_TARGET = ArticleIdentity(
    url="https://mp.weixin.qq.com/s/sample_article_token_12345",
    title="测试精选文章",
)
PRODUCT_TARGET = ProductIdentity("prod_999", "精选图书商品")


@pytest.fixture
def page(chromium):
    context = chromium.new_context()
    context.route("**/*", lambda route: route.abort())
    p = context.new_page()
    yield p
    context.close()


def article_form_html():
    return """
    <div id="container">
      <div class="link-display-wrap" onclick="toggleDropdown()">选择链接</div>
      <div class="choosen-link-wrap" style="display:none;"></div>
      
      <div class="weui-desktop-dropdown__list" id="dropdown" hidden>
        <div class="option-item" onclick="openArticleDialog()">公众号文章</div>
        <div class="option-item" onclick="openProductDialog()">商品</div>
      </div>

      <!-- 公众号文章输入弹窗 -->
      <div role="dialog" class="weui-desktop-dialog" id="article_dialog" hidden>
        <div class="weui-desktop-dialog__hd">添加公众号文章</div>
        <div class="weui-desktop-dialog__bd">
          <input type="text" placeholder="请输入公众号文章链接" id="article_input" />
        </div>
        <div class="weui-desktop-dialog__ft">
          <button id="article_cancel" onclick="closeArticleDialog()">取消</button>
          <button id="article_confirm" onclick="submitArticle()">添加</button>
        </div>
      </div>

      <!-- 跨主体确认弹窗 -->
      <div role="dialog" class="weui-desktop-dialog" id="cross_dialog" hidden>
        <div class="weui-desktop-dialog__hd">该文章属于其他公众号，确认添加？</div>
        <div class="weui-desktop-dialog__ft">
          <button onclick="document.querySelector('#cross_dialog').hidden=true">取消</button>
          <button id="cross_confirm" onclick="confirmCross()">确定</button>
        </div>
      </div>

      <!-- 挂接卡片容器 -->
      <div class="post-component-choose-wrap" id="card_wrap" hidden>
        <div class="choose-content" id="card_content"></div>
        <button class="close-icon" onclick="removeCard()">移除</button>
      </div>

      <button id="publish_btn">发表</button>
    </div>

    <script>
      let currentUrl = '';
      function toggleDropdown() {
        const d = document.querySelector('#dropdown');
        d.hidden = !d.hidden;
      }
      function openArticleDialog() {
        document.querySelector('#dropdown').hidden = true;
        document.querySelector('#article_dialog').hidden = false;
      }
      function closeArticleDialog() {
        document.querySelector('#article_dialog').hidden = true;
      }
      function submitArticle() {
        currentUrl = document.querySelector('#article_input').value;
        document.querySelector('#article_dialog').hidden = true;
        // 模拟跨主体确认弹窗出现
        document.querySelector('#cross_dialog').hidden = false;
      }
      function confirmCross() {
        document.querySelector('#cross_dialog').hidden = true;
        document.querySelector('#container .link-display-wrap').hidden = true;
        const cardWrap = document.querySelector('#card_wrap');
        cardWrap.hidden = false;
        document.querySelector('#card_content').outerHTML = `
          <div class="choose-content" data-url="${currentUrl}" id="card_content">
            <a href="${currentUrl}" class="title">测试精选文章</a>
            <span class="name">测试精选文章</span>
          </div>`;
      }
      function removeCard() {
        document.querySelector('#card_wrap').hidden = true;
        document.querySelector('#container .link-display-wrap').hidden = false;
        document.querySelector('#card_content').outerHTML = '<div class="choose-content" id="card_content"></div>';
        currentUrl = '';
      }
    </script>
    """


def test_article_picker_attach_and_cross_confirm_flow(page):
    """测试完整公众号文章注入、跨主体确认、卡片生成与回读。"""
    page.set_content(article_form_html())
    picker = PlaywrightArticlePicker(page)

    assert picker.read_binding(timeout_ms=500) is None
    assert picker.ready_to_submit(timeout_ms=500) is True

    picker.attach(ARTICLE_TARGET, timeout_ms=5000)

    # 回读确认卡片正确绑定
    actual = picker.read_binding(timeout_ms=500)
    assert actual is not None
    assert actual.url == ARTICLE_TARGET.url
    assert actual.title == ARTICLE_TARGET.title
    assert picker.ready_to_submit(timeout_ms=500) is True


def test_article_picker_cancel_and_clear(page):
    """测试 cancel_and_clear 清退弹窗及卡片，恢复 unbound 状态。"""
    page.set_content(article_form_html())
    picker = PlaywrightArticlePicker(page)
    picker.attach(ARTICLE_TARGET, timeout_ms=5000)
    assert picker.read_binding(timeout_ms=500) is not None

    # 清退
    cleared = picker.cancel_and_clear(timeout_ms=1000)
    assert cleared is True
    assert picker.read_binding(timeout_ms=500) is None
    assert picker.ready_to_submit(timeout_ms=500) is True


def test_article_picker_identity_mismatch_blocks(page):
    """测试当页面生成的实际卡片 URL 与预期不一致时，严格抛出异常阻断。"""
    page.set_content(article_form_html())
    # 篡改确认逻辑生成其他 URL
    page.evaluate("() => { window.confirmCross = function() { document.querySelector('#cross_dialog').hidden=true; document.querySelector('#card_wrap').hidden=false; document.querySelector('#card_content').outerHTML = '<div class=\"choose-content\" data-url=\"https://mp.weixin.qq.com/s/wrong_url\" id=\"card_content\"><span class=\"name\">不同文章</span></div>'; }; }")

    picker = PlaywrightArticlePicker(page)
    with pytest.raises(BindingIdentityUnavailable, match="SELECTED_ARTICLE_URL_MISMATCH"):
        picker.attach(ARTICLE_TARGET, timeout_ms=5000)


def test_product_picker_b02_fix_cancel_and_clear_without_name(page):
    """验证 B02 修复：空商品搜索容器（无 .name）时，cancel_and_clear 仍可正确点击关闭。"""
    html = """
    <div class="post-component-choose-wrap">
      <div class="choose-content">选择需要添加的商品</div>
      <button class="close-icon" onclick="this.parentElement.outerHTML='<div class=link-display-wrap>选择链接</div>'">关闭</button>
    </div>
    <button>发表</button>
    """
    page.set_content(html)
    product_picker = PlaywrightProductPicker(page)

    cleared = product_picker.cancel_and_clear(timeout_ms=1000)
    assert cleared is True
    assert product_picker.read_binding(timeout_ms=500) is None
    assert product_picker.ready_to_submit(timeout_ms=500) is True


def test_article_and_product_status_mutual_exclusion(page):
    """测试商品卡片与文章卡片的状态互斥读取。"""
    # 场景 1: 商品卡片在页面
    product_html = f'<div class="choosen-link-wrap">商品</div><div class="post-component-choose-wrap"><div class="choose-content" data-product-id="{PRODUCT_TARGET.product_id}"><span class="name">{PRODUCT_TARGET.title}</span></div></div><button>发表</button>'
    page.set_content(product_html)

    product_picker = PlaywrightProductPicker(page)
    article_picker = PlaywrightArticlePicker(page)

    # 商品读取器识别出商品
    assert product_picker.read_binding(timeout_ms=500) == PRODUCT_TARGET
    # 文章读取器拒绝将其作为文章，抛出明确异常而不是静默 None
    with pytest.raises(BindingIdentityUnavailable, match="NON_ARTICLE_ATTACHMENT_PRESENT:PRODUCT"):
        article_picker.read_binding(timeout_ms=500)

    # 场景 2: 文章卡片在页面
    article_html = f'<div class="choosen-link-wrap">公众号文章</div><div class="post-component-choose-wrap"><div class="choose-content" data-url="{ARTICLE_TARGET.url}"><span class="name">{ARTICLE_TARGET.title}</span></div></div><button>发表</button>'
    page.set_content(article_html)

    # 文章读取器识别出文章
    actual_art = article_picker.read_binding(timeout_ms=500)
    assert actual_art == ARTICLE_TARGET
    # 商品读取器因缺少商品 ID 抛出异常，严禁转成 None
    with pytest.raises(BindingIdentityUnavailable):
        product_picker.read_binding(timeout_ms=500)


def test_browser_end_to_end_article_execution_and_pre_submit_gate(page, tmp_path):
    """在真实 Chromium 页面中端到端验证 execute_article_task 与 finalize_article_before_submit。"""
    page.set_content(article_form_html())
    picker = PlaywrightArticlePicker(page)
    payload = {"task_id": "browser_task_1", "url": ARTICLE_TARGET.url, "title": ARTICLE_TARGET.title}

    # 执行注入
    ok = execute_article_task(payload, picker, tmp_path)
    assert ok is True
    receipt = json.loads((tmp_path / "article_selection_receipt.json").read_text())
    assert receipt["state"] == "BOUND"

    # Step 5 终验
    assert finalize_article_before_submit(payload, picker, tmp_path) is True
    readback = json.loads((tmp_path / "article_pre_submit_readback.json").read_text())
    assert readback["final_verified"] is True
    assert readback["actual_url"] == ARTICLE_TARGET.url

    # 验证发表前若卡片被清空，终验必须失败
    picker.cancel_and_clear(timeout_ms=1000)
    assert finalize_article_before_submit(payload, picker, tmp_path) is False


def test_article_picker_recognizes_product_child_attributes(page):
    """测试当商品 ID 位于子元素链接或属性时，文章选择器依然将其准确互斥识别为 PRODUCT。"""
    # 无 choosen-link-wrap 显式标识，data-product-id 位于子链接
    html = f'''
    <div class="post-component-choose-wrap">
      <div class="choose-content">
        <a href="https://channels.weixin.qq.com/shop?productId={PRODUCT_TARGET.product_id}" class="name">{PRODUCT_TARGET.title}</a>
      </div>
    </div>
    <button>发表</button>
    '''
    page.set_content(html)
    article_picker = PlaywrightArticlePicker(page)
    with pytest.raises(BindingIdentityUnavailable, match="NON_ARTICLE_ATTACHMENT_PRESENT:PRODUCT"):
        article_picker.read_binding(timeout_ms=500)


def test_article_picker_cancel_and_clear_with_confirm_dialog(page):
    """测试当点击移除后弹出二次确认弹窗时，cancel_and_clear 能够正确点击确认并恢复 unbound。"""
    html = '''
    <div id="container">
      <div class="link-display-wrap" style="display:none;">选择链接</div>
      <div class="post-component-choose-wrap" id="card_wrap">
        <div class="choose-content" data-url="__URL__">
          <span class="name">__TITLE__</span>
        </div>
        <button class="close-icon" onclick="document.querySelector('#confirm_remove_dialog').hidden=false">移除</button>
      </div>

      <!-- 二次移除确认弹窗 -->
      <div role="dialog" class="weui-desktop-dialog" id="confirm_remove_dialog" hidden>
        <div class="weui-desktop-dialog__hd">确认移除该公众号文章链接？</div>
        <div class="weui-desktop-dialog__ft">
          <button onclick="document.querySelector('#confirm_remove_dialog').hidden=true">取消</button>
          <button id="btn_confirm_remove" onclick="doRemove()">确定</button>
        </div>
      </div>

      <button>发表</button>
    </div>
    <script>
      function doRemove() {
        document.querySelector('#confirm_remove_dialog').hidden = true;
        document.querySelector('#card_wrap').outerHTML = '';
        document.querySelector('.link-display-wrap').style.display = 'block';
      }
    </script>
    '''.replace("__URL__", ARTICLE_TARGET.url).replace("__TITLE__", ARTICLE_TARGET.title)

    page.set_content(html)
    picker = PlaywrightArticlePicker(page)
    assert picker.read_binding(timeout_ms=500) is not None

    cleared = picker.cancel_and_clear(timeout_ms=2000)
    assert cleared is True
    assert picker.read_binding(timeout_ms=500) is None
    assert picker.ready_to_submit(timeout_ms=500) is True

