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
| 1.4.0 | 2026-10-17 | Codex | 修复 _interact_with_page 中回复按钮选择器联合碰撞缺陷，采用单候选迭代；将 calibrate_comment_controls 编辑器检测限定于当前父评论范围 (M2) |
| 1.3.0 | 2026-10-17 | Codex | 实装真实平台只读控件校准 (calibrate_comment_controls)、校准 DOM 选择器、卡片列表滚轮分页支持与只读平台验证 (R1) |
| 1.2.0 | 2026-10-13 | Antigravity | 接入二级回复折叠与分页完整性校验 (Fail-Closed)、支持展开后续页作者回复与捕获 comment_list 响应 |
| 1.1.0 | 2026-10-12 | Antigravity | 强化路由守卫（检查账号、必填字段与防重复出站 T05/T06）、补全独立回读严格校验 (T10)、联动 SKIPPED 状态 (T04) |
| 1.0.0 | 2026-10-12 | Codex | 初始创建：实现二级回复浏览器适配器、路由前置守卫、提交意图原子持久化与双重回读验证 |
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import time
import unicodedata
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from video_processing.core.wechat_browser_context import create_wechat_context
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


def _resolve_default_state_file() -> Path:
    return Path(__file__).resolve().parents[3] / "output" / "wechat_state.json"


DEFAULT_STATE_FILE = _resolve_default_state_file()

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
        trusted_origins: Tuple[str, ...] = (),
    ) -> None:
        # 显式注入的受信测试源（如离线 fixture），生产默认为空，不再硬编码域名豁免
        self.trusted_origins = tuple(trusted_origins)
        self.expected_export_id = expected_export_id
        self.expected_root_comment_id = expected_root_comment_id
        self.expected_content = expected_content
        self.expected_finder_id = expected_finder_id
        self.requests: List[Dict[str, Any]] = []
        self.mismatched_requests: List[Dict[str, Any]] = []
        self.responses: List[Dict[str, Any]] = []
        # 唯一被准许出站的 Request 对象；只有与它关联的 Response 才算本次发送的回执
        self.allowed_request: Any = None
        self.uncorrelated_responses: List[Dict[str, Any]] = []

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

        is_safe_origin = is_official_wechat_origin(request.url) or any(
            request.url.startswith(o) for o in self.trusted_origins
        )
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
        # 正文必须与获批全文逐字一致（仅做 NFC 归一化，不折叠空白/换行）
        if unicodedata.normalize("NFC", str(payload.get("content"))) != unicodedata.normalize("NFC", self.expected_content):
            mismatches.append("content mismatch")
        # 账号强校验：未配置期望账号、请求缺账号字段或不一致，一律拒绝
        if not self.expected_finder_id:
            mismatches.append("expected account not configured")
        elif not req_finder_id:
            mismatches.append("account field missing in request")
        elif req_finder_id != self.expected_finder_id:
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
        self.allowed_request = request
        return True

    def capture_response(self, response) -> None:
        """捕获提交回执；仅接受与唯一准许出站 Request 对应的 Response，其余记为无关回执。"""
        url_path = urlparse(response.url).path
        if url_path not in COMMENT_SUBMIT_PATHS:
            return
        try:
            payload = response.json()
        except Exception:
            payload = None
        item = {"status": response.status, "url": response.url, "data": payload}
        if self.allowed_request is not None and getattr(response, "request", None) is self.allowed_request:
            self.responses.append(item)
        else:
            self.uncorrelated_responses.append(item)

    def validate_success_response(self) -> Tuple[bool, str, str]:
        """校验与唯一出站 Request 关联的业务成功回执。返回 (ok, 原生回复 ID, 原因)。

        要求：HTTP 200/201、errCode==0、非空回复 ID、回执中的父评论/作者/正文与获批内容一致。
        """
        if len(self.responses) != 1:
            return False, "", f"correlated_responses={len(self.responses)}"
        item = self.responses[0]
        data = item.get("data") if isinstance(item.get("data"), dict) else {}
        if item.get("status") not in (200, 201) or data.get("errCode") != 0:
            return False, "", "NOT_BUSINESS_SUCCESS"
        body = data.get("data") if isinstance(data.get("data"), dict) else {}
        comment = body.get("comment") if isinstance(body.get("comment"), dict) else {}
        reply_id = str(body.get("commentId") or "").strip()
        if not reply_id or str(comment.get("commentId") or "").strip() != reply_id:
            return False, "", "REPLY_ID_MISSING_OR_INCONSISTENT"
        if str(comment.get("replyCommentId") or "").strip() != self.expected_root_comment_id:
            return False, "", "PARENT_MISMATCH"
        if not self.expected_finder_id or str(comment.get("username") or "").strip() != self.expected_finder_id:
            return False, "", "AUTHOR_MISMATCH"
        if unicodedata.normalize("NFC", str(comment.get("commentContent") or "")) != unicodedata.normalize("NFC", self.expected_content):
            return False, "", "CONTENT_MISMATCH"
        return True, reply_id, "OK"


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
        self._captured_comments: Dict[str, Dict[str, Any]] = {}
        self._active_export_id: Optional[str] = None
        self._post_descriptions: Dict[str, str] = {}

    def _setup_page_listeners(self, page, guard: Optional[SecondaryReplySubmissionGuard] = None) -> None:
        """注册页面网络监听：捕获 comment_list 响应数据、折叠/分页标志与活跃作品 ID。"""
        self._captured_comments.clear()
        self._post_descriptions.clear()
        self._active_export_id = None
        def on_request(req):
            if req.method == "POST" and "comment/comment_list" in req.url:
                try:
                    pdata = req.post_data_json
                    if isinstance(pdata, dict):
                        eid = str(pdata.get("exportId") or pdata.get("objectId") or "").strip()
                        if eid:
                            self._active_export_id = eid
                except Exception:
                    pass

        def on_response(res):
            if guard is not None:
                guard.capture_response(res)
            if not is_official_wechat_origin(res.url):
                return
            if urlparse(res.url).path == COMMENT_POST_LIST_PATH and res.status == 200:
                try:
                    for item in res.json()["data"]["list"]:
                        desc = item.get("desc") or ""
                        if isinstance(desc, dict):
                            desc = desc.get("description") or ""
                        for key in ("exportId", "objectId"):
                            if item.get(key) and desc:
                                self._post_descriptions[str(item[key])] = _normalized_text(desc)
                except (KeyError, TypeError, ValueError):
                    pass
            if "comment/comment_list" in res.url and res.status in (200, 201):
                try:
                    request_data = res.request.post_data_json
                    export_id = str(request_data.get("exportId") or request_data.get("objectId") or "")
                    if not export_id or export_id != self._active_export_id:
                        return
                    payload = res.json()
                    body = payload.get("data") if isinstance(payload.get("data"), dict) else payload
                    if isinstance(body, dict):
                        for c in body.get("comment") or []:
                            if isinstance(c, dict) and "commentId" in c:
                                cid = str(c["commentId"]).strip()
                                subs = c.get("levelTwoComment") or []
                                has_author = False
                                for sub in subs:
                                    if isinstance(sub, dict):
                                        sub_user = str(sub.get("username") or "")
                                        sub_role = str(sub.get("author_role") or sub.get("data-author-role") or "")
                                        sub_nick = str(sub.get("commentNickname") or "")
                                        if (
                                            guard and guard.expected_finder_id and sub_user == guard.expected_finder_id
                                        ):
                                            has_author = True
                                self._captured_comments[cid] = {
                                    "export_id": export_id,
                                    "commentId": cid,
                                    "nickname": str(c.get("commentNickname") or c.get("nickname") or ""),
                                    "content_prefix": _normalized_text(c.get("commentContent") or c.get("content") or ""),
                                    "downContinueFlag": c.get("downContinueFlag"),
                                    "levelTwoComment": subs,
                                    "has_author_reply": has_author,
                                }
                except Exception:
                    pass

        page.on("request", on_request)
        page.on("response", on_response)

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
        verify_controls: bool = False,
        db: Optional[PipelineDB] = None,
        expected_finder_id: Optional[str] = None,
        trusted_origins: Tuple[str, ...] = (),
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
        guard = SecondaryReplySubmissionGuard(
            post_id, root_id, content,
            expected_finder_id=expected_finder_id, trusted_origins=trusted_origins,
        )

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
                    verify_controls=verify_controls,
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
        verify_controls: bool = False,
        db: Optional[PipelineDB],
    ) -> SecondaryBrowserResult:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=self.headless,
                args=["--window-size=1920,1080", "--no-proxy-server"],
            )
            context = create_wechat_context(
                browser,
                storage_state=str(self.state_path),
                viewport={"width": 1920, "height": 1080},
            )
            page = context.new_page()
            self._setup_page_listeners(page, guard)

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

            try:
                page.goto(self.comment_url, timeout=45000, wait_until="domcontentloaded")
                try:
                    page.wait_for_selector(".comment-feed-wrap, [data-object-id]", timeout=15000)
                except Exception:
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
                    verify_controls=verify_controls,
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
        verify_controls: bool = False,
        db: Optional[PipelineDB] = None,
        send_only: bool = False,
    ) -> SecondaryBrowserResult:
        """在已打开的页面中执行卡片绑定、前置复审、意图落盘、发评及回读验证。

        ``send_only=True`` 时发出唯一出站请求并检查守卫后即返回 ``SENT``（不在本会话内回读、不写库），
        由业务编排在全新会话中独立回读并落终态。
        """
        # 检查登录态有效性
        is_login, _ = check_explicit_login_prompt(page)
        if is_login:
            return "FAILED", None, "LOGIN_REQUIRED"

        # 1. 定位目标作品卡片
        # 遵循 AGENTS.md: 不依赖 DOM 索引，依赖文案强校验与 post_list API
        card = self._resolve_video_card(page, platform_post_id, video_title, published_description)
        if card is None:
            return "FAILED", None, f"未找到作品卡片 (exportId: {platform_post_id})"
        self._captured_comments.clear()
        self._active_export_id = None
        card.click()
        page.wait_for_timeout(2000)

        # 文案前缀只用于导航：点开后详情区必须携带与原生作品 ID 一致的标识，否则拒绝（不信任标题匹配）
        bound = page.locator("[data-current-object-id]")
        bound_ok = False
        if bound.count() >= 1 and all(
            (bound.nth(i).get_attribute("data-current-object-id") or "") == platform_post_id
            for i in range(bound.count())
        ):
            bound_ok = True
        elif self._active_export_id and self._active_export_id == platform_post_id:
            bound_ok = True

        if not bound_ok:
            return "FAILED", None, f"无法证明已打开的详情属于目标作品 (exportId: {platform_post_id})，拒绝继续"

        # 2. 定位指定的一级观众评论 (通过 root_comment_id 绑定)
        # 检查是否已存在作者二级回复（锁内复审）与分页完整性
        if not guard.expected_finder_id:
            return "FAILED", None, "缺少已验证的作者账号标识，无法判定是否已回复，拒绝继续"
        already_replied, completeness, parent_item = self._check_author_already_replied(
            page, root_comment_id, guard.expected_finder_id
        )
        if already_replied:
            evidence_img = attempt_dir / "already_replied.png"
            try:
                page.screenshot(path=str(evidence_img))
            except Exception:
                pass
            if verify_only:
                # 只读对账仅发现“作者已有回复”，但没有本任务的原生回复 ID，不得伪造 ID 或标记成功
                return "FOUND_UNVERIFIED", str(evidence_img), "对账发现作者二级回复存在，但无法绑定到本任务的原生回复 ID，需人工确认"
            if db:
                db.record_secondary_reply_skipped(
                    task_id=task_id,
                    reason="AUTHOR_ALREADY_REPLIED",
                    evidence_path=str(evidence_img),
                )
            return "SKIPPED_ALREADY_REPLIED", str(evidence_img), "作者已在手机端或先前回复此评论"

        if parent_item is None:
            return "FAILED", None, f"评论区未找到原生 commentId 为 {root_comment_id} 的一级评论"

        if completeness != "COMPLETE":
            if verify_only:
                return "UNKNOWN", None, f"二级回复分页状态未知或折叠无法穷尽 ({completeness})，无法证明作者未回复"
            return "FAILED", None, f"二级回复分页状态不完整或未知 ({completeness})，无法证明作者未回复，触发 Fail-Closed 硬阻断，禁止出站"

        if verify_only:
            if verify_controls:
                calib = self.calibrate_comment_controls(
                    page,
                    parent_item=parent_item,
                    root_comment_id=root_comment_id,
                    attempt_dir=attempt_dir,
                )
                if not calib.get("ok"):
                    return "FAILED", None, f"只读控件校准失败: {calib.get('error')}"
                return "VERIFIED_ABSENT", calib.get("evidence_screenshot"), "只读核验：目标评论存在、作者未回复且控件校准通过"
            return "VERIFIED_ABSENT", None, "只读核验：目标评论存在且作者尚未回复"

        # 3. 点击该一级评论的“回复”按钮展开回复输入框
        reply_candidates = [
            ".action-icon.weui-icon-outlined-comment",
            ".action-item:has(.weui-icon-outlined-comment)",
            "[data-reply]",
            "button[aria-label='回复'], [role='button'][aria-label='回复']",
            "button:text-is('回复'), [role='button']:text-is('回复')",
            ".weui-desktop-icon[aria-label='回复'], [title='回复']",
            "button:has-text('回复'), [role='button']:has-text('回复')",
            "[data-action='reply']",
            ".comment-item__action:has-text('回复')",
        ]
        reply_btn = None
        for cand in reply_candidates:
            loc = parent_item.locator(cand).filter(visible=True)
            if loc.count() == 1:
                reply_btn = loc.first
                break
            elif loc.count() > 1:
                return "FAILED", None, f"回复按钮选择器 '{cand}' 匹配到多个可见控件 ({loc.count()})，触发歧义阻断"

        if reply_btn is None or not reply_btn.is_enabled():
            return "FAILED", None, "未能唯一定位可用的回复按钮；禁止按图标顺序或通用 button 猜测"
        reply_btn.click()
        page.wait_for_timeout(1000)

        # 定位输入框
        editor_candidates = [
            ".edit-area[contenteditable='true']",
            ".comment-reply-wrap .edit-area",
            "textarea[placeholder*='回复'], textarea[data-comment-editor], textarea.weui-desktop-form__textarea",
            "textarea.create-input, textarea[placeholder*='说点什么']",
            "textarea",
        ]
        textarea = None
        for cand in editor_candidates:
            loc = parent_item.locator(cand).filter(visible=True)
            if loc.count() == 1:
                textarea = loc.first
                break
            elif loc.count() > 1:
                return "FAILED", None, f"父评论内输入框匹配到多个 ({loc.count()})，选择器: {cand}"

        if textarea is None:
            for cand in editor_candidates[:3]:
                loc = page.locator(cand).filter(visible=True)
                if loc.count() == 1:
                    textarea = loc.first
                    break

        if textarea is None:
            return "FAILED", None, "未能定位到二级回复输入框"

        textarea.fill(reply_content)
        page.wait_for_timeout(500)

        # 确认唯一且可用的提交控件后，才持久化意图；后续不明结果不得重发。
        submit_candidates = [
            ".comment-reply-wrap button.weui-desktop-btn_primary:text-is('评论')",
            ".reply-opt button:text-is('评论')",
            "button:text-is('评论'), button:text-is('发送'), button[data-submit]",
            ".create-ft .tag-wrap.primary, .weui-desktop-btn_primary:text-is('评论')",
            "button[type='submit']",
            "[data-action='submit']",
        ]
        submit_btn = None
        for cand in submit_candidates:
            loc = parent_item.locator(cand).filter(visible=True)
            if loc.count() == 1:
                submit_btn = loc.first
                break
            elif loc.count() > 1:
                return "FAILED", None, f"提交按钮选择器 '{cand}' 匹配到多个可见控件 ({loc.count()})，触发歧义阻断"

        if submit_btn is None:
            for cand in submit_candidates[:2]:
                loc = page.locator(cand).filter(visible=True)
                if loc.count() == 1:
                    submit_btn = loc.first
                    break

        if submit_btn is None or not submit_btn.is_enabled():
            return "FAILED", None, "未能唯一定位可用的提交按钮"

        # 4. 提交前持久化提交意图 (SUBMIT_INTENT)
        if before_submit is not None:
            intent_ok = before_submit()
            if not intent_ok:
                return "FAILED", None, "持久化提交意图失败（配额超限或防重冲突），中止发送"

        # 5. 点击提交
        submit_btn.first.click()
        page.wait_for_timeout(3000)

        # 6. 验证出站拦截情况
        if guard.mismatched_requests and not guard.requests:
            mism = guard.mismatched_requests[0]
            return "FAILED", None, f"发送前路由守卫拦截: {mism.get('reason')} ({mism.get('details')})"

        if send_only:
            if guard.requests:
                return "SENT", None, None
            return "UNCERTAIN", None, "意图已持久化，但未观察到出站请求"

        # 7. 验证接口响应：只认与唯一准许出站 Request 关联且字段一致的业务成功回执
        api_success, new_reply_id, _resp_reason = guard.validate_success_response()

        # 8. 刷新并进行独立回读校验（刷新前截图只作为“未经核对”的现场记录，不作为成功证据）
        pre_reload_img = attempt_dir / "post_submit_pre_reload_unverified.png"
        evidence_img = attempt_dir / "verified_reply.png"
        try:
            page.screenshot(path=str(pre_reload_img))
        except Exception:
            pass

        # T10 铁律：双重成功确认 — 平台返回成功 且 独立回读确认存在于父评论下
        if api_success:
            readback_ok = False
            # 必须有非空的平台回复 ID，且在“重新加载页面”后由服务器数据渲染出：
            # 同作品、父评论下、原生作者身份一致、正文（专用内容节点）NFC 后完整等值
            if new_reply_id:
                try:
                    page.reload()
                    page.wait_for_timeout(1500)
                    state, found_id = self.find_author_reply(
                        page, platform_post_id=platform_post_id, root_comment_id=root_comment_id,
                        reply_content=reply_content, author_id=guard.expected_finder_id,
                        video_title=video_title, published_description=published_description,
                    )
                    readback_ok = state == "FOUND" and found_id == new_reply_id
                except Exception as exc:  # 回读异常不得判成功
                    logger.warning("[SecondaryReplyBrowser] 重新加载回读异常: %s", exc)

            if readback_ok:
                # 成功证据必须是刷新并核对通过之后的页面状态；保存失败则不得报告 VERIFIED（避免无证据成功）
                try:
                    page.screenshot(path=str(evidence_img))
                except Exception as exc:
                    logger.warning("[SecondaryReplyBrowser] 成功证据保存失败: %s", exc)
                    if db:
                        db.record_secondary_reply_uncertain(
                            task_id=task_id,
                            error_message="平台回读确认，但成功证据保存失败，转入只读对账",
                            evidence_path=str(pre_reload_img),
                        )
                    return "UNCERTAIN", str(pre_reload_img), "成功证据保存失败，转入 UNCERTAIN"
                if db:
                    persisted = db.record_secondary_reply_success(
                        task_id=task_id,
                        platform_reply_comment_id=new_reply_id,
                        evidence_path=str(evidence_img),
                    )
                    if not persisted:
                        # 成功落库被拒（状态不符/缺 ID）时不得对外报告 VERIFIED
                        db.record_secondary_reply_uncertain(
                            task_id=task_id,
                            error_message="平台回读确认但本地成功落库被拒绝，转入只读对账",
                            evidence_path=str(evidence_img),
                        )
                        return "UNCERTAIN", str(evidence_img), "成功落库返回 False，转入 UNCERTAIN"
                return "VERIFIED", str(evidence_img), None
            else:
                logger.warning(
                    "[SecondaryReplyBrowser] 平台返回 201 成功，但独立回读未找到回复节点（可能延迟或被隐藏），转入 UNCERTAIN 对账"
                )
                if db:
                    db.record_secondary_reply_uncertain(
                        task_id=task_id,
                        error_message="平台接口成功返回 201，但页面独立回读未找到回复节点，转入只读对账",
                        evidence_path=str(pre_reload_img),
                    )
                return "UNCERTAIN", str(pre_reload_img), "平台返回 201 但独立回读未确认，转入 UNCERTAIN"

        # 若发出了请求但未收到明确成功回执，必须进入 UNCERTAIN 只读对账
        if guard.requests:
            if db:
                db.record_secondary_reply_uncertain(
                    task_id=task_id,
                    error_message="发评请求已发出，但未收到确定的 201 成功回执",
                    evidence_path=str(pre_reload_img),
                )
            return "UNCERTAIN", str(pre_reload_img), "未收到确定成功回执，转入 UNCERTAIN 对账"

        return "FAILED", str(pre_reload_img), "未触发发评网络请求"

    @contextlib.contextmanager
    def open_session(self, guard: Optional[SecondaryReplySubmissionGuard] = None):
        """会话锁 + 全新 Chromium 上下文 + 发送路由守卫，yield 已打开评论页的 page。

        每次调用都是全新会话，因此在其中读到的数据来自服务器而非上一次会话的乐观 DOM。
        """
        if not self.state_path.exists():
            raise FileNotFoundError(f"登录态文件不存在: {self.state_path}")
        with WeChatSessionLock(self.state_path, timeout_seconds=self.lock_timeout_seconds):
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=self.headless, args=["--window-size=1920,1080", "--no-proxy-server"],
                )
                context = create_wechat_context(
                    browser,
                    storage_state=str(self.state_path),
                    viewport={"width": 1920, "height": 1080},
                )
                try:
                    page = context.new_page()
                    self._setup_page_listeners(page, guard)
                    if guard is not None:
                        def route_interceptor(route):
                            if not guard.capture_request(route.request):
                                logger.critical("[SecondaryReplyBrowser] 拦截到违规或错帖请求，中止请求！")
                                route.abort()
                                return
                            route.continue_()

                        page.route("**/comment/create_comment*", route_interceptor)
                    else:
                        # 只读会话不携带发送许可；即使页面意外触发提交也必须拦截。
                        page.route("**/comment/create_comment*", lambda route: route.abort())
                    page.goto(self.comment_url, timeout=45000, wait_until="domcontentloaded")
                    try:
                        page.wait_for_selector(".comment-feed-wrap, [data-object-id]", timeout=15000)
                    except Exception:
                        page.wait_for_timeout(2000)
                    yield page
                finally:
                    context.close()
                    browser.close()

    def find_author_reply(
        self,
        page,
        *,
        platform_post_id: str,
        root_comment_id: str,
        reply_content: str,
        author_id: str,
        video_title: Optional[str] = None,
        published_description: Optional[str] = None,
    ) -> Tuple[str, str]:
        """只读：在已打开页面的正确作品/父评论下，查找同作者且正文 NFC 完整等值的回复。

        返回 (状态, 回复原生 ID)；状态为 FOUND / NOT_FOUND / AMBIGUOUS / UNKNOWN。
        只有恰好一个匹配才 FOUND；找不到不代表未发出，仅代表“未观察到”。
        """
        if not author_id or "'" in author_id:
            return "UNKNOWN", ""
        is_login, _ = check_explicit_login_prompt(page)
        if is_login:
            return "UNKNOWN", ""
        card = self._resolve_video_card(page, platform_post_id, video_title, published_description)
        if card is None:
            return "UNKNOWN", ""
        self._captured_comments.clear()
        self._active_export_id = None
        card.click()
        page.wait_for_timeout(1500)
        _replied, _comp, parent = self._check_author_already_replied(page, root_comment_id, author_id)
        if parent is None or _comp != "COMPLETE":
            return "UNKNOWN", ""
        api_info = self._captured_comments.get(root_comment_id)
        if api_info is not None:
            if api_info.get("export_id") != platform_post_id or self._active_export_id != platform_post_id:
                return "UNKNOWN", ""
            if type(api_info.get("downContinueFlag")) is not int or api_info["downContinueFlag"] != 0:
                return "UNKNOWN", ""
            want = unicodedata.normalize("NFC", reply_content)
            matches = [str(sub["commentId"]) for sub in api_info.get("levelTwoComment", [])
                       if isinstance(sub, dict) and sub.get("commentId")
                       and sub.get("username") == author_id
                       and unicodedata.normalize("NFC", str(sub.get("commentContent") or "")) == want]
            if len(matches) == 1:
                return "FOUND", matches[0]
            return ("AMBIGUOUS" if matches else "NOT_FOUND"), ""
        post_attr = parent.locator("xpath=ancestor::article[@data-current-object-id]")
        if post_attr.count() != 1 or post_attr.first.get_attribute("data-current-object-id") != platform_post_id:
            return "UNKNOWN", ""
        want = _normalized_text(unicodedata.normalize("NFC", reply_content))
        nodes = parent.locator(".level-two, [data-level-two]").locator(f"[data-author-id='{author_id}']")
        matches: List[str] = []
        for i in range(nodes.count()):
            node = nodes.nth(i)
            content = node.locator("[data-reply-content]")
            if content.count() != 1:
                continue
            if _normalized_text(unicodedata.normalize("NFC", content.first.inner_text())) == want:
                matches.append(node.get_attribute("data-comment-id") or "")
        matches = [m for m in matches if m]
        if len(matches) == 1:
            return "FOUND", matches[0]
        if len(matches) > 1:
            return "AMBIGUOUS", ""
        return "NOT_FOUND", ""

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
        title_hint = self._post_descriptions.get(platform_post_id) or video_title or published_description or ""
        clean_hint = _normalized_text(title_hint)[:20]
        if clean_hint:
            cards = page.locator(".comment-feed-wrap:visible, .post-card:visible").filter(has_text=clean_hint)
            if cards.count() == 1:
                return cards.first

        # 3. 若初始未找到且页面存在滚动列表容器，执行滚轮分页向下查找
        scroll_container = page.locator(".scroll-list__wrp, .feeds-container, .scroll-list").filter(visible=True)
        if scroll_container.count() > 0:
            for _ in range(15):
                try:
                    scroll_container.first.hover()
                except Exception:
                    pass
                page.mouse.wheel(0, 2500)
                page.wait_for_timeout(800)

                # 重新检查 data-object-id
                card = page.locator(f"[data-object-id='{platform_post_id}']").filter(visible=True)
                if card.count() == 1:
                    return card.first

                # 重新检查文案匹配
                if clean_hint:
                    cards = page.locator(".comment-feed-wrap:visible, .post-card:visible").filter(has_text=clean_hint)
                    if cards.count() == 1:
                        return cards.first
                    elif cards.count() > 1:
                        logger.warning("[SecondaryReplyBrowser] 文案 '%s' 匹配到多个卡片 (%d)，触发歧义阻断", clean_hint, cards.count())
                        return None

        return None

    def _check_author_already_replied(
        self,
        page,
        root_comment_id: str,
        author_id: Optional[str],
    ) -> Tuple[bool, str, Any]:
        """检查指定一级评论下是否已有作者回复与分页完整性。

        返回 (already_replied, completeness, parent_node)
        - already_replied: 是否已存在作者二级回复（以原生作者 ID 为准）
        - completeness: 分页完整性状态 (COMPLETE / PAGINATION_UNKNOWN / PAGINATION_INCOMPLETE)
        - parent_node: 一级评论节点定位器
        """
        # 1. 定位一级评论 DOM 节点
        parent_loc = page.locator(f"[data-comment-id='{root_comment_id}']")
        parent_node = None
        if parent_loc.count() == 1:
            parent_node = parent_loc.first
        else:
            # 真实平台回退：通过 captured_comments 中的内容特征唯一定位
            info = self._captured_comments.get(root_comment_id)
            if info and info.get("content_prefix") and info.get("export_id") == self._active_export_id:
                candidates = page.locator(".comment-item:visible").filter(has_text=info["content_prefix"])
                same_text = [c for c in self._captured_comments.values()
                             if c.get("content_prefix") == info["content_prefix"]]
                if candidates.count() == 1 and len(same_text) == 1:
                    parent_node = candidates.first

        if parent_node is None:
            return False, "NOT_FOUND", None

        if not author_id or "'" in author_id:
            return False, "INVALID_AUTHOR_ID", parent_node

        # 2. 检查当前已渲染的二级回复中是否已有作者回复
        author_nodes = parent_node.locator(".level-two, [data-level-two], .comment-reply-list").locator(
            f"[data-author-id='{author_id}']"
        )
        if author_nodes.count() > 0:
            return True, "COMPLETE", parent_node

        # 检查网络监听捕获的回复数据
        api_info = self._captured_comments.get(root_comment_id, {})
        if any(isinstance(sub, dict) and sub.get("username") == author_id
               for sub in api_info.get("levelTwoComment", [])):
            return True, "COMPLETE", parent_node

        # 3. 检查是否有折叠或后续分页
        dom_status = parent_node.get_attribute("data-pagination-status") or ""
        if dom_status in ("unknown", "error", "timeout"):
            return False, "PAGINATION_UNKNOWN", parent_node

        expand_btn = parent_node.locator(
            "button:has-text('展开'), [data-action='expand-replies'], .show-more-replies, [data-expand-replies]"
        ).filter(visible=True)

        if expand_btn.count() > 0:
            try:
                expand_btn.first.click()
                page.wait_for_timeout(1000)
            except Exception as exc:
                logger.warning("[SecondaryReplyBrowser] 点击展开二级回复失败: %s", exc)
                return False, "PAGINATION_UNKNOWN", parent_node

            # 展开后重新检查是否有作者回复
            author_nodes_after = parent_node.locator(".level-two, [data-level-two], .comment-reply-list").locator(
                f"[data-author-id='{author_id}']"
            )
            if author_nodes_after.count() > 0:
                return True, "COMPLETE", parent_node

            # 检查展开后是否依然有未穷尽分页
            api_info = self._captured_comments.get(root_comment_id, {})
            if any(isinstance(sub, dict) and sub.get("username") == author_id
                   for sub in api_info.get("levelTwoComment", [])):
                return True, "COMPLETE", parent_node
            still_has_btn = parent_node.locator(
                "button:has-text('展开'), [data-action='expand-replies'], .show-more-replies, [data-expand-replies]"
            ).filter(visible=True).count() > 0
            new_status = parent_node.get_attribute("data-pagination-status") or ""
            if still_has_btn or new_status in ("unknown", "incomplete") or (api_info.get("downContinueFlag") == 1):
                return False, "PAGINATION_INCOMPLETE", parent_node

        elif api_info.get("downContinueFlag") == 1 or parent_node.get_attribute("data-down-continue-flag") == "1":
            # API 或 DOM 明确标记有更多回复，但界面上没有可展开按钮 -> 无法证明完整
            return False, "PAGINATION_INCOMPLETE", parent_node

        # 真实接口缺少明确的分页终止标记不能当成空列表；DOM 夹具保留兼容。
        if parent_loc.count() != 1 and (
            type(api_info.get("downContinueFlag")) is not int or api_info["downContinueFlag"] != 0
        ):
            return False, "PAGINATION_UNKNOWN", parent_node
        # 完整确认无作者回复
        return False, "COMPLETE", parent_node

    def calibrate_comment_controls(
        self,
        page: Any,
        *,
        parent_item: Any,
        root_comment_id: str,
        attempt_dir: Optional[Path | str] = None,
    ) -> Dict[str, Any]:
        """只读探测并校准目标一级评论下的二级回复相关控件。

        严格执行零写安全：
        - 不向 textarea / edit-area 输入任何真实内容；
        - 绝不点击 submit 提交按钮；
        - 校验提交按钮在输入框为空时的不可用/禁用状态；
        - 若打开了回复编辑器，在探测结束后通过取消按钮或 ESC 恢复现场；
        - 产出各控件的选择器、数量、可见性与可用性诊断字典。
        """
        if parent_item is None or parent_item.count() != 1:
            return {"ok": False, "error": f"一级评论节点不唯一或未找到 (commentId: {root_comment_id})"}

        # 1. 探测回复图标按钮
        reply_candidates = [
            ".action-icon.weui-icon-outlined-comment",
            ".action-item:has(.weui-icon-outlined-comment)",
            "[data-reply]",
            "button[aria-label='回复'], [role='button'][aria-label='回复']",
            "button:text-is('回复'), [role='button']:text-is('回复')",
            ".weui-desktop-icon[aria-label='回复'], [title='回复']",
            "button:has-text('回复'), [role='button']:has-text('回复')",
            "[data-action='reply']",
            ".comment-item__action:has-text('回复')",
        ]
        reply_selector_matched = None
        reply_btn_loc = None
        for cand in reply_candidates:
            loc = parent_item.locator(cand).filter(visible=True)
            if loc.count() == 1:
                reply_selector_matched = cand
                reply_btn_loc = loc.first
                break
            elif loc.count() > 1:
                return {
                    "ok": False,
                    "error": f"回复按钮选择器 '{cand}' 匹配到多个可见控件 ({loc.count()})，触发歧义阻断",
                }

        if not reply_selector_matched or not reply_btn_loc:
            return {"ok": False, "error": "未能唯一定位可用的二级回复触发按钮"}

        reply_enabled = reply_btn_loc.is_enabled()
        if not reply_enabled:
            return {"ok": False, "error": f"回复按钮处于禁用状态: {reply_selector_matched}"}

        # 2. 探测二级回复展开折叠按钮
        expand_candidates = [
            ".comment-reply-list button:has-text('展开'), .comment-reply-list [data-action='expand-replies'], .comment-reply-list .show-more-replies, .comment-reply-list :text-matches('展开|查看.*回复')",
            "button:has-text('展开'), [role='button']:has-text('展开')",
            "[data-action='expand-replies'], [data-expand-replies]",
            ".show-more-replies, .show-more:has-text('展开')",
            "span:has-text('展开'), a:has-text('展开')",
        ]
        expand_matched = None
        expand_count = 0
        expand_text = None
        for cand in expand_candidates:
            loc = parent_item.locator(cand).filter(visible=True)
            if loc.count() > 0:
                expand_matched = cand
                expand_count = loc.count()
                try:
                    expand_text = loc.first.inner_text().strip()
                except Exception:
                    pass
                break

        # 3. 展开回复编辑器（若尚未展开）
        editor_already_open = parent_item.locator(".edit-area:visible, textarea:visible").count() > 0
        if not editor_already_open:
            reply_btn_loc.click()
            page.wait_for_timeout(500)

        # 4. 探测输入框
        editor_candidates = [
            ".edit-area[contenteditable='true']",
            ".comment-reply-wrap .edit-area",
            "textarea[placeholder*='回复'], textarea[data-comment-editor], textarea.weui-desktop-form__textarea",
            "textarea.create-input, textarea[placeholder*='说点什么']",
            "textarea",
        ]
        textarea_matched = None
        textarea_loc = None
        for cand in editor_candidates:
            loc = parent_item.locator(cand).filter(visible=True)
            if loc.count() == 1:
                textarea_matched = cand
                textarea_loc = loc.first
                break
            elif loc.count() > 1:
                self._safe_close_editor(page, parent_item, editor_already_open)
                return {
                    "ok": False,
                    "error": f"父评论内输入框匹配到多个 ({loc.count()})，选择器: {cand}",
                }

        if not textarea_loc:
            # 针对微前端悬浮或 Portal 弹层，在全局页面兜底查找
            for cand in editor_candidates[:3]:
                loc = page.locator(cand).filter(visible=True)
                if loc.count() == 1:
                    textarea_matched = cand
                    textarea_loc = loc.first
                    break

        if not textarea_loc:
            self._safe_close_editor(page, parent_item, editor_already_open)
            return {"ok": False, "error": "未能定位到二级回复输入框"}

        textarea_editable = textarea_loc.is_editable()
        try:
            textarea_empty = bool(
                textarea_loc.evaluate("el => (el.value !== undefined ? el.value : el.innerText).trim() === ''")
            )
        except Exception:
            textarea_empty = True

        # 5. 探测提交按钮
        submit_candidates = [
            ".comment-reply-wrap button.weui-desktop-btn_primary:text-is('评论')",
            ".reply-opt button:text-is('评论')",
            "button:text-is('评论'), button:text-is('发送'), button[data-submit]",
            ".create-ft .tag-wrap.primary, .weui-desktop-btn_primary:text-is('评论')",
            "button[type='submit']",
            "[data-action='submit']",
        ]
        submit_matched = None
        submit_loc = None
        for cand in submit_candidates:
            loc = parent_item.locator(cand).filter(visible=True)
            if loc.count() == 1:
                submit_matched = cand
                submit_loc = loc.first
                break
            elif loc.count() > 1:
                self._safe_close_editor(page, parent_item, editor_already_open)
                return {
                    "ok": False,
                    "error": f"父评论内提交按钮匹配到多个 ({loc.count()})，选择器: {cand}",
                }

        if not submit_loc:
            # 微前端 portal 弹层兜底
            for cand in submit_candidates[:2]:
                loc = page.locator(cand).filter(visible=True)
                if loc.count() == 1:
                    submit_matched = cand
                    submit_loc = loc.first
                    break

        if not submit_loc:
            self._safe_close_editor(page, parent_item, editor_already_open)
            return {"ok": False, "error": "未能定位到二级回复提交按钮"}

        is_disabled_when_empty = bool(
            submit_loc.is_disabled()
            or submit_loc.get_attribute("aria-disabled") == "true"
            or "disabled" in (submit_loc.get_attribute("class") or "")
        )

        # 6. 安全关闭编辑器，恢复现场
        editor_closed = self._safe_close_editor(page, parent_item, editor_already_open, textarea_loc)

        # 7. 截图留证
        evidence_path = None
        if attempt_dir:
            shot_target = Path(attempt_dir) / f"controls_calibration_{root_comment_id}.png"
            try:
                page.screenshot(path=str(shot_target))
                evidence_path = str(shot_target)
            except Exception:
                pass

        return {
            "ok": True,
            "error": None,
            "controls_calibration": {
                "reply_icon": {
                    "selector": reply_selector_matched,
                    "found": True,
                    "count": 1,
                    "visible": True,
                    "enabled": reply_enabled,
                },
                "editor_textarea": {
                    "selector": textarea_matched,
                    "found": True,
                    "count": 1,
                    "visible": True,
                    "editable": textarea_editable,
                    "is_empty": textarea_empty,
                },
                "submit_button": {
                    "selector": submit_matched,
                    "found": True,
                    "count": 1,
                    "visible": True,
                    "enabled_when_filled": True,
                    "disabled_when_empty": is_disabled_when_empty,
                },
                "expand_button": {
                    "selector": expand_matched,
                    "found": bool(expand_count > 0),
                    "count": expand_count,
                    "visible": bool(expand_count > 0),
                    "text": expand_text,
                },
            },
            "editor_closed_cleanly": editor_closed,
            "evidence_screenshot": evidence_path,
        }

    def _safe_close_editor(
        self,
        page: Any,
        parent_item: Any,
        editor_already_open: bool,
        textarea_loc: Optional[Any] = None,
    ) -> bool:
        """安全关闭回复编辑器，避免污染 DOM 现场。"""
        if editor_already_open:
            return True
        cancel_candidates = [
            ".reply-opt button:text-is('取消')",
            "button:text-is('取消'), [data-action='cancel'], .cancel-btn, [role='button']:text-is('取消')",
        ]
        for cand in cancel_candidates:
            cancel_btn = parent_item.locator(cand).filter(visible=True)
            if cancel_btn.count() == 1:
                try:
                    cancel_btn.first.click()
                    page.wait_for_timeout(300)
                    break
                except Exception:
                    pass
        if textarea_loc is not None:
            try:
                if textarea_loc.is_visible():
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(300)
            except Exception:
                pass
            try:
                return not textarea_loc.is_visible()
            except Exception:
                return True
        return True

    def calibrate_page_controls(
        self,
        page: Any,
        *,
        platform_post_id: str,
        root_comment_id: str,
        author_id: str,
        video_title: Optional[str] = None,
        published_description: Optional[str] = None,
        expected_comment_text: Optional[str] = None,
        attempt_dir: Optional[Path | str] = None,
    ) -> Dict[str, Any]:
        """在已打开的页面上执行卡片定位、作者状态核验与二级回复控件校准。"""
        is_login, _ = check_explicit_login_prompt(page)
        if is_login:
            return {
                "ok": False,
                "status": "LOGIN_REQUIRED",
                "reason": "LOGIN_REQUIRED",
                "channel_profile": {"finder_id": author_id},
                "target": {"post_id": platform_post_id, "comment_id": root_comment_id, "fresh": False},
            }

        # 0. 检验原生作者身份与登录态
        native_username = ""
        channel_nickname = ""
        try:
            native_username = str(page.evaluate("""() => {
                try {
                    return localStorage.getItem('finder_username') || window.__finder_username || document.body.getAttribute('data-finder-username') || '';
                } catch (e) {
                    return window.__finder_username || document.body.getAttribute('data-finder-username') || '';
                }
            }""") or "").strip()
            channel_nickname = str(page.evaluate("""() => {
                const el = document.querySelector('.account-info .name, .account-info, .finder-nickname');
                return el ? el.innerText.trim() : '';
            }""") or "").strip()
        except Exception:
            pass

        identity_verified = bool(author_id and (native_username == author_id or author_id in native_username))
        channel_profile = {
            "finder_id": author_id,
            "native_username": native_username,
            "channel_nickname": channel_nickname,
            "identity_verified": identity_verified,
        }

        card = self._resolve_video_card(page, platform_post_id, video_title, published_description)
        if card is None:
            return {
                "ok": False,
                "status": "UNKNOWN",
                "reason": f"未找到作品卡片 (exportId: {platform_post_id})",
                "channel_profile": channel_profile,
                "target": {"post_id": platform_post_id, "comment_id": root_comment_id, "fresh": False},
            }

        self._captured_comments.clear()
        self._active_export_id = None
        card.click()
        page.wait_for_timeout(1500)

        # 校验卡片详情归属
        bound = page.locator("[data-current-object-id]")
        bound_ok = False
        if bound.count() >= 1 and all(
            (bound.nth(i).get_attribute("data-current-object-id") or "") == platform_post_id
            for i in range(bound.count())
        ):
            bound_ok = True
        elif self._active_export_id and self._active_export_id == platform_post_id:
            bound_ok = True

        if not bound_ok:
            return {
                "ok": False,
                "status": "UNKNOWN",
                "reason": f"无法证明已打开的详情属于目标作品 (exportId: {platform_post_id})",
                "channel_profile": channel_profile,
                "target": {"post_id": platform_post_id, "comment_id": root_comment_id, "fresh": False},
            }

        already_replied, completeness, parent_item = self._check_author_already_replied(
            page, root_comment_id, author_id
        )

        comment_info = self._captured_comments.get(root_comment_id, {})
        actual_text = comment_info.get("content_prefix", "")
        actual_nickname = comment_info.get("nickname", "")
        if not actual_text and parent_item is not None:
            try:
                dom_text_loc = parent_item.locator(
                    ".comment-content, .content, [data-comment-content], [data-reply-content]"
                ).filter(visible=True)
                if dom_text_loc.count() > 0:
                    actual_text = dom_text_loc.first.inner_text().strip()
            except Exception:
                pass

        text_matched = True
        if expected_comment_text:
            text_matched = _normalized_text(actual_text) == _normalized_text(expected_comment_text)

        target_info = {
            "post_id": platform_post_id,
            "comment_id": root_comment_id,
            "video_title": video_title or "",
            "author_nickname": actual_nickname,
            "comment_text": actual_text,
            "text_matched": text_matched,
            "fresh": True,
        }

        shot_path = ""
        if already_replied:
            if attempt_dir:
                shot_target = Path(attempt_dir) / f"already_replied_{root_comment_id}.png"
                try:
                    page.screenshot(path=str(shot_target))
                    shot_path = str(shot_target)
                except Exception:
                    pass
            return {
                "ok": True,
                "status": "REPLIED",
                "completeness": completeness,
                "channel_profile": channel_profile,
                "target": target_info,
                "controls_calibration": {},
                "evidence_files": {"screenshot": shot_path},
            }

        if parent_item is None:
            return {
                "ok": False,
                "status": "UNKNOWN",
                "reason": f"评论区未找到原生 commentId 为 {root_comment_id} 的一级评论",
                "channel_profile": channel_profile,
                "target": {"post_id": platform_post_id, "comment_id": root_comment_id, "fresh": False},
            }

        if not text_matched:
            return {
                "ok": False,
                "status": "UNKNOWN",
                "reason": f"目标评论正文与预期不符 (实际: '{actual_text[:30]}...', 预期: '{expected_comment_text[:30]}...')",
                "channel_profile": channel_profile,
                "target": target_info,
            }

        if completeness != "COMPLETE":
            return {
                "ok": False,
                "status": "UNKNOWN",
                "reason": f"二级回复分页未穷尽 ({completeness})，无法证明作者未回复",
                "channel_profile": channel_profile,
                "target": target_info,
            }

        calib = self.calibrate_comment_controls(
            page, parent_item=parent_item, root_comment_id=root_comment_id, attempt_dir=attempt_dir
        )
        return {
            "ok": calib["ok"] and identity_verified and text_matched,
            "status": "NOT_REPLIED",
            "completeness": "COMPLETE",
            "reason": calib.get("error") if not calib["ok"] else (None if identity_verified else "作者原生身份核对失败"),
            "channel_profile": channel_profile,
            "target": target_info,
            "controls_calibration": calib.get("controls_calibration", {}),
            "editor_closed_cleanly": calib.get("editor_closed_cleanly", False),
            "evidence_files": {
                "screenshot": calib.get("evidence_screenshot") or "",
            },
        }

    def verify_and_calibrate_controls(
        self,
        *,
        platform_post_id: str,
        root_comment_id: str,
        video_title: Optional[str] = None,
        published_description: Optional[str] = None,
        author_finder_id: Optional[str] = None,
        expected_comment_text: Optional[str] = None,
        evidence_dir: Optional[Path | str] = None,
    ) -> Dict[str, Any]:
        """只读环境下的完整卡片导航、作者状态核验及控件校准入口（无写操作、无许可守卫、路由硬拦截）。"""
        out_dir = self._new_evidence_dir(evidence_dir)
        with self.open_session(guard=None) as page:
            return self.calibrate_page_controls(
                page,
                platform_post_id=platform_post_id,
                root_comment_id=root_comment_id,
                author_id=author_finder_id or "",
                video_title=video_title,
                published_description=published_description,
                expected_comment_text=expected_comment_text,
                attempt_dir=out_dir,
            )
