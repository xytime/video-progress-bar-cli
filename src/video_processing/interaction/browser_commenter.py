"""视频号评论管理后台 Playwright 自动化执行器。

负责通过无头浏览器登录态访问互动管理后台，完成目标作品精准定位、
重复发评防御、多行评论填入、接口 errCode 校验、DOM 真实回读与证据链留存。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-09-19 | Antigravity | 加固安全：彻底移除第一卡片回退，实现 objectId 精确绑定、接口 errCode==0 拦截与 DOM 回读闭环 |
| 1.0.0 | 2026-09-19 | Antigravity | 初始创建：实现带排他锁的视频号评论自动化与证据链 |
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

from playwright.sync_api import sync_playwright

from config.settings import settings

logger = logging.getLogger(__name__)

WECHAT_COMMENT_URL = "https://channels.weixin.qq.com/platform/interaction/comment"
DEFAULT_STATE_FILE = Path(__file__).resolve().parents[3] / "output" / "wechat_state.json"
DEFAULT_LOCK_FILE = Path(__file__).resolve().parents[3] / "output" / ".wechat_browser.lock"


class BrowserCommenter:
    """视频号评论自动化执行器。"""

    def __init__(
        self,
        *,
        state_path: Path | str = DEFAULT_STATE_FILE,
        lock_path: Path | str = DEFAULT_LOCK_FILE,
        headless: bool = True,
    ) -> None:
        self.state_path = Path(state_path)
        self.lock_path = Path(lock_path)
        self.headless = headless

    def post_comment(
        self,
        *,
        comment_text: str,
        platform_post_id: str,
        video_title: Optional[str] = None,
        evidence_dir: Optional[Path | str] = None,
    ) -> Tuple[str, Optional[str], Optional[str]]:
        """执行发评流程。

        Args:
            comment_text: 格式化后的多行评论文本。
            platform_post_id: 微信原生 post_id（必填，拒绝模糊盲发）。
            video_title: 辅助核验的视频标题。
            evidence_dir: 证据保存目录。

        Returns:
            Tuple of (status, evidence_path, error_message)
            status in {"COMMENTED", "SKIPPED_EXISTS", "PENDING_REVIEW", "FAILED"}
        """
        clean_post_id = str(platform_post_id or "").strip()
        if not clean_post_id:
            return "FAILED", None, "必须提供有效的 platform_post_id 进行精确定位，严禁盲发"

        if not self.state_path.exists():
            return "FAILED", None, f"登录凭据不存在: {self.state_path}"

        evidence_root = Path(evidence_dir) if evidence_dir else self.state_path.parent / "wechat_evidence" / "interactions"
        evidence_root.mkdir(parents=True, exist_ok=True)

        # 获取跨进程文件锁，避免与 keepalive 或上传抢占会话
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.lock_path, "w") as lock_file:
            try:
                fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (BlockingIOError, OSError):
                logger.warning("[BrowserCommenter] 另一个浏览器进程正在运行，等待锁释放...")
                fcntl.flock(lock_file, fcntl.LOCK_EX)

            try:
                return self._do_post(
                    comment_text=comment_text,
                    platform_post_id=clean_post_id,
                    video_title=video_title,
                    evidence_root=evidence_root,
                )
            finally:
                try:
                    fcntl.flock(lock_file, fcntl.LOCK_UN)
                except Exception:
                    pass

    def _do_post(
        self,
        *,
        comment_text: str,
        platform_post_id: str,
        video_title: Optional[str],
        evidence_root: Path,
    ) -> Tuple[str, Optional[str], Optional[str]]:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=self.headless,
                args=[
                    "--disable-web-security",
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                    "--window-size=1280,800",
                    "--no-proxy-server",
                ],
            )
            context = browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
                storage_state=str(self.state_path),
            )
            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => false });
                window.chrome = { runtime: {}, loadTimes: function(){}, csi: function(){}, app: {} };
            """)
            page = context.new_page()

            # 1. 监听接口数据，获取原生 objectId 映射与列表顺序
            post_cards_map = {}
            post_list_order = []
            comment_api_responses = []

            def handle_response(resp):
                url = resp.url
                try:
                    if "mmfinderassistant-bin/post/post_list" in url:
                        data = resp.json().get("data", {})
                        for item in data.get("list", []):
                            oid = item.get("objectId")
                            if oid:
                                post_cards_map[oid] = item
                                if oid not in post_list_order:
                                    post_list_order.append(oid)
                    elif "comment" in url and "mmfinderassistant-bin" in url and resp.request.method == "POST":
                        comment_api_responses.append(resp.json())
                except Exception:
                    pass

            page.on("response", handle_response)

            logger.info("[BrowserCommenter] 打开评论管理页: %s", WECHAT_COMMENT_URL)
            page.goto(WECHAT_COMMENT_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)

            # 2. 登录有效性判定
            if "login.html" in page.url:
                logger.error("[BrowserCommenter] 会话已失效，重定向至登录页")
                shot_path = evidence_root / "login_required.png"
                page.screenshot(path=str(shot_path))
                browser.close()
                return "FAILED", str(shot_path), "微信登录态已失效，需重新扫码"

            # 等待 post_list 接口数据到达（最多等待 4 秒）
            for _ in range(8):
                if platform_post_id in post_cards_map:
                    break
                page.wait_for_timeout(500)

            # 3. 严格校验目标作品是否存在于后台列表中
            if platform_post_id not in post_cards_map:
                shot_path = evidence_root / "video_not_in_post_list.png"
                page.screenshot(path=str(shot_path))
                browser.close()
                logger.warning(
                    "[BrowserCommenter] 目标作品 (%s) 尚未出现在后台 post_list 中，进入 PENDING_REVIEW",
                    platform_post_id,
                )
                return "PENDING_REVIEW", str(shot_path), f"目标作品 ({platform_post_id}) 尚未出现在互动列表（转码或审核中）"

            target_item = post_cards_map[platform_post_id]
            target_desc = str(target_item.get("desc") or "").strip()

            # 4. 在 DOM 中精确查找目标卡片（绝不盲目点击第 1 个视频）
            target_card = None

            # 4.1 优先通过原生属性匹配
            attr_loc = page.locator(
                f"[data-id='{platform_post_id}'], [data-object-id='{platform_post_id}'], [data-post-id='{platform_post_id}']"
            ).first
            if attr_loc.count() > 0 and attr_loc.is_visible():
                target_card = attr_loc

            # 4.2 依据 post_list 索引与文本双重核验匹配
            if not target_card and platform_post_id in post_list_order:
                idx = post_list_order.index(platform_post_id)
                cards = page.locator(".feed-item, [class*='post-card'], [class*='feed-card'], .post-item").all()
                if idx < len(cards) and cards[idx].is_visible():
                    card_txt = cards[idx].inner_text()
                    expected_keywords = [target_desc[:10], (video_title or "")[:10]]
                    if any(kw and kw in card_txt for kw in expected_keywords) or len(target_desc) == 0:
                        target_card = cards[idx]

            # 4.3 依据目标 desc / video_title 文本匹配
            if not target_card:
                match_text = target_desc[:12] if len(target_desc) >= 6 else (video_title or "")[:12]
                if match_text:
                    text_loc = page.locator(f"text={match_text}").first
                    if text_loc.count() > 0 and text_loc.is_visible():
                        target_card = text_loc

            # 坚决不使用任何默认第一项或日期项回退！未定位成功即 Fail-Closed
            if not target_card:
                shot_path = evidence_root / "card_dom_not_matched.png"
                page.screenshot(path=str(shot_path))
                browser.close()
                logger.warning("[BrowserCommenter] 无法在 DOM 中精确选定目标作品卡片: %s", platform_post_id)
                return "PENDING_REVIEW", str(shot_path), f"接口已确认作品存在但 DOM 卡片定位未果: {platform_post_id}"

            logger.info("[BrowserCommenter] 精准选定目标作品卡片: %s", platform_post_id)
            target_card.click()
            page.wait_for_timeout(2500)

            # 5. 检查是否已存在【作者】发出的评论（幂等查重）
            author_badges = page.locator(".comment-list, [class*='comment-wrap'], .comment-item").locator("text=作者").all()
            visible_author_comments = [b for b in author_badges if b.is_visible()]
            if visible_author_comments:
                shot_path = evidence_root / "already_commented.png"
                page.screenshot(path=str(shot_path))
                browser.close()
                logger.info("[BrowserCommenter] 目标视频已存在作者首评，跳过重复发评")
                return "SKIPPED_EXISTS", str(shot_path), None

            # 6. 点击写评论按钮
            write_btn = page.locator("[ml-key='mgr_cmmt'], div.tag-wrap:has-text('写评论'), button:has-text('写评论')").first
            if not write_btn.is_visible():
                shot_path = evidence_root / "write_btn_missing.png"
                page.screenshot(path=str(shot_path))
                browser.close()
                return "FAILED", str(shot_path), "未找到'写评论'按钮"

            logger.info("[BrowserCommenter] 点击'写评论'")
            write_btn.click(force=True)
            page.wait_for_timeout(1000)

            # 7. 定位评论输入框并填入排版文本
            textarea = page.locator("textarea").first
            if not textarea.is_visible():
                shot_path = evidence_root / "textarea_missing.png"
                page.screenshot(path=str(shot_path))
                browser.close()
                return "FAILED", str(shot_path), "未找到评论输入框"

            logger.info("[BrowserCommenter] 注入评论文本 (%d 字)", len(comment_text))
            textarea.fill(comment_text)
            page.wait_for_timeout(1000)

            # 8. 点击提交按钮
            submit_btn = page.locator("button:has-text('评论'), .weui-desktop-btn:has-text('评论')").first
            if not submit_btn.is_visible() or submit_btn.is_disabled():
                shot_path = evidence_root / "submit_btn_disabled.png"
                page.screenshot(path=str(shot_path))
                browser.close()
                return "FAILED", str(shot_path), "评论提交按钮不可点击"

            logger.info("[BrowserCommenter] 点击提交评论")
            submit_btn.click()

            # 9. 真实结果核验闭环：校验平台接口 errCode == 0
            api_success = False
            api_err_msg = ""
            for _ in range(10):
                if comment_api_responses:
                    latest_resp = comment_api_responses[-1]
                    err_code = latest_resp.get("errCode", latest_resp.get("code", latest_resp.get("ret", -1)))
                    if err_code == 0:
                        api_success = True
                        break
                    else:
                        api_err_msg = latest_resp.get("errMsg", str(latest_resp))
                        break
                page.wait_for_timeout(500)

            if not api_success and comment_api_responses:
                shot_path = evidence_root / "submit_api_rejected.png"
                page.screenshot(path=str(shot_path))
                browser.close()
                return "FAILED", str(shot_path), f"评论提交被平台接口拒绝: {api_err_msg}"

            # 10. 真实结果核验闭环：DOM 回读作者标签与评论文本
            dom_verified = False
            snippet = re.sub(r"\s+", "", comment_text)[:12]
            for _ in range(12):
                page.wait_for_timeout(500)
                comments_area = page.locator(".comment-list, [class*='comment-wrap'], .comment-item")
                if comments_area.count() > 0:
                    area_text = re.sub(r"\s+", "", comments_area.first.inner_text())
                    if snippet in area_text and "作者" in area_text:
                        dom_verified = True
                        break

            final_shot = evidence_root / f"comment_published_{int(time.time())}.png"
            page.screenshot(path=str(final_shot))

            if not dom_verified:
                logger.warning("[BrowserCommenter] 提交已触发，但未能从页面回读刚刚发布的作者评论内容")
                browser.close()
                return "FAILED", str(final_shot), "评论已提交但页面 DOM 回读未找到已发布的作者评论证据"

            # 写入只读回读诊断证据
            try:
                (evidence_root / "comment_readback.json").write_text(
                    json.dumps({
                        "platform_post_id": platform_post_id,
                        "api_success": api_success,
                        "dom_verified": dom_verified,
                        "verified_at": datetime.now(timezone.utc).isoformat(),
                    }, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception:
                pass

            logger.info("[BrowserCommenter] 发评完成且 DOM 回读成功验证，证据已保存: %s", final_shot)
            browser.close()
            return "COMMENTED", str(final_shot), None
