# -*- coding: utf-8 -*-
"""翻译一致性守门器。

本模块做整片级一致性检查：同一源事实或领域术语在字幕候选中不应前后漂移。
它不调用翻译 API，不写文件，只输出可并入质量审计的 QualityIssue。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-05 | Codex  | 初始创建：检查金融 close/oversubscribe 术语在整片译文中的一致性风险 |
| 1.1.0   | 2026-07-05 | Codex  | 新增金额单位漂移 consistency warning，捕捉同一候选中正确金额与十倍级错译并存 |
| 1.2.0   | 2026-07-06 | Codex  | 新增受保护英文实体整片丢失 warning，减少组织/产品名漂移 |
| 1.3.0   | 2026-07-13 | Codex  | 数字检查开关同时覆盖整片金额单位漂移规则 |
"""

from __future__ import annotations

import re
from typing import List, Sequence

from .translation_entity_guard import find_missing_protected_entities
from .translation_quality_guard import QualityIssue, extract_fact_signal


_SOURCE_FUND_CLOSE_PATTERNS: Sequence[re.Pattern[str]] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bfinal\s+close\b",
        r"\bfirst\s+close\b",
        r"\bclosed\s+(?:its\s+)?(?:fund|fund\s+[ivx]+)\b",
        r"\bfund\s+(?:[ivx]+\s+)?(?:closed|closing)\b",
        r"\bover[-\s]?subscribed\b",
        r"\bexceed(?:ed|s|ing)\s+(?:its\s+)?(?:initial\s+)?target\b",
    )
)

_ZH_FUNDRAISING_TERMS: Sequence[re.Pattern[str]] = tuple(
    re.compile(pattern)
    for pattern in (
        r"募集",
        r"募资",
        r"最终关账",
        r"完成.*关账",
        r"超募",
        r"超过.*目标",
    )
)

_ZH_AMBIGUOUS_OR_WRONG_CLOSE_TERMS: Sequence[re.Pattern[str]] = tuple(
    re.compile(pattern)
    for pattern in (
        r"基金.*关闭",
        r"关闭.*基金",
        r"已以.*关闭",
        r"撤退",
        r"撤出",
        r"退出市场",
        r"离场",
        r"清盘",
    )
)


def evaluate_translation_consistency(
    source_texts: Sequence[str],
    translated_texts: Sequence[str],
    *,
    protected_entities: Sequence[str] | None = None,
    enable_numeric_checks: bool = True,
) -> List[QualityIssue]:
    """检查整片候选译文的一致性风险。"""
    issues: List[QualityIssue] = []
    _append_fund_close_consistency_issue(issues, source_texts, translated_texts)
    if enable_numeric_checks:
        _append_amount_consistency_issue(issues, source_texts, translated_texts)
    _append_entity_consistency_issue(issues, source_texts, translated_texts, protected_entities)
    return issues


def _append_fund_close_consistency_issue(
    issues: List[QualityIssue],
    source_texts: Sequence[str],
    translated_texts: Sequence[str],
) -> None:
    relevant_indexes = [
        idx
        for idx, source in enumerate(source_texts)
        if _any_match(_SOURCE_FUND_CLOSE_PATTERNS, source)
    ]
    if not relevant_indexes:
        return

    good_indexes = [
        idx
        for idx in relevant_indexes
        if idx < len(translated_texts) and _any_match(_ZH_FUNDRAISING_TERMS, translated_texts[idx])
    ]
    bad_indexes = [
        idx
        for idx in relevant_indexes
        if idx < len(translated_texts) and _any_match(_ZH_AMBIGUOUS_OR_WRONG_CLOSE_TERMS, translated_texts[idx])
    ]

    if not good_indexes or not bad_indexes:
        return

    issues.append(
        QualityIssue(
            severity="P1",
            code="TERM_CONSISTENCY_FUND_CLOSE_DRIFT",
            message=(
                "同一基金 close/oversubscription 语境在译文中同时出现募集/关账与关闭/退出类表达，"
                "存在术语漂移风险。"
            ),
            source_signal=f"fund_close_indexes={relevant_indexes[:8]}",
            translation_signal=f"fundraising_indexes={good_indexes[:8]}; ambiguous_or_wrong_indexes={bad_indexes[:8]}",
            suggested_fix="统一译为完成募集/最终关账/超募，避免关闭、撤退、退出市场等表达。",
        )
    )


def _any_match(patterns: Sequence[re.Pattern[str]], text: str) -> bool:
    return any(pattern.search(text or "") for pattern in patterns)


def _append_amount_consistency_issue(
    issues: List[QualityIssue],
    source_texts: Sequence[str],
    translated_texts: Sequence[str],
) -> None:
    source_amounts = _unique_amounts(
        amount
        for text in source_texts
        for amount in extract_fact_signal(text, lang="en").amounts_usd
    )
    translated_amounts = _unique_amounts(
        amount
        for text in translated_texts
        for amount in extract_fact_signal(text, lang="zh").amounts_usd
    )
    if not source_amounts or len(translated_amounts) < 2:
        return

    for source_amount in source_amounts:
        close_matches = [
            amount for amount in translated_amounts
            if _ratio(source_amount, amount) < 2
        ]
        drift_matches = [
            amount for amount in translated_amounts
            if _ratio(source_amount, amount) >= 10
        ]
        if not close_matches or not drift_matches:
            continue

        issues.append(
            QualityIssue(
                severity="P1",
                code="AMOUNT_CONSISTENCY_UNIT_DRIFT",
                message="同一候选中既出现接近原文的金额，也出现相差十倍以上的金额，存在单位漂移风险。",
                source_signal=_format_amounts([source_amount]),
                translation_signal=(
                    f"close={_format_amounts(close_matches[:4])}; "
                    f"drift={_format_amounts(drift_matches[:4])}"
                ),
                suggested_fix="统一核对 billion/million/trillion 与 亿/万亿/万美元 的转换，删除或修正漂移金额。",
            )
        )
        return


def _append_entity_consistency_issue(
    issues: List[QualityIssue],
    source_texts: Sequence[str],
    translated_texts: Sequence[str],
    protected_entities: Sequence[str] | None,
) -> None:
    missing_entities = find_missing_protected_entities(
        source_texts,
        translated_texts,
        protected_entities=protected_entities,
    )
    if not missing_entities:
        return

    issues.append(
        QualityIssue(
            severity="P2",
            code="ENTITY_CONSISTENCY_MISSING_PROTECTED_ENTITY",
            message="源内容中的受保护英文实体在整份译文中完全不可见，可能发生组织、产品或基金名丢失。",
            source_signal=", ".join(missing_entities[:8]),
            translation_signal="missing_in_translation",
            suggested_fix="保留关键英文实体名，或使用公认中文译名并避免改成无关主体。",
        )
    )


def _unique_amounts(amounts) -> List[float]:
    unique: List[float] = []
    for amount in amounts:
        if amount <= 0:
            continue
        if any(_ratio(amount, existing) < 1.01 for existing in unique):
            continue
        unique.append(amount)
    return unique


def _ratio(left: float, right: float) -> float:
    if left <= 0 or right <= 0:
        return float("inf")
    return max(left / right, right / left)


def _format_amounts(amounts: Sequence[float]) -> str:
    return ", ".join(_format_usd(amount) for amount in amounts)


def _format_usd(value: float) -> str:
    if value >= 1_000_000_000_000:
        return f"${value / 1_000_000_000_000:.3g}T"
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.3g}B"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.3g}M"
    return f"${value:.3g}"
