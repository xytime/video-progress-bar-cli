"""改进分析的事件口径、人工审核与失败原子性测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-01 | Codex | 覆盖旧入库新失败、切片去重、审批失效、保留旧报告和不误关事项。 |
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from video_processing.db.database import PipelineDB
from video_processing.improvement.analysis import BJ, build_analysis, clean
from video_processing.improvement.store import ReviewStore, digest, render
from video_processing.improvement import service

NOW = datetime(2026, 11, 2, 9, tzinfo=BJ)


def row(video_id=1, family=1, category="EXECUTION_FAILURE", code="BURNED_CAPTION_REPAIR_UNCERTAIN", **kw):
    return dict(video_id=video_id, family_root_id=family, youtube_id=f"video_{video_id}", slice_index=kw.pop("slice_index", 0),
                category=category, cause_code=code, cause_title="原字幕定位不确定", status="FAILED",
                unresolved=True, sanitized_error_excerpt="ValueError: 原字幕定位不确定", **kw)


def event(event_id=1, video_id=1, family=1, failed_at="2026-11-01 02:00:00", **kw):
    return dict(event_id=event_id, video_id=video_id, family_root_id=family, youtube_id=f"video_{video_id}",
                slice_index=0, status="FAILED", reason="burned_caption_repair", failed_at=failed_at, orphaned=False, **kw)


def analysis(rows=None, events=None, now=NOW):
    return build_analysis(dict(tasks=rows if rows is not None else [row()], summary={}, as_of_bj=now.isoformat()),
                          events if events is not None else [event()], now)


def populated(tmp_path):
    store = ReviewStore(tmp_path / "review")
    report = store.merge(analysis(), "source-sha")
    record = store.read()
    key = next(iter(record["issues"]))
    return store, key, report


def proof(tmp_path, sha=None, state=None, **kw):
    p = tmp_path / "proof.json"
    p.write_text(json.dumps(dict(plan_sha=sha, state=state, passed=True, **kw)))
    return p


def test_event_window_counts_previous_day_and_family_vs_attempts():
    a = analysis([row(1, 1), row(2, 1, slice_index=1)], [event(1), event(2, 2), event(3, failed_at="2026-11-02 01:00:00")])
    assert a["backlog_families"] == 1
    assert a["yesterday_event_count"] == 2
    assert a["yesterday_families"] == 1
    assert a["weekly"] is True
    assert a["issues"][0]["slices"] == [2]
    assert a["effectiveness"]["state"] == "UNAVAILABLE"


def test_uncertain_policy_and_observation_are_not_technical_failures():
    a = analysis([row(1, 1), row(2, 2, "DELIVERY_UNVERIFIED", "WECHAT_DELIVERY_UNVERIFIED"),
                  row(3, 3, "QUALITY_POLICY_BLOCK", "CONTENT_CENSOR_BLOCK"),
                  row(4, 4, "OBSERVATION_ANOMALY", "UNKNOWN")], [])
    assert a["primary_buckets"] == dict(technical=1, uncertain=1, policy=1, observation=1)


def test_family_with_uncertain_and_failure_counts_once():
    a = analysis([row(), row(2, 1, "DELIVERY_UNVERIFIED", "WECHAT_DELIVERY_UNVERIFIED")], [])
    assert a["primary_buckets"] == {"uncertain": 1}
    assert sum(a["primary_buckets"].values()) == 1


def test_recovery_evidence_unknown_and_cooldown_are_not_code_faults():
    a = analysis([row(code="RECOVERY_EVIDENCE_UNVERIFIED"), row(2, 2, "DEPENDENCY_BLOCK", "DEPENDENCY_COOLDOWN_BACKOFF"),
                  row(3, 3, "FUTURE_UNKNOWN_CATEGORY", "UNCLASSIFIED")], [])
    assert a["primary_buckets"] == {"observation": 2, "blocked": 1}
    store_record = {"analysis": a, "issues": {}}
    assert "技术执行故障/识别受阻 | 0" in render(store_record)


def test_generic_youtube_errors_group_across_video_ids_and_redact_detail():
    one, two = row(code="STAGE_EXECUTION_FAILED"), row(2, 2, code="STAGE_EXECUTION_FAILED")
    one["sanitized_error_excerpt"] = "ERROR: [youtube] abc123_XYZa: Sign in https://example.test?token=private123"
    two["sanitized_error_excerpt"] = "ERROR: [youtube] def456_UVWb: Sign in https://example.test?token=private456"
    a = analysis([one, two], [])
    assert len(a["issues"]) == 1
    assert a["issues"][0]["affected_families"] == 2
    assert "private" not in a["issues"][0]["detail"]


def test_native_specific_error_preserves_original_classification():
    a = analysis([row(code="NATIVE_CAPTION_INCOMPLETE", sanitized_override=True)], [])
    source = row(code="NATIVE_CAPTION_INCOMPLETE")
    source["sanitized_error_excerpt"] = "NativeCaptionReview: OCR_BUDGET_EXCEEDED"
    b = analysis([source], [])
    assert a["issues"][0]["id"] != b["issues"][0]["id"]
    assert b["issues"][0]["cause_code"] == "NATIVE_CAPTION_INCOMPLETE"
    assert b["issues"][0]["detail"] == "OCR_BUDGET_EXCEEDED"


@pytest.mark.parametrize("s", ["Authorization: Bearer private123", "api_key='private123'", '"token": "private123"',
                              "https://example.test?token=private123", "cookie=private123"])
def test_no_secret_in_saved_excerpts(s):
    assert "private123" not in clean(s)


def test_daily_runs_update_same_issue_preserve_approval(tmp_path):
    store, key, _ = populated(tmp_path)
    sha = store.read()["issues"][key]["plan_sha"]
    store.review(key, "APPROVED", sha, "user", proof(tmp_path))
    store.merge(analysis(now=NOW + timedelta(days=1)), "new-source")
    record = store.read()
    assert len(record["issues"]) == 1
    assert record["issues"][key]["state"] == "APPROVED"
    assert record["issues"][key]["seen_event_ids"] == [1]


def test_plan_change_invalidates_previous_approval(tmp_path):
    store, key, _ = populated(tmp_path)
    item = store.read()["issues"][key]
    sha = item["plan_sha"]
    store.review(key, "APPROVED", sha, "user", proof(tmp_path))
    plan = deepcopy(item["plan"])
    plan["change"] = "具体的新调查范围"
    store.set_plan(key, plan)
    changed = store.read()["issues"][key]
    assert changed["plan_version"] == 2
    assert changed["state"] == "PENDING_REVIEW"
    assert "approval" not in changed
    with pytest.raises(ValueError):
        store.review(key, "APPROVED", sha, "user", proof(tmp_path))


def test_report_text_is_not_an_approval_and_stages_cannot_be_skipped(tmp_path):
    store, key, _ = populated(tmp_path)
    sha = store.read()["issues"][key]["plan_sha"]
    with pytest.raises(ValueError):
        store.advance(key, "LOCAL_VERIFIED", sha, proof(tmp_path, sha, "LOCAL_VERIFIED"))
    store.review(key, "APPROVED", sha, "user", proof(tmp_path))
    with pytest.raises(ValueError):
        store.advance(key, "IMPLEMENTING", sha, proof(tmp_path, sha, "IMPLEMENTING"))
    store.advance(key, "INVESTIGATING", sha, proof(tmp_path, sha, "INVESTIGATING"))
    store.advance(key, "ANALYZED", sha, proof(tmp_path, sha, "ANALYZED"))
    assert store.read()["issues"][key]["state"] == "ANALYZED"


def test_fix_requires_all_stages_observation_time_and_real_samples(tmp_path):
    store, key, _ = populated(tmp_path)
    plan = store.read()["issues"][key]["plan"]
    plan["kind"] = "FIX"
    store.set_plan(key, plan)
    sha = store.read()["issues"][key]["plan_sha"]
    store.review(key, "APPROVED", sha, "user", proof(tmp_path))
    for state in ["IMPLEMENTING", "LOCAL_VERIFIED", "RUNTIME_ADOPTED", "OBSERVING"]:
        store.advance(key, state, sha, proof(tmp_path, sha, state))
    with pytest.raises(ValueError):
        store.advance(key, "CLOSED", sha, proof(tmp_path, sha, "CLOSED", sample_count=2))
    record = store.read()
    record["issues"][key]["observing_since"] = (datetime.now(timezone.utc)-timedelta(days=8)).isoformat()
    store.commit(record)
    with pytest.raises(ValueError):
        store.advance(key, "CLOSED", sha, proof(tmp_path, sha, "CLOSED", sample_count=0))
    store.advance(key, "CLOSED", sha, proof(tmp_path, sha, "CLOSED", sample_count=2))
    store.merge(analysis(events=[event(1), event(2)]), "source-sha")
    item = store.read()["issues"][key]
    assert item["state"] == "REOPENED"
    assert item["recurrences"] == 1


def test_absence_does_not_auto_close_open_issue(tmp_path):
    store, key, _ = populated(tmp_path)
    store.merge(analysis([], []), "source-sha")
    item = store.read()["issues"][key]
    assert item["present"] is False
    assert item["state"] == "PENDING_REVIEW"


def test_failed_publish_keeps_old_report_and_ledger_together(tmp_path, monkeypatch):
    store, _, original = populated(tmp_path)
    before = store.read()
    import video_processing.improvement.store as module
    real = module.atomic_json
    def fail_pointer(path, data):
        if path.name == "current.json":
            raise OSError("synthetic interruption")
        return real(path, data)
    monkeypatch.setattr(module, "atomic_json", fail_pointer)
    with pytest.raises(OSError):
        store.merge(analysis([], []), "new-sha")
    assert store.read() == before
    assert original.is_file()


def test_overlapping_writer_is_rejected(tmp_path):
    a = ReviewStore(tmp_path / "review")
    b = ReviewStore(tmp_path / "review")
    with a.locked():
        with pytest.raises(BlockingIOError):
            with b.locked():
                pass


def test_report_failure_is_not_empty_and_next_same_day_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "collect_analysis", lambda *args: analysis())
    done = service.run_report(tmp_path / "unused", tmp_path, now=NOW)
    assert done["state"] == "COMPLETE"
    assert service.run_report(tmp_path / "unused", tmp_path, now=NOW)["state"] == "ALREADY_RECORDED"
    def fail(*args):
        raise RuntimeError("database unavailable")
    monkeypatch.setattr(service, "collect_analysis", fail)
    with pytest.raises(RuntimeError):
        service.run_report(tmp_path / "unused", tmp_path, now=NOW+timedelta(days=1))
    receipt = json.loads((tmp_path / "improvement/last_attempt.json").read_text())
    assert receipt["state"] == "UNAVAILABLE"
    assert receipt["last_valid_at"] == NOW.isoformat()
    assert ReviewStore(tmp_path / "improvement").read()["analysis"]["backlog_families"] == 1


def test_dal_old_created_video_new_failure_and_orphan_are_in_window(tmp_path):
    db = PipelineDB(str(tmp_path / "test.db"))
    with db.get_connection() as c:
        c.execute("INSERT INTO processed_videos(id,youtube_id,title,channel_id,status,created_at) VALUES(1,'old_video','old video','test_channel','PENDING','2025-01-01')")
        c.executemany("INSERT INTO publishing_failure_events(id,video_id,status,reason,failed_at) VALUES(?,?,'FAILED','error',?)",
                      [(1,1,'2026-11-01 15:59:59'), (2,1,'2026-11-01 16:00:00'), (3,99,'2026-11-01 01:00:00')])
    rows = db.get_improvement_failure_events("2026-10-31T16:00:00+00:00", "2026-11-01T16:00:00+00:00")
    assert [r["event_id"] for r in rows] == [3,1]
    assert rows[0]["orphaned"] == 1
    assert rows[1]["created_at"] == "2025-01-01"


def test_dal_missing_ledger_fails_instead_of_zero(tmp_path):
    db = PipelineDB(str(tmp_path / "test.db"))
    with db.get_connection() as c:
        c.execute("DROP TABLE publishing_failure_events")
    with pytest.raises(Exception):
        db.get_improvement_failure_events("2026-10-31", "2026-11-02")


def test_collector_reads_actual_snapshot_and_never_initializes_live_database(tmp_path, monkeypatch):
    source = tmp_path / "source.db"
    db = PipelineDB(str(source))
    before = source.read_bytes()
    calls = []
    def diagnose(read_db, output, window):
        assert read_db._read_only is True
        assert Path(read_db.db_path) != source
        calls.append(read_db.db_path)
        with pytest.raises(Exception):
            with read_db.get_connection() as c:
                c.execute("DELETE FROM processed_videos")
        return dict(tasks=[], summary={}, as_of_bj=NOW.isoformat())
    monkeypatch.setattr(service, "get_funnel_diagnosis_payload", diagnose)
    result = service.collect_analysis(source, tmp_path, NOW)
    assert result["yesterday_event_count"] == 0
    assert source.read_bytes() == before
    assert len(calls) == 1
    assert not list(tmp_path.glob(".improvement-snapshot-*"))


def test_tampered_ledger_cannot_be_read(tmp_path):
    store, _, report = populated(tmp_path)
    path = report.parent / "record.json"
    data = json.loads(path.read_text())
    data["issues"] = {}
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        store.read()


def test_daily_improvement_only_never_calls_balance_or_telegram(tmp_path, monkeypatch, capsys):
    import scripts.daily_ops_report as daily
    monkeypatch.setattr(service, "run_report", lambda *args: {"state": "COMPLETE"})
    def forbidden():
        pytest.fail("分析路径不得执行旧日报采集或外部请求")
    monkeypatch.setattr(daily, "collect", forbidden)
    monkeypatch.setattr("sys.argv", ["daily_ops_report.py", "--improvement-only"])
    assert daily.main() == 0
    assert "COMPLETE" in capsys.readouterr().out
