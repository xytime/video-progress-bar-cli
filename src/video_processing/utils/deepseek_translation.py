# -*- coding: utf-8 -*-
"""DeepSeek 字幕翻译供应商。

通过 DeepSeek OpenAI-compatible Chat Completions API 批量翻译字幕。
本模块只负责调用 DeepSeek 并返回中文翻译列表，不负责质量守门、
供应商降级、vocab 对齐或 ASS 渲染。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-05 | Codex  | 初始创建：DeepSeek OpenAI-compatible 字幕批量翻译 provider |
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def translate_batch_deepseek(
    texts: List[str],
    *,
    context_text: str = "",
    settings_obj: Any = None,
) -> Optional[List[str]]:
    """使用 DeepSeek API 批量翻译字幕文本。"""
    if not texts:
        return []

    if settings_obj is None:
        try:
            from config.settings import settings as settings_obj
        except Exception:
            settings_obj = None

    api_key = getattr(settings_obj, "deepseek_api_key", "") if settings_obj else ""
    if not api_key:
        logger.info("[DeepSeek] API key not configured. Skipping provider.")
        return None

    base_url = (getattr(settings_obj, "deepseek_base_url", "") or "https://api.deepseek.com").rstrip("/")
    model = getattr(settings_obj, "deepseek_model", "") or "deepseek-v4-flash"
    payload = _build_payload(texts, context_text=context_text, model=model)
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        logger.warning(f"[DeepSeek] API call failed: {e}")
        return None

    content = _extract_message_content(data)
    if not content:
        logger.warning("[DeepSeek] Empty response content.")
        return None

    translations = _parse_translation_json(content, expected_count=len(texts))
    if translations is None:
        logger.warning("[DeepSeek] Could not parse aligned translation response.")
    return translations


def _build_payload(texts: List[str], *, context_text: str, model: str) -> Dict[str, Any]:
    items = [{"id": i, "english": text} for i, text in enumerate(texts)]
    context_block = f"\nGlobal context:\n{context_text.strip()}\n" if context_text.strip() else ""
    user_prompt = (
        "Translate each subtitle segment into concise, natural zh-CN.\n"
        "Preserve event direction, entity names, money flow, and numeric magnitude.\n"
        "Return JSON only: an array with exactly one object per input item.\n"
        "Each object must contain: id (same integer) and translation (Chinese string).\n"
        f"{context_block}\n"
        f"Input:\n{json.dumps(items, ensure_ascii=False)}"
    )
    return {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a professional subtitle translator for finance, technology, "
                    "business, and news videos. Output valid JSON only."
                ),
            },
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "temperature": 0.1,
    }


def _extract_message_content(data: Dict[str, Any]) -> str:
    try:
        return str(data["choices"][0]["message"]["content"] or "")
    except Exception:
        return ""


def _parse_translation_json(content: str, *, expected_count: int) -> Optional[List[str]]:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        return None

    if not isinstance(result, list):
        return None

    slots: List[Optional[str]] = [None] * expected_count
    for item in result:
        if not isinstance(item, dict):
            continue
        idx = item.get("id")
        if isinstance(idx, bool) or not isinstance(idx, int) or not (0 <= idx < expected_count):
            continue
        slots[idx] = str(item.get("translation") or "")

    if any(value is None for value in slots):
        return None
    return [value or "" for value in slots]
