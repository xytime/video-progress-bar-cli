"""本机部署适配器：每次动作前复核真实现场，沿用维护 inspection。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| publishing-recovery-v1 | 2026-10-23 | Codex | 发布恢复 worker 空闲后沿用精确身份受控停止。 |
| 1.4.0 | 2026-10-18 | AGY | stop() 兼容独立二创执行者 wallstreet-worker 受控校验与 SIGTERM 退出 |
| 1.2.0 | 2026-10-14 | Codex | 已完成阶段配置可原样保留部署；仍验证持久 OFF、来源、备份及预算 |
| 1.3.0 | 2026-10-15 | Codex | 绑定已完成部署与精确角色快照，安全退役源码漂移的旧 worker |
| keyword-stage-v1 | 2026-10-14 | Codex | 非秘密阶段配置绑定原生部署日志，维护、漂移及完成回读闭锁 |
| 1.0.0 | 2026-10-13 | Codex | 来源证据、正常退出、一致性备份、维护启动和恢复 |
"""
from pathlib import Path
import os
import signal
import time
import httpx

from config.settings import settings
from video_processing.db.database import PipelineDB
from .deployment import Deployment, require, write_json, read_json, digest, DeploymentDenied
from .deployment_sources import Sources, sha
from .deployment_schedules import Schedules, UI
from .maintenance import gate
from .maintenance_runtime import inspection, code_hash, protection_snapshot, process_birth, SOURCE_GROUPS, ROLES, PROTOCOL
from .task_lease import read_lease_owner


def implementation():
    paths = [Path(__file__).with_name(n + ".py") for n in
             ("deployment", "deployment_sources", "deployment_schedules", "deployment_host", "maintenance_runtime", "keyword_rollout", "keyword_job_proof")]
    paths.append(Path(__file__).resolve().parents[2] / "config" / "keyword_rollout.py")
    return {str(p.relative_to(Path(__file__).resolve().parents[2])): sha(p.read_bytes()) for p in paths}


LOADED_IMPLEMENTATION = implementation()


def retirement_snapshot(root, directory):
    """仅已完成原生部署可证明旧来源；不允许调用方提供任意可信哈希。"""
    directory = Path(directory).resolve()
    previous = read_json(directory / "plan.json")
    require(Path(previous["root"]).resolve() == Path(root).resolve(), "RETIREMENT_ROOT_MISMATCH")
    require(Deployment(previous, directory, None).status()["state"] == "COMPLETE", "RETIREMENT_DEPLOYMENT_INCOMPLETE")
    proof_names = ["plan.json", "journal.json", "start.json"]
    if (directory / "adopt.json").exists():
        adopted = read_json(directory / "adopt.json")
        proof_names.append("adopt.json")
    else:
        # 中断发生在采用后、写回执前时，recover 会验证采用后置条件并记 COMPLETE。
        # 仅接受完整原生部署的 intent、来源验证、启动与最终回读链，不补造旧回执。
        intent = read_json(directory / "adopt-intent.json")
        sources = read_json(directory / "sources.json")
        verified = read_json(directory / "verify.json")
        require(intent.get("target") == previous["sources"]["target"]
                and intent.get("before") == previous["sources"]["before"]["head"]
                and sources.get("schema") == 1 and sources.get("groups") == sorted(SOURCE_GROUPS)
                and verified.get("ok") is True, "RETIREMENT_PROOF_INVALID")
        adopted = {"ok": True, "target": intent["target"], "source_hash": sources.get("source_hash")}
        proof_names.extend(["adopt-intent.json", "sources.json", "verify.json"])
    started = read_json(directory / "start.json")["inspection"]
    require(adopted.get("ok") is True and adopted.get("target") == previous["sources"]["target"]
            and started.get("safe") is True, "RETIREMENT_PROOF_INVALID")
    source_hash = adopted["source_hash"]
    require(len(source_hash) == 64 and all(c in "0123456789abcdef" for c in source_hash)
            and started["workers"].get("ui", {}).get("source_hash") == source_hash, "RETIREMENT_SOURCE_UNPROVEN")
    owners = {}
    for role in ROLES:
        row = read_lease_owner(settings.maintenance_state_path.with_suffix(".workers") / (role + ".lock"))
        if row and row.get("source_hash") == source_hash:
            require(row.get("protocol") == PROTOCOL and row.get("cwd") == str(root)
                    and process_birth(row["pid"]) == row.get("birth"), "RETIREMENT_OWNER_CHANGED")
            owners[role] = row
    require(owners and owners.get("ui") == started["workers"].get("ui"), "RETIREMENT_UI_UNPROVEN")
    return {"directory": str(directory), "owners": owners,
            "files": {name: sha((directory / name).read_bytes()) for name in proof_names}}


def retirement_owners(proof):
    if not proof:
        return {}
    directory = Path(proof["directory"])
    require(all(sha((directory / name).read_bytes()) == value for name, value in proof["files"].items()),
            "RETIREMENT_PROOF_DRIFT")
    return proof["owners"]


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
        from .keyword_rollout import KeywordTransition
        self.keyword = KeywordTransition(plan, directory, settings) if plan.get("keyword_transition") else None
        self.keyword_after = False

    def preserves_keyword_profile(self):
        return self.plan.get("keyword_preserve") is True

    def protections(self):
        require(not (self.preserves_keyword_profile() and self.plan.get("keyword_transition")),
                "KEYWORD_DEPLOYMENT_MODE_CONFLICT")
        if getattr(self, "keyword", None):
            self.keyword.protections(protection_snapshot(), after=self.keyword_after)
            return
        require(protection_snapshot() == self.plan["protections"], "PROTECTION_DRIFT")
        if self.preserves_keyword_profile():
            from .keyword_rollout import verify_loaded
            require(verify_loaded(settings, complete=True), "KEYWORD_PROFILE_REQUIRED")
            require(settings.topic_rollout_snapshot() == self.plan["keyword_profile_before"],
                    "KEYWORD_PROFILE_DRIFT")
            return
        require(not settings.topic_search_enabled and not settings.topic_scheduler_enabled and not settings.topic_admission_enabled and not settings.topic_trial_mode
                and not settings.topic_quota_verified and not settings.topic_quota_project,
                "SEARCH_CLOSURE_UNCONFIRMED")

    def safe(self, *, started=False):
        self.protections()
        self.schedules.frozen(self.plan["schedules"], ui_started=started)
        retiring = retirement_owners(self.plan.get("retirement"))
        options = {"retiring_workers": retiring} if retiring else {}
        raw = inspection(self.control, **options)
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
                           "groups": sorted(SOURCE_GROUPS), "protections": protection_snapshot(), "checks": checks,
                           "keyword_profile": settings.topic_rollout_snapshot()})
        result = inspection(self.control, evidence=proof, **options)
        require(result["safe"], "MAINTENANCE_INSPECTION_REJECTED")
        return result

    def preflight(self, step):
        self.keyword_after = step in {"start", "resume", "restore", "verify"}
        if getattr(self, "keyword", None) and step in {"baseline", "freeze", "adopt"}:
            from config.keyword_rollout import expected_protections
            expected_protections(self.plan["protections"], self.plan["keyword_transition"], time.time())
            self.keyword.job_proof()
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
            if self.keyword:
                self.keyword.apply()
                self.keyword_after = True
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
        require(set(after["workers"]) <= {"ready-worker", "wallstreet-worker", "publishing-recovery-worker"}, "UNEXPECTED_REMAINING_WORKER")
        for role in ("ready-worker", "wallstreet-worker", "publishing-recovery-worker"):
            worker = after["workers"].get(role)
            if worker:
                self.owner_check(role, worker)
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
            if getattr(self, "keyword", None) or self.preserves_keyword_profile():
                from .keyword_rollout import values
                require(value.get("configuration") == values(settings)
                        and value.get("rollout") == settings.topic_rollout_snapshot(), "KEYWORD_RUNTIME_CONFIG_MISMATCH")
                require(value["control"]["mode"] == "OFF" and value["search_open"] is False
                        and not value["collection"]["admission"]
                        and not any(j["state"] in {"RUNNING", "STOPPING"} for j in value["jobs"]),
                        "SEARCH_RUNTIME_NOT_CLOSED")
            else:
                require(value["control"]["mode"] == "OFF" and value["search_open"] is False and value["can_enable"] is False
                        and value["jobs"] == [], "SEARCH_RUNTIME_NOT_CLOSED")
            if maintenance:
                require(value["maintenance"]["state"] == maintenance, "RUNTIME_MAINTENANCE_MISMATCH")
            keys = ("control", "maintenance", "jobs", "budget", "search_open", "can_enable")
            if getattr(self, "keyword", None) or self.preserves_keyword_profile():
                keys += ("configuration", "rollout", "collection", "trial")
            return {k: value[k] for k in keys}

    def verify(self, step, result):
        self.keyword_after = step in {"adopt", "start", "resume", "restore", "verify"}
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
        if getattr(self, "keyword", None):
            self.keyword_after = settings._topic_rollout_record is not None and (
                settings._topic_rollout_record.get("deployment_id") == self.plan["id"])
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
        self.keyword_after = True
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
        baseline = read_json(self.directory / "baseline.json")["runtime"]
        if self.keyword or self.preserves_keyword_profile():
            require(runtime["trial"]["budget"] == baseline["trial"]["budget"], "SEARCH_BUDGET_CHANGED")
            return runtime
        previous = baseline["budget"]
        budget = runtime["budget"]
        require(budget == previous if budget["day"] == previous["day"] else budget["search"] == budget["general"] == 0,
                "SEARCH_BUDGET_CHANGED")
        return runtime
