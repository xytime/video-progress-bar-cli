"""本机部署适配器：每次动作前复核真实现场，沿用维护 inspection。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-13 | Codex | 来源证据、正常退出、一致性备份、维护启动和恢复 |
"""
from pathlib import Path
import os
import signal
import time
import httpx

from config.settings import settings
from video_processing.db.database import PipelineDB
from .deployment import require, write_json, read_json, digest, DeploymentDenied
from .deployment_sources import Sources, sha
from .deployment_schedules import Schedules, UI
from .maintenance import gate
from .maintenance_runtime import inspection, code_hash, protection_snapshot, process_birth, SOURCE_GROUPS
from .task_lease import read_lease_owner


def implementation():
    paths = [Path(__file__).with_name(n + ".py") for n in
             ("deployment", "deployment_sources", "deployment_schedules", "deployment_host")]
    return {p.name: sha(p.read_bytes()) for p in paths}


LOADED_IMPLEMENTATION = implementation()


class HostDeployment:
    def __init__(self, plan, directory, schedules=None):
        self.plan, self.directory = plan, Path(directory).resolve()
        self.root = Path(plan["root"]).resolve()
        require(self.root == settings.project_root.resolve(), "EXECUTION_ROOT_MISMATCH")
        require(plan["implementation"] == LOADED_IMPLEMENTATION, "EXECUTION_IMPLEMENTATION_MISMATCH")
        self.control = gate()
        self.sources = Sources(self.root, self.directory, plan["sources"])
        self.schedules = schedules or Schedules(self.root, self.directory)
        self.lock_path = settings.default_output_dir / "deployment.lock"

    def protections(self):
        require(protection_snapshot() == self.plan["protections"], "PROTECTION_DRIFT")
        require(not settings.topic_search_enabled and not settings.topic_scheduler_enabled and not settings.topic_admission_enabled and not settings.topic_trial_mode
                and not settings.topic_quota_verified and not settings.topic_quota_project,
                "SEARCH_CLOSURE_UNCONFIRMED")

    def safe(self, *, started=False):
        self.protections()
        self.schedules.frozen(self.plan["schedules"], ui_started=started)
        raw = inspection(self.control)
        require(not raw["active"] and raw["unknown"] == [{"code": "SOURCES_NOT_VERIFIED"}], "MAINTENANCE_NOT_IDLE")
        require(raw["state"] == "MAINTENANCE", "MAINTENANCE_REQUIRED")
        checks = [{"group": "cron", "kind": "cron", "sha256": sha(self.schedules.cron())}]
        observations = {
            "launchd": [{"label": r["label"], "state": "INTEGRATED" if r["label"] == UI and "ui" in raw["workers"] else "FROZEN",
                         "observation": self.schedules.service(r["label"])} for r in self.plan["schedules"]["launchd"]],
            "manual": [{"state": "ABSENT", "unregistered_processes": [], "via": "inspection process/cwd/locks"}],
            "bot": [{"state": "ABSENT", "loaded": False}],
            "independent-workers": [{"state": "INTEGRATED", "workers": raw["workers"], "active": []}],
        }
        for group, readbacks in observations.items():
            path = self.directory / ("source-" + group + ".json")
            write_json(path, {"group": group, "version": raw["version"], "source_hash": code_hash(), "readbacks": readbacks})
            checks.append({"group": group, "kind": "file", "path": str(path), "sha256": sha(path.read_bytes())})
        proof = self.directory / "sources.json"
        write_json(proof, {"schema": 1, "version": raw["version"], "at": time.time(), "source_hash": code_hash(),
                           "groups": sorted(SOURCE_GROUPS), "protections": protection_snapshot(), "checks": checks})
        result = inspection(self.control, evidence=proof)
        require(result["safe"], "MAINTENANCE_INSPECTION_REJECTED")
        return result

    def preflight(self, step):
        self.protections()
        if step in {"baseline", "freeze"}:
            self.sources.baseline()
            self.schedules.baseline(self.plan["schedules"])
            require(self.control.status()["state"] == "RUNNING", "BASELINE_NOT_RUNNING")
            self.web_readback()
        elif step in {"stop", "backup", "adopt"}:
            self.sources.baseline()
            state = self.safe()
            if step != "stop":
                require(not state["workers"], "WORKERS_NOT_STOPPED")
                require(not self.schedules.service(UI)["loaded"], "UI_NOT_UNLOADED")
            if step == "adopt":
                self.backup_valid()
        elif step == "start":
            self.sources.final()
            self.backup_valid()
            require(not self.safe()["workers"], "WORKERS_NOT_STOPPED")
        elif step == "resume":
            self.sources.final()
            self.backup_valid()
            self.safe(started=True)
            self.web_readback(maintenance="MAINTENANCE")
        elif step == "restore":
            self.sources.final()
            require(self.control.status()["state"] == "RUNNING", "RESUME_UNCONFIRMED")
            self.schedules.frozen(self.plan["schedules"], ui_started=True)
            self.web_readback(maintenance="RUNNING")
        elif step == "verify":
            self.final_status()

    def action(self, step):
        if step == "baseline":
            return {"ok": True, "source_hash": code_hash(), "implementation": LOADED_IMPLEMENTATION,
                    "runtime": self.web_readback(maintenance="RUNNING")}
        if step == "freeze":
            self.control.enter("部署 " + self.plan["id"])
            self.schedules.freeze(self.plan["schedules"])
            # 不无限等待；有在途立即保持维护并返回，显式 recover 时重新核验。
            return {"ok": True, "inspection": self.safe()}
        if step == "stop":
            return self.stop()
        if step == "backup":
            receipt = PipelineDB.maintenance_backup(settings.default_output_dir / "pipeline.db", self.directory / "pipeline.sqlite")
            write_json(self.directory / "backup-verified.json", receipt)
            return {"ok": True, "backup": receipt}
        if step == "adopt":
            self.sources.adopt()
            return {"ok": True, "source_hash": code_hash(), "target": self.plan["sources"]["target"]}
        if step == "start":
            row = next(r for r in self.plan["schedules"]["launchd"] if r["label"] == UI)
            require(row["loaded"] and not row["disabled"], "UI_ORIGINAL_STATE_UNSUPPORTED")
            self.schedules.runner.run(["launchctl", "enable", self.schedules.domain + "/" + UI])
            self.schedules.runner.run(["launchctl", "bootstrap", self.schedules.domain, row["loaded_path"]])
            deadline = time.monotonic() + 30
            while True:
                try:
                    self.web_readback(maintenance="MAINTENANCE")
                    state = self.safe(started=True)
                    require("ui" in state["workers"], "UI_NOT_REGISTERED")
                    return {"ok": True, "inspection": state}
                except (httpx.HTTPError, DeploymentDenied):
                    require(time.monotonic() < deadline, "START_TIMEOUT")
                    time.sleep(.25)
        if step == "resume":
            state = self.safe(started=True)
            result = self.control.resume(state["version"], validated=True)
            return {"ok": True, "maintenance": result}
        if step == "restore":
            self.schedules.restore(self.plan["schedules"])
        if step == "verify":
            return {"ok": True, "runtime": self.final_status()}
        return {"ok": True}

    def stop(self):
        state = self.safe()
        ui = state["workers"].get("ui")
        require(ui is not None, "UI_OWNER_UNKNOWN")
        observed = self.schedules.service(UI)
        require(observed["pid"] == ui["pid"] and observed["cwd"] == str(self.root), "UI_OWNER_CHANGED")
        self.owner_check("ui", ui)
        write_json(self.directory / "stop-owners.json", state["workers"])
        self.schedules.runner.run(["launchctl", "bootout", self.schedules.domain + "/" + UI])
        self.wait_exit(ui)
        self.schedules.wait_unloaded(UI)
        after = self.safe()
        require(set(after["workers"]) <= {"ready-worker"}, "UNEXPECTED_REMAINING_WORKER")
        worker = after["workers"].get("ready-worker")
        if worker:
            self.owner_check("ready-worker", worker)
            os.kill(worker["pid"], signal.SIGTERM)
            self.wait_exit(worker)
        require(not self.safe()["workers"], "WORKERS_NOT_STOPPED")
        return {"ok": True, "owners": state["workers"]}

    def owner_check(self, role, owner):
        path = self.control.path.with_suffix(".workers") / (role + ".lock")
        require(read_lease_owner(path) == owner and process_birth(owner["pid"]) == owner["birth"], "PROCESS_OWNER_CHANGED")

    @staticmethod
    def wait_exit(owner):
        deadline = time.monotonic() + 15
        while True:
            try:
                birth = process_birth(owner["pid"])
            except ProcessLookupError:
                return
            require(birth == owner["birth"], "PID_REUSED")
            require(time.monotonic() < deadline, "NORMAL_STOP_TIMEOUT")
            time.sleep(.1)

    def backup_valid(self):
        proof = read_json(self.directory / "backup-verified.json")
        require(PipelineDB.maintenance_verify_backup(self.directory / "pipeline.sqlite", proof), "BACKUP_INVALID")

    def web_readback(self, maintenance=None):
        with httpx.Client(base_url=f"http://127.0.0.1:{settings.dashboard_port}", timeout=3, trust_env=False) as c:
            c.get("/topic-candidates").raise_for_status()
            state = c.get("/api/topic-candidates/state")
            state.raise_for_status()
            value = state.json()
            health = c.get("/api/topic-candidates/health")
            health.raise_for_status()
            require(health.json().get("ready") is True, "TOPIC_NOT_READY")
            require(value["control"]["mode"] == "OFF" and value["search_open"] is False and value["can_enable"] is False
                    and value["jobs"] == [], "SEARCH_RUNTIME_NOT_CLOSED")
            if maintenance:
                require(value["maintenance"]["state"] == maintenance, "RUNTIME_MAINTENANCE_MISMATCH")
            return {k: value[k] for k in ("control", "maintenance", "jobs", "budget", "search_open", "can_enable")}

    def verify(self, step, result):
        if step == "baseline":
            self.sources.baseline()
        elif step == "freeze":
            self.safe()
        elif step == "stop":
            require(not self.safe()["workers"], "WORKERS_NOT_STOPPED")
        elif step == "backup":
            self.backup_valid()
        elif step == "adopt":
            self.sources.final()
            self.safe()
        elif step == "start":
            require("ui" in self.safe(started=True)["workers"], "UI_NOT_REGISTERED")
            self.web_readback(maintenance="MAINTENANCE")
        elif step == "resume":
            require(self.control.status()["state"] == "RUNNING", "RESUME_UNCONFIRMED")
        elif step in {"restore", "verify"}:
            self.final_status()

    def reconcile(self, row):
        self.protections()
        pending = row["pending"]
        if pending is None:
            return "READY"
        # 只用可判定的后置事实。部分采用、部分恢复等结果不明时保留现场。
        try:
            self.verify(pending, {})
            if pending == "baseline":
                return "NOT_STARTED"
            return "DONE"
        except (OSError, ValueError, DeploymentDenied, httpx.HTTPError):
            if pending in {"baseline", "freeze"}:
                try:
                    self.sources.baseline()
                    self.schedules.baseline(self.plan["schedules"])
                    require(self.control.status()["state"] == "RUNNING", "PARTIAL_FREEZE")
                    return "NOT_STARTED"
                except (OSError, DeploymentDenied):
                    pass
            return "UNKNOWN"

    def final_status(self):
        self.protections()
        self.sources.final()
        self.schedules.restored(self.plan["schedules"])
        require(self.control.status()["state"] == "RUNNING", "MAINTENANCE_NOT_RESUMED")
        expected = code_hash()
        for role in ("ui", "auto-pipeline", "queue-runner", "ready-supervisor", "keepalive-watchdog"):
            owner = read_lease_owner(self.control.path.with_suffix(".workers") / (role + ".lock"))
            require(owner and owner["source_hash"] == expected and owner["cwd"] == str(self.root)
                    and process_birth(owner["pid"]) == owner["birth"], "FINAL_WORKER_MISMATCH")
        runtime = self.web_readback(maintenance="RUNNING")
        previous = read_json(self.directory / "baseline.json")["runtime"]["budget"]
        budget = runtime["budget"]
        require(budget == previous if budget["day"] == previous["day"] else budget["search"] == budget["general"] == 0,
                "SEARCH_BUDGET_CHANGED")
        return runtime
