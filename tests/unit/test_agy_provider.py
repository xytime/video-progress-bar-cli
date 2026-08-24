"""agy 受限结构化 provider 测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
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
    assert captured["args"][:7] == ["agy", "--mode", "plan", "--sandbox", "--model", "test-model", "--json-schema"]
    assert "--print=translate" in captured["args"]
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
