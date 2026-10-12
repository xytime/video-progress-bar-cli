"""微信视频号发布页公众号文章扩展链接选择器实现。

实现 ArticlePicker 契约协议，负责操作视频号实际发布页面（微前端/Iframe）完成公众号文章链接注入、
跨主体弹窗确认、表单绑定完整性核查及清空取消动作。
严禁执行任何“发表”或“保存草稿”动作。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-10-12 | Antigravity | 增强微前端商品卡片互斥识别（支持子元素属性与链接）；cancel_and_clear 支持二次移除确认弹窗。 |
| 1.0.0 | 2026-10-12 | Codex | 初始实现：支持公众号文章注入、跨主体确认、表单回读、身份冲突拦截与安全清退。 |
"""

from __future__ import annotations

from time import monotonic
from typing import Any

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from video_processing.core.wechat_article_policy import ArticleIdentity, is_valid_mp_article_url
from video_processing.utils.wechat_product_picker import BindingIdentityUnavailable


_ARTICLE_DOM = r"""
const visible = e => !!e && !!e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden';
const text = e => (e?.innerText || '').trim();
const enabled = e => visible(e) && !e.disabled && e.getAttribute('aria-disabled') !== 'true';

const dialogs = () => Array.from(scope.querySelectorAll('.weui-desktop-dialog, .ant-modal, [role="dialog"], .dialog-wrap'))
    .filter(d => visible(d));

const articleDialogs = () => dialogs().filter(d => /公众号文章|添加链接|扩展链接|该文章属于/.test(text(d)));

const button = (d, re) => Array.from(d.querySelectorAll('button, .weui-desktop-btn, [role="button"], a.btn')).find(b => enabled(b) && re.test(text(b)));

const binding = () => {
    // 检查是否有商品卡片（如果是商品，明确标识为 PRODUCT）
    const productCards = Array.from(scope.querySelectorAll('.post-component-choose-wrap .choose-content')).filter(visible);
    const chosenLinkWraps = Array.from(scope.querySelectorAll('.choosen-link-wrap')).filter(visible);
    if (chosenLinkWraps.some(e => text(e).includes('商品')) ||
        productCards.some(c => c.hasAttribute('data-product-id') || !!c.querySelector('[data-product-id], a[href*="productId"], a[href*="product_id"]'))) {
        return {type: 'PRODUCT'};
    }


    // 检查是否有文章卡片
    const articleCards = Array.from(scope.querySelectorAll('.post-component-choose-wrap .choose-content, .article-link-wrap, .link-display-wrap')).filter(visible);
    for (const card of articleCards) {
        // 如果只是未选择占位
        if (text(card) === '选择链接' || text(card).includes('选择需要添加的商品') || text(card).includes('从公众号添加')) {
            continue;
        }
        let url = card.getAttribute('data-url') || card.getAttribute('data-link') || card.getAttribute('data-article-url');
        if (!url) {
            const anchor = card.querySelector('a[href*="mp.weixin.qq.com"]');
            if (anchor) url = anchor.getAttribute('href');
        }
        if (!url) {
            // 尝试从包含 mp.weixin.qq.com 的文本中提取
            const cardText = text(card);
            const m = cardText.match(/https?:\/\/mp\.weixin\.qq\.com\/s[^\s"'>]*/);
            if (m) url = m[0];
        }
        if (url) {
            const titleElem = card.querySelector('.name, .title, .article-title, a[title]');
            const title = titleElem ? (titleElem.getAttribute('title') || text(titleElem)) : text(card).split('\n')[0];
            return {type: 'ARTICLE', url: url.trim(), title: (title || '').trim()};
        }
        // 如果容器存在且非占位但取不到有效信息，返回未知
        if (card.querySelector('.name, .title') || text(card)) {
            return {unknown: true};
        }
    }

    // 检查明确的未绑定状态
    if (chosenLinkWraps.some(e => text(e).includes('选择链接')) ||
        Array.from(scope.querySelectorAll('.link-display-wrap')).some(e => visible(e) && text(e) === '选择链接') ||
        articleCards.some(c => text(c).includes('选择需要添加的商品'))) {
        return {unbound: true};
    }

    // 没有任何挂接组件
    if (!articleCards.length && !productCards.length) {
        return {unbound: true};
    }

    return {unknown: true};
};
"""


class PlaywrightArticlePicker:
    """公众号文章扩展链接界面适配器。所有操作遵守截止时间，不推断身份。"""

    def __init__(self, page: Any, *, clock=monotonic) -> None:
        self.page = page
        self.clock = clock

    def _get_content_frame(self) -> Any:
        controls = self.page.locator('.post-component-choose-wrap:visible, .link-display-wrap:visible')
        if controls.count():
            return self.page
        frames = []
        for frame in getattr(self.page, "frames", []):
            if "content/post/create" in getattr(frame, "url", "") or getattr(frame, "name", "") == "content":
                if frame.frame_element().is_visible():
                    frames.append(frame)
        if len(frames) > 1:
            raise BindingIdentityUnavailable("ARTICLE_VISIBLE_FRAME_CONFLICT")
        return frames[0] if frames else self.page

    def _end(self, timeout_ms: int, cap_ms: int = 10000) -> float:
        if timeout_ms <= 0:
            raise TimeoutError("ARTICLE_OPERATION_TIMEOUT")
        return self.clock() + min(timeout_ms, cap_ms) / 1000

    def _remaining(self, end: float) -> int:
        remaining = int((end - self.clock()) * 1000)
        if remaining <= 0:
            raise TimeoutError("ARTICLE_OPERATION_TIMEOUT")
        return remaining

    def _eval(self, code: str, end: float, arg=None):
        ctx = self._get_content_frame()
        try:
            anchor = ctx.locator('.post-component-choose-wrap:visible, .link-display-wrap:visible').first
            if not anchor.count():
                anchor = ctx.locator("body").first
            value = anchor.evaluate(
                "(root, arg) => {const scope = root.getRootNode();" + _ARTICLE_DOM + code + "}", arg,
                timeout=self._remaining(end),
            )
        except PlaywrightTimeoutError as exc:
            raise TimeoutError("ARTICLE_OPERATION_TIMEOUT") from exc
        self._remaining(end)
        return value

    def _poll(self, code: str, end: float, arg=None):
        while True:
            value = self._eval(code, end, arg)
            if value:
                return value
            self.page.wait_for_timeout(min(50, self._remaining(end)))

    def _open(self, end: float):
        """打开添加公众号文章的弹窗。"""
        if self._eval("return articleDialogs().length > 0;", end):
            return
        ctx = self._get_content_frame()
        try:
            # 查找并点击“选择链接”
            link_btn = ctx.locator('.choosen-link-wrap, .link-display-wrap, button:has-text("选择链接"), span:has-text("选择链接")').filter(has_text="选择链接")
            if link_btn.count():
                link_btn.first.click(timeout=self._remaining(end))
            elif not self._eval("return Array.from(scope.querySelectorAll('.choosen-link-wrap')).some(e => visible(e) && text(e).includes('公众号文章'));", end):
                ctx.get_by_text("选择链接", exact=True).click(timeout=self._remaining(end))

            # 点击下拉菜单中的“公众号文章”
            self.page.wait_for_timeout(min(100, max(10, self._remaining(end))))
            option = ctx.locator('.weui-desktop-dropdown__list-item, .option-item, li, [role="option"]').filter(has_text="公众号文章")
            if option.count():
                option.first.click(timeout=self._remaining(end))
            else:
                ctx.get_by_text("公众号文章", exact=True).first.click(timeout=self._remaining(end))
        except PlaywrightTimeoutError as exc:
            raise TimeoutError("ARTICLE_OPERATION_TIMEOUT") from exc

        self._poll("return articleDialogs().length > 0;", end)

    def read_binding(self, *, timeout_ms: int) -> ArticleIdentity | None:
        """从页面实读文章挂接状态。

        Returns:
            ArticleIdentity 如果页面挂接了公众号文章；
            None 如果页面明确未挂接（unbound）；
        Raises:
            BindingIdentityUnavailable: 如果页面挂接了商品、未知卡片或处于读取异常状态。
        """
        end = self._end(timeout_ms)
        info = self._eval("return binding();", end)
        if info.get("unbound"):
            return None
        if info.get("type") == "PRODUCT":
            raise BindingIdentityUnavailable("NON_ARTICLE_ATTACHMENT_PRESENT:PRODUCT")
        if info.get("type") == "ARTICLE" and info.get("url"):
            return ArticleIdentity(url=info["url"], title=info.get("title", ""))
        raise BindingIdentityUnavailable("ARTICLE_ACTUAL_URL_OR_CARD_UNAVAILABLE")

    def attach(self, article: ArticleIdentity, *, timeout_ms: int) -> None:
        """注入公众号文章链接并完成弹窗确认与回读核验。"""
        if not is_valid_mp_article_url(article.url):
            raise ValueError(f"非法文章 URL 拒绝注入: {article.url!r}")

        end = self._end(timeout_ms)

        # 检查是否已存在挂接
        existing_info = self._eval("return binding();", end)
        if existing_info.get("type") == "ARTICLE":
            if existing_info.get("url") == article.url:
                return
            raise BindingIdentityUnavailable("EXISTING_LINK_CONFLICT:ARTICLE_URL_MISMATCH")
        if existing_info.get("type") == "PRODUCT":
            raise BindingIdentityUnavailable("EXISTING_LINK_CONFLICT:PRODUCT_ALREADY_ATTACHED")

        # 打开公众号文章弹窗
        self._open(end)
        ctx = self._get_content_frame()

        # 定位文章 URL 输入框并填入 URL
        input_loc = ctx.locator(
            "input[placeholder*='公众号文章'], input[placeholder*='链接'], input[placeholder*='http'], "
            ".weui-desktop-dialog input, [role='dialog'] input"
        ).first
        if not input_loc.count():
            raise BindingIdentityUnavailable("ARTICLE_INPUT_FIELD_NOT_FOUND")

        try:
            input_loc.fill(article.url, timeout=self._remaining(end))
        except PlaywrightTimeoutError as exc:
            raise TimeoutError("ARTICLE_OPERATION_TIMEOUT") from exc

        # 点击确定/添加按钮
        confirm_clicked = self._eval(r"""
            for (const d of articleDialogs()) {
                const b = button(d, /^(确定|添加|确认)$/);
                if (b) { b.click(); return true; }
            }
            return false;
        """, end)
        if not confirm_clicked:
            raise BindingIdentityUnavailable("ARTICLE_CONFIRM_BUTTON_NOT_FOUND")

        # 处理可能出现的跨主体确认弹窗（例如“该文章属于其他公众号，确认添加？”）
        self.page.wait_for_timeout(min(150, max(10, self._remaining(end))))
        self._eval(r"""
            for (const d of dialogs().filter(d => /跨主体|属于其他公众号|确认添加/.test(text(d)))) {
                const b = button(d, /^(确定|确认|继续添加|我已知晓)$/);
                if (b) b.click();
            }
        """, end)

        # 等待所有弹窗关闭，且文章卡片生成
        self._poll("return !dialogs().length && binding().type === 'ARTICLE';", end)

        # 最终回读核对实际 URL
        actual = self.read_binding(timeout_ms=self._remaining(end))
        if actual is None or actual.url != article.url:
            raise BindingIdentityUnavailable(
                f"SELECTED_ARTICLE_URL_MISMATCH: expected {article.url}, got {actual.url if actual else None}"
            )

    def cancel_and_clear(self, *, timeout_ms: int) -> bool:
        """真实控件清退：关闭所有弹窗，点击删除/解绑控件，并核验四项齐备。"""
        end = self._end(timeout_ms, 3000)
        # 点击所有弹窗上的取消/关闭按钮
        self._eval(r"for (const d of dialogs()) { const b = button(d, /^(取消|关闭)$/); if (b) b.click(); }", end)
        # 点击挂接卡片上的真实关闭/移除控件
        self._eval(r"""
            let b = scope.querySelector(
                '.post-component-choose-wrap .close-icon, .post-component-choose-wrap button.close-icon, ' +
                '.post-component-choose-wrap [class*="close"], .article-link-wrap .close-icon, ' +
                '.link-display-wrap .close-icon'
            );
            if (!visible(b)) {
                b = Array.from(scope.querySelectorAll('button, .btn, [role="button"]'))
                    .find(e => visible(e) && (/^(移除|删除|×|x)$/i.test(text(e)) || e.classList.contains('close-icon')));
            }
            if (visible(b)) b.click();
            // 处理点击移除后可能弹出的二次确认弹窗（如“确定删除/移除该链接？”）
            for (const d of dialogs().filter(d => /确定|确认|移除|删除/.test(text(d)))) {
                const cb = button(d, /^(确定|确认)$/);
                if (cb) cb.click();
            }
        """, end)
        # 轮询确认弹窗销毁且恢复未绑定状态
        return bool(self._poll("return !dialogs().length && binding().unbound === true;", end))


    def ready_to_submit(self, *, timeout_ms: int) -> bool:
        """正向确认无弹窗遮挡且发表按钮可用。"""
        return bool(self._eval("return !dialogs().length && !!button(scope, /^发表$/);", self._end(timeout_ms)))
