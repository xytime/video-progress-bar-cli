"""Codex 最后一层兜底的正式文案/字幕接线验收。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-03 | Codex | 现有成功短路、冷却回退、严格质量和失败延后。 |
| 1.1.0 | 2026-11-01 | Grok Bot | 全文案供应商顺序 agy→codex→grok→gemini、grok 执行者与延后保留。 |
"""

import json
from pathlib import Path

import pytest

from config.settings import Settings
from scripts import copywriter
from video_processing.processors import caption_processor as caption
from video_processing.utils.codex_text_provider import CodexTextError, CodexTextResult
from video_processing.utils.subtitle_translation_provider import SubtitleTranslationCandidate


RAW = {"short_title": "凝胶打印突破重力", "display_title": "", "hook_subtitle": "制造的新方法",
       "wechat_copy": "凝胶中的三维打印，为复杂结构制造提供了新方法。视频介绍这种制造技术的原理与应用。",
       "engagement_post": "", "category": "科技", "content_hints": ["manufacturing"], "content_label": ""}
SOURCE = "The Gravity-Defying Future of Manufacturing"
DESCRIPTION = "Printing in gel enables complex structures and new manufacturing methods."


def _settings(tmp_path, enabled=True, **kwargs):
    kwargs.setdefault("copywriter_title_provider_order", "agy,codex")
    return Settings(_env_file=None, default_output_dir=tmp_path,
                    enable_codex_text_fallback=enabled, copywriter_content_provider="agy", **kwargs)


def _deferred(*args, **kwargs):
    raise copywriter.CopyProviderDeferred(9999999999, "cooldown")


def test_existing_copy_success_never_calls_codex(tmp_path, monkeypatch):
    monkeypatch.setattr(copywriter, "settings", _settings(tmp_path))
    monkeypatch.setattr(copywriter, "_generate_existing_wechat_content", lambda *a: {"copy": "已有文案"})
    def forbidden(*a, **k):
        pytest.fail("existing accepted copy must short circuit")
    monkeypatch.setattr(copywriter, "run_codex_structured", forbidden)
    assert copywriter.generate_wechat_content(SOURCE, DESCRIPTION) == {"copy": "已有文案"}


def test_disabled_copy_preserves_provider_deferral(tmp_path, monkeypatch):
    monkeypatch.setattr(copywriter, "settings", _settings(tmp_path, False))
    monkeypatch.setattr(copywriter, "_generate_existing_wechat_content", _deferred)
    with pytest.raises(copywriter.CopyProviderDeferred, match="cooldown"):
        copywriter.generate_wechat_content(SOURCE, DESCRIPTION)


def test_agy_cooldown_recovers_through_host_quality_and_preserves_audit(tmp_path, monkeypatch):
    monkeypatch.setattr(copywriter, "settings", _settings(tmp_path))
    monkeypatch.setattr(copywriter, "_generate_existing_wechat_content", _deferred)
    def run(prompt, **kwargs):
        assert kwargs["model"] == "gpt-5.6-luna" and kwargs["timeout_sec"] <= 120
        return CodexTextResult(kwargs["validate"](RAW), kwargs["model"], {"input_tokens": 50}, 10)
    monkeypatch.setattr(copywriter, "run_codex_structured", run)
    audit = tmp_path / "quality.json"
    content = copywriter.generate_wechat_content(SOURCE, DESCRIPTION, audit_path=audit)
    events = json.loads(audit.read_text())["events"]
    assert content["short_title"] == RAW["short_title"]
    assert events[0]["provider"] == "agy" and not events[0]["selected"]
    assert events[-1]["provider"] == "codex:gpt-5.6-luna" and events[-1]["selected"]
    assert events[-1]["usage"] == {"input_tokens": 50}


def test_codex_quota_remains_deferred_without_retries_or_content(tmp_path, monkeypatch):
    monkeypatch.setattr(copywriter, "settings", _settings(tmp_path))
    monkeypatch.setattr(copywriter, "_generate_existing_wechat_content", _deferred)
    calls = []
    def run(*args, **kwargs):
        calls.append(1)
        raise CodexTextError("quota", 9999999999)
    monkeypatch.setattr(copywriter, "run_codex_structured", run)
    with pytest.raises(copywriter.CopyProviderDeferred) as error:
        copywriter.generate_wechat_content(SOURCE, DESCRIPTION, audit_path=tmp_path / "quality.json")
    assert error.value.until == 9999999999 and calls == [1]
    assert not list(tmp_path.glob("*_title.txt"))


def test_codex_keeps_configured_position_and_is_opt_in(tmp_path):
    assert _settings(tmp_path, False, subtitle_translation_provider_order="codex,google,gemini").subtitle_translation_provider_order_list == ["google", "gemini"]
    assert _settings(tmp_path, subtitle_translation_provider_order="codex,google,gemini").subtitle_translation_provider_order_list == ["codex", "google", "gemini"]
    # 未写入顺序的旧配置仍在末尾追加一次 Codex 兜底，不重复。
    assert _settings(tmp_path, subtitle_translation_provider_order="google,gemini").subtitle_translation_provider_order_list == ["google", "gemini", "codex"]


def _processor():
    # 避免真实模型加载；本测试只执行正式候选仲裁方法。
    processor = object.__new__(caption.AutoCaptionProcessor)
    processor.input_path = Path("sample.mp4")
    processor.src_lang = "en"
    processor.target_lang = "zh-CN"
    return processor


@pytest.mark.parametrize("first_success", [False, True])
def test_subtitle_existing_order_then_codex_preserves_source_and_timeline(tmp_path, monkeypatch, first_success):
    monkeypatch.setattr(caption, "settings", _settings(tmp_path, subtitle_translation_provider_order="gemini,google"))
    processor = _processor()
    calls = []
    def build(provider, texts, context):
        calls.append(provider)
        if provider == "codex" or first_success:
            return SubtitleTranslationCandidate(provider=provider, translations=["三维打印拓展了制造方式。"],
                                                vocabs=[{}], supports_vocab=True)
        return None
    monkeypatch.setattr(processor, "_build_translation_candidate", build)
    segments = [{"text": "3D printing expands manufacturing methods.", "start": 1.1, "end": 3.2}]
    original = dict(segments[0])
    result = processor._translate_segments(segments)
    assert calls == (["gemini"] if first_success else ["gemini", "google", "codex"])
    assert all(result[0][key] == value for key, value in original.items())
    assert result[0]["zh_text"]


def test_codex_cannot_use_legacy_quality_fail_open(tmp_path, monkeypatch):
    monkeypatch.setattr(caption, "settings", _settings(tmp_path, enable_translation_quality_fail_open=True))
    decision = _processor()._evaluate_translation_quality(
        ["MGX announced the final close of Fund I at $49 billion."], ["490亿主权基金撤退。"],
        provider="codex", final_provider=True, quality_context=None,
    )
    assert decision.blocking_issues and not decision.accepted


def _chain_settings(tmp_path, enabled=True):
    return _settings(tmp_path, enabled, copywriter_title_provider_order="agy,codex,grok,gemini",
                     grok_command="grok-test")


def test_chain_order_cli_first_grok_recovers_before_gemini(tmp_path, monkeypatch):
    monkeypatch.setattr(copywriter, "settings", _chain_settings(tmp_path))
    calls = []
    def existing(*args):
        calls.append(args[4] if len(args) > 4 else "agy")
        if len(args) > 4:
            pytest.fail("gemini API must stay behind grok")
        _deferred()
    monkeypatch.setattr(copywriter, "_generate_existing_wechat_content", existing)
    def codex(*args, **kwargs):
        calls.append("codex")
        raise CodexTextError("quota", 9999999999)
    monkeypatch.setattr(copywriter, "run_codex_structured", codex)
    def grok(prompt, **kwargs):
        calls.append("grok")
        assert kwargs["command"] == "grok-test" and kwargs["timeout_sec"] <= 150
        assert "PATH" in kwargs["environment"]
        return dict(RAW)
    monkeypatch.setattr(copywriter, "run_grok_structured", grok)
    audit = tmp_path / "quality.json"
    content = copywriter.generate_wechat_content(SOURCE, DESCRIPTION, audit_path=audit)
    assert calls == ["agy", "codex", "grok"]
    assert content["short_title"] == RAW["short_title"]
    events = json.loads(audit.read_text())["events"]
    assert events[-1]["provider"] == "grok:default" and events[-1]["selected"]


def test_chain_all_cli_fail_then_gemini_last_and_deferral_preserved(tmp_path, monkeypatch):
    monkeypatch.setattr(copywriter, "settings", _chain_settings(tmp_path, enabled=False))
    calls = []
    def existing(*args):
        calls.append(args[4] if len(args) > 4 else "agy")
        if len(args) > 4:
            raise ValueError("gemini key missing")
        _deferred()
    monkeypatch.setattr(copywriter, "_generate_existing_wechat_content", existing)
    monkeypatch.setattr(copywriter, "run_codex_structured",
                        lambda *a, **k: pytest.fail("codex disabled must be skipped"))
    def grok(prompt, **kwargs):
        calls.append("grok")
        raise copywriter.GrokProviderError("grok timed out after 90s")
    monkeypatch.setattr(copywriter, "run_grok_structured", grok)
    with pytest.raises(copywriter.CopyProviderDeferred):
        copywriter.generate_wechat_content(SOURCE, DESCRIPTION, audit_path=tmp_path / "quality.json")
    assert calls == ["agy", "grok", "gemini"]


def test_title_order_accepts_cli_providers():
    configured = Settings(_env_file=None, copywriter_title_provider_order="AGY, codex,grok,bogus,gemini,grok")
    assert configured.copywriter_title_provider_order_list == ["agy", "codex", "grok", "gemini"]
