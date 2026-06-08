import re

with open("scripts/wechat_uploader.py", "r", encoding="utf-8") as f:
    code = f.read()

target = """                        # 策略1: get_by_role("dialog") 语义最精准
                        for btn_name in ["确认", "确定", "完成", "下一步", "应用"]:
                            try:
                                btn = page.get_by_role("dialog").get_by_role("button", name=btn_name).last
                                if btn.count() > 0 and btn.is_visible() and btn.get_attribute("disabled") is None:
                                    btn.click(force=True)
                                    logger.info(f"[P0] Cover confirmed via get_by_role button: \\'{btn_name}\\'")
                                    confirmed = True
                                    break
                            except Exception:
                                continue

                        # 策略2: 降级 — 在 dialog__ft（微信弹窗底部按钮栏）找
                        if not confirmed:
                            for btn_name in ["确认", "确定", "完成", "下一步", "应用"]:
                                try:
                                    btn = page.locator(".weui-desktop-dialog__ft").last.get_by_role("button", name=btn_name)
                                    if btn.count() > 0 and btn.is_visible() and btn.get_attribute("disabled") is None:
                                        btn.click(force=True)
                                        logger.info(f"[P0] Cover confirmed via dialog__ft button: \\'{btn_name}\\'")
                                        confirmed = True
                                        break
                                except Exception:
                                    continue"""

replacement = """                        # 策略1: 综合遍历所有的弹窗与按钮结构
                        for btn_name in ["确认", "确定", "完成", "下一步", "应用"]:
                            for dialog_sel in [".weui-desktop-dialog", "div[role='dialog']"]:
                                try:
                                    d_loc = page.locator(dialog_sel).last
                                    if d_loc.count() > 0 and d_loc.is_visible():
                                        for target_sel in [
                                            f"button:has-text('{btn_name}')",
                                            f".weui-desktop-btn:has-text('{btn_name}')",
                                            f".weui-desktop-dialog__ft div:has-text('{btn_name}')",
                                            f"text={btn_name}"
                                        ]:
                                            btn = d_loc.locator(target_sel).last
                                            if btn.count() > 0 and btn.is_visible() and btn.get_attribute("disabled") is None:
                                                try:
                                                    btn.click(timeout=1500, force=True)
                                                except:
                                                    btn.evaluate("node => node.click()")
                                                logger.info(f"[Strategy A] Cover confirmed via '{btn_name}' (selector: {target_sel})")
                                                confirmed = True
                                                cover_set = True
                                                break
                                except Exception:
                                    pass
                                if confirmed:
                                    break
                            if confirmed:
                                break"""

code = code.replace(target, replacement)

with open("scripts/wechat_uploader.py", "w", encoding="utf-8") as f:
    f.write(code)

print("Patched.")
