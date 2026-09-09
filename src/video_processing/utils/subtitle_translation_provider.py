# -*- coding: utf-8 -*-
"""字幕翻译供应商结果模型。

本模块只定义 provider-neutral 的字幕翻译候选结果，不直接调用任何 API。
Gemini、Google、DeepSeek/OpenAI 等供应商只要产出同一结构，
上层就能复用统一的质量守门、降级和审计逻辑。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-05 | Codex  | 初始创建：抽象字幕翻译候选结果与应用函数，为多供应商接入预留接口 |
| 1.1.0   | 2026-07-13 | Codex  | 拒绝全空或中文覆盖率不足的候选，禁止空字幕进入发布链路 |
| 1.2.0   | 2026-08-17 | Codex  | 拒绝上游 HTTP 错误页候选，确保所有翻译供应商共享同一道底线 |
| 1.3.0   | 2026-09-09 | Codex  | 严格要求段数相等并拒绝承接占位符，返回可审计的段号原因 |
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, MutableMapping, Sequence

from .generated_content_validation import is_upstream_error_response
from .subtitle_content_contract import is_translation_placeholder


@dataclass(frozen=True)
class SubtitleTranslationCandidate:
    """一个翻译供应商返回的字幕候选结果。"""

    provider: str
    translations: List[str]
    vocabs: List[Dict[str, Any]] = field(default_factory=list)
    supports_vocab: bool = False
    model: str | None = None

    def is_usable_for(self, segment_count: int) -> bool:
        """候选结果是否足以应用到指定数量的字幕段。"""
        return self.contract_error_for(segment_count) is None

    def contract_error_for(self, segment_count: int) -> str | None:
        """结构错误不能通过软性质量 fail-open 放行；段号为 0-based。"""
        if segment_count <= 0 or len(self.translations) != segment_count:
            return f"translation_segment_count_mismatch: expected={segment_count}, actual={len(self.translations)}"
        for index, text in enumerate(self.translations):
            if not isinstance(text, str) or not text.strip():
                return f"translation_empty_segment: index={index}"
            if is_upstream_error_response(text):
                return f"translation_upstream_error: index={index}"
            if is_translation_placeholder(text):
                return f"translation_placeholder: index={index}"
        return None


def apply_translation_candidate(
    segments: Sequence[MutableMapping[str, Any]],
    candidate: SubtitleTranslationCandidate,
) -> None:
    """把 provider-neutral 候选结果应用到字幕段。"""
    error = candidate.contract_error_for(len(segments))
    if error:
        raise ValueError(error)
    for i, segment in enumerate(segments):
        if i >= len(candidate.translations):
            break
        segment["zh_text"] = candidate.translations[i] or ""
        if candidate.supports_vocab and i < len(candidate.vocabs):
            segment["vocab"] = candidate.vocabs[i] or {}
        else:
            segment["vocab"] = {}
