# -*- coding: utf-8 -*-
"""统一翻译助手模块 — 阿里云 MT 优先，Google Translate 自动降级。

提供单条翻译与批量翻译接口，所有翻译需求应通过此模块统一调用，
不应在其他模块中直接使用 deep_translator 或阿里云 SDK。

# Modification History
| Version | Date       | Author                     | Description |
| ------- | ---------- | -------------------------- | ----------- |
| 1.0.0   | 2026-06-08 | Claude_Sonnet_4.6_planning | 初始创建：高内聚翻译模块，阿里云 MT 优先 + Google Translate 降级兜底 |
"""

import logging
from typing import List, Optional

try:
    from deep_translator import GoogleTranslator  # [Claude_Sonnet_4.6_planning] top-level for testability
except ImportError:
    GoogleTranslator = None  # type: ignore[assignment,misc]

try:
    from config.settings import settings  # [Claude_Sonnet_4.6_planning] top-level for testability
except Exception:
    settings = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# 阿里云 MT 批量拼接常量
_SEP = "\n###\n"
_BATCH_SIZE = 25


def translate_batch_aliyun(
    texts: List[str],
    src_lang: str = "en",
    target_lang: str = "zh",
) -> Optional[List[str]]:
    """调用阿里云机器翻译通用版批量翻译文本列表。

    采用分隔符批量拼接策略（BATCH_SIZE=25），将多条翻译请求压缩为少量 API 调用。

    Args:
        texts: 待翻译文本列表。
        src_lang: 源语言代码（"en" / "auto" 等，默认 "en"）。
        target_lang: 目标语言代码（默认 "zh"，即普通话）。

    Returns:
        按入参顺序排列的翻译结果列表；若凭证未配置或调用失败则返回 None。
    """
    # 使用模块级 settings 对象（可在测试中 mock）
    _settings = settings
    if _settings is None:
        logger.debug("[AliyunMT] settings not available.")
        return None
    try:
        ak_id = _settings.aliyun_mt_access_key_id or ""
        ak_secret = _settings.aliyun_mt_access_key_secret or ""
    except Exception as e:
        logger.debug(f"[AliyunMT] Could not read settings: {e}")
        return None

    if not ak_id or not ak_secret:
        logger.info("[AliyunMT] ALIYUN_MT_ACCESS_KEY_ID/SECRET not configured. Skipping.")
        return None

    try:
        from alibabacloud_alimt20181012.client import Client as AlimtClient
        from alibabacloud_tea_openapi.models import Config as OpenApiConfig
        from alibabacloud_alimt20181012 import models as alimt_models
    except ImportError as e:
        logger.info(f"[AliyunMT] SDK not installed ({e}). Skipping.")
        return None

    try:
        # 标准化语言代码
        src = "en" if src_lang in ("en", "auto", None) else src_lang
        tgt = "zh" if target_lang in ("zh", "zh-CN", None) else target_lang

        config = OpenApiConfig(
            access_key_id=ak_id,
            access_key_secret=ak_secret,
            endpoint="mt.aliyuncs.com",
        )
        client = AlimtClient(config)

        translated: List[str] = [""] * len(texts)
        logger.info(
            f"[AliyunMT] Translating {len(texts)} texts "
            f"in batches of {_BATCH_SIZE} ({src} → {tgt})..."
        )

        for batch_start in range(0, len(texts), _BATCH_SIZE):
            batch_texts = texts[batch_start: batch_start + _BATCH_SIZE]
            non_empty_indices = [i for i, t in enumerate(batch_texts) if t and t.strip()]
            non_empty_texts = [batch_texts[i] for i in non_empty_indices]

            if not non_empty_texts:
                continue

            combined = _SEP.join(non_empty_texts)
            req = alimt_models.TranslateGeneralRequest(
                format_type="text",
                scene="general",
                source_language=src,
                source_text=combined[:5000],  # 安全截断，防止超限
                target_language=tgt,
            )
            resp = client.translate_general(req)

            if resp and resp.body and str(resp.body.code) == "200":
                result_text = resp.body.data.translated or ""
                parts = [p.strip() for p in result_text.split("###")]
                for local_idx, abs_idx in enumerate(non_empty_indices):
                    if local_idx < len(parts):
                        translated[batch_start + abs_idx] = parts[local_idx]
                    else:
                        logger.warning(
                            f"[AliyunMT] Batch split count mismatch at batch_start={batch_start}"
                        )
            else:
                code = resp.body.code if resp and resp.body else "unknown"
                logger.warning(
                    f"[AliyunMT] Non-200 code={code} for batch starting at index {batch_start}"
                )

        logger.info("[AliyunMT] Batch translation completed.")
        return translated

    except Exception as e:
        logger.error(f"[AliyunMT] Translation failed: {e}")
        return None


def translate_batch(
    texts: List[str],
    src_lang: str = "auto",
    target_lang: str = "zh-CN",
) -> List[str]:
    """批量翻译文本列表，优先使用阿里云 MT，失败时降级到 Google Translate。

    Args:
        texts: 待翻译文本列表。
        src_lang: 源语言代码（默认 "auto"）。
        target_lang: 目标语言代码（默认 "zh-CN"）。

    Returns:
        按入参顺序排列的翻译结果列表，翻译失败的条目返回空字符串 ""。
    """
    if not texts:
        return []

    # 尝试阿里云 MT
    aliyun_results = translate_batch_aliyun(texts, src_lang=src_lang, target_lang=target_lang)
    if aliyun_results is not None:
        return aliyun_results

    # 降级：Google Translate
    logger.warning("[TransHelper] Aliyun MT unavailable. Falling back to Google Translate.")
    return _google_translate_batch(texts, src_lang=src_lang, target_lang=target_lang)


def translate_text(
    text: str,
    src_lang: str = "auto",
    target_lang: str = "zh-CN",
) -> str:
    """翻译单条文本，优先使用阿里云 MT，失败时降级到 Google Translate。

    Args:
        text: 待翻译文本。
        src_lang: 源语言代码（默认 "auto"）。
        target_lang: 目标语言代码（默认 "zh-CN"）。

    Returns:
        翻译结果字符串；失败时返回原文。
    """
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
    """使用 deep_translator.GoogleTranslator 进行批量翻译（兜底实现）。

    内部使用，不应直接从其他模块调用。

    Returns:
        翻译结果列表；对每个失败条目返回空字符串 ""。
    """
    import re
    import time

    _GoogleTranslator = GoogleTranslator  # 使用模块级（可在测试中 mock）
    if _GoogleTranslator is None:
        logger.error("[GoogleTranslate] deep_translator not installed.")
        return [""] * len(texts)

    translator = _GoogleTranslator(source=src_lang, target=target_lang)
    translated_texts: List[str] = []
    batch_size = 30

    for i in range(0, len(texts), batch_size):
        batch = texts[i: i + batch_size]
        try:
            res = translator.translate_batch(batch)
            translated_texts.extend(res or [""] * len(batch))
        except Exception as e:
            logger.warning(f"[GoogleTranslate] Batch failed at index {i}: {e}. Retrying one by one.")
            for text in batch:
                translated = ""
                for _ in range(3):
                    try:
                        single = translator.translate(text)
                        translated = single if single else ""
                        time.sleep(0.5)
                        break
                    except Exception:
                        time.sleep(2)
                translated_texts.append(translated)

    # 过滤 HTML 垃圾响应（被风控时 Google 返回错误页面）
    clean_results: List[str] = []
    for text in translated_texts:
        if text and re.search(
            r"<html|<body|<div|captcha|that's an error|error 500|cloudflare",
            text,
            re.IGNORECASE,
        ):
            logger.warning("[GoogleTranslate] Detected HTML garbage response. Clearing.")
            clean_results.append("")
        else:
            clean_results.append(text if text else "")

    # 确保长度与输入一致
    while len(clean_results) < len(texts):
        clean_results.append("")
    return clean_results[:len(texts)]
