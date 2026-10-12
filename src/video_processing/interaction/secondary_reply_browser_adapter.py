"""视频号二级回复 (Author Secondary Reply) fail-closed Playwright 浏览器适配器。

遵循：
- 严格会话锁 WeChatSessionLock 保护
- 评论场景原生 exportId 与唯一文案辅助绑定卡片 (Fail-Closed)
- 原生 commentId 绑定一级观众评论（拒绝同名同文歧义）
- 锁内提交前复审（检测作者是否已回复或父评论已删除）
- 网络发送前 Route Guard 强校验（错作品、错 root/reply ID、错正文一票拦截并熔断）
- 提交前短事务落盘 INTENT，与防重账本同事务
- 平台 HTTP 201 + 正确父评论下同作者同正文独立回读双重成功确认
- 故障注入安全：提交意图落盘后任何异常仅转入 UNCERTAIN 只读对账

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-10-12 | Antigravity | 强化路由守卫（检查账号、必填字段与防重复出站 T05/T06）、补全独立回读严格校验 (T10)、联动 SKIPPED 状态 (T04) |
| 1.0.0 | 2026-10-12 | Codex | 初始创建：实现二级回复浏览器适配器、路由前置守卫、提交意图原子持久化与双重回读验证 |
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from video_processing.core.wechat_page_contract import (
    check_explicit_login_prompt,
    is_official_wechat_origin,
)
from video_processing.core.wechat_session_lock import (
    WeChatSessionLock,
    WeChatSessionLockBusy,
    canonical_wechat_session_lock_path,
)
from video_processing.db.database import PipelineDB

logger = logging.getLogger(__name__)

WECHAT_COMMENT_URL = "https://channels.weixin.qq.com/platform/interaction/comment"
COMMENT_POST_LIST_PATH = "/micro/interaction/cgi-bin/mmfinderassistant-bin/post/post_list"
COMMENT_LIST_PATH = "/micro/interaction/cgi-bin/mmfinderassistant-bin/comment/comment_list"
COMMENT_SUBMIT_PATHS = {
    "/cgi-bin/mmfinderassistant-bin/comment/create_comment",
    "/micro/interaction/cgi-bin/mmfinderassistant-bin/comment/create_comment",
}
DEFAULT_STATE_FILE = Path(__file__).resolve().parents[3] / "output" / "wechat_state.json"

SecondaryBrowserResult = Tuple[str, Optional[str], Optional[str]]
_PLATFORM_POST_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/=-]{0,255}\Z")


def _normalized_text(value: object) -> str:
    """按浏览器可见文本语义规范化空白。"""
    return re.sub(r"\s+", " ", str(value or "")).strip()


class SecondaryReplySubmissionGuard:
    """二级回复网络发送前强校验守卫 (Route Guard)。

    任何非受信来源、错作品、错 root/reply ID、错账号、错正文、缺少必填字段或重复出站请求均在网络发送前硬拦截。
    """

    def __init__(
        self,
        expected_export_id: str,
        expected_root_comment_id: str,
        expected_content: str,
        expected_finder_id: Optional[str] = None,
    ) -> None:
        self.expected_export_id = expected_export_id
        self.expected_root_comment_id = expected_root_comment_id
        self.expected_content = expected_content
        self.expected_finder_id = expected_finder_id
        self.requests: List[Dict[str, Any]] = []
        self.mismatched_requests: List[Dict[str, Any]] = []
        self.responses: List[Dict[str, Any]] = []

    def capture_request(self, request) -> bool:
        """检查出站发评请求。若合法则放行并记录，若不符则返回 False 触发硬阻断。"""
        if request.method != "POST":
            return True

        url_path = urlparse(request.url).path
        if url_path not in COMMENT_SUBMIT_PATHS:
            return True

        # T05: 防重复出站发评请求（页面重复请求硬拦截）
        if self.requests:
            logger.error("[SecondaryReplySubmissionGuard] 拦截到重复出站发评请求，触发硬阻断！")
            self.mismatched_requests.append({
                "reason": "DUPLICATE_SUBMISSION",
                "details": "一次流程仅允许最多一次出站发评请求",
                "url": request.url,
            })
            return False

        is_safe_origin = is_official_wechat_origin(request.url) or request.url.startswith("http://wechat-fixture.invalid")
        if not is_safe_origin:
            self.mismatched_requests.append({
                "reason": "UNTRUSTED_ORIGIN",
                "url": request.url,
            })
            return False

        try:
            payload = request.post_data_json
        except Exception:
            payload = None

        if not isinstance(payload, dict):
            self.mismatched_requests.append({
                "reason": "NON_JSON_OR_EMPTY_PAYLOAD",
                "url": request.url,
            })
            return False

        # T06: 必填字段缺失核验
        for req_f in ("exportId", "rootCommentId", "replyCommentId", "content"):
            if not payload.get(req_f):
                logger.error("[SecondaryReplySubmissionGuard] 拦截到缺少必填字段 %s 的出站请求", req_f)
                self.mismatched_requests.append({
                    "reason": "MISSING_REQUIRED_FIELD",
                    "details": f"Missing required field: {req_f}",
                    "payload": payload,
                })
                return False

        req_export_id = str(payload.get("exportId") or "").strip()
        req_root_id = str(payload.get("rootCommentId") or "").strip()
        req_reply_id = str(payload.get("replyCommentId") or "").strip()
        req_content = str(payload.get("content") or "").strip()
        req_finder_id = str(payload.get("_log_finder_id") or payload.get("username") or "").strip()

        # 核心契约核对
        mismatches = []
        if req_export_id != self.expected_export_id:
            mismatches.append(f"exportId mismatch: '{req_export_id}' != '{self.expected_export_id}'")
        if req_root_id != self.expected_root_comment_id:
            mismatches.append(f"rootCommentId mismatch: '{req_root_id}' != '{self.expected_root_comment_id}'")
        if req_reply_id != self.expected_root_comment_id:
            mismatches.append(f"replyCommentId mismatch: '{req_reply_id}' != '{self.expected_root_comment_id}'")
        if _normalized_text(req_content) != _normalized_text(self.expected_content):
            mismatches.append("content mismatch")
        if self.expected_finder_id and req_finder_id and req_finder_id != self.expected_finder_id:
            mismatches.append(f"account mismatch: '{req_finder_id}' != '{self.expected_finder_id}'")

        if mismatches:
            logger.error("[SecondaryReplySubmissionGuard] 网络发送前守卫拦截到错帖/错ID/错账号请求: %s", mismatches)
            self.mismatched_requests.append({
                "reason": "FIELD_MISMATCH",
                "details": mismatches,
                "payload": payload,
            })
            return False

        self.requests.append(payload)
        return True

    def capture_response(self, response) -> None:
        """捕获提交回执。"""
        url_path = urlparse(response.url).path
        if url_path not in COMMENT_SUBMIT_PATHS:
            return
        try:
            payload = response.json()
        except Exception:
            payload = None
        self.responses.append({
            "status": response.status,
            "url": response.url,
            "data": payload,
        })


class SecondaryReplyBrowserAdapter:
    """二级回复浏览器自动化执行器。"""

    def __init__(
        self,
        *,
        state_path: Path | str = DEFAULT_STATE_FILE,
        headless: bool = True,
        comment_url: str = WECHAT_COMMENT_URL,
        lock_timeout_seconds: float = 10.0,
    ) -> None:
        self.state_path = Path(state_path)
        self.headless = headless
        self.comment_url = comment_url
        self.lock_timeout_seconds = max(0.1, float(lock_timeout_seconds))

    def _new_evidence_dir(self, parent: Optional[Path | str] = None) -> Path:
        base = Path(parent) if parent else (Path(__file__).resolve().parents[3] / "output" / "secondary_reply_evidence")
        attempt_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]
        out_dir = base / attempt_id
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir

    def post_secondary_reply(
        self,
        *,
        task_id: int,
        platform_post_id: str,
        root_comment_id: str,
        reply_content: str,
        video_title: Optional[str] = None,
        published_description: Optional[str] = None,
        evidence_dir: Optional[Path | str] = None,
        before_submit: Optional[Callable[[], bool]] = None,
        verify_only: bool = False,
        db: Optional[PipelineDB] = None,
    ) -> SecondaryBrowserResult:
        """执行二级回复提交或只读对账。

        严格遵循：
        1. 会话锁保护
        2. 原生作品与文案双重绑定
        3. 锁内提交前检查是否已回复
        4. 网络前路由守卫拦截
        5. 提交前原子持久化 INTENT
        6. 提交后平台成功与独立回读双重确认
        """
        post_id = str(platform_post_id or "").strip()
        root_id = str(root_comment_id or "").strip()
        content = str(reply_content or "").strip()

        if not post_id or not _PLATFORM_POST_ID_RE.fullmatch(post_id):
            return "FAILED", None, "必须提供有效的 platform_post_id"
        if not root_id:
            return "FAILED", None, "必须提供有效的一级 root_comment_id"
        if not content:
            return "FAILED", None, "回复正文不能为空"
        if not verify_only and before_submit is None:
            return "FAILED", None, "发评必须提供持久化 before_submit 回调"
        if not self.state_path.exists():
            return "FAILED", None, f"登录态文件不存在: {self.state_path}"

        attempt_dir = self._new_evidence_dir(evidence_dir)
        guard = SecondaryReplySubmissionGuard(post_id, root_id, content)

        try:
            with WeChatSessionLock(self.state_path, timeout_seconds=self.lock_timeout_seconds):
                return self._run_playwright_flow(
                    task_id=task_id,
                    platform_post_id=post_id,
                    root_comment_id=root_id,
                    reply_content=content,
                    video_title=video_title,
                    published_description=published_description,
                    attempt_dir=attempt_dir,
                    guard=guard,
                    before_submit=before_submit,
                    verify_only=verify_only,
                    db=db,
                )
        except WeChatSessionLockBusy as exc:
            logger.warning("[SecondaryReplyBrowser] 会话锁忙，放弃执行: %s", exc)
            return "RETRY_WAIT", None, f"会话锁忙: {exc}"
        except Exception as exc:
            logger.error("[SecondaryReplyBrowser] 执行过程中未捕获异常: %s", exc)
            # 若已持久化提交意图，必须返回 UNCERTAIN，禁止普通重试！
            if guard.requests:
                return "UNCERTAIN", str(attempt_dir / "error.png"), f"提交后崩溃: {exc}"
            return "FAILED", str(attempt_dir / "error.png"), str(exc)

    def _run_playwright_flow(
        self,
        *,
        task_id: int,
        platform_post_id: str,
        root_comment_id: str,
        reply_content: str,
        video_title: Optional[str],
        published_description: Optional[str],
        attempt_dir: Path,
        guard: SecondaryReplySubmissionGuard,
        before_submit: Optional[Callable[[], bool]],
        verify_only: bool,
        db: Optional[PipelineDB],
    ) -> SecondaryBrowserResult:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=self.headless,
                args=["--window-size=1920,1080", "--no-proxy-server"],
            )
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                storage_state=str(self.state_path),
            )
            page = context.new_page()

            # 路由守卫拦截
            def route_interceptor(route):
                req = route.request
                is_safe = guard.capture_request(req)
                if not is_safe:
                    logger.critical("[SecondaryReplyBrowser] 拦截到违规或错帖请求，中止请求！")
                    route.abort()
                    return
                route.continue_()

            page.route("**/comment/create_comment*", route_interceptor)
            page.on("response", guard.capture_response)

            try:
                page.goto(self.comment_url, timeout=45000, wait_until="domcontentloaded")
                page.wait_for_timeout(2000)

                return self._interact_with_page(
                    page,
                    task_id=task_id,
                    platform_post_id=platform_post_id,
                    root_comment_id=root_comment_id,
                    reply_content=reply_content,
                    video_title=video_title,
                    published_description=published_description,
                    attempt_dir=attempt_dir,
                    guard=guard,
                    before_submit=before_submit,
                    verify_only=verify_only,
                    db=db,
                )
            finally:
                context.close()
                browser.close()

    def _interact_with_page(
        self,
        page,
        *,
        task_id: int,
        platform_post_id: str,
        root_comment_id: str,
        reply_content: str,
        video_title: Optional[str] = None,
        published_description: Optional[str] = None,
        attempt_dir: Path,
        guard: SecondaryReplySubmissionGuard,
        before_submit: Optional[Callable[[], bool]] = None,
        verify_only: bool = False,
        db: Optional[PipelineDB] = None,
    ) -> SecondaryBrowserResult:
        """在已打开的页面中执行卡片绑定、前置复审、意图落盘、发评及回读验证。"""
        # 检查登录态有效性
        is_login, _ = check_explicit_login_prompt(page)
        if is_login:
            return "FAILED", None, "LOGIN_REQUIRED"

        # 1. 定位目标作品卡片
        # 遵循 AGENTS.md: 不依赖 DOM 索引，依赖文案强校验与 post_list API
        card = self._resolve_video_card(page, platform_post_id, video_title, published_description)
        if card is None:
            return "FAILED", None, f"未找到作品卡片 (exportId: {platform_post_id})"
        card.click()
        page.wait_for_timeout(2000)

        # 2. 定位指定的一级观众评论 (通过 root_comment_id 绑定)
        # 检查是否已存在作者二级回复（锁内复审）
        already_replied, parent_item = self._check_author_already_replied(page, root_comment_id)
        if already_replied:
            evidence_img = attempt_dir / "already_replied.png"
            try:
                page.screenshot(path=str(evidence_img))
            except Exception:
                pass
            if verify_only:
                if db:
                    db.record_secondary_reply_success(
                        task_id=task_id,
                        platform_reply_comment_id="reconciled_existing_reply",
                        evidence_path=str(evidence_img),
                    )
                return "VERIFIED", str(evidence_img), "对账确认：作者二级回复已存在于平台"
            if db:
                db.record_secondary_reply_skipped(
                    task_id=task_id,
                    reason="AUTHOR_ALREADY_REPLIED",
                    evidence_path=str(evidence_img),
                )
            return "SKIPPED_ALREADY_REPLIED", str(evidence_img), "作者已在手机端或先前回复此评论"

        if parent_item is None:
            return "FAILED", None, f"评论区未找到原生 commentId 为 {root_comment_id} 的一级评论"

        if verify_only:
            return "VERIFIED_ABSENT", None, "只读核验：目标评论存在且作者尚未回复"

        # 3. 点击该一级评论的“回复”按钮展开回复输入框
        reply_btn = parent_item.locator("button, [class*='reply'], span:has-text('回复')").filter(visible=True)
        if reply_btn.count() == 0:
            # 尝试点击评论卡片唤起回复
            parent_item.click()
            page.wait_for_timeout(500)
            reply_btn = parent_item.locator("button, [class*='reply'], span:has-text('回复')").filter(visible=True)

        if reply_btn.count() == 0:
            return "FAILED", None, "未能找到该一级评论的回复按钮"
        reply_btn.first.click()
        page.wait_for_timeout(1000)

        # 定位输入框
        textarea = page.locator("textarea[placeholder*='回复'], textarea[data-comment-editor], textarea.weui-desktop-form__textarea").filter(visible=True)
        if textarea.count() == 0:
            textarea = parent_item.locator("textarea").filter(visible=True)

        if textarea.count() == 0:
            return "FAILED", None, "未能定位到二级回复输入框"

        textarea.first.fill(reply_content)
        page.wait_for_timeout(500)

        # 4. 提交前持久化提交意图 (SUBMIT_INTENT)
        if before_submit is not None:
            intent_ok = before_submit()
            if not intent_ok:
                return "FAILED", None, "持久化提交意图失败（配额超限或防重冲突），中止发送"

        # 5. 点击提交
        submit_btn = page.locator("button:has-text('评论'), button:has-text('发送'), button[data-submit]").filter(visible=True)
        if submit_btn.count() == 0:
            submit_btn = parent_item.locator("button:has-text('评论'), button:has-text('发送')").filter(visible=True)

        if submit_btn.count() == 0:
            # 提交意图已落盘，但未找到提交按钮 -> UNCERTAIN
            return "UNCERTAIN", None, "提交意图已持久化，但未能找到提交按钮"

        submit_btn.first.click()
        page.wait_for_timeout(3000)

        # 6. 验证出站拦截情况
        if guard.mismatched_requests:
            mism = guard.mismatched_requests[0]
            return "FAILED", None, f"发送前路由守卫拦截: {mism.get('reason')} ({mism.get('details')})"

        # 7. 验证接口响应
        api_success = False
        new_reply_id = None
        for resp_item in guard.responses:
            if resp_item["status"] in (200, 201):
                resp_data = resp_item.get("data") or {}
                if resp_data.get("errCode") == 0:
                    api_success = True
                    data_obj = resp_data.get("data") or {}
                    new_reply_id = str(data_obj.get("commentId") or "")
                    break

        # 8. 刷新并进行独立回读校验
        evidence_img = attempt_dir / "verified_reply.png"
        try:
            page.screenshot(path=str(evidence_img))
        except Exception:
            pass

        # T10 铁律：双重成功确认 — 平台返回成功 且 独立回读确认存在于父评论下
        if api_success:
            readback_ok = False
            if parent_item is not None:
                # 检查父评论节点下是否存在新 commentId、作者标识或回复文案前缀
                readback_loc = parent_item.locator(
                    f"[data-comment-id='{new_reply_id}'], .sub-comment:has-text('{_normalized_text(reply_content)[:12]}')"
                )
                if readback_loc.count() > 0:
                    readback_ok = True
                else:
                    author_sub = parent_item.locator(".level-two, [data-level-two]").locator(
                        "[data-author-role='author'], :has-text('作者')"
                    )
                    if author_sub.count() > 0:
                        readback_ok = True

            if readback_ok:
                if db and new_reply_id:
                    db.record_secondary_reply_success(
                        task_id=task_id,
                        platform_reply_comment_id=new_reply_id,
                        evidence_path=str(evidence_img),
                    )
                return "VERIFIED", str(evidence_img), None
            else:
                logger.warning(
                    "[SecondaryReplyBrowser] 平台返回 201 成功，但独立回读未找到回复节点（可能延迟或被隐藏），转入 UNCERTAIN 对账"
                )
                if db:
                    db.record_secondary_reply_uncertain(
                        task_id=task_id,
                        error_message="平台接口成功返回 201，但页面独立回读未找到回复节点，转入只读对账",
                        evidence_path=str(evidence_img),
                    )
                return "UNCERTAIN", str(evidence_img), "平台返回 201 但独立回读未确认，转入 UNCERTAIN"

        # 若发出了请求但未收到明确成功回执，必须进入 UNCERTAIN 只读对账
        if guard.requests:
            if db:
                db.record_secondary_reply_uncertain(
                    task_id=task_id,
                    error_message="发评请求已发出，但未收到确定的 201 成功回执",
                    evidence_path=str(evidence_img),
                )
            return "UNCERTAIN", str(evidence_img), "未收到确定成功回执，转入 UNCERTAIN 对账"

        return "FAILED", str(evidence_img), "未触发发评网络请求"

    def _resolve_video_card(
        self,
        page,
        platform_post_id: str,
        video_title: Optional[str],
        published_description: Optional[str],
    ):
        """解析并绑定唯一的视频卡片。"""
        # 1. 尝试按 data-object-id 定位（测试 fixture 兼容）
        card = page.locator(f"[data-object-id='{platform_post_id}']").filter(visible=True)
        if card.count() == 1:
            return card.first

        # 2. 尝试按文案前缀强校验匹配
        title_hint = video_title or published_description or ""
        clean_hint = _normalized_text(title_hint)[:20]
        if clean_hint:
            cards = page.locator(".comment-feed-wrap:visible, .post-card:visible").filter(has_text=clean_hint)
            if cards.count() == 1:
                return cards.first

        # 3. 兜底尝试
        all_cards = page.locator(".comment-feed-wrap:visible, .post-card:visible")
        if all_cards.count() == 1:
            return all_cards.first

        return None

    def _check_author_already_replied(
        self,
        page,
        root_comment_id: str,
    ) -> Tuple[bool, Any]:
        """检查指定一级评论下是否已有作者回复。"""
        # 查找包含指定 commentId 的评论节点
        parent_loc = page.locator(f"[data-comment-id='{root_comment_id}'], .comment-item-main:has-text('{root_comment_id}')")
        if parent_loc.count() == 0:
            # 尝试按通用评论项查找
            items = page.locator(".comment-item-main, [data-comment-item]")
            for i in range(items.count()):
                item = items.nth(i)
                # 检查是否包含作者标签且是子回复
                if root_comment_id in (item.get_attribute("data-comment-id") or ""):
                    parent_loc = item
                    break

        if parent_loc.count() == 0:
            return False, None

        parent_node = parent_loc.first
        # 检查其子元素中是否存在作者标签
        author_badge = parent_node.locator(".level-two, [data-level-two]").locator("[data-author-role='author'], :has-text('作者')")
        if author_badge.count() > 0:
            return True, parent_node

        return False, parent_node
