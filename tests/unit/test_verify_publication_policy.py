"""发布策略校验器的受控覆盖回归测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-31 | Codex | 覆盖示例基线、本机显式覆盖和未受管运行时覆盖的三层校验。 |
| 1.1.0 | 2026-09-22 | Codex | 实测 cron 启动锁在解释器启动前跳过重入、正常释放并保留子进程退出码。 |
"""

from types import SimpleNamespace
import fcntl
from pathlib import Path
import subprocess
import time

import pytest

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


def _installed_line(root):
    """直接使用安装器的命令模板，避免测试另造一条正确命令。"""
    installer = Path(__file__).resolve().parents[2] / "scripts/install_publication_window_schedule.sh"
    template = next(line for line in installer.read_text().splitlines() if line.startswith("* * * * * "))
    return template.replace("$PROJECT_ROOT", str(root)).replace("$PYTHON_BIN", str(root / ".venv/bin/python"))


@pytest.mark.parametrize("variant", ["locked", "legacy", "duplicate", "outside", "unrelated"])
def test_installed_schedule_requires_one_guarded_project_entry(monkeypatch, variant):
    line = _installed_line(policy.PROJECT_ROOT)
    legacy = line.replace(
        f'/usr/bin/lockf -ks -t 0 "{policy.PROJECT_ROOT}/output/publication_window_startup.lock" ', ""
    )
    content = [policy.CRON_BEGIN, legacy if variant == "legacy" else line, policy.CRON_END]
    if variant == "duplicate":
        content.append(legacy)
    if variant == "outside":
        content = [policy.CRON_BEGIN, policy.CRON_END, line]
    if variant == "unrelated":
        content.append('* * * * * /another/project/scripts/run_publication_window.py')
    monkeypatch.setattr(policy.subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=0, stdout="\n".join(content), stderr=""
    ))
    assert bool(policy._check_installed_schedule()) == (variant not in {"locked", "unrelated"})


def _fake_cron(tmp_path, body):
    root = tmp_path / "repo with spaces"
    (root / ".venv/bin").mkdir(parents=True)
    (root / "output").mkdir()
    interpreter = root / ".venv/bin/python"
    interpreter.write_text("#!/bin/sh\n" + body)
    interpreter.chmod(0o755)
    return root, _installed_line(root).split(" ", 5)[5]


def test_cron_busy_lock_does_not_start_python(tmp_path):
    root, command = _fake_cron(tmp_path, "touch python-started\n")
    lock = root / "output/publication_window_startup.lock"
    with lock.open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = subprocess.run(["/bin/sh", "-c", command], timeout=5)
    assert result.returncode == 75
    assert not (root / "python-started").exists()
    assert lock.exists()


def test_cron_releases_lock_and_preserves_exit_status(tmp_path):
    root, command = _fake_cron(tmp_path, "touch python-started\nexit 23\n")
    for _ in range(2):
        result = subprocess.run(["/bin/sh", "-c", command], timeout=5)
        assert result.returncode == 23
    assert (root / "python-started").exists()
    with (root / "output/publication_window_startup.lock").open() as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_cron_holds_startup_lock_for_full_child_lifetime(tmp_path):
    root, command = _fake_cron(tmp_path, "touch python-started\nread token\nexit 0\n")
    first = subprocess.Popen(["/bin/sh", "-c", command], stdin=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 5
        while not (root / "python-started").exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert (root / "python-started").exists()
        assert first.poll() is None
        assert subprocess.run(["/bin/sh", "-c", command], timeout=5).returncode == 75
    finally:
        first.communicate(b"done\n", timeout=5)
    assert first.returncode == 0
