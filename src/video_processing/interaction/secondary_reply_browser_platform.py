"""把真实浏览器适配器接入业务编排的平台端口实现。

``SecondaryReplyBrowserAdapter`` 负责页面级动作；本类把它适配成编排所需的
``SecondaryReplyPlatformPort``：作者回复状态只读复核、唯一出站发送、全新会话独立回读。

边界：
- 每个端口方法各开一次全新会话（持 WeChatSessionLock，生成与人工等待不持锁）。
- 回读/对账用全新会话，读到的是服务器数据而非发送会话的乐观 DOM。
- 端口自身不写库；意图持久化由编排传入的 ``before_submit`` 完成。
- 真实平台仍需 M3 只读样本验证；默认不被任何入口自动构造。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-10-17 | Codex | 新增 calibrate_controls 与 calibrate_and_verify 只读控件校准及平台状态验证 (R1/R2) |
| 1.0.0 | 2026-10-13 | Antigravity | 新增：浏览器适配器的平台端口封装（只读复核/唯一发送/全新会话回读） |
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any, Callable, ContextManager, Dict, Optional, Tuple

from video_processing.interaction.secondary_reply_browser_adapter import (
    SecondaryReplyBrowserAdapter,
    SecondaryReplySubmissionGuard,
)
from video_processing.interaction.secondary_reply_orchestrator import LookupResult, PlatformSendResult

logger = logging.getLogger(__name__)

SessionFactory = Callable[[Optional[SecondaryReplySubmissionGuard]], ContextManager[Any]]


class BrowserSecondaryReplyPlatform:
    """``SecondaryReplyPlatformPort`` 的浏览器实现。"""

    evidence_ref = "browser://fresh_session_readback"

    def __init__(
        self,
        adapter: SecondaryReplyBrowserAdapter,
        *,
        account_finder_id: str,
        post_hints: Optional[Callable[[str], Tuple[str, str]]] = None,
        session_factory: Optional[SessionFactory] = None,
        trusted_origins: Tuple[str, ...] = (),
        evidence_dir: Optional[Path] = None,
    ) -> None:
        if not account_finder_id:
            raise ValueError("account_finder_id 不能为空（必须是已验证的作者原生账号标识）")
        self.adapter = adapter
        self.account_finder_id = account_finder_id
        self._hints = post_hints or (lambda _post_id: ("", ""))
        self._session = session_factory or adapter.open_session
        self._trusted_origins = trusted_origins
        self._evidence_dir = evidence_dir or Path(tempfile.gettempdir()) / "secondary_reply_evidence"

    def make_guard(self, post_id: str, root_id: str, text: str) -> SecondaryReplySubmissionGuard:
        return SecondaryReplySubmissionGuard(
            post_id, root_id, text,
            expected_finder_id=self.account_finder_id, trusted_origins=self._trusted_origins,
        )

    def author_reply_state(self, *, post_id: str, root_id: str) -> str:
        title, desc = self._hints(post_id)
        try:
            with self._session(None) as page:
                status, _ev, _reason = self.adapter._interact_with_page(
                    page, task_id=0, platform_post_id=post_id, root_comment_id=root_id,
                    reply_content="-", video_title=title, published_description=desc,
                    attempt_dir=self.adapter._new_evidence_dir(self._evidence_dir),
                    guard=self.make_guard(post_id, root_id, "-"), verify_only=True,
                )
        except Exception as exc:
            logger.warning("作者回复状态复核异常，按 UNKNOWN 处理: %s", exc)
            return "UNKNOWN"
        if status == "VERIFIED_ABSENT":
            return "NOT_REPLIED"
        if status in ("FOUND_UNVERIFIED", "SKIPPED_ALREADY_REPLIED"):
            return "REPLIED"
        return "UNKNOWN"

    def send_reply(
        self, *, post_id: str, root_id: str, text: str,
        before_submit: Callable[[], bool], guard: SecondaryReplySubmissionGuard,
    ) -> PlatformSendResult:
        persisted = [False]

        def wrapped_before_submit() -> bool:
            ok = bool(before_submit())
            persisted[0] = ok
            return ok

        title, desc = self._hints(post_id)
        try:
            with self._session(guard) as page:
                status, _evidence, reason = self.adapter._interact_with_page(
                    page, task_id=0, platform_post_id=post_id, root_comment_id=root_id,
                    reply_content=text, video_title=title, published_description=desc,
                    attempt_dir=self.adapter._new_evidence_dir(self._evidence_dir),
                    guard=guard, before_submit=wrapped_before_submit, send_only=True,
                )
                if status not in ("SENT", "VERIFIED"):
                    return PlatformSendResult(intent_persisted=persisted[0], guard=guard,
                                              exception=f"{status}: {reason}")
        except Exception as exc:
            return PlatformSendResult(intent_persisted=persisted[0], guard=guard, exception=str(exc))
        return PlatformSendResult(intent_persisted=persisted[0], guard=guard)

    def lookup_reply(self, *, post_id: str, root_id: str, text: str) -> LookupResult:
        title, desc = self._hints(post_id)
        shot = ""
        shot_ok = True
        try:
            with self._session(None) as page:
                state, reply_id = self.adapter.find_author_reply(
                    page, platform_post_id=post_id, root_comment_id=root_id, reply_content=text,
                    author_id=self.account_finder_id, video_title=title, published_description=desc,
                )
                if state == "FOUND" and reply_id:
                    # 此刻页面是全新会话加载并核对通过的服务器状态；在此取证
                    try:
                        out_dir = self.adapter._new_evidence_dir(self._evidence_dir)
                        target = out_dir / f"readback_{reply_id.replace('/', '_')}.png"
                        page.screenshot(path=str(target))
                        if not target.exists():
                            raise OSError("screenshot file missing")
                        shot = str(target)
                    except Exception as exc:
                        logger.warning("回读证据截图保存失败: %s", exc)
                        shot_ok = False
        except Exception as exc:
            logger.warning("回读会话异常，按未观察到处理: %s", exc)
            return LookupResult(found=False)
        if state == "FOUND" and reply_id:
            return LookupResult(found=True, reply_id=reply_id, complete=True, evidence_path=shot, evidence_ok=shot_ok)
        return LookupResult(found=False)

    def calibrate_controls(
        self,
        *,
        post_id: str,
        root_id: str,
        evidence_dir: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """只读校准指定作品与父评论下的二级回复相关控件。"""
        title, desc = self._hints(post_id)
        return self.adapter.verify_and_calibrate_controls(
            platform_post_id=post_id,
            root_comment_id=root_id,
            video_title=title,
            published_description=desc,
            author_finder_id=self.account_finder_id,
            evidence_dir=evidence_dir or self._evidence_dir,
        )

    def calibrate_and_verify(
        self,
        *,
        post_id: str,
        root_id: str,
        video_title: Optional[str] = None,
        comment_text: Optional[str] = None,
        evidence_dir: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """在会话锁与路由强拦截下，执行三态回复分类、目标作品/父评论验证与控件校准。"""
        title = video_title or (self._hints(post_id)[0] if self._hints else "")
        desc = self._hints(post_id)[1] if self._hints else ""
        out_dir = self.adapter._new_evidence_dir(evidence_dir or self._evidence_dir)
        try:
            with self._session(None) as page:
                return self.adapter.calibrate_page_controls(
                    page,
                    platform_post_id=post_id,
                    root_comment_id=root_id,
                    author_id=self.account_finder_id,
                    video_title=title,
                    published_description=desc,
                    expected_comment_text=comment_text,
                    attempt_dir=out_dir,
                )
        except Exception as exc:
            logger.warning("[BrowserSecondaryReplyPlatform] 控件校准与状态验证异常: %s", exc)
            return {
                "ok": False,
                "status": "UNKNOWN",
                "reason": f"PLATFORM_VERIFICATION_EXCEPTION: {exc}",
                "target": {"post_id": post_id, "comment_id": root_id, "fresh": False},
                "controls_calibration": {},
            }


