"""本机受控部署：plan/apply/status/recover；搜索始终保持关闭。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-13 | Codex | 单入口顺序执行、私有回执与明确恢复 |
"""
import argparse
import json
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from config.settings import settings
from video_processing.core.deployment import Deployment, DeploymentDenied, read_json, write_json, require
from video_processing.core.deployment_sources import prepare
from video_processing.core.deployment_schedules import Schedules, UI
from video_processing.core.deployment_host import HostDeployment, LOADED_IMPLEMENTATION
from video_processing.core.maintenance_runtime import protection_snapshot


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=["plan", "apply", "status", "recover"])
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--target")
    parser.add_argument("--tested-manifest", type=Path)
    parser.add_argument("--overlay", type=Path)
    args = parser.parse_args(argv)
    directory = args.directory.resolve()
    try:
        require(not directory.is_relative_to(settings.project_root.resolve()), "PRIVATE_DIRECTORY_REQUIRED")
        if args.action == "plan":
            require(args.target and args.tested_manifest and not directory.exists(), "NEW_PLAN_ARGUMENTS_REQUIRED")
            directory.mkdir(parents=True, mode=0o700)
            sources = prepare(settings.project_root, args.target, directory, args.tested_manifest, args.overlay)
            schedules = Schedules(settings.project_root, directory).snapshot()
            ui = next(r for r in schedules["launchd"] if r["label"] == UI)
            require(ui["loaded"] and not ui["disabled"], "UI_ORIGINAL_STATE_UNSUPPORTED")
            plan = {"schema": 1, "id": uuid.uuid4().hex, "root": str(settings.project_root), "sources": sources,
                    "schedules": schedules, "protections": protection_snapshot(), "implementation": LOADED_IMPLEMENTATION}
            write_json(directory / "plan.json", plan)
            print(json.dumps({"planned": True, "id": plan["id"], "path": str(directory / "plan.json")}, ensure_ascii=False))
            return 0
        plan = read_json(directory / "plan.json")
        require(plan["schema"] == 1, "PLAN_SCHEMA_INVALID")
        deploy = Deployment(plan, directory, None if args.action == "status" else HostDeployment(plan, directory))
        result = deploy.status() if args.action == "status" else deploy.run(recover=args.action == "recover")
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "code": getattr(exc, "code", type(exc).__name__),
                          "recovery": "保持当前现场；先运行 status，再经核实使用 recover。不会自动启动或恢复业务。",
                          "directory": str(directory)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
