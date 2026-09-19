"""微信视频号评论互动微内核单元测试。

覆盖数据合同校验、自生长策略存储、程序化兜底生成、业务门面、安全审查门禁与 DAL 账本。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-09-19 | Antigravity | 依据 Codex 审查加固：补充审查一票否决、精准状态绑定、无裸 SQL 规范与 dry-run 幂等测试 |
| 1.0.0 | 2026-09-19 | Antigravity | 初始创建：对互动引导各模块进行隔离单元测试 |
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from video_processing.db.database import PipelineDB
from video_processing.interaction.browser_commenter import BrowserCommenter
from video_processing.interaction.contract import (
    CensorshipViolationError,
    InteractionContractError,
    InteractionDraft,
    InteractionType,
    render_interaction_comment,
    validate_interaction_draft,
)
from video_processing.interaction.rule_provider import RuleInteractionProvider
from video_processing.interaction.service import InteractionService
from video_processing.interaction.strategy_store import StrategyStore


def _draft(
    *,
    topic: str = "关于技术迭代的思考，你怎么看？",
    interaction_type: InteractionType = InteractionType.POLL_STAND,
    poll_options: list[str] | None = None,
    share_hook: str = "转发到群聊测测大家态度！",
    provider: str = "test_provider",
    category: str = "General",
) -> InteractionDraft:
    """构造与受控渲染合同一致的测试草稿。"""
    options = poll_options or ["坚定看好", "持保留意见"]
    return InteractionDraft(
        topic=topic,
        interaction_type=interaction_type,
        poll_options=options,
        share_hook=share_hook,
        formatted_comment=render_interaction_comment(
            topic=topic, interaction_type=interaction_type, poll_options=options, share_hook=share_hook
        ),
        provider=provider,
        category=category,
    )


class TestInteractionContract:
    """测试数据合同与校验逻辑。"""

    def test_valid_draft(self):
        draft = validate_interaction_draft(
            topic="关于技术迭代的思考，你怎么看？",
            interaction_type="POLL_STAND",
            poll_options=["坚定看好", "持保留意见"],
            share_hook="转发到群聊测测大家态度！",
            formatted_comment=render_interaction_comment(
                topic="关于技术迭代的思考，你怎么看？",
                interaction_type=InteractionType.POLL_STAND,
                poll_options=["坚定看好", "持保留意见"],
                share_hook="转发到群聊测测大家态度！",
            ),
            provider="test_provider",
            category="Tech",
        )
        assert draft.topic == "关于技术迭代的思考，你怎么看？"
        assert draft.interaction_type == InteractionType.POLL_STAND
        assert len(draft.poll_options) == 2
        assert draft.provider == "test_provider"

    def test_invalid_type_raises(self):
        with pytest.raises(InteractionContractError, match="不支持的互动类型代码"):
            validate_interaction_draft(
                topic="测试",
                interaction_type="INVALID_TYPE",
                poll_options=["A", "B"],
                share_hook="转",
                formatted_comment="一段足够长的测试评论内容，必须大于三十个字以上才可以符合规范！",
                provider="test",
            )

    def test_options_require_two_to_four_items(self):
        with pytest.raises(InteractionContractError, match="投票选项必须为 2-4 项"):
            validate_interaction_draft(
                topic="测试话题",
                interaction_type="POLL_STAND",
                poll_options=["单一选项"],
                share_hook="转给朋友",
                formatted_comment="一段足够长的测试评论内容，必须大于三十个字以上才可以符合规范！",
                provider="test",
            )

    def test_options_required_for_every_interaction_type(self):
        with pytest.raises(InteractionContractError, match="投票选项必须为 2-4 项"):
            validate_interaction_draft(
                topic="测试话题",
                interaction_type="WARNING_SHARE",
                poll_options=[],
                share_hook="转给朋友",
                formatted_comment="太短了",
                provider="test",
            )


class TestStrategyStore:
    """测试自生长策略库、槽位抽象与文件锁。"""

    def test_store_learning_with_slot_abstraction(self, tmp_path: Path):
        store_file = tmp_path / "strategies.json"
        store = StrategyStore(storage_path=store_file)

        draft = _draft(
            topic="针对视频中关于AI智能体的核心思考，你怎么看？",
            interaction_type=InteractionType.POLL_STAND,
            poll_options=["1-2年内普及", "短期不可能"],
            share_hook="转到技术群，测测同行怎么看！",
            provider="agy:test",
            category="AI/Tech",
        )

        # 学习成功，但具体事件只能作为 exemplar，不能提升为跨主题模板。
        learned = store.learn_from_success(draft, "AI智能体")
        assert learned is True
        assert store_file.exists()

        reloaded_store = StrategyStore(storage_path=store_file)
        templates = reloaded_store.get_templates(category="AI/Tech", interaction_type=InteractionType.POLL_STAND)
        assert len(templates) >= 1
        assert not any("核心思考" in t.get("topic_template", "") for t in templates)
        assert reloaded_store._data["learned_exemplars"][-1]["title"] == "AI智能体"

    def test_store_learning_rejects_censorship_violation(self, tmp_path: Path):
        store_file = tmp_path / "strategies.json"
        store = StrategyStore(storage_path=store_file)

        # 包含违禁词的草稿
        bad_draft = _draft(
            topic="关于台独势力的讨论",
            interaction_type=InteractionType.POLL_STAND,
            poll_options=["A", "B"],
            share_hook="转到群聊！",
            provider="agy:test",
            category="General",
        )

        learned = store.learn_from_success(bad_draft, "台独")
        assert learned is False
        # 知识库 exemplars 不得增加
        assert len(store._data.get("learned_exemplars", [])) == 0

    def test_store_learning_without_slot_does_not_pollute_categories(self, tmp_path: Path):
        store_file = tmp_path / "strategies.json"
        store = StrategyStore(storage_path=store_file)

        # 话题无法与标题产生槽位替换（具体事件）
        concrete_draft = _draft(
            topic="具体不可复用的孤立事件讨论，你怎么看？",
            interaction_type=InteractionType.POLL_STAND,
            poll_options=["支持", "反对"],
            share_hook="转给朋友！",
            provider="agy:test",
            category="General",
        )

        learned = store.learn_from_success(concrete_draft, "完全不相关的外部英文标题")
        assert learned is True
        # 不得进入 categories 的通用模板库（因为未生成 {core_subject}）
        templates = store.get_templates(category="General", interaction_type=InteractionType.POLL_STAND)
        assert not any("具体不可复用" in t.get("topic_template", "") for t in templates)


class TestRuleProvider:
    """测试基于自生长知识库的程序化兜底引擎。"""

    def test_rule_generation_warning_type(self):
        provider = RuleInteractionProvider()
        draft = provider.generate(
            title="美联储降息危机与市场风险警惕！",
            description="原油暴跌，通胀高企，面临巨大爆仓风险",
            category="Finance",
        )
        assert draft.interaction_type == InteractionType.WARNING_SHARE
        assert "⚠️" in draft.formatted_comment
        assert "避险" in draft.formatted_comment or "风险" in draft.formatted_comment
        assert draft.provider == "self_growing_rule"

    def test_rule_generation_poll_type(self):
        provider = RuleInteractionProvider()
        draft = provider.generate(
            title="全新大模型技术架构发布与争议",
            description="引发行业关于推理成本与落地的激烈辩论",
            category="General",
        )
        assert "🗳️" in draft.formatted_comment
        assert "🅰️" in draft.formatted_comment
        assert len(draft.poll_options) >= 2


class TestInteractionService:
    """测试业务门面、Fail-Closed 安全审查与降级。"""

    def test_service_agy_success(self):
        mock_agy = MagicMock()
        mock_agy.generate.return_value = _draft(
            topic="AGY测试议题",
            interaction_type=InteractionType.GROUP_DISCUSSION,
            poll_options=["A", "B"],
            share_hook="转到群聊看看！",
            provider="agy:test-model",
            category="General",
        )
        service = InteractionService(agy_provider=mock_agy)
        draft = service.generate_comment(title="测试标题", description="测试描述")

        assert draft.provider == "agy:test-model"
        assert draft.interaction_type == InteractionType.GROUP_DISCUSSION

    def test_service_agy_failure_fallback_to_rule(self):
        mock_agy = MagicMock()
        mock_agy.generate.side_effect = RuntimeError("AGY Timeout")
        service = InteractionService(agy_provider=mock_agy)

        draft = service.generate_comment(title="全球AI前沿峰会发布重磅突破", description="开源模型性能全面对标闭源旗舰")
        assert draft.provider == "self_growing_rule"
        assert len(draft.formatted_comment) > 30

    def test_service_censorship_blocks_sensitive_agy_and_falls_back(self):
        mock_agy = MagicMock()
        # AGY 生成了敏感词“台独”
        mock_agy.generate.return_value = _draft(
            topic="台独势力分析",
            interaction_type=InteractionType.POLL_STAND,
            poll_options=["A", "B"],
            share_hook="转发！",
            provider="agy:test-model",
            category="General",
        )
        service = InteractionService(agy_provider=mock_agy)
        # 应被审查门禁拦截并安全降级到 rule_provider
        draft = service.generate_comment(title="正常财经科技动态", description="正常描述")
        assert draft.provider == "self_growing_rule"
        assert "台独" not in draft.formatted_comment

    def test_service_censorship_fail_closed_raises_when_all_fail(self):
        service = InteractionService()
        # 传入包含极度敏感词的标题，兜底规则也会包含该违规词
        with pytest.raises(CensorshipViolationError, match="未能通过安全审查"):
            service.generate_comment(
                title="支持台独与分裂国家的重要讲话",
                description="涉及政治敏感内容",
                force_rule=True,
            )

    def test_service_censorship_engine_error_fails_closed(self):
        service = InteractionService()
        with patch("video_processing.censor_engine.check_text", side_effect=Exception("Database corrupt")):
            with pytest.raises(CensorshipViolationError):
                service.generate_comment(title="任意标题", description="任意描述", force_rule=True)

    def test_dry_run_does_not_mutate_strategy_store(self, tmp_path: Path):
        store_file = tmp_path / "strategies.json"
        store = StrategyStore(storage_path=store_file)
        assert not store_file.exists()

        service = InteractionService(store=store)
        draft = service.generate_comment(title="测试标题", description="测试描述", force_rule=True)
        assert draft is not None

        # 生成期不初始化或写入运行学习文件。
        assert not store_file.exists()


class TestBrowserCommenter:
    """测试浏览器执行器的前置安全门禁。"""

    def test_missing_platform_post_id_fails_immediately(self):
        commenter = BrowserCommenter()
        status, evidence, error = commenter.post_comment(
            comment_text="测试评论",
            platform_post_id="",
        )
        assert status == "FAILED"
        assert "必须提供有效的 platform_post_id" in (error or "")

    def test_missing_state_file_fails_safely(self, tmp_path: Path):
        commenter = BrowserCommenter(state_path=tmp_path / "non_existent.json")
        status, evidence, error = commenter.post_comment(
            comment_text="测试评论",
            platform_post_id="export/12345",
        )
        assert status == "FAILED"
        assert "登录凭据不存在" in (error or "")


class TestInteractionDAL:
    """测试数据库 DAL 层关于 wechat_interactions 的记录与精准绑定查询（零裸 SQL）。"""

    def test_record_and_get_interaction(self, tmp_path: Path):
        db_path = tmp_path / "test_pipeline.db"
        db = PipelineDB(db_path=str(db_path))

        # 使用 DAL 标准封装添加视频与发布记录
        db.add_video("yt_test_1", "Test Video", "ch_test_1", score=80)
        db.update_video_status("yt_test_1", "PUBLISHED")
        evidence = tmp_path / "evidence.png"
        evidence.write_bytes(b"dummy")

        pub = db.record_wechat_publication_confirmation(
            "yt_test_1",
            evidence_path=str(evidence),
            state="PUBLISHED",
            platform_post_id="export/test_post_123",
        )
        pub_id = pub["id"]
        assert pub_id > 0

        # 记录互动
        row_id = db.record_wechat_interaction(
            publication_id=pub_id,
            platform_post_id="export/test_post_123",
            interaction_type="POLL_STAND",
            provider="agy:gemini-3.7-flash-high",
            comment_text="测试首评内容",
            status="COMMENTED",
            evidence_path="/path/to/shot.png",
            commented_at="2026-09-19T12:00:00Z",
        )
        assert row_id > 0

        # 精确查询单条互动记录
        record = db.get_wechat_interaction_by_post_id("export/test_post_123")
        assert record is not None
        assert record["status"] == "COMMENTED"
        assert record["interaction_type"] == "POLL_STAND"

        # 幂等更新
        db.record_wechat_interaction(
            publication_id=pub_id,
            platform_post_id="export/test_post_123",
            interaction_type="WARNING_SHARE",
            provider="self_growing_rule",
            comment_text="更新后的评论",
            status="SKIPPED_EXISTS",
        )
        record_updated = db.get_wechat_interaction_by_post_id("export/test_post_123")
        # 已确认 COMMENTED 是终态，后来的去重观察不能覆盖原始提交证据。
        assert record_updated["status"] == "COMMENTED"
        assert record_updated["interaction_type"] == "POLL_STAND"

    def test_get_published_wechat_post_strictly_filters_published_state(self, tmp_path: Path):
        db_path = tmp_path / "test_pipeline.db"
        db = PipelineDB(db_path=str(db_path))

        # 视频 1：处于 UNDER_REVIEW，不可用于发评
        db.add_video("yt_under_review", "Under Review Video", "ch_test_1", score=80)
        evidence = tmp_path / "evidence.png"
        evidence.write_bytes(b"dummy")
        db.record_wechat_publication_confirmation(
            "yt_under_review",
            evidence_path=str(evidence),
            state="UNDER_REVIEW",
            platform_post_id="export/post_under_review",
        )

        # 严格限定 PUBLISHED 的 DAL 查询应该返回 None
        target = db.get_published_wechat_post_by_platform_id("export/post_under_review")
        assert target is None

        # 视频 2：处于 PUBLISHED，可正常查出
        db.add_video("yt_published", "Published Video", "ch_test_1", score=80)
        db.record_wechat_publication_confirmation(
            "yt_published",
            evidence_path=str(evidence),
            state="PUBLISHED",
            platform_post_id="export/post_published_ok",
        )

        target_ok = db.get_published_wechat_post_by_platform_id("export/post_published_ok")
        assert target_ok is not None
        assert target_ok["platform_post_id"] == "export/post_published_ok"
        assert target_ok["wechat_state"] == "PUBLISHED"
