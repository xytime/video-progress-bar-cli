"""视频号作者评论的 fail-closed Playwright 适配器。

本模块只接受平台原生作品 ID，不使用标题、接口顺序或卡片索引回退。
当前 DOM/API 选择器是待真实平台只读校准的适配器合同；任何未知 schema
都会停止在提交前。一次点击后若结果不能完整确认，则返回 ``UNCERTAIN``，
调用方不得把它当作普通失败自动重试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
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
# 尚待真实平台只读校准。仅此精确路径可被视为“创建作者评论”的响应。
COMMENT_SUBMIT_PATH = "/cgi-bin/mmfinderassistant-bin/comment/create"
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


class _SubmissionResponseWindow:
    """只关联监听窗口内发出的精确提交 Request 及其 Response。"""

    def __init__(self, page_url: str, platform_post_id: str, expected_text: str) -> None:
        parsed = urlparse(page_url)
        self.origin = (parsed.scheme, parsed.netloc)
        self.platform_post_id = platform_post_id
        self.expected_text = expected_text
        self.requests: list[Any] = []
        self.responses: list[dict[str, Any]] = []

    def capture_request(self, request) -> None:
        parsed = urlparse(request.url)
        if (
            request.method != "POST"
            or (parsed.scheme, parsed.netloc) != self.origin
            or parsed.path != COMMENT_SUBMIT_PATH
        ):
            return
        try:
            payload = request.post_data_json
        except Exception:
            return
        if str(_payload_value(payload, "objectId", "object_id") or "") != self.platform_post_id:
            return
        text = _normalized_text(_payload_value(payload, "content", "comment", "commentText"))
        if text == self.expected_text:
            self.requests.append(request)

    def capture_response(self, response) -> None:
        request = response.request
        parsed = urlparse(response.url)
        if (
            (parsed.scheme, parsed.netloc) != self.origin
            or parsed.path != COMMENT_SUBMIT_PATH
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
    ) -> BrowserResult:
        """创建浏览器；不关闭 Web 安全、不禁用 Chromium sandbox。"""
        with sync_playwright() as runtime:
            launch_options: dict[str, Any] = {
                "headless": self.headless,
                "args": ["--window-size=1280,800", "--no-proxy-server"],
            }
            if self.browser_executable_path:
                launch_options["executable_path"] = self.browser_executable_path
            browser = runtime.chromium.launch(**launch_options)
            try:
                context = browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    storage_state=str(self.state_path),
                )
                page = context.new_page()
                page.goto(self.comment_url, wait_until="domcontentloaded")
                return self._interact_with_page(
                    page,
                    comment_text=comment_text,
                    platform_post_id=platform_post_id,
                    video_title=video_title,
                    attempt_dir=attempt_dir,
                    before_submit=before_submit,
                    verify_only=verify_only,
                )
            finally:
                browser.close()

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
    ) -> BrowserResult:
        """在已打开的真实页面上执行适配器合同，供隔离 Chromium 验收复用。"""
        clicked = False
        expected_text = _normalized_text(comment_text)
        metadata: dict[str, Any] = {
            "platform_post_id": platform_post_id,
            "video_title_hint": video_title,
            "verify_only": verify_only,
            "comment_text_normalized": expected_text,
            "adapter_contract": "wechat-comment-v2-pending-live-schema-validation",
        }
        if not _PLATFORM_POST_ID_RE.fullmatch(platform_post_id):
            return self._finish_page(
                page, attempt_dir, "FAILED",
                "platform_post_id 包含未校准字符，拒绝构造 DOM 选择器", metadata,
            )
        try:
            if "login" in page.url:
                return self._finish_page(page, attempt_dir, "FAILED", "微信登录态已失效", metadata)

            cards = page.locator(
                f'[data-object-id="{platform_post_id}"]:visible, '
                f'[data-post-id="{platform_post_id}"]:visible, '
                f'[data-id="{platform_post_id}"]:visible'
            )
            visible_count = cards.count()
            if visible_count != 1:
                return self._finish_page(
                    page, attempt_dir, "FAILED",
                    f"原生 ID 目标卡片必须唯一，实际可见数量={visible_count}", metadata,
                )
            cards.click()
            page.wait_for_timeout(self.poll_interval_ms)

            # ID 已由严格字符白名单限定；精确属性 locator 不会因 DOM 重排改绑其他作品。
            opened = page.locator(
                f'[data-current-object-id="{platform_post_id}"]:visible'
            )
            if opened.count() != 1:
                return self._finish_page(
                    page, attempt_dir, "FAILED", "无法验证当前打开详情的原生作品 ID，停止提交", metadata,
                )

            comments = opened.locator('[data-comment-list][data-comments-complete="true"]')
            if comments.count() != 1:
                return self._finish_page(
                    page, attempt_dir, "FAILED", "评论列表不完整或目标详情结构歧义，停止提交", metadata,
                )
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
            metadata["existing_author_comments"] = existing
            if any(item["text"] == expected_text for item in existing):
                return self._finish_page(page, attempt_dir, "COMMENTED", None, metadata)
            if existing:
                return self._finish_page(page, attempt_dir, "SKIPPED_EXISTS", None, metadata)
            if verify_only:
                return self._finish_page(
                    page, attempt_dir, "FAILED",
                    "verify-only 未找到目标作者评论；未打开写入或提交界面", metadata,
                )

            write_button = opened.get_by_role("button", name="写评论", exact=True)
            if write_button.count() != 1 or not write_button.is_visible():
                return self._finish_page(page, attempt_dir, "FAILED", "未唯一定位写评论按钮", metadata)
            write_button.click()
            editor = opened.locator("textarea[data-comment-editor]")
            if editor.count() != 1 or not editor.is_visible():
                return self._finish_page(page, attempt_dir, "FAILED", "未唯一定位评论输入框", metadata)
            editor.fill(comment_text)

            submit_button = opened.get_by_role("button", name="评论", exact=True)
            if submit_button.count() != 1 or not submit_button.is_visible() or submit_button.is_disabled():
                return self._finish_page(page, attempt_dir, "FAILED", "评论提交按钮不可用", metadata)
            # 详情可能在填写期间被 SPA 重绘；callback 前再次校验，避免把意图绑定到错误作品。
            if opened.count() != 1 or opened.get_attribute("data-current-object-id") != platform_post_id:
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
            clicked = True
            submit_button.click()

            deadline = time.monotonic() + self.response_timeout_ms / 1000
            while not response_window.responses and time.monotonic() < deadline:
                page.wait_for_timeout(self.poll_interval_ms)
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
            response_post_id = str(_payload_value(response_payload, "objectId", "object_id") or "")
            comment_id = str(
                _payload_value(response_payload, "commentId", "comment_id") or ""
            ).strip()
            if response_post_id != platform_post_id or not comment_id:
                return self._finish_page(
                    page, attempt_dir, "UNCERTAIN", "受理响应缺少精确作品 ID 或评论 ID", metadata,
                )

            deadline = time.monotonic() + self.dom_timeout_ms / 1000
            matching: list[dict[str, str]] = []
            while time.monotonic() < deadline:
                author_nodes = comments.locator('[data-comment-id][data-author-role="author"]')
                matching = [
                    row for row in self._read_author_comments(author_nodes)
                    if row["comment_id"] == comment_id
                ]
                if len(matching) == 1 and matching[0]["text"] == expected_text:
                    break
                page.wait_for_timeout(self.poll_interval_ms)
            metadata["accepted_comment_id"] = comment_id
            metadata["matching_author_nodes"] = matching
            if len(matching) != 1 or matching[0]["text"] != expected_text:
                return self._finish_page(
                    page, attempt_dir, "UNCERTAIN",
                    "平台已受理但未回读到同 ID、同作者、完整同文评论节点", metadata,
                )
            return self._finish_page(page, attempt_dir, "COMMENTED", None, metadata)
        except Exception as exc:
            status = "UNCERTAIN" if clicked else "FAILED"
            return self._finish_page(
                page, attempt_dir, status,
                f"浏览器适配器异常: {type(exc).__name__}: {exc}", metadata,
            )

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
