"""视频号评论管理后台 Playwright 自动化执行器。

负责通过无头浏览器登录态访问互动管理后台，完成目标视频定位、
重复查重、多行评论填入、提交发评与证据留存。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-19 | Antigravity | 初始创建：实现带排他锁的视频号评论自动化与证据链 |
"""

from __future__ import annotations

import fcntl
import logging
import os
import time
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
        platform_post_id: Optional[str] = None,
        video_title: Optional[str] = None,
        evidence_dir: Optional[Path | str] = None,
    ) -> Tuple[str, Optional[str], Optional[str]]:
        """执行发评流程。

        Returns:
            Tuple of (status, evidence_path, error_message)
            status in {"COMMENTED", "SKIPPED_EXISTS", "PENDING_REVIEW", "FAILED"}
        """
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
                    platform_post_id=platform_post_id,
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
        platform_post_id: Optional[str],
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

            # 监听接口数据，获取 objectId 映射
            post_cards_map = {}
            def handle_response(resp):
                if "mmfinderassistant-bin/post/post_list" in resp.url:
                    try:
                        data = resp.json().get("data", {})
                        for item in data.get("list", []):
                            oid = item.get("objectId")
                            if oid:
                                post_cards_map[oid] = item
                    except Exception:
                        pass

            page.on("response", handle_response)

            logger.info("[BrowserCommenter] 打开评论管理页: %s", WECHAT_COMMENT_URL)
            page.goto(WECHAT_COMMENT_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(4000)

            # 登录有效性判定
            if "login.html" in page.url:
                logger.error("[BrowserCommenter] 会话已失效，重定向至登录页")
                shot_path = evidence_root / "login_required.png"
                page.screenshot(path=str(shot_path))
                browser.close()
                return "FAILED", str(shot_path), "微信登录态已失效，需重新扫码"

            # 寻找左侧视频卡片
            # 优先等待卡片容器
            page.wait_for_timeout(2000)

            # 定位卡片：若提供具体标题或 post_id，则精确查找；否则默认选择最新发布的第一个视频
            target_card = None
            if video_title:
                # 尝试用标题文本匹配
                sub_title = video_title[:10]
                card_loc = page.locator(f"text={sub_title}").first
                if card_loc.count() > 0 and card_loc.is_visible():
                    target_card = card_loc

            if not target_card:
                # 选择列表中第一个可点击视频项
                card_loc = page.locator(".feed-item, [class*='post-card'], [class*='feed-card'], .post-item").first
                if card_loc.count() > 0 and card_loc.is_visible():
                    target_card = card_loc
                else:
                    # 备用：点击日期文本或第二张缩略图
                    date_loc = page.locator("text=2026/").first
                    if date_loc.count() > 0 and date_loc.is_visible():
                        target_card = date_loc

            if not target_card:
                shot_path = evidence_root / "video_not_found.png"
                page.screenshot(path=str(shot_path))
                browser.close()
                logger.warning("[BrowserCommenter] 未在列表中找到视频，可能尚在转码审核中")
                return "PENDING_REVIEW", str(shot_path), "视频未出现在互动列表（转码或审核中）"

            logger.info("[BrowserCommenter] 选中目标视频卡片")
            target_card.click()
            page.wait_for_timeout(3000)

            # 检查是否已存在【作者】发出的评论
            author_badge = page.locator("text=作者").all()
            # 过滤排除自身的作者标识，检查评论列表内是否有作者评论
            comment_authors = [b for b in author_badge if b.is_visible()]
            # 如果已有评论区且展示了作者评论
            comments_container = page.locator(".comment-list, .comment-item, [class*='comment-wrap']")
            if comments_container.count() > 0 and len(comment_authors) > 1:
                shot_path = evidence_root / "already_commented.png"
                page.screenshot(path=str(shot_path))
                browser.close()
                logger.info("[BrowserCommenter] 目标视频已存在作者首评，跳过重复发评")
                return "SKIPPED_EXISTS", str(shot_path), None

            # 点击写评论按钮
            write_btn = page.locator("[ml-key='mgr_cmmt'], div.tag-wrap:has-text('写评论')").first
            if not write_btn.is_visible():
                shot_path = evidence_root / "write_btn_missing.png"
                page.screenshot(path=str(shot_path))
                browser.close()
                return "FAILED", str(shot_path), "未找到'写评论'按钮"

            logger.info("[BrowserCommenter] 点击'写评论'")
            write_btn.click(force=True)
            page.wait_for_timeout(1500)

            # 定位评论输入框
            textarea = page.locator("textarea").first
            if not textarea.is_visible():
                shot_path = evidence_root / "textarea_missing.png"
                page.screenshot(path=str(shot_path))
                browser.close()
                return "FAILED", str(shot_path), "未找到评论输入框"

            # 输入排版文本
            logger.info("[BrowserCommenter] 注入评论文本 (%d 字)", len(comment_text))
            textarea.fill(comment_text)
            page.wait_for_timeout(1000)

            # 点击提交按钮
            submit_btn = page.locator("button:has-text('评论'), .weui-desktop-btn:has-text('评论')").first
            if not submit_btn.is_visible() or submit_btn.is_disabled():
                shot_path = evidence_root / "submit_btn_disabled.png"
                page.screenshot(path=str(shot_path))
                browser.close()
                return "FAILED", str(shot_path), "评论提交按钮不可点击"

            logger.info("[BrowserCommenter] 点击提交评论")
            submit_btn.click()
            page.wait_for_timeout(3000)

            # 截图保存成功证据
            final_shot = evidence_root / f"comment_published_{int(time.time())}.png"
            page.screenshot(path=str(final_shot))
            logger.info("[BrowserCommenter] 发评完成，证据已保存: %s", final_shot)

            browser.close()
            return "COMMENTED", str(final_shot), None
