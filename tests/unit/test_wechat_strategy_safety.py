"""互动策略存储的并发、损坏隔离与跨主题安全测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-09-20 | Codex | 覆盖短模板下结构化生成失败后，危险兜底正文仍不能越过审查门禁。 |
| 1.0.0 | 2026-09-19 | Codex | 验证无写生成、锁定事务、原子失败与结构化 AGY 合同 |
"""

from __future__ import annotations

import json
import multiprocessing
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from video_processing.interaction.agy_provider import AgyInteractionError, AgyInteractionProvider
from video_processing.interaction.contract import (
    CensorshipViolationError,
    InteractionDraft,
    InteractionType,
    render_interaction_comment,
)
from video_processing.interaction.rule_provider import RuleInteractionProvider
from video_processing.interaction.service import InteractionService
from video_processing.interaction.strategy_store import StrategyStore


def _draft(subject: str, *, category: str = "General") -> InteractionDraft:
    options = ["认同这个方向", "还想继续观察"]
    hook = "说说原因。"
    topic = f"关于{subject}，你怎么看？"
    return InteractionDraft(
        topic=topic,
        interaction_type=InteractionType.POLL_STAND,
        poll_options=options,
        share_hook=hook,
        formatted_comment=render_interaction_comment(
            topic=topic,
            interaction_type=InteractionType.POLL_STAND,
            poll_options=options,
            share_hook=hook,
        ),
        provider="test",
        category=category,
    )


def _learn_in_child(storage_path: str, subject: str) -> None:
    """spawn 子进程入口：真实调用同一运行文件的读改写事务。"""
    assert StrategyStore(storage_path=storage_path).learn_from_success(_draft(subject), subject)


class TestStrategyStoreSafety:
    def test_constructor_and_generation_never_create_learning_file(self, tmp_path: Path) -> None:
        runtime_path = tmp_path / "runtime.json"
        store = StrategyStore(storage_path=runtime_path)
        assert not runtime_path.exists()

        draft = RuleInteractionProvider(store=store).generate(
            title="花园番茄的修剪方法", description="分步讲解日常养护", category="Garden"
        )
        assert draft.formatted_comment
        assert not runtime_path.exists()

    def test_concurrent_learning_keeps_every_successful_update(self, tmp_path: Path) -> None:
        runtime_path = tmp_path / "runtime.json"
        subjects = [f"并发主题{index}" for index in range(6)]
        context = multiprocessing.get_context("spawn")
        workers = [context.Process(target=_learn_in_child, args=(str(runtime_path), subject)) for subject in subjects]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=15)
            assert worker.exitcode == 0

        stored = json.loads(runtime_path.read_text(encoding="utf-8"))
        assert {item["title"] for item in stored["learned_exemplars"]} == set(subjects)

    def test_atomic_replace_failure_preserves_previous_valid_file(self, tmp_path: Path) -> None:
        runtime_path = tmp_path / "runtime.json"
        store = StrategyStore(storage_path=runtime_path)
        assert store.learn_from_success(_draft("初始主题"), "初始主题")
        before = runtime_path.read_text(encoding="utf-8")

        with patch("video_processing.interaction.strategy_store.os.replace", side_effect=OSError("simulated crash")):
            assert not store.learn_from_success(_draft("失败主题"), "失败主题")

        assert runtime_path.read_text(encoding="utf-8") == before
        assert json.loads(before)["learned_exemplars"][-1]["title"] == "初始主题"

    def test_corrupt_runtime_is_never_silently_replaced(self, tmp_path: Path) -> None:
        runtime_path = tmp_path / "runtime.json"
        corrupt = "{ definitely not json"
        runtime_path.write_text(corrupt, encoding="utf-8")
        store = StrategyStore(storage_path=runtime_path)

        assert not store.learn_from_success(_draft("不能覆盖"), "不能覆盖")
        assert runtime_path.read_text(encoding="utf-8") == corrupt

    def test_concrete_garden_exemplar_never_changes_math_fallback(self, tmp_path: Path) -> None:
        runtime_path = tmp_path / "runtime.json"
        store = StrategyStore(storage_path=runtime_path)
        assert store.learn_from_success(_draft("番茄白粉病", category="Garden"), "番茄白粉病")

        math_draft = RuleInteractionProvider(store=StrategyStore(storage_path=runtime_path)).generate(
            title="数学证明的常见思路", description="步骤拆解与复盘", category="Education"
        )
        assert "番茄" not in math_draft.formatted_comment
        assert "白粉病" not in math_draft.formatted_comment
        assert len(store._data["categories"].get("Garden", [])) == 0


class TestAgyStructuredSafety:
    def test_valid_structured_output_is_host_rendered(self) -> None:
        payload = {
            "topic": "关于模型推理成本的讨论，你怎么看？",
            "interaction_type": "POLL_STAND",
            "poll_options": ["优先控制成本", "优先追求能力"],
            "share_hook": "转到技术群，听听大家的取舍。",
        }
        with patch("video_processing.interaction.agy_provider.run_agy_structured", return_value=payload):
            draft = AgyInteractionProvider().generate(title="测试", description="测试")
        assert draft.formatted_comment == render_interaction_comment(
            topic=payload["topic"], interaction_type=InteractionType.POLL_STAND,
            poll_options=payload["poll_options"], share_hook=payload["share_hook"],
        )

    @pytest.mark.parametrize("payload", [
        {"topic": "话题", "interaction_type": "POLL_STAND", "poll_options": ["A", "B"], "share_hook": "引导", "formatted_comment": "伪造"},
        {"topic": "话题", "interaction_type": "POLL_STAND", "poll_options": ["A", {"bad": "type"}], "share_hook": "引导"},
        {"topic": "话题", "interaction_type": "POLL_STAND", "poll_options": ["A", "B", "C", "D", "E"], "share_hook": "引导"},
        {"topic": "  ", "interaction_type": "POLL_STAND", "poll_options": ["A", "B"], "share_hook": "引导"},
    ])
    def test_extra_or_wrong_typed_agy_fields_are_rejected(self, payload: dict) -> None:
        with patch("video_processing.interaction.agy_provider.run_agy_structured", return_value=payload), patch(
            "video_processing.interaction.agy_provider.time.sleep"
        ):
            with pytest.raises(AgyInteractionError):
                AgyInteractionProvider().generate(title="测试", description="测试")

    def test_malformed_agy_output_cannot_bypass_censorship_fallback(self) -> None:
        malformed = {"topic": "话题", "interaction_type": "POLL_STAND", "poll_options": ["A"], "share_hook": "引导"}
        rule_provider = MagicMock()
        rule_provider.generate.return_value = _draft("支持台独的重要讲话")
        service = InteractionService(agy_provider=AgyInteractionProvider(), rule_provider=rule_provider)
        with patch("video_processing.interaction.agy_provider.run_agy_structured", return_value=malformed), patch(
            "video_processing.interaction.agy_provider.time.sleep"
        ):
            with pytest.raises(CensorshipViolationError, match="未能通过安全审查"):
                service.generate_comment(title="普通标题", description="普通描述")
