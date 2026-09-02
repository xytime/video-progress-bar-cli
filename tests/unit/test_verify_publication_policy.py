"""发布策略校验器的受控覆盖回归测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-31 | Codex | 覆盖示例基线、本机显式覆盖和未受管运行时覆盖的三层校验。 |
"""

from types import SimpleNamespace

from scripts import verify_publication_policy as policy


class FakeSettings:
    """隔离 Settings 文件与进程环境，只验证策略校验语义。"""

    model_fields = {"flag": SimpleNamespace(default=False)}
    effective_value = True

    def __init__(self) -> None:
        self.flag = self.effective_value

    @classmethod
    def model_validate(cls, values: dict[str, str]) -> "FakeSettings":
        result = cls.__new__(cls)
        result.flag = values["flag"].strip().lower() in {"1", "true", "yes", "on"}
        return result


def _configure_sources(monkeypatch, *, example: str, production: str | None, effective: bool) -> None:
    FakeSettings.effective_value = effective
    monkeypatch.setattr(policy, "POLICY_FIELDS", {"FLAG": "flag"})
    monkeypatch.setattr(policy, "Settings", FakeSettings)

    def fake_dotenv_values(path):
        if path.name == ".env.example":
            return {"FLAG": example}
        return {} if production is None else {"FLAG": production}

    monkeypatch.setattr(policy, "dotenv_values", fake_dotenv_values)


def test_policy_check_accepts_explicit_local_override(monkeypatch):
    _configure_sources(monkeypatch, example="false", production="true", effective=True)

    assert policy._check_policy_sources() == []


def test_policy_check_rejects_unmanaged_runtime_override(monkeypatch):
    _configure_sources(monkeypatch, example="false", production="true", effective=False)

    errors = policy._check_policy_sources()

    assert errors == ["FLAG: 当前进程有效值为 'false'，与.env 显式配置 'true' 不一致"]


def test_policy_check_rejects_example_that_changes_safe_default(monkeypatch):
    _configure_sources(monkeypatch, example="true", production=None, effective=False)

    errors = policy._check_policy_sources()

    assert errors == ["FLAG: Settings 默认值为 'false'，.env.example 为 'true'"]
