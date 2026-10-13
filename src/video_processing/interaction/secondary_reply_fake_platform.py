"""离线平台替身：模拟视频号服务器端状态与二级回复发送，经真实路由守卫放行/拦截。

仅用于离线演示与测试，不具备任何真实网络能力。它不是浏览器适配器，只证明编排、守卫、
意图、回读与对账状态机的行为；真实平台字段与分页仍属未验证项。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-13 | Antigravity | 新增：可注入的离线平台替身（多种故障模式） |
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from video_processing.interaction.secondary_reply_browser_adapter import SecondaryReplySubmissionGuard
from video_processing.interaction.secondary_reply_orchestrator import LookupResult, PlatformSendResult

_SUBMIT_URL = "https://channels.weixin.qq.com/cgi-bin/mmfinderassistant-bin/comment/create_comment"


@dataclass
class _FakeRequest:
    method: str
    url: str
    post_data_json: Dict[str, Any]


@dataclass
class _FakeResponse:
    request: Any
    url: str
    status: int
    _body: Dict[str, Any]

    def json(self) -> Dict[str, Any]:
        return self._body


@dataclass
class FakeSecondaryReplyPlatform:
    account_finder_id: str = "v2_synthetic_author_finder_id@finder"
    mode: str = "success"
    # 服务器持久化数据: (post_id, root_id) -> [{"commentId","authorId","content"}]
    server_replies: Dict[tuple, List[Dict[str, str]]] = field(default_factory=dict)
    outbound_requests: List[Dict[str, Any]] = field(default_factory=list)  # 真正放行出站的请求
    _seq: int = 0

    # ---- 端口实现 ----
    def seed_author_reply(self, post_id: str, root_id: str, content: str = "手机端先回复") -> None:
        self._store(post_id, root_id, content, self.account_finder_id, "phone_reply_1")

    def author_reply_state(self, *, post_id: str, root_id: str) -> str:
        if self.mode == "state-unknown":
            return "UNKNOWN"
        replies = self.server_replies.get((post_id, root_id), [])
        return "REPLIED" if any(r["authorId"] == self.account_finder_id for r in replies) else "NOT_REPLIED"

    def send_reply(
        self, *, post_id: str, root_id: str, text: str,
        before_submit: Callable[[], bool], guard: SecondaryReplySubmissionGuard,
    ) -> PlatformSendResult:
        result = PlatformSendResult(guard=guard)
        if not before_submit():
            return result
        result.intent_persisted = True
        if self.mode == "crash-after-intent":
            raise RuntimeError("simulated process crash after intent")

        payload = {
            "exportId": post_id, "rootCommentId": root_id, "replyCommentId": root_id,
            "content": text, "_log_finder_id": self.account_finder_id,
        }
        if self.mode == "wrong-root":
            payload["rootCommentId"] = payload["replyCommentId"] = "some_other_comment"
        if self.mode == "wrong-post":
            payload["exportId"] = "export/some_other_post"
        if self.mode == "wrong-account":
            payload["_log_finder_id"] = "v2_other_account@finder"
        if self.mode == "missing-account":
            payload.pop("_log_finder_id")
        if self.mode == "altered-text":
            payload["content"] = text + "!"

        request = _FakeRequest("POST", _SUBMIT_URL, payload)
        if not guard.capture_request(request):
            return result  # 网络前被拦截：不触达服务器

        self.outbound_requests.append(payload)
        if self.mode == "drop-response":
            self._store(post_id, root_id, payload["content"], self.account_finder_id)
            return result  # 服务器已受理，但响应丢失
        if self.mode == "drop-not-persisted":
            return result  # 请求丢失，服务器未受理

        reply_id = self._next_id()
        if self.mode != "optimistic-only":
            self._store(post_id, root_id, payload["content"], self.account_finder_id, reply_id)
        body = {
            "errCode": 0,
            "data": {
                "commentId": reply_id,
                "comment": {
                    "commentId": reply_id, "commentContent": payload["content"],
                    "replyCommentId": root_id, "username": self.account_finder_id,
                },
            },
        }
        response_request = request
        if self.mode == "unrelated-response":
            response_request = _FakeRequest("POST", _SUBMIT_URL, dict(payload))  # 不是被放行的那个 Request
        guard.capture_response(_FakeResponse(response_request, _SUBMIT_URL, 201, body))
        return result

    def lookup_reply(self, *, post_id: str, root_id: str, text: str) -> LookupResult:
        for r in self.server_replies.get((post_id, root_id), []):
            if r["authorId"] == self.account_finder_id and r["content"] == text:
                return LookupResult(True, r["commentId"], complete=True)
        return LookupResult(False, "", complete=False)

    # ---- 内部 ----
    def _next_id(self) -> str:
        self._seq += 1
        return f"fake_reply_{self._seq}"

    def _store(self, post_id: str, root_id: str, content: str, author: str, reply_id: Optional[str] = None) -> None:
        self.server_replies.setdefault((post_id, root_id), []).append(
            {"commentId": reply_id or self._next_id(), "authorId": author, "content": content}
        )
