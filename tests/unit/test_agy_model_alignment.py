"""agy 模型换代守卫：默认配置不得指向已退役模型，且别名映射可解析。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-21 | Antigravity | 新增：防止已退役 agy 模型名回流到默认配置。 |
"""

from config.settings import AGY_DEFAULT_MODEL, Settings
from video_processing.utils.agy_provider import _RETIRED_MODEL_ALIASES, _normalize_agy_model

_AGY_FIELDS = (
    "wechat_reply_agy_model",
    "copywriter_agy_model",
    "agy_subtitle_model",
    "antigravity_model",
    "english_world_antigravity_model",
)


def test_agy_defaults_not_retired():
    for name in _AGY_FIELDS:
        default = Settings.model_fields[name].default
        assert default == AGY_DEFAULT_MODEL
        assert default not in _RETIRED_MODEL_ALIASES, name


def test_retired_alias_resolves_to_default():
    assert _normalize_agy_model("gemini-3.7-flash-high") == AGY_DEFAULT_MODEL
    assert _normalize_agy_model(AGY_DEFAULT_MODEL) == AGY_DEFAULT_MODEL
