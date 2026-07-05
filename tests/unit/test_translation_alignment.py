"""字幕翻译对齐 (BUG-4) 单元测试

锁定：批量翻译绝不再因「少返一段 / 分隔符错位 / 超长截断」而整体串位。

1. vocab_helper._parse_response —— 按 id 重对齐：
   - 漏返中间某段 → 该 id 槽位留空，其余位置不偏移
   - 乱序返回 → 仍按 id 归位
   - 无 id 且数量不符 → 判失败(None)，绝不补空错位
2. translation_helper._split_by_char_budget —— 按字数切子块，单行超预算独占一组
   （配合「split 段数须与输入严格相等才回写」共同杜绝错位/丢行）

均为纯函数，无 API 调用。

# Modification History
| Version | Date       | Author          | Description                          |
|---------|------------|-----------------|--------------------------------------|
| 1.0.0   | 2026-06-15 | Claude_Opus_4.8 | 初始创建：锁定 BUG-4 翻译 id 对齐 + 字数切块行为 |
| 1.1.0   | 2026-07-05 | Codex           | 增加 vocab_helper prompt 上下文注入回归测试 |
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from video_processing.utils.vocab_helper import _build_prompt, _parse_response
from video_processing.utils.translation_helper import _split_by_char_budget, _SEP


def _item(i, tr):
    return {"id": i, "translation": tr, "vocab": {}}


# ── 1. id 重对齐 ────────────────────────────────────────────────────────────
class TestParseResponseIdAlignment:
    def test_exact_with_ids(self):
        text = json.dumps([_item(0, "零"), _item(1, "一"), _item(2, "二")])
        out = _parse_response(text, 3)
        assert [o["translation"] for o in out] == ["零", "一", "二"]

    def test_missing_middle_segment_leaves_empty_no_shift(self):
        # 模型漏返 id=1：旧实现会把后面整体前移；新实现 id=1 留空，id=2 仍在位
        text = json.dumps([_item(0, "零"), _item(2, "二")])
        out = _parse_response(text, 3)
        assert [o["translation"] for o in out] == ["零", "", "二"]

    def test_out_of_order_ids_are_repositioned(self):
        text = json.dumps([_item(2, "二"), _item(0, "零"), _item(1, "一")])
        out = _parse_response(text, 3)
        assert [o["translation"] for o in out] == ["零", "一", "二"]

    def test_too_few_aligned_items_discarded(self):
        # 仅 1/5 命中 (<80%) → 判失败，交由上层 fallback
        text = json.dumps([_item(0, "零")])
        assert _parse_response(text, 5) is None

    def test_no_id_count_mismatch_discarded(self):
        # 无 id 且数量不符 → 必须判失败，绝不补空错位（这正是旧 BUG）
        text = json.dumps([{"translation": "零", "vocab": {}},
                           {"translation": "一", "vocab": {}}])
        assert _parse_response(text, 3) is None

    def test_no_id_exact_count_positional_ok(self):
        # 无 id 但数量完全一致 → 安全顺序映射
        text = json.dumps([{"translation": "零", "vocab": {}},
                           {"translation": "一", "vocab": {}}])
        out = _parse_response(text, 2)
        assert [o["translation"] for o in out] == ["零", "一"]

    def test_bool_id_not_treated_as_index(self):
        # True 是 int 子类，不能被当作 id=1
        text = json.dumps([{"id": True, "translation": "x", "vocab": {}},
                           {"translation": "y", "vocab": {}}])
        # 无有效 id → 走无-id 分支，数量(2)==expected(2) → 顺序映射
        out = _parse_response(text, 2)
        assert [o["translation"] for o in out] == ["x", "y"]


# ── 2. 字数切块 ─────────────────────────────────────────────────────────────
class TestSplitByCharBudget:
    def test_all_fit_single_group(self):
        texts = ["aaa", "bbb", "ccc"]
        groups = _split_by_char_budget([0, 1, 2], texts, max_chars=1000)
        assert groups == [[0, 1, 2]]

    def test_splits_when_over_budget(self):
        # 每段 100 字，预算 250；含分隔符后每组最多 2 段
        texts = ["x" * 100, "x" * 100, "x" * 100, "x" * 100]
        groups = _split_by_char_budget([0, 1, 2, 3], texts, max_chars=250)
        # 不丢任何下标，且每组拼接后不超预算
        flat = [i for g in groups for i in g]
        assert sorted(flat) == [0, 1, 2, 3]
        for g in groups:
            joined = _SEP.join(texts[i] for i in g)
            assert len(joined) <= 250 or len(g) == 1

    def test_oversize_single_line_isolated(self):
        texts = ["short", "y" * 9000, "short2"]
        groups = _split_by_char_budget([0, 1, 2], texts, max_chars=5000)
        flat = [i for g in groups for i in g]
        assert sorted(flat) == [0, 1, 2]          # 不丢行
        assert [1] in groups                       # 超长行独占一组（兜底）

    def test_empty(self):
        assert _split_by_char_budget([], [], max_chars=5000) == []


# ── 3. 全片上下文注入 ───────────────────────────────────────────────────────
class TestVocabPromptContext:
    def test_translation_prompt_includes_global_context(self):
        prompt = _build_prompt(
            ["MGX announced the final close of Fund I."],
            None,
            context_text="Domain note: final close means 完成募集, not withdrawal.",
        )

        assert "global context" in prompt.lower()
        assert "完成募集" in prompt
        assert "not withdrawal" in prompt

    def test_alignment_prompt_includes_context_without_changing_chinese(self):
        prompt = _build_prompt(
            ["MGX announced the final close of Fund I."],
            ["MGX宣布一期基金完成募集。"],
            context_text="Use fund context.",
        )

        assert "Use fund context" in prompt
        assert "DO NOT change it" in prompt
        assert "MGX宣布一期基金完成募集。" in prompt
