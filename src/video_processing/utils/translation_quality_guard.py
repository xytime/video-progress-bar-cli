# -*- coding: utf-8 -*-
"""字幕翻译事实保真守门器。

本模块不直接做翻译，而是从原文与译文中抽取可比较的事实信号，
用于发现“事件方向反了”“金额数量级错了”这类会改变视频主旨的错误。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-05 | Codex  | 初始创建：抽取融资完成/退出语义、金额数量级，并输出可阻断的质量问题 |
| 1.1.0   | 2026-07-05 | Codex  | 本句信号优先、上下文只补足未知语义；新增批量 P0 汇总供字幕链路接入 |
| 1.2.0   | 2026-07-05 | Codex  | 金融语境下支持无 $ 的 billion/million/trillion 金额抽取 |
| 1.3.0   | 2026-07-05 | Codex  | 支持 $49B/49B fund 等 B/M/T 金融金额缩写抽取 |
| 1.4.0   | 2026-07-06 | Codex  | 支持 US$49bn/49bn fund 等 bn/mn/tn 金融金额缩写抽取 |
| 1.5.0   | 2026-07-06 | Codex  | 金额信号格式避免科学计数法，提升审计报告和 prompt 可读性 |
| 1.6.0   | 2026-07-09 | Codex  | 仅允许上下文补足事件语义，不再为单句金额检查继承全片金额，避免财经长字幕跨句错配导致 P0 误杀 |
| 1.7.0   | 2026-07-09 | Codex  | 对被字幕切断的金额短语做窄范围补全：仅当本句出现裸数字而上下文出现同尾数带单位金额时，提升为带单位金额，避免 `$600` vs `$450B` 这类拆句误杀 |
| 1.8.0   | 2026-07-13 | Codex  | 支持暂时禁用金额数量级检查，保留事件方向与空译文安全检查 |
| 1.9.0   | 2026-10-27 | Codex  | 完整单位与真实相邻字幕补全；自然中文金额、精确同值去重及逐段全部金额锚点覆盖校验 |
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import IntEnum
from typing import List, Sequence


class Severity(IntEnum):
    """质量问题严重程度，数值越大越严重。"""

    PASS_ = 0
    P3 = 1
    P2 = 2
    P1 = 3
    P0 = 4

    @property
    def label(self) -> str:
        return "PASS" if self == Severity.PASS_ else self.name


@dataclass(frozen=True)
class FactSignal:
    """一段文本中可被机器比较的事实信号。"""

    event_type: str = "unknown"
    money_flow: str = "unknown"
    amounts_usd: List[float] = field(default_factory=list)
    markers: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class QualityIssue:
    """单个翻译质量问题。"""

    severity: str
    code: str
    message: str
    source_signal: str
    translation_signal: str
    suggested_fix: str = ""


@dataclass(frozen=True)
class GuardResult:
    """翻译质量守门结果。"""

    issues: List[QualityIssue]
    source_signal: FactSignal
    translation_signal: FactSignal

    @property
    def max_severity(self) -> str:
        if not self.issues:
            return "PASS"
        return max(Severity[item.severity] for item in self.issues).label

    @property
    def passed(self) -> bool:
        return not any(Severity[item.severity] >= Severity.P1 for item in self.issues)


@dataclass(frozen=True)
class BatchGuardSummary:
    """批量守门摘要，用于调用方决定是否阻断。"""

    results: List[GuardResult]

    @property
    def blocking_issues(self) -> List[QualityIssue]:
        return [
            issue
            for result in self.results
            for issue in result.issues
            if Severity[issue.severity] >= Severity.P0
        ]

    @property
    def warning_issues(self) -> List[QualityIssue]:
        return [
            issue
            for result in self.results
            for issue in result.issues
            if Severity.P1 <= Severity[issue.severity] < Severity.P0
        ]

    @property
    def passed(self) -> bool:
        return not self.blocking_issues


_FUNDRAISING_SOURCE_PATTERNS: Sequence[re.Pattern[str]] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(final\s+close|first\s+close)\b",
        r"\bclosed\s+(?:its\s+)?(?:fund|fund\s+[ivx]+)\b",
        r"\bfund\s+(?:[ivx]+\s+)?(?:closed|closing)\b",
        r"\bexceed(?:ed|s|ing)\s+(?:its\s+)?(?:initial\s+)?target\b",
        r"\bover[-\s]?subscribed\b",
        r"\brais(?:e|ed|ing)\s+(?:a\s+)?(?:fund|capital|commitments)\b",
        r"\bcapital\s+commitments\b",
    )
)

_SOURCE_EXIT_PATTERNS: Sequence[re.Pattern[str]] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bexit(?:ed|ing|s)?\b",
        r"\bwithdraw(?:al|n|ing)?\b",
        r"\bpull(?:ed|ing)?\s+out\b",
        r"\bretreat(?:ed|ing)?\b",
    )
)

_ZH_FUNDRAISING_PATTERNS: Sequence[re.Pattern[str]] = tuple(
    re.compile(pattern)
    for pattern in (
        r"募集",
        r"募资",
        r"认缴",
        r"承诺出资",
        r"最终关账",
        r"完成.*关账",
        r"完成.*募集",
        r"超募",
        r"超过.*目标",
    )
)

_ZH_EXIT_PATTERNS: Sequence[re.Pattern[str]] = tuple(
    re.compile(pattern)
    for pattern in (
        r"撤退",
        r"撤出",
        r"退出市场",
        r"选择退出",
        r"离场",
        r"清盘",
        r"套现离场",
    )
)

_ZH_AMBIGUOUS_CLOSE_PATTERNS: Sequence[re.Pattern[str]] = tuple(
    re.compile(pattern) for pattern in (r"基金.*关闭", r"关闭.*基金", r"已以.*关闭")
)


def extract_fact_signal(text: str, *, lang: str = "auto") -> FactSignal:
    """抽取文本中的事件、资金流向、金额等事实信号。"""
    normalized = (text or "").strip()
    markers: List[str] = []
    event_type = "unknown"
    money_flow = "unknown"

    source_fundraising = _any_match(_FUNDRAISING_SOURCE_PATTERNS, normalized)
    zh_fundraising = _any_match(_ZH_FUNDRAISING_PATTERNS, normalized)
    source_exit = _any_match(_SOURCE_EXIT_PATTERNS, normalized)
    zh_exit = _any_match(_ZH_EXIT_PATTERNS, normalized)
    zh_ambiguous_close = _any_match(_ZH_AMBIGUOUS_CLOSE_PATTERNS, normalized)

    if source_fundraising or zh_fundraising:
        event_type = "fundraising_complete"
        money_flow = "inflow"
        markers.append("fundraising_complete")
    if source_exit or zh_exit:
        event_type = "market_exit"
        money_flow = "outflow"
        markers.append("market_exit")
    if zh_ambiguous_close:
        markers.append("ambiguous_fund_close")
        if event_type == "unknown":
            event_type = "ambiguous_fund_close"

    return FactSignal(
        event_type=event_type,
        money_flow=money_flow,
        amounts_usd=_extract_amounts_usd(normalized),
        markers=markers,
    )


def evaluate_translation_pair(
    source_text: str,
    translated_text: str,
    *,
    context_text: str = "",
    enable_numeric_checks: bool = True,
    next_source_text: str = "",
    require_amount_coverage: bool = False,
) -> GuardResult:
    """评估一组原文/译文是否存在会改变事实的严重错误。

    Args:
        source_text: 单句、字幕片段或标题对应的源文本。
        translated_text: 待检查的中文译文。
        context_text: 可选的全局上下文；用于补充短字幕缺失的主题语义。
        next_source_text: 实际相邻的下一条源字幕，仅用于补全句尾被切断的金额单位。
        require_amount_coverage: 显式要求本句美元事实在对应译文保留金额或等价数字锚点。
    """
    source_signal = _merge_source_with_context(
        extract_fact_signal(_complete_split_amount_fragment(source_text, next_source_text), lang="en"),
        extract_fact_signal(context_text, lang="en") if context_text else None,
    )
    translation_signal = extract_fact_signal(translated_text, lang="zh")
    issues: List[QualityIssue] = []

    _append_event_direction_issues(issues, source_signal, translation_signal)
    if enable_numeric_checks:
        _append_amount_issues(issues, source_signal, translation_signal)
        if require_amount_coverage:
            _append_missing_amount_issues(
                issues, source_signal, translation_signal, source_text, translated_text, next_source_text,
            )

    return GuardResult(
        issues=issues,
        source_signal=source_signal,
        translation_signal=translation_signal,
    )


def evaluate_translation_batch(
    source_texts: Sequence[str],
    translated_texts: Sequence[str],
    *,
    context_text: str = "",
    enable_numeric_checks: bool = True,
    next_source_text: str = "",
    require_amount_coverage: bool = False,
) -> BatchGuardSummary:
    """批量评估字幕片段，返回可直接用于阻断/告警的摘要。"""
    return BatchGuardSummary([
        evaluate_translation_pair(
            source,
            translated,
            context_text=context_text,
            enable_numeric_checks=enable_numeric_checks,
            require_amount_coverage=require_amount_coverage,
            next_source_text=(
                source_texts[index + 1]
                if index + 1 < len(source_texts) else next_source_text
            ),
        )
        for index, (source, translated) in enumerate(zip(source_texts, translated_texts))
    ])


def _merge_source_with_context(source_signal: FactSignal, context_signal: FactSignal | None) -> FactSignal:
    """用上下文补足本句缺失的事实信号，但不覆盖本句已有的明确事件。"""
    if context_signal is None:
        return source_signal

    event_type = source_signal.event_type
    money_flow = source_signal.money_flow
    markers = list(source_signal.markers)

    if event_type == "unknown" and context_signal.event_type != "unknown":
        event_type = context_signal.event_type
        money_flow = context_signal.money_flow
        markers.extend(f"context:{marker}" for marker in context_signal.markers)

    return FactSignal(
        event_type=event_type,
        money_flow=money_flow,
        # 摘要中的同尾数金额不能证明本句省略单位；金额只来自本句与明确相邻的拆句边界。
        amounts_usd=source_signal.amounts_usd,
        markers=markers,
    )


def _complete_split_amount_fragment(source_text: str, next_source_text: str) -> str:
    """仅补全“本句末尾 $600 / 下一句开头 billion”这类有直接边界证据的单位。"""
    if not next_source_text or not re.search(
        r"(?:US)?\$\s*[0-9][0-9,]*(?:\.[0-9]+)?\s*$", source_text, re.IGNORECASE,
    ):
        return source_text
    unit = re.match(rf"\s*({_english_amount_unit_pattern()})", next_source_text, re.IGNORECASE)
    if unit is None:
        return source_text
    return f"{source_text.rstrip()} {unit.group(1)}"


def _append_event_direction_issues(
    issues: List[QualityIssue],
    source_signal: FactSignal,
    translation_signal: FactSignal,
) -> None:
    if (
        source_signal.event_type == "fundraising_complete"
        and translation_signal.event_type == "market_exit"
    ):
        issues.append(
            QualityIssue(
                severity="P0",
                code="FINANCE_EVENT_DIRECTION_REVERSAL",
                message="原文表达基金完成募集/最终关账，译文却表达撤退、退出或离场，事件方向被反转。",
                source_signal="fundraising_complete/inflow",
                translation_signal="market_exit/outflow",
                suggested_fix="将 close/final close 译为“完成募集”“最终关账”或“募资规模达到”，避免译成撤退/退出。",
            )
        )
        return

    if (
        source_signal.event_type == "fundraising_complete"
        and "ambiguous_fund_close" in translation_signal.markers
        and "fundraising_complete" not in translation_signal.markers
    ):
        issues.append(
            QualityIssue(
                severity="P1",
                code="FINANCE_TERM_AMBIGUOUS_CLOSE",
                message="基金语境中的 close 被直译为“关闭”，容易误读为停业、清盘或退出。",
                source_signal="fundraising_complete/inflow",
                translation_signal="ambiguous_fund_close",
                suggested_fix="在基金募资语境中优先译为“完成募集/最终关账/募资完成”。",
            )
        )


def _append_amount_issues(
    issues: List[QualityIssue],
    source_signal: FactSignal,
    translation_signal: FactSignal,
) -> None:
    if not source_signal.amounts_usd or not translation_signal.amounts_usd:
        return

    for source_amount in source_signal.amounts_usd:
        if source_amount <= 0:
            continue
        closest = min(
            translation_signal.amounts_usd,
            key=lambda candidate: abs(_safe_ratio(candidate, source_amount) - 1),
        )
        ratio = max(_safe_ratio(source_amount, closest), _safe_ratio(closest, source_amount))
        if ratio >= 100:
            issues.append(
                QualityIssue(
                    severity="P0",
                    code="NUMBER_MAGNITUDE_MISMATCH",
                    message="译文金额与原文金额相差两个数量级以上，足以改变事实判断。",
                    source_signal=_format_usd(source_amount),
                    translation_signal=_format_usd(closest),
                    suggested_fix="回看原文数字单位，重点核对 million/billion/trillion 与 亿/万亿 的转换。",
                )
            )
            return
        if ratio >= 10:
            issues.append(
                QualityIssue(
                    severity="P1",
                    code="NUMBER_MAGNITUDE_SUSPECT",
                    message="译文金额与原文金额相差一个数量级以上，需要人工复核。",
                    source_signal=_format_usd(source_amount),
                    translation_signal=_format_usd(closest),
                    suggested_fix="核对数字单位与中文金额表达。",
                )
            )
            return


def _append_missing_amount_issues(
    issues: List[QualityIssue], source_signal: FactSignal, translation_signal: FactSignal,
    source_text: str, translated_text: str, next_source_text: str,
) -> None:
    """逐一检查本句金额锚点；已有数量级问题沿用原门禁，不重复分类。"""
    if not source_signal.amounts_usd or any(
        issue.code in {"NUMBER_MAGNITUDE_MISMATCH", "NUMBER_MAGNITUDE_SUSPECT"}
        for issue in issues
    ):
        return
    numeric_anchors = list(translation_signal.amounts_usd)
    for match in re.finditer(r"(?<![0-9A-Za-z_])([0-9][0-9,]*(?:\.[0-9]+)?)(?![0-9A-Za-z_])", translated_text):
        suffix = translated_text[match.end():]
        if _has_non_amount_suffix(suffix) or re.match(
            rf"\s*(?:{_chinese_amount_unit_pattern()}|美元|美金|{_english_amount_unit_pattern()})",
            suffix, re.IGNORECASE,
        ):
            # 已带单位的数只贡献规范化金额，不能把100万的系数100再当成裸$100。
            continue
        value = _parse_number(match.group(1))
        if value is not None:
            numeric_anchors.append(value)

    # 本句 $600 / 下一句 billion 时，本句译文仍可只保留裸 600，单位归下一时间槽。
    split_amount = split_raw = None
    completed = _complete_split_amount_fragment(source_text, next_source_text)
    if completed != source_text:
        raw = re.search(r"\$\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*$", source_text)
        split_raw = _parse_number(raw.group(1))
        split_amount = split_raw * _english_amount_multipliers()[completed.rsplit(" ", 1)[1].lower()]

    for amount in source_signal.amounts_usd:
        equivalents = [amount]
        if split_amount is not None and _same_numeric_amount(amount, split_amount):
            equivalents.append(split_raw)
        if any(_same_numeric_amount(anchor, expected) for anchor in numeric_anchors for expected in equivalents):
            continue
        issues.append(QualityIssue(
            severity="P0", code="NUMBER_AMOUNT_MISSING",
            message="本句原文的美元金额在对应译文中没有金额或等价数值锚点，可能跨段串句或遗漏事实。",
            source_signal=_format_usd(amount), translation_signal="amount_not_in_segment",
            suggested_fix="只翻译本段源文本，将本段金额留在对应时间槽；不要从相邻段借用或搬移事实。",
        ))


def _same_numeric_amount(left: float, right: float) -> bool:
    return abs(left - right) <= max(1e-9, max(abs(left), abs(right)) * 1e-9)


def _has_non_amount_suffix(text: str) -> bool:
    # 万人、万桶等计数也不能把系数当作美元锚点；美元/桶的金额仍由货币单位确定。
    return bool(re.match(
        rf"\s*(?:{_chinese_amount_unit_pattern()}\s*)?"
        r"(?:[%％]|(?:个)?(?:百分点|基点|年份|年|股|人|桶|倍)|个|bp(?:s)?\b)",
        text, re.IGNORECASE,
    ))


def _chinese_amount_unit_pattern() -> str:
    # 先匹配完整复合量词，不能把“千万/百万/百分点”的第一个字当金额单位。
    return r"(?:万亿|千亿|百亿|十亿|亿|千万|百万|十万|万|千|百|十)(?![十百千万亿])"


def _extract_amounts_usd(text: str) -> List[float]:
    amounts: List[float] = []
    amounts.extend(_extract_english_amounts_usd(text))
    amounts.extend(_extract_chinese_amounts_usd(text))
    return _dedupe_amounts(amounts)


def _extract_english_amounts_usd(text: str) -> List[float]:
    amounts: List[float] = []
    unit_pattern = _english_amount_unit_pattern()
    dollar_pattern = re.compile(
        rf"(?:US)?\$\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*({unit_pattern})?",
        re.IGNORECASE,
    )
    multipliers = _english_amount_multipliers()
    for match in dollar_pattern.finditer(text):
        value = _parse_number(match.group(1))
        if value is None:
            continue
        unit = _normalize_english_amount_unit(match.group(2))
        if unit is None and re.match(rf"\s*{_chinese_amount_unit_pattern()}", text[match.end():]):
            # $115万等混合写法交给中文单位规范化，不能同时产生一个伪裸$115锚点。
            continue
        amounts.append(value * multipliers[unit])

    bare_money_cues = (
        "fund", "capital", "capex", "expenditure", "commitment", "commitments",
        "valuation", "revenue", "market cap", "investment", "investments",
        "target", "assets", "aum",
    )
    cue_pattern = "|".join(re.escape(cue) for cue in bare_money_cues)
    bare_after_pattern = re.compile(
        rf"\b([0-9][0-9,]*(?:\.[0-9]+)?)\s*"
        rf"({unit_pattern})\b"
        rf"(?:\s+\w+){{0,3}}\s+(?:{cue_pattern})\b",
        re.IGNORECASE,
    )
    for match in bare_after_pattern.finditer(text):
        value = _parse_number(match.group(1))
        if value is None:
            continue
        unit = _normalize_english_amount_unit(match.group(2))
        amounts.append(value * multipliers[unit])

    bare_before_pattern = re.compile(
        rf"\b(?:raised|raising|committed|commit|valued\s+at|worth|target(?:ed)?\s+at|at)\s+"
        rf"([0-9][0-9,]*(?:\.[0-9]+)?)\s*"
        rf"({unit_pattern})\b",
        re.IGNORECASE,
    )
    for match in bare_before_pattern.finditer(text):
        value = _parse_number(match.group(1))
        if value is None:
            continue
        unit = _normalize_english_amount_unit(match.group(2))
        amounts.append(value * multipliers[unit])
    return amounts


def _english_amount_unit_pattern() -> str:
    # 尤其不能把 $115 bucks / $75 to 中普通单词的首字母识别成 billion / trillion。
    return r"(?:trillion|billion|million|tn|bn|mn|[tmb])(?!\w)"


def _english_amount_multipliers() -> dict[str | None, int]:
    return {
        "trillion": 1_000_000_000_000,
        "billion": 1_000_000_000,
        "million": 1_000_000,
        "tn": 1_000_000_000_000,
        "bn": 1_000_000_000,
        "mn": 1_000_000,
        "t": 1_000_000_000_000,
        "b": 1_000_000_000,
        "m": 1_000_000,
        None: 1,
    }


def _normalize_english_amount_unit(unit: str | None) -> str | None:
    return unit.lower() if unit else None


def _extract_chinese_amounts_usd(text: str) -> List[float]:
    amounts: List[float] = []
    pattern = re.compile(
        r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*"
        rf"({_chinese_amount_unit_pattern()}|美元|美金)\s*(?:美元|美金)?"
    )
    multipliers = {
        "万亿": 1_000_000_000_000,
        "千亿": 100_000_000_000,
        "百亿": 10_000_000_000,
        "十亿": 1_000_000_000,
        "亿": 100_000_000,
        "千万": 10_000_000,
        "百万": 1_000_000,
        "十万": 100_000,
        "万": 10_000,
        "千": 1_000,
        "百": 100,
        "十": 10,
        "美元": 1,
        "美金": 1,
    }
    for match in pattern.finditer(text):
        if _has_non_amount_suffix(text[match.end(1):]):
            continue
        value = _parse_number(match.group(1))
        if value is not None:
            amounts.append(value * multipliers[match.group(2)])
    return amounts


def _dedupe_amounts(amounts: Sequence[float]) -> List[float]:
    unique: List[float] = []
    for amount in amounts:
        if amount <= 0:
            continue
        if any(_same_numeric_amount(amount, existing) for existing in unique):
            continue
        unique.append(amount)
    return unique


def _any_match(patterns: Sequence[re.Pattern[str]], text: str) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def _join_non_empty(parts: Sequence[str]) -> str:
    return "\n".join(part.strip() for part in parts if part and part.strip())


def _parse_number(value: str) -> float | None:
    try:
        return float(value.replace(",", ""))
    except ValueError:
        return None


def _safe_ratio(a: float, b: float) -> float:
    if b == 0:
        return float("inf")
    return a / b


def _format_usd(value: float) -> str:
    if value >= 1_000_000_000_000:
        return f"${value / 1_000_000_000_000:.3g}T"
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.3g}B"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.3g}M"
    return f"${value:,.0f}" if value.is_integer() else f"${value:,.2f}".rstrip("0").rstrip(".")
