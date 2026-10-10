"""微信视频号发布页商品选择器实现。

实现 ProductPicker 契约协议，负责操作视频号实际发布页面（微前端/Iframe）完成商品选择、
弹窗确认、表单绑定完整性核查及清空取消动作。
严禁执行任何“发表”或“保存草稿”动作。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-10-10 | Antigravity | 自动确认‘选择商品出现时机’弹窗，确保遮罩完全关闭且发表按钮无阻碍。 |
| 1.0.0 | 2026-10-10 | Antigravity | 初始实现：适配当前视频号微前端结构，支持完整商品查找、单选确认、表单回读与解绑。 |
"""

from __future__ import annotations

import logging
from typing import Any

from video_processing.core.wechat_product_policy import (
    ProductCatalog, ProductIdentity, ProductLookup,
)

logger = logging.getLogger("wechat_product_picker")


class PlaywrightProductPicker:
    """基于 Playwright Page 的真实微信视频号商品选择适配器。

    满足 ProductPicker 协议，所有交互严格受传入超时控制。
    """

    def __init__(self, page: Any, catalog: ProductCatalog) -> None:
        self.page = page
        self.catalog = catalog

    def _get_content_frame(self) -> Any:
        """获取视频号发表微前端 content frame，若无则回退 top page。"""
        for fr in getattr(self.page, "frames", []):
            if "content/post/create" in getattr(fr, "url", "") or getattr(fr, "name", "") == "content":
                return fr
        return self.page

    def read_binding(self, *, timeout_ms: int) -> ProductIdentity | None:
        """回读表单完整商品身份；None 仅表示已确认无商品，未知必须抛错。"""
        ctx = self._get_content_frame()

        name_info = ctx.evaluate("""() => {
            const nameEl = document.querySelector('.post-component-choose-wrap .choose-content .name');
            if (nameEl && nameEl.innerText.trim()) {
                return { bound: true, title: nameEl.innerText.trim() };
            }
            const chooseContent = document.querySelector('.post-component-choose-wrap .choose-content');
            if (chooseContent && chooseContent.innerText.includes('选择需要添加的商品')) {
                return { bound: false };
            }
            const linkDisplay = document.querySelector('.link-display-wrap');
            if (linkDisplay && linkDisplay.innerText.includes('选择链接')) {
                return { bound: false };
            }
            const closeIcon = document.querySelector('.post-component-choose-wrap .close-icon');
            if (!closeIcon) {
                return { bound: false };
            }
            return { bound: null };
        }""")

        if name_info.get("bound") is False:
            return None
        if name_info.get("bound") is True:
            bound_title = name_info.get("title")
            for prod in self.catalog.products.values():
                if prod.title == bound_title:
                    return prod
            # 若不在当前 catalog 中，返回带未识别 ID 的商品身份，外层将识别为身份冲突并阻断发表
            return ProductIdentity(product_id="unknown_bound_id", title=bound_title)

        raise RuntimeError("无法识别当前发布表单商品绑定状态")

    def _ensure_modal_open(self, timeout_ms: int) -> None:
        """确保商品选择弹窗已打开。"""
        ctx = self._get_content_frame()

        is_open = ctx.evaluate("""() => {
            const dialog = Array.from(document.querySelectorAll('.weui-desktop-dialog, .ant-modal, [class*="dialog"]')).find(
                d => d.offsetParent !== null && document.body.innerText.includes('从橱窗添加商品')
            );
            return !!dialog;
        }""")
        if is_open:
            return

        link_type = ctx.evaluate("""() => {
            const wrap = document.querySelector('.choosen-link-wrap');
            return wrap ? wrap.innerText.trim() : '';
        }""")
        if "商品" not in link_type:
            link_btn = self.page.locator("text=选择链接").first
            if link_btn.count() > 0 and link_btn.is_visible():
                link_btn.click(timeout=min(5000, timeout_ms))
                self.page.wait_for_timeout(500)
                self.page.get_by_text("商品", exact=True).last.click(timeout=min(5000, timeout_ms))
                self.page.wait_for_timeout(1000)

        choose_btn = self.page.locator("text=选择需要添加的商品").first
        if choose_btn.count() > 0 and choose_btn.is_visible():
            choose_btn.click(timeout=min(5000, timeout_ms))
            self.page.wait_for_timeout(1500)

    def find(self, product: ProductIdentity, *, timeout_ms: int) -> ProductLookup:
        """只按 ID 和完整名称查找，唯一且可挂载才返回 AVAILABLE。"""
        self._ensure_modal_open(timeout_ms)
        ctx = self._get_content_frame()

        lookup_result = ctx.evaluate("""(prod) => {
            const trs = Array.from(document.querySelectorAll('tr'));
            let idMatches = 0;
            let titleMatches = 0;
            let exactMatches = [];

            for (const tr of trs) {
                const text = tr.innerText ? tr.innerText.trim() : '';
                if (!text) continue;
                const hasId = text.includes(prod.product_id);
                const hasTitle = text.includes(prod.title);

                if (hasId) idMatches++;
                if (hasTitle) titleMatches++;
                if (hasId && hasTitle) {
                    const radio = tr.querySelector('.ant-radio-input, input[type="radio"]');
                    const disabled = radio ? (radio.disabled || radio.getAttribute('disabled')) : false;
                    exactMatches.push({ disabled: disabled });
                }
            }

            if (exactMatches.length === 1) {
                if (exactMatches[0].disabled) {
                    return 'UNAVAILABLE';
                }
                return 'AVAILABLE';
            }
            if (idMatches > 1 || titleMatches > 1 || (idMatches > 0 && titleMatches > 0 && exactMatches.length === 0)) {
                return 'IDENTITY_CONFLICT';
            }
            return 'UNAVAILABLE';
        }""", {"product_id": product.product_id, "title": product.title})

        if lookup_result == "AVAILABLE":
            return ProductLookup.AVAILABLE
        if lookup_result == "IDENTITY_CONFLICT":
            return ProductLookup.IDENTITY_CONFLICT
        return ProductLookup.UNAVAILABLE

    def select(self, product: ProductIdentity, *, timeout_ms: int) -> None:
        """选择并完成弹窗确认；点击成功并不表示商品已绑定。"""
        self._ensure_modal_open(timeout_ms)
        ctx = self._get_content_frame()

        clicked = ctx.evaluate("""(prod) => {
            const trs = Array.from(document.querySelectorAll('tr'));
            const targetTr = trs.find(tr => tr.innerText && tr.innerText.includes(prod.product_id) && tr.innerText.includes(prod.title));
            if (!targetTr) return false;
            const radio = targetTr.querySelector('.ant-radio-input, input[type="radio"]');
            if (radio) {
                radio.click();
            } else {
                targetTr.click();
            }
            return true;
        }""", {"product_id": product.product_id, "title": product.title})

        if not clicked:
            raise RuntimeError(f"弹窗内未找到要选择的目标商品: {product.product_id}")

        self.page.wait_for_timeout(500)

        # 在可见弹窗内点击“添加(1)”按钮确认
        add_clicked = ctx.evaluate("""() => {
            const dialog = Array.from(document.querySelectorAll('.weui-desktop-dialog, .ant-modal, [class*="dialog"]')).find(
                d => d.offsetParent !== null && d.innerText.includes('从橱窗添加商品')
            );
            if (!dialog) return false;
            const addBtn = Array.from(dialog.querySelectorAll('button, .weui-desktop-btn')).find(
                b => b.innerText && b.innerText.includes('添加')
            );
            if (addBtn) {
                addBtn.click();
                return true;
            }
            return false;
        }""")

        if not add_clicked:
            raise RuntimeError("弹窗内未找到'添加'按钮")

        # 轮询等待弹窗关闭且表单绑定卡片呈现；若出现“选择商品出现时机”弹窗，自动点击“确认”
        bound_name = None
        poll_count = max(1, int(min(10000, timeout_ms) / 500))
        for _ in range(poll_count):
            self.page.wait_for_timeout(500)
            status = ctx.evaluate("""() => {
                // 1. 若出现“选择商品出现时机”弹窗，点击其“确认”按钮
                const timingDialog = Array.from(document.querySelectorAll('.weui-desktop-dialog, .ant-modal, [class*="dialog"]')).find(
                    d => d.offsetParent !== null && d.innerText.includes('选择商品出现时机')
                );
                if (timingDialog) {
                    const confirmBtn = Array.from(timingDialog.querySelectorAll('button, .weui-desktop-btn')).find(
                        b => b.innerText && b.innerText.includes('确认')
                    );
                    if (confirmBtn) {
                        confirmBtn.click();
                    }
                }

                // 2. 检查所有商品相关弹窗是否已完全关闭
                const dialog = Array.from(document.querySelectorAll('.weui-desktop-dialog, .ant-modal, [class*="dialog"]')).find(
                    d => d.offsetParent !== null && (d.innerText.includes('从橱窗添加商品') || d.innerText.includes('选择商品出现时机'))
                );
                const nameEl = document.querySelector('.post-component-choose-wrap .choose-content .name');
                return {
                    dialogOpen: !!dialog,
                    name: nameEl ? nameEl.innerText.trim() : null
                };
            }""")
            if not status.get("dialogOpen") and status.get("name"):
                bound_name = status.get("name")
                break

        if not bound_name:
            raise TimeoutError("SELECT_CONFIRM_DOM_UPDATE_TIMEOUT")

    def cancel_and_clear(self, *, timeout_ms: int) -> bool:
        """取消选择并核实无商品、无残留弹窗；未知返回 False。"""
        ctx = self._get_content_frame()

        # 1. 若弹窗处于打开状态，点击取消并按 Escape
        ctx.evaluate("""() => {
            const cancelBtn = Array.from(document.querySelectorAll('button, .weui-desktop-btn')).find(
                b => b.innerText && b.innerText.trim() === '取消'
            );
            if (cancelBtn && cancelBtn.offsetParent !== null) {
                cancelBtn.click();
            }
        }""")
        self.page.keyboard.press("Escape")
        self.page.wait_for_timeout(500)

        # 2. 若表单已绑定商品，点击 close-icon 清除
        ctx.evaluate("""() => {
            const closeBtn = document.querySelector('.post-component-choose-wrap .close-icon');
            if (closeBtn) {
                closeBtn.click();
            }
        }""")
        self.page.wait_for_timeout(500)

        # 3. 验证无残留弹窗且无商品名称
        is_cleared = ctx.evaluate("""() => {
            const dialog = Array.from(document.querySelectorAll('.weui-desktop-dialog, .ant-modal, [class*="dialog"]')).find(
                d => d.offsetParent !== null && (d.innerText.includes('从橱窗添加商品') || d.innerText.includes('选择商品出现时机'))
            );
            const boundName = document.querySelector('.post-component-choose-wrap .choose-content .name');
            return !dialog && !boundName;
        }""")
        return bool(is_cleared)

    def ready_to_submit(self, *, timeout_ms: int) -> bool:
        """正向确认商品弹窗关闭且表单可操作；不是发表授权。"""
        ctx = self._get_content_frame()

        ready = bool(ctx.evaluate("""() => {
            const dialog = Array.from(document.querySelectorAll('.weui-desktop-dialog, .ant-modal, [class*="dialog"]')).find(
                d => d.offsetParent !== null && (d.innerText.includes('从橱窗添加商品') || d.innerText.includes('选择商品出现时机'))
            );
            if (dialog) return false;

            const publishBtn = Array.from(document.querySelectorAll('button, .weui-desktop-btn')).find(
                b => b.innerText && b.innerText.trim() === '发表'
            );
            return !!(publishBtn && publishBtn.offsetParent !== null);
        }"""))
        return ready
