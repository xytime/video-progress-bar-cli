"""合规二创生命周期：真实临时 DAL、竞争、只读及进程树回归。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-25 | GPT-6.1 Sol | 审批事务与无副作用执行证据 |
"""
import asyncio
import copy
import hashlib
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from video_processing.db.database import PipelineDB
from video_processing.compliance_remix.remix_service import ComplianceRemixService, _extract_video_id, run_bounded_async
from tests.unit.test_compliance_remix_contracts import VALID_MANIFEST

SOURCE_ID = "p8smG9rkQVY"
VTT = "WEBVTT\n\n00:00:00.000 --> 00:00:03.000\nSynthetic source evidence.\n"


class Generator:
    def generate_proposal(self, **kwargs):
        return copy.deepcopy(VALID_MANIFEST), SimpleNamespace(passed=True), "fixture"

    def render_comparison_markdown(self, *args):
        return "| 来源 | 解说 |\n| Synthetic source evidence. | 市场 |"


def source_fetcher(url, work_dir):
    work_dir.mkdir(parents=True)
    (work_dir / "source.vtt").write_text(VTT)
    return SOURCE_ID, "Synthetic source", work_dir / f"{SOURCE_ID}.mp4", VTT


@pytest.fixture
def proposal(tmp_path):
    db = PipelineDB(str(tmp_path / "db.sqlite"))
    service = ComplianceRemixService(db, generator=Generator(), source_fetcher=source_fetcher)
    result = service.propose_remix(SOURCE_ID, tmp_path / "custom", actor="123", chat="456")
    return db, service, result


def approve(service, result, **changes):
    args = dict(actor="123", chat="456", content_hash=result["content_hash"], source_reviewed=True)
    args.update(changes)
    service.approve_remix(result["video_id"], **args)


def test_proposal_independent_and_not_ordinary_queue(tmp_path):
    db = PipelineDB(str(tmp_path / "db.sqlite"))
    db.add_video(SOURCE_ID, "原片", "original", score=80)
    original = db.get_video_by_youtube_id(SOURCE_ID)
    service = ComplianceRemixService(db, generator=Generator(), source_fetcher=source_fetcher)
    first = service.propose_remix(SOURCE_ID, tmp_path / "one")
    second = service.propose_remix(SOURCE_ID, tmp_path / "two")
    assert first["video_id"] != second["video_id"] != SOURCE_ID
    assert db.get_video_by_youtube_id(SOURCE_ID) == original
    assert db.get_video_by_youtube_id(first["video_id"])["status"] == "PENDING_REVIEW"
    assert all(row["source"] != "COMPLIANCE_REMIX" for row in db.get_high_score_pending_videos())
    assert not list((tmp_path / "one").rglob("*.mp4"))


@pytest.mark.parametrize("change", [{"actor": "other"}, {"chat": "other"}, {"content_hash": "0" * 64}, {"purpose": "publish"}])
def test_approval_context_bound(proposal, change):
    db, service, result = proposal
    with pytest.raises(ValueError):
        approve(service, result, **change)
    assert db.get_compliance_remix(result["video_id"])["state"] == "PENDING_REVIEW"


def test_revoke_and_replay(proposal):
    db, service, result = proposal
    db.revoke_compliance_remix(result["video_id"], actor="123", chat="456")
    with pytest.raises(ValueError): approve(service, result)
    assert db.get_compliance_remix(result["video_id"])["state"] == "REVOKED"


def test_approval_expired(proposal, monkeypatch):
    db, service, result = proposal
    monkeypatch.setattr("video_processing.db.compliance_remix.time.time", lambda: result["expires_at"] + 1)
    with pytest.raises(ValueError): approve(service, result)


def test_manifest_changed_rejected(proposal):
    db, service, result = proposal
    path = Path(result["manifest_path"])
    manifest = json.loads(path.read_text()); manifest["title"] = "changed"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError): approve(service, result)
    assert db.get_compliance_remix(result["video_id"])["state"] == "PENDING_REVIEW"


def test_concurrent_claim_once(proposal):
    db, service, result = proposal
    approve(service, result)
    def claim():
        try:
            db.claim_compliance_remix(result["video_id"], actor="123", chat="456", content_hash=result["content_hash"])
            return True
        except ValueError:
            return False
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(lambda _: claim(), range(8))) == 1
    with pytest.raises(ValueError): approve(service, result)


def test_unapproved_execution_has_no_media_side_effects(proposal):
    db, service, result = proposal
    with pytest.raises(ValueError):
        asyncio.run(service.execute_approved_remix(result["video_id"], actor="123", chat="456", content_hash=result["content_hash"]))
    assert not list(Path(result["manifest_path"]).parent.glob("*.mp4"))
    assert db.get_compliance_remix(result["video_id"])["state"] == "PENDING_REVIEW"


def test_dryrun_zero_writes_and_custom_directory(proposal):
    db, service, result = proposal
    folder = Path(result["manifest_path"]).parent
    before_files = {p: (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest()) for p in folder.rglob("*") if p.is_file()}
    before = db.get_compliance_remix(result["video_id"])
    receipt = asyncio.run(service.execute_approved_remix(result["video_id"], dry_run=True))
    assert receipt["status"] == "VALIDATED"
    assert before == db.get_compliance_remix(result["video_id"])
    assert before_files == {p: (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest()) for p in folder.rglob("*") if p.is_file()}


@pytest.mark.parametrize("source", ["../bad", "https://youtube.com.evil/watch?v=p8smG9rkQVY", "http://youtube.com/watch?v=p8smG9rkQVY", "https://user@youtube.com/watch?v=p8smG9rkQVY", "file:///etc/passwd"])
def test_source_and_identifier_reject_traversal(source):
    with pytest.raises(ValueError): _extract_video_id(source)


def test_missing_source_evidence_blocked_before_generation(tmp_path):
    db = PipelineDB(str(tmp_path / "db.sqlite"))
    service = ComplianceRemixService(db, generator=Generator(), source_fetcher=lambda *_: (SOURCE_ID, "title", tmp_path / "x.mp4", "No subtitle"))
    with pytest.raises(ValueError): service.propose_remix(SOURCE_ID, tmp_path / "work")
    assert not db.get_videos_by_status("PENDING_REVIEW")


def test_timeout_reaps_child_process_group(tmp_path):
    marker = tmp_path / "heartbeat"
    child_code = "from pathlib import Path; import time; p=Path(" + repr(str(marker)) + ");\nwhile True: p.write_text(str(time.time())); time.sleep(.02)"
    parent_code = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c'," + repr(child_code) + "]); time.sleep(30)"
    async def run():
        with pytest.raises(asyncio.TimeoutError):
            await run_bounded_async([sys.executable, "-c", parent_code], timeout=.4)
    asyncio.run(run())
    assert marker.is_file()
    before = marker.read_text(); time.sleep(.15)
    assert marker.read_text() == before


def test_review_list_and_count_include_local_proposal(proposal):
    db, service, result = proposal
    rows, total = db.get_paginated_videos(tab="review")
    assert total == 1
    assert rows[0]["youtube_id"] == result["video_id"]
    assert rows[0]["status"] == "PENDING_REVIEW"
    assert db.get_tab_counts()["review"] == 1
    assert db.get_filtered_tab_counts("review")["review"] == 1
    assert db.get_tab_counts()["local_accepted"] == 0


def test_approval_requires_human_source_attestation(proposal):
    db, service, result = proposal
    with pytest.raises(ValueError): approve(service, result, source_reviewed=False)
    assert db.get_compliance_remix(result["video_id"])["human_reviewed_at"] is None
    approve(service, result)
    record = db.get_compliance_remix(result["video_id"])
    assert record["human_reviewed_at"] is not None
    assert record["human_reviewed_hash"] == result["content_hash"]


def test_source_gist_must_match_corresponding_cue():
    from video_processing.compliance_remix.remix_service import validate_source_comparison
    manifest = copy.deepcopy(VALID_MANIFEST)
    transcript = VTT + "\n00:00:03.000 --> 00:00:06.000\nDifferent second evidence.\n"
    manifest["comparison_table"][0]["timestamp_range"] = "00:03 - 00:06"
    with pytest.raises(ValueError): validate_source_comparison(manifest, transcript)


@pytest.mark.parametrize("transcript", [
    "WEBVTT\n\nNOTE\n00:00:00.000 --> 00:00:03.000\nSynthetic source evidence.\n",
    "WEBVTT\n\n00:00:00.000 --> 00:00:03.000\n<lang en></lang>\n",
    "WEBVTT\n\n00:00:03.000 --> 00:00:00.000\nSynthetic evidence.\n",
    VTT + "x" * 12000,
])
def test_vtt_note_empty_or_malformed_not_evidence(transcript):
    from video_processing.compliance_remix.remix_service import parse_timestamped_vtt
    with pytest.raises(ValueError): parse_timestamped_vtt(transcript)


def test_production_once_and_guard_bound_to_snapshot(proposal, monkeypatch):
    db, service, result = proposal
    class Pipeline:
        def __init__(self, *, work_dir):
            self.work_dir = work_dir
        async def execute_full_pipeline(self, *, manifest, source_video, **kwargs):
            assert self.execution_guard(manifest, self.work_dir) is True
            changed = dict(manifest, title="伪造")
            with pytest.raises(PermissionError): self.execution_guard(changed, self.work_dir)
            return {"status": "PRODUCED", "upload_status": "NOT_SUBMITTED"}
    async def download(cmd, **kwargs):
        Path(cmd[cmd.index("-o") + 1]).write_bytes(b"fixture source media")
        return 0, "", ""
    service.pipeline_factory = Pipeline
    monkeypatch.setattr("video_processing.compliance_remix.remix_service.run_bounded_async", download)
    approve(service, result)
    receipt = asyncio.run(service.execute_approved_remix(result["video_id"], actor="123", chat="456", content_hash=result["content_hash"]))
    assert receipt["status"] == "PRODUCED"
    assert db.get_compliance_remix(result["video_id"])["state"] == "COMPLETED"
    with pytest.raises(ValueError):
        asyncio.run(service.execute_approved_remix(result["video_id"], actor="123", chat="456", content_hash=result["content_hash"]))


def test_publish_blocked_and_no_status_upgrade(proposal):
    db, service, result = proposal
    approve(service, result)
    with pytest.raises(PermissionError):
        asyncio.run(service.execute_approved_remix(result["video_id"], upload_now=True, actor="123", chat="456", content_hash=result["content_hash"]))
    assert db.get_compliance_remix(result["video_id"])["state"] == "APPROVED"
    with pytest.raises(ValueError): db.finish_compliance_remix(result["video_id"], state="PUBLISHED")


def test_source_symlink_rejected_before_download(proposal, tmp_path):
    db, service, result = proposal
    work_dir = Path(result["manifest_path"]).parent
    (work_dir / "linked.mp4").symlink_to(tmp_path / "outside.mp4")
    with pytest.raises(ValueError): service.load_proposal(result["video_id"])


def test_fetch_phase_never_downloads_source_media(tmp_path, monkeypatch):
    from video_processing.compliance_remix.remix_service import fetch_source_metadata_and_subtitles
    calls = []
    def run(cmd, **kwargs):
        calls.append(cmd)
        if "--dump-single-json" in cmd:
            return subprocess.CompletedProcess(cmd, 0, json.dumps(dict(id=SOURCE_ID, title="source", duration=3)), "")
        (tmp_path / f"{SOURCE_ID}_sub.en.vtt").write_text(VTT)
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr("video_processing.compliance_remix.remix_service._run_bounded", run)
    _, _, source_video, transcript = fetch_source_metadata_and_subtitles(SOURCE_ID, tmp_path)
    assert transcript == VTT
    assert len(calls) == 2
    assert all("--skip-download" in cmd for cmd in calls)
    assert not source_video.exists()


def test_cli_legacy_dryrun_is_readonly_and_censors(tmp_path):
    script = Path(__file__).resolve().parents[2] / "scripts/compliance_remix.py"
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(VALID_MANIFEST))
    work_dir = tmp_path / "never-created"
    before = manifest_path.read_bytes()
    command = [sys.executable, str(script), "--manifest", str(manifest_path), "--work-dir", str(work_dir)]
    denied = subprocess.run(command, capture_output=True, text=True, timeout=20)
    assert denied.returncode != 0 and "dry-run" in denied.stderr
    good = subprocess.run(command + ["--dry-run"], capture_output=True, text=True, timeout=20)
    assert good.returncode == 0 and json.loads(good.stdout)["status"] == "VALIDATED"
    assert not work_dir.exists() and manifest_path.read_bytes() == before
    unsafe = copy.deepcopy(VALID_MANIFEST); unsafe["cover_subtitle"] = "港!独"
    manifest_path.write_text(json.dumps(unsafe))
    bad = subprocess.run(command + ["--dry-run"], capture_output=True, text=True, timeout=20)
    assert bad.returncode != 0
    assert not work_dir.exists()


def test_cli_execute_requires_hash_and_human_review_before_db_creation(tmp_path):
    script = Path(__file__).resolve().parents[2] / "scripts/compliance_remix.py"
    denied = subprocess.run([sys.executable, str(script), "--execute", "--video-id", "remix_" + "a" * 32], capture_output=True, text=True, timeout=20)
    assert denied.returncode != 0 and "content-hash" in denied.stderr
    denied = subprocess.run([sys.executable, str(script), "--execute", "--video-id", "remix_" + "a" * 32,
                             "--content-hash", "b" * 64], capture_output=True, text=True, timeout=20)
    assert denied.returncode != 0 and "source-reviewed" in denied.stderr


def test_cancel_reaps_subprocess_group(tmp_path):
    marker = tmp_path / "heartbeat"
    child_code = "from pathlib import Path; import time; p=Path(" + repr(str(marker)) + ");\nwhile True: p.write_text(str(time.time())); time.sleep(.02)"
    parent_code = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c'," + repr(child_code) + "]); time.sleep(30)"
    async def run():
        task = asyncio.create_task(run_bounded_async([sys.executable, "-c", parent_code], timeout=30))
        await asyncio.sleep(.4)
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
    asyncio.run(run())
    assert marker.is_file()
    before = marker.read_text(); time.sleep(.15)
    assert marker.read_text() == before


def test_tampered_human_review_document_rejected(proposal):
    db, service, result = proposal
    Path(result["comparison_md_path"]).write_text("伪造对照表")
    with pytest.raises(ValueError): approve(service, result)
    assert db.get_compliance_remix(result["video_id"])["state"] == "PENDING_REVIEW"


def test_ordinary_operations_cannot_enter_remix_execution(proposal):
    import sqlite3
    db, service, result = proposal
    key = result["video_id"]
    assert db.promote_to_manual(key) is False
    assert db.promote_waitlist_to_queue(key) is False
    assert db.claim_video_for_processing(key) is False
    assert db.claim_video_for_publication(key, 123) is False
    db.update_video_status(key, "PENDING")
    db.mark_video_ready_for_publication(key)
    assert db.get_video_by_youtube_id(key)["status"] == "PENDING_REVIEW"
    # generic ignore/republish SQL cannot overwrite the lifecycle authority.
    with pytest.raises(sqlite3.IntegrityError): db.ignore_video(key)
    assert db.get_video_by_youtube_id(key)["source"] == "COMPLIANCE_REMIX"
    assert db.get_compliance_remix(key)["state"] == "PENDING_REVIEW"


def test_ordinary_recovery_handles_mixed_tasks_without_reclaiming_remix(proposal):
    db, service, result = proposal
    key = result["video_id"]
    approve(service, result)
    db.claim_compliance_remix(key, actor="123", chat="456", content_hash=result["content_hash"])
    for ordinary in ("ordinary-purge", "ordinary-orphan", "ordinary-failed"):
        db.add_video(ordinary, "普通任务", "channel", score=80)
    db.update_video_status("ordinary-purge", "PROCESSING")
    db.update_video_status("ordinary-orphan", "PROCESSING")
    db.update_video_status("ordinary-failed", "FAILED")
    # Fixture clock aging only; lifecycle state is always changed through its DAL.
    with db.get_connection() as conn:
        conn.execute("UPDATE processed_videos SET updated_at = datetime('now', '-3 hours') WHERE status = 'PROCESSING'")
        conn.commit()
    claimed = db.get_compliance_remix(key)
    assert {row["youtube_id"] for row in db.get_stale_pre_submission_processing_videos()} == {"ordinary-purge", "ordinary-orphan"}
    assert db.recover_orphaned_pre_submission_task(key, expected_process_pid=None, error_msg="orphan") is None
    assert db.recover_orphaned_pre_submission_task("ordinary-orphan", expected_process_pid=None, error_msg="orphan") == "PENDING"
    assert db.purge_stale_tasks() == 1
    assert db.get_video_by_youtube_id("ordinary-purge")["status"] == "PENDING"
    assert db.get_video_by_youtube_id(key)["status"] == "PROCESSING"
    assert db.get_compliance_remix(key) == claimed
    db.finish_compliance_remix(key, state="FAILED", error="synthetic failure")
    assert {row["youtube_id"] for row in db.get_failed_videos_since(24)} == {"ordinary-failed"}
