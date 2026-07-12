# -*- coding: utf-8 -*-
"""动态字幕模型池单元测试。"""

from pathlib import Path

from video_processing.utils.translation_model_pool import DynamicTranslationModelPool, classify_error


def test_model_pool_prefers_vocab_capable_provider(tmp_path: Path):
    pool = DynamicTranslationModelPool(tmp_path / "pool.json")
    assert pool.order(["aliyun", "deepseek", "gemini"], required={"translate", "vocab"}) == ["gemini", "deepseek", "aliyun"]


def test_model_pool_cools_rate_limited_provider_and_persists(tmp_path: Path):
    path = tmp_path / "pool.json"
    pool = DynamicTranslationModelPool(path)
    pool.record_failure("gemini", "429 RESOURCE_EXHAUSTED quota")
    assert classify_error("10009 permission denied") == "auth_or_permission"
    assert "gemini" not in pool.order(["gemini", "deepseek"])
    restored = DynamicTranslationModelPool(path)
    assert restored.snapshot()["gemini"]["last_error_class"] == "rate_limit"


def test_model_pool_cools_only_the_rate_limited_gemini_model(tmp_path: Path):
    pool = DynamicTranslationModelPool(tmp_path / "pool.json")
    pool.record_failure("gemini-2.5-flash", "429 RESOURCE_EXHAUSTED")
    ordered = pool.order(["gemini-2.5-flash", "gemini-3.1-flash-lite"], required={"translate", "vocab"})
    assert ordered == ["gemini-3.1-flash-lite"]
