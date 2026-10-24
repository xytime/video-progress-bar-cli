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
| operations-v1 | 2026-10-24 | Codex | 分用途滚动预算与安全有界重试接入，保留既有提交事实与内容保护。 |
| scan-timer-v1 | 2026-10-25 | Codex | 具名扫描仅遇5秒内已知时间门禁时先做一次本地等待，再走完整原生准入，避免cron秒级抖动多等半小时。 |
| scan-binding-diagnostic | 2026-10-25 | Codex | 绑定失败只记录脱敏结构计数，保留严格绑定和原访问次数，不记录正文/原生ID/会话信息。 |
| root-reply-scope-v1 | 2026-10-23 | Codex | 回复触发器限定父评论直属主体，排除已展开的观众子回复控件；仍拒绝主体内歧义。 |
| interaction-recovery-v1 | 2026-10-23 | Codex | 绑定单作品的人工一次性恢复许可，平台限流继续阻断。 |
| 1.6.3 | 2026-10-23 | Codex | 恢复具名作品只读会话；单条回复闭环共享账户许可，独立上下文保持写入守卫与请求预算。 |
| scheduler-v1 | 2026-10-21 | Codex | 真实浏览器访问纳入账户统一准入；无绑定任务不扫描。 |
| 1.6.2 | 2026-10-18 | Antigravity | 修复含微信方括号表情（如 [捂脸]）的一级评论在 DOM 中转渲染为 img 导致文本唯一探针未命中的问题 |
| 1.6.1 | 2026-10-17 | Antigravity | 修复 post/post_list HTTP 201 响应捕获，支持通过 >=30 字符唯一已发布文案跨场景绑定 exportId 并在滚动分页时动态重算探针 |
| 1.6.0 | 2026-10-17 | Antigravity | 新增只读 discover_comments_on_page 接口与 comment_list 原始载荷捕获，供 M3.5 Tick 扫描复用 |
| 1.5.0 | 2026-10-17 | Antigravity | 统一校准与发送的卡片绑定、父评论与回复控件唯一定位逻辑；从契约层导入 SecondaryReplySubmissionGuard；公开 create_evidence_dir 与 execute_page_reply_flow；收紧 calibrate_page_controls 身份与文本证据要求 |
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
    current_wechat_session,
)
from video_processing.db.database import PipelineDB
from video_processing.interaction.secondary_reply_contract import (
    COMMENT_SUBMIT_PATHS,
    SecondaryReplySubmissionGuard,
)

logger = logging.getLogger(__name__)


def _near_scan_release_delay(info, now):
    """技术定时容差，不是额度或授权；完整准入仍在等待后执行。"""
    blockers = info.get('blockers') or []
    if info.get('allowed') or not blockers:
        return 0.0
    if any(b.get('code') not in {'OPERATION_ROLLING_1H_LIMIT', 'OPERATION_INTERVAL'} for b in blockers):
        return 0.0
    until = info.get('until')
    if type(until) not in (int, float):
        return 0.0
    delay = until - now
    return delay if 0 < delay <= 5 else 0.0


WECHAT_COMMENT_URL = "https://channels.weixin.qq.com/platform/interaction/comment"
COMMENT_POST_LIST_PATH = "/micro/interaction/cgi-bin/mmfinderassistant-bin/post/post_list"
COMMENT_LIST_PATH = "/micro/interaction/cgi-bin/mmfinderassistant-bin/comment/comment_list"

REPLY_TRIGGER_SELECTORS: Tuple[str, ...] = (
    ".action-icon.weui-icon-outlined-comment",
    ".action-item:has(.weui-icon-outlined-comment)",
    "[data-reply]",
    "button[aria-label='回复'], [role='button'][aria-label='回复']",
    "button:text-is('回复'), [role='button']:text-is('回复')",
    ".weui-desktop-icon[aria-label='回复'], [title='回复']",
    "button:has-text('回复'), [role='button']:has-text('回复')",
    "[data-action='reply']",
    ".comment-item__action:has-text('回复')",
)

EDITOR_INPUT_SELECTORS: Tuple[str, ...] = (
    ".edit-area[contenteditable='true']",
    ".comment-reply-wrap .edit-area",
    "textarea[placeholder*='回复'], textarea[data-comment-editor], textarea.weui-desktop-form__textarea",
    "textarea.create-input, textarea[placeholder*='说点什么']",
    "textarea",
)

SUBMIT_BUTTON_SELECTORS: Tuple[str, ...] = (
    ".comment-reply-wrap button.weui-desktop-btn_primary:text-is('评论')",
    ".reply-opt button:text-is('评论')",
    "button:text-is('评论'), button:text-is('发送'), button[data-submit]",
    ".create-ft .tag-wrap.primary, .weui-desktop-btn_primary:text-is('评论')",
    "button[type='submit']",
    "[data-action='submit']",
)

EXPAND_REPLIES_SELECTORS: Tuple[str, ...] = (
    ".comment-reply-list button:has-text('展开'), .comment-reply-list [data-action='expand-replies'], .comment-reply-list .show-more-replies, .comment-reply-list :text-matches('展开|查看.*回复')",
    "button:has-text('展开'), [role='button']:has-text('展开')",
    "[data-action='expand-replies'], [data-expand-replies]",
    ".show-more-replies, .show-more:has-text('展开')",
    "span:has-text('展开'), a:has-text('展开')",
)


def _resolve_default_state_file() -> Path:
    return Path(__file__).resolve().parents[3] / "output" / "wechat_state.json"


DEFAULT_STATE_FILE = _resolve_default_state_file()

SecondaryBrowserResult = Tuple[str, Optional[str], Optional[str]]
_PLATFORM_POST_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/=-]{0,255}\Z")


def _normalized_text(value: object) -> str:
    """按浏览器可见文本语义规范化空白。"""
    return re.sub(r"\s+", " ", str(value or "")).strip()


class SecondaryReplyBrowserAdapter:
    """二级回复浏览器自动化执行器。"""

    def __init__(
        self,
        *,
        state_path: Path | str = DEFAULT_STATE_FILE,
        headless: bool = True,
        comment_url: str = WECHAT_COMMENT_URL,
        lock_timeout_seconds: float = 10.0,
        manual_retry_post_id: str = "",
    ) -> None:
        self.state_path = Path(state_path)
        self.headless = headless
        self.comment_url = comment_url
        self.lock_timeout_seconds = max(0.1, float(lock_timeout_seconds))
        self._captured_comments: Dict[str, Dict[str, Any]] = {}
        self._active_export_id: Optional[str] = None
        self._post_descriptions: Dict[str, str] = {}
        self._last_comment_list_payload: Optional[Dict[str, Any]] = None
        self._bound_scene_post_id: Optional[str] = None
        self._active_guard: Optional[SecondaryReplySubmissionGuard] = None
        self._manual_retry_post_id = manual_retry_post_id
        self._manual_retry_consumed = False

    @contextlib.contextmanager
    def _session_scope(self, post_id: str, purpose: str = "回复"):
        """显式人工恢复最多签发一个绑定作品的许可，平台限流仍停止。"""
        from video_processing.core.wechat_request_guard import WeChatRequestGuard
        token = ''
        request_guard = WeChatRequestGuard(self.state_path)
        if self._manual_retry_post_id and not self._manual_retry_consumed:
            if post_id != self._manual_retry_post_id:
                raise WeChatSessionLockBusy('人工补发许可与作品不匹配')
            cooldown = request_guard.cooldown()
            if cooldown['active'] and cooldown['reason'] == '视频号返回限流':
                raise WeChatSessionLockBusy('平台限流仍有效，人工补发不覆盖平台限制')
            token = request_guard.issue_override(post_id, cooldown['version'])
            self._manual_retry_consumed = True
        try:
            with WeChatSessionLock(self.state_path, timeout_seconds=self.lock_timeout_seconds,
                                   purpose=purpose, video=post_id, cooldown_override=token) as session:
                yield session
        finally:
            if token:
                request_guard.revoke_override(token)

    def _setup_page_listeners(self, page, guard: Optional[SecondaryReplySubmissionGuard] = None) -> None:
        """注册页面网络监听：捕获 comment_list 响应数据、折叠/分页标志与活跃作品 ID。"""
        self._captured_comments.clear()
        self._post_descriptions.clear()
        self._active_export_id = None
        self._last_comment_list_payload = None
        self._bound_scene_post_id = None
        self._active_guard = guard
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
            if urlparse(res.url).path == COMMENT_POST_LIST_PATH and res.status in (200, 201):
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
                    if isinstance(payload, dict):
                        self._last_comment_list_payload = payload
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

    def create_evidence_dir(self, parent: Optional[Path | str] = None) -> Path:
        base = Path(parent) if parent else (Path(__file__).resolve().parents[3] / "output" / "secondary_reply_evidence")
        attempt_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]
        out_dir = base / attempt_id
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir

    _new_evidence_dir = create_evidence_dir

    def _resolve_scene_post_id(
        self,
        platform_post_id: str,
        published_description: Optional[str] = None,
    ) -> Optional[str]:
        """解析评论管理页当前场景的原生 exportId；若跨场景则仅允许 >=30 字符的唯一完整已发布文案绑定。"""
        if platform_post_id in self._post_descriptions:
            return platform_post_id
        expected = _normalized_text(published_description)
        if expected and len(expected) >= 30:
            matches = [
                pid
                for pid, desc in self._post_descriptions.items()
                if _normalized_text(desc) == expected
            ]
            if len(matches) == 1:
                return matches[0]
        return None

    def _select_and_bind_post_card(
        self,
        page: Any,
        *,
        platform_post_id: str,
        video_title: Optional[str] = None,
        published_description: Optional[str] = None,
        wait_ms: int = 1500,
    ) -> Tuple[bool, Optional[str]]:
        """唯一定位作品卡片、点击并校验详情面板已绑定到目标原生 exportId。"""
        card = self._resolve_video_card(page, platform_post_id, video_title, published_description)
        if card is None:
            self._log_card_binding_diagnostic(page, platform_post_id, video_title, published_description)
            return False, f"未找到作品卡片 (exportId: {platform_post_id})"
        scene_post_id = self._resolve_scene_post_id(platform_post_id, published_description) or platform_post_id
        self._bound_scene_post_id = scene_post_id
        self._captured_comments.clear()
        self._active_export_id = None
        self._last_comment_list_payload = None
        card.click()
        page.wait_for_timeout(wait_ms)

        valid_post_ids = {platform_post_id, scene_post_id} - {""}
        bound = page.locator("[data-current-object-id]")
        bound_ok = False
        if bound.count() >= 1 and all(
            (bound.nth(i).get_attribute("data-current-object-id") or "") in valid_post_ids
            for i in range(bound.count())
        ):
            bound_ok = True
        elif self._active_export_id and self._active_export_id in valid_post_ids:
            bound_ok = True

        if not bound_ok:
            return False, f"无法证明已打开的详情属于目标作品 (exportId: {platform_post_id})，拒绝继续"
        if (
            self._active_guard is not None
            and self._active_export_id == scene_post_id
            and self._active_guard.expected_export_id == platform_post_id
            and scene_post_id != platform_post_id
        ):
            self._active_guard.expected_export_id = scene_post_id
        from ..core.wechat_page_contract import is_official_wechat_origin, check_explicit_login_prompt
        if is_official_wechat_origin(page.url):
            is_login, dom_error = check_explicit_login_prompt(page)
            if not is_login and not dom_error:
                from ..core.wechat_session_lock import record_current_wechat_verified
                record_current_wechat_verified("comment_controls")
        return True, None

    def _log_card_binding_diagnostic(self, page, post_id, title, description):
        """仅检查已加载DOM，不发请求；诊断失败不能覆盖原有闭锁结果。"""
        import hashlib
        try:
            scene = self._resolve_scene_post_id(post_id, description)
            hint = _normalized_text(self._post_descriptions.get(scene or post_id) or description or title or '')[:20]
            data = {
                'event': 'CARD_BINDING_DIAGNOSTIC',
                'target_sha256': hashlib.sha256(post_id.encode()).hexdigest(),
                'captured_post_count': len(self._post_descriptions),
                'expected_id_captured': post_id in self._post_descriptions,
                'scene_mapping_available': bool(scene),
                'exact_visible_candidates': page.locator(f"[data-object-id='{post_id}']").filter(visible=True).count(),
                'visible_cards': page.locator('.comment-feed-wrap:visible, .post-card:visible').count(),
                'hint_visible_candidates': page.locator('.comment-feed-wrap:visible, .post-card:visible').filter(has_text=hint).count() if hint else 0,
            }
            logger.warning('[SecondaryReplyBrowser] %s', json.dumps(data, sort_keys=True))
        except Exception as exc:
            logger.warning('[SecondaryReplyBrowser] CARD_BINDING_DIAGNOSTIC_UNAVAILABLE %s', type(exc).__name__)

    def _locate_unique_visible_control(
        self,
        scope: Any,
        candidates: Tuple[str, ...],
        *,
        control_label: str,
        fallback_scope: Optional[Any] = None,
        fallback_candidates: Tuple[str, ...] = (),
    ) -> Tuple[Optional[str], Optional[Any], Optional[str]]:
        """在指定作用域按优先级查找唯一可见控件；任何候选出现 count > 1 立即触发歧义阻断，绝不回退首个节点。"""
        for cand in candidates:
            loc = scope.locator(cand).filter(visible=True)
            cnt = loc.count()
            if cnt == 1:
                return cand, loc.first, None
            if cnt > 1:
                return (
                    None,
                    None,
                    f"{control_label}匹配到多个可见控件 ({cnt}) [选择器: '{cand}']，触发歧义阻断",
                )
        if fallback_scope is not None:
            for cand in fallback_candidates:
                loc = fallback_scope.locator(cand).filter(visible=True)
                cnt = loc.count()
                if cnt == 1:
                    return cand, loc.first, None
                if cnt > 1:
                    return (
                        None,
                        None,
                        f"{control_label}在全局弹层匹配到多个可见控件 ({cnt}) [选择器: '{cand}']，触发歧义阻断",
                    )
        return None, None, None

    def _locate_expand_control(
        self, parent_item: Any
    ) -> Tuple[Optional[str], int, Optional[str], Optional[Any]]:
        """在父评论作用域内定位二级回复展开按钮；若 count > 1 则返回数量供调用方按歧义拒绝。"""
        for cand in EXPAND_REPLIES_SELECTORS:
            loc = parent_item.locator(cand).filter(visible=True)
            cnt = loc.count()
            if cnt == 1:
                text = None
                try:
                    text = loc.first.inner_text().strip()
                except Exception:
                    pass
                return cand, 1, text, loc.first
            if cnt > 1:
                return cand, cnt, None, None
        return None, 0, None, None

    def _open_and_bind_reply_controls(
        self,
        page: Any,
        parent_item: Any,
        *,
        root_comment_id: str = "",
        close_on_error: bool = True,
    ) -> Dict[str, Any]:
        """校准与发送共享的控件唯一定位与展开绑定流程（不输入正文、不点击提交）。"""
        if parent_item is None or parent_item.count() != 1:
            return {
                "ok": False,
                "error": f"一级评论节点不唯一或未找到 (commentId: {root_comment_id})",
            }

        # 已展开的观众子回复也有同款图标；只在根评论直属主体中定位触发器。
        root_main = parent_item.locator(":scope > .comment-item-main").filter(visible=True)
        if root_main.count() > 1:
            return {"ok": False, "error": "父评论直属主体不唯一，触发歧义阻断"}
        reply_scope = parent_item
        if root_main.count() == 1:
            reply_scope = root_main.locator(":scope > .comment-main-content > .comment-row > .comment-actions").filter(visible=True)
            if reply_scope.count() != 1:
                return {"ok": False, "error": "父评论直属操作区不唯一或缺失，触发歧义阻断"}
        reply_selector, reply_btn_loc, reply_err = self._locate_unique_visible_control(
            reply_scope,
            REPLY_TRIGGER_SELECTORS,
            control_label="父评论内回复按钮",
        )
        if reply_err:
            return {"ok": False, "error": reply_err}
        if not reply_selector or reply_btn_loc is None:
            return {
                "ok": False,
                "error": "未能唯一定位可用的二级回复触发按钮；禁止按图标顺序或通用 button 猜测",
            }

        reply_enabled = reply_btn_loc.is_enabled()
        if not reply_enabled:
            return {"ok": False, "error": f"回复按钮处于禁用状态: {reply_selector}"}

        expand_selector, expand_count, expand_text, _expand_loc = self._locate_expand_control(parent_item)
        if expand_count > 1:
            return {
                "ok": False,
                "error": f"父评论内展开回复按钮选择器 '{expand_selector}' 匹配到多个可见控件 ({expand_count})，触发歧义阻断",
            }

        editor_already_open = parent_item.locator(".edit-area:visible, textarea:visible").count() > 0
        if not editor_already_open:
            reply_btn_loc.click()
            page.wait_for_timeout(500)

        textarea_selector, textarea_loc, textarea_err = self._locate_unique_visible_control(
            parent_item,
            EDITOR_INPUT_SELECTORS,
            control_label="父评论内输入框",
            fallback_scope=page,
            fallback_candidates=EDITOR_INPUT_SELECTORS[:3],
        )
        if textarea_err:
            if close_on_error:
                self._safe_close_editor(page, parent_item, editor_already_open)
            return {"ok": False, "error": textarea_err}
        if not textarea_selector or textarea_loc is None:
            if close_on_error:
                self._safe_close_editor(page, parent_item, editor_already_open)
            return {"ok": False, "error": "未能定位到二级回复输入框"}

        submit_selector, submit_loc, submit_err = self._locate_unique_visible_control(
            parent_item,
            SUBMIT_BUTTON_SELECTORS,
            control_label="父评论内提交按钮",
            fallback_scope=page,
            fallback_candidates=SUBMIT_BUTTON_SELECTORS[:2],
        )
        if submit_err:
            if close_on_error:
                self._safe_close_editor(page, parent_item, editor_already_open, textarea_loc)
            return {"ok": False, "error": submit_err}
        if not submit_selector or submit_loc is None:
            if close_on_error:
                self._safe_close_editor(page, parent_item, editor_already_open, textarea_loc)
            return {"ok": False, "error": "未能定位到二级回复提交按钮"}

        return {
            "ok": True,
            "error": None,
            "reply_selector": reply_selector,
            "reply_btn": reply_btn_loc,
            "reply_enabled": reply_enabled,
            "textarea_selector": textarea_selector,
            "textarea": textarea_loc,
            "submit_selector": submit_selector,
            "submit_btn": submit_loc,
            "expand_selector": expand_selector,
            "expand_count": expand_count,
            "expand_text": expand_text,
            "editor_already_open": editor_already_open,
        }

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

        attempt_dir = self.create_evidence_dir(evidence_dir)
        guard = SecondaryReplySubmissionGuard(
            post_id, root_id, content,
            expected_finder_id=expected_finder_id, trusted_origins=trusted_origins,
        )

        try:
            with WeChatSessionLock(self.state_path, timeout_seconds=self.lock_timeout_seconds,
                                   purpose="回复", video=post_id):
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

            def route_interceptor(route):
                req = route.request
                is_safe = guard.capture_request(req)
                if not is_safe:
                    logger.critical("[SecondaryReplyBrowser] 拦截到违规或错帖请求，中止请求！")
                    route.abort()
                    return
                route.fallback()

            page.route("**/comment/create_comment*", route_interceptor)

            try:
                page.goto(self.comment_url, timeout=45000, wait_until="domcontentloaded")
                try:
                    page.wait_for_selector(".comment-feed-wrap, [data-object-id]", timeout=15000)
                except Exception:
                    page.wait_for_timeout(2000)

                return self.execute_page_reply_flow(
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

    def execute_page_reply_flow(
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
        is_login, _ = check_explicit_login_prompt(page)
        if is_login:
            from ..core.wechat_session_lock import record_current_wechat_login_required
            record_current_wechat_login_required()
            return "FAILED", None, "LOGIN_REQUIRED"

        bound_ok, bind_err = self._select_and_bind_post_card(
            page,
            platform_post_id=platform_post_id,
            video_title=video_title,
            published_description=published_description,
            wait_ms=2000,
        )
        if not bound_ok:
            return "FAILED", None, bind_err

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

        bound_controls = self._open_and_bind_reply_controls(
            page,
            parent_item,
            root_comment_id=root_comment_id,
            close_on_error=True,
        )
        if not bound_controls["ok"]:
            return "FAILED", None, bound_controls["error"]

        textarea = bound_controls["textarea"]
        submit_btn = bound_controls["submit_btn"]
        editor_already_open = bound_controls["editor_already_open"]

        textarea.fill(reply_content)
        page.wait_for_timeout(500)

        if not submit_btn.is_enabled():
            self._safe_close_editor(page, parent_item, editor_already_open, textarea)
            return "FAILED", None, "未能唯一定位可用的提交按钮"

        if before_submit is not None:
            intent_ok = before_submit()
            if not intent_ok:
                self._safe_close_editor(page, parent_item, editor_already_open, textarea)
                return "FAILED", None, "持久化提交意图失败（配额超限或防重冲突），中止发送"

        submit_btn.click()
        page.wait_for_timeout(3000)

        if guard.mismatched_requests and not guard.requests:
            mism = guard.mismatched_requests[0]
            return "FAILED", None, f"发送前路由守卫拦截: {mism.get('reason')} ({mism.get('details')})"

        if send_only:
            if guard.requests:
                return "SENT", None, None
            return "UNCERTAIN", None, "意图已持久化，但未观察到出站请求"

        api_success, new_reply_id, _resp_reason = guard.validate_success_response()

        pre_reload_img = attempt_dir / "post_submit_pre_reload_unverified.png"
        evidence_img = attempt_dir / "verified_reply.png"
        try:
            page.screenshot(path=str(pre_reload_img))
        except Exception:
            pass

        if api_success:
            readback_ok = False
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
                except Exception as exc:
                    logger.warning("[SecondaryReplyBrowser] 重新加载回读异常: %s", exc)

            if readback_ok:
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

        if guard.requests:
            if db:
                db.record_secondary_reply_uncertain(
                    task_id=task_id,
                    error_message="发评请求已发出，但未收到确定的 201 成功回执",
                    evidence_path=str(pre_reload_img),
                )
            return "UNCERTAIN", str(pre_reload_img), "未收到确定成功回执，转入 UNCERTAIN 对账"

        return "FAILED", str(pre_reload_img), "未触发发评网络请求"

    _interact_with_page = execute_page_reply_flow

    @property
    def scan_active(self):
        return bool(getattr(self, "_scan_post_ids", ()))

    @contextlib.contextmanager
    def scan_workflow(self, post_ids):
        """一批具名目标共用一次只读预算；浏览器仍串行，禁止借批次访问其他作品。"""
        from ..utils.wechat_operations_policy import load_policy
        policy = load_policy()
        ids = tuple(dict.fromkeys(str(p).strip() for p in post_ids if str(p).strip()))
        if policy is None:
            yield
            return
        if not ids or len(ids) > policy["operations"]["comment_scan"]["max_videos_per_run"]:
            raise WeChatSessionLockBusy("扫描批次目标数量无效")
        if getattr(self, "_workflow_session", None) is not None:
            raise WeChatSessionLockBusy("扫描工作流不允许嵌套")
        import hashlib
        identity = "scan-batch:" + hashlib.sha256("\n".join(ids).encode()).hexdigest()[:24]
        from video_processing.core.wechat_request_guard import WeChatRequestGuard
        hint = WeChatRequestGuard(self.state_path).evaluate(purpose="评论扫描", account_only=True)
        delay = _near_scan_release_delay(hint, time.time())
        if delay:
            logger.info("[SecondaryReplyBrowser] 具名扫描等待本地时间门禁 %.3f 秒；之后仍完整核验", delay)
            time.sleep(delay)  # 不持浏览器锁，不访问平台；配置/锁/队列在原生准入时重新判断。
        with self._session_scope(identity, purpose="评论扫描") as session:
            self._workflow_session = session
            self._scan_post_ids = frozenset(ids)
            try:
                yield
            finally:
                self._workflow_session = None
                self._scan_post_ids = frozenset()

    @contextlib.contextmanager
    def reply_workflow(self, post_id: str):
        """同一回复的复核、发送、独立回读共享一次有界账户许可。"""
        if getattr(self, "_workflow_session", None) is not None:
            raise WeChatSessionLockBusy("回复工作流不允许嵌套")
        if not post_id.strip():
            raise WeChatSessionLockBusy("缺少具体作品身份，禁止回复")
        with self._session_scope(post_id) as session:
            self._workflow_session = session
            try:
                yield
            finally:
                self._workflow_session = None

    @contextlib.contextmanager
    def open_session(
        self, guard: Optional[SecondaryReplySubmissionGuard] = None, *, readonly_post_id: str = "",
    ):
        """会话锁 + 全新 Chromium 上下文 + 发送路由守卫，yield 已打开评论页的 page。"""
        if not self.state_path.exists():
            raise FileNotFoundError(f"登录态文件不存在: {self.state_path}")
        post_id = guard.expected_export_id if guard is not None else readonly_post_id.strip()
        if not post_id:
            raise WeChatSessionLockBusy("缺少具体作品身份，禁止评论扫描或回复")
        session = getattr(self, "_workflow_session", None)
        allowed_post = session is not None and (session.video == post_id or post_id in getattr(self, "_scan_post_ids", ()))
        if session is not None and (not allowed_post or current_wechat_session() is not session):
            raise WeChatSessionLockBusy("回复工作流作品身份不匹配")
        scope = contextlib.nullcontext() if session is not None else self._session_scope(post_id)
        with scope:
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
                            route.fallback()

                        page.route("**/comment/create_comment*", route_interceptor)
                    else:
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
        """只读：在已打开页面的正确作品/父评论下，查找同作者且正文 NFC 完整等值的回复。"""
        if not author_id or "'" in author_id:
            return "UNKNOWN", ""
        is_login, _ = check_explicit_login_prompt(page)
        if is_login:
            return "UNKNOWN", ""
        bound_ok, _bind_err = self._select_and_bind_post_card(
            page,
            platform_post_id=platform_post_id,
            video_title=video_title,
            published_description=published_description,
            wait_ms=1500,
        )
        if not bound_ok:
            return "UNKNOWN", ""
        _replied, _comp, parent = self._check_author_already_replied(page, root_comment_id, author_id)
        if parent is None or _comp != "COMPLETE":
            return "UNKNOWN", ""
        valid_post_ids = {platform_post_id, self._bound_scene_post_id or ""} - {""}
        api_info = self._captured_comments.get(root_comment_id)
        if api_info is not None:
            if api_info.get("export_id") not in valid_post_ids or self._active_export_id not in valid_post_ids:
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
        if post_attr.count() != 1 or (post_attr.first.get_attribute("data-current-object-id") or "") not in valid_post_ids:
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
        """解析并绑定唯一的视频卡片；若出现多个候选卡片立即拒绝，绝不回退首个节点。"""
        card = page.locator(f"[data-object-id='{platform_post_id}']").filter(visible=True)
        if card.count() == 1:
            return card.first
        if card.count() > 1:
            logger.warning("[SecondaryReplyBrowser] data-object-id '%s' 匹配到多个卡片 (%d)，触发歧义阻断", platform_post_id, card.count())
            return None

        scene_pid = self._resolve_scene_post_id(platform_post_id, published_description) or platform_post_id
        title_hint = (
            self._post_descriptions.get(scene_pid)
            or published_description
            or video_title
            or ""
        )
        clean_hint = _normalized_text(title_hint)[:20]
        if clean_hint:
            cards = page.locator(".comment-feed-wrap:visible, .post-card:visible").filter(has_text=clean_hint)
            if cards.count() == 1:
                return cards.first
            if cards.count() > 1:
                logger.warning("[SecondaryReplyBrowser] 文案 '%s' 匹配到多个卡片 (%d)，触发歧义阻断", clean_hint, cards.count())
                return None

        scroll_container = page.locator(".feeds-container, .scroll-list__wrp, .scroll-list").filter(visible=True)
        if scroll_container.count() > 0:
            for _ in range(15):
                try:
                    scroll_container.first.hover()
                except Exception:
                    pass
                page.mouse.wheel(0, 2500)
                page.wait_for_timeout(800)

                card = page.locator(f"[data-object-id='{platform_post_id}']").filter(visible=True)
                if card.count() == 1:
                    return card.first
                if card.count() > 1:
                    logger.warning("[SecondaryReplyBrowser] 滚动后 data-object-id '%s' 匹配到多个卡片 (%d)，触发歧义阻断", platform_post_id, card.count())
                    return None

                scene_pid = self._resolve_scene_post_id(platform_post_id, published_description) or platform_post_id
                title_hint = (
                    self._post_descriptions.get(scene_pid)
                    or published_description
                    or video_title
                    or ""
                )
                clean_hint = _normalized_text(title_hint)[:20]
                if clean_hint:
                    cards = page.locator(".comment-feed-wrap:visible, .post-card:visible").filter(has_text=clean_hint)
                    if cards.count() == 1:
                        return cards.first
                    if cards.count() > 1:
                        logger.warning("[SecondaryReplyBrowser] 文案 '%s' 匹配到多个卡片 (%d)，触发歧义阻断", clean_hint, cards.count())
                        return None

        return None

    def _check_author_already_replied(
        self,
        page,
        root_comment_id: str,
        author_id: Optional[str],
    ) -> Tuple[bool, str, Any]:
        """检查指定一级评论下是否已有作者回复与分页完整性。"""
        parent_loc = page.locator(f"[data-comment-id='{root_comment_id}']").filter(visible=True)
        parent_node = None
        if parent_loc.count() == 1:
            parent_node = parent_loc.first
        elif parent_loc.count() > 1:
            return False, "AMBIGUOUS_COMMENT_ID", None
        else:
            raw_loc = page.locator(f"[data-comment-id='{root_comment_id}']")
            if raw_loc.count() > 0:
                return False, "HIDDEN_OR_AMBIGUOUS_COMMENT_NODE", None
            info = self._captured_comments.get(root_comment_id)
            if info and info.get("content_prefix") and info.get("export_id") == self._active_export_id:
                candidates = page.locator(".comment-item:visible").filter(has_text=info["content_prefix"])
                same_text = [c for c in self._captured_comments.values()
                             if c.get("content_prefix") == info["content_prefix"]]
                if candidates.count() == 0:
                    clean_probe = _normalized_text(re.sub(r"\[[^\[\]\s]{1,10}\]", "", info["content_prefix"]))
                    if clean_probe:
                        candidates = page.locator(".comment-item:visible").filter(has_text=clean_probe)
                        same_text = [
                            c for c in self._captured_comments.values()
                            if _normalized_text(re.sub(r"\[[^\[\]\s]{1,10}\]", "", c.get("content_prefix") or "")) == clean_probe
                        ]
                if candidates.count() == 1 and len(same_text) == 1:
                    parent_node = candidates.first
                elif candidates.count() > 1 or len(same_text) > 1:
                    return False, "AMBIGUOUS_COMMENT_TEXT", None

        if parent_node is None:
            return False, "NOT_FOUND", None

        if not author_id or "'" in author_id:
            return False, "INVALID_AUTHOR_ID", parent_node

        author_nodes = parent_node.locator(".level-two, [data-level-two], .comment-reply-list").locator(
            f"[data-author-id='{author_id}']"
        )
        if author_nodes.count() > 0:
            return True, "COMPLETE", parent_node

        api_info = self._captured_comments.get(root_comment_id, {})
        if any(isinstance(sub, dict) and sub.get("username") == author_id
               for sub in api_info.get("levelTwoComment", [])):
            return True, "COMPLETE", parent_node

        dom_status = parent_node.get_attribute("data-pagination-status") or ""
        if dom_status in ("unknown", "error", "timeout"):
            return False, "PAGINATION_UNKNOWN", parent_node

        _expand_sel, expand_count, _expand_txt, expand_btn_loc = self._locate_expand_control(parent_node)
        if expand_count > 1:
            return False, "PAGINATION_UNKNOWN", parent_node

        if expand_count == 1 and expand_btn_loc is not None:
            try:
                expand_btn_loc.click()
                page.wait_for_timeout(1000)
            except Exception as exc:
                logger.warning("[SecondaryReplyBrowser] 点击展开二级回复失败: %s", exc)
                return False, "PAGINATION_UNKNOWN", parent_node

            author_nodes_after = parent_node.locator(".level-two, [data-level-two], .comment-reply-list").locator(
                f"[data-author-id='{author_id}']"
            )
            if author_nodes_after.count() > 0:
                return True, "COMPLETE", parent_node

            api_info = self._captured_comments.get(root_comment_id, {})
            if any(isinstance(sub, dict) and sub.get("username") == author_id
                   for sub in api_info.get("levelTwoComment", [])):
                return True, "COMPLETE", parent_node
            _after_sel, still_expand_count, _after_txt, _after_loc = self._locate_expand_control(parent_node)
            new_status = parent_node.get_attribute("data-pagination-status") or ""
            if still_expand_count > 0 or new_status in ("unknown", "incomplete") or (api_info.get("downContinueFlag") == 1):
                return False, "PAGINATION_INCOMPLETE", parent_node

        elif api_info.get("downContinueFlag") == 1 or parent_node.get_attribute("data-down-continue-flag") == "1":
            return False, "PAGINATION_INCOMPLETE", parent_node

        if parent_loc.count() != 1 and (
            type(api_info.get("downContinueFlag")) is not int or api_info["downContinueFlag"] != 0
        ):
            return False, "PAGINATION_UNKNOWN", parent_node
        return False, "COMPLETE", parent_node

    def calibrate_comment_controls(
        self,
        page: Any,
        *,
        parent_item: Any,
        root_comment_id: str,
        attempt_dir: Optional[Path | str] = None,
    ) -> Dict[str, Any]:
        """只读探测并校准目标一级评论下的二级回复相关控件（与发送共用同一套定位规则）。

        严格执行零写安全：
        - 不向 textarea / edit-area 输入任何真实内容；
        - 绝不点击 submit 提交按钮；
        - 校验提交按钮在输入框为空时的不可用/禁用状态；
        - 若打开了回复编辑器，在探测结束后通过取消按钮或 ESC 恢复现场；
        - 产出各控件的选择器、数量、可见性与可用性诊断字典。
        """
        bound = self._open_and_bind_reply_controls(
            page,
            parent_item,
            root_comment_id=root_comment_id,
            close_on_error=True,
        )
        if not bound["ok"]:
            return {"ok": False, "error": bound["error"]}

        textarea_loc = bound["textarea"]
        submit_loc = bound["submit_btn"]
        editor_already_open = bound["editor_already_open"]

        textarea_editable = textarea_loc.is_editable()
        try:
            textarea_empty = bool(
                textarea_loc.evaluate("el => (el.value !== undefined ? el.value : el.innerText).trim() === ''")
            )
        except Exception:
            textarea_empty = True

        is_disabled_when_empty = bool(
            submit_loc.is_disabled()
            or submit_loc.get_attribute("aria-disabled") == "true"
            or "disabled" in (submit_loc.get_attribute("class") or "")
        )

        editor_closed = self._safe_close_editor(page, parent_item, editor_already_open, textarea_loc)

        evidence_path = None
        if attempt_dir:
            shot_target = Path(attempt_dir) / f"controls_calibration_{root_comment_id}.png"
            try:
                page.screenshot(path=str(shot_target))
                evidence_path = str(shot_target)
            except Exception:
                pass

        expand_count = int(bound["expand_count"])
        return {
            "ok": True,
            "error": None,
            "controls_calibration": {
                "reply_icon": {
                    "selector": bound["reply_selector"],
                    "found": True,
                    "count": 1,
                    "visible": True,
                    "enabled": bound["reply_enabled"],
                },
                "editor_textarea": {
                    "selector": bound["textarea_selector"],
                    "found": True,
                    "count": 1,
                    "visible": True,
                    "editable": textarea_editable,
                    "is_empty": textarea_empty,
                },
                "submit_button": {
                    "selector": bound["submit_selector"],
                    "found": True,
                    "count": 1,
                    "visible": True,
                    "enabled_when_filled": True,
                    "disabled_when_empty": is_disabled_when_empty,
                },
                "expand_button": {
                    "selector": bound["expand_selector"],
                    "found": bool(expand_count > 0),
                    "count": expand_count,
                    "visible": bool(expand_count > 0),
                    "text": bound["expand_text"],
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
                "completeness": "UNKNOWN",
                "reason": "LOGIN_REQUIRED",
                "channel_profile": {
                    "finder_id": author_id,
                    "native_username": "",
                    "channel_nickname": "",
                    "identity_verified": False,
                },
                "target": {
                    "post_id": platform_post_id,
                    "comment_id": root_comment_id,
                    "text_matched": False,
                    "fresh": False,
                },
            }

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

        identity_verified = bool(author_id and native_username and native_username == author_id)
        channel_profile = {
            "finder_id": author_id,
            "native_username": native_username,
            "channel_nickname": channel_nickname,
            "identity_verified": identity_verified,
        }

        bound_ok, bind_err = self._select_and_bind_post_card(
            page,
            platform_post_id=platform_post_id,
            video_title=video_title,
            published_description=published_description,
            wait_ms=1500,
        )
        if not bound_ok:
            return {
                "ok": False,
                "status": "UNKNOWN",
                "completeness": "UNKNOWN",
                "reason": bind_err,
                "channel_profile": channel_profile,
                "target": {
                    "post_id": platform_post_id,
                    "comment_id": root_comment_id,
                    "text_matched": False,
                    "fresh": False,
                },
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
                    ".comment-content, .content, .text, p, [data-comment-content], [data-reply-content]"
                ).filter(visible=True)
                if dom_text_loc.count() > 0:
                    actual_text = dom_text_loc.first.inner_text().strip()
            except Exception:
                pass

        if expected_comment_text is not None and str(expected_comment_text).strip():
            text_matched = bool(actual_text) and (
                _normalized_text(actual_text) == _normalized_text(expected_comment_text)
            )
        else:
            text_matched = bool(actual_text)

        target_info = {
            "post_id": platform_post_id,
            "comment_id": root_comment_id,
            "video_title": video_title or "",
            "author_nickname": actual_nickname,
            "comment_text": actual_text,
            "text_matched": text_matched,
            "fresh": parent_item is not None,
        }

        if parent_item is None:
            return {
                "ok": False,
                "status": "UNKNOWN",
                "completeness": completeness or "NOT_FOUND",
                "reason": f"评论区未找到原生 commentId 为 {root_comment_id} 的一级评论 ({completeness})",
                "channel_profile": channel_profile,
                "target": {
                    "post_id": platform_post_id,
                    "comment_id": root_comment_id,
                    "text_matched": False,
                    "fresh": False,
                },
            }

        if not text_matched:
            return {
                "ok": False,
                "status": "UNKNOWN",
                "completeness": completeness or "UNKNOWN",
                "reason": f"目标评论正文与预期不符或未读到 (实际: '{actual_text[:30]}...', 预期: '{(expected_comment_text or '')[:30]}...')",
                "channel_profile": channel_profile,
                "target": target_info,
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
            ok_replied = bool(identity_verified and text_matched and completeness not in ("INVALID", "ERROR", "INVALID_AUTHOR_ID"))
            return {
                "ok": ok_replied,
                "status": "REPLIED" if ok_replied else "UNKNOWN",
                "completeness": completeness or "OBSERVED_REPLIED",
                "reason": None if ok_replied else ("作者原生身份核对失败" if not identity_verified else "回复状态核验不完整"),
                "channel_profile": channel_profile,
                "target": target_info,
                "controls_calibration": {},
                "evidence_files": {"screenshot": shot_path},
            }

        if completeness != "COMPLETE":
            return {
                "ok": False,
                "status": "UNKNOWN",
                "completeness": completeness or "UNKNOWN",
                "reason": f"二级回复分页未穷尽 ({completeness})，无法证明作者未回复",
                "channel_profile": channel_profile,
                "target": target_info,
            }

        calib = self.calibrate_comment_controls(
            page, parent_item=parent_item, root_comment_id=root_comment_id, attempt_dir=attempt_dir
        )
        editor_closed_cleanly = bool(calib.get("editor_closed_cleanly", False))
        ok_unreplied = bool(calib["ok"] and identity_verified and text_matched)
        return {
            "ok": ok_unreplied,
            "status": "NOT_REPLIED" if ok_unreplied else "UNKNOWN",
            "completeness": "COMPLETE",
            "reason": calib.get("error") if not calib["ok"] else (
                None if ok_unreplied else "作者原生身份核对失败"
            ),
            "channel_profile": channel_profile,
            "target": target_info,
            "controls_calibration": calib.get("controls_calibration", {}),
            "editor_closed_cleanly": editor_closed_cleanly,
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
        out_dir = self.create_evidence_dir(evidence_dir)
        with self.open_session(readonly_post_id=platform_post_id) as page:
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

    def discover_comments_on_page(
        self,
        page: Any,
        *,
        platform_post_id: str,
        video_title: Optional[str] = None,
        published_description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """只读绑定指定作品卡片并返回捕获到的 comment_list 原始载荷。"""
        is_login, _ = check_explicit_login_prompt(page)
        if is_login:
            from ..core.wechat_session_lock import record_current_wechat_login_required
            record_current_wechat_login_required()
            return {"ok": False, "reason": "LOGIN_REQUIRED", "payload": None}
        bound_ok, bind_err = self._select_and_bind_post_card(
            page,
            platform_post_id=platform_post_id,
            video_title=video_title,
            published_description=published_description,
            wait_ms=1500,
        )
        if not bound_ok:
            return {"ok": False, "reason": bind_err or "CARD_BIND_FAILED", "payload": None}
        if isinstance(self._last_comment_list_payload, dict):
            return {"ok": True, "reason": None, "payload": self._last_comment_list_payload}
        return {"ok": False, "reason": "NO_COMMENT_LIST_PAYLOAD_CAPTURED", "payload": None}


