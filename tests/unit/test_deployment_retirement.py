"""独立维护回执退役证明：使用真实角色锁，不操作宿主服务或业务记录。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-20 | Codex | 来源缺项、篡改、PID 身份漂移与证明绑定回归 |
"""
import json

import pytest

from config.settings import settings
from video_processing.core.deployment import DeploymentDenied, write_json
from video_processing.core.deployment_host import retirement_owners
from video_processing.core.deployment_retirement import inspection_retirement_snapshot
from video_processing.core.deployment_sources import sha
from video_processing.core.maintenance_runtime import SOURCE_GROUPS, role_lease
from video_processing.core.task_lease import read_lease_owner


def inspection_receipts(directory, owner):
    workers = {"ui": owner}
    write_json(directory / "final-readback.json", dict(schema=1, version=7, safe=True, state="MAINTENANCE",
                                                      phase="IDLE", active=[], unknown=[], workers=workers))
    readbacks = {
        "launchd": [{"label": "com.videopipeline.ui", "state": "INTEGRATED",
                     "observation": {"loaded": True, "pid": owner["pid"], "cwd": owner["cwd"]}}],
        "independent-workers": [{"state": "INTEGRATED", "workers": workers, "active": []}],
        "manual": [{"state": "ABSENT", "unregistered_processes": [], "via": "inspection process/cwd/locks"}],
        "bot": [{"state": "ABSENT", "loaded": False}],
    }
    checks = [{"group": "cron", "kind": "cron", "sha256": "a" * 64}]
    for group, rows in readbacks.items():
        path = directory / ("source-" + group + ".json")
        write_json(path, dict(group=group, version=7, source_hash=owner["source_hash"], readbacks=rows))
        checks.append(dict(group=group, kind="file", path=str(path), sha256=sha(path.read_bytes())))
    write_json(directory / "sources.json", dict(schema=1, version=7, source_hash=owner["source_hash"],
                                                 groups=sorted(SOURCE_GROUPS), checks=checks))


def test_exact_maintenance_receipts_bind_live_owner_and_all_files(tmp_path, isolated_running_maintenance):
    with role_lease("ui"):
        owner = read_lease_owner(settings.maintenance_state_path.with_suffix(".workers") / "ui.lock")
        inspection_receipts(tmp_path, owner)
        proof = inspection_retirement_snapshot(settings.project_root, tmp_path)
        assert proof["owners"] == {"ui": owner}
        assert len(proof["files"]) == 6
        assert retirement_owners(proof) == {"ui": owner}
        (tmp_path / "source-bot.json").write_text("{}")
        with pytest.raises(DeploymentDenied, match="RETIREMENT_PROOF_DRIFT"):
            retirement_owners(proof)


@pytest.mark.parametrize("fault", ["unsafe", "active", "unknown", "running", "source", "version", "group",
                                    "path", "tamper", "birth", "launchd", "worker", "symlink"])
def test_incomplete_or_changed_proof_never_retires(tmp_path, isolated_running_maintenance, fault):
    with role_lease("ui"):
        owner = read_lease_owner(settings.maintenance_state_path.with_suffix(".workers") / "ui.lock")
        inspection_receipts(tmp_path, owner)
        if fault == "symlink":
            path = tmp_path / "final-readback.json"
            path.rename(tmp_path / "moved.json")
            path.symlink_to(tmp_path / "moved.json")
        elif fault in {"unsafe", "active", "unknown", "running", "birth"}:
            path = tmp_path / "final-readback.json"
            data = json.loads(path.read_text())
            if fault == "unsafe": data["safe"] = False
            if fault == "active": data["active"] = [{"pid": owner["pid"]}]
            if fault == "unknown": data["unknown"] = [{"code": "UNREGISTERED_PROCESS"}]
            if fault == "running": data["state"] = "RUNNING"
            if fault == "birth": data["workers"]["ui"]["birth"] = "reused"
            write_json(path, data)
        elif fault in {"source", "version", "group", "path"}:
            path = tmp_path / "sources.json"
            data = json.loads(path.read_text())
            if fault == "source": data["source_hash"] = "b" * 64
            if fault == "version": data["version"] = 8
            if fault == "group": data["checks"].pop()
            if fault == "path": data["checks"][1]["path"] = str(tmp_path / "outside.json")
            write_json(path, data)
        else:
            group = {"tamper": "bot", "launchd": "launchd", "worker": "independent-workers"}[fault]
            path = tmp_path / ("source-" + group + ".json")
            data = json.loads(path.read_text())
            if fault == "tamper": data["readbacks"][0]["loaded"] = True
            if fault == "launchd": data["readbacks"][0]["observation"]["pid"] += 1
            if fault == "worker": data["readbacks"][0]["active"] = [{"pid": owner["pid"]}]
            write_json(path, data)
            # 后两例即使文件摘要也更新，语义不完整仍拒绝。
            if fault != "tamper":
                sources = json.loads((tmp_path / "sources.json").read_text())
                next(c for c in sources["checks"] if c["group"] == group)["sha256"] = sha(path.read_bytes())
                write_json(tmp_path / "sources.json", sources)
        with pytest.raises(DeploymentDenied):
            inspection_retirement_snapshot(settings.project_root, tmp_path)


def test_same_pid_changed_birth_cannot_be_retirement_owner(tmp_path, isolated_running_maintenance):
    with role_lease("ui"):
        owner = read_lease_owner(settings.maintenance_state_path.with_suffix(".workers") / "ui.lock")
        inspection_receipts(tmp_path, dict(owner, birth="reused"))
        with pytest.raises(DeploymentDenied, match="RETIREMENT_OWNER_CHANGED"):
            inspection_retirement_snapshot(settings.project_root, tmp_path)
