"""英语世界工作台并发和身份边界契约测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.5.0 | 2026-10-25 | Codex | 覆盖最近计划时刻、运行待办排除、诊断折叠及UTC步骤时间转换。 |
| 1.3.0 | 2026-10-25 | Codex | 覆盖按上海当前时刻选择最近配置计划时刻。 |
| 1.2.0 | 2026-10-25 | Codex | 覆盖无心跳执行状态监督和失败研究来源沿用。 |
| 1.1.0 | 2026-10-25 | Codex | 覆盖桌面授权过期、六项投稿包绑定及启动失败后的原操作回执重放。 |
| 1.0.0 | 2026-10-25 | Codex | 覆盖新研究幂等并发、跨revision重放及显式运行/平台身份边界。 |
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
from threading import Barrier, Lock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from video_processing.db.database import PipelineDB
from video_processing.english_world.workbench import EnglishWorldWorkbench
from video_processing.english_world.package_integrity import calculate_package_hashes
from web.english_world_console import create_english_console_router, next_scheduled_display
from datetime import datetime, time
from zoneinfo import ZoneInfo


def _review_fixture(tmp_path):
    output = tmp_path / "output"
    output.mkdir(exist_ok=True)
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    files = {}
    for field, name in (("mp4_path", "video.mp4"), ("manifest_path", "manifest.json"),
                        ("title_path", "title.txt"), ("copy_path", "copy.txt"),
                        ("cover_path", "cover.png"), ("cover_provenance_path", "cover.json")):
        path = output / name
        path.write_bytes(field.encode("utf-8"))
        files[field] = str(path)
    Path(files["manifest_path"]).write_text(json.dumps({"product_context": {"product_intent": "NONE"}}))
    hashes = calculate_package_hashes(files)
    review = db.create_english_world_review_item(
        artifact_sha256=hashes["artifact_sha256"], manifest_sha256=hashes["manifest_sha256"],
        title_sha256=hashes["title_sha256"], copy_sha256=hashes["copy_sha256"],
        cover_sha256=hashes["cover_sha256"], cover_provenance_sha256=hashes["cover_provenance_sha256"],
        title="Fixture review", **files,
    )
    return db, output, review


def test_next_scheduled_display_uses_next_shanghai_slot_and_rolls_to_tomorrow():
    slots = (time(9, 0), time(14, 0), time(20, 0))
    shanghai = ZoneInfo("Asia/Shanghai")

    assert next_scheduled_display(slots, datetime(2026, 10, 25, 13, 30, tzinfo=shanghai)) == "14:00"
    assert next_scheduled_display(slots, datetime(2026, 10, 25, 20, 0, tzinfo=shanghai)) == "明日 09:00"


def test_failed_runs_do_not_inflate_business_waiting_and_technical_error_is_folded(tmp_path, monkeypatch):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    db.create_english_world_research_job()
    workbench = EnglishWorldWorkbench(db, tmp_path)
    business_rows, _, _ = workbench.console.tasks()
    created_at = "2026-10-25T08:00:00+08:00"
    runs = []
    long_error = "本次协调器运行失败\n执行摘要：Traceback (most recent call last): RuntimeError: " + "provider output " * 40
    for index in range(35):
        record = {"id": f"failed-run-{index}", "state": "FAILED", "title": f"Failed run {index}",
                  "created_at": created_at, "updated_at": created_at,
                  "error_message": long_error if index == 0 else "具体错误：下载请求返回 HTTP 403"}
        runs.append(workbench.console.task(None, record, run=True))
    monkeypatch.setattr(workbench.console, "tasks", lambda: (business_rows + runs, {}, []))

    result = workbench.view(view="attention")
    failed_run = next(row for row in business_rows + runs if row["id"] == "run:failed-run-0")
    item = workbench._item(failed_run)
    detail = workbench.detail("run:failed-run-0")
    short_error_run = workbench._item(next(row for row in runs if row["id"] == "run:failed-run-1"))

    assert result["summary"]["waiting"] == 0
    assert result["summary"]["active"] == 1
    assert result["summary"]["latest_run"]["record_type"] == "run"
    assert "本次协调器运行失败" in item["block_reason"]
    assert "Traceback" not in item["block_reason"]
    assert detail["safe_diagnostics"]["collapsed"] is True
    assert "Traceback" in detail["safe_diagnostics"]["text"]
    assert short_error_run["block_reason"] == "具体错误：下载请求返回 HTTP 403"


def test_same_new_research_operation_concurrently_creates_one_job(tmp_path, monkeypatch):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    workbench = EnglishWorldWorkbench(db, tmp_path)
    original = db.create_english_world_research_job
    prior_reads = db.english_world_workbench_audit_result
    entered = Barrier(2)
    count_lock = Lock()
    created = []

    def synchronized_create(**kwargs):
        result = original(**kwargs)
        with count_lock:
            created.append(result["id"])
        return result

    def simultaneous_prior_read(*args):
        result = prior_reads(*args)
        entered.wait(timeout=5)
        return result

    monkeypatch.setattr(db, "create_english_world_research_job", synchronized_create)
    monkeypatch.setattr(db, "english_world_workbench_audit_result", simultaneous_prior_read)

    def invoke():
        return workbench.action(task_id="new", action="research", revision="new-v1",
                                operation_id="same-operation-001", payload={}, actor="session-actor")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(invoke) for _ in range(2)]
        results = []
        for future in futures:
            results.append(future.result())

    assert len(created) == 1
    assert len(results) == 2
    assert len({result["audit_id"] for result in results}) == 1
    assert sum(bool(result.get("replayed")) for result in results) == 1
    snapshot = db.english_console_snapshot()
    assert len(snapshot["jobs"]) == 1


def test_same_operation_replays_original_receipt_after_revision_changes(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    workbench = EnglishWorldWorkbench(db, tmp_path)
    first = workbench.action(task_id="new", action="research", revision="new-v1",
                             operation_id="same-operation-002", payload={}, actor="session-actor")

    replay = workbench.action(task_id="new", action="research", revision="new-v2",
                              operation_id="same-operation-002", payload={}, actor="session-actor")

    assert replay["replayed"] is True
    assert replay["task_id"] == first["task_id"]
    assert replay["audit_id"] == first["audit_id"]
    assert len(db.english_console_snapshot()["jobs"]) == 1


def test_early_run_failure_uses_only_exact_run_log_sidecar(tmp_path):
    run_log = tmp_path / "run_2026-10-25_090000_000000.log"
    identity_path = run_log.with_suffix(".identity.json")
    identity_path.write_text('{"identity_schema":1,"run_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",'
                             '"attempts":[{"run_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",'
                             '"source_attempt_id":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",'
                             '"candidate_id":"abcdefghijk"}]}', encoding="utf-8")
    service = EnglishWorldWorkbench(PipelineDB(str(tmp_path / "pipeline.db")), tmp_path)

    # A run without a request can be bound by the coordinator's exact log path.
    identity = service._run_identity({"_request": None, "_run_log": str(run_log)})

    assert identity["run_id"] == "a" * 32
    assert identity["attempts"][0]["source_attempt_id"] == "b" * 32


def test_manual_public_claim_requires_existing_evidence_and_matching_native_id(tmp_path):
    output = tmp_path / "output"
    evidence_dir = output / "reconciliation"
    evidence_dir.mkdir(parents=True)
    evidence = evidence_dir / "capture.png"
    evidence.write_bytes(b"fixture")
    service = EnglishWorldWorkbench(PipelineDB(str(tmp_path / "pipeline.db")), output)
    record = {"platform_post_id": "native-123", "evidence_dir": str(evidence_dir)}

    (evidence_dir / "management_readback.json").write_text(
        '{"platform_post_id":"native-123","state":"PUBLISHED","reason":"DOM_STATUS_TEXT"}', encoding="utf-8")
    assert not service._identity_match(record, {"verified": True, "native_id": "native-123",
                                                "evidence_ref": "arbitrary.png"}, "public")
    assert not service._identity_match(record, {"verified": True, "native_id": "other-id",
                                                "evidence_ref": "management_readback.json"}, "public")
    assert not service._identity_match(record, {"verified": False, "native_id": "native-123",
                                                "evidence_ref": "management_readback.json"}, "public")


def test_candidate_from_another_job_cannot_be_selected(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    workbench = EnglishWorldWorkbench(db, tmp_path)
    first = db.create_english_world_research_job()
    second = db.create_english_world_research_job()
    candidate = {"id": "candidate-foreign", "source_url": "https://www.youtube.com/watch?v=abcdefghijk",
                 "youtube_id": "abcdefghijk", "source_title": "A useful science story",
                 "source_channel": "CBC Kids News", "source_channel_id": "UCWUA2W6LueNy9BSovivFVvQ",
                 "topic": "science", "learning_value": "Vocabulary", "safety_note": "Metadata only",
                 "caption_status": "not checked", "recommendation_score": 80}
    for job in (first, second):
        assert db.claim_english_world_job_for_research(job["id"])
        db.complete_english_world_research(job["id"], candidates=[candidate if job is second else
            {**candidate, "id": "candidate-local", "youtube_id": "dQw4w9WgXcQ",
             "source_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}])
    row = workbench.console.find("job:" + first["id"])
    item = workbench._item(row)

    try:
        workbench.action(task_id="job:" + first["id"], action="select_candidate", revision=item["revision"],
                         operation_id="foreign-candidate-op", payload={"candidate_id": "candidate-foreign"},
                         actor="session-actor")
    except PermissionError as exc:
        assert "不属于当前任务" in str(exc)
    else:
        raise AssertionError("a candidate from another research job must not be selectable")

    assert db.get_english_world_job(first["id"])["state"] == "CANDIDATES_READY"


def test_all_tasks_page_through_without_a_20_item_truncation(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    for _ in range(43):
        db.create_english_world_research_job()
    workbench = EnglishWorldWorkbench(db, tmp_path)

    pages = [workbench.view(view="all", page=page) for page in (1, 2, 3)]

    assert [page["total"] for page in pages] == [43, 43, 43]
    assert [len(page["items"]) for page in pages] == [20, 20, 3]
    assert len({item["task_id"] for page in pages for item in page["items"]}) == 43


def test_history_over_twenty_items_has_reachable_second_page(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    for _ in range(25):
        db.create_english_world_research_job()
    with db.get_connection() as conn:
        conn.execute("UPDATE english_world_jobs SET created_at='2026-10-01T00:00:00+00:00', updated_at='2026-10-01T00:00:00+00:00'")
        conn.commit()
    workbench = EnglishWorldWorkbench(db, tmp_path)

    first = workbench.view(view="all", history=True, page=1)
    second = workbench.view(view="all", history=True, page=2)

    assert first["history"]["count"] == 25
    assert first["history"]["pages"] == 2
    assert len(first["history"]["items"]) == 20
    assert second["history"]["page"] == 2
    assert len(second["history"]["items"]) == 5
    assert len({item["task_id"] for page in (first, second) for item in page["history"]["items"]}) == 25


def test_resume_stays_blocked_without_formal_executor(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    job = db.create_english_world_research_job()
    db.fail_english_world_job(job["id"], "bounded fixture failure")
    workbench = EnglishWorldWorkbench(db, tmp_path)
    row = workbench.console.find("job:" + job["id"])
    item = workbench._item(row)

    assert item["action_eligibility"]["resume"]["allowed"] is False
    try:
        workbench.action(task_id="job:" + job["id"], action="resume", revision=item["revision"],
                         operation_id="blocked-resume-op", payload={}, actor="session-actor")
    except PermissionError:
        pass
    else:
        raise AssertionError("resume must fail closed without a formal single-task executor")
    assert db.get_english_world_job(job["id"])["state"] == "FAILED"


def test_stale_execution_without_heartbeat_is_visible_as_unverified_attention(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    job = db.create_english_world_research_job(source_url="https://www.youtube.com/watch?v=abcdefghijk")
    assert db.claim_english_world_job_for_research(job["id"])
    with db.get_connection() as conn:
        conn.execute("UPDATE english_world_jobs SET created_at=?, updated_at=? WHERE id=?",
                     ("2026-10-25 00:29:20", "2026-10-25 00:30:14", job["id"]))
        conn.commit()
    workbench = EnglishWorldWorkbench(db, tmp_path)

    result = workbench.view(view="attention")
    item = next(item for item in result["items"] if item["task_id"] == "job:" + job["id"])
    detail = workbench.detail(item["task_id"])
    research = next(step for step in detail["steps"] if step["id"] == "research")

    assert item["status"] == "RESEARCHING"
    assert item["display_status"] == "研究状态待核实"
    assert item["current_step"] == "研究状态待核实"
    assert "没有近期执行心跳" in item["block_reason"]
    assert result["summary"]["active"] == 0
    assert result["summary"]["waiting"] >= 1
    assert item["action_eligibility"]["research"]["allowed"] is False
    assert research["display_state"] == "研究状态待核实"
    assert research["started_at"] == "2026-10-25T08:29:20+08:00"
    assert research["last_activity"] == "2026-10-25T08:30:14+08:00"

    journal = tmp_path / "stage_recovery.json"
    journal.write_text(json.dumps({"attempts": [{"run_id": "run-1", "source_attempt_id": "attempt-1",
        "stage": "language_review", "state": "RUNNING", "started_ns": 1000000000}]}), encoding="utf-8")
    stages = workbench._run_steps({"run_id": "run-1"},
        {"source_attempt_id": "attempt-1", "stage_journal": str(journal)})
    assert stages[0]["label"] == "语言复核"
    assert stages[0]["display_state"] == "阶段已开始 · 执行状态待核实"
    assert "没有后续心跳" in stages[0]["detail"]


def test_failed_research_creates_new_job_with_original_source_url(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    source_url = "https://www.youtube.com/watch?v=abcdefghijk"
    original = db.create_english_world_research_job(source_url=source_url)
    db.fail_english_world_job(original["id"], "bounded fixture failure")
    workbench = EnglishWorldWorkbench(db, tmp_path)
    item = workbench._item(workbench.console.find("job:" + original["id"]))

    result = workbench.action(task_id="job:" + original["id"], action="research", revision=item["revision"],
        operation_id="research-from-failed-original", payload={}, actor="session-actor")

    new_job = db.get_english_world_job(result["task_id"].removeprefix("job:"))
    assert new_job["source_url"] == source_url
    assert db.get_english_world_job(original["id"])["state"] == "FAILED"


def test_record_outcome_is_audit_only_and_detail_keeps_verification_boundary(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    paths = {}
    for field in ("mp4", "manifest", "title", "copy", "cover", "cover_provenance"):
        path = output / f"{field}.fixture"
        path.write_bytes(field.encode())
        paths[f"{field}_path"] = str(path)
    review = db.create_english_world_review_item(
        artifact_sha256=hashlib.sha256(b"fixture package").hexdigest(),
        manifest_sha256="1" * 64, title_sha256="2" * 64, copy_sha256="3" * 64,
        cover_sha256="4" * 64, cover_provenance_sha256="5" * 64, title="Fixture review",
        **paths,
    )
    db.approve_english_world_submission(review["id"], authorization="TELEGRAM_REVIEW")
    claim = db.claim_english_world_submission(review["id"])
    assert claim
    attempt_id = db.list_english_world_submission_attempts(review["id"])[0]["attempt_id"]
    db.complete_english_world_submission(review["id"], state="UNCERTAIN", uploader_exit_code=1,
                                         attempt_id=attempt_id, platform_post_id="native-123")
    workbench = EnglishWorldWorkbench(db, output)
    row = workbench.console.find("review:" + review["id"])
    item = workbench._item(row)
    before = db.get_english_world_review_item(review["id"])

    result = workbench.action(task_id="review:" + review["id"], action="record_outcome",
                              revision=item["revision"], operation_id="outcome-audit-op",
                              payload={"outcome": "unknown", "verified": True,
                                       "evidence": {"native_id": "native-123", "evidence_ref": "random.png"}},
                              actor="session-actor")
    detail = workbench.detail("review:" + review["id"])
    after = db.get_english_world_review_item(review["id"])

    assert result["submission_state_changed"] is False
    assert result["evidence_identity"] == "NOT_VERIFIED"
    assert "未核实" in result["verification_note"]
    assert after["state"] == before["state"] == "UNCERTAIN"
    assert detail["audit"]
    platform_evidence = next(entry for entry in detail["evidence"] if entry["kind"] == "submission")
    assert "UNCERTAIN" in platform_evidence["summary"]
    assert "本页未访问平台" in platform_evidence["summary"]


def test_desktop_approval_expiry_returns_to_review_without_reauthorization_or_auto_dispatch(tmp_path):
    db, _output, review = _review_fixture(tmp_path)
    approved = db.approve_english_world_submission(review["id"], authorization="DESKTOP_WORKBENCH")
    assert approved["approval_source"] == "DESKTOP_WORKBENCH"
    with db.get_connection() as conn:
        conn.execute("UPDATE english_world_review_items SET authorization_expires_at='2000-01-01 00:00:00' WHERE id=?",
                     (review["id"],))
        conn.commit()

    expired = db.expire_english_world_submission_authorization(review["id"])

    assert expired["state"] == "READY_FOR_REVIEW"
    assert expired["approval_source"] is None
    assert expired["authorization_expires_at"] is None
    assert db.list_english_world_submission_attempts(review["id"]) == []
    assert db.get_next_auto_approved_english_world_submission() is None


def test_workbench_approval_rejects_each_changed_package_binding(tmp_path, monkeypatch):
    path_fields = {
        "artifact_sha256": "mp4_path", "manifest_sha256": "manifest_path",
        "title_sha256": "title_path", "copy_sha256": "copy_path",
        "cover_sha256": "cover_path", "cover_provenance_sha256": "cover_provenance_path",
    }
    for index, (hash_field, path_field) in enumerate(path_fields.items()):
        case = tmp_path / str(index)
        case.mkdir()
        db, output, review = _review_fixture(case)
        workbench = EnglishWorldWorkbench(db, output)
        monkeypatch.setattr(workbench, "_product_context_status", lambda _record: (True, "fixture gated independently"))
        row = workbench.console.find("review:" + review["id"])
        item = workbench._item(row)
        Path(review[path_field]).write_bytes(b"changed after approval snapshot")

        with pytest.raises(PermissionError, match="哈希不一致"):
            workbench.action(task_id="review:" + review["id"], action="approve_submission",
                             revision=item["revision"], operation_id=f"changed-hash-{index}",
                             payload={}, actor="session-actor")
        assert db.get_english_world_review_item(review["id"])["state"] == "READY_FOR_REVIEW"


def test_failed_dispatch_replays_original_approval_without_second_dispatch(tmp_path, monkeypatch):
    db, output, review = _review_fixture(tmp_path)
    db.topic_initialize()
    monkeypatch.setattr(EnglishWorldWorkbench, "_product_context_status",
                        lambda _self, _record: (True, "fixture gated independently"))
    calls = []

    def fail_dispatch(review_id):
        calls.append(review_id)
        raise RuntimeError("synthetic dispatcher failure")

    app = FastAPI()
    app.include_router(create_english_console_router(
        db, port=9100, output=output, start_submission=fail_dispatch,
    ))
    client = TestClient(app, base_url="http://127.0.0.1:9100", client=("127.0.0.1", 50000))
    assert client.get("/english-world").status_code == 200
    token = client.cookies.get("runtime_local_session")
    csrf = hashlib.sha256(("runtime-csrf:" + token).encode()).hexdigest()
    workbench = EnglishWorldWorkbench(db, output)
    row = workbench.console.find("review:" + review["id"])
    revision = workbench._item(row)["revision"]
    body = {"task": "review:" + review["id"], "action": "approve_submission",
            "revision": revision, "operation_id": "dispatch-failure-op-01", "payload": {}}
    headers = {"Origin": "http://127.0.0.1:9100", "X-Runtime-CSRF": csrf}

    first = client.post("/api/english-world/workbench/actions", json=body, headers=headers)
    replay = client.post("/api/english-world/workbench/actions", json=body, headers=headers)

    assert first.status_code == 503
    assert first.json()["dispatch_state"] == "FAILED_OR_UNKNOWN"
    assert replay.status_code == 200
    assert replay.json()["replayed"] is True
    assert replay.json()["dispatch_state"] == "FAILED_OR_UNKNOWN"
    assert calls == [review["id"]]


@pytest.mark.parametrize("linked_job", [False, True])
def test_approval_dispatches_bound_review_once_for_both_task_forms(tmp_path, monkeypatch, linked_job):
    db, output, review = _review_fixture(tmp_path)
    db.topic_initialize()
    monkeypatch.setattr(EnglishWorldWorkbench, "_product_context_status",
                        lambda _self, _record: (True, "fixture gated independently"))
    task_id = "review:" + review["id"]
    if linked_job:
        job = db.create_english_world_research_job()
        assert db.claim_english_world_job_for_research(job["id"])
        db.complete_english_world_research(job["id"], candidates=[{
            "id": "dispatch-candidate", "source_url": "https://www.youtube.com/watch?v=abcdefghijk",
            "source_title": "Synthetic science story", "source_channel_id": "UCWUA2W6LueNy9BSovivFVvQ",
            "youtube_id": "abcdefghijk", "topic": "science", "learning_value": "Vocabulary",
            "safety_note": "Synthetic fixture", "caption_status": "unchecked"}])
        db.select_english_world_candidate("dispatch-candidate")
        db.request_english_world_production(job["id"])
        assert db.claim_english_world_job_for_production(job["id"])
        db.complete_english_world_job_production(job["id"], review_id=review["id"],
                                                mp4_path=review["mp4_path"], manifest_path=review["manifest_path"])
        task_id = "job:" + job["id"]
    calls = []
    app = FastAPI()
    app.include_router(create_english_console_router(db, port=9100, output=output, start_submission=calls.append))
    client = TestClient(app, base_url="http://127.0.0.1:9100", client=("127.0.0.1", 50000))
    assert client.get("/english-world").status_code == 200
    csrf = hashlib.sha256(("runtime-csrf:" + client.cookies.get("runtime_local_session")).encode()).hexdigest()
    service = EnglishWorldWorkbench(db, output)
    body = {"task": task_id, "action": "approve_submission",
            "revision": service._item(service.console.find(task_id))["revision"],
            "operation_id": "bound-review-dispatch-01", "payload": {"review_id": "untrusted-other-review"}}
    headers = {"Origin": "http://127.0.0.1:9100", "X-Runtime-CSRF": csrf}

    first = client.post("/api/english-world/workbench/actions", json=body, headers=headers)
    replay = client.post("/api/english-world/workbench/actions", json=body, headers=headers)

    assert first.status_code == replay.status_code == 200
    assert calls == [review["id"]]
    assert first.json()["review_id"] == review["id"]
    assert first.json()["dispatch_state"] == "ADMITTED"
    assert replay.json()["replayed"] is True
    assert replay.json()["review_id"] == review["id"]
    assert db.get_english_world_review_item(review["id"])["approval_source"] == "DESKTOP_WORKBENCH"
