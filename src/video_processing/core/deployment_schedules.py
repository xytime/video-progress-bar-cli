"""macOS 部署来源：原状态绑定、停止重拉起、逐项恢复；不操作其他项目。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-10-21 | Codex | 保存已核验运行调度意图，阻止冻结现场成为新基线；恢复定义使用本机私有目录。 |
| 1.0.0 | 2026-10-13 | Codex | cron/launchd 受控快照与回读、保留原禁用及一次性任务 |
"""
from pathlib import Path
import hashlib
import json
import os
import plistlib
import re
import subprocess
import time

from .deployment import require, write_json, DeploymentDenied
from .deployment_sources import sha

UI = "com.videopipeline.ui"


class MacCommands:
    def run(self, args, *, data=None, allowed=(0,)):
        result = subprocess.run(args, input=data, capture_output=True, timeout=20)
        require(result.returncode in allowed, "HOST_COMMAND_FAILED:" + args[0])
        return result


class Schedules:
    def __init__(self, root, directory, runner=None):
        self.root, self.directory = Path(root), Path(directory)
        self.runner = runner or MacCommands()
        self.domain = "gui/" + str(os.getuid())

    def cron(self):
        r = self.runner.run(["crontab", "-l"], allowed=(0, 1))
        require(r.returncode == 0 or b"no crontab" in r.stderr.lower(), "CRON_READ_UNKNOWN")
        return r.stdout

    def disabled(self):
        text = self.runner.run(["launchctl", "print-disabled", self.domain]).stdout.decode()
        return {label: value in {"true", "disabled"} for label, value in
                re.findall(r'"([^"]+)"\s*=>\s*(true|false|disabled|enabled)', text)}

    def service(self, label):
        r = self.runner.run(["launchctl", "print", self.domain + "/" + label], allowed=(0, 113))
        if r.returncode:
            require(b"Could not find service" in r.stderr, "LAUNCHD_READ_UNKNOWN")
            return {"loaded": False, "pid": None}
        text = r.stdout.decode()
        def field(pattern):
            match = re.search(pattern, text, re.M)
            return match.group(1).strip() if match else None
        pid = field(r"^\s*pid = (\d+)\s*$")
        return {"loaded": True, "pid": int(pid) if pid else None,
                "cwd": field(r"^\s*working directory = (.*)$"), "path": field(r"^\s*path = (.*)$")}

    def loaded_labels(self):
        text = self.runner.run(["launchctl", "list"]).stdout.decode()
        return {line.split()[-1] for line in text.splitlines() if line.split() and line.split()[-1].startswith("com.videopipeline.")}

    def snapshot(self):
        self.require_operational_intent()
        disabled = self.disabled()
        rows = []
        paths = sorted((Path.home() / "Library/LaunchAgents").glob("com.videopipeline.*.plist"))
        require(paths, "LAUNCHD_SOURCES_MISSING")
        for path in paths:
            definition = plistlib.loads(path.read_bytes())
            label = definition["Label"]
            require(label == path.stem, "LAUNCHD_OWNER_UNKNOWN")
            bindings = self.owner_binding(definition)
            state = self.service(label)
            loaded_path = Path(state["path"]) if state["loaded"] else path
            payload = loaded_path.read_bytes()
            current = plistlib.loads(payload)
            require(current.get("Label") == label and self.owner_binding(current) == bindings, "LOADED_SOURCE_UNKNOWN")
            require(label == UI or not state["pid"], "SCHEDULE_JOB_ACTIVE")
            # 非秘密摘要；原 plist 私有保存仅用于恢复，不能提交到仓库。
            copied = self.directory / "plists" / path.name
            copied.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            copied.write_bytes(payload)
            copied.chmod(0o600)
            rows.append({"label": label, "path": str(path), "sha256": sha(path.read_bytes()),
                         "loaded_path": str(loaded_path), "loaded_sha256": sha(payload),
                         "loaded": state["loaded"], "disabled": disabled.get(label, bool(current.get("Disabled", False))),
                         "run_at_load": bool(current.get("RunAtLoad")), "keepalive": bool(current.get("KeepAlive")),
                         "bindings": bindings})
        require(UI in {r["label"] for r in rows}, "UI_SOURCE_MISSING")
        require(self.loaded_labels() <= {r["label"] for r in rows}, "UNKNOWN_LOADED_SERVICE")
        cron = self.cron()
        frozen = b"".join(line for line in cron.splitlines(keepends=True) if str(self.root).encode() not in line)
        for name, payload in [("cron.original", cron), ("cron.frozen", frozen)]:
            p = self.directory / name
            p.write_bytes(payload)
            p.chmod(0o600)
        return {"launchd": rows, "cron": sha(cron), "frozen_cron": sha(frozen)}

    @property
    def runtime_directory(self):
        # launchd 拒绝某些外置卷的所有权语义；私有定义始终放本机 HOME。
        key = hashlib.sha256(str(self.root.resolve()).encode()).hexdigest()[:20]
        return Path.home() / "Library/Application Support/VideoProcessing/schedules" / key

    def project_cron_digest(self):
        return sha(b"".join(line for line in self.cron().splitlines(keepends=True)
                            if str(self.root).encode() in line))

    def require_operational_intent(self):
        """只读比对最近一次完整恢复；不得把维护残留当成正常运行基线。"""
        path = self.runtime_directory / "operational-intent.json"
        if not path.exists():
            # 首次接入也不能认可“只恢复了 UI”的冻结现场。
            recurring = []
            for source in (Path.home() / "Library/LaunchAgents").glob("com.videopipeline.*.plist"):
                config = plistlib.loads(source.read_bytes())
                if config.get("Label") != UI and any(config.get(k) for k in
                        ("StartInterval", "StartCalendarInterval", "KeepAlive")):
                    recurring.append(config)
            if recurring:
                disabled = self.disabled()
                require(any(not disabled.get(c["Label"], bool(c.get("Disabled")))
                            and self.service(c["Label"])["loaded"] for c in recurring),
                        "PRODUCTION_SCHEDULES_SUSPENDED")
            return
        try:
            intent = json.loads(path.read_text())
            require(intent["schema"] == 1 and intent["root"] == str(self.root.resolve()),
                    "SCHEDULE_INTENT_INVALID")
            require(self.project_cron_digest() == intent["project_cron"], "PROJECT_CRON_NOT_OPERATIONAL")
            require({p.stem for p in (Path.home() / "Library/LaunchAgents").glob("com.videopipeline.*.plist")}
                    == {row["label"] for row in intent["launchd"]}, "LAUNCHD_INVENTORY_DRIFT")
            disabled = self.disabled()
            for row in intent["launchd"]:
                observed = self.service(row["label"])
                require(observed["loaded"] == row["loaded"]
                        and disabled.get(row["label"], row["disabled"]) == row["disabled"],
                        "PRODUCTION_SCHEDULE_NOT_RESTORED:" + row["label"])
                if observed["loaded"]:
                    require(sha(Path(observed["path"]).read_bytes()) == row["definition_sha256"],
                            "OPERATIONAL_DEFINITION_DRIFT:" + row["label"])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise DeploymentDenied("SCHEDULE_INTENT_INVALID") from exc

    def record_operational_intent(self, plan):
        """完整回读通过后记录非秘密运行意图；失败不能覆盖上次正常状态。"""
        self.restored(plan)
        rows = []
        for row in plan["launchd"]:
            observed = self.service(row["label"])
            rows.append({"label": row["label"], "loaded": row["loaded"], "disabled": row["disabled"],
                         "definition_sha256": sha(Path(observed["path"]).read_bytes()) if row["loaded"] else None})
        self.runtime_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self.runtime_directory / "operational-intent.json"
        write_json(path, {"schema": 1, "root": str(self.root.resolve()),
                          "project_cron": self.project_cron_digest(), "launchd": rows})
        path.chmod(0o600)

    def owner_binding(self, definition):
        if definition.get("WorkingDirectory") == str(self.root):
            return []
        # 既有封面服务在 HOME 执行，归属由具名 launcher 中的项目路径证明。
        launcher = Path.home() / "Library/Application Support/VideoPrecessing/ai-cover-doer-launcher.sh"
        require(definition.get("Label") == "com.videopipeline.ai-cover-doer"
                and definition.get("ProgramArguments") == ["/bin/bash", str(launcher)]
                and not launcher.is_symlink(), "LAUNCHD_OWNER_UNKNOWN")
        payload = launcher.read_bytes()
        require(str(self.root).encode() in payload, "LAUNCHER_PROJECT_UNKNOWN")
        return [{"path": str(launcher), "sha256": sha(payload)}]

    def files_check(self, plan):
        labels = {r["label"] for r in plan["launchd"]}
        require({p.stem for p in (Path.home() / "Library/LaunchAgents").glob("com.videopipeline.*.plist")} == labels,
                "LAUNCHD_INVENTORY_DRIFT")
        require(self.loaded_labels() <= labels, "UNKNOWN_LOADED_SERVICE")
        for row in plan["launchd"]:
            for binding in row.get("bindings", []):
                require(sha(Path(binding["path"]).read_bytes()) == binding["sha256"], "LAUNCHER_DRIFT")
            require(sha(Path(row["path"]).read_bytes()) == row["sha256"], "PLIST_EDIT_CONFLICT")
            require(sha(Path(row["loaded_path"]).read_bytes()) == row["loaded_sha256"], "LOADED_PLIST_DRIFT")
            require(sha((self.directory / "plists" / (row["label"] + ".plist")).read_bytes()) == row["loaded_sha256"], "PLIST_BACKUP_DRIFT")
        require(sha((self.directory / "cron.original").read_bytes()) == plan["cron"], "CRON_BACKUP_DRIFT")
        require(sha((self.directory / "cron.frozen").read_bytes()) == plan["frozen_cron"], "CRON_BACKUP_DRIFT")

    def baseline(self, plan):
        self.files_check(plan)
        require(sha(self.cron()) == plan["cron"], "CRON_EDIT_CONFLICT")
        disabled = self.disabled()
        for row in plan["launchd"]:
            state = self.service(row["label"])
            require(state["loaded"] == row["loaded"] and disabled.get(row["label"], row["disabled"]) == row["disabled"], "SCHEDULE_BASELINE_DRIFT")
            require(row["label"] == UI or not state["pid"], "SCHEDULE_JOB_ACTIVE")

    def freeze(self, plan):
        self.baseline(plan)
        self.runner.run(["crontab", "-"], data=(self.directory / "cron.frozen").read_bytes())
        for row in plan["launchd"]:
            label = row["label"]
            self.files_check(plan)
            self.runner.run(["launchctl", "disable", self.domain + "/" + label])
            if label != UI and row["loaded"]:
                require(not self.service(label)["pid"], "SCHEDULE_JOB_ACTIVE")
                self.runner.run(["launchctl", "bootout", self.domain + "/" + label])
                self.wait_unloaded(label)
        self.frozen(plan)

    def wait_unloaded(self, label):
        deadline = time.monotonic() + 15
        while self.service(label)["loaded"]:
            require(time.monotonic() < deadline, "SERVICE_UNLOAD_TIMEOUT")
            time.sleep(.1)

    def frozen(self, plan, *, ui_started=False):
        self.files_check(plan)
        require(sha(self.cron()) == plan["frozen_cron"], "CRON_EDIT_CONFLICT")
        disabled = self.disabled()
        for row in plan["launchd"]:
            label = row["label"]
            require(disabled.get(label) == (False if label == UI and ui_started else True), "LAUNCHD_FREEZE_DRIFT")
            if label != UI:
                require(not self.service(label)["loaded"], "UNFROZEN_SERVICE")

    def restore(self, plan):
        self.frozen(plan, ui_started=True)
        for row in plan["launchd"]:
            self.files_check(plan)
            label = row["label"]
            if label == UI:
                continue
            if row["loaded"]:
                original = self.directory / "plists" / (label + ".plist")
                config = plistlib.loads(original.read_bytes())
                # 恢复周期/日历，但不把已完成的一次性任务再跑一遍。
                if config.get("RunAtLoad") and not config.get("KeepAlive"):
                    config["RunAtLoad"] = False
                folder = self.runtime_directory / sha(str(self.directory.resolve()).encode())[:20]
                folder.mkdir(parents=True, exist_ok=True, mode=0o700)
                path = folder / (label + ".restore.plist")
                path.write_bytes(plistlib.dumps(config))
                path.chmod(0o600)
                if not row["disabled"]:
                    self.runner.run(["launchctl", "enable", self.domain + "/" + label])
                self.runner.run(["launchctl", "bootstrap", self.domain, str(path)])
            self.runner.run(["launchctl", "disable" if row["disabled"] else "enable", self.domain + "/" + label])
        require(sha(self.cron()) == plan["frozen_cron"], "CRON_EDIT_CONFLICT")
        self.runner.run(["crontab", "-"], data=(self.directory / "cron.original").read_bytes())
        self.restored(plan)
        self.record_operational_intent(plan)

    def restored(self, plan):
        self.files_check(plan)
        require(sha(self.cron()) == plan["cron"], "CRON_NOT_RESTORED")
        disabled = self.disabled()
        for row in plan["launchd"]:
            observed = self.service(row["label"])
            require(observed["loaded"] == row["loaded"], "LOADED_STATE_NOT_RESTORED")
            require(disabled.get(row["label"], row["disabled"]) == row["disabled"], "ENABLED_STATE_NOT_RESTORED")
            if row["loaded"]:
                expected = plistlib.loads((self.directory / "plists" / (row["label"] + ".plist")).read_bytes())
                if row["label"] != UI and expected.get("RunAtLoad") and not expected.get("KeepAlive"):
                    expected["RunAtLoad"] = False
                require(plistlib.loads(Path(observed["path"]).read_bytes()) == expected, "RESTORED_DEFINITION_MISMATCH")
