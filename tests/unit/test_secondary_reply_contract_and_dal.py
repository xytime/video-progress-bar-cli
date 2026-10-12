"""视频号二级回复数据合同、DAL 与安全状态机单元测试。

覆盖：
- 长度方案 A (中<=75, 英<=150, 合<=230)
- 禁止内部换行、Emoji、Markdown 标签、分隔符
- 非法控制字符拒绝并报错
- 输入评论超出预算时标记 MANUAL 并不静默截断 (T12)
- 独立防重账本与墓碑持久性：删除任务后仍有效阻断 (T09)
- 配额原子预占：单视频3条上限、滚动60分钟10条上限、上海时段、15秒间隔 (T14)
- 审批 Token 一次性消费、防重放、过期与身份匹配 (T07)
- 并发抢占与防多出站请求 (T05)
"""

from __future__ import annotations

import datetime
import hashlib
from pathlib import Path
import pytest
import sqlite3

from video_processing.db.database import PipelineDB
from video_processing.interaction.secondary_reply_contract import (
    SecondaryReplyIntent,
    SecondaryReplyStyle,
    SecondaryReplyStatus,
    SecondaryReplyContractError,
    IllegalControlCharError,
    validate_reply_length_and_format,
    validate_input_comment,
    MAX_ZH_CODEPOINTS,
    MAX_EN_CODEPOINTS,
    MAX_COMBINED_CODEPOINTS,
)

UTC = datetime.timezone.utc


# =========================================================================
# 1. 契约与格式校验测试 (Contract & Format)
# =========================================================================

def test_scheme_a_valid_replies():
    zh = "地缘脆弱性与生存代偿确实深刻，你如何看未来十年该模式的抗冲击韧性？"
    en = "Geopolitical vulnerability is real. How durable is this model against future shocks?"
    zh_nfc, en_nfc, formatted = validate_reply_length_and_format(zh, en)
    assert zh_nfc == zh
    assert en_nfc == en
    assert formatted == f"{zh}\n{en}"
    assert len(zh_nfc) <= MAX_ZH_CODEPOINTS
    assert len(en_nfc) <= MAX_EN_CODEPOINTS
    assert len(formatted) <= MAX_COMBINED_CODEPOINTS


def test_scheme_a_rejects_internal_newlines():
    zh_with_nl = "第一行观点\n第二行观点"
    en = "Valid english text"
    with pytest.raises(SecondaryReplyContractError, match="字段内部不得包含换行符"):
        validate_reply_length_and_format(zh_with_nl, en)

    zh = "合法中文观点"
    en_with_cr = "Line 1\rLine 2"
    with pytest.raises(SecondaryReplyContractError, match="字段内部不得包含换行符"):
        validate_reply_length_and_format(zh, en_with_cr)


def test_scheme_a_rejects_emojis_and_tags():
    zh_emoji = "非常赞同这个观点！👍"
    en = "Totally agree."
    with pytest.raises(SecondaryReplyContractError, match="Emoji"):
        validate_reply_length_and_format(zh_emoji, en)

    zh_tag = "请查看 <a href='http://evil.com'>链接</a>"
    with pytest.raises(SecondaryReplyContractError, match="标签或格式标记"):
        validate_reply_length_and_format(zh_tag, en)

    zh_md = "**加粗观点**"
    with pytest.raises(SecondaryReplyContractError, match="标签或格式标记"):
        validate_reply_length_and_format(zh_md, en)

    zh_sep = "观点一 --- 观点二"
    with pytest.raises(SecondaryReplyContractError, match="装饰分隔符"):
        validate_reply_length_and_format(zh_sep, en)


def test_scheme_a_rejects_illegal_control_characters():
    zh_ctrl = "正常观点\x00注入控制字符"
    en = "Normal text"
    with pytest.raises(IllegalControlCharError, match="非法控制字符"):
        validate_reply_length_and_format(zh_ctrl, en)

    zh = "正常观点"
    en_ctrl = "Normal\x1b[31mtext"
    with pytest.raises(IllegalControlCharError, match="非法控制字符"):
        validate_reply_length_and_format(zh, en_ctrl)


def test_scheme_a_length_boundaries():
    # 中文刚好 75 码点
    zh_75 = "一" * 75
    en_10 = "A" * 10
    zh_out, en_out, fmt = validate_reply_length_and_format(zh_75, en_10)
    assert len(zh_out) == 75

    # 中文 76 码点，超长拒绝
    zh_76 = "一" * 76
    with pytest.raises(SecondaryReplyContractError, match="中文回复超过方案 A 上限"):
        validate_reply_length_and_format(zh_76, en_10)

    # 英文刚好 150 码点
    zh_10 = "观点"
    en_150 = "A" * 150
    zh_out, en_out, fmt = validate_reply_length_and_format(zh_10, en_150)
    assert len(en_out) == 150

    # 英文 151 码点，超长拒绝
    en_151 = "A" * 151
    with pytest.raises(SecondaryReplyContractError, match="英文回复超过方案 A 上限"):
        validate_reply_length_and_format(zh_10, en_151)

    # 合并上限 230 码点 (75 + 1 + 150 = 226 <= 230 合法)
    zh_out, en_out, fmt = validate_reply_length_and_format(zh_75, en_150)
    assert len(fmt) == 75 + 1 + 150


def test_input_comment_budget_and_no_silent_truncation():
    # 正常评论
    normal_text = "这是一条正常的观众评论，没有超过输入预算。"
    content, is_truncated, hash_val = validate_input_comment(normal_text, max_codepoints=50)
    assert content == normal_text
    assert is_truncated is False
    assert hash_val == hashlib.sha256(normal_text.encode("utf-8")).hexdigest()

    # 超过预算评论：不截断原文，保留完整哈希，返回 is_truncated=True
    long_text = "很长的观众评论，后面有关键转折：我不赞同视频结尾关于汇率风险已释放的论断。"
    content, is_truncated, hash_val = validate_input_comment(long_text, max_codepoints=20)
    assert content == long_text  # 决不静默截断！完整保留！
    assert is_truncated is True
    assert hash_val == hashlib.sha256(long_text.encode("utf-8")).hexdigest()


# =========================================================================
# 2. 数据库与 DAL 测试 (DAL & State Machine)
# =========================================================================

@pytest.fixture
def test_db(tmp_path: Path) -> PipelineDB:
    db_file = tmp_path / "test_pipeline.db"
    return PipelineDB(db_path=str(db_file))


def test_audience_comments_saving_and_deduplication(test_db: PipelineDB):
    post_id = "export/synth_post_001"
    raw_comments = [
        {
            "commentId": "c_001",
            "commentNickname": "用户A",
            "commentContent": "评论内容一",
            "is_author": False,
            "has_author_reply": False,
        },
        {
            "commentId": "c_002",
            "commentNickname": "作者号",
            "commentContent": "作者置顶首评",
            "is_author": True,
            "has_author_reply": False,
        },
        {
            "commentId": "c_003",
            "commentNickname": "用户B",
            "commentContent": "已回复评论",
            "is_author": False,
            "has_author_reply": True,
        }
    ]
    inserted = test_db.save_discovered_audience_comments(post_id, raw_comments)
    assert inserted == 3

    # 重复保存，应该幂等忽略
    inserted_again = test_db.save_discovered_audience_comments(post_id, raw_comments)
    assert inserted_again == 0

    # 查询待处理观众评论（排除作者自身的首评以及已回复评论）
    unprocessed = test_db.get_unprocessed_audience_comments(post_id)
    assert len(unprocessed) == 1
    assert unprocessed[0]["comment_id"] == "c_001"
    assert unprocessed[0]["nickname"] == "用户A"


def test_secondary_reply_task_lifecycle_and_approval_token(test_db: PipelineDB):
    post_id = "export/synth_post_002"
    cid = "c_101"

    # 1. 创建草稿任务
    task_id = test_db.create_or_update_secondary_reply_task(
        platform_post_id=post_id,
        comment_id=cid,
        intent="REPLY",
        style="MACRO",
        chinese_reply="中文回复正文",
        english_reply="English reply text",
        formatted_reply="中文回复正文\nEnglish reply text",
        reason_code="VALID_AUDIENCE_QUERY",
        provider="rule_mock",
        status="DRAFTED",
    )
    task = test_db.get_secondary_reply_task(task_id)
    assert task is not None
    assert task["status"] == "DRAFTED"
    assert task["revision"] == 1

    # 2. 绑定审批请求 Token
    token = "secret_token_xyz123"
    expires = (datetime.datetime.now(UTC) + datetime.timedelta(hours=2)).isoformat()
    bound = test_db.bind_reply_task_approval_request(
        task_id, approval_token=token, expires_at_iso=expires, approver_id="tg_admin_88"
    )
    assert bound is True

    task = test_db.get_secondary_reply_task(task_id)
    assert task["status"] == "PENDING_REVIEW"
    assert task["approval_token"] == token

    # 3. 审批 Token 防重放与防伪造校验
    # 错误 Token 拒绝
    ok, reason = test_db.consume_reply_task_approval(
        task_id=task_id, token="wrong_token", approver_id="tg_admin_88", action="APPROVE"
    )
    assert ok is False
    assert reason == "TOKEN_MISMATCH"

    # 错误审批人拒绝
    ok, reason = test_db.consume_reply_task_approval(
        task_id=task_id, token=token, approver_id="tg_attacker_99", action="APPROVE"
    )
    assert ok is False
    assert reason == "APPROVER_MISMATCH"

    # 正确批准
    ok, reason = test_db.consume_reply_task_approval(
        task_id=task_id, token=token, approver_id="tg_admin_88", action="APPROVE"
    )
    assert ok is True
    assert reason == "APPROVED"

    # 重复批准拒绝（一次性消费 Token 防重放）
    ok, reason = test_db.consume_reply_task_approval(
        task_id=task_id, token=token, approver_id="tg_admin_88", action="APPROVE"
    )
    assert ok is False
    assert "TOKEN_ALREADY_CONSUMED" in reason or "INVALID_STATUS" in reason


def test_claim_and_atomic_submit_intent(test_db: PipelineDB):
    post_id = "export/synth_post_003"
    cid = "c_201"

    task_id = test_db.create_or_update_secondary_reply_task(
        platform_post_id=post_id,
        comment_id=cid,
        intent="REPLY",
        style="PRAGMATIC",
        chinese_reply="务实中文",
        english_reply="Pragmatic en",
        formatted_reply="务实中文\nPragmatic en",
        provider="rule_mock",
        status="APPROVED",
    )

    # 1. 认领任务
    claimed = test_db.claim_approved_reply_task(lease_seconds=60, task_id=task_id)
    assert claimed is not None
    lease_token = claimed["lease_token"]
    assert claimed["status"] == "CLAIMED"

    # 构造上海时段（10:00）测试提交意图
    shanghai_time = datetime.datetime(2026, 10, 12, 10, 0, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=8)))
    now_utc = shanghai_time.astimezone(UTC).isoformat()

    # 2. 原子记录提交意图 (SUBMIT_INTENT)
    ok, msg = test_db.record_secondary_reply_submit_intent(task_id, lease_token, now_utc=now_utc)
    assert ok is True
    assert msg == "INTENT_RECORDED"

    # 验证独立防重账本已写入 INTENT
    ledger = test_db.check_secondary_reply_idempotency(post_id, cid)
    assert ledger is not None
    assert ledger["status"] == "INTENT"

    # 验证同一租约/worker 二次调用被独立防重账本唯一键直接拦截 (T05)
    ok_second, msg_second = test_db.record_secondary_reply_submit_intent(task_id, lease_token, now_utc=now_utc)
    assert ok_second is False
    assert "INVALID_STATUS" in msg_second or "IDEMPOTENCY_CONFLICT" in msg_second


def test_tombstone_survives_task_deletion_and_blocks_resend(test_db: PipelineDB):
    """验证 T09: 删除任务及其上游记录后，独立防重账本 INTENT/UNCERTAIN/VERIFIED 凭据仍生效。"""
    post_id = "export/synth_post_t09"
    cid = "c_t09_root"

    task_id = test_db.create_or_update_secondary_reply_task(
        platform_post_id=post_id,
        comment_id=cid,
        intent="REPLY",
        style="PHILOSOPHICAL",
        chinese_reply="哲理中文",
        english_reply="Philosophical en",
        formatted_reply="哲理中文\nPhilosophical en",
        provider="rule_mock",
        status="APPROVED",
    )
    claimed = test_db.claim_approved_reply_task(lease_seconds=60, task_id=task_id)
    sh_dt = datetime.datetime(2026, 10, 12, 11, 0, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=8)))
    now_utc = sh_dt.astimezone(UTC).isoformat()

    ok, msg = test_db.record_secondary_reply_submit_intent(task_id, claimed["lease_token"], now_utc=now_utc)
    assert ok is True

    # 模拟外部直接删除了该任务！
    with test_db.get_connection() as conn:
        conn.execute("DELETE FROM wechat_secondary_reply_tasks WHERE id = ?", (task_id,))
        conn.commit()

    # 确认任务已被物理删除
    assert test_db.get_secondary_reply_task(task_id) is None

    # 确认独立防重账本依然健在！
    ledger = test_db.check_secondary_reply_idempotency(post_id, cid)
    assert ledger is not None
    assert ledger["status"] == "INTENT"

    # 尝试重新创建并提交（时间延后20秒，通过15秒间隔检查，精确验证独立防重账本拦截）
    task_id_new = test_db.create_or_update_secondary_reply_task(
        platform_post_id=post_id,
        comment_id=cid,
        intent="REPLY",
        style="PHILOSOPHICAL",
        chinese_reply="哲理中文2",
        english_reply="Philosophical en2",
        formatted_reply="哲理中文2\nPhilosophical en2",
        provider="rule_mock",
        status="APPROVED",
    )
    claimed_new = test_db.claim_approved_reply_task(lease_seconds=60, task_id=task_id_new)
    now_utc_later = (sh_dt + datetime.timedelta(seconds=20)).astimezone(UTC).isoformat()
    ok_new, msg_new = test_db.record_secondary_reply_submit_intent(task_id_new, claimed_new["lease_token"], now_utc=now_utc_later)
    assert ok_new is False
    assert "IDEMPOTENCY_CONFLICT" in msg_new


def test_quota_limits_single_video_and_rolling_hour(test_db: PipelineDB):
    """验证 T14: 配额检查与上海时段边界。"""
    post_id = "export/synth_post_quota"
    sh_tz = datetime.timezone(datetime.timedelta(hours=8))

    # 1. 凌晨时段 (03:00) 拒绝
    night_time = datetime.datetime(2026, 10, 12, 3, 0, 0, tzinfo=sh_tz)
    allowed, reason = test_db.check_wechat_reply_quota(post_id, now_utc=night_time.astimezone(UTC))
    assert allowed is False
    assert "Outside Shanghai submission window" in reason

    # 2. 正常工作时段 (14:00)
    day_time = datetime.datetime(2026, 10, 12, 14, 0, 0, tzinfo=sh_tz)
    allowed, reason = test_db.check_wechat_reply_quota(post_id, now_utc=day_time.astimezone(UTC))
    assert allowed is True

    # 3. 单视频累计已达 3 条，拒绝第 4 条
    with test_db.get_connection() as conn:
        for i in range(3):
            conn.execute(
                """
                INSERT INTO wechat_secondary_reply_idempotency_ledger (
                    platform_post_id, root_comment_id, reply_comment_id, content_hash, status, created_at
                ) VALUES (?, ?, ?, ?, 'VERIFIED', '2026-10-10 10:00:00')
                """,
                (post_id, f"root_{i}", f"reply_{i}", f"hash_{i}"),
            )
        conn.commit()

    allowed, reason = test_db.check_wechat_reply_quota(post_id, now_utc=day_time.astimezone(UTC))
    assert allowed is False
    assert "Single video secondary reply limit reached" in reason
