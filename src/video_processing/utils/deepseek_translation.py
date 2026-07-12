# -*- coding: utf-8 -*-
"""DeepSeek 字幕翻译供应商。

通过 DeepSeek OpenAI-compatible Chat Completions API 批量翻译字幕。
本模块只负责调用 DeepSeek 并返回中文翻译列表，不负责质量守门、
供应商降级、vocab 对齐或 ASS 渲染。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-05 | Codex  | 初始创建：DeepSeek OpenAI-compatible 字幕批量翻译 provider |
| 1.1.0   | 2026-07-06 | Codex  | 强化全局上下文硬约束提示，降低金融 close/金额单位误译 |
| 1.2.0   | 2026-07-06 | Codex  | 复用 translation_prompt_constraints，避免 provider 约束漂移 |
| 1.3.0   | 2026-07-06 | Codex  | 兼容 DeepSeek 返回 translations/list 顶层包装，减少可解析响应误降级 |
| 1.4.0   | 2026-07-13 | Codex  | 新增一次返回翻译与 vocabulary 的结构化候选，供 Gemini 对比测试 |
| 1.5.0   | 2026-07-13 | Codex  | 明确财经/学术术语至少提取一项，修复模型因保守策略持续返回空 vocabulary |
| 1.6.0   | 2026-07-13 | Codex  | 强制 vocabulary 使用英文词到中文子串的 JSON 对象，修复模型返回列表被安全过滤 |
| 1.7.0   | 2026-07-13 | Codex  | 翻译+vocabulary 按 25 段分批调用，避免长视频 JSON 输出截断 |
| 1.8.0   | 2026-07-13 | Codex  | 词汇口径下调至 PET/B1，并要求保留专有名词，统一学习字幕标准 |
| 1.9.0   | 2026-07-13 | Codex  | 恢复每条字幕最多三项词汇卡，按学习价值排序避免版面拥挤 |
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from .translation_prompt_constraints import render_translation_constraints

logger = logging.getLogger(__name__)

_VOCAB_BATCH_SIZE = 25


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


def translate_batch_with_vocab_deepseek(
    texts: List[str],
    *,
    context_text: str = "",
    settings_obj: Any = None,
    error_out: Optional[List[str]] = None,
) -> Optional[List[Dict[str, Any]]]:
    """一次调用返回中文翻译和与中文子串严格对齐的 vocabulary。"""
    if not texts:
        return []
    def record_error(message: str) -> None:
        if error_out is not None:
            error_out.append(message)
    if settings_obj is None:
        try:
            from config.settings import settings as settings_obj
        except Exception:
            settings_obj = None
    api_key = getattr(settings_obj, "deepseek_api_key", "") if settings_obj else ""
    if not api_key:
        logger.info("[DeepSeek] API key not configured. Skipping vocab provider.")
        record_error("credentials not configured")
        return None

    base_url = (getattr(settings_obj, "deepseek_base_url", "") or "https://api.deepseek.com").rstrip("/")
    model = getattr(settings_obj, "deepseek_model", "") or "deepseek-v4-flash"
    all_items: List[Dict[str, Any]] = []
    for batch_start in range(0, len(texts), _VOCAB_BATCH_SIZE):
        batch = texts[batch_start: batch_start + _VOCAB_BATCH_SIZE]
        req = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=json.dumps(_build_vocab_payload(batch, context_text=context_text, model=model), ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            logger.warning(f"[DeepSeek] Translation+vocab API call failed: {e}")
            record_error(str(e))
            return None
        content = _extract_message_content(data)
        items = _parse_translation_vocab_json(content, expected_count=len(batch)) if content else None
        if items is None:
            logger.warning("[DeepSeek] Could not parse aligned translation+vocab response.")
            record_error("DeepSeek invalid or empty aligned response")
            return None
        all_items.extend(items)
    return all_items


def _build_payload(texts: List[str], *, context_text: str, model: str) -> Dict[str, Any]:
    items = [{"id": i, "english": text} for i, text in enumerate(texts)]
    user_prompt = (
        "Translate each subtitle segment into concise, natural zh-CN.\n"
        f"{render_translation_constraints(context_text)}\n"
        "Return JSON only: an array with exactly one object per input item.\n"
        "Each object must contain: id (same integer) and translation (Chinese string).\n"
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


def _build_vocab_payload(texts: List[str], *, context_text: str, model: str) -> Dict[str, Any]:
    items = [{"id": i, "english": text} for i, text in enumerate(texts)]
    user_prompt = (
        "Translate each subtitle segment into concise, natural zh-CN and identify the English-learning "
        "vocabulary items that a PET-level learner should study.\n"
        f"{render_translation_constraints(context_text)}\n"
        "Return JSON only: exactly one object per input item, preserving id order by id.\n"
        "Each object must contain id, translation, and vocab. vocab MUST be a JSON object whose keys are "
        "the exact English source words/phrases and whose values are Chinese strings. Never return vocab "
        "as an array/list. The Chinese value MUST be an exact substring of that item's translation. "
        "For example: {\"id\": 0, \"translation\": \"能够对冲风险\", \"vocab\": {\"hedge\": \"对冲\"}}. "
        "Vocabulary policy: extract all meaningful content words or phrases at CEFR B1 (PET) or above, "
        "including academic, technical, finance, economics, and idiomatic terms. Always extract proper nouns "
        "(people, organisations, products, places, frameworks, acronyms) when present; they are learning "
        "content, not stop words. Do not extract only A1-A2 function words or trivial greetings. "
        "When a segment contains more than three eligible items, select the three with the highest learning "
        "value; prefer phrases over their component words. Examples: portfolio→投资组合, hedge→对冲, "
        "disinflationary→反通胀, inflationary pressures→通胀压力, liquidity→流动性. "
        "Use {} only when the segment genuinely has no eligible vocabulary or proper noun.\n"
        f"Input:\n{json.dumps(items, ensure_ascii=False)}"
    )
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a professional subtitle translator and English educator. Output valid JSON only."},
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

    if isinstance(result, dict) and "translations" in result:
        result = result["translations"]
    elif isinstance(result, dict) and "list" in result:
        result = result["list"]

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


def _parse_translation_vocab_json(content: str, *, expected_count: int) -> Optional[List[Dict[str, Any]]]:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(result, dict):
        result = result.get("translations", result.get("list"))
    if not isinstance(result, list):
        return None

    slots: List[Optional[Dict[str, Any]]] = [None] * expected_count
    for item in result:
        if not isinstance(item, dict):
            continue
        idx = item.get("id")
        if isinstance(idx, bool) or not isinstance(idx, int) or not (0 <= idx < expected_count):
            continue
        translation = str(item.get("translation") or "")
        raw_vocab = item.get("vocab") or {}
        vocab = {}
        if isinstance(raw_vocab, dict):
            for word, meaning in raw_vocab.items():
                meaning = str(meaning or "").strip()
                if meaning and meaning in translation:
                    vocab[str(word)] = meaning
        slots[idx] = {"translation": translation, "vocab": vocab}
    if any(value is None for value in slots):
        return None
    return [value or {"translation": "", "vocab": {}} for value in slots]
