# -*- coding: utf-8 -*-
"""词汇提取助手 — 封装 Gemini API 难词提取与中文对齐逻辑

# Modification History
| Version | Date       | Author                              | Description                                                              |
| ------- | ---------- | ----------------------------------- | ------------------------------------------------------------------------ |
| 1.0.0   | 2026-06-08 | Claude_Sonnet_4.6_Thinking_planning | 初始创建：从 caption_processor.py 抽取 Gemini 生词提取与对齐职责，实现高内聚低耦合 |
| 1.1.0   | 2026-06-08 | Claude_Sonnet_4.6_Thinking_planning | 实现分批调用（50段/次）解决277段场景下输出截断导致计数不符的问题；放宽计数校验 |
| 1.2.0   | 2026-06-15 | Claude_Opus_4.8 | [BUG-4] prompt 给每段加 id 并要求回显；_parse_response 按 id 重对齐到定长列表，缺失段留空于正确位置，废弃「补空错位」级联 |
| 1.3.0   | 2026-06-28 | Claude_Opus_4.8 | 词汇质量：①双模式 prompt 增加「禁止抽取周知专有名词/常识词」约束；②新增 _STOPWORDS + _filter_vocab，解析后剔除 Wall Street/Google 等周知词，避免占用词汇卡而无学习价值 |
| 1.4.0   | 2026-07-05 | Codex | 支持注入全片翻译上下文，避免逐批字幕缺少主题与金融术语语境 |
| 1.5.0   | 2026-07-06 | Codex | 强化 Gemini 翻译 prompt 全局上下文硬约束，降低金融 close/金额单位误译 |
| 1.6.0   | 2026-07-06 | Codex | 复用 translation_prompt_constraints，避免 provider 约束漂移 |
| 1.7.0   | 2026-07-09 | Codex | Gemini Client 显式设置 HTTP timeout=90 秒，避免代理/上游 API 半开连接导致词汇提取无限等待 |
| 1.8.0   | 2026-07-13 | Codex | 词汇标准改为 PET/B1 起，保留专有名词，消除历史黑名单漏词 |
| 1.9.0   | 2026-07-13 | Codex | 保留每条最多三项词汇卡，按学习价值取舍避免字幕版面溢出 |
| 2.0.0   | 2026-07-13 | Codex | PET/B1 改为最低门槛，优先 C1-C2、专业术语和关键专有名词 |
| 2.1.0   | 2026-07-13 | Codex | Gemini 改为模型级动态池，接入 3.1 Flash Lite 并压缩批量/上下文防 TPM 峰值 |
| 2.2.0   | 2026-07-25 | Codex | 修正 google-genai HttpOptions.timeout 单位为毫秒，避免 90ms TLS 握手超时导致字幕翻译全失败 |
| 2.3.0   | 2026-08-02 | Codex | 生词结果可选回传十级难度，供独立新闻精读卡片按全文密度筛选。 |
| 2.4.0   | 2026-08-02 | Codex | 支持独立学习卡按全文请求更多候选词，并回传 IPA 音标，不改变字幕默认三词限制。 |
| 2.5.0   | 2026-08-02 | Codex | 学习卡可声明候选词下限，避免模型在长正文中保守少抽。 |

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

from .translation_prompt_constraints import render_translation_constraints
from .translation_model_pool import DynamicTranslationModelPool, classify_error

logger = logging.getLogger(__name__)

def _filter_vocab(vocab: Any) -> Dict[str, Any]:
    """保留模型返回的有效词汇；PET/B1 及专有名词均属于学习内容。"""
    return vocab if isinstance(vocab, dict) else {}

# 模型级池：先保留质量最好的 Flash；一旦单模型冷却，才使用免费 Lite 容量。
_MODELS_TO_TRY = ["gemini-2.5-flash", "gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-2.5-flash-lite"]

# [Claude_Sonnet_4.6_Thinking_planning] v1.1.0: 每批最多 50 段
# 277 段 1 次调用时模型输出被截断，分批后每次 ≤ 50 段，避免计数不符
_BATCH_SIZE = 25
_MAX_CONTEXT_CHARS = 6000
_GENAI_HTTP_TIMEOUT_MS = 90_000

# 指数退避参数
_INITIAL_RETRY_DELAY_S = 2
_MAX_RETRY_DELAY_S = 8
_MAX_RETRIES_PER_MODEL = 3


def extract_vocab_batch(
    english_texts: List[str],
    chinese_translations: Optional[List[str]] = None,
    context_text: str = "",
    model_out: Optional[List[str]] = None,
    max_vocabulary_items: int = 3,
    min_vocabulary_items: int = 0,
) -> Optional[List[Dict[str, Any]]]:
    """批量从英文字幕段落中提取难词词汇，并可选地与中文翻译句子对齐。

    [Claude_Sonnet_4.6_Thinking_planning] v1.1.0: 实现分批调用
    将输入按 _BATCH_SIZE 分批，逐批调用 Gemini，合并结果。
    单次调用 277 段会触发输出 token 截断，导致返回件数不足而整批丢弃。

    Args:
        english_texts: 英文字幕文本列表（按 segment 顺序）。
        chinese_translations: 可选的中文翻译文本列表（与 english_texts 一一对应）。
        context_text: 可选的全片翻译上下文，注入每个批次 prompt。
        max_vocabulary_items: 每个输入单元的候选词上限；字幕默认 3，学习卡可提高。
        min_vocabulary_items: 正文候选词下限；仅在存在足够 B1+ 词时生效。

    Returns:
        每个 segment 对应的字典列表，或失败时返回 None。
    """
    if not english_texts:
        return []
    if not 1 <= max_vocabulary_items <= 12:
        raise ValueError("max_vocabulary_items 必须在 1 到 12 之间")
    if not 0 <= min_vocabulary_items <= max_vocabulary_items:
        raise ValueError("min_vocabulary_items 必须在 0 到 max_vocabulary_items 之间")

    try:
        from config.settings import settings as settings_obj
        api_key = settings_obj.gemini_api_key or ""
    except Exception:
        settings_obj = None
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

    client = _genai.Client(
        api_key=api_key,
        http_options=_genai_types.HttpOptions(timeout=_GENAI_HTTP_TIMEOUT_MS),
    )

    # [Claude_Sonnet_4.6_Thinking_planning] v1.1.0: 分批处理，每批 _BATCH_SIZE 段
    all_results: List[Dict[str, Any]] = []
    total = len(english_texts)
    for batch_start in range(0, total, _BATCH_SIZE):
        batch_end = min(batch_start + _BATCH_SIZE, total)
        en_batch = english_texts[batch_start:batch_end]
        zh_batch = chinese_translations[batch_start:batch_end] if chinese_translations else None

        logger.info(f"[vocab_helper] Processing batch {batch_start//_BATCH_SIZE + 1} "
                    f"(segments {batch_start+1}-{batch_end}/{total})...")

        prompt = _build_prompt(
            en_batch, zh_batch, context_text=context_text, max_vocabulary_items=max_vocabulary_items,
            min_vocabulary_items=min_vocabulary_items,
        )
        state_path = (
            getattr(settings_obj, "project_root", None) / "output" / "translation_model_pool.json"
            if getattr(settings_obj, "project_root", None) is not None else None
        )
        call_result = _call_with_retry(client, prompt, _genai_types, state_path=state_path)
        if call_result is None:
            logger.warning(f"[vocab_helper] Batch {batch_start//_BATCH_SIZE + 1} failed. Aborting.")
            return None
        response, model_name = call_result

        batch_result = _parse_response(response.text, len(en_batch))
        if batch_result is None:
            DynamicTranslationModelPool(state_path).record_failure(
                model_name, "invalid aligned JSON response", category="invalid_response",
            )
            logger.warning(f"[vocab_helper] Batch {batch_start//_BATCH_SIZE + 1} parse failed. Aborting.")
            return None
        if model_out is not None and model_name not in model_out:
            model_out.append(model_name)

        all_results.extend(batch_result)

    logger.info(f"[vocab_helper] All batches completed. Total: {len(all_results)} segments.")
    return all_results


# ── Private helpers ────────────────────────────────────────────────────────────

def _build_prompt(
    english_texts: List[str],
    chinese_translations: Optional[List[str]],
    context_text: str = "",
    max_vocabulary_items: int = 3,
    min_vocabulary_items: int = 0,
) -> str:
    """[Claude_Sonnet_4.6_Thinking_planning] 构造双模式提示词。

    对齐模式（chinese_translations 提供时）：
        - 直接使用提供的中文翻译作为 translation 字段返回（原文不变）。
        - vocab 中的中文值必须是 chinese_translations 对应句子中的精确子字符串。
        - 这保证了 SubtitleStylist 的 apply_chinese_highlights 正则能够命中。

    翻译模式（chinese_translations 为 None 时）：
        - Gemini 自行翻译并提取词汇（传统 fallback 逻辑）。
    """
    # [Claude_Opus_4.8] BUG-4: 每个输入项带 0-based 整数 id，要求模型逐项回显 id。
    # 解析端按 id 重对齐到定长列表——即便模型漏返/合并某段，也只是该 id 槽位留空（位置正确），
    # 绝不发生「该段之后整体串位」的级联错位。
    context_block = _render_context_block(context_text)
    target_instruction = (
        f"The text has enough learning value: return at least {min_vocabulary_items} distinct useful B1+ items "
        "when they exist; include contextual B1-B2 terms after C1/C2 terms. "
        if min_vocabulary_items else ""
    )
    if chinese_translations and len(chinese_translations) == len(english_texts):
        # 对齐模式：中文翻译已由阿里云/Google 提供，Gemini 只做词汇识别与子串对齐
        segments_payload = [
            {"id": i, "english": en, "chinese": zh}
            for i, (en, zh) in enumerate(zip(english_texts, chinese_translations))
        ]
        prompt = (
            "You are an expert English educator analyzing video subtitles.\n"
            "For each item in the input array, you are given:\n"
            "  - 'id': an integer index you MUST echo back unchanged\n"
            "  - 'english': the original English subtitle text\n"
            "  - 'chinese': the already-translated Chinese subtitle text (DO NOT change it)\n\n"
            f"{context_block}"
            "Your task:\n"
            "1. Return the 'chinese' value UNCHANGED as the 'translation' field.\n"
            "2. CEFR B1 (PET) is the minimum eligibility threshold, not a requirement to extract every B1 "
            "word. For every extracted item, return its difficulty in a separate 'vocab_levels' object using "
            "integer 1-10 (B1/PET=3, B2=5, C1=7, C2=9, specialist=10). "
            f"Extract up to {max_vocabulary_items} items. Prioritise C1-C2 vocabulary, specialist academic/technical/"
            f"{target_instruction}"
            "finance/economics terms, meaningful proper nouns (people, organisations, products, places, "
            "frameworks, acronyms), then B2 and PET/B1 words only when especially useful in context. Do not "
            "extract A1-A2 words, function words, trivial greetings, or low-learning-value words. Prefer "
            "phrases over component words. If there is no worthwhile PET-or-higher vocabulary or meaningful "
            "proper noun, "
            "use an empty object {}.\n"
            "3. CRITICAL: For each extracted English word/phrase, its Chinese value in the 'vocab' "
            "object MUST be an EXACT SUBSTRING of the provided 'chinese' translation string. "
            "Use the shortest meaningful substring that corresponds to that English term. "
            "If no exact substring match is possible for a word, skip that word entirely.\n\n"
            "Return a JSON array with EXACTLY ONE object per input item — never merge, drop, or reorder. "
            "Each object:\n"
            "  - \"id\": integer (echo the input item's id verbatim)\n"
            "  - \"translation\": string (the Chinese value verbatim from input)\n"
            "  - \"vocab\": object (English word/phrase keys → exact Chinese substring values)\n"
            "  - \"vocab_levels\": object (same English keys → integer 1-10)\n\n"
            "  - \"vocab_phonetics\": object (same English keys → IPA pronunciation, e.g. /ˈlaɪkwɪdɪti/)\n\n"
            f"Input:\n{json.dumps(segments_payload, ensure_ascii=False)}"
        )
    else:
        # 翻译模式：Gemini 自行翻译并提取词汇（fallback）
        segments_payload = [{"id": i, "english": en} for i, en in enumerate(english_texts)]
        prompt = (
            "You are an expert video subtitle translator and English educator. "
            "Each input item has an integer 'id' (echo it back unchanged) and 'english' text. "
            f"{context_block}"
            "For each segment:\n"
            "1. Translate it into natural, native, and screen-friendly Chinese (zh-CN).\n"
            "2. CEFR B1 (PET) is the minimum eligibility threshold, not a requirement to extract every B1 word. "
            "For every extracted item, return its difficulty in a separate 'vocab_levels' object using integer "
            "1-10 (B1/PET=3, B2=5, C1=7, C2=9, specialist=10). "
            f"Extract up to {max_vocabulary_items} items. Prioritise C1-C2 vocabulary, specialist academic/technical/finance/"
            f"{target_instruction}"
            "economics terms, meaningful proper nouns (people, organisations, products, places, frameworks, "
            "acronyms), then B2 and PET/B1 words only when especially useful in context. Do not extract A1-A2 "
            "words, function words, trivial greetings, or low-learning-value words. Prefer phrases over "
            "component words. "
            "CRITICAL: For each extracted word/phrase, its Chinese definition in the 'vocab' "
            "dictionary MUST be the exact substring as it appears in your translated 'translation' "
            "string. If there is no B1+ vocabulary or proper noun, leave the "
            "vocabulary dictionary empty.\n"
            "Return a JSON array with EXACTLY ONE object per input item — never merge, drop, or reorder. "
            "Each object must contain:\n"
            "  - \"id\": integer (echo the input item's id verbatim)\n"
            "  - \"translation\": string (Chinese translation)\n"
            "  - \"vocab\": object (English word/phrase keys → exact Chinese substring values)\n"
            "  - \"vocab_levels\": object (same English keys → integer 1-10)\n\n"
            "  - \"vocab_phonetics\": object (same English keys → IPA pronunciation, e.g. /ˈlaɪkwɪdɪti/)\n\n"
            f"Input segments:\n{json.dumps(segments_payload, ensure_ascii=False)}"
        )
    return prompt


def _render_context_block(context_text: str) -> str:
    if not context_text or not context_text.strip():
        return ""
    normalized = context_text.strip()
    if len(normalized) > _MAX_CONTEXT_CHARS:
        normalized = normalized[:_MAX_CONTEXT_CHARS] + "\n[context truncated for rate-limit safety]"
    return f"{render_translation_constraints(normalized)}\n\n"


def _call_with_retry(client: Any, prompt: str, genai_types: Any, *, state_path=None) -> Optional[tuple[Any, str]]:
    """模型级动态 fallback；429 立即冷却切换，网络问题才短暂重试。"""
    last_err = None
    response = None
    pool = DynamicTranslationModelPool(state_path)

    for model_name in pool.order(_MODELS_TO_TRY, required={"translate", "vocab"}):
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
                response = (response, model_name)
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
                error_class = classify_error(err_msg)
                if is_rate_limit:
                    pool.record_failure(model_name, err_msg, category=error_class)
                    logger.warning(f"[vocab_helper] {model_name} rate limited; cooling it and trying another model.")
                    break
                if is_fatal:
                    pool.record_failure(model_name, err_msg, category=error_class)
                    logger.error(f"[vocab_helper] {model_name} fatal client error: {e}. Trying next model.")
                    break
                if attempt < _MAX_RETRIES_PER_MODEL - 1:
                    wait = min(retry_delay, _MAX_RETRY_DELAY_S)
                    logger.warning(f"[vocab_helper] {model_name} transient failure. Retry in {wait}s...")
                    time.sleep(wait)
                    retry_delay *= 2
                    continue
                pool.record_failure(model_name, err_msg, category=error_class)
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
    """[Claude_Opus_4.8] v1.2.0 BUG-4: 解析并【按 id 重对齐】Gemini JSON 响应。

    每个返回项应回显 0-based 整数 "id"。按 id 放回定长列表（长度 expected_count），
    缺失的 id 槽位以空条目占位——位置永远正确，绝不发生「整体串位」级联错位。

    回退兼容：若模型完全没回显 id，则仅在数量【完全一致】时按顺序映射；
    数量不一致则判定失败（返回 None，交由上层 fallback），绝不再做「补空错位」。
    """
    def _norm(item: Any) -> Dict[str, Any]:
        if not isinstance(item, dict):
            return {"translation": "", "vocab": {}}
        vocab = _filter_vocab(item.get("vocab", {}) or {})
        normalized = {"translation": item.get("translation", "") or "", "vocab": vocab}
        raw_levels = item.get("vocab_levels")
        if isinstance(raw_levels, dict):
            normalized["vocab_levels"] = {
                word: max(1, min(10, int(raw_levels[word])))
                for word in vocab
                if isinstance(raw_levels.get(word), (int, float, str))
                and str(raw_levels[word]).strip().isdigit()
            }
        raw_phonetics = item.get("vocab_phonetics")
        if isinstance(raw_phonetics, dict):
            normalized["vocab_phonetics"] = {
                word: str(raw_phonetics[word]).strip()
                for word in vocab
                if isinstance(raw_phonetics.get(word), str) and raw_phonetics[word].strip()
            }
        return normalized

    _EMPTY = {"translation": "", "vocab": {}}
    try:
        result = json.loads(text)
        # 兼容部分模型返回顶级 dict 包装
        if isinstance(result, dict) and "translations" in result:
            result = result["translations"]
        elif isinstance(result, dict) and "list" in result:
            result = result["list"]

        if not isinstance(result, list) or len(result) == 0:
            logger.warning("[vocab_helper] Empty or non-list response.")
            return None

        # bool 是 int 子类，需排除（避免把 True/False 当作 id）
        has_ids = any(isinstance(it, dict) and isinstance(it.get("id"), int)
                      and not isinstance(it.get("id"), bool) for it in result)

        if has_ids:
            slots: List[Optional[Dict[str, Any]]] = [None] * expected_count
            placed = 0
            for it in result:
                if not isinstance(it, dict):
                    continue
                idx = it.get("id")
                if isinstance(idx, bool) or not isinstance(idx, int):
                    continue
                if 0 <= idx < expected_count and slots[idx] is None:
                    slots[idx] = _norm(it)
                    placed += 1
            if placed < int(expected_count * 0.8):
                logger.warning(f"[vocab_helper] Too few id-aligned items: {placed}/{expected_count}. Discarding.")
                return None
            if placed < expected_count:
                logger.warning(
                    f"[vocab_helper] {expected_count - placed} segment(s) missing; "
                    f"left EMPTY at correct index (no positional shift)."
                )
            return [s if s is not None else dict(_EMPTY) for s in slots]

        # 无 id 回显：仅当数量完全一致才安全地顺序映射；否则判失败（绝不补空错位）
        if len(result) == expected_count:
            logger.info(f"[vocab_helper] Vocab extraction succeeded ({expected_count} segments, positional).")
            return [_norm(it) for it in result]
        logger.warning(
            f"[vocab_helper] No id echo and count mismatch (got {len(result)}, expected {expected_count}). "
            f"Discarding to avoid subtitle desync."
        )
        return None
    except Exception as e:
        logger.error(f"[vocab_helper] Failed to parse Gemini response: {e}\nRaw text: {text[:300]}")
        return None
