"""失主准入的显式 plan/apply/recover；不改任务、不开闸、不停止进程。"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["plan", "apply", "recover"])
    parser.add_argument("--directory", type=Path, required=True, help="项目外的新审计目录")
    parser.add_argument("--record", action="append", default=[], help="明确选择的32位准入记录ID")
    parser.add_argument("--expected-plan", help="plan返回的摘要，apply/recover必须精确提供")
    args = parser.parse_args(argv)
    from config.settings import settings
    from video_processing.core.deployment import digest, require
    from video_processing.core.maintenance import gate
    from video_processing.core.maintenance_recovery import MaintenanceRecovery
    try:
        directory = args.directory.resolve()
        require(not directory.is_relative_to(settings.project_root.resolve()), "AUDIT_MUST_BE_OUTSIDE_PROJECT")
        require(args.action == "plan" or not args.record, "RECORDS_ONLY_FOR_PLAN")
        recovery = MaintenanceRecovery(gate(), directory)
        if args.action == "plan":
            plan = recovery.plan(args.record)
            result = {"planned": True, "count": len(plan["records"]), "directory": str(directory),
                      "plan_sha256": digest(plan),
                      "task_outcome": "NOT_ASSESSED", "maintenance_resumed": False}
        else:
            require(bool(args.expected_plan), "EXPECTED_PLAN_REQUIRED")
            result = recovery.apply(expected_plan=args.expected_plan, recover=args.action == "recover")
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "code": getattr(exc, "code", type(exc).__name__),
                          "task_outcome": "NOT_ASSESSED", "maintenance_resumed": False}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
