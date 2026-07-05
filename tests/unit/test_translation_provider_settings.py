# -*- coding: utf-8 -*-
"""Unit tests for subtitle translation provider settings.

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-05 | Codex  | 初始创建：覆盖字幕翻译供应商顺序配置解析 |
"""

import sys
from pathlib import Path

_src_root = Path(__file__).parent.parent.parent / "src"
if str(_src_root) not in sys.path:
    sys.path.insert(0, str(_src_root))

from config.settings import Settings  # noqa: E402


def test_default_subtitle_translation_provider_order():
    settings = Settings(_env_file=None)

    assert settings.subtitle_translation_provider_order_list == ["gemini", "aliyun", "google"]


def test_subtitle_translation_provider_order_filters_unknowns_and_duplicates():
    settings = Settings(
        _env_file=None,
        subtitle_translation_provider_order="aliyun,deepseek,google,aliyun,gemini",
    )

    assert settings.subtitle_translation_provider_order_list == ["aliyun", "google", "gemini"]


def test_empty_subtitle_translation_provider_order_falls_back_to_default():
    settings = Settings(_env_file=None, subtitle_translation_provider_order="unknown,,")

    assert settings.subtitle_translation_provider_order_list == ["gemini", "aliyun", "google"]
