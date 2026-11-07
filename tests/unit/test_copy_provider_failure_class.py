"""文案供应商失败分类不得互相掩盖，Grok 全文案交接仍走原质量合同。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-07 | Grok Bot | 证明 auth/timeout/quota/429 同时留在审计和异常里；全文案交接不放宽标题合同。 |
"""

import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

from config.settings import Settings
from scripts import copywriter
from video_processing.utils.agy_provider import AgyProviderError
from video_processing.utils.codex_text_provider import CodexTextError
from video_processing.utils.generated_content_validation import GeneratedContentValidationError


RAW = {"short_title": "凝胶打印突破重力", "display_title": "", "hook_subtitle": "制造的新方法",
       "wechat_copy": "凝胶中的三维打印，为复杂结构制造提供了新方法。视频介绍这种制造技术的原理与应用。",
       "engagement_post": "", "category": "科技", "content_hints": ["manufacturing"], "content_label": ""}
SOURCE = "The Gravity-Defying Future of Manufacturing"
DESCRIPTION = "Printing in gel enables complex structures and new manufacturing methods. https://example.test/watch"


def _chain_settings(tmp_path):
    return Settings(
        _env_file=None, default_output_dir=tmp_path, copywriter_content_provider="agy",
        copywriter_title_provider_order="agy,codex,grok,gemini", enable_codex_text_fallback=True,
        grok_command="grok-test", copywriter_grok_timeout_seconds=150, gemini_api_key="test-key",
    )


def _isolate_output(monkeypatch, tmp_path, configured):
    monkeypatch.setattr(copywriter, "settings", configured)
    monkeypatch.setattr(type(configured), "default_output_dir", property(lambda _: tmp_path))


def test_chain_keeps_agy_auth_and_later_gemini_429(tmp_path, monkeypatch):
    _isolate_output(monkeypatch, tmp_path, _chain_settings(tmp_path))
    monkeypatch.setattr(copywriter.time, "sleep", lambda *_: None)

    def agy(*_args, **_kwargs):
        raise AgyProviderError("agy exit 1: AGY_AUTH_REQUIRED")

    import video_processing.utils.agy_copy_service as agy_service
    monkeypatch.setattr(agy_service, "run_agy_structured", agy)

    def codex(*_args, **_kwargs):
        raise CodexTextError("quota", 9999999999)

    monkeypatch.setattr(copywriter, "run_codex_structured", codex)

    def grok(*_args, **_kwargs):
        raise copywriter.GrokProviderError("grok timed out after 149.99s")

    monkeypatch.setattr(copywriter, "run_grok_structured", grok)

    class _Models:
        @staticmethod
        def generate_content(**_kwargs):
            raise RuntimeError("429 RESOURCE_EXHAUSTED key=super-secret-token")

    class _Client:
        def __init__(self, api_key):
            self.models = _Models()

    class _Config:
        def __init__(self, **_kwargs):
            pass

    google = types.ModuleType("google")
    genai = types.ModuleType("google.genai")
    genai_types = types.ModuleType("google.genai.types")
    genai.Client = _Client
    genai_types.GenerateContentConfig = _Config
    google.genai = genai
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", genai_types)

    def fallback(*_args, **_kwargs):
        raise GeneratedContentValidationError("fallback rejected")

    monkeypatch.setattr(copywriter, "_translate_fallback", fallback)
    audit = tmp_path / "quality.json"
    with pytest.raises(copywriter.CopyProviderDeferred) as error:
        copywriter.generate_wechat_content(SOURCE, DESCRIPTION, audit_path=audit)
    text = str(error.value)
    assert "classes=agy:auth,codex:quota,grok:timeout,gemini:rate_limit" in text
    assert "reason=auth" in text
    assert "super-secret-token" not in text
    assert "unavailable" not in text.split("classes=", 1)[-1]
    events = json.loads(audit.read_text(encoding="utf-8"))["events"]
    classes = {event.get("failure_class") or event.get("reason") for event in events}
    assert {"auth", "quota", "timeout", "rate_limit"} <= classes
    diagnostics = " ".join(str(event.get("diagnostic", "")) for event in events)
    assert "super-secret-token" not in diagnostics
    assert "RESOURCE_EXHAUSTED" in diagnostics or "HTTP 429" in diagnostics


def test_grok_full_copy_handoff_stays_inside_budget_and_title_contract(tmp_path, monkeypatch):
    _isolate_output(monkeypatch, tmp_path, Settings(
        _env_file=None, default_output_dir=tmp_path, copywriter_content_provider="agy",
        copywriter_title_provider_order="grok", enable_codex_text_fallback=False,
        grok_command="grok-test", copywriter_grok_timeout_seconds=150,
    ))
    assert copywriter.settings.copywriter_grok_timeout_seconds == 150
    seen = []

    def fake_run(args, **kwargs):
        prompt_path = Path(args[args.index("--prompt-file") + 1])
        seen.append((args, kwargs, prompt_path.read_text(encoding="utf-8")))
        payload = dict(RAW)
        if fake_run.first_bad:
            payload["short_title"] = "为什么只有9"
        return subprocess.CompletedProcess(
            args, 0, json.dumps({"structured_output": payload}), "",
        )

    fake_run.first_bad = False
    import video_processing.utils.grok_provider as grok_provider
    monkeypatch.setattr(grok_provider.subprocess, "run", fake_run)
    audit = tmp_path / "quality.json"
    content = copywriter.generate_wechat_content(SOURCE, DESCRIPTION, audit_path=audit)
    assert content["short_title"] == RAW["short_title"]
    args, kwargs, prompt = seen[0]
    assert 120 <= kwargs["timeout"] <= 150
    assert {"--verbatim", "--no-plan"} <= set(args)
    assert SOURCE in prompt and "https://example.test/watch" in prompt
    assert "不得编造因果" in prompt
    assert prompt not in args
    schema = json.loads(args[args.index("--json-schema") + 1])
    assert set(schema["required"]) == set(copywriter.WeChatContentSchema.model_fields)
    raw_schema = copywriter.WeChatContentSchema.model_json_schema()
    assert len(json.dumps(schema, ensure_ascii=False)) < len(json.dumps(raw_schema, ensure_ascii=False))
    assert "不得编造因果" not in json.dumps(schema, ensure_ascii=False)
    events = json.loads(audit.read_text(encoding="utf-8"))["events"]
    assert events[-1]["selected"] is True

    seen.clear()
    fake_run.first_bad = True
    with pytest.raises(copywriter.CopyProviderDeferred):
        copywriter.generate_wechat_content(SOURCE, "另一段来源。", audit_path=tmp_path / "rejected.json")
    rejected = json.loads((tmp_path / "rejected.json").read_text(encoding="utf-8"))["events"]
    assert any(event.get("selected") is False for event in rejected)
    assert all(event.get("content", {}).get("short_title") != "为什么只有9" or event.get("selected") is False
               for event in rejected)
