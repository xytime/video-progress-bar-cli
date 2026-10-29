"""既有维护中的逐项冻结：先落意图，精确原态/目标态才可显式接续。

调用方使用原生 Deployment 的显式 recover；此模块不改部署日志或维护闸门。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-30 | Codex | cron/disable/bootout 持久前缀，已知现场复验与空闲 Bot 当场身份审计。 |
"""
from pathlib import Path
import plistlib

from .deployment import DeploymentDenied, digest, read_json, require, write_json
from .deployment_schedules import BOT, UI
from .deployment_sources import sha
from .maintenance_runtime import process_birth


def _no_live_children(schedules, pid):
    output = schedules.runner.run(["ps", "-axo", "pid=,ppid="]).stdout.decode()
    rows = {}
    for line in output.splitlines():
        if not line.strip():
            continue
        fields = line.split()
        require(len(fields) == 2 and all(value.isdecimal() for value in fields), "FREEZE_CHILD_TREE_UNKNOWN")
        child, parent = map(int, fields)
        require(child not in rows, "FREEZE_CHILD_TREE_UNKNOWN")
        rows[child] = parent
    require(pid in rows, "FREEZE_CHILD_TREE_UNKNOWN")
    for child, parent in rows.items():
        if parent != pid:
            continue
        try:
            process_birth(child)
        except ProcessLookupError:
            continue
        raise DeploymentDenied("FREEZE_DAEMON_HAS_CHILDREN")


def _state(host, row):
    schedules = host.schedules
    label = row["label"]
    seen = schedules.service(label)
    disabled = schedules.disabled().get(label, row["disabled"])
    require(type(disabled) is bool and (disabled == row["disabled"] or disabled is True), "FREEZE_DISABLED_UNKNOWN")
    require(not seen["loaded"] or row["loaded"], "FREEZE_UNEXPECTED_LOADED_SERVICE")
    daemon = None
    if seen["loaded"]:
        require(seen.get("path") == row["loaded_path"]
                and sha(Path(seen["path"]).read_bytes()) == row["loaded_sha256"], "FREEZE_LOADED_DEFINITION_UNKNOWN")
        if label == UI:
            owner = host.plan["restart"]["owners"]["workers"]["ui"]
            require(seen.get("pid") == owner["pid"] and seen.get("cwd") == str(host.root), "FREEZE_UI_CHANGED")
        elif seen.get("pid"):
            require(label == BOT, "FREEZE_JOB_ACTIVE")
            definition = plistlib.loads(Path(row["loaded_path"]).read_bytes())
            daemon = schedules.daemon_identity(label, seen, definition)
            _no_live_children(schedules, daemon["pid"])
            require(schedules.daemon_identity(label, schedules.service(label), definition) == daemon,
                    "FREEZE_DAEMON_CHANGED")
    require(label != UI or seen["loaded"], "FREEZE_UI_MISSING")
    return dict(loaded=seen["loaded"], disabled=disabled, daemon=daemon)


def _is_target(row, observed):
    return observed["disabled"] is True and observed["loaded"] is (row["label"] == UI)


def _journal(host, path):
    plan = host.plan["schedules"]
    labels = [row["label"] for row in plan["launchd"]]
    if not path.exists():
        host.retirement_check()
        return dict(schema=1, plan=digest(host.plan), schedules=digest(plan), cron=False,
                    done=[], pending=None, daemons=[], complete=False)
    value = read_json(path)
    require(isinstance(value, dict) and value.get("schema") == 1
            and value.get("plan") == digest(host.plan) and value.get("schedules") == digest(plan)
            and type(value.get("cron")) is bool and type(value.get("complete")) is bool
            and isinstance(value.get("done"), list) and value["done"] == labels[:len(value["done"])]
            and isinstance(value.get("daemons"), list), "FREEZE_INTENT_CHANGED")
    next_label = labels[len(value["done"])] if len(value["done"]) < len(labels) else None
    require(value.get("pending") in {None, next_label, "cron"}
            and (value["cron"] or not value["done"])
            and (value.get("pending") != "cron" or not value["cron"])
            and (value["cron"] or value.get("pending") in {None, "cron"})
            and (not value["complete"] or value["cron"] and value["done"] == labels), "FREEZE_JOURNAL_ORDER_INVALID")
    return value


def _partial(host, journal):
    host.retirement_check(partial=True)
    schedules, plan = host.schedules, host.plan["schedules"]
    schedules.files_check(plan)
    cron = sha(schedules.cron())
    require(cron in {plan["cron"], plan["frozen_cron"]}, "FREEZE_CRON_DRIFT")
    require(not journal["cron"] or cron == plan["frozen_cron"], "FREEZE_COMPLETED_CRON_DRIFT")
    states = {row["label"]: _state(host, row) for row in plan["launchd"]}
    require(all(_is_target(row, states[row["label"]]) for row in plan["launchd"]
                if row["label"] in journal["done"]), "FREEZE_COMPLETED_SERVICE_DRIFT")
    return states


def _remember_daemons(journal, states):
    for label, state in states.items():
        if state["daemon"] is None:
            continue
        observation = dict(label=label, identity=state["daemon"])
        if not journal["daemons"] or journal["daemons"][-1] != observation:
            journal["daemons"].append(observation)


def freeze_closed(host):
    """只冻结已绑定原调度；已有意图的部分动作由原生显式 recover 接续。"""
    path = host.directory / "freeze-closed.json"
    journal = _journal(host, path)
    states = _partial(host, journal)
    _remember_daemons(journal, states)
    write_json(path, journal)  # 首次 cron/disable 前，完整计划绑定已持久化。
    schedules, plan = host.schedules, host.plan["schedules"]
    if not journal["cron"]:
        journal["pending"] = "cron"
        write_json(path, journal)
        _partial(host, journal)
        if sha(schedules.cron()) != plan["frozen_cron"]:
            schedules.runner.run(["crontab", "-"], data=(schedules.directory / "cron.frozen").read_bytes())
        require(sha(schedules.cron()) == plan["frozen_cron"], "FREEZE_CRON_UNCONFIRMED")
        journal.update(cron=True, pending=None)
        write_json(path, journal)
    for row in plan["launchd"]:
        label = row["label"]
        if label in journal["done"]:
            continue
        states = _partial(host, journal)
        _remember_daemons(journal, states)
        journal["pending"] = label
        write_json(path, journal)
        if not states[label]["disabled"]:
            schedules.runner.run(["launchctl", "disable", schedules.domain + "/" + label])
        require(schedules.disabled().get(label) is True, "FREEZE_DISABLE_UNCONFIRMED")
        states = _partial(host, journal)
        _remember_daemons(journal, states)
        write_json(path, journal)  # 当场 Bot 身份必须在 bootout 前持久化。
        if label != UI and states[label]["loaded"]:
            schedules.runner.run(["launchctl", "bootout", schedules.domain + "/" + label])
            schedules.wait_unloaded(label)
        require(_is_target(row, _state(host, row)), "FREEZE_ITEM_UNCONFIRMED")
        journal["done"].append(label)
        journal["pending"] = None
        write_json(path, journal)
    host.retirement_check(frozen=True)
    journal["complete"] = True
    write_json(path, journal)
    return journal
