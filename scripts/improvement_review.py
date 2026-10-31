"""本地改进分析与人工审核 CLI；不执行修复、重试或发布。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-01 | Codex | 首期报告、独立方案版本、审核及分层验收记录入口。 |
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from video_processing.improvement.service import run_report
from video_processing.improvement.store import ReviewStore


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="action", required=True)
    report = sub.add_parser("report")
    report.add_argument("--refresh", action="store_true", help="显式更新当日报告，不重复建立事项")
    sub.add_parser("show")
    plan = sub.add_parser("set-plan")
    plan.add_argument("issue_id")
    plan.add_argument("--file", type=Path, required=True)
    for action in ("review", "advance"):
        command = sub.add_parser(action)
        command.add_argument("issue_id")
        command.add_argument("--plan-sha", required=True)
        command.add_argument("--evidence", type=Path, required=True)
        if action == "review":
            command.add_argument("--decision", choices=["APPROVED", "RETURNED", "DEFERRED"], required=True)
            command.add_argument("--reviewer", required=True)
        else:
            command.add_argument("--state", required=True)
    args = parser.parse_args(argv)
    output = ROOT / "output"
    try:
        if args.action == "report":
            result = run_report(output / "pipeline.db", output, refresh=args.refresh)
        else:
            store = ReviewStore(output / "improvement")
            with store.locked():
                if args.action == "show":
                    record = store.read()
                    result = dict(issues=[{k: i[k] for k in ("id", "title", "state", "plan_version", "plan_sha")} for i in record["issues"].values()])
                elif args.action == "set-plan":
                    result = dict(report=str(store.set_plan(args.issue_id, json.loads(args.file.read_text()))))
                elif args.action == "review":
                    result = dict(report=str(store.review(args.issue_id, args.decision, args.plan_sha, args.reviewer, args.evidence)))
                else:
                    result = dict(report=str(store.advance(args.issue_id, args.state, args.plan_sha, args.evidence)))
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps(dict(state="UNAVAILABLE", error_type=type(exc).__name__,
                              message="保留最近有效报告；检查本地失败回执与方案版本。"), ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
