"""D04/D09：launchd/cron 受控替身，不连接真实服务管理器。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-13 | Codex | KeepAlive、来源冲突、原禁用与 RunAtLoad 恢复 |
"""
from pathlib import Path
from types import SimpleNamespace
import plistlib
import pytest
from video_processing.core.deployment import DeploymentDenied
from video_processing.core.deployment_schedules import Schedules, UI


class Commands:
    def __init__(self, root):
        self.root = root
        self.crontab = ("keep-other-project\n* * * * * cd " + str(root) + " && job\n").encode()
        self.services = {}
        self.disabled = {}
        self.calls = []
        self.bootstraps = []

    def run(self, args, *, data=None, allowed=(0,)):
        self.calls.append(args)
        result = SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
        if args[:2] == ["crontab", "-l"]:
            result.stdout = self.crontab
        elif args[:2] == ["crontab", "-"]:
            self.crontab = data
        elif args[1] == "print-disabled":
            result.stdout = "\n".join('"' + l + '" => ' + str(v).lower() for l, v in self.disabled.items()).encode()
        elif args[1] == "list":
            result.stdout = "\n".join("-\t0\t" + l for l in self.services).encode()
        elif args[1] == "print":
            label = args[2].split("/")[-1]
            row = self.services.get(label)
            if row is None:
                result.returncode, result.stderr = 113, b"Could not find service"
            else:
                result.stdout = ("path = " + str(row["path"]) + "\nworking directory = " + str(self.root) + "\n" +
                                 ("pid = " + str(row["pid"]) + "\n" if row.get("pid") else "")).encode()
        elif args[1] in {"enable", "disable"}:
            self.disabled[args[2].split("/")[-1]] = args[1] == "disable"
        elif args[1] == "bootout":
            self.services.pop(args[2].split("/")[-1])
        elif args[1] == "bootstrap":
            path = Path(args[3])
            config = plistlib.loads(path.read_bytes())
            self.services[config["Label"]] = {"path": path, "pid": None}
            self.bootstraps.append(config)
        else:
            raise AssertionError(args)
        assert result.returncode in allowed
        return result


@pytest.fixture
def scheduling(tmp_path, monkeypatch):
    home, root, directory = tmp_path / "home", tmp_path / "repo", tmp_path / "private"
    root.mkdir(); directory.mkdir()
    agents = home / "Library/LaunchAgents"
    agents.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    commands = Commands(root)
    configurations = [(UI, True, False, True), ("com.videopipeline.once", True, False, False),
                      ("com.videopipeline.disabled", False, True, False), ("com.videopipeline.unloaded", False, False, False)]
    for label, loaded, disabled, keepalive in configurations:
        path = agents / (label + ".plist")
        path.write_bytes(plistlib.dumps({"Label": label, "WorkingDirectory": str(root), "ProgramArguments": ["fixture"],
                                        "RunAtLoad": True, "KeepAlive": keepalive, "StartInterval": 180}))
        commands.disabled[label] = disabled
        if loaded:
            commands.services[label] = {"path": path, "pid": 123 if label == UI else None}
    schedules = Schedules(root, directory, commands)
    return schedules, commands, schedules.snapshot()


def test_d09_restore_preserves_disabled_unloaded_and_suppresses_oneoff(scheduling):
    schedules, commands, plan = scheduling
    original = commands.crontab
    schedules.freeze(plan)
    assert UI in commands.services  # disable 不能充当停止证据。
    assert commands.disabled[UI] is True
    assert commands.crontab == b"keep-other-project\n"
    commands.services.pop(UI)
    commands.services[UI] = {"path": next(r["loaded_path"] for r in plan["launchd"] if r["label"] == UI), "pid": 456}
    commands.disabled[UI] = False
    schedules.restore(plan)
    assert commands.crontab == original
    assert commands.disabled["com.videopipeline.disabled"] is True
    assert "com.videopipeline.disabled" not in commands.services
    assert "com.videopipeline.unloaded" not in commands.services
    assert commands.bootstraps[0]["RunAtLoad"] is False
    assert commands.bootstraps[0]["StartInterval"] == 180
    schedules.restored(plan)


@pytest.mark.parametrize("change", ["cron", "plist", "process"])
def test_d05_conflicts_prevent_freeze(scheduling, change):
    schedules, commands, plan = scheduling
    if change == "cron":
        commands.crontab += b"new operator edit\n"
    elif change == "plist":
        Path(plan["launchd"][0]["path"]).write_bytes(b"changed")
    else:
        commands.services["com.videopipeline.once"]["pid"] = 42
    before = len(commands.calls)
    with pytest.raises(DeploymentDenied):
        schedules.freeze(plan)
    assert not any(c[1] in {"disable", "bootout", "-"} for c in commands.calls[before:])


def test_d09_external_cron_edit_never_overwritten_during_restore(scheduling):
    schedules, commands, plan = scheduling
    schedules.freeze(plan)
    commands.disabled[UI] = False
    commands.crontab += b"concurrent edit\n"
    changed = commands.crontab
    with pytest.raises(DeploymentDenied, match="CRON_EDIT_CONFLICT"):
        schedules.restore(plan)
    assert commands.crontab == changed


def test_d05_unknown_loaded_service_blocks_before_mutation(scheduling):
    schedules, commands, plan = scheduling
    commands.services["com.videopipeline.unknown"] = {"path": "unknown", "pid": None}
    before = len(commands.calls)
    with pytest.raises(DeploymentDenied, match="UNKNOWN_LOADED_SERVICE"):
        schedules.freeze(plan)
    assert not any(c[1] in {"disable", "bootout", "-"} for c in commands.calls[before:])


def test_d09_loaded_wrong_definition_is_not_success(scheduling):
    schedules, commands, plan = scheduling
    schedules.freeze(plan)
    commands.disabled[UI] = False
    schedules.restore(plan)
    path = Path(commands.services["com.videopipeline.once"]["path"])
    config = plistlib.loads(path.read_bytes()); config["StartInterval"] = 1
    path.write_bytes(plistlib.dumps(config))
    with pytest.raises(DeploymentDenied, match="RESTORED_DEFINITION_MISMATCH"):
        schedules.restored(plan)
