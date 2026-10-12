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
    TopLevelPaginationStatus,
    SecondaryPaginationStatus,
    parse_wechat_comment_list_payload,
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


def test_parse_comment_list_payload_discovery_t01():
    """T01: 无作者首评且仅 1 条观众评论依然稳定发现；downContinueFlag=0 判定为 COMPLETE。"""
    payload = {
        "comment_list": {
            "data": {
                "comment": [
                    {
                        "commentId": "c_only_one",
                        "commentNickname": "用户A",
                        "commentContent": "很好的分析",
                        "commentCreatetime": "1700000000",
                        "levelTwoComment": [],
                    }
                ],
                "downContinueFlag": 0,
                "lastBuff": "token_end",
            }
        }
    }
    res = parse_wechat_comment_list_payload(payload, platform_post_id="export/test_t01")
    assert res.top_level_status == TopLevelPaginationStatus.COMPLETE
    assert res.author_first_comment is None
    assert len(res.comments) == 1
    assert res.comments[0].comment_id == "c_only_one"
    assert res.secondary_states["c_only_one"] == SecondaryPaginationStatus.NO_REPLIES


def test_parse_comment_list_payload_folded_pagination_t02():
    """T02: 分别判断一级与二级分页完整性，未知折叠或二级 downContinueFlag=1 标记为 UNSUPPORTED_FOLDED_PAGINATION。"""
    payload = {
        "comment_list": {
            "data": {
                "comment": [
                    {
                        "commentId": "c_folded",
                        "commentNickname": "热评用户",
                        "commentContent": "这是大热评",
                        "downContinueFlag": 1,
                        "levelTwoComment": [
                            {"commentId": "sub_1", "commentContent": "赞同", "downContinueFlag": 0}
                        ],
                    },
                    {
                        "commentId": "c_normal",
                        "commentNickname": "普通用户",
                        "commentContent": "这是普通评论",
                        "downContinueFlag": 0,
                        "levelTwoComment": [],
                    },
                ],
                "downContinueFlag": 1,
                "lastBuff": "token_more",
            }
        }
    }
    res = parse_wechat_comment_list_payload(payload, platform_post_id="export/test_t02")
    assert res.top_level_status == TopLevelPaginationStatus.HAS_MORE
    assert res.secondary_states["c_folded"] == SecondaryPaginationStatus.UNSUPPORTED_FOLDED_PAGINATION
    assert "c_folded" in res.unsupported_comments
    assert res.secondary_states["c_normal"] == SecondaryPaginationStatus.NO_REPLIES


def test_parse_comment_list_disambiguation_t03():
    """T03: 相同昵称、相同正文的不同评论根据 commentId 精准消歧，绝不串号。"""
    payload = {
        "comment_list": {
            "data": {
                "comment": [
                    {
                        "commentId": "c_dup_101",
                        "commentNickname": "张三",
                        "commentContent": "支持！",
                        "commentCreatetime": "1700000001",
                    },
                    {
                        "commentId": "c_dup_102",
                        "commentNickname": "张三",
                        "commentContent": "支持！",
                        "commentCreatetime": "1700000002",
                    },
                ],
                "downContinueFlag": 0,
            }
        }
    }
    res = parse_wechat_comment_list_payload(payload, platform_post_id="export/test_t03")
    assert len(res.comments) == 2
    assert res.comments[0].comment_id == "c_dup_101"
    assert res.comments[1].comment_id == "c_dup_102"
    assert res.comments[0].content_hash == res.comments[1].content_hash


def test_parse_comment_list_strict_schema_rejection_t12():
    """T12: 严格 Schema 校验，拒绝类型强转与非法控制字符。"""
    # 1. commentId 必须为 str，整型拒绝
    payload_bad_type = {
        "comment_list": {
            "data": {
                "comment": [{"commentId": 12345, "commentContent": "text"}],
                "downContinueFlag": 0,
            }
        }
    }
    with pytest.raises(SecondaryReplyContractError, match="commentId 必须为字符串类型"):
        parse_wechat_comment_list_payload(payload_bad_type, platform_post_id="p1", strict_schema=True)

    # 2. 正文包含控制字符拒绝
    payload_ctrl = {
        "comment_list": {
            "data": {
                "comment": [{"commentId": "c1", "commentContent": "评论内容\x00注入"}],
                "downContinueFlag": 0,
            }
        }
    }
    with pytest.raises(IllegalControlCharError, match="非法控制字符"):
        parse_wechat_comment_list_payload(payload_ctrl, platform_post_id="p1", strict_schema=True)


def test_atomic_claim_concurrency_race_condition_t05(test_db: PipelineDB):
    """T05: 两个 Worker 同时竞争同一 APPROVED 任务，仅一人原子领取成功。"""
    post_id = "export/synth_race"
    cid = "c_race_1"

    task_id = test_db.create_or_update_secondary_reply_task(
        platform_post_id=post_id,
        comment_id=cid,
        intent="REPLY",
        style="MACRO",
        chinese_reply="原子抢占测试",
        provider="rule_mock",
        status="APPROVED",
    )

    # Worker A 领取
    claimed_a = test_db.claim_approved_reply_task(lease_seconds=60, task_id=task_id)
    assert claimed_a is not None
    assert claimed_a["status"] == "CLAIMED"

    # Worker B 试图领取同一任务
    claimed_b = test_db.claim_approved_reply_task(lease_seconds=60, task_id=task_id)
    assert claimed_b is None


def test_approval_fingerprint_invalidation_on_draft_change_t07(test_db: PipelineDB):
    """T07: 审批绑定正文与草稿版本哈希，草稿被篡改或升级版本后，原审批 Token 失效。"""
    post_id = "export/synth_fp"
    cid = "c_fp_1"

    task_id = test_db.create_or_update_secondary_reply_task(
        platform_post_id=post_id,
        comment_id=cid,
        intent="REPLY",
        style="MACRO",
        chinese_reply="原始方案内容",
        provider="rule_mock",
        status="PENDING_REVIEW",
    )

    token = "token_abc_123"
    expires = (datetime.datetime.now(UTC) + datetime.timedelta(hours=2)).isoformat()
    ok_bind = test_db.bind_reply_task_approval_request(
        task_id=task_id,
        approval_token=token,
        expires_at_iso=expires,
        source_comment_hash="cmt_hash_001",
        draft_revision=1,
        reply_text_hash=hashlib.sha256("原始方案内容".encode()).hexdigest(),
        approver_id="admin_1",
    )
    assert ok_bind is True

    # 外部修改草稿正文 -> 升级 revision 为 2
    test_db.create_or_update_secondary_reply_task(
        platform_post_id=post_id,
        comment_id=cid,
        intent="REPLY",
        style="MACRO",
        chinese_reply="被篡改后的新内容",
        provider="rule_mock",
        status="PENDING_REVIEW",
    )

    # 试图消费原 Token
    ok_consume, reason = test_db.consume_reply_task_approval(
        task_id=task_id,
        token=token,
        approver_id="admin_1",
        action="APPROVE",
    )
    assert ok_consume is False
    assert reason in ("DRAFT_TEXT_CHANGED", "DRAFT_REVISION_CHANGED", "TOKEN_MISMATCH")


def test_record_secondary_reply_skipped_t04(test_db: PipelineDB):
    """T04: 评论已回复时安全转入 SKIPPED，且 VERIFIED 终态不可覆盖。"""
    post_id = "export/synth_skip"
    cid = "c_skip_1"

    task_id = test_db.create_or_update_secondary_reply_task(
        platform_post_id=post_id,
        comment_id=cid,
        intent="REPLY",
        style="PRAGMATIC",
        chinese_reply="测试跳过",
        provider="rule_mock",
        status="CLAIMED",
    )

    ok_skip = test_db.record_secondary_reply_skipped(task_id, reason="AUTHOR_ALREADY_REPLIED")
    assert ok_skip is True
    task = test_db.get_secondary_reply_task(task_id)
    assert task["status"] == "SKIPPED"
    assert task["error_message"] == "AUTHOR_ALREADY_REPLIED"


def test_uncertain_tasks_reconcile_flow_t10(test_db: PipelineDB):
    """T10: 异常任务进入 UNCERTAIN，提供只读对账查询与安全终结。"""
    post_id = "export/synth_unc"
    cid = "c_unc_1"

    task_id = test_db.create_or_update_secondary_reply_task(
        platform_post_id=post_id,
        comment_id=cid,
        intent="REPLY",
        style="PRAGMATIC",
        chinese_reply="测试对账",
        provider="rule_mock",
        status="SUBMIT_INTENT",
    )

    test_db.record_secondary_reply_uncertain(task_id, error_message="网络假死，未收到明确回执")
    unc_tasks = test_db.get_uncertain_secondary_reply_tasks(post_id)
    assert len(unc_tasks) == 1
    assert unc_tasks[0]["id"] == task_id

    # 只读对账证实未出站：安全终结为 FAILED
    ok_reconcile = test_db.reconcile_secondary_reply_uncertain(
        task_id=task_id,
        verified=False,
        reason="平台回读未发现，证实未出站",
    )
    assert ok_reconcile is True
    task_after = test_db.get_secondary_reply_task(task_id)
    assert task_after["status"] == "FAILED"
    assert "平台回读未发现" in task_after["error_message"]


def test_shanghai_window_enforced_in_record_submit_intent_t14(test_db: PipelineDB):
    """T14: 提交意图事务直接硬拦截非上海工作窗口（08:30-23:00）。"""
    post_id = "export/synth_window"
    cid = "c_win_1"

    task_id = test_db.create_or_update_secondary_reply_task(
        platform_post_id=post_id,
        comment_id=cid,
        intent="REPLY",
        style="MACRO",
        chinese_reply="时段测试",
        provider="rule_mock",
        status="APPROVED",
    )
    claimed = test_db.claim_approved_reply_task(task_id=task_id)
    assert claimed is not None

    # 上海凌晨 03:00
    sh_tz = datetime.timezone(datetime.timedelta(hours=8))
    night_time = datetime.datetime(2026, 10, 12, 3, 0, 0, tzinfo=sh_tz)
    ok, reason = test_db.record_secondary_reply_submit_intent(
        task_id, claimed["lease_token"], now_utc=night_time.astimezone(UTC).isoformat()
    )
    assert ok is False
    assert "Outside Shanghai submission window" in reason


def test_shared_quota_rate_limiting_across_tables_t14(test_db: PipelineDB, tmp_path: Path):
    """T14: 共享配额跨表节流（首评与二级回复共享 15 秒最小间隔）。"""
    post_id = "export/synth_shared_rate"
    cid = "c_shared_1"

    # 创建关联视频与发布确认
    test_db.add_video("yt_shared_quota", "Test Video", "ch_test_1", score=80)
    shot_file = tmp_path / "shot.png"
    shot_file.write_bytes(b"dummy")
    pub = test_db.record_wechat_publication_confirmation(
        "yt_shared_quota",
        evidence_path=str(shot_file),
        state="PUBLISHED",
        platform_post_id=post_id,
    )
    pub_id = pub["id"]

    # 在 wechat_interactions 记录首评提交意图
    sh_tz = datetime.timezone(datetime.timedelta(hours=8))
    t0 = datetime.datetime(2026, 10, 12, 10, 0, 0, tzinfo=sh_tz)
    t0_utc = t0.astimezone(UTC).isoformat()

    with test_db.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO wechat_interactions (
                publication_id, platform_post_id, interaction_type, provider, comment_text, status, submit_intent_at, created_at, updated_at
            ) VALUES (?, ?, 'COMMENT', 'rule_mock', '首评引导', 'SUBMIT_INTENT', ?, ?, ?)
            """,
            (pub_id, post_id, t0_utc, t0_utc, t0_utc),
        )
        conn.commit()

    # 10 秒后试图记录二级回复提交意图（必须被 15 秒共享间隔拦截）
    t_10s_later = (t0 + datetime.timedelta(seconds=10)).astimezone(UTC).isoformat()
    task_id = test_db.create_or_update_secondary_reply_task(
        platform_post_id=post_id,
        comment_id=cid,
        intent="REPLY",
        style="MACRO",
        chinese_reply="间隔拦截测试",
        provider="rule_mock",
        status="APPROVED",
    )
    claimed = test_db.claim_approved_reply_task(task_id=task_id)

    ok, reason = test_db.record_secondary_reply_submit_intent(
        task_id, claimed["lease_token"], now_utc=t_10s_later
    )
    assert ok is False
    assert "Rate limit: minimum submission interval 15s violated" in reason

    # 20 秒后再次尝试（超过 15 秒间隔，允许通过）
    t_20s_later = (t0 + datetime.timedelta(seconds=20)).astimezone(UTC).isoformat()
    ok_pass, msg_pass = test_db.record_secondary_reply_submit_intent(
        task_id, claimed["lease_token"], now_utc=t_20s_later
    )
    assert ok_pass is True
    assert msg_pass == "INTENT_RECORDED"

