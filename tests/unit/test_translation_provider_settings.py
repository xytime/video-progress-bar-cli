# -*- coding: utf-8 -*-
"""Unit tests for subtitle translation provider settings.

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.5.0   | 2026-08-21 | Codex  | 覆盖 yt-dlp 下载总超时配置 |
| 1.6.0   | 2026-08-25 | Codex  | 覆盖受限 WeChat 桌面快捷授权默认关闭及环境模板说明。 |
| 1.0.0   | 2026-07-05 | Codex  | 初始创建：覆盖字幕翻译供应商顺序配置解析 |
| 1.1.0   | 2026-07-05 | Codex  | 覆盖 DeepSeek provider 配置解析 |
| 1.4.0   | 2026-08-20 | Codex  | 显式隔离宿主环境变量，确保 RSS 默认行为测试不受部署密钥污染。 |
| 1.3.0   | 2026-07-17 | Codex  | 移除阿里云配置，固定 Gemini→DeepSeek→Google 质量链路 |
"""

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError
_src_root = Path(__file__).parent.parent.parent / "src"
if str(_src_root) not in sys.path:
    sys.path.insert(0, str(_src_root))

from config.settings import Settings  # noqa: E402


def test_default_subtitle_translation_provider_order():
    settings = Settings(_env_file=None)

    assert settings.subtitle_translation_provider_order_list == ["gemini", "deepseek", "google"]


def test_subtitle_translation_provider_order_filters_unknowns_and_duplicates():
    settings = Settings(
        _env_file=None,
        subtitle_translation_provider_order="unknown,deepseek,google,deepseek,gemini",
    )

    assert settings.subtitle_translation_provider_order_list == ["deepseek", "google", "gemini"]


def test_empty_subtitle_translation_provider_order_falls_back_to_default():
    settings = Settings(_env_file=None, subtitle_translation_provider_order="unknown,,")

    assert settings.subtitle_translation_provider_order_list == ["gemini", "deepseek", "google"]


def test_dubbing_refinement_provider_order_defaults_to_deepseek_during_agy_shadow():
    settings = Settings(_env_file=None)

    assert settings.dubbing_script_refinement_provider_order_list == ["deepseek"]


def test_translation_provider_env_example_documents_required_keys():
    env_example = Path(__file__).parent.parent.parent / ".env.example"
    content = env_example.read_text(encoding="utf-8")

    assert "SUBTITLE_TRANSLATION_PROVIDER_ORDER=" in content
    assert "DEEPSEEK_API_KEY=" in content
    assert "DEEPSEEK_BASE_URL=" in content
    assert "DEEPSEEK_MODEL=" in content
    assert "YOUTUBE_DATA_API_KEY=" in content


def test_youtube_catalog_defaults_to_rss_without_an_api_key(monkeypatch):
    monkeypatch.delenv("YOUTUBE_DATA_API_KEY", raising=False)
    settings = Settings(_env_file=None)

    assert settings.youtube_data_api_key == ""
    assert settings.youtube_data_api_timeout_sec == 20


def test_youtube_download_timeout_is_bounded_and_configurable():
    settings = Settings(_env_file=None, youtube_download_timeout_seconds=123)

    assert settings.youtube_download_timeout_seconds == 123


def test_wechat_desktop_quick_login_is_opt_in_with_bounded_timeout():
    settings = Settings(_env_file=None)

    assert settings.enable_wechat_desktop_quick_login is False
    assert settings.wechat_desktop_quick_login_timeout_seconds == 15

    with pytest.raises(ValidationError):
        Settings(_env_file=None, wechat_desktop_quick_login_timeout_seconds=0)


def test_env_example_documents_wechat_desktop_quick_login_preflight():
    env_example = Path(__file__).parent.parent.parent / ".env.example"
    content = env_example.read_text(encoding="utf-8")

    assert "ENABLE_WECHAT_DESKTOP_QUICK_LOGIN=false" in content
    assert "WECHAT_DESKTOP_QUICK_LOGIN_TIMEOUT_SECONDS=15" in content
