# -*- coding: utf-8 -*-
"""Unit tests for translation_quality_report.

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-05 | Codex  | 初始创建：覆盖字幕/文案翻译质量报告聚合 |
| 1.1.0   | 2026-07-05 | Codex  | 覆盖术语一致性 warning 进入聚合统计 |
| 1.2.0   | 2026-07-05 | Codex  | 覆盖 warning_count/warning_files 聚合字段 |
| 1.3.0   | 2026-07-05 | Codex  | 覆盖 warning/blocking issue counts 分离统计 |
| 1.4.0   | 2026-07-06 | Codex  | 覆盖 provider_issue_counts 按供应商归因问题类型 |
| 1.5.0   | 2026-07-06 | Codex  | 覆盖 selected 候选维度聚合统计 |
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
                        "selected": True,
                        "warning_issues": [
                            {"code": "FINANCE_TERM_AMBIGUOUS_CLOSE"},
                            {"code": "TERM_CONSISTENCY_FUND_CLOSE_DRIFT"},
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
    assert summary["selected_count"] == 1
    assert summary["selected_warning_count"] == 1
    assert summary["warning_count"] == 1
    assert summary["blocked_count"] == 2
    assert summary["provider_counts"] == {"Aliyun": 1, "Gemini": 1, "fallback": 1}
    assert summary["selected_provider_counts"] == {"Aliyun": 1}
    assert summary["issue_counts"] == {
        "FINANCE_EVENT_DIRECTION_REVERSAL": 1,
        "FINANCE_TERM_AMBIGUOUS_CLOSE": 1,
        "NUMBER_MAGNITUDE_MISMATCH": 1,
        "TERM_CONSISTENCY_FUND_CLOSE_DRIFT": 1,
    }
    assert summary["warning_issue_counts"] == {
        "FINANCE_TERM_AMBIGUOUS_CLOSE": 1,
        "TERM_CONSISTENCY_FUND_CLOSE_DRIFT": 1,
    }
    assert summary["selected_issue_counts"] == {
        "FINANCE_TERM_AMBIGUOUS_CLOSE": 1,
        "TERM_CONSISTENCY_FUND_CLOSE_DRIFT": 1,
    }
    assert summary["selected_warning_issue_counts"] == {
        "FINANCE_TERM_AMBIGUOUS_CLOSE": 1,
        "TERM_CONSISTENCY_FUND_CLOSE_DRIFT": 1,
    }
    assert summary["blocking_issue_counts"] == {
        "FINANCE_EVENT_DIRECTION_REVERSAL": 1,
        "NUMBER_MAGNITUDE_MISMATCH": 1,
    }
    assert summary["provider_issue_counts"] == {
        "Aliyun": {
            "FINANCE_TERM_AMBIGUOUS_CLOSE": 1,
            "TERM_CONSISTENCY_FUND_CLOSE_DRIFT": 1,
        },
        "Gemini": {
            "FINANCE_EVENT_DIRECTION_REVERSAL": 1,
        },
        "fallback": {
            "NUMBER_MAGNITUDE_MISMATCH": 1,
        },
    }
    assert summary["warning_files"][0]["issue_codes"] == [
        "FINANCE_TERM_AMBIGUOUS_CLOSE",
        "TERM_CONSISTENCY_FUND_CLOSE_DRIFT",
    ]
    assert len(summary["blocked_files"]) == 2
