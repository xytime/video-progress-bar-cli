# -*- coding: utf-8 -*-
"""词汇提取助手 — 封装 Gemini API 难词提取与中文对齐逻辑

# Modification History
| Version | Date       | Author                              | Description                                                              |
| ------- | ---------- | ----------------------------------- | ------------------------------------------------------------------------ |
| 1.0.0   | 2026-06-08 | Claude_Sonnet_4.6_Thinking_planning | 初始创建：从 caption_processor.py 抽取 Gemini 生词提取与对齐职责，实现高内聚低耦合 |
| 1.1.0   | 2026-06-08 | Claude_Sonnet_4.6_Thinking_planning | 实现分批调用（50段/次）解决277段场景下输出截断导致计数不符的问题；放宽计数校验 |

# Modification History
| Version | Date       | Author                              | Description                                                              |
| ------- | ---------- | ----------------------------------- | ------------------------------------------------------------------------ |
| 1.0.0   | 2026-06-08 | Claude_Sonnet_4.6_Thinking_planning | 初始创建：从 caption_processor.py 抽取 Gemini 生词提取与对齐职责，实现高内聚低耦合 |

职责边界：
- 负责：Gemini SDK 初始化、多模型 Fallback、指数退避重试、提示词构造、JSON 解析
- 不负责：阿里云翻译、Google 翻译、ASS 字幕生成、视频合成

核心优化（修复中文字幕下划线不显示 BUG）：
  当提供 chinese_translations 参数时，提示词强制 Gemini 将 vocab 字典的中文值
  限制为 chinese_translations 中的精确子字符串。这确保了 SubtitleStylist 的
  apply_chinese_highlights 函数能够在主中文字幕文本中找到精确匹配，从而正确渲染
  青绿色（&HC7D36F&）高亮下划线。
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# [Claude_Sonnet_4.6_Thinking_planning] 模型候选列表：按质量优先排序
# gemini-2.5-flash: 最高质量，但 20 RPD/日，跑多次后耗尽
# gemini-3.5-flash: 20 RPD/日，与 2.5 交替使用延长配额
# gemini-2.5-flash-lite: 轻量版，RPD 更高，翻译质量仍远超 Aliyun
_MODELS_TO_TRY = ["gemini-2.5-flash", "gemini-3.5-flash", "gemini-2.5-flash-lite"]

# [Claude_Sonnet_4.6_Thinking_planning] v1.1.0: 每批最多 50 段
# 277 段 1 次调用时模型输出被截断，分批后每次 ≤ 50 段，避免计数不符
_BATCH_SIZE = 50

# 指数退避参数
_INITIAL_RETRY_DELAY_S = 2
_MAX_RETRY_DELAY_S = 8
_MAX_RETRIES_PER_MODEL = 3


def extract_vocab_batch(
    english_texts: List[str],
    chinese_translations: Optional[List[str]] = None,
) -> Optional[List[Dict[str, Any]]]:
    """批量从英文字幕段落中提取难词词汇，并可选地与中文翻译句子对齐。

    [Claude_Sonnet_4.6_Thinking_planning] v1.1.0: 实现分批调用
    将输入按 _BATCH_SIZE 分批，逐批调用 Gemini，合并结果。
    单次调用 277 段会触发输出 token 截断，导致返回件数不足而整批丢弃。

    Args:
        english_texts: 英文字幕文本列表（按 segment 顺序）。
        chinese_translations: 可选的中文翻译文本列表（与 english_texts 一一对应）。

    Returns:
        每个 segment 对应的字典列表，或失败时返回 None。
    """
    if not english_texts:
        return []

    try:
        from config.settings import settings
        api_key = settings.gemini_api_key or ""
    except Exception:
        api_key = ""

    if not api_key:
        import os
        api_key = os.getenv("GEMINI_API_KEY", "")

    if not api_key:
        logger.warning("[vocab_helper] GEMINI_API_KEY not configured. Skipping vocab extraction.")
        return None

    try:
        from google import genai as _genai
        from google.genai import types as _genai_types
    except ImportError:
        logger.error("[vocab_helper] google-genai SDK not installed. Cannot extract vocab.")
        return None

    client = _genai.Client(api_key=api_key)

    # [Claude_Sonnet_4.6_Thinking_planning] v1.1.0: 分批处理，每批 _BATCH_SIZE 段
    all_results: List[Dict[str, Any]] = []
    total = len(english_texts)
    for batch_start in range(0, total, _BATCH_SIZE):
        batch_end = min(batch_start + _BATCH_SIZE, total)
        en_batch = english_texts[batch_start:batch_end]
        zh_batch = chinese_translations[batch_start:batch_end] if chinese_translations else None

        logger.info(f"[vocab_helper] Processing batch {batch_start//_BATCH_SIZE + 1} "
                    f"(segments {batch_start+1}-{batch_end}/{total})...")

        prompt = _build_prompt(en_batch, zh_batch)
        response = _call_with_retry(client, prompt, _genai_types)
        if response is None:
            logger.warning(f"[vocab_helper] Batch {batch_start//_BATCH_SIZE + 1} failed. Aborting.")
            return None

        batch_result = _parse_response(response.text, len(en_batch))
        if batch_result is None:
            logger.warning(f"[vocab_helper] Batch {batch_start//_BATCH_SIZE + 1} parse failed. Aborting.")
            return None

        all_results.extend(batch_result)

    logger.info(f"[vocab_helper] All batches completed. Total: {len(all_results)} segments.")
    return all_results


# ── Private helpers ────────────────────────────────────────────────────────────

def _build_prompt(
    english_texts: List[str],
    chinese_translations: Optional[List[str]],
) -> str:
    """[Claude_Sonnet_4.6_Thinking_planning] 构造双模式提示词。

    对齐模式（chinese_translations 提供时）：
        - 直接使用提供的中文翻译作为 translation 字段返回（原文不变）。
        - vocab 中的中文值必须是 chinese_translations 对应句子中的精确子字符串。
        - 这保证了 SubtitleStylist 的 apply_chinese_highlights 正则能够命中。

    翻译模式（chinese_translations 为 None 时）：
        - Gemini 自行翻译并提取词汇（传统 fallback 逻辑）。
    """
    if chinese_translations and len(chinese_translations) == len(english_texts):
        # 对齐模式：中文翻译已由阿里云/Google 提供，Gemini 只做词汇识别与子串对齐
        segments_payload = [
            {"english": en, "chinese": zh}
            for en, zh in zip(english_texts, chinese_translations)
        ]
        prompt = (
            "You are an expert English educator analyzing video subtitles.\n"
            "For each item in the input array, you are given:\n"
            "  - 'english': the original English subtitle text\n"
            "  - 'chinese': the already-translated Chinese subtitle text (DO NOT change it)\n\n"
            "Your task:\n"
            "1. Return the 'chinese' value UNCHANGED as the 'translation' field.\n"
            "2. From the English text, identify 2-3 key academic/difficult vocabulary "
            "words or phrases (CEFR B2-C2 / TOEFL / IELTS / GRE level). "
            "Do NOT extract common or easy words. If no difficult words exist, use an empty object {}.\n"
            "3. CRITICAL: For each extracted English word/phrase, its Chinese value in the 'vocab' "
            "object MUST be an EXACT SUBSTRING of the provided 'chinese' translation string. "
            "Use the shortest meaningful substring that corresponds to that English term. "
            "If no exact substring match is possible for a word, skip that word entirely.\n\n"
            "Return a JSON array (one object per input item, same order). Each object:\n"
            "  - \"translation\": string (the Chinese value verbatim from input)\n"
            "  - \"vocab\": object (English word/phrase keys → exact Chinese substring values)\n\n"
            f"Input:\n{json.dumps(segments_payload, ensure_ascii=False)}"
        )
    else:
        # 翻译模式：Gemini 自行翻译并提取词汇（fallback）
        prompt = (
            "You are an expert video subtitle translator and English educator. "
            "For each of the following English subtitle segments:\n"
            "1. Translate it into natural, native, and screen-friendly Chinese (zh-CN).\n"
            "2. Identify 2 to 3 key, academic, or difficult vocabulary words/phrases "
            "(CEFR B2-C2 or TOEFL/IELTS/GRE level) that are essential to the segment's meaning. "
            "CRITICAL: For each extracted word/phrase, its Chinese definition in the 'vocab' "
            "dictionary MUST be the exact substring as it appears in your translated 'translation' "
            "string. Do not extract common/easy words. If there are no difficult words, leave the "
            "vocabulary dictionary empty.\n"
            "Return a JSON array of objects (one for each segment in the exact same order). "
            "Each object must contain:\n"
            "  - \"translation\": string (Chinese translation)\n"
            "  - \"vocab\": object (English word/phrase keys → exact Chinese substring values)\n\n"
            f"Input segments:\n{json.dumps(english_texts, ensure_ascii=False)}"
        )
    return prompt


def _call_with_retry(client: Any, prompt: str, genai_types: Any) -> Optional[Any]:
    """[Claude_Sonnet_4.6_Thinking_planning] 多模型 Fallback + 指数退避重试。"""
    last_err = None
    response = None

    for model_name in _MODELS_TO_TRY:
        retry_delay = _INITIAL_RETRY_DELAY_S
        for attempt in range(_MAX_RETRIES_PER_MODEL):
            try:
                logger.info(f"[vocab_helper] Calling {model_name} (attempt {attempt + 1}/{_MAX_RETRIES_PER_MODEL})...")
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=genai_types.GenerateContentConfig(
                        response_mime_type="application/json"
                    ),
                )
                break  # 成功
            except Exception as e:
                last_err = e
                err_msg = str(e)
                is_rate_limit = (
                    "429" in err_msg
                    or "RESOURCE_EXHAUSTED" in err_msg
                    or "rate limit" in err_msg.lower()
                )
                is_fatal = (
                    "400" in err_msg
                    or "401" in err_msg
                    or "403" in err_msg
                    or "API_KEY" in err_msg
                )
                if is_fatal:
                    logger.error(f"[vocab_helper] {model_name} fatal client error: {e}")
                    raise
                if is_rate_limit and attempt < _MAX_RETRIES_PER_MODEL - 1:
                    wait = min(retry_delay, _MAX_RETRY_DELAY_S)
                    logger.warning(f"[vocab_helper] {model_name} rate limited. Retry in {wait}s...")
                    time.sleep(wait)
                    retry_delay *= 2
                    continue
                logger.warning(f"[vocab_helper] {model_name} failed: {e}. Trying next model.")
                break

        if response is not None:
            break

    if response is None:
        if last_err:
            logger.error(f"[vocab_helper] All models failed. Last error: {last_err}")
        return None

    return response


def _parse_response(text: str, expected_count: int) -> Optional[List[Dict[str, Any]]]:
    """[Claude_Sonnet_4.6_Thinking_planning] 解析并校验 Gemini JSON 响应。

    v1.1.0: 放宽计数校验 — 允许返回件数在 [expected_count*0.8, expected_count] 范围内，
    不足的条目由调用方补空 vocab。严格等值校验在大批量场景下过于脆弱。
    """
    try:
        result = json.loads(text)
        # 兼容部分模型返回顶级 dict 包装
        if isinstance(result, dict) and "translations" in result:
            result = result["translations"]
        elif isinstance(result, dict) and "list" in result:
            result = result["list"]

        if not isinstance(result, list) or len(result) == 0:
            logger.warning(f"[vocab_helper] Empty or non-list response.")
            return None

        # 允许小幅欠缺（模型偶尔合并相邻空段）
        if len(result) == expected_count:
            logger.info(f"[vocab_helper] Vocab extraction succeeded ({expected_count} segments).")
            return result
        elif len(result) >= int(expected_count * 0.8):
            logger.warning(
                f"[vocab_helper] Count mismatch: expected {expected_count}, got {len(result)}. "
                f"Padding remaining with empty vocab."
            )
            # 不足部分补空条目
            while len(result) < expected_count:
                result.append({"translation": "", "vocab": {}})
            return result[:expected_count]
        else:
            logger.warning(
                f"[vocab_helper] Count too low: expected {expected_count}, got {len(result)}. Discarding."
            )
            return None
    except Exception as e:
        logger.error(f"[vocab_helper] Failed to parse Gemini response: {e}\nRaw text: {text[:300]}")
        return None
