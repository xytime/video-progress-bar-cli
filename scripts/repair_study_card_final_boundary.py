#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用通过身份核验的 Whisper 末词终点修正学习卡时间轴。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-03 | Codex | 提供末词字幕框延长故障的一次性、可审计本地校正入口。 |
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from video_processing.study_cards.audio_qa import repair_final_word_boundary  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeline", required=True, type=Path, help="音频 QA 使用过的 enriched timeline")
    parser.add_argument("--audio-qa-report", required=True, type=Path, help="失败的最终音频 QA 报告")
    parser.add_argument("--output", required=True, type=Path, help="新的修正后 timeline JSON")
    return parser.parse_args()


def _read_mapping(path: Path, label: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} 不可读取") from exc
    if not isinstance(payload, Mapping):
        raise ValueError(f"{label} 必须是 JSON 对象")
    return payload


def _write_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(path.name + ".tmp")
    temporary_path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary_path.replace(path)


def main() -> int:
    args = _parse_args()
    try:
        repaired = repair_final_word_boundary(
            _read_mapping(args.timeline, "timeline"),
            _read_mapping(args.audio_qa_report, "audio QA 报告"),
        )
        _write_atomic(args.output, repaired)
    except (OSError, ValueError, TypeError) as exc:
        print(f"repair_study_card_final_boundary: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"state": "REPAIRED", "timeline": str(args.output.resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
