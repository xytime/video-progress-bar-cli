"""视频号来源归因与北京日期漏斗测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-24 | Codex | 验证自动、人工参与与旧记录未知三类不互相冒充。 |
"""

from datetime import datetime
import sqlite3
from zoneinfo import ZoneInfo

from video_processing.db.database import PipelineDB


def test_daily_publication_funnel_preserves_unknown_and_manual_assistance(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    for yid in ("auto-item", "manual-touched", "legacy-item", "ready-only", "manual-scored", "prep-only"):
        assert db.add_video(yid, yid, "channel", score=80, source="AUTO")
    assert db.add_video("manual-source", "manual-source", "channel", score=80, source="MANUAL")
    db.set_manually_scored("manual-scored")
    db.record_processing_trigger("auto-item", "cron")
    db.record_processing_trigger("auto-item", "ready_worker")
    db.record_processing_trigger("manual-touched", "cron")
    db.record_processing_trigger("manual-touched", "dashboard_manual_item")
    db.record_processing_trigger("ready-only", "ready_worker")
    db.record_processing_trigger("manual-source", "cron")
    db.record_processing_trigger("manual-scored", "cron")
    db.record_processing_trigger("prep-only", "background_preparation")
    submitters = {
        "auto-item": "cron", "manual-touched": "dashboard_manual_item",
        "ready-only": "ready_worker", "manual-source": "cron", "manual-scored": "cron",
    }
    for yid in ("auto-item", "manual-touched", "legacy-item", "ready-only", "manual-source", "manual-scored", "prep-only"):
        db.record_wechat_submission_acceptance(
            yid, evidence_path=f"evidence/{yid}", error_message=None,
            final_title=yid, platform_post_id=f"export/{yid}",
            trigger_source=submitters.get(yid),
        )

    today_bj = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    metrics = db.get_daily_publication_funnel(today_bj)

    assert metrics["auto_intake"] == 6
    assert metrics["eligible_intake_current_score"] == 5
    assert metrics["bound_acceptances"] == 7
    assert metrics["proven_auto"] == 2
    assert metrics["manual_assisted"] == 3
    assert metrics["unknown"] == 2


def test_publication_trigger_requires_known_video_and_source(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    try:
        db.record_processing_trigger("missing", "cron")
    except ValueError:
        pass
    else:
        raise AssertionError("missing video must not be silently attributed")

    assert db.add_video("present", "title", "channel")
    try:
        db.record_processing_trigger("present", "untrusted-label")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown source must not be counted")


def test_existing_submission_attempt_table_gets_source_column(tmp_path):
    path = tmp_path / "pipeline.db"
    PipelineDB(str(path))
    with sqlite3.connect(path) as conn:
        conn.execute("ALTER TABLE wechat_submission_attempts DROP COLUMN trigger_source")

    PipelineDB(str(path))
    with sqlite3.connect(path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(wechat_submission_attempts)")}
    assert "trigger_source" in columns
