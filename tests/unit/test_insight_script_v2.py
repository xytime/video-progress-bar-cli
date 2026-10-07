"""InsightScriptV2 数据契约与 DAL enrichment_status 状态机单元测试 (RFC-2026-DEEP-CREATION-001)。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-08 | Antigravity | 覆盖 V2 Pydantic 模型、JSON Schema、边界时序校验、适配器及 DAL 状态更新 |
"""
import copy
import jsonschema
import pytest
from pydantic import ValidationError

from video_processing.core.insight_script import InsightScriptV2, InsightScript
from video_processing.utils.insight_v2_prompt import (
    INSIGHT_SCRIPT_V2_JSON_SCHEMA,
    FEW_SHOT_EXAMPLE_CORNELL,
    FEW_SHOT_EXAMPLE_NOBEL,
)


class TestInsightScriptV2:
    def test_valid_benchmark_examples(self):
        """标杆案例通过 Pydantic v2 与 Draft-07 Schema 双重严格校验。"""
        # Pydantic 校验
        m_cornell = InsightScriptV2.model_validate(FEW_SHOT_EXAMPLE_CORNELL)
        assert m_cornell.video_id == "SfNypZIb0H4"
        assert m_cornell.preserve_full_body is True
        assert len(m_cornell.cards) == 2

        m_nobel = InsightScriptV2.model_validate(FEW_SHOT_EXAMPLE_NOBEL)
        assert m_nobel.video_id == "RaUWCtcJtK8"
        assert m_nobel.preserve_full_body is True
        assert len(m_nobel.cards) == 2

        # JSON Schema Draft-07 校验
        validator = jsonschema.Draft7Validator(INSIGHT_SCRIPT_V2_JSON_SCHEMA)
        assert list(validator.iter_errors(FEW_SHOT_EXAMPLE_CORNELL)) == []
        assert list(validator.iter_errors(FEW_SHOT_EXAMPLE_NOBEL)) == []

    def test_review_text_contains_all_critical_copy(self):
        """review_text() 必须提取全部新增口播、卡片正文及尾部思辨议题送审风控。"""
        m = InsightScriptV2.model_validate(FEW_SHOT_EXAMPLE_CORNELL)
        reviewed = m.review_text()
        assert m.headline in reviewed
        assert m.hook.title in reviewed
        assert m.hook.narration in reviewed
        for card in m.cards:
            assert card.badge in reviewed
            assert card.title in reviewed
            for p in card.points:
                assert p.keyword in reviewed
                assert p.explanation in reviewed
        assert m.outro.philosophical_quote in reviewed
        assert m.outro.reflection_question in reviewed
        for opt in m.outro.poll_options:
            assert opt in reviewed

    def test_to_legacy_v1_compatibility_adapter(self):
        """V2 模型可通过 to_legacy_v1 转换为旧版 InsightScript 并保持零裁切。"""
        m = InsightScriptV2.model_validate(FEW_SHOT_EXAMPLE_CORNELL)
        legacy = m.to_legacy_v1(body_duration=180.0)
        assert isinstance(legacy, InsightScript)
        assert legacy.hook_title == m.hook.title
        assert legacy.highlight_window.start_sec == 0.0
        assert legacy.highlight_window.end_sec == 180.0
        assert len(legacy.context_cards) == 2
        assert legacy.context_cards[0].badge == m.cards[0].badge
        assert legacy.closing_takeaway.quote == m.outro.philosophical_quote

    def test_card_timeline_overlap_rejected(self):
        """卡片时序重叠或倒流时必须被 Pydantic 校验拦截。"""
        bad = copy.deepcopy(FEW_SHOT_EXAMPLE_CORNELL)
        # 将第二张卡提前到第一张卡结束前 (40.0 < 44.0 重叠，跨度 25s 合法)
        bad["cards"][1]["start_sec"] = 40.0
        bad["cards"][1]["end_sec"] = 65.0
        with pytest.raises(ValidationError, match="卡片时序不可重叠或倒流"):
            InsightScriptV2.model_validate(bad)

    def test_card_duration_boundary_rejected(self):
        """卡片展示时间小于 5s 或大于 45s 时必须被拦截。"""
        too_short = copy.deepcopy(FEW_SHOT_EXAMPLE_CORNELL)
        too_short["cards"][0]["start_sec"] = 22.0
        too_short["cards"][0]["end_sec"] = 24.0  # 仅 2s
        with pytest.raises(ValidationError, match="卡片展示时间跨度必须在 5~45 秒之间"):
            InsightScriptV2.model_validate(too_short)

        too_long = copy.deepcopy(FEW_SHOT_EXAMPLE_CORNELL)
        too_long["cards"][0]["start_sec"] = 10.0
        too_long["cards"][0]["end_sec"] = 60.0  # 50s
        with pytest.raises(ValidationError, match="卡片展示时间跨度必须在 5~45 秒之间"):
            InsightScriptV2.model_validate(too_long)

    def test_vtt_reference_reversed_time_rejected(self):
        """引证结束时间不可早于开始时间。"""
        bad = copy.deepcopy(FEW_SHOT_EXAMPLE_CORNELL)
        bad["cards"][0]["points"][0]["vtt_reference"]["start_sec"] = 10.0
        bad["cards"][0]["points"][0]["vtt_reference"]["end_sec"] = 5.0
        with pytest.raises(ValidationError, match="引证结束时间不可早于开始时间"):
            InsightScriptV2.model_validate(bad)

    def test_additional_fields_forbidden(self):
        """严格禁止多余注入字段 (extra='forbid')。"""
        bad = copy.deepcopy(FEW_SHOT_EXAMPLE_CORNELL)
        bad["malicious_field"] = "injection"
        with pytest.raises(ValidationError):
            InsightScriptV2.model_validate(bad)


class TestDatabaseEnrichmentStatus:
    def test_database_enrichment_status_dal(self, tmp_path):
        """验证 PipelineDB 对 enrichment_status 的读写与默认状态。"""
        from video_processing.db.database import PipelineDB
        db_file = tmp_path / "test_pipeline.db"
        db = PipelineDB(db_file)

        # 插入测试视频
        yid = "TestEnrich01"
        with db.get_connection() as conn:
            conn.execute(
                "INSERT INTO processed_videos (youtube_id, slice_index, title, channel_id, status) "
                "VALUES (?, 0, 'Test Video', 'channel_1', 'PENDING')",
                (yid,)
            )
            conn.commit()

        # 初始默认状态必须是 NONE
        assert db.get_enrichment_status(yid, slice_index=0) == "NONE"

        # 更新为 ENRICHED
        ok = db.update_enrichment_status(yid, "ENRICHED", slice_index=0)
        assert ok is True
        assert db.get_enrichment_status(yid, slice_index=0) == "ENRICHED"

        # 更新为 DEGRADED
        ok = db.update_enrichment_status(yid, "DEGRADED", slice_index=0)
        assert ok is True
        assert db.get_enrichment_status(yid, slice_index=0) == "DEGRADED"

        # 未知视频返回 NONE
        assert db.get_enrichment_status("NonExistentVideo", slice_index=0) == "NONE"
