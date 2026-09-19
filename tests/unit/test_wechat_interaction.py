"""微信视频号评论互动微内核单元测试。

覆盖数据合同校验、自生长策略存储、程序化兜底生成、业务门面及 DAL 账本。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-19 | Antigravity | 初始创建：对互动引导各模块进行隔离单元测试 |
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from video_processing.db.database import PipelineDB
from video_processing.interaction.contract import (
    InteractionContractError,
    InteractionDraft,
    InteractionType,
    validate_interaction_draft,
)
from video_processing.interaction.rule_provider import RuleInteractionProvider
from video_processing.interaction.service import InteractionService
from video_processing.interaction.strategy_store import StrategyStore


class TestInteractionContract:
    """测试数据合同与校验逻辑。"""

    def test_valid_draft(self):
        draft = validate_interaction_draft(
            topic="白宫拉黑特定媒体，你怎么看？",
            interaction_type="POLL_STAND",
            poll_options=["赞同总统", "捍卫媒体"],
            share_hook="转发到群聊测测大家态度！",
            formatted_comment="📌【今日互动】白宫拉黑特定媒体\n🗳️【立场站队】\n🅰️ 赞同总统\n🅱️ 捍卫媒体\n📢 转发到群聊！",
            provider="test_provider",
            category="Politics",
        )
        assert draft.topic == "白宫拉黑特定媒体，你怎么看？"
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

    def test_poll_stand_requires_options(self):
        with pytest.raises(InteractionContractError, match="投票型互动必须提供至少 2 个有效选项"):
            validate_interaction_draft(
                topic="测试话题",
                interaction_type="POLL_STAND",
                poll_options=["单一选项"],
                share_hook="转给朋友",
                formatted_comment="一段足够长的测试评论内容，必须大于三十个字以上才可以符合规范！",
                provider="test",
            )

    def test_too_short_comment_raises(self):
        with pytest.raises(InteractionContractError, match="排版评论过短"):
            validate_interaction_draft(
                topic="测试话题",
                interaction_type="WARNING_SHARE",
                poll_options=[],
                share_hook="转给朋友",
                formatted_comment="太短了",
                provider="test",
            )


class TestStrategyStore:
    """测试自生长策略库与经验沉淀。"""

    def test_store_learning_and_evolution(self, tmp_path: Path):
        store_file = tmp_path / "strategies.json"
        store = StrategyStore(storage_path=store_file)

        draft = InteractionDraft(
            topic="AI取代程序员真的会发生吗？",
            interaction_type=InteractionType.POLL_STAND,
            poll_options=["1-2年内普及", "短期不可能"],
            share_hook="转到技术群，测测同行怎么看！",
            formatted_comment="📌【互动】AI取代程序员真的会发生吗？\n🗳️【投票】\n🅰️ 1-2年内普及\n🅱️ 短期不可能\n📢 转到技术群！",
            provider="agy:test",
            category="AI/Tech",
        )

        # 沉淀经验
        store.learn_from_success(draft, "AI取代程序员真的会发生吗？")

        # 重新加载验证
        reloaded_store = StrategyStore(storage_path=store_file)
        templates = reloaded_store.get_templates(category="AI/Tech", interaction_type=InteractionType.POLL_STAND)
        assert len(templates) >= 1
        assert any("技术群" in t.get("share_hook", "") for t in templates)


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
            title="特朗普宣布白宫媒体准入禁令",
            description="引发第一修正案与权力边界激烈辩论",
            category="General",
        )
        assert "🗳️" in draft.formatted_comment
        assert "🅰️" in draft.formatted_comment
        assert len(draft.poll_options) >= 2


class TestInteractionService:
    """测试业务门面及 AGY -> 兜底降级。"""

    def test_service_agy_success(self):
        mock_agy = MagicMock()
        mock_agy.generate.return_value = InteractionDraft(
            topic="AGY测试议题",
            interaction_type=InteractionType.GROUP_DISCUSSION,
            poll_options=["A", "B"],
            share_hook="转到群聊看看！",
            formatted_comment="📌【议题】AGY测试议题\n🗳️ 站队：A 或 B\n📢 转到群聊看看！这是一段合规且足够长度的有效评论文字。",
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

        # 此时应当自动降级为 rule_provider
        draft = service.generate_comment(title="全球AI前沿峰会发布重磅突破", description="开源模型性能全面对标闭源旗舰")
        assert draft.provider == "self_growing_rule"
        assert len(draft.formatted_comment) > 30


class TestInteractionDAL:
    """测试数据库 DAL 层关于 wechat_interactions 的记录与查询。"""

    def test_record_and_get_interaction(self, tmp_path: Path):
        db_path = tmp_path / "test_pipeline.db"
        db = PipelineDB(db_path=str(db_path))

        # 插入前置 processed_videos 和 wechat_publications
        with db.get_connection() as conn:
            conn.execute(
                "INSERT INTO processed_videos (youtube_id, slice_index, title, channel_id, status) VALUES ('yt_test_1', 0, 'Test Video', 'ch_test_1', 'PUBLISHED')"
            )
            vid = conn.execute("SELECT id FROM processed_videos WHERE youtube_id = 'yt_test_1'").fetchone()[0]
            subj_id = f"video:{vid}"
            conn.execute(
                "INSERT INTO publication_subjects (id, kind, video_id) VALUES (?, 'VIDEO_ITEM', ?)",
                (subj_id, vid)
            )
            conn.execute(
                "INSERT INTO wechat_publications (video_id, subject_id, state, platform_post_id) VALUES (?, ?, 'PUBLISHED', 'export/test_post_123')",
                (vid, subj_id)
            )
            pub_id = conn.execute("SELECT id FROM wechat_publications WHERE video_id = ?", (vid,)).fetchone()[0]
            conn.commit()

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

            # 查询单条
            record = db.get_wechat_interaction_by_post_id("export/test_post_123")
            assert record is not None
            assert record["status"] == "COMMENTED"
            assert record["interaction_type"] == "POLL_STAND"

            # 再次插入应幂等更新
            db.record_wechat_interaction(
                publication_id=pub_id,
                platform_post_id="export/test_post_123",
                interaction_type="WARNING_SHARE",
                provider="self_growing_rule",
                comment_text="更新后的评论",
                status="SKIPPED_EXISTS",
            )
            record_updated = db.get_wechat_interaction_by_post_id("export/test_post_123")
            assert record_updated["status"] == "SKIPPED_EXISTS"
            assert record_updated["interaction_type"] == "WARNING_SHARE"
