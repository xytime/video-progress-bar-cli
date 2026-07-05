# -*- coding: utf-8 -*-
"""字幕翻译候选质量决策兼容门面。

通用质量评估逻辑已下沉到 translation_quality_evaluator。本模块保留字幕侧
既有 import 路径和类名，避免调用方大面积改动。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-05 | Codex  | 初始创建：抽象字幕翻译候选质量决策和审计事件 |
| 1.1.0   | 2026-07-05 | Codex  | 新增质量评估上下文载体，让审核与审计复用全片领域、事实、术语提示 |
| 1.2.0   | 2026-07-05 | Codex  | 合并整片术语一致性检查结果，为后续字幕/标题统一审核预留入口 |
| 1.3.0   | 2026-07-05 | Codex  | 改为 translation_quality_evaluator 的兼容门面，统一字幕/标题/文案审核内核 |
"""

from __future__ import annotations

from typing import Sequence

from .translation_quality_evaluator import (
    TranslationQualityContext,
    TranslationQualityDecision,
    evaluate_translation_candidate,
)


SubtitleTranslationQualityContext = TranslationQualityContext
SubtitleTranslationQualityDecision = TranslationQualityDecision


def evaluate_subtitle_translation_candidate(
    source_texts: Sequence[str],
    translated_texts: Sequence[str],
    *,
    provider: str,
    final_provider: bool,
    context_text: str = "",
    quality_context: SubtitleTranslationQualityContext | None = None,
) -> SubtitleTranslationQualityDecision:
    """评估一个字幕 provider 候选，返回接受/降级/失败决策。"""
    return evaluate_translation_candidate(
        source_texts,
        translated_texts,
        provider=provider,
        final_provider=final_provider,
        context_text=context_text,
        quality_context=quality_context,
    )
