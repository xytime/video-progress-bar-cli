# -*- coding: utf-8 -*-
"""动态字幕模型池单元测试。"""

from pathlib import Path

from video_processing.utils.translation_model_pool import DynamicTranslationModelPool, classify_error


def test_model_pool_prefers_vocab_capable_provider(tmp_path: Path):
    pool = DynamicTranslationModelPool(tmp_path / "pool.json")
    assert pool.order(["google", "deepseek", "gemini"], required={"translate", "vocab"}) == ["gemini", "deepseek", "google"]


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


def test_model_pool_can_ignore_outer_provider_cooldown(tmp_path: Path):
    pool = DynamicTranslationModelPool(tmp_path / "pool.json")
    pool.record_failure("gemini", "429 RESOURCE_EXHAUSTED")
    assert pool.order(["gemini", "deepseek"], ignore_cooldown={"gemini"}) == ["gemini", "deepseek"]


def test_model_pool_merge_preserves_model_cooldown_from_another_instance(tmp_path: Path):
    path = tmp_path / "pool.json"
    outer = DynamicTranslationModelPool(path)
    inner = DynamicTranslationModelPool(path)
    inner.record_failure("gemini-2.5-flash", "429 RESOURCE_EXHAUSTED")
    outer.record_quality("gemini", score=90)
    restored = DynamicTranslationModelPool(path)
    assert restored.snapshot()["gemini-2.5-flash"]["last_error_class"] == "rate_limit"
    assert restored.snapshot()["gemini"]["quality_score"] > 70
