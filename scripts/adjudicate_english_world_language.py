#!/usr/bin/env python3
"""为已核实的 P1 误报建立可审计裁决，不修改原始 AGY 结果。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-10 | Codex | 仅允许带外部依据的 P1 误报裁决，并绑定原始报告。 |
"""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from video_processing.study_cards.language_qa import (  # noqa: E402
    VERSION, apply_adjudications, atomic_json, digest, read_json,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeline", type=Path, required=True)
    parser.add_argument("--check", required=True)
    parser.add_argument("--target", action="append", required=True,
                        help="可重复；同一 check 下的每个 P1 误报目标")
    parser.add_argument("--reason", required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--source-label", default="")
    args = parser.parse_args()
    root = args.timeline.expanduser().resolve().parent
    report_path = root / "qa/language_qa.json"
    report = read_json(report_path)
    if report.get("version") != VERSION or report.get("state") != "FAIL":
        raise ValueError("只可裁决当前绑定且失败的语言审校报告")
    base_report = {key: value for key, value in report.items()
                   if key not in {"adjudications", "effective_result", "adjudication_version"}}
    base_report["state"] = "FAIL"
    adjudications = list(report.get("adjudications", []))
    for target in args.target:
        adjudications.append({
            "check": args.check, "target": target, "from_status": "FAIL", "from_severity": "P1",
            "decision": "OVERRULE_P1_FALSE_POSITIVE", "reason": args.reason,
            "source_url": args.source_url, "source_label": args.source_label,
            "report_sha256": digest(base_report),
        })
    effective = apply_adjudications(report["result"], adjudications)
    report["adjudications"] = adjudications
    report["effective_result"] = effective
    report["state"] = "PASS"
    report["adjudication_version"] = "english-world-language-adjudication-v1"
    atomic_json(report_path, report)
    print("language QA adjudication: PASS")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"language QA adjudication: {exc}", file=sys.stderr)
        raise SystemExit(2)
