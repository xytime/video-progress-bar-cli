"""二级回复测试公共助手：通过真实审批绑定与消费路径制造“已批准”任务，不直接伪造 APPROVED 状态。"""
from __future__ import annotations

import datetime
import hashlib
import secrets

from video_processing.db.database import PipelineDB

TEST_ACCOUNT = "acct_test"
TEST_APPROVER = "admin_1"
TEST_CHAT = "chat_1"


def approved_task(db: PipelineDB, *, account_key: str = TEST_ACCOUNT, comment_text: str = "观众评论内容", **kw) -> int:
    """创建草稿 -> 保存源评论 -> 绑定审批 -> 以正确 token/审批人/chat 消费，得到真正 APPROVED 的任务。"""
    kw.setdefault("intent", "REPLY")
    kw.setdefault("style", "MACRO")
    kw.setdefault("provider", "rule_mock")
    zh = kw.get("chinese_reply", "")
    en = kw.get("english_reply", "")
    if not kw.get("formatted_reply"):
        kw["formatted_reply"] = f"{zh}\n{en}" if en else zh
    db.save_discovered_audience_comments(
        kw["platform_post_id"],
        [{"comment_id": kw["comment_id"], "nickname": "观众", "content": comment_text}],
        account_key=account_key,
    )
    task_id = db.create_or_update_secondary_reply_task(account_key=account_key, status="PENDING_REVIEW", **kw)
    token = secrets.token_urlsafe(16)
    expires = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    assert db.bind_reply_task_approval_request(
        task_id, approval_token=token, expires_at_iso=expires,
        approver_id=TEST_APPROVER, approver_chat_id=TEST_CHAT,
    )
    ok, reason = db.consume_reply_task_approval(
        task_id=task_id, token=token, approver_id=TEST_APPROVER, chat_id=TEST_CHAT, action="APPROVE",
    )
    assert ok, reason
    return task_id
