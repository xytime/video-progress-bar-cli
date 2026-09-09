# -*- coding: utf-8 -*-
"""翻译生产提示词硬约束。

集中维护 LLM 翻译 provider 共享的事实保真约束，避免 Gemini、DeepSeek
等生产提示词各自演化导致规则漂移。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-06 | Codex  | 初始创建：统一渲染全局上下文与金融翻译硬约束 |
| 1.1.0   | 2026-07-06 | Codex  | 支持按调用场景关闭字幕段落顺序约束，便于文案链路复用 |
| 1.2.0   | 2026-09-09 | Codex  | 强调每段时间槽与语义归属，禁止跨段搬移译文与承接占位符 |
"""

from __future__ import annotations


def render_translation_constraints(
    context_text: str = "",
    *,
    include_subtitle_segment_rule: bool = True,
) -> str:
    """渲染可注入 LLM prompt 的通用翻译硬约束。"""
    lines = [
        "Treat the global context as hard constraints for every segment.",
        "The global context is more authoritative than isolated word senses, but do not invent facts beyond it.",
        "Preserve event direction, entity names, money flow, and numeric magnitude.",
        (
            "For private funds, close/final close usually means 完成募集/最终关账, "
            "not 退出、撤退、关闭、清盘 or liquidation."
        ),
        (
            "Preserve USD magnitude exactly: billion/bn = 十亿美元 = 10亿美元, "
            "million/mn = 百万美元, trillion/tn = 万亿美元."
        ),
    ]
    if include_subtitle_segment_rule:
        lines.append("Do not merge, split, omit, or reorder subtitle segments.")
        lines.append(
            "Each segment owns its original time slot: translate only the words in that segment. "
            "Use context to interpret fragments, never move a later segment's meaning into an earlier slot. "
            "Preserve every segment id; never fill a slot with 承接上文, 同上, or any continuation placeholder."
        )
    rendered = "\n".join(lines)
    if context_text and context_text.strip():
        rendered = f"{rendered}\nGlobal context:\n{context_text.strip()}"
    return rendered
