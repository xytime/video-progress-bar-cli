"""本机维护命令；来源回执与生产采用授权分开，绝不操作搜索开关。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-12 | Codex | enter/status/resume/stop-ui 与启动归属预检 |
"""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from video_processing.core.maintenance import gate, MaintenanceDenied
from video_processing.core.maintenance_runtime import inspection, stop_ui


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=["enter", "status", "resume", "stop-ui", "check-ui", "require-running"])
    parser.add_argument("--reason", default="维护启动")
    parser.add_argument("--expected-version", type=int)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--pid", type=int)
    args = parser.parse_args(argv)
    control = gate()
    try:
        if args.action == "enter":
            control.enter(args.reason)
            result = inspection(control, evidence=args.evidence)
        elif args.action == "require-running":
            control.require_running()
            result = {"running": True}
        elif args.action == "stop-ui":
            result = stop_ui(control, evidence=args.evidence)
        else:
            result = inspection(control, evidence=args.evidence)
            if args.action == "resume":
                if args.expected_version is None or not result["safe"]:
                    raise MaintenanceDenied("NOT_VERIFIED_IDLE")
                result = control.resume(args.expected_version, validated=True)
            elif args.action == "check-ui":
                owner = result["workers"].get("ui")
                if not owner or owner["pid"] != args.pid:
                    raise MaintenanceDenied("UI_OWNER_UNKNOWN")
            elif not result["safe"]:
                print(json.dumps(result, ensure_ascii=False))
                return 2
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (MaintenanceDenied, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "code": getattr(exc, "code", "CONTROL_WRITE_FAILED")}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
