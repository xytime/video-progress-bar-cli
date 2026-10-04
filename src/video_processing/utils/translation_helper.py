# -*- coding: utf-8 -*-
"""统一翻译助手模块 — Google Translate 终级兜底。

提供单条翻译与批量翻译接口。主字幕质量链路由 Gemini/DeepSeek 承担；
本模块只提供无词汇对齐能力的终级兜底，不直接调用其他云厂商 SDK。

# Modification History
| Version | Date       | Author                     | Description |
| ------- | ---------- | -------------------------- | ----------- |
| 1.4.0   | 2026-10-05 | Codex | 逐段节流和有界退避，保留已完成缓存，供应商共用截止时间。 |
| 1.0.0   | 2026-06-08 | Claude_Sonnet_4.6_planning | 初始创建：高内聚翻译模块 |
| 1.3.0   | 2026-07-17 | Codex                      | 移除阿里云 MT 调用；仅保留 Google 终级翻译接口 |
| 1.3.1   | 2026-07-26 | Codex                      | 保留字符预算切块纯函数，维持字幕对齐回归保护 |
| 1.3.2   | 2026-08-17 | Codex                      | 拒绝 Google 返回的纯文本 HTTP 错误页，避免被当作非空字幕译文 |
| 1.3.3   | 2026-08-31 | Codex                      | Google 终级兜底显式使用受信 TLS 和有界请求超时，不再修改全局 requests 行为 |
| 1.3.4   | 2026-08-31 | Codex                      | Google 批次按整片 deadline 收紧每条请求，避免故障时逐段累积占满字幕阶段 |
"""

import logging
import hashlib
import json
import threading
import time
from contextlib import contextmanager
from typing import List
from pathlib import Path

import requests

from config.settings import settings
from .generated_content_validation import is_upstream_error_response
from .file_utils import write_json_atomically
from .translation_model_pool import classify_error

try:
    from deep_translator import GoogleTranslator
    from deep_translator import google as _deep_translator_google
except ImportError:
    GoogleTranslator = None  # type: ignore[assignment,misc]
    _deep_translator_google = None

logger = logging.getLogger(__name__)

_SEP = "\n###\n"
_GOOGLE_TRANSLATOR_LOCK = threading.RLock()


def _google_translate_timeout() -> tuple[int, int]:
    """返回 Google 终级兜底的连接/读取超时，避免单条请求无限占用字幕阶段。"""
    read_timeout = max(5, int(getattr(settings, "google_translate_request_timeout_seconds", 90) or 90))
    return min(20, read_timeout), read_timeout


def _google_translate_total_timeout() -> int:
    """返回一整片 Google 终级兜底的总预算，防止逐段超时累积。"""
    return max(30, int(getattr(settings, "google_translate_total_timeout_seconds", 300) or 300))


class _VerifiedGoogleRequests:
    """仅注入 deep_translator.google 的窄接口，绝不修改进程级 requests.Session。"""

    def __init__(self, deadline: float):
        self._deadline = deadline

    def get(self, *args, **kwargs):
        remaining_seconds = self._deadline - time.monotonic()
        if remaining_seconds <= 0:
            raise requests.Timeout("Google Translate batch budget exhausted")
        _, configured_read_timeout = _google_translate_timeout()
        connect_timeout = min(20, remaining_seconds / 2)
        read_timeout = min(configured_read_timeout, remaining_seconds - connect_timeout)
        kwargs["verify"] = True
        kwargs["timeout"] = (connect_timeout, read_timeout)
        return requests.get(*args, **kwargs)

    def __getattr__(self, name: str):
        return getattr(requests, name)


@contextmanager
def _bounded_google_translator_transport(deadline: float):
    """临时收紧第三方模块局部传输接口；锁内必定复原，其他 requests 用户不受影响。"""
    if _deep_translator_google is None:
        yield
        return
    with _GOOGLE_TRANSLATOR_LOCK:
        original_requests = _deep_translator_google.requests
        _deep_translator_google.requests = _VerifiedGoogleRequests(deadline)
        try:
            yield
        finally:
            _deep_translator_google.requests = original_requests


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
    *, deadline: float | None = None, cache_dir: Path | None = None,
    error_out: List[str] | None = None,
) -> List[str]:
    """批量翻译文本列表，使用 Google Translate 作为终级兜底。"""
    if not texts:
        return []
    return _google_translate_batch(texts, src_lang=src_lang, target_lang=target_lang,
                                   deadline=deadline, cache_dir=cache_dir, error_out=error_out)


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
    *, deadline: float | None = None, cache_dir: Path | None = None,
    error_out: List[str] | None = None,
) -> List[str]:
    """使用 deep_translator.GoogleTranslator 批量翻译并过滤错误页面。"""
    if not texts:
        return []
    if GoogleTranslator is None:
        logger.warning("[TransHelper] deep_translator 未安装，Google 终级兜底不可用。")
        return [""] * len(texts)
    local_deadline = time.monotonic() + _google_translate_total_timeout()
    deadline = min(deadline, local_deadline) if deadline is not None else local_deadline
    invalid_markers = ("<html", "cloudflare", "captcha", "attention required")
    def valid_translation(value) -> str:
        text = value.strip() if isinstance(value, str) else ""
        if any(marker in text.lower() for marker in invalid_markers) or is_upstream_error_response(text):
            return ""
        return text

    results = [""] * len(texts)
    cache_path = None
    if cache_dir is not None:
        identity = json.dumps(["google-v2", src_lang, target_lang, texts], ensure_ascii=False)
        signature = hashlib.sha256(identity.encode()).hexdigest()
        cache_path = cache_dir / f"{signature}.json"
        try:
            cached = json.loads(cache_path.read_text())
            if isinstance(cached, list) and len(cached) == len(texts):
                results = [valid_translation(value) for value in cached]
        except (OSError, ValueError):
            pass

    interval = settings.google_translate_interval_seconds
    next_request_at = time.monotonic()
    with _bounded_google_translator_transport(deadline):
        translator = GoogleTranslator(source=src_lang, target=target_lang)
        for index, source in enumerate(texts):
            if results[index]:
                continue
            for attempt in range(settings.google_translate_max_retries + 1):
                wait = max(0.0, next_request_at - time.monotonic())
                if time.monotonic() + wait >= deadline:
                    if error_out is not None:
                        error_out.append(f"Google batch budget exhausted at segment {index + 1}/{len(texts)}")
                    return results
                if wait:
                    time.sleep(wait)
                try:
                    value = valid_translation(translator.translate(source))
                    if not value:
                        raise ValueError("Google invalid or empty upstream response")
                    results[index] = value
                    if cache_path is not None:
                        write_json_atomically(cache_path, results)
                    break
                except Exception as exc:
                    category = classify_error(str(exc))
                    # deep-translator TooManyRequests 的消息不总含 HTTP 429。
                    if type(exc).__name__ == "TooManyRequests":
                        category = "rate_limit"
                    logger.warning("[TransHelper] Google segment %s/%s attempt %s failed: %s",
                                   index + 1, len(texts), attempt + 1, category)
                    if category not in {"rate_limit", "network"} or attempt >= settings.google_translate_max_retries:
                        if error_out is not None:
                            error_out.append(f"Google segment {index + 1}/{len(texts)}: {category}: {str(exc)[:240]}")
                        # 认证/限流/传输失败停止整个批次，不继续冲击同一服务。
                        if category in {"auth_or_permission", "rate_limit", "network"}:
                            return results
                        break
                    next_request_at = time.monotonic() + min(8.0, 2.0 ** (attempt + 1))
                finally:
                    next_request_at = max(next_request_at, time.monotonic() + interval)
    return results
