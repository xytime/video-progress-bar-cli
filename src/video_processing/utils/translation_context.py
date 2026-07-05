# -*- coding: utf-8 -*-
"""字幕翻译上下文构建器。

从全片字幕中抽取 provider-neutral 的语义提示，供 Gemini/OpenAI/DeepSeek
等模型在批量翻译时共享同一份全局背景，避免逐句翻译丢失视频主题。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-05 | Codex  | 初始创建：从全片文本抽取领域、事实、术语提示并渲染为翻译上下文 |
| 1.1.0   | 2026-07-06 | Codex  | 抽取受保护英文实体并注入 prompt，减少整片实体漂移 |
| 1.2.0   | 2026-07-06 | Codex  | 从全片文本抽取结构化信号，避免长视频中段关键事实被采样遗漏 |
| 1.3.0   | 2026-07-06 | Codex  | 金额事实提示避免科学计数法，降低模型误读数字单位风险 |
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, List, Sequence

from .translation_entity_guard import extract_protected_entities
from .translation_quality_guard import extract_fact_signal


@dataclass(frozen=True)
class TranslationContext:
    """翻译模型可复用的全片上下文。"""

    domain: str = "general"
    facts: List[str] = field(default_factory=list)
    entities: List[str] = field(default_factory=list)
    term_notes: List[str] = field(default_factory=list)
    style_notes: List[str] = field(default_factory=list)

    def to_prompt_context(self, *, max_chars: int = 1800) -> str:
        """渲染为可注入 LLM prompt 的上下文片段。"""
        sections: List[str] = [
            "Global video context for subtitle translation:",
            f"- Domain: {self.domain}",
        ]
        if self.facts:
            sections.append("- Source facts to preserve:")
            sections.extend(f"  - {fact}" for fact in self.facts)
        if self.entities:
            sections.append("- Protected source entities:")
            sections.append(
                "  - Keep these entity names recognizable in the zh-CN output: "
                + ", ".join(self.entities)
            )
        if self.term_notes:
            sections.append("- Domain translation notes:")
            sections.extend(f"  - {note}" for note in self.term_notes)
        if self.style_notes:
            sections.append("- Style notes:")
            sections.extend(f"  - {note}" for note in self.style_notes)

        rendered = "\n".join(sections)
        if len(rendered) <= max_chars:
            return rendered
        return rendered[:max_chars].rsplit("\n", 1)[0]


def build_translation_context(
    english_texts: Sequence[str],
    *,
    title: str = "",
    description: str = "",
) -> TranslationContext:
    """从标题、简介和全片字幕构建翻译上下文。"""
    full_parts = [title, description, *_clean_texts(english_texts)]
    full_corpus = _join_non_empty(full_parts)
    domain = _detect_domain(full_corpus)
    facts = _extract_facts(full_corpus)
    entities = extract_protected_entities(full_parts)
    term_notes = _extract_term_notes(full_corpus, domain)
    style_notes = [
        "Translate meaning, not isolated words; keep subtitles concise and natural in zh-CN.",
        "Preserve event direction, money flow, entities, and numeric magnitude.",
    ]

    return TranslationContext(
        domain=domain,
        facts=facts,
        entities=entities,
        term_notes=term_notes,
        style_notes=style_notes,
    )


def _detect_domain(text: str) -> str:
    lowered = text.lower()
    finance_score = _count_matches(
        lowered,
        (
            "fund", "capital", "market", "invest", "investment", "valuation",
            "revenue", "capex", "expenditure", "sovereign", "portfolio",
            "oversubscribed", "close", "commitments",
        ),
    )
    technology_score = _count_matches(
        lowered,
        (
            "ai", "artificial intelligence", "chip", "model", "data center",
            "compute", "nvidia", "openai", "semiconductor", "cloud",
            "infrastructure",
        ),
    )
    geopolitics_score = _count_matches(
        lowered,
        (
            "war", "election", "president", "sanction", "military",
            "geopolitical", "government", "policy",
        ),
    )

    if finance_score >= 3 and technology_score >= 1:
        return "finance/technology"
    if finance_score >= max(3, technology_score, geopolitics_score):
        return "finance"
    if technology_score >= max(3, geopolitics_score):
        return "technology"
    if geopolitics_score >= 3:
        return "geopolitics"
    return "general"


def _extract_facts(text: str) -> List[str]:
    signal = extract_fact_signal(text, lang="en")
    facts: List[str] = []

    if signal.event_type == "fundraising_complete":
        facts.append(
            "The source describes a fund reaching final close/completing fundraising; "
            "do not translate this as withdrawal, exit, shutdown, or liquidation."
        )
    if signal.amounts_usd:
        formatted = ", ".join(_format_usd(amount) for amount in signal.amounts_usd[:6])
        facts.append(f"Preserve USD amount magnitudes exactly where mentioned: {formatted}.")

    return facts


def _extract_term_notes(text: str, domain: str) -> List[str]:
    lowered = text.lower()
    notes: List[str] = []

    if "fund" in lowered and re.search(r"\b(final\s+close|closed\s+(?:its\s+)?fund|fund\s+closing)\b", lowered):
        notes.append(
            "In private fund context, 'close/final close' usually means 完成募集/最终关账, not 关闭/撤退."
        )
    if re.search(r"\bover[-\s]?subscribed\b|exceed(?:ed|s|ing)\s+(?:its\s+)?(?:initial\s+)?target", lowered):
        notes.append("Translate oversubscription/target exceeded as 超募/超过原定目标.")
    if "capital expenditure" in lowered or "capex" in lowered:
        notes.append("Translate capital expenditure/capex as 资本开支 or 资本支出; verify billion/trillion units.")
    if domain in ("finance", "finance/technology"):
        notes.append("For finance subtitles, distinguish fundraising inflow from investor exit/outflow.")

    return _dedupe(notes)


def _clean_texts(texts: Sequence[str]) -> List[str]:
    return [text.strip() for text in texts if text and text.strip()]


def _join_non_empty(parts: Iterable[str]) -> str:
    return "\n".join(part.strip() for part in parts if part and part.strip())


def _count_matches(text: str, terms: Sequence[str]) -> int:
    return sum(text.count(term) for term in terms)


def _dedupe(items: Sequence[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _format_usd(value: float) -> str:
    if value >= 1_000_000_000_000:
        return f"${value / 1_000_000_000_000:.3g}T"
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.3g}B"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.3g}M"
    return f"${value:,.0f}" if value.is_integer() else f"${value:,.2f}".rstrip("0").rstrip(".")
