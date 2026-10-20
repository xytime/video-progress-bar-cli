"""agy 受限结构化 provider 测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.3 | 2026-10-20 | Codex | 验证宿主单一超时边界及空成功输出不可触发兜底，防止敏感输出外泄。 |
| 1.0.2 | 2026-09-25 | Codex | 识别结构化参数的 API 400，确保只输出安全分类而不泄漏原始错误文本。 |
| 1.0.1 | 2026-09-22 | Codex | 覆盖本地启动分类、模型列表预检及敏感输出不外泄。 |
| 1.0.0 | 2026-08-24 | Codex | 覆盖隔离调用、Schema 输出提取和缺失结构化结果的拒绝 |
"""

import json
from types import SimpleNamespace

import pytest

from video_processing.utils.agy_provider import AgyProviderError, run_agy_structured


def test_agy_provider_uses_isolated_schema_command_and_extracts_structured_output(monkeypatch):
    import video_processing.utils.agy_provider as module

    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout=json.dumps({"structured_output": {"items": []}}), stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    result = run_agy_structured("translate", schema={"type": "object"}, model="test-model", command="agy", timeout_sec=17)

    assert result == {"items": []}
    assert captured["args"][:7] == [
        "agy", "--mode", "plan", "--sandbox", "--disable-slash-commands", "--model", "test-model",
    ]
    assert "--disable-slash-commands" in captured["args"]
    assert captured["args"][captured["args"].index("--effort") + 1] == "medium"
    assert "--print=translate" in captured["args"]
    assert captured["args"][captured["args"].index("--print-timeout") + 1] == "0s"
    assert captured["kwargs"]["timeout"] == 32
    assert captured["kwargs"]["cwd"] != "/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing"


def test_agy_provider_rejects_missing_structured_output(monkeypatch):
    import video_processing.utils.agy_provider as module

    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="{}", stderr=""),
    )

    with pytest.raises(AgyProviderError, match="structured_output"):
        run_agy_structured("translate", schema={"type": "object"}, model="test", command="agy", timeout_sec=1)


def test_host_timeout_is_infrastructure_failure_without_exposing_output(monkeypatch):
    import video_processing.utils.agy_provider as module
    from video_processing.utils.english_world_provider import infrastructure_error

    def timed_out(args, **kwargs):
        assert kwargs["timeout"] == 16
        assert args[args.index("--print-timeout") + 1] == "0s"
        raise module.subprocess.TimeoutExpired(args, kwargs["timeout"], output="private subtitle")

    monkeypatch.setattr(module.subprocess, "run", timed_out)
    with pytest.raises(AgyProviderError) as exc:
        run_agy_structured("translate", schema={"type": "object"}, model="test", command="agy", timeout_sec=1)
    assert str(exc.value) == "agy timed out after 1s"
    assert infrastructure_error(exc.value)


def test_empty_success_envelope_remains_invalid_not_fallback(monkeypatch):
    import video_processing.utils.agy_provider as module
    from video_processing.utils.english_world_provider import infrastructure_error

    monkeypatch.setattr(module.subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=0, stdout=json.dumps({"status": "SUCCESS", "response": "", "num_turns": 0}), stderr=""))
    with pytest.raises(AgyProviderError) as exc:
        run_agy_structured("translate", schema={"type": "object"}, model="test", command="agy", timeout_sec=1)
    assert not infrastructure_error(exc.value)


def test_agy_provider_does_not_expose_external_error_text(monkeypatch):
    import video_processing.utils.agy_provider as module

    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="quota for prompt: private subtitle"),
    )

    with pytest.raises(AgyProviderError) as exc_info:
        run_agy_structured("translate", schema={"type": "object"}, model="test", command="agy", timeout_sec=1)

    assert str(exc_info.value) == "agy exit 1: rate limit"


def test_agy_provider_classifies_invalid_structured_schema_without_external_text(monkeypatch):
    import video_processing.utils.agy_provider as module

    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=3, stdout="",
            stderr="INVALID_ARGUMENT (code 400): function_declarations[0].parameters.properties[learning_points] "
                   "private subtitle: cannot be empty",
        ),
    )

    with pytest.raises(AgyProviderError) as exc_info:
        run_agy_structured("translate", schema={"type": "object"}, model="test", command="agy", timeout_sec=1)

    assert str(exc_info.value) == "agy exit 3: invalid schema"


@pytest.mark.parametrize("message, expected", [
    ("Failed to start: listen tcp 127.0.0.1:0: bind: operation not permitted", "local startup blocked"),
    ("403 permission denied", "permission"),
    ("operation not permitted", "provider error"),
])
def test_startup_failure_category_is_narrow(message, expected):
    from video_processing.utils.agy_provider import _safe_failure_category
    assert _safe_failure_category(message) == expected


@pytest.mark.parametrize("code, output, success", [
    (0, "m\tTest model\n", True), (0, "other\tOther model\n", False),
    (1, "private account details", False),
])
def test_startup_probe_only_queries_model_list(monkeypatch, code, output, success):
    import video_processing.utils.agy_provider as module
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=code, stdout=output, stderr="")
    monkeypatch.setattr(module.subprocess, "run", run)
    if success:
        assert module.probe_agy_startup(command="agy", model="m")["model_available"]
    else:
        with pytest.raises(AgyProviderError) as exc:
            module.probe_agy_startup(command="agy", model="m")
        assert "private" not in str(exc.value)
    assert calls == [["agy", "models"]]
