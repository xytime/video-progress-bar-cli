"""英语世界工作台运行身份与程序化阶段关联回归。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.2.0 | 2026-10-25 | Codex | 验证人工续做只接受未通知宿主失败回执及冻结输入哈希。 |
| 1.1.0 | 2026-10-25 | Codex | 验证受限续做的宿主阶段回执不得从通知启动状态降级。 |
| 1.0.0 | 2026-10-25 | Codex | 验证运行身份 sidecar、阶段记录和交付请求具名关联。 |
"""

import json
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import english_world_programmatic_daily as programmatic
from scripts import run_english_world_daily as daily
from video_processing.db.database import PipelineDB


def test_programmatic_stage_journal_carries_explicit_run_and_attempt_ids(tmp_path):
    workspace = tmp_path / "attempt"
    identity = {
        "identity_schema": 1,
        "run_id": "a" * 32,
        "source_attempt_id": "b" * 32,
        "candidate_id": "abcdefghijk",
        "request_path": str((tmp_path / "request.json").resolve()),
    }
    programmatic.atomic_json(workspace / "run_identity.json", identity)

    assert programmatic._stage_call("source_evidence", workspace, lambda: "evidence") == "evidence"

    journal = json.loads((workspace / "qa/stage_recovery.json").read_text())
    assert len(journal["attempts"]) == 1
    event = journal["attempts"][0]
    assert (event["run_id"], event["source_attempt_id"]) == (identity["run_id"], identity["source_attempt_id"])
    assert event["stage"] == "source_evidence"
    assert event["state"] == "COMPLETED"


def test_programmatic_child_writes_attempt_into_only_the_named_parent_sidecar(tmp_path):
    run_id = "a" * 32
    identity_path = tmp_path / f"run_{run_id}.identity.json"
    daily_identity = {
        "identity_schema": 1, "run_id": run_id, "request_path": str((tmp_path / "req.json").resolve()),
        "source_attempt_id": None, "attempts": [],
    }
    programmatic.atomic_json(identity_path, daily_identity)
    workspace = tmp_path / "candidate_attempt"
    identity = {
        "identity_schema": 1, "run_id": run_id, "source_attempt_id": "c" * 32,
        "candidate_id": "abcdefghijk", "request_path": daily_identity["request_path"],
    }
    programmatic.atomic_json(workspace / "run_identity.json", identity)

    programmatic._record_run_attempt(
        identity_path, run_id=run_id, source_attempt_id=identity["source_attempt_id"],
        candidate_id=identity["candidate_id"], workspace=workspace,
    )

    result = json.loads(identity_path.read_text())
    assert result["run_id"] == run_id
    assert result["attempts"] == [{
        "source_attempt_id": identity["source_attempt_id"], "candidate_id": identity["candidate_id"],
        "workspace": str(workspace.resolve()),
        "stage_journal": str((workspace / "qa/stage_recovery.json").resolve()),
        "failure_path": str((workspace / "qa/candidate_failure.json").resolve()),
    }]
    assert "HISTORICAL_UNBOUND" not in result
    with pytest.raises(ValueError, match="duplicate source_attempt_id"):
        programmatic._record_run_attempt(
            identity_path, run_id=run_id, source_attempt_id=identity["source_attempt_id"],
            candidate_id=identity["candidate_id"], workspace=workspace,
        )


def test_run_attempt_rejects_sidecar_for_another_run(tmp_path):
    identity_path = tmp_path / "identity.json"
    programmatic.atomic_json(identity_path, {"identity_schema": 1, "run_id": "a" * 32, "attempts": []})
    with pytest.raises(ValueError, match="does not match"):
        programmatic._record_run_attempt(identity_path, run_id="b" * 32,
                                         source_attempt_id="c" * 32, candidate_id="abcdefghijk",
                                         workspace=tmp_path / "candidate")


def test_success_request_carries_the_exact_parent_and_candidate_identity(tmp_path, monkeypatch):
    request = tmp_path / "request.json"
    manifest = tmp_path / "english_world.manifest.json"
    request.write_text(json.dumps({"kind": "production", "title": "fixture"}))
    identity_path = tmp_path / f"run_{'a' * 32}.identity.json"

    def fake_run(*_args, **_kwargs):
        return 0

    monkeypatch.setattr(programmatic, "_run", fake_run)
    programmatic._make_delivery_request(
        request=request, title="fixture", mp4=tmp_path / "english_world.mp4", manifest=manifest,
        audio_qa=tmp_path / "audio.json", safety=tmp_path / "safety.json",
        run_id="a" * 32, source_attempt_id="b" * 32, run_identity_path=identity_path,
    )

    payload = json.loads(request.read_text())
    assert payload["workbench_run_id"] == "a" * 32
    assert payload["source_attempt_id"] == "b" * 32
    assert payload["workbench_run_identity_path"] == str(identity_path.resolve())


def test_daily_identity_rejects_guessed_ids_before_running(tmp_path):
    paths = daily.RuntimePaths(
        project_root=tmp_path, codex_home=tmp_path, codex_bin=tmp_path / "codex",
        python_bin=tmp_path / "python", notifier_script=tmp_path / "notify.py",
        log_dir=tmp_path / "logs", lock_dir=tmp_path / "locks" / "daily.lock",
        coordinator_provider="programmatic", coordinator_timeout_seconds=30,
    )
    with pytest.raises(ValueError, match="32-character lowercase hex"):
        daily.run(paths, max_attempts=1, retry_delay_seconds=0, workbench_run_id="latest")


def test_identity_creation_preserves_existing_run_receipt(tmp_path):
    path = tmp_path / "run.identity.json"
    first = {"identity_schema": 1, "run_id": "a" * 32, "attempts": []}
    daily._create_workbench_run_identity(path, first)
    original = path.read_text()

    with pytest.raises(FileExistsError):
        daily._create_workbench_run_identity(path, {**first, "attempts": [{"candidate_id": "abcdefghijk"}]})

    assert path.read_text() == original


def test_host_phase_starting_cannot_be_rewritten_as_pre_notifier_failure(tmp_path):
    run_id, attempt_id = "a" * 32, "b" * 32
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    paths = daily.RuntimePaths(
        project_root=tmp_path, codex_home=tmp_path, codex_bin=tmp_path / "codex",
        python_bin=tmp_path / "python", notifier_script=tmp_path / "notify.py",
        log_dir=log_dir, lock_dir=tmp_path / "locks" / "daily.lock",
        coordinator_timeout_seconds=30,
    )
    request = log_dir / "run_fixture.delivery-request.json"
    artifacts = {key: log_dir / key for key in ("mp4", "manifest", "audio", "safety")}
    for key, path in artifacts.items():
        path.write_bytes(key.encode())
    request.write_text(json.dumps({
        "kind": "production", "title": "fixture", "workbench_run_id": run_id,
        "source_attempt_id": attempt_id,
        "workbench_run_identity_path": str(request.with_name("run_fixture.identity.json")),
        "mp4": str(artifacts["mp4"]), "manifest": str(artifacts["manifest"]),
        "audio_qa_report": str(artifacts["audio"]), "safety_report": str(artifacts["safety"]),
    }), encoding="utf-8")

    daily._write_host_phase(request, paths, state="STARTING", notifier_started=True,
                            request={"mp4": str(artifacts["mp4"]), "manifest": str(artifacts["manifest"]),
                                     "audio_qa_report": str(artifacts["audio"]),
                                     "safety_report": str(artifacts["safety"])})
    marker = request.with_name("run_fixture.host-phase.json")
    original = marker.read_text(encoding="utf-8")
    daily._write_host_phase(request, paths, state="FAILED_BEFORE_NOTIFIER", notifier_started=False,
                            request=None, detail="later failure")

    assert json.loads(marker.read_text(encoding="utf-8"))["state"] == "STARTING"
    assert marker.read_text(encoding="utf-8") == original


def test_workbench_delivery_forces_manual_review_only_with_fake_host(tmp_path, monkeypatch):
    project = tmp_path / "project"
    log_dir = project / "output/english_world_daily"
    log_dir.mkdir(parents=True)
    (project / "output").mkdir(exist_ok=True)
    PipelineDB(str(project / "output/pipeline.db"))
    manifest = project / "manifest.json"
    manifest.write_text('{"source_provenance":{"youtube_id":"abcdefghijk"}}', encoding="utf-8")
    mp4 = project / "clip.mp4"
    audio = project / "audio.json"
    mp4.write_bytes(b"video")
    audio.write_text('{}', encoding="utf-8")
    request_path = log_dir / "run_fixture.delivery-request.json"
    request_path.write_text(json.dumps({"kind": "production", "title": "fixture",
                                        "mp4": str(mp4), "manifest": str(manifest),
                                        "audio_qa_report": str(audio),
                                        "workbench_run_id": "a" * 32,
                                        "source_attempt_id": "b" * 32}), encoding="utf-8")
    normalized = {"kind": "production", "title": "fixture", "mp4": str(mp4),
                  "manifest": str(manifest), "audio_qa_report": str(audio)}
    monkeypatch.setattr(daily, "_read_delivery_request", lambda *_args, **_kwargs: normalized)
    captured = {}

    def fake_host(command, **_kwargs):
        captured["command"] = command
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(daily, "run_admitted", fake_host)
    paths = daily.RuntimePaths(
        project_root=project, codex_home=tmp_path, codex_bin=tmp_path / "codex",
        python_bin=tmp_path / "python", notifier_script=project / "scripts/notify.py",
        log_dir=log_dir, lock_dir=project / "output/locks/daily.lock",
        coordinator_timeout_seconds=30,
    )

    code, failure_reported = daily._deliver_request_from_host(
        paths, request_path, request_path.with_name("run_fixture.delivery.json"), StringIO(),
        manual_review_only=True,
    )

    command = captured["command"]
    assert code == 0 and failure_reported is False
    assert "--manual-review-only" in command
    assert "--allow-production-retry" not in command
    marker = json.loads(request_path.with_name("run_fixture.host-phase.json").read_text(encoding="utf-8"))
    assert marker["state"] == "STARTING" and marker["notifier_started"] is True


def test_workbench_resume_requires_exact_pre_notifier_marker_and_unchanged_inputs(tmp_path, monkeypatch):
    project = tmp_path / "project"
    log_dir = project / "output/english_world_daily"
    log_dir.mkdir(parents=True)
    (project / "output").mkdir(exist_ok=True)
    PipelineDB(str(project / "output/pipeline.db"))
    run_id, attempt_id = "a" * 32, "b" * 32
    request_path = log_dir / "run_fixture.delivery-request.json"
    identity_path = log_dir / "run_fixture.identity.json"
    artifacts = {key: project / f"{key}.bin" for key in ("mp4", "manifest", "audio", "safety")}
    for key, path in artifacts.items():
        path.write_bytes(key.encode())
    request_path.write_text(json.dumps({
        "kind": "production", "title": "fixture", "workbench_run_id": run_id,
        "source_attempt_id": attempt_id, "workbench_run_identity_path": str(identity_path),
        "mp4": str(artifacts["mp4"]), "manifest": str(artifacts["manifest"]),
        "audio_qa_report": str(artifacts["audio"]), "safety_report": str(artifacts["safety"]),
    }), encoding="utf-8")
    identity_path.write_text(json.dumps({
        "identity_schema": 1, "run_id": run_id,
        "attempts": [{"run_id": run_id, "source_attempt_id": attempt_id}],
    }), encoding="utf-8")
    normalized = {"kind": "production", "mp4": str(artifacts["mp4"]),
                  "manifest": str(artifacts["manifest"]),
                  "audio_qa_report": str(artifacts["audio"]),
                  "safety_report": str(artifacts["safety"])}
    monkeypatch.setattr(daily, "_read_delivery_request", lambda *_args, **_kwargs: normalized)
    paths = daily.RuntimePaths(
        project_root=project, codex_home=tmp_path, codex_bin=tmp_path / "codex",
        python_bin=tmp_path / "python", notifier_script=project / "scripts/notify.py",
        log_dir=log_dir, lock_dir=project / "output/locks/daily.lock",
        coordinator_timeout_seconds=30,
    )

    daily._write_host_phase(request_path, paths, state="FAILED_BEFORE_NOTIFIER",
                            notifier_started=False, request=normalized)
    assert daily._validate_workbench_resume(paths, request_path) == normalized

    marker_path = request_path.with_name("run_fixture.host-phase.json")
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["state"] = "STARTING"
    marker["notifier_started"] = True
    marker_path.write_text(json.dumps(marker), encoding="utf-8")
    with pytest.raises(ValueError, match="投稿前宿主失败回执"):
        daily._validate_workbench_resume(paths, request_path)

    marker["state"] = "FAILED_BEFORE_NOTIFIER"
    marker["notifier_started"] = False
    marker["mp4_sha256"] = "0" * 64
    marker_path.write_text(json.dumps(marker), encoding="utf-8")
    with pytest.raises(ValueError, match="指纹与原宿主失败回执不一致"):
        daily._validate_workbench_resume(paths, request_path)


def test_workbench_app_wires_production_and_resume_to_their_distinct_runner_argv(monkeypatch):
    from web import app as web_app

    spawned = []
    invocations = []
    monkeypatch.setattr(web_app, "spawn_admitted",
                        lambda target, **kwargs: spawned.append((target, kwargs)))
    monkeypatch.setattr(web_app, "run_admitted", lambda argv, **kwargs: (
        invocations.append((argv, kwargs)) or SimpleNamespace(returncode=0, stderr="")
    ))

    job_id = "job-123"
    web_app._start_english_world_production(job_id)
    assert len(spawned) == 1
    production_target, production_meta = spawned.pop()
    assert production_meta["role"] == "english-production"
    production_target()
    production_argv = invocations.pop()[0]
    assert production_argv[production_argv.index("--job-id"):production_argv.index("--job-id") + 2] == ["--job-id", job_id]
    assert production_argv[production_argv.index("--wait-for-lock-seconds"):][:2] == ["--wait-for-lock-seconds", "7200"]
    assert "--workbench-resume" not in production_argv

    request_path = "/tmp/run.delivery-request.json"
    web_app._start_english_world_workbench_resume(request_path)
    assert len(spawned) == 1
    resume_target, resume_meta = spawned.pop()
    assert resume_meta["role"] == "english-workbench-resume"
    resume_target()
    resume_argv = invocations.pop()[0]
    assert resume_argv[-3:] == ["--resume-delivery-request", request_path, "--workbench-resume"]
