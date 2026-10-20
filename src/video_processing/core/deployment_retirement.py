"""以既有安全维护回执证明精确旧进程；只允许维护中退役，不授权继续业务。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-20 | Codex | 校验独立维护采用的完整来源回执、真实角色锁及进程 birth |
"""
from pathlib import Path

from config.settings import settings
from .deployment import require, read_json
from .deployment_sources import sha
from .maintenance_runtime import PROTOCOL, ROLES, SOURCE_GROUPS, process_birth
from .task_lease import read_lease_owner


def inspection_retirement_snapshot(root, directory):
    """接受已落盘的安全维护回读，拒绝任意哈希、未知来源或变更后的角色身份。"""
    root, directory = Path(root).resolve(), Path(directory).resolve()
    require(not directory.is_relative_to(root), "RETIREMENT_PRIVATE_DIRECTORY_REQUIRED")
    files = {}

    def receipt(name):
        path = directory / name
        require(not path.is_symlink() and path.resolve() == path.absolute(), "RETIREMENT_RECEIPT_SYMLINK")
        data = path.read_bytes()
        files[name] = sha(data)
        return read_json(path)

    started = receipt("final-readback.json")
    require(started.get("schema") == 1 and started.get("safe") is True
            and started.get("state") == "MAINTENANCE" and started.get("phase") == "IDLE"
            and started.get("active") == [] and started.get("unknown") == [], "RETIREMENT_INSPECTION_UNSAFE")
    previous = started.get("workers", {})
    ui = previous.get("ui", {})
    source_hash = ui.get("source_hash", "")
    require(len(source_hash) == 64 and all(c in "0123456789abcdef" for c in source_hash),
            "RETIREMENT_SOURCE_UNPROVEN")
    require(set(previous) <= set(ROLES) and ui.get("cwd") == str(root), "RETIREMENT_ROOT_MISMATCH")
    sources = receipt("sources.json")
    require(sources.get("schema") == 1 and sources.get("version") == started.get("version")
            and sources.get("source_hash") == source_hash
            and sources.get("groups") == sorted(SOURCE_GROUPS), "RETIREMENT_SOURCES_UNPROVEN")
    checks = sources.get("checks", [])
    require(len(checks) == len(SOURCE_GROUPS) and {c.get("group") for c in checks} == SOURCE_GROUPS,
            "RETIREMENT_SOURCES_UNPROVEN")
    observations = {}
    for check in checks:
        group = check["group"]
        if group == "cron":
            require(check.get("kind") == "cron" and len(check.get("sha256", "")) == 64
                    and all(c in "0123456789abcdef" for c in check["sha256"]),
                    "RETIREMENT_SOURCES_UNPROVEN")
            continue
        name = "source-" + group + ".json"
        require(check.get("kind") == "file" and check.get("path") == str(directory / name),
                "RETIREMENT_SOURCE_PATH_INVALID")
        value = receipt(name)
        require(files[name] == check.get("sha256") and value.get("group") == group
                and value.get("version") == started["version"] and value.get("source_hash") == source_hash,
                "RETIREMENT_SOURCE_PROOF_DRIFT")
        observations[group] = value.get("readbacks", [])
    require(observations["independent-workers"] == [{"state": "INTEGRATED", "workers": previous, "active": []}],
            "RETIREMENT_WORKERS_UNPROVEN")
    launchd_ui = [row for row in observations["launchd"] if row.get("label") == "com.videopipeline.ui"]
    require(len(launchd_ui) == 1 and launchd_ui[0].get("state") == "INTEGRATED"
            and launchd_ui[0].get("observation", {}).get("loaded") is True
            and launchd_ui[0].get("observation", {}).get("pid") == ui.get("pid")
            and launchd_ui[0]["observation"].get("cwd") == str(root), "RETIREMENT_UI_UNPROVEN")
    require(all(row.get("state") == "FROZEN" and row.get("observation") == {"loaded": False, "pid": None}
                for row in observations["launchd"] if row.get("label") != "com.videopipeline.ui"),
            "RETIREMENT_SOURCES_UNPROVEN")
    require(observations["manual"] == [{"state": "ABSENT", "unregistered_processes": [],
                                        "via": "inspection process/cwd/locks"}]
            and observations["bot"] == [{"state": "ABSENT", "loaded": False}], "RETIREMENT_SOURCES_UNPROVEN")
    owners = {}
    for role in ROLES:
        row = read_lease_owner(settings.maintenance_state_path.with_suffix(".workers") / (role + ".lock"))
        if row and (role in previous or row.get("source_hash") == source_hash):
            require(row == previous.get(role) and row.get("protocol") == PROTOCOL
                    and row.get("cwd") == str(root) and row.get("source_hash") == source_hash
                    and process_birth(row["pid"]) == row.get("birth"), "RETIREMENT_OWNER_CHANGED")
            owners[role] = row
    require(owners.get("ui") == ui, "RETIREMENT_UI_UNPROVEN")
    return {"kind": "safe-maintenance-inspection", "directory": str(directory), "owners": owners, "files": files}
