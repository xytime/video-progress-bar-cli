# -*- coding: utf-8 -*-
"""Unit tests for daily_ops_report translation quality summary.

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-05 | Codex  | 初始创建：覆盖每日运维报告中的翻译质量摘要格式 |
| 1.1.0   | 2026-07-05 | Codex  | 覆盖翻译质量摘要展示非阻断告警数 |
| 1.2.0   | 2026-07-05 | Codex  | 覆盖翻译质量摘要分开展示最高频告警与阻断 |
| 1.3.0   | 2026-07-06 | Codex  | 覆盖翻译质量摘要展示 provider-issue 高频组合 |
| 1.4.0   | 2026-07-06 | Codex  | 覆盖翻译质量摘要展示 selected 候选统计 |
| 1.5.0   | 2026-07-17 | Codex  | 覆盖每日 API 尝试次数与 DeepSeek 余额格式化 |
"""

import sys
from pathlib import Path

_root = Path(__file__).parent.parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from scripts.daily_ops_report import (  # noqa: E402
    format_ai_provider_usage,
    format_deepseek_balance,
    format_translation_quality,
)


def test_format_translation_quality_without_reports():
    assert format_translation_quality({"files_scanned": 0}) == "翻译质量: 暂无审计报告"


def test_format_translation_quality_with_counts():
    line = format_translation_quality(
        {
            "files_scanned": 3,
            "event_count": 5,
            "selected_count": 2,
            "selected_warning_count": 1,
            "warning_count": 1,
            "blocked_count": 2,
            "issue_counts": {
                "FINANCE_EVENT_DIRECTION_REVERSAL": 2,
                "NUMBER_MAGNITUDE_MISMATCH": 1,
            },
            "warning_issue_counts": {
                "AMOUNT_CONSISTENCY_UNIT_DRIFT": 1,
            },
            "blocking_issue_counts": {
                "FINANCE_EVENT_DIRECTION_REVERSAL": 2,
            },
            "provider_counts": {
                "Gemini": 3,
                "DeepSeek": 2,
            },
            "selected_provider_counts": {
                "DeepSeek": 2,
            },
            "selected_warning_issue_counts": {
                "AMOUNT_CONSISTENCY_UNIT_DRIFT": 1,
            },
            "provider_issue_counts": {
                "Gemini": {
                    "FINANCE_EVENT_DIRECTION_REVERSAL": 2,
                },
                "DeepSeek": {
                    "AMOUNT_CONSISTENCY_UNIT_DRIFT": 1,
                },
            },
        }
    )

    assert "报告 3" in line
    assert "事件 5" in line
    assert "采用 2" in line
    assert "采用告警 1" in line
    assert "告警 1" in line
    assert "阻断/降级 2" in line
    assert "AMOUNT_CONSISTENCY_UNIT_DRIFT×1" in line
    assert "FINANCE_EVENT_DIRECTION_REVERSAL×2" in line
    assert "Gemini×3" in line
    assert "采用provider DeepSeek×2" in line
    assert "采用告警项 AMOUNT_CONSISTENCY_UNIT_DRIFT×1" in line
    assert "provider问题 Gemini:FINANCE_EVENT_DIRECTION_REVERSAL×2" in line


def test_format_ai_provider_usage_marks_it_as_local_audit():
    line = format_ai_provider_usage(
        {
            "providers": [
                {"provider": "deepseek", "attempts": 3, "successes": 2, "failures": 1},
                {"provider": "gemini", "attempts": 2, "successes": 2, "failures": 0},
            ]
        }
    )

    assert "DeepSeek 尝试3/成功2/失败1" in line
    assert "Gemini 尝试2/成功2/失败0" in line
    assert "不等同 token/账单" in line


def test_format_deepseek_balance_omits_sensitive_response_details():
    line = format_deepseek_balance(
        {
            "is_available": True,
            "balance_infos": [
                {
                    "currency": "CNY",
                    "total_balance": "12.34",
                    "granted_balance": "2.34",
                    "topped_up_balance": "10.00",
                }
            ],
        }
    )

    assert line == "DeepSeek 余额: 🟢 CNY 总12.34（赠金2.34/充值10.00）"
