# -*- coding: utf-8 -*-
"""Unit tests for translation_quality_report.

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-05 | Codex  | 初始创建：覆盖字幕/文案翻译质量报告聚合 |
"""

import json
import sys
from pathlib import Path

_src_root = Path(__file__).parent.parent.parent / "src"
if str(_src_root) not in sys.path:
    sys.path.insert(0, str(_src_root))

from video_processing.utils.translation_quality_report import (  # noqa: E402
    aggregate_quality_reports,
    collect_quality_report_paths,
)


def test_collect_quality_report_paths_finds_subtitle_and_copy_reports(tmp_path):
    subtitle = tmp_path / "video.translation_quality.json"
    copy = tmp_path / "video_copy_quality.json"
    ignored = tmp_path / "other.json"
    subtitle.write_text("{}", encoding="utf-8")
    copy.write_text("{}", encoding="utf-8")
    ignored.write_text("{}", encoding="utf-8")

    paths = collect_quality_report_paths(tmp_path)

    assert paths == [subtitle, copy]


def test_aggregate_quality_reports_counts_providers_and_issues(tmp_path):
    subtitle = tmp_path / "video.translation_quality.json"
    subtitle.write_text(
        json.dumps(
            {
                "events": [
                    {
                        "provider": "Gemini",
                        "status": "blocked",
                        "action": "fallback",
                        "warning_issues": [],
                        "blocking_issues": [
                            {"code": "FINANCE_EVENT_DIRECTION_REVERSAL"}
                        ],
                    },
                    {
                        "provider": "Aliyun",
                        "status": "passed",
                        "action": "accept",
                        "warning_issues": [
                            {"code": "FINANCE_TERM_AMBIGUOUS_CLOSE"}
                        ],
                        "blocking_issues": [],
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    copy = tmp_path / "video_copy_quality.json"
    copy.write_text(
        json.dumps(
            {
                "provider": "fallback",
                "status": "blocked",
                "action": "fail",
                "warning_issues": [],
                "blocking_issues": [
                    {"code": "NUMBER_MAGNITUDE_MISMATCH"}
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    summary = aggregate_quality_reports(tmp_path)

    assert summary["files_scanned"] == 2
    assert summary["event_count"] == 3
    assert summary["blocked_count"] == 2
    assert summary["provider_counts"] == {"Aliyun": 1, "Gemini": 1, "fallback": 1}
    assert summary["issue_counts"] == {
        "FINANCE_EVENT_DIRECTION_REVERSAL": 1,
        "FINANCE_TERM_AMBIGUOUS_CLOSE": 1,
        "NUMBER_MAGNITUDE_MISMATCH": 1,
    }
    assert len(summary["blocked_files"]) == 2
