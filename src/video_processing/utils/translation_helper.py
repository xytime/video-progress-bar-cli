# -*- coding: utf-8 -*-
"""统一翻译助手模块 — Google Translate 终级兜底。

提供单条翻译与批量翻译接口。主字幕质量链路由 Gemini/DeepSeek 承担；
本模块只提供无词汇对齐能力的终级兜底，不直接调用其他云厂商 SDK。

# Modification History
| Version | Date       | Author                     | Description |
| ------- | ---------- | -------------------------- | ----------- |
| 1.0.0   | 2026-06-08 | Claude_Sonnet_4.6_planning | 初始创建：高内聚翻译模块 |
| 1.3.0   | 2026-07-17 | Codex                      | 移除阿里云 MT 调用；仅保留 Google 终级翻译接口 |
| 1.3.1   | 2026-07-26 | Codex                      | 保留字符预算切块纯函数，维持字幕对齐回归保护 |
| 1.3.2   | 2026-08-17 | Codex                      | 拒绝 Google 返回的纯文本 HTTP 错误页，避免被当作非空字幕译文 |
"""

import logging
from typing import List

from .generated_content_validation import is_upstream_error_response

try:
    from deep_translator import GoogleTranslator
except ImportError:
    GoogleTranslator = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

_SEP = "\n###\n"


def _split_by_char_budget(indices: List[int], batch_texts: List[str], max_chars: int) -> List[List[int]]:
    """把下标切成若干组，使每组用 _SEP 拼接后尽量不超过 max_chars。"""
    groups: List[List[int]] = []
    current: List[int] = []
    current_len = 0
    sep_len = len(_SEP)

    for index in indices:
        text_len = len(batch_texts[index])
        added_len = text_len + (sep_len if current else 0)
        if current and current_len + added_len > max_chars:
            groups.append(current)
            current = []
            current_len = 0
            added_len = text_len
        current.append(index)
        current_len += added_len

    if current:
        groups.append(current)
    return groups


def translate_batch(
    texts: List[str],
    src_lang: str = "auto",
    target_lang: str = "zh-CN",
) -> List[str]:
    """批量翻译文本列表，使用 Google Translate 作为终级兜底。"""
    if not texts:
        return []
    return _google_translate_batch(texts, src_lang=src_lang, target_lang=target_lang)


def translate_text(
    text: str,
    src_lang: str = "auto",
    target_lang: str = "zh-CN",
) -> str:
    """翻译单条文本；失败时保持原文，绝不返回伪成功空串。"""
    if not text or not text.strip():
        return text
    results = translate_batch([text], src_lang=src_lang, target_lang=target_lang)
    translated = results[0] if results else ""
    return translated if translated else text


def _google_translate_batch(
    texts: List[str],
    src_lang: str = "auto",
    target_lang: str = "zh-CN",
) -> List[str]:
    """使用 deep_translator.GoogleTranslator 批量翻译并过滤错误页面。"""
    if not texts:
        return []
    if GoogleTranslator is None:
        logger.warning("[TransHelper] deep_translator 未安装，Google 终级兜底不可用。")
        return [""] * len(texts)
    try:
        translator = GoogleTranslator(source=src_lang, target=target_lang)
        translated = translator.translate_batch(texts)
    except Exception as exc:
        logger.warning("[TransHelper] Google Translate failed: %s", exc)
        return [""] * len(texts)

    invalid_markers = ("<html", "cloudflare", "captcha", "attention required")
    results = []
    for value in translated or []:
        text = str(value or "").strip()
        if any(marker in text.lower() for marker in invalid_markers) or is_upstream_error_response(text):
            logger.warning("[TransHelper] Google returned an upstream error response; discarding candidate entry.")
            text = ""
        results.append(text)
    return (results + [""] * len(texts))[:len(texts)]
