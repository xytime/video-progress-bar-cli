"""视频号作者评论的 fail-closed Playwright 适配器。

本模块始终要求平台原生作品 ID。当前真实后台列表没有暴露该 ID 的 DOM 属性时，
只允许以发布时已保存、且唯一命中的文案片段辅助定位；接口顺序或卡片索引绝不用于写入。
任何未知 schema 都会停止在提交前。一次点击后若结果不能完整确认，则返回
``UNCERTAIN``，调用方不得把它当作普通失败自动重试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 3.0.0 | 2026-09-26 | Codex | 绑定评论页完整文案与场景 ID；发送前阻断错帖请求，限定作品与完整作者评论回读。 |
| 2.9.0 | 2026-09-23 | Antigravity | 修复视频号后台处理中作品未上架导致卡片索引错位发评的严重缺陷；引入内容前缀强校验、详情面板文本核验与发评请求作品ID不符硬熔断（Fail-Closed）。 |
| 2.8.0 | 2026-09-20 | Antigravity | 新增首评自动置顶与替换确认逻辑，记录 is_pinned 证据。 |
| 2.7.0 | 2026-09-20 | Antigravity | 提取 resolve_target_card 纯逻辑，支持离线单元测试卡片索引消歧义与降级分支。 |
| 2.6.0 | 2026-09-20 | Antigravity | 遵循 AGENTS.md 规范优先以 post_list 原生 ID 精准索引绑定卡片，文本片段退为兜底，消除前缀重复卡片歧义。 |
| 2.5.0 | 2026-09-20 | Antigravity | 视口升级至1920x1080防响应式折叠，增强展开/折叠双模态菜单导航并引入评论路由守门断言。 |
| 2.4.0 | 2026-09-20 | Antigravity | 接入 post_list API 响应捕获与真实平台 exportId 精准索引卡片绑定，解决后台 DOM 缺少 data-id 属性的定位问题。 |
| 2.3.0 | 2026-09-20 | Codex | 依据真实后台只读校准，以唯一发布文案片段辅助绑定无原生 ID 属性的卡片；移除接口顺序回退，并在提交前再次确认活动卡片。 |
| 2.2.0 | 2026-09-20 | Antigravity | 真实发评闭环强化：支持 post_list API 索引卡片定位、真实微前端评论正文上屏回读兼容。 |
| 2.1.0 | 2026-09-20 | Antigravity | 真实平台校准：支持微前端接口路径(/micro/interaction/)、微前端类名选择器、双重绑定与手机号拦截检测。 |
| 2.0.0 | 2026-09-19 | Codex | 原生 ID、提交因果、完整作者回读、不可变证据、verify-only 与会话锁安全重构。 |
| 1.1.0 | 2026-09-19 | Antigravity | 加固 objectId 定位、接口返回与 DOM 回读。 |
| 1.0.0 | 2026-09-19 | Antigravity | 初始评论自动化与证据链。 |
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
from typing import Any, Optional, Tuple
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from video_processing.core.wechat_session_lock import WeChatSessionLock, WeChatSessionLockBusy

logger = logging.getLogger(__name__)

WECHAT_COMMENT_URL = "https://channels.weixin.qq.com/platform/interaction/comment"
# 真实平台已完成只读校准：包含微前端子路径与传统路径
COMMENT_SUBMIT_PATH = "/cgi-bin/mmfinderassistant-bin/comment/create"
COMMENT_SUBMIT_PATHS = {
    "/cgi-bin/mmfinderassistant-bin/comment/create",
    "/micro/interaction/cgi-bin/mmfinderassistant-bin/comment/create",
    "/cgi-bin/mmfinderassistant-bin/comment/comment_create",
    "/micro/interaction/cgi-bin/mmfinderassistant-bin/comment/comment_create",
    "/cgi-bin/mmfinderassistant-bin/comment/create_comment",
    "/micro/interaction/cgi-bin/mmfinderassistant-bin/comment/create_comment",
}
SET_TOP_COMMENT_PATH = "/cgi-bin/mmfinderassistant-bin/comment/set_top_comment"
SET_TOP_COMMENT_PATHS = {
    "/cgi-bin/mmfinderassistant-bin/comment/set_top_comment",
    "/micro/interaction/cgi-bin/mmfinderassistant-bin/comment/set_top_comment",
}
DEFAULT_STATE_FILE = Path(__file__).resolve().parents[3] / "output" / "wechat_state.json"

BrowserResult = Tuple[str, Optional[str], Optional[str]]
_PLATFORM_POST_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/=-]{0,255}\Z")


def _normalized_text(value: object) -> str:
    """按浏览器可见文本语义规范化空白，同时保留完整内容。"""
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _payload_value(payload: object, *names: str) -> object:
    """仅从顶层或明确 ``data`` 对象读取已知字段，不猜测未知结构。"""
    if not isinstance(payload, dict):
        return None
    for name in names:
        if name in payload:
            return payload[name]
    data = payload.get("data")
    if isinstance(data, dict):
        for name in names:
            if name in data:
                return data[name]
    return None


def _interaction_post_id(post_id: str, published_description: Optional[str], descriptions: dict[str, str]) -> tuple[str, str]:
    """不同后台场景可能返回不同 exportId；只允许完整已发布文案唯一绑定。"""
    if post_id in descriptions:
        return post_id, "exact_native_id"
    expected = _normalized_text(published_description)
    matches = [pid for pid, desc in descriptions.items() if expected and _normalized_text(desc) == expected]
    if len(matches) == 1 and len(expected) >= 30:
        return matches[0], "unique_exact_published_description"
    raise ValueError("评论页未找到原生 ID 或唯一完整已发布文案，拒绝绑定场景 ID")


def _read_live_author_comments(page, captured_comments, platform_post_id):
    """真实 DOM 作者徽标与完整正文，绑定同作品接口返回的唯一评论 ID。"""
    texts = page.locator('.comment-author-bandage:visible').evaluate_all("""els => els.flatMap(el => {
        let node = el.parentElement;
        while (node && node !== document.body) {
            const contents = node.querySelectorAll('.comment-content');
            if (contents.length) {
                return contents.length === 1 && node.querySelectorAll('.comment-author-bandage').length === 1
                    ? [contents[0].innerText] : [];
            }
            node = node.parentElement;
        }
        return [];
    })""")
    result = []
    for text in texts:
        normalized = _normalized_text(text)
        ids = {c['comment_id'] for c in (captured_comments or [])
               if c.get('platform_post_id') == platform_post_id and c.get('comment_id')
               and c.get('content') == normalized}
        if len(ids) == 1:
            result.append({'comment_id': next(iter(ids)), 'text': normalized})
    return result


def _extract_title_probes(
    video_title: Optional[str], target_desc: Optional[str] = None
) -> list[str]:
    """提取用于在评论管理页卡片和详情中强校验目标作品的文本探针。"""
    probes: list[str] = []
    candidates = [video_title, target_desc]
    for raw in candidates:
        if not raw:
            continue
        text = _normalized_text(raw).strip()
        if not text:
            continue
        # 1. 直接前缀 (15 字符)
        p1 = text[:15].strip()
        if p1 and p1 not in probes:
            probes.append(p1)
        # 2. 剥离开头的话题标签 (#...#)、书名号、中括号等符号后的核心文案前缀 (12 字符)
        core = re.sub(
            r"^([#＃][^#＃]+[#＃]\s*|[【《「『“\"][^】》」』”\"]+[】》」』”\"]\s*|[^\w\u4e00-\u9fa5]+)",
            "",
            text,
        ).strip()
        if core and len(core) >= 4:
            p2 = core[:12].strip()
            if p2 and p2 not in probes:
                probes.append(p2)
    return probes


class _SubmissionResponseWindow:
    """只关联监听窗口内发出的精确提交 Request 及其 Response。"""

    def __init__(self, page_url: str, platform_post_id: str, expected_text: str) -> None:
        parsed = urlparse(page_url)
        self.origin = (parsed.scheme, parsed.netloc)
        self.platform_post_id = platform_post_id
        self.expected_text = expected_text
        self.requests: list[Any] = []
        self.responses: list[dict[str, Any]] = []
        self.mismatched_requests: list[dict[str, Any]] = []
        self.blocked_requests: list[dict[str, Any]] = []

    def guard_request(self, route) -> None:
        """网络发送前核对作品 ID 与全文；监听响应不能撤回已经发出的错帖。"""
        request = route.request
        parsed = urlparse(request.url)
        if parsed.path not in COMMENT_SUBMIT_PATHS:
            route.fallback()
            return
        try:
            payload = request.post_data_json
            pid = str(_payload_value(payload, "objectId", "object_id", "exportId", "export_id") or "").strip()
            text = _normalized_text(_payload_value(payload, "content", "comment", "commentText"))
        except Exception:
            pid, text = "", ""
        if request.method != "POST" or (parsed.scheme, parsed.netloc) != self.origin or pid != self.platform_post_id or text != self.expected_text:
            self.blocked_requests.append({"payload_id": pid, "expected_post_id": self.platform_post_id})
            route.abort()
            return
        route.fallback()

    def capture_request(self, request) -> None:
        parsed = urlparse(request.url)
        if (
            request.method != "POST"
            or (parsed.scheme, parsed.netloc) != self.origin
            or parsed.path not in COMMENT_SUBMIT_PATHS
        ):
            return
        try:
            payload = request.post_data_json
        except Exception:
            return
        payload_id = str(_payload_value(payload, "objectId", "object_id", "exportId", "export_id") or "").strip()
        if payload_id != self.platform_post_id:
            self.mismatched_requests.append({
                "url": request.url,
                "payload_id": payload_id,
                "expected_post_id": self.platform_post_id,
            })
            return
        text = _normalized_text(_payload_value(payload, "content", "comment", "commentText"))
        if text == self.expected_text:
            self.requests.append(request)

    def capture_response(self, response) -> None:
        request = response.request
        parsed = urlparse(response.url)
        if (
            (parsed.scheme, parsed.netloc) != self.origin
            or parsed.path not in COMMENT_SUBMIT_PATHS
            or not any(candidate is request for candidate in self.requests)
        ):
            return
        try:
            payload = response.json()
        except Exception:
            payload = None
        self.responses.append({"request": request.post_data_json, "response": payload})


class BrowserCommenter:
    """对一份登录态串行执行作者评论或只读核验。"""

    def __init__(
        self,
        *,
        state_path: Path | str = DEFAULT_STATE_FILE,
        lock_path: Path | str | None = None,
        headless: bool = True,
        comment_url: str = WECHAT_COMMENT_URL,
        browser_executable_path: Path | str | None = None,
        response_timeout_ms: int = 5_000,
        dom_timeout_ms: int = 6_000,
        poll_interval_ms: int = 100,
        lock_timeout_seconds: float = 0.25,
    ) -> None:
        self.state_path = Path(state_path)
        # 旧参数只为构造兼容保留；共享锁必须由 state path 唯一派生，禁止分叉。
        self.lock_path = Path(lock_path) if lock_path is not None else None
        self.headless = headless
        self.comment_url = comment_url
        self.browser_executable_path = (
            str(browser_executable_path) if browser_executable_path is not None else None
        )
        self.response_timeout_ms = max(0, int(response_timeout_ms))
        self.dom_timeout_ms = max(0, int(dom_timeout_ms))
        self.poll_interval_ms = max(10, int(poll_interval_ms))
        self.lock_timeout_seconds = max(0.0, float(lock_timeout_seconds))

    def post_comment(
        self,
        comment_text: str,
        platform_post_id: str,
        video_title: Optional[str] = None,
        evidence_dir: Optional[Path | str] = None,
        before_submit: Callable[[], bool] | None = None,
        verify_only: bool = False,
        published_description: Optional[str] = None,
    ) -> BrowserResult:
        """提交或只读核验作者评论，保持 ``(status, evidence, error)`` 返回合同。"""
        post_id = str(platform_post_id or "").strip()
        expected_text = _normalized_text(comment_text)
        if not post_id:
            return "FAILED", None, "必须提供有效的 platform_post_id 进行精确定位，严禁盲发"
        if not _PLATFORM_POST_ID_RE.fullmatch(post_id):
            return "FAILED", None, "platform_post_id 包含未校准字符，拒绝构造 DOM 选择器"
        if not expected_text:
            return "FAILED", None, "评论正文为空，拒绝打开写入界面"
        if not self.state_path.exists():
            return "FAILED", None, f"登录凭据不存在: {self.state_path}"
        if not verify_only and before_submit is None:
            return "FAILED", None, "live 发评必须提供持久化 before_submit 回调"

        attempt_dir = self._new_attempt_dir(evidence_dir)
        try:
            with WeChatSessionLock(self.state_path, timeout_seconds=self.lock_timeout_seconds):
                return self._run_browser(
                    comment_text=comment_text,
                    platform_post_id=post_id,
                    video_title=video_title,
                    attempt_dir=attempt_dir,
                    before_submit=before_submit,
                    verify_only=verify_only,
                    published_description=published_description,
                )
        except WeChatSessionLockBusy as exc:
            return self._finish(
                attempt_dir,
                "FAILED",
                "wechat session lock busy",
                details={"lock_error": str(exc), "clicked": False},
            )

    def _new_attempt_dir(self, evidence_dir: Optional[Path | str]) -> Path:
        root = (
            Path(evidence_dir)
            if evidence_dir is not None
            else self.state_path.parent / "wechat_evidence" / "interactions"
        )
        attempt = root / (
            f"attempt-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')}"
            f"-{uuid.uuid4().hex}"
        )
        attempt.mkdir(parents=True, exist_ok=False)
        return attempt

    def _run_browser(
        self,
        *,
        comment_text: str,
        platform_post_id: str,
        video_title: Optional[str],
        attempt_dir: Path,
        before_submit: Callable[[], bool] | None,
        verify_only: bool,
        published_description: Optional[str] = None,
    ) -> BrowserResult:
        """创建浏览器；不关闭 Web 安全、不禁用 Chromium sandbox。"""
        with sync_playwright() as runtime:
            launch_options: dict[str, Any] = {
                "headless": self.headless,
                "args": ["--window-size=1920,1080", "--no-proxy-server"],
            }
            if self.browser_executable_path:
                launch_options["executable_path"] = self.browser_executable_path
            browser = runtime.chromium.launch(**launch_options)
            try:
                context = browser.new_context(
                    viewport={"width": 1920, "height": 1080},
                    storage_state=str(self.state_path),
                )
                page = context.new_page()
                captured_post_ids: list[str] = []
                captured_post_descs: dict[str, str] = {}
                captured_comments: list[dict[str, Any]] = []

                def _on_response_capture(res: Any) -> None:
                    if "post/post_list" in res.url and res.status in (200, 201):
                        try:
                            body = res.json()
                            if isinstance(body, dict) and "data" in body and isinstance(body["data"], dict) and "list" in body["data"]:
                                for item in body["data"]["list"]:
                                    eid = str(item.get("exportId") or "").strip()
                                    oid = str(item.get("objectId") or "").strip()
                                    raw_desc = item.get("desc") or ""
                                    desc = _normalized_text(raw_desc.get("description") if isinstance(raw_desc, dict) else raw_desc)
                                    item_id = eid or oid
                                    if item_id and item_id not in captured_post_ids:
                                        captured_post_ids.append(item_id)
                                    if eid and desc:
                                        captured_post_descs[eid] = desc
                                    if oid and desc:
                                        captured_post_descs[oid] = desc
                        except Exception:
                            pass
                    if "comment/comment_list" in res.url and res.status in (200, 201):
                        try:
                            body = res.json()
                            request_post_id = str(_payload_value(res.request.post_data_json, "exportId", "objectId", "export_id", "object_id") or "")
                            if isinstance(body, dict) and "data" in body and isinstance(body["data"], dict) and "comment" in body["data"]:
                                captured_comments.append({"platform_post_id": request_post_id, "list_loaded": True})
                                for c in body["data"]["comment"]:
                                    captured_comments.append({
                                        "platform_post_id": request_post_id,
                                        "comment_id": str(c.get("commentId") or ""),
                                        "content": _normalized_text(str(c.get("commentContent") or "")),
                                    })
                        except Exception:
                            pass

                page.on("response", _on_response_capture)
                if "channels.weixin.qq.com" in self.comment_url:
                    page.goto("https://channels.weixin.qq.com/platform", timeout=30000, wait_until="domcontentloaded")
                    page.wait_for_timeout(2500)
                    if "platform/interaction/comment" not in page.url:
                        menu_link = page.get_by_role("link", name="互动管理")
                        if menu_link.count() > 0:
                            menu_link.first.click()
                            page.wait_for_timeout(1000)
                        else:
                            sub_wrp = page.locator(".finder-ui-desktop-menu__sub__wrp:has-text('互动管理'), .finder-ui-desktop-menu__sub__wrp:nth-child(2)")
                            if sub_wrp.count() > 0:
                                sub_wrp.first.click()
                                page.wait_for_timeout(1000)
                        comment_link = page.get_by_role("link", name="评论")
                        if comment_link.count() == 0:
                            comment_link = page.locator("a:has-text('评论'), .finder-ui-desktop-menu__link:has-text('评论')")
                        if comment_link.count() > 0:
                            comment_link.first.click()
                            page.wait_for_timeout(3500)
                        else:
                            page.goto(self.comment_url, timeout=30000, wait_until="domcontentloaded")
                            page.wait_for_timeout(3000)
                else:
                    page.goto(self.comment_url, wait_until="domcontentloaded")
                return self._interact_with_page(
                    page,
                    comment_text=comment_text,
                    platform_post_id=platform_post_id,
                    video_title=video_title,
                    attempt_dir=attempt_dir,
                    before_submit=before_submit,
                    verify_only=verify_only,
                    captured_post_ids=captured_post_ids,
                    captured_post_descs=captured_post_descs,
                    captured_comments=captured_comments,
                    published_description=published_description,
                )
            finally:
                browser.close()

    @staticmethod
    def resolve_target_card(
        page,
        platform_post_id: str,
        video_title: Optional[str] = None,
        captured_post_ids: Optional[list[str]] = None,
        captured_post_descs: Optional[dict[str, str]] = None,
    ):
        """解析页面上与目标作品对应的卡片定位器，严格遵循内容强校验与索引消歧义铁律。"""
        cards = page.locator(
            f'[data-object-id="{platform_post_id}"]:visible, '
            f'[data-post-id="{platform_post_id}"]:visible, '
            f'[data-id="{platform_post_id}"]:visible'
        )
        if cards.count() == 1:
            return cards

        feed_wraps = page.locator(".comment-feed-wrap:visible")
        if feed_wraps.count() == 0:
            return feed_wraps

        target_desc = (captured_post_descs or {}).get(platform_post_id)
        probes = _extract_title_probes(video_title, target_desc)
        if not probes:
            # 没有任何文案提示且无原生 ID 属性时，严禁盲发盲猜，Fail-Closed 返回空定位器
            return feed_wraps.filter(has_text="__NO_HINT_FAIL_CLOSED__")

        # 通过文案探针在可见卡片列表中进行内容强校验过滤
        matching = None
        matched_probe = None
        for probe in probes:
            candidate_matches = feed_wraps.filter(has_text=probe)
            if candidate_matches.count() > 0:
                matching = candidate_matches
                matched_probe = probe
                break

        # 若 DOM 中无任何卡片匹配目标文案（视频仍在转码处理中，后台列表未展示），坚决 Fail-Closed
        if matching is None or matching.count() == 0:
            return feed_wraps.filter(has_text="__NO_MATCHING_CARD_FAIL_CLOSED__")

        # 若恰好唯一匹配，直接返回
        if matching.count() == 1:
            return matching

        # 若存在多张卡片同时匹配前缀（如分集系列视频），尝试进一步消歧义：
        # 1. 先尝试更长/更精确的完整文案片段消歧义
        for full_text in [target_desc, video_title]:
            if full_text and len(full_text.strip()) > 15:
                longer_matches = matching.filter(has_text=full_text.strip()[:25])
                if longer_matches.count() == 1:
                    return longer_matches

        # 2. 结合 post_list 接口物理索引消歧义（仅在对应下标卡片通过内容校验时采信）
        if captured_post_ids and platform_post_id in captured_post_ids:
            idx = captured_post_ids.index(platform_post_id)
            if feed_wraps.count() > idx:
                candidate = feed_wraps.nth(idx)
                if matched_probe and candidate.filter(has_text=matched_probe).count() == 1:
                    return candidate

        # 若仍无法唯一确定，返回多重匹配定位器供调用方触发 Fail-Closed
        return matching

    def _interact_with_page(
        self,
        page,
        *,
        comment_text: str,
        platform_post_id: str,
        video_title: Optional[str],
        attempt_dir: Path,
        before_submit: Callable[[], bool] | None,
        verify_only: bool,
        captured_post_ids: Optional[list[str]] = None,
        captured_post_descs: Optional[dict[str, str]] = None,
        captured_comments: Optional[list[dict[str, Any]]] = None,
        published_description: Optional[str] = None,
    ) -> BrowserResult:
        """在已打开的真实页面上执行适配器合同，供隔离 Chromium 验收复用。"""
        clicked = False
        expected_text = _normalized_text(comment_text)
        metadata: dict[str, Any] = {
            "platform_post_id": platform_post_id,
            "video_title_hint": video_title,
            "verify_only": verify_only,
            "comment_text_normalized": expected_text,
            "adapter_contract": "wechat-comment-v3-scoped-author-readback",
        }
        if not _PLATFORM_POST_ID_RE.fullmatch(platform_post_id):
            return self._finish_page(
                page, attempt_dir, "FAILED",
                "platform_post_id 包含未校准字符，拒绝构造 DOM 选择器", metadata,
            )
        try:
            if "login" in page.url:
                return self._finish_page(page, attempt_dir, "FAILED", "微信登录态已失效", metadata)

            if "channels.weixin.qq.com" in self.comment_url and "platform/interaction/comment" not in page.url:
                return self._finish_page(
                    page, attempt_dir, "FAILED",
                    f"未能成功导航至视频号评论管理页面 (当前URL: {page.url})", metadata,
                )

            canonical_post_id = platform_post_id
            if captured_post_descs:
                try:
                    platform_post_id, binding = _interaction_post_id(platform_post_id, published_description, captured_post_descs)
                except ValueError as exc:
                    return self._finish_page(page, attempt_dir, "FAILED", str(exc), metadata)
                metadata["id_binding"] = binding
            if not _PLATFORM_POST_ID_RE.fullmatch(platform_post_id):
                return self._finish_page(page, attempt_dir, "FAILED", "评论页作品 ID 字符无效", metadata)
            metadata["interaction_post_id"] = platform_post_id
            metadata["platform_post_id"] = canonical_post_id

            cards = self.resolve_target_card(
                page,
                platform_post_id=platform_post_id,
                video_title=video_title,
                captured_post_ids=captured_post_ids,
                captured_post_descs=captured_post_descs,
            )

            visible_count = cards.count()
            if visible_count != 1:
                return self._finish_page(
                    page, attempt_dir, "FAILED",
                    f"原生 ID 目标卡片必须唯一，实际可见数量={visible_count}", metadata,
                )
            if captured_comments is not None:
                captured_comments.clear()
            cards.click()
            page.wait_for_timeout(self.poll_interval_ms)

            probes = _extract_title_probes(
                video_title,
                (captured_post_descs or {}).get(platform_post_id),
            )

            active_cards = page.locator('.comment-feed-wrap.active-feed:visible')
            if active_cards.count() > 0 and probes:
                matched_active = False
                for probe in probes:
                    if active_cards.filter(has_text=probe).count() > 0:
                        matched_active = True
                        break
                if not matched_active:
                    return self._finish_page(
                        page, attempt_dir, "FAILED",
                        f"激活卡片内容与目标作品不符 (期望包含: {probes[0]!r})，停止交互",
                        metadata,
                    )

            # ID 已由严格字符白名单限定；精确属性 locator 不会因 DOM 重排改绑其他作品。
            opened = page.locator(
                f'[data-current-object-id="{platform_post_id}"]:visible'
            )
            if opened.count() != 1:
                if active_cards.count() == 1:
                    target_desc = (captured_post_descs or {}).get(platform_post_id)
                    if not target_desc or active_cards.filter(has_text=target_desc).count() != 1:
                        return self._finish_page(page, attempt_dir, "FAILED", "活动卡片缺少完整目标文案，停止提交", metadata)
                    loaded_deadline = time.monotonic() + 5.0
                    while not any(c.get('list_loaded') and c.get('platform_post_id') == platform_post_id for c in (captured_comments or [])):
                        if time.monotonic() >= loaded_deadline:
                            return self._finish_page(page, attempt_dir, "FAILED", "未回读到目标作品的评论列表，停止提交", metadata)
                        page.wait_for_timeout(self.poll_interval_ms)
                    opened = page.locator('.body-wrap, .feeds, body').first
                else:
                    return self._finish_page(
                        page, attempt_dir, "FAILED", "无法验证当前打开详情的原生作品 ID，停止提交", metadata,
                    )

            # 校验右侧详情区域文本前缀（防微前端卡片点击后详情未刷新或漂移）
            if probes and opened.count() > 0 and opened.get_attribute("data-current-object-id") != platform_post_id:
                detail_matches = False
                for probe in probes:
                    if opened.filter(has_text=probe).count() > 0:
                        detail_matches = True
                        break
                if not detail_matches:
                    return self._finish_page(
                        page, attempt_dir, "FAILED",
                        f"详情面板展示内容与目标作品文案不符 (期望包含: {probes[0]!r})，停止交互",
                        metadata,
                    )

            comments = opened.locator('[data-comment-list][data-comments-complete="true"]')
            if comments.count() != 1:
                if active_cards.count() == 1:
                    comments = page.locator('.body-wrap, body').first
                else:
                    return self._finish_page(
                        page, attempt_dir, "FAILED", "评论列表不完整或目标详情结构歧义，停止提交", metadata,
                    )

            is_sandbox_nodes = comments.locator('[data-author-role="author"]').count() > 0
            if is_sandbox_nodes:
                all_author_nodes = comments.locator('[data-author-role="author"]')
                author_nodes = comments.locator('[data-comment-id][data-author-role="author"]')
                if all_author_nodes.count() != author_nodes.count():
                    return self._finish_page(
                        page, attempt_dir, "FAILED", "作者评论节点缺少原生 comment ID，停止提交", metadata,
                    )
                invalid_author_ids = [
                    index
                    for index in range(author_nodes.count())
                    if not str(
                        author_nodes.nth(index).get_attribute("data-comment-id") or ""
                    ).strip()
                ]
                if invalid_author_ids:
                    metadata["invalid_author_comment_id_indexes"] = invalid_author_ids
                    return self._finish_page(
                        page, attempt_dir, "FAILED", "作者评论节点的原生 comment ID 为空，停止提交", metadata,
                    )
                existing = self._read_author_comments(author_nodes)
            else:
                existing = []
                check_deadline = time.monotonic() + (4.0 if verify_only else 2.0)
                while time.monotonic() < check_deadline:
                    existing = _read_live_author_comments(page, captured_comments, platform_post_id)
                    if existing:
                        break
                    page.wait_for_timeout(self.poll_interval_ms)

            metadata["existing_author_comments"] = existing
            if any(item["text"] == expected_text for item in existing):
                if not verify_only:
                    try:
                        metadata["is_pinned"] = self._ensure_comment_pinned(page, comments, expected_text)
                    except Exception as exc:
                        logger.warning("已有首评补齐置顶异常: %s", exc)
                        metadata["is_pinned"] = False
                return self._finish_page(page, attempt_dir, "COMMENTED", None, metadata)
            if existing:
                return self._finish_page(page, attempt_dir, "SKIPPED_EXISTS", None, metadata)
            if verify_only:
                return self._finish_page(
                    page, attempt_dir, "FAILED",
                    "verify-only 未找到目标作者评论；未打开写入或提交界面", metadata,
                )

            # 1. 定位写评论按钮：优先 exact 匹配 button，未找到则回退至微前端 tag-wrap
            write_button = opened.get_by_role("button", name="写评论", exact=True)
            if write_button.count() != 1 or not write_button.is_visible():
                write_button = opened.locator('.tag-wrap.primary').filter(has_text=re.compile(r"^\s*写评论\s*$"))
            if write_button.count() != 1 or not write_button.is_visible():
                write_button = page.locator('.tag-wrap.primary').filter(has_text=re.compile(r"^\s*写评论\s*$"))
            if write_button.count() != 1 or not write_button.is_visible():
                return self._finish_page(page, attempt_dir, "FAILED", "未唯一定位写评论按钮", metadata)
            write_button.first.click()

            # 2. 定位评论输入框
            editor = opened.locator("textarea[data-comment-editor]")
            if editor.count() != 1 or not editor.is_visible():
                editor = opened.locator("textarea.create-input, textarea[placeholder='发表评论']")
            if editor.count() != 1 or not editor.is_visible():
                editor = page.locator("textarea.create-input, textarea[placeholder='发表评论']")
            if editor.count() != 1 or not editor.is_visible():
                return self._finish_page(page, attempt_dir, "FAILED", "未唯一定位评论输入框", metadata)
            editor = editor.first
            editor.fill(comment_text)

            # 真实平台安全检测：若弹出未绑定手机号弹窗，立即 fail-closed
            phone_dialog = page.locator(
                '.phone-check-dialog:visible, .weui-desktop-dialog:has-text("绑定手机号"):visible'
            )
            if phone_dialog.count() > 0:
                return self._finish_page(
                    page, attempt_dir, "FAILED", "微信安全策略要求账号先绑定手机号后方可发表评论", metadata
                )

            # 3. 定位评论提交按钮：优先 exact 匹配 button，未找到则回退至微前端提交按钮
            submit_button = opened.get_by_role("button", name="评论", exact=True)
            if submit_button.count() != 1 or not submit_button.is_visible():
                submit_button = opened.locator('.create-ft .tag-wrap.primary').filter(has_text=re.compile(r"^\s*评论\s*$"))
            if submit_button.count() != 1 or not submit_button.is_visible():
                submit_button = page.locator('.create-ft .tag-wrap.primary').filter(has_text=re.compile(r"^\s*评论\s*$"))
            if submit_button.count() != 1 or not submit_button.is_visible():
                return self._finish_page(page, attempt_dir, "FAILED", "未唯一定位评论提交按钮", metadata)
            submit_button = submit_button.first
            is_disabled = (
                submit_button.is_disabled()
                or "disabled" in (submit_button.get_attribute("class") or "")
            )
            if is_disabled:
                return self._finish_page(page, attempt_dir, "FAILED", "评论提交按钮不可用", metadata)

            # 详情可能在填写期间被 SPA 重绘；callback 前再次校验，避免把意图绑定到错误作品。
            has_valid_opened = (
                opened.count() == 1
                and opened.get_attribute("data-current-object-id") == platform_post_id
            )
            if not has_valid_opened:
                target_desc = (captured_post_descs or {}).get(platform_post_id)
                if active_cards.count() != 1 or not target_desc or active_cards.filter(has_text=target_desc).count() != 1:
                    return self._finish_page(
                        page, attempt_dir, "FAILED", "提交前作品详情已变化，未持久化提交意图", metadata,
                    )

            if editor.count() != 1 or _normalized_text(editor.input_value()) != expected_text:
                return self._finish_page(
                    page, attempt_dir, "FAILED", "提交前评论输入内容已变化，未持久化提交意图", metadata,
                )
            if before_submit is None or before_submit() is not True:
                return self._finish_page(
                    page, attempt_dir, "FAILED", "before_submit 未持久化提交意图，已在点击前停止", metadata,
                )

            response_window = _SubmissionResponseWindow(
                page.url, platform_post_id, expected_text
            )

            # 请求和响应监听都只在 callback 成功后安装；响应必须属于窗口内捕获的同一 Request。
            page.on("request", response_window.capture_request)
            page.on("response", response_window.capture_response)
            page.route("**/*", response_window.guard_request)
            clicked = True
            submit_button.click()

            deadline = time.monotonic() + self.response_timeout_ms / 1000
            while not response_window.responses and not response_window.mismatched_requests and not response_window.blocked_requests and time.monotonic() < deadline:
                page.wait_for_timeout(self.poll_interval_ms)

            if response_window.blocked_requests:
                metadata["blocked_requests"] = response_window.blocked_requests
                metadata["mismatched_requests"] = response_window.mismatched_requests
                return self._finish_page(page, attempt_dir, "FAILED", "评论请求 ID、来源或全文不符，已在网络发送前阻断", metadata)
            if response_window.mismatched_requests:
                metadata["mismatched_requests"] = response_window.mismatched_requests
                return self._finish_page(
                    page, attempt_dir, "FAILED",
                    f"检测到发往非目标作品的提交请求 ({response_window.mismatched_requests[0]['payload_id']} != {platform_post_id})，硬阻断为 FAILED",
                    metadata,
                )

            correlated_responses = response_window.responses
            metadata["correlated_responses"] = correlated_responses
            if not correlated_responses:
                return self._finish_page(
                    page, attempt_dir, "UNCERTAIN", "已点击提交但未收到严格关联响应", metadata,
                )
            if len(correlated_responses) != 1:
                return self._finish_page(page, attempt_dir, "UNCERTAIN", "提交响应数量歧义", metadata)

            response_payload = correlated_responses[0]["response"]
            error_code = _payload_value(response_payload, "errCode", "err_code")
            if isinstance(error_code, bool) or not isinstance(error_code, (int, float)):
                return self._finish_page(
                    page, attempt_dir, "UNCERTAIN", "关联响应缺少明确数字 errCode", metadata,
                )
            if error_code != 0:
                return self._finish_page(page, attempt_dir, "FAILED", "平台明确拒绝评论提交", metadata)
            request_payload = correlated_responses[0].get("request")
            response_post_id = str(
                _payload_value(response_payload, "objectId", "object_id", "exportId", "export_id")
                or _payload_value(request_payload, "objectId", "object_id", "exportId", "export_id")
                or ""
            )
            comment_id = str(
                _payload_value(response_payload, "commentId", "comment_id") or ""
            ).strip()
            if response_post_id != platform_post_id or not comment_id:
                return self._finish_page(
                    page, attempt_dir, "UNCERTAIN", "受理响应缺少精确作品 ID 或评论 ID", metadata,
                )

            deadline = time.monotonic() + self.dom_timeout_ms / 1000
            matching: list[dict[str, str]] = []
            has_explicit_sandbox_ids = comments.locator('[data-comment-id]').count() > 0
            while time.monotonic() < deadline:
                author_nodes = comments.locator('[data-comment-id][data-author-role="author"]')
                matching = [
                    row for row in self._read_author_comments(author_nodes)
                    if row["comment_id"] == comment_id
                ]
                if len(matching) == 1 and matching[0]["text"] == expected_text:
                    break
                if not has_explicit_sandbox_ids and not matching:
                    matching = [row for row in _read_live_author_comments(page, captured_comments, platform_post_id)
                                if row['comment_id'] == comment_id]
                    if len(matching) == 1 and matching[0]['text'] == expected_text:
                        break
                page.wait_for_timeout(self.poll_interval_ms)
            metadata["accepted_comment_id"] = comment_id
            metadata["matching_author_nodes"] = matching
            if len(matching) != 1 or matching[0]["text"] != expected_text:
                return self._finish_page(
                    page, attempt_dir, "UNCERTAIN",
                    "平台已受理但未回读到同 ID、同作者、完整同文评论节点", metadata,
                )
            if not verify_only:
                try:
                    metadata["is_pinned"] = self._ensure_comment_pinned(page, comments, expected_text)
                except Exception as exc:
                    logger.warning("新发首评置顶异常（不影响发评成功）: %s", exc)
                    metadata["is_pinned"] = False
            return self._finish_page(page, attempt_dir, "COMMENTED", None, metadata)
        except Exception as exc:
            status = "UNCERTAIN" if clicked else "FAILED"
            return self._finish_page(
                page, attempt_dir, status,
                f"浏览器适配器异常: {type(exc).__name__}: {exc}", metadata,
            )

    def _ensure_comment_pinned(self, page, comments_locator, expected_text: str) -> bool:
        """仅操作完整同文的作者评论；不使用全页第一个更多按钮。"""
        try:
            target = comments_locator.locator('[data-author-role="author"]').filter(has_text=expected_text)
            if target.count() != 1:
                target = page.locator('.comment-item-main:has(.comment-author-bandage)').filter(has_text=expected_text)
            if target.count() != 1:
                return False
            tags = target.locator('.comment-tags:has-text("置顶"), .tag:has-text("置顶"), [data-pinned="true"]')
            if target.get_attribute("data-pinned") == "true" or (tags.count() and tags.first.is_visible()):
                return True
            target.hover()
            more = target.locator('.action-icon.weui-icon-outlined-more, .action-item:has(.weui-icon-outlined-more), [data-action="more"], [data-action="pin"]')
            if more.count() != 1 or not more.is_visible():
                return False
            more.click()
            page.wait_for_timeout(200)
            if more.get_attribute('data-action') != 'pin':
                pin = page.locator('.weui-desktop-popover:visible .menu-item, [role="menu"]:visible [role="menuitem"], [data-menu-item="pin"]:visible').filter(has_text=re.compile(r"^\s*置顶\s*$"))
                if pin.count() != 1:
                    return False
                pin.click()
                page.wait_for_timeout(300)
                dialog = page.locator('.common-dialog:visible, .weui-desktop-dialog:visible').filter(has_text='置顶')
                if dialog.count():
                    confirm = dialog.get_by_role('button', name='替换置顶', exact=True)
                    if confirm.count() != 1:
                        return False
                    confirm.click()
            deadline = time.monotonic() + min(3.0, self.dom_timeout_ms / 1000)
            while time.monotonic() < deadline:
                if target.get_attribute("data-pinned") == "true" or (tags.count() and tags.first.is_visible()):
                    return True
                page.wait_for_timeout(self.poll_interval_ms)
            return False
        except Exception as exc:
            logger.warning("目标作者评论置顶未确认: %s", exc)
            return False

    @staticmethod
    def _read_author_comments(locator) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for index in range(locator.count()):
            node = locator.nth(index)
            if not node.is_visible():
                continue
            comment_id = str(node.get_attribute("data-comment-id") or "").strip()
            if comment_id:
                rows.append({"comment_id": comment_id, "text": _normalized_text(node.inner_text())})
        return rows

    def _finish_page(
        self,
        page,
        attempt_dir: Path,
        status: str,
        error: Optional[str],
        details: dict[str, Any],
    ) -> BrowserResult:
        screenshot = attempt_dir / "final.png"
        try:
            page.screenshot(path=str(screenshot), full_page=True)
            evidence = str(screenshot)
        except Exception as exc:
            details["screenshot_error"] = f"{type(exc).__name__}: {exc}"
            evidence = None
        return self._finish(attempt_dir, status, error, details=details, evidence=evidence)

    @staticmethod
    def _finish(
        attempt_dir: Path,
        status: str,
        error: Optional[str],
        *,
        details: dict[str, Any],
        evidence: Optional[str] = None,
    ) -> BrowserResult:
        receipt = attempt_dir / "receipt.json"
        payload = {
            **details,
            "status": status,
            "error": error,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        with receipt.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, default=str)
        return status, evidence or str(receipt), error
