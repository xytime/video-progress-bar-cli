# -*- coding: utf-8 -*-
"""翻译自然度守门器。

本模块专注发现“事实没反，但中文明显像逐词直译”的高置信坏味道，
例如把常见英语习语/话语标记机械映射成中文 calque。它不做主观评分，
只输出可用于候选仲裁的 warning。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-06 | Codex  | 初始创建：覆盖财经/新闻常见英语习语的高置信直译腔告警 |
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Sequence

from .translation_quality_guard import QualityIssue


@dataclass(frozen=True)
class _CalqueRule:
    """一条英语习语/话语标记的高置信直译规则。"""

    code: str
    message: str
    source_pattern: re.Pattern[str]
    translation_pattern: re.Pattern[str]
    source_signal: str
    translation_signal: str
    suggested_fix: str


_CALQUE_RULES: Sequence[_CalqueRule] = (
    _CalqueRule(
        code="FLUENCY_LITERAL_CALQUE_RADAR",
        message="译文把英语固定表达机械直译成中文，读起来像翻译腔而非自然中文。",
        source_pattern=re.compile(r"\bon your radar\b", re.IGNORECASE),
        translation_pattern=re.compile(r"在你的雷达上"),
        source_signal="on your radar",
        translation_signal="在你的雷达上",
        suggested_fix="按语境改成“需要重点关注”“纳入观察范围”等自然表达。",
    ),
    _CalqueRule(
        code="FLUENCY_LITERAL_CALQUE_GET_INTO_IT",
        message="译文把英语开场话语标记逐词照搬，中文不自然。",
        source_pattern=re.compile(r"\b(?:let'?s|get)\s+get\s+into\s+it\b", re.IGNORECASE),
        translation_pattern=re.compile(r"进入它"),
        source_signal="let's/get into it",
        translation_signal="进入它",
        suggested_fix="按语境改成“进入正题”“开始分析”“展开说”等自然表达。",
    ),
    _CalqueRule(
        code="FLUENCY_LITERAL_CALQUE_WICKED_STORM",
        message="译文把口语强调词逐词直译，破坏中文自然度。",
        source_pattern=re.compile(r"\bwicked\s+storm\b", re.IGNORECASE),
        translation_pattern=re.compile(r"邪恶的风暴"),
        source_signal="wicked storm",
        translation_signal="邪恶的风暴",
        suggested_fix="按语境改成“猛烈的风暴”“强烈风暴”等自然表达。",
    ),
    _CalqueRule(
        code="FLUENCY_LITERAL_CALQUE_SINGLE_MOST",
        message="译文误把英语强调结构按字面翻成中文，语义明显错位。",
        source_pattern=re.compile(r"\bsingle\s+most\b", re.IGNORECASE),
        translation_pattern=re.compile(r"单身"),
        source_signal="single most",
        translation_signal="单身",
        suggested_fix="按语境改成“最重要的”“影响最大的一项”等自然表达。",
    ),
    _CalqueRule(
        code="FLUENCY_LITERAL_CALQUE_CAUGHT_A_BID",
        message="译文把金融市场习语逐词直译，中文不符合财经表达习惯。",
        source_pattern=re.compile(r"\bcaught\s+a\s+bid\b", re.IGNORECASE),
        translation_pattern=re.compile(r"受到(?:了)?竞标"),
        source_signal="caught a bid",
        translation_signal="受到竞标",
        suggested_fix="按语境改成“获得买盘支撑”“受到追捧”“走强”等自然表达。",
    ),
    _CalqueRule(
        code="FLUENCY_LITERAL_CALQUE_PIVOT",
        message="译文把政策/立场转向类表达机械直译，中文不自然。",
        source_pattern=re.compile(r"\bpivot(?:ing)?\s+outright\b", re.IGNORECASE),
        translation_pattern=re.compile(r"直接旋转"),
        source_signal="pivot outright",
        translation_signal="直接旋转",
        suggested_fix="按语境改成“彻底转向”“明确转鸽”“立场明显转变”等自然表达。",
    ),
)


def evaluate_translation_fluency(
    source_texts: Sequence[str],
    translated_texts: Sequence[str],
) -> List[QualityIssue]:
    """发现高置信直译腔 warning。"""
    issues: List[QualityIssue] = []
    seen_codes: set[tuple[str, str]] = set()

    for source_text, translated_text in zip(source_texts, translated_texts):
        source = (source_text or "").strip()
        translated = (translated_text or "").strip()
        if not source or not translated:
            continue
        for rule in _CALQUE_RULES:
            if not rule.source_pattern.search(source):
                continue
            if not rule.translation_pattern.search(translated):
                continue
            dedupe_key = (rule.code, rule.translation_signal)
            if dedupe_key in seen_codes:
                continue
            seen_codes.add(dedupe_key)
            issues.append(
                QualityIssue(
                    severity="P2",
                    code=rule.code,
                    message=rule.message,
                    source_signal=rule.source_signal,
                    translation_signal=rule.translation_signal,
                    suggested_fix=rule.suggested_fix,
                )
            )
    return issues
