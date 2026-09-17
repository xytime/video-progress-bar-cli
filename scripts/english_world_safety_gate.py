#!/usr/bin/env python3
"""为英语世界成片生成可绑定的 fail-closed 安全回执。

此命令不调用模型。视觉审核由已受限的独立步骤生成 JSON 回执后作为输入传入；
没有该回执、其 effort 不是 high，或来源/成片文本无法读取时，输出均为非 PASS。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-17 | Codex | 新增成片交付前的文本、频道策略与视觉回执绑定命令。 |
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from video_processing.english_world.safety_gate import (
    attach_artifact_binding,
    evaluate_delivery,
)


def _read_json(path: Path) -> dict:
    value = json.loads(path.expanduser().read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("视觉审核回执必须是 JSON 对象")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--title", required=True)
    parser.add_argument("--timeline", required=True, type=Path)
    parser.add_argument("--mp4", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--visual-review-report", required=True, type=Path)
    args = parser.parse_args()

    receipt = evaluate_delivery(
        title=args.title.strip(),
        timeline_path=args.timeline,
        visual_review=_read_json(args.visual_review_report),
        require_visual_review=True,
    )
    if receipt["state"] == "PASS":
        receipt = attach_artifact_binding(receipt, mp4=args.mp4, manifest=args.manifest, timeline=args.timeline)
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    print(f"English World safety gate: {receipt['state']}; receipt={output}")
    return 0 if receipt["state"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())

