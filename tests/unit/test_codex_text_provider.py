"""Codex 文字入口的预算、结构、无工具与缓存边界。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.2.0 | 2026-10-27 | Codex | 验证真实执行前预算回调与缓存、锁、冷却的零消耗边界。 |
| 1.1.0 | 2026-10-27 | Codex | 覆盖有界宿主拒绝回执、质量合同缓存隔离及失效缓存原预算重建。 |
| fallback-v1 | 2026-10-20 | Codex | 验证独立备用通道及其预算、输入、证据与失败关闭边界。 |
| 1.0.0 | 2026-10-03 | Codex | 覆盖真实故障路径、质量缓存和经济模型限制。 |
"""

import fcntl
import hashlib
import json
from pathlib import Path
import subprocess
import signal

import pytest

from config.settings import settings
from video_processing.utils import codex_text_provider as provider


SCHEMA = {"type": "object", "properties": {"title": {"type": "string"}},
          "required": ["title"], "additionalProperties": False}


def _call(tmp_path, **changes):
    args = dict(schema=SCHEMA, state_dir=tmp_path, command="codex", timeout_sec=5)
    args.update(changes)
    return provider.run_codex_structured("来源含 $(touch forbidden)；只翻译文字。", **args)


def _executor(payload=None, *, code=0, error="", events=None, calls=None):
    def execute(args, prompt, directory, timeout):
        if calls is not None:
            calls.append((args, prompt, directory, timeout))
        Path(args[args.index("--output-last-message") + 1]).write_text(
            json.dumps(payload if payload is not None else {"title": "制造业的新可能"}), encoding="utf-8")
        rows = events if events is not None else [{"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 20}}]
        return subprocess.CompletedProcess(args, code, "\n".join(json.dumps(r) for r in rows), error)
    return execute


def test_bounded_stdin_text_only_cli_and_usage(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(provider, "_execute", _executor(calls=calls))
    result = _call(tmp_path)
    args, prompt, directory, timeout = calls[0]
    assert result.usage == {"input_tokens": 100, "output_tokens": 20}
    assert result.model == "gpt-5.6-luna"
    assert prompt not in args and args[-1] == "-"
    assert args[args.index("--sandbox") + 1] == "read-only"
    assert "--ignore-user-config" in args and "--ephemeral" in args
    assert 'web_search="disabled"' in args
    for feature in ("shell_tool", "plugins", "apps", "browser_use", "computer_use", "multi_agent"):
        index = args.index(feature)
        assert args[index - 1] == "--disable"
    assert timeout == 5 and not directory.exists()


@pytest.mark.parametrize("events", [[], [{"type": "turn.failed"}], [
    {"type": "item.started", "item": {"type": "command_execution"}}, {"type": "turn.completed"},
]])
def test_missing_completion_and_tools_are_not_success(tmp_path, monkeypatch, events):
    monkeypatch.setattr(provider, "_execute", _executor(events=events))
    with pytest.raises(provider.CodexTextError):
        _call(tmp_path)
    assert not list(tmp_path.glob("*.json"))


def test_recovered_stream_requires_terminal_completion_and_valid_payload(tmp_path, monkeypatch):
    events = [{'type': 'error', 'message': 'Reconnecting... Connection reset by peer'},
              {'type': 'item.completed', 'item': {'type': 'error', 'message': 'Reconnected'}},
              {'type': 'item.completed', 'item': {'type': 'agent_message'}},
              {'type': 'turn.completed', 'usage': {'output_tokens': 20}}]
    monkeypatch.setattr(provider, '_execute', _executor(events=events))
    assert _call(tmp_path).payload['title'] == '制造业的新可能'


@pytest.mark.parametrize('events', [
    [{'type': 'error', 'message': 'Reconnecting...'}],
    [{'type': 'error'}, {'type': 'turn.failed'}, {'type': 'turn.completed'}],
    [{'type': 'error'}, {'type': 'item.completed', 'item': {'type': 'command_execution'}},
     {'type': 'turn.completed'}],
])
def test_transport_notice_never_overrides_failure_or_tool_use(tmp_path, monkeypatch, events):
    monkeypatch.setattr(provider, '_execute', _executor(events=events))
    with pytest.raises(provider.CodexTextError):
        _call(tmp_path)


@pytest.mark.parametrize("payload", [{}, {"title": 7}, {"title": "中文", "extra": True}])
def test_invalid_structure_fails_closed(tmp_path, monkeypatch, payload):
    monkeypatch.setattr(provider, "_execute", _executor(payload))
    with pytest.raises(provider.CodexTextError, match="invalid_output"):
        _call(tmp_path)


def test_quality_rejected_output_not_cached_and_cache_revalidated(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(provider, "_execute", _executor(calls=calls))
    def reject(raw):
        raise ValueError("quality blocked")
    with pytest.raises(ValueError, match="quality blocked"):
        _call(tmp_path, validate=reject)
    receipt = json.loads((tmp_path / "requests.jsonl").read_text().splitlines()[-1])
    assert receipt["status"] == "FAILED" and receipt["usage"]["input_tokens"] == 100
    assert not list(tmp_path.glob("*.json"))
    first = _call(tmp_path, validate=lambda x: x)
    second = _call(tmp_path, validate=lambda x: x)
    assert first.payload == second.payload and second.cached and len(calls) == 2
    with pytest.raises(ValueError, match="quality blocked"):
        _call(tmp_path, validate=reject)


@pytest.mark.parametrize("message,classification", [
    ("You've hit your usage limit. PRIVATE TEXT", "quota"),
    ("401 unauthorized PRIVATE TEXT", "authentication"),
    ("model is not supported PRIVATE TEXT", "model_unavailable"),
])
def test_failure_receipt_and_cooldown_hide_raw_logs(tmp_path, monkeypatch, message, classification):
    calls = []
    monkeypatch.setattr(provider, "_execute", _executor(code=1, error=message, calls=calls))
    with pytest.raises(provider.CodexTextError) as first:
        _call(tmp_path)
    assert first.value.code == classification and first.value.retry_at > 0
    assert "PRIVATE" not in str(first.value)
    with pytest.raises(provider.CodexTextError, match="cooldown"):
        _call(tmp_path)
    assert len(calls) == 1


def test_busy_lock_and_flagship_rejected_before_request(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(provider, "_execute", _executor(calls=calls))
    with (tmp_path / "provider.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(provider.CodexTextError, match="busy"):
            _call(tmp_path)
    with pytest.raises(provider.CodexTextError, match="configuration"):
        _call(tmp_path, model="gpt-6-astra")
    assert calls == []


def test_minimal_environment_has_no_business_or_paid_api_credentials(monkeypatch):
    for key in ("OPENAI_API_KEY", "DEEPSEEK_API_KEY", "GEMINI_API_KEY", "TELEGRAM_BOT_TOKEN"):
        monkeypatch.setenv(key, "fake-private")
    env = settings.agy_app_environment()
    assert not any(key in env for key in ("OPENAI_API_KEY", "DEEPSEEK_API_KEY", "GEMINI_API_KEY", "TELEGRAM_BOT_TOKEN"))


def test_timeout_kills_group_even_after_parent_exits(tmp_path, monkeypatch):
    signals = []
    class Process:
        pid = 123
        calls = 0
        def communicate(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired("codex", 1)
            return "", ""
    process = Process()
    monkeypatch.setattr(provider.subprocess, "Popen", lambda *a, **k: process)
    monkeypatch.setattr(provider.os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    with pytest.raises(provider.CodexTextError, match="timeout"):
        provider._execute(["codex"], "文字", tmp_path, 1)
    assert signals == [(123, signal.SIGTERM), (123, signal.SIGKILL)]
    assert process.calls == 3


def test_corrupt_cache_is_rebuilt_and_revalidated(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(provider, "_execute", _executor(calls=calls))
    _call(tmp_path, validate=lambda x: x)
    next(tmp_path.glob("*.json")).write_text("broken")
    result = _call(tmp_path, validate=lambda x: x)
    assert not result.cached and len(calls) == 2


def test_accepted_repair_reuses_original_request_cache(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(provider, "_execute", _executor(calls=calls))
    kwargs = dict(schema=SCHEMA, state_dir=tmp_path, command="codex", validate=lambda raw: raw, cache_prompt="原始来源")
    provider.run_codex_structured("原始来源加一次修正提示", **kwargs)
    cached = provider.run_codex_structured("原始来源", **kwargs)
    assert cached.cached and len(calls) == 1


def test_images_pass_as_attachment_and_change_cache_identity(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(provider, '_execute', _executor(calls=calls))
    picture = tmp_path / 'contact.png'
    picture.write_bytes(b'first-picture')
    first = _call(tmp_path, images=(picture,), validate=lambda x: x)
    picture.write_bytes(b'new-picture')
    second = _call(tmp_path, images=(picture,), validate=lambda x: x)
    assert not first.cached and not second.cached and len(calls) == 2
    args = calls[0][0]
    assert args[args.index('--image') + 1] == str(picture.resolve())
    assert args[args.index('view_image') - 1] == '--disable'


def test_quality_receipt_keeps_only_bounded_host_details(tmp_path, monkeypatch):
    monkeypatch.setattr(provider, "_execute", _executor())
    details = [{"segment_number": index + 1, "source_id": index, "code": "NUMBER_MAGNITUDE_MISMATCH",
                "source_signal": "$115", "translation_signal": "$115B", "prompt": "PRIVATE FULL PROMPT"}
               for index in range(20)]
    def reject(raw):
        raise provider.CodexTextError("subtitle_quality_NUMBER_MAGNITUDE_MISMATCH", quality_details=details)
    with pytest.raises(provider.CodexTextError):
        _call(tmp_path, validate=reject)
    receipt_text = (tmp_path / "requests.jsonl").read_text()
    receipt = json.loads(receipt_text.splitlines()[-1])
    assert len(receipt["quality_details"]) == 10
    assert receipt["quality_details"][0] == {
        "segment_number": 1, "source_id": 0, "code": "NUMBER_MAGNITUDE_MISMATCH",
        "source_signal": "$115", "translation_signal": "$115B",
    }
    assert "PRIVATE" not in receipt_text and "touch forbidden" not in receipt_text
    assert not list(tmp_path.glob("*.json"))


def test_cache_contract_versions_are_isolated_without_deleting_other_cache(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(provider, "_execute", _executor(calls=calls))
    _call(tmp_path, validate=lambda raw: raw)
    _call(tmp_path, validate=lambda raw: raw, cache_contract="subtitle-facts-adjacent-v2")
    result = _call(tmp_path, validate=lambda raw: raw, cache_contract="subtitle-facts-adjacent-v2")
    assert len(calls) == 2 and result.cached
    assert len(list(tmp_path.glob("*.json"))) == 2


def test_rejected_cached_quality_is_repaired_before_first_new_request(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(provider, "_execute", _executor({"title": "旧缓存"}, calls=calls))
    _call(tmp_path, validate=lambda raw: raw)
    monkeypatch.setattr(provider, "_execute", _executor({"title": "修正后"}, calls=calls))
    details = [{"segment_number": 105, "source_id": 104, "code": "NUMBER_MAGNITUDE_MISMATCH",
                "source_signal": "$115", "translation_signal": "$115B"}]
    def validate(raw):
        if raw["title"] == "旧缓存":
            raise provider.CodexTextError("subtitle_quality_NUMBER_MAGNITUDE_MISMATCH", quality_details=details)
        return raw
    def repair(prompt, error):
        return prompt + "\n宿主安全反馈：" + json.dumps(error.quality_details)
    result = _call(tmp_path, validate=validate, repair_cached_output=repair)
    assert result.payload == {"title": "修正后"} and not result.cached and len(calls) == 2
    assert '"segment_number": 105' in calls[1][1]
    assert 0 < calls[1][3] <= 5
    receipt = json.loads((tmp_path / "requests.jsonl").read_text().splitlines()[-1])
    assert receipt["status"] == "SUCCEEDED" and receipt["cache_rejection"]["quality_details"] == details
    assert receipt["executed_input_sha256"] == hashlib.sha256(calls[1][1].encode()).hexdigest()
    assert receipt["executed_input_sha256"] != receipt["input_sha256"]
    cached = _call(tmp_path, validate=validate, repair_cached_output=repair)
    assert cached.cached and len(calls) == 2


def test_expired_budget_cannot_rebuild_rejected_cache(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(provider, "_execute", _executor(calls=calls))
    _call(tmp_path, validate=lambda raw: raw)
    clock = {"now": 0.0}
    monkeypatch.setattr(provider.time, "monotonic", lambda: clock["now"])
    def reject(raw):
        clock["now"] = 6.0
        raise provider.CodexTextError("subtitle_quality_NUMBER_MAGNITUDE_MISMATCH")
    with pytest.raises(provider.CodexTextError, match="timeout"):
        _call(tmp_path, validate=reject, repair_cached_output=lambda prompt, error: prompt)
    assert len(calls) == 1 and not list(tmp_path.glob("*.json"))


def test_before_execute_counts_only_fresh_execution_including_rejected_cache(tmp_path, monkeypatch):
    calls, admissions = [], []
    monkeypatch.setattr(provider, "_execute", _executor(calls=calls))
    arguments = dict(validate=lambda raw: raw, before_execute=lambda: admissions.append(1))
    _call(tmp_path, **arguments)
    cached = _call(tmp_path, **arguments)
    assert cached.cached and len(calls) == len(admissions) == 1
    def reject(raw):
        raise provider.CodexTextError("quality_rejected")
    with pytest.raises(provider.CodexTextError, match="quality_rejected"):
        _call(tmp_path, validate=reject, before_execute=arguments["before_execute"],
              repair_cached_output=lambda prompt, error: prompt)
    assert len(calls) == len(admissions) == 2


def test_budget_denial_and_existing_cooldown_do_not_execute_or_report_execution(tmp_path, monkeypatch):
    calls, admissions = [], []
    monkeypatch.setattr(provider, "_execute", _executor(calls=calls))
    def deny():
        admissions.append(1)
        raise provider.CodexTextError("request_budget_exhausted")
    with pytest.raises(provider.CodexTextError, match="request_budget_exhausted"):
        _call(tmp_path, before_execute=deny)
    receipt = json.loads((tmp_path / "requests.jsonl").read_text().splitlines()[-1])
    assert "executed_input_sha256" not in receipt and calls == []
    (tmp_path / "gpt-5.6-luna.cooldown.json").write_text(json.dumps({"retry_at": 99999999999}))
    with pytest.raises(provider.CodexTextError, match="cooldown"):
        _call(tmp_path, before_execute=deny)
    assert admissions == [1] and calls == []
