"""维护中部分冻结恢复：真实闸门/持久意图，宿主调度只用受控替身。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-30 | Codex | cron/首 disable 中断接续，未知漂移、无意图混合态及 Bot 保护。 |
"""
from pathlib import Path
import plistlib
from types import SimpleNamespace

import pytest

from tests.unit.test_deployment_schedules import scheduling  # noqa: F401
from video_processing.core import maintenance_restart_freeze as freeze
from video_processing.core.deployment import Deployment, DeploymentDenied, digest, read_json, write_json
from video_processing.core.deployment_schedules import BOT, UI
from video_processing.core.maintenance import MaintenanceGate


@pytest.fixture
def freezing(scheduling):
    schedules, commands, plan = scheduling
    control = MaintenanceGate(schedules.root / "output/maintenance-state.json")
    control.enter("isolated closed freeze")
    baseline = control._read()
    host = SimpleNamespace(root=schedules.root, directory=schedules.directory, schedules=schedules, control=control,
                           plan=dict(id="freeze", schedules=plan, restart=dict(owners=dict(workers=dict(ui=dict(pid=123))))))
    checks = []
    def retirement_check(*, partial=False, frozen=False):
        checks.append((partial, frozen))
        assert control._read() == baseline
        state = control.status()
        if state["active"] or state["unknown"]:
            raise DeploymentDenied("ACTIVE_OR_UNKNOWN")
        current_plan = host.plan["schedules"]
        if frozen:
            schedules.frozen(current_plan)
        elif partial:
            schedules.files_check(current_plan)
        else:
            schedules.baseline(current_plan)
    host.retirement_check = retirement_check
    return SimpleNamespace(host=host, commands=commands, checks=checks)


def mutations(commands):
    return [command for command in commands.calls if command[:2] == ["crontab", "-"]
            or len(command) > 1 and command[1] in {"disable", "bootout"}]


def test_first_intent_is_durable_before_every_mutation_and_freeze_keeps_ui_loaded(freezing):
    host, commands = freezing.host, freezing.commands
    original_control = host.control.path.read_bytes()
    run = commands.run
    def checked_run(arguments, **kwargs):
        if arguments[:2] == ["crontab", "-"] or len(arguments) > 1 and arguments[1] in {"disable", "bootout"}:
            intent = read_json(host.directory / "freeze-closed.json")
            assert intent["plan"] == digest(host.plan) and intent["pending"] is not None
            assert host.control._read()["state"] == "MAINTENANCE"
        return run(arguments, **kwargs)
    commands.run = checked_run
    result = freeze.freeze_closed(host)
    assert result["complete"] is True
    assert host.control.path.read_bytes() == original_control
    assert commands.services.keys() == {UI}
    assert all(commands.disabled.values()) and commands.crontab == b"keep-other-project\n"
    assert freezing.checks[0] == (False, False) and freezing.checks[-1] == (False, True)


@pytest.mark.parametrize("failure", ["after-cron", "after-first-disable", "after-bootout"])
def test_partial_freeze_with_exact_intent_can_continue_without_repeating_effect(freezing, failure):
    host, commands = freezing.host, freezing.commands
    run, triggered = commands.run, [False]
    def interrupted(arguments, **kwargs):
        result = run(arguments, **kwargs)
        wanted = {"after-cron": ["crontab", "-"], "after-first-disable": ["launchctl", "disable"],
                  "after-bootout": ["launchctl", "bootout"]}[failure]
        if not triggered[0] and arguments[:2] == wanted:
            triggered[0] = True
            raise OSError("injected after accepted host action")
        return result
    commands.run = interrupted
    before = host.control.path.read_bytes()
    with pytest.raises(OSError):
        freeze.freeze_closed(host)
    assert (host.directory / "freeze-closed.json").exists()
    assert host.control.path.read_bytes() == before
    commands.run = run
    assert freeze.freeze_closed(host)["complete"] is True
    assert host.control.path.read_bytes() == before
    actions = mutations(commands)
    assert len([row for row in actions if row[:2] == ["crontab", "-"]]) == 1
    assert len([row for row in actions if row[:2] == ["launchctl", "disable"]]) == 3
    assert len([row for row in actions if row[:2] == ["launchctl", "bootout"]]) == 1


@pytest.mark.parametrize("failure", [["crontab", "-"], ["launchctl", "disable"]])
def test_native_deployment_explicit_recover_resumes_partial_freeze(freezing, failure):
    from video_processing.core.maintenance_restart import RestartHost
    host, commands = freezing.host, freezing.commands
    adapter = RestartHost.__new__(RestartHost)
    adapter.__dict__.update(host.__dict__)
    adapter.lock_path = host.root / "output/deployment.lock"
    adapter.web_readback = lambda **kwargs: dict(maintenance="MAINTENANCE")
    adapter.preflight = lambda step: RestartHost.preflight(adapter, step) if step == "freeze" else None
    adapter.action = lambda step: RestartHost.action(adapter, step) if step == "freeze" else dict(ok=True)
    adapter.verify = lambda step, result: RestartHost.verify(adapter, step, result) if step == "freeze" else None
    adapter.final_status = lambda: host.schedules.frozen(host.plan["schedules"])
    write_json(host.directory / "journal.json", dict(schema=1, plan=digest(host.plan), done=["baseline"],
                                                   pending="freeze", state="FAILED"))
    run = commands.run
    def interrupted(arguments, **kwargs):
        result = run(arguments, **kwargs)
        if arguments[:2] == failure:
            raise OSError("injected after host accepted action")
        return result
    commands.run = interrupted
    deployment = Deployment(host.plan, host.directory, adapter)
    before = host.control.path.read_bytes()
    with pytest.raises(OSError): deployment.run(recover=True)
    commands.run = run
    assert deployment.status()["pending"] == "freeze"
    with pytest.raises(DeploymentDenied, match="RECOVERY_REQUIRED"): deployment.run()
    assert deployment.run(recover=True)["state"] == "COMPLETE"
    assert host.control.path.read_bytes() == before
    host.schedules.frozen(host.plan["schedules"])


@pytest.mark.parametrize("change", ["cron", "disable"])
def test_mixed_state_without_our_intent_cannot_be_adopted(freezing, change):
    host, commands = freezing.host, freezing.commands
    if change == "cron": commands.crontab = b"keep-other-project\n"
    else: commands.disabled[UI] = True
    before = len(mutations(commands))
    with pytest.raises(DeploymentDenied):
        freeze.freeze_closed(host)
    assert len(mutations(commands)) == before and not (host.directory / "freeze-closed.json").exists()


@pytest.mark.parametrize("change", ["cron", "definition", "extra-label", "job-pid", "ui-pid", "intent", "gate"])
def test_unknown_partial_drift_refuses_further_schedule_mutation(freezing, change):
    host, commands = freezing.host, freezing.commands
    run = commands.run
    def interrupted(arguments, **kwargs):
        result = run(arguments, **kwargs)
        if arguments[:2] == ["crontab", "-"]:
            raise OSError("after cron")
        return result
    commands.run = interrupted
    with pytest.raises(OSError): freeze.freeze_closed(host)
    commands.run = run
    if change == "cron": commands.crontab += b"operator drift\n"
    elif change == "definition": Path(host.plan["schedules"]["launchd"][0]["path"]).write_bytes(b"drift")
    elif change == "extra-label": commands.services["com.videopipeline.unknown"] = dict(path="unknown", pid=None)
    elif change == "job-pid": commands.services["com.videopipeline.once"]["pid"] = 777
    elif change == "ui-pid": commands.services[UI]["pid"] = 456
    elif change == "intent":
        path = host.directory / "freeze-closed.json"
        path.write_text(path.read_text().replace('"plan": "', '"plan": "different-'))
    else:
        host.control.resume(host.control._read()["version"], validated=True)
    before = len(mutations(commands))
    with pytest.raises((DeploymentDenied, AssertionError)):
        freeze.freeze_closed(host)
    assert len(mutations(commands)) == before


def test_completed_items_are_verified_and_cannot_be_silently_refrozen(freezing):
    host, commands = freezing.host, freezing.commands
    freeze.freeze_closed(host)
    commands.disabled[UI] = False
    before = len(mutations(commands))
    with pytest.raises(DeploymentDenied, match="FREEZE_COMPLETED_SERVICE_DRIFT"):
        freeze.freeze_closed(host)
    assert len(mutations(commands)) == before


@pytest.fixture
def with_bot(freezing, monkeypatch):
    from video_processing.core import maintenance_runtime
    host, commands = freezing.host, freezing.commands
    path = Path.home() / "Library/LaunchAgents" / (BOT + ".plist")
    arguments = [str(host.root / ".venv/bin/python"), str(host.root / "src/bot/telegram_bot.py")]
    path.write_bytes(plistlib.dumps(dict(Label=BOT, WorkingDirectory=str(host.root), ProgramArguments=arguments,
                                        RunAtLoad=True, KeepAlive=True)))
    commands.services[BOT] = dict(path=path, pid=789)
    commands.disabled[BOT] = False
    commands.daemon_command, commands.processes = " ".join(arguments), "789 1\n"
    monkeypatch.setattr(maintenance_runtime, "process_birth", lambda pid: f"birth-{pid}")
    monkeypatch.setattr(freeze, "process_birth", lambda pid: f"birth-{pid}")
    plan = host.schedules.snapshot()
    host.plan["schedules"] = plan
    check = host.retirement_check
    def retirement_check(*, partial=False, frozen=False):
        if partial:
            check(partial=True)
        elif frozen:
            host.schedules.frozen(plan)
        else:
            host.schedules.baseline(plan)
    host.retirement_check = retirement_check
    return freezing


def test_bot_restarted_during_partial_freeze_has_fresh_identity_before_bootout(with_bot):
    host, commands = with_bot.host, with_bot.commands
    run, failed = commands.run, [False]
    def interrupted(arguments, **kwargs):
        result = run(arguments, **kwargs)
        if not failed[0] and arguments[:2] == ["crontab", "-"]:
            failed[0] = True
            raise OSError("after cron")
        return result
    commands.run = interrupted
    with pytest.raises(OSError): freeze.freeze_closed(host)
    commands.run = run
    commands.services[BOT]["pid"], commands.processes = 790, "790 1\n"
    result = freeze.freeze_closed(host)
    assert result["complete"] is True
    assert {item["identity"]["pid"] for item in result["daemons"]} == {789, 790}
    assert BOT not in commands.services


@pytest.mark.parametrize("fault", ["child", "command", "birth-unknown"])
def test_bot_live_children_or_unknown_identity_never_allow_schedule_mutation(with_bot, monkeypatch, fault):
    host, commands = with_bot.host, with_bot.commands
    if fault == "child": commands.processes += "790 789\n"
    elif fault == "command": commands.daemon_command += " --unexpected"
    else:
        def unavailable(pid): raise PermissionError("birth unavailable")
        monkeypatch.setattr(freeze, "process_birth", unavailable)
        commands.processes += "790 789\n"
    before = len(mutations(commands))
    with pytest.raises((DeploymentDenied, PermissionError)):
        freeze.freeze_closed(host)
    assert len(mutations(commands)) == before
