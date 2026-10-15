"""本机受控部署：plan/apply/status/recover；部署期间搜索保持关闭，可原样保留已完成采用的阶段配置。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.2.0 | 2026-10-14 | Codex | 显式保留已完成阶段配置，拒绝配置转换混用 |
| 1.3.0 | 2026-10-15 | Codex | 可引用已完成部署证明旧 worker 来源，精确身份只用于维护退役 |
| keyword-stage-v1 | 2026-10-14 | Codex | 非秘密阶段配置绑定原生部署日志，维护、漂移及完成回读闭锁 |
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
from video_processing.core.deployment_host import HostDeployment, LOADED_IMPLEMENTATION, retirement_snapshot
from video_processing.core.maintenance_runtime import protection_snapshot


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=["plan", "apply", "status", "recover"])
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--target")
    parser.add_argument("--tested-manifest", type=Path)
    parser.add_argument("--overlay", type=Path)
    parser.add_argument("--retire-from-deployment", type=Path)
    parser.add_argument("--preserve-keyword-profile", action="store_true")
    parser.add_argument("--keyword-stage", choices=["TRIAL", "OFF", "MANUAL", "SCHEDULED", "ADMISSION", "LONG_TERM"])
    parser.add_argument("--keyword-evidence", type=Path)
    args = parser.parse_args(argv)
    directory = args.directory.resolve()
    try:
        require(not directory.is_relative_to(settings.project_root.resolve()), "PRIVATE_DIRECTORY_REQUIRED")
        if args.action == "plan":
            require(args.target and args.tested_manifest and not directory.exists(), "NEW_PLAN_ARGUMENTS_REQUIRED")
            require(not args.preserve_keyword_profile or not (args.keyword_stage or args.keyword_evidence),
                    "KEYWORD_DEPLOYMENT_MODE_CONFLICT")
            directory.mkdir(parents=True, mode=0o700)
            sources = prepare(settings.project_root, args.target, directory, args.tested_manifest, args.overlay)
            schedules = Schedules(settings.project_root, directory).snapshot()
            ui = next(r for r in schedules["launchd"] if r["label"] == UI)
            require(ui["loaded"] and not ui["disabled"], "UI_ORIGINAL_STATE_UNSUPPORTED")
            plan = {"schema": 1, "id": uuid.uuid4().hex, "root": str(settings.project_root), "sources": sources,
                    "schedules": schedules, "protections": protection_snapshot(), "implementation": LOADED_IMPLEMENTATION}
            if args.retire_from_deployment:
                plan["retirement"] = retirement_snapshot(settings.project_root, args.retire_from_deployment)
            if args.preserve_keyword_profile:
                from video_processing.core.keyword_rollout import verify_loaded
                require(verify_loaded(settings, complete=True), "KEYWORD_PROFILE_REQUIRED")
                plan["keyword_preserve"] = True
                plan["keyword_profile_before"] = settings.topic_rollout_snapshot()
            if args.keyword_stage:
                import time
                from config.keyword_rollout import transition, expected_protections
                from video_processing.core.keyword_rollout import values, verify_loaded, KeywordTransition
                verify_loaded(settings, complete=True)
                evidence = read_json(args.keyword_evidence) if args.keyword_evidence else {}
                plan["keyword_transition"] = transition(values(settings), args.keyword_stage, evidence, time.time())
                plan["keyword_profile_before"] = settings.topic_rollout_snapshot()
                expected_protections(plan["protections"], plan["keyword_transition"], time.time())
                plan["keyword_job_proof"] = KeywordTransition(plan, directory, settings).job_proof(planning=True)
            else:
                require(args.keyword_evidence is None, "KEYWORD_STAGE_REQUIRED")
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
