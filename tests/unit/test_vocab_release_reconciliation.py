"""本次上线的单项对账边界，不接触生产库或执行任何投稿。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0 | 2026-10-17 | Codex | 原值漂移、审核证据、并发提交与触发器拒绝及事务回滚 |
"""
from contextlib import closing
import copy
import importlib.util
from pathlib import Path
import sqlite3
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2] / "docs/handoffs/2026-10-17-vocab-release"
spec = importlib.util.spec_from_file_location("reconcile_dal", ROOT / "reconcile_dal.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
sys.modules["reconcile_dal"] = module
control_spec = importlib.util.spec_from_file_location("vocab_reconcile_control", ROOT / "reconcile_submission.py")
control = importlib.util.module_from_spec(control_spec)
control_spec.loader.exec_module(control)


class FixtureDAL(module.PipelineDB):
    @staticmethod
    def seed(path, *, mutate=None, extra=None, trigger=False):
        video = dict(module.TARGET, publication_review_required=0, error_msg=None)
        pub = dict(module.PUBLICATION, video_path="test.mp4")
        if mutate:
            video.update(mutate)
        with closing(sqlite3.connect(path)) as conn, conn:
            for table, row in [("processed_videos", video), ("douyin_publications", pub)]:
                conn.execute(f'CREATE TABLE "{table}" ({",".join(row)})')
                conn.execute(f'INSERT INTO "{table}" VALUES ({",".join("?" for _ in row)})', list(row.values()))
            for table in module.LEDGERS:
                if table != "douyin_publications":
                    conn.execute(f'CREATE TABLE "{table}" (video_id, note)')
            conn.execute("INSERT INTO processed_videos (id,status) VALUES (9999,'PUBLISHED')")
            if extra:
                conn.execute(f'INSERT INTO "{extra}" (video_id) VALUES (?)', (module.TARGET["id"],))
            if trigger:
                conn.execute("""CREATE TRIGGER unwanted AFTER UPDATE ON processed_videos BEGIN
                    UPDATE processed_videos SET status='PENDING' WHERE id=9999; END""")

    @staticmethod
    def all_videos(path):
        with closing(sqlite3.connect(path)) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute("SELECT * FROM processed_videos ORDER BY id")]


def test_reconciles_only_one_row_and_preserves_published(tmp_path):
    path = tmp_path / "test.db"
    FixtureDAL.seed(path)
    before = module.PipelineDB.snapshot(path)
    videos = FixtureDAL.all_videos(path)
    result = module.PipelineDB.reconcile(path, before)
    after = module.PipelineDB.snapshot(path)
    assert result["updated_rows"] == 1 and result["uploaded"] is False
    assert after["video"]["status"] == "UNDER_REVIEW"
    assert after["publication"] == before["publication"]
    assert after["ledger_hashes"] == before["ledger_hashes"]
    assert after["video"]["retry_count"] == 0
    assert FixtureDAL.all_videos(path)[1] == videos[1]
    with pytest.raises(ValueError, match="DRIFT"):
        module.PipelineDB.reconcile(path, before)


@pytest.mark.parametrize("changes", [{"status": "PUBLISHED"}, {"process_pid": 42}, {"retry_count": 1},
                                    {"youtube_id": "other"}, {"updated_at": "changed"}])
def test_refuses_changed_target(tmp_path, changes):
    path = tmp_path / "test.db"
    FixtureDAL.seed(path, mutate=changes)
    before = module.PipelineDB.snapshot(path)
    with pytest.raises(ValueError, match="NOT_CONFIRMED"):
        module.PipelineDB.reconcile(path, before)
    assert module.PipelineDB.snapshot(path) == before


@pytest.mark.parametrize("state", ["PUBLISHED", "SUBMITTING", "UNCERTAIN", "FAILED"])
def test_refuses_wrong_submission_state(tmp_path, state):
    path = tmp_path / "test.db"
    FixtureDAL.seed(path)
    before = module.PipelineDB.snapshot(path)
    expected = copy.deepcopy(before)
    expected["publication"]["state"] = state
    with pytest.raises(ValueError, match="NOT_CONFIRMED"):
        module.PipelineDB.reconcile(path, expected)
    assert module.PipelineDB.snapshot(path) == before


@pytest.mark.parametrize("table", [t for t in module.LEDGERS if t != "douyin_publications"])
def test_refuses_other_platform_submission(tmp_path, table):
    path = tmp_path / "test.db"
    FixtureDAL.seed(path, extra=table)
    before = module.PipelineDB.snapshot(path)
    with pytest.raises(ValueError, match="OTHER_SUBMISSION"):
        module.PipelineDB.reconcile(path, before)
    assert module.PipelineDB.snapshot(path) == before


def test_refuses_stale_snapshot_without_writing(tmp_path):
    path = tmp_path / "test.db"
    FixtureDAL.seed(path)
    before = module.PipelineDB.snapshot(path)
    expected = copy.deepcopy(before)
    expected["video"]["error_msg"] = "changed"
    with pytest.raises(ValueError, match="DRIFT"):
        module.PipelineDB.reconcile(path, expected)
    assert module.PipelineDB.snapshot(path) == before


def test_trigger_cannot_change_other_video_and_rolls_back(tmp_path):
    path = tmp_path / "test.db"
    FixtureDAL.seed(path, trigger=True)
    before = module.PipelineDB.snapshot(path)
    videos = FixtureDAL.all_videos(path)
    with pytest.raises(sqlite3.DatabaseError):
        module.PipelineDB.reconcile(path, before)
    assert module.PipelineDB.snapshot(path) == before
    assert FixtureDAL.all_videos(path) == videos


@pytest.mark.parametrize("value,active,unknown", [
    ({"state": "RUNNING", "version": 65}, [], []),
    ({"state": "MAINTENANCE", "version": 66}, [], []),
    ({"state": "MAINTENANCE", "version": 65}, [{"pid": 1}], []),
    ({"state": "MAINTENANCE", "version": 65}, [], [{"code": "UNKNOWN"}]),
])
def test_maintenance_must_remain_exact_and_idle(value, active, unknown):
    with pytest.raises(Exception, match="DRIFT|NOT_IDLE"):
        control.require_control(value, active, unknown)


def test_maintenance_keeps_validated_frozen_version():
    control.require_control({"state": "MAINTENANCE", "version": 65}, [], [])
