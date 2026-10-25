#!/usr/bin/env python3
"""兼容导出；禁止通过技能旧入口直接生产。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-10-25 | Codex | 旧入口仅提示统一审批 CLI |
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
from video_processing.compliance_remix.remix_pipeline import ComplianceVideoRemixPipeline

if __name__ == "__main__":
    raise SystemExit("此旧入口不执行生产。请使用 scripts/compliance_remix.py 的两阶段审批入口；演练使用 --manifest ... --dry-run。")
