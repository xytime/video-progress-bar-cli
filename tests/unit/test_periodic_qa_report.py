"""三小时质检报告的格式和 DAL 回归测试。

# Modification History
| Version | Date       | Author | Description |
|---------|------------|--------|-------------|
| 1.0.0 | 2026-07-28 | Codex | 覆盖阻塞判定、平台待确认语义和只读快照 |
| 1.1.0 | 2026-07-28 | Codex | 覆盖三秒质检首屏结论和下载进度噪声清理 |
"""
import datetime as dt

from scripts import periodic_qa_report
from video_processing.db.database import PipelineDB


def test_format_report_keeps_platform_review_as_outstanding():
    snapshot = {
        "hours": 3,
        "status_counts": {"PUBLISHED": 1, "FAILED": 2},
        "eligible_queue": 4,
        "local_published": 1,
        "active_count": 0,
        "active": [],
        "stale_active": [],
        "recent_failures": [],
        "platform_states": [{"platform": "douyin", "state": "UNDER_REVIEW", "count": 1}],
    }
    monitor = {"state": "健康", "approved": 1, "polled": 1, "summary": {}, "backoffs": 0}

    report = periodic_qa_report.format_report(
        snapshot,
        monitor,
        "状态文件存在",
        dt.datetime(2026, 7, 28, 12, 0, tzinfo=periodic_qa_report.SHANGHAI),
    )

    assert report.startswith("<b>🟡 待核验：平台账本 1 项</b>")
    assert "<b>信号</b>：<code>队列 4 | 在途 0 | 新失败 0" in report
    assert "本地 PUBLISHED 1（近 3h；不等同平台侧可见确认）" in report
    assert "抖音 UNDER_REVIEW 1" in report
    assert "平台账本有待确认项；管线可继续，但勿重复提交" in report


def test_format_report_surfaces_recent_failure_without_curl_noise():
    snapshot = {
        "hours": 3,
        "status_counts": {"FAILED": 2},
        "eligible_queue": 4,
        "local_published": 0,
        "active_count": 0,
        "active": [],
        "stale_active": [],
        "recent_failures": [
            {
                "youtube_id": "timeout-id",
                "status": "FAILED",
                "error_msg": "% Total    % Received % Xferd\n0     0    0     0 --:--:--  0:00:01 --:--:--     0\nDownload timed out",
            }
        ],
        "platform_states": [],
    }
    monitor = {"state": "健康", "approved": 1, "polled": 1, "summary": {}, "backoffs": 0}

    report = periodic_qa_report.format_report(
        snapshot,
        monitor,
        "状态文件存在",
        dt.datetime(2026, 7, 28, 12, 0, tzinfo=periodic_qa_report.SHANGHAI),
    )

    assert report.startswith("<b>🟠 异常：近3h 有新失败</b>")
    assert "timeout-id: Download timed out" in report
    assert "--:--:--" not in report


def test_quality_report_snapshot_is_read_only_and_includes_active_rows(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    db.add_video("qa-active", "Active", "channel", score=86)
    db.add_video("qa-failed", "Failed", "channel", score=80)
    db.update_video_status("qa-active", "DOWNLOADING")
    db.update_video_status("qa-failed", "FAILED", error_msg="download unavailable")

    snapshot = db.get_quality_report_snapshot(hours=3, active_stale_minutes=90)

    assert snapshot["status_counts"]["DOWNLOADING"] == 1
    assert snapshot["eligible_queue"] == 0
    assert snapshot["active"][0]["youtube_id"] == "qa-active"
    assert snapshot["recent_failures"][0]["youtube_id"] == "qa-failed"
    assert db.get_video_by_youtube_id("qa-active")["status"] == "DOWNLOADING"
