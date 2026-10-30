"""双七天服务的资源边界与引用反例；只使用真实临时目录和隔离存储。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-31 | Codex | 空闲双七天、预算、字幕、引用、占用与恢复冲突验证 |
"""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
import json
import os
from types import SimpleNamespace

import pytest

from config.output_retention import OutputRetentionPolicy
from video_processing.core.output_retention import DAY, OutputRetentionService, RetentionInventory
from video_processing.core.output_retention_store import OutputRetentionStore
from video_processing.db.database import PipelineDB


SOURCE = "abcdefghijk"


class Host:
    def __init__(self):
        self.facts = {"status": "OK", "busy_processes": [], "open_references": [], "tracked_paths": []}
        self.captures, self.locks, self.inside = 0, 0, False
        self.on_lock = None
        self.mount_ok = True

    def verify_mount(self):
        if not self.mount_ok:
            raise RuntimeError("VOLUME_UNKNOWN")
        return {"volume_uuid": "test-volume"}

    def capture(self):
        self.captures += 1
        return deepcopy(self.facts)

    @contextmanager
    def exclusive_idle(self):
        self.locks += 1
        self.inside = True
        try:
            if self.on_lock:
                self.on_lock()
            yield
        finally:
            self.inside = False


@pytest.fixture
def setup_service(tmp_path, monkeypatch):
    volume = tmp_path / "volume"
    project, store = volume / "project", volume / "control/store"
    output = project / "output"
    output.mkdir(parents=True)
    now = [1_800_000_000.0]
    initial = OutputRetentionStore(output, store, create=True, clock=lambda: now[0])
    policy = OutputRetentionPolicy(str(project), str(output), str(volume), "test-volume", str(store),
                                   initial.identity, max_seconds=30)
    host = Host()
    state = {"snapshot": {"status": "OK", "sources": {
        SOURCE: {"terminal": True, "last_activity_at": now[0] - 30 * DAY}},
        "path_references": []}, "reads": 0, "on_read": None}

    def snapshot(_):
        assert not host.inside or state["reads"] >= 1
        state["reads"] += 1
        if state["on_read"]:
            state["on_read"](state["reads"])
        return deepcopy(state["snapshot"])

    monkeypatch.setattr(PipelineDB, "output_retention_snapshot", staticmethod(snapshot))
    service = OutputRetentionService(policy, host, clock=lambda: now[0])

    def artifact(name=None, content=b"old video"):
        path = output / (name or f"{SOURCE}.mp4")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        os.utime(path, (now[0] - 20 * DAY,) * 2)
        return path

    return SimpleNamespace(service=service, policy=policy, host=host, state=state,
                           now=now, output=output, store=store, artifact=artifact)


def test_quarantine_observation_uses_success_time_then_purges(setup_service):
    env = setup_service
    source = env.artifact()
    run = env.service.run(apply=True)
    assert run["state"] == "COMPLETE"
    assert [row["action"] for row in run["actions"]] == ["QUARANTINED"]
    assert not source.exists()
    receipt = env.service.store.list_receipts()[0]
    assert receipt["quarantined_at"] == env.now[0]
    assert env.host.locks == 1
    env.now[0] += 7 * DAY - 1
    assert not env.service.run(apply=True)["actions"]
    assert env.service.store.get_receipt(receipt["id"])["state"] == "QUARANTINED"
    env.now[0] += 2
    final = env.service.run(apply=True)
    assert final["actions"][0]["action"] == "PURGED"
    assert final["purged_logical_bytes"] == len(b"old video")


def test_busy_or_unknown_host_does_not_scan_database_or_output(setup_service):
    env = setup_service
    env.artifact()
    env.host.facts["busy_processes"] = [{"pid": 123, "kinds": ["auto-caption"]}]
    assert env.service.run(apply=True)["state"] == "SKIPPED_BUSY"
    assert env.state["reads"] == 0
    env.host.facts.update(status="UNKNOWN", busy_processes=[])
    assert env.service.run(apply=True)["state"] == "BLOCKED_UNKNOWN"
    assert env.state["reads"] == 0


def test_missing_mount_never_creates_control_lock_or_receipt(setup_service):
    env = setup_service
    env.host.mount_ok = False
    run = env.service.run(apply=True)
    assert run["state"] == "BLOCKED"
    assert run["receipt_error"] == "CONTROL_WRITE_UNAVAILABLE"
    assert not (env.store.parent / "run.lock").exists()
    assert not (env.store.parent / "runs").exists()
    assert not (env.store.parent / "latest.json").exists()


def test_control_receipt_directory_cannot_follow_symlink(setup_service, tmp_path):
    env = setup_service
    outside = tmp_path / "outside"
    outside.mkdir()
    (env.store.parent / "runs").symlink_to(outside, target_is_directory=True)
    run = env.service.run()
    assert run["receipt_error"] == "CONTROL_WRITE_UNAVAILABLE"
    assert list(outside.iterdir()) == []


def test_source_subtitles_remain_even_when_very_old(setup_service):
    env = setup_service
    subtitles = [env.artifact(f"{SOURCE}{suffix}") for suffix in (".ass", ".srt", ".vtt")]
    env.now[0] += 365 * DAY
    assert not env.service.run(apply=True)["actions"]
    assert all(path.exists() for path in subtitles)


def test_manifest_in_protected_directory_preserves_referenced_media(setup_service):
    env = setup_service
    source = env.artifact()
    manifest = env.output / "evidence/current/manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"status": "DONE", "asset": str(source)}))
    run = env.service.run(apply=True)
    assert not run["actions"]
    assert run["skipped"]["MANIFEST_REFERENCE"] == 1
    assert source.exists()


def test_ordinary_symlink_preserves_its_target_without_following(setup_service):
    env = setup_service
    source = env.artifact()
    (env.output / "final.mp4").symlink_to(source.name)
    run = env.service.run(apply=True)
    assert not run["actions"]
    assert run["skipped"]["SYMLINK_REFERENCE"] == 1
    assert source.exists()


def test_unknown_json_and_scan_budget_fail_closed(setup_service):
    env = setup_service
    source = env.artifact()
    manifest = env.output / "manifest.json"
    manifest.write_text("{")
    run = env.service.run(apply=True)
    assert run["state"] == "BLOCKED_UNKNOWN"
    assert source.exists()
    manifest.unlink()
    env.service.policy = replace(env.policy, scan_entries=1)
    assert env.service.run(apply=True)["state"] == "BLOCKED"
    assert source.exists()


def test_static_ytdlp_and_package_json_do_not_consume_reference_budget(setup_service):
    env = setup_service
    env.artifact(f"{SOURCE}.info.json", b"x" * (2 * 1024**2 + 1))
    env.artifact("package-data.json", b"x" * (2 * 1024**2 + 1))
    env.artifact(f"{SOURCE}_vertical.source-captions.evidence.json", b"x" * (2 * 1024**2 + 1))
    env.artifact("investigations/log_records.json", b"x" * (2 * 1024**2 + 1))
    env.artifact("original_video/.native-caption-scan/partial-scan.json", b"x" * (2 * 1024**2 + 1))
    inventory = RetentionInventory(env.policy, env.state["snapshot"], clock=lambda: env.now[0]).scan()
    assert inventory.json_read == 0
    assert not inventory.unknown


def test_evidence_reference_is_protected_even_if_dal_terminal(setup_service):
    env = setup_service
    source = env.artifact()
    env.state["snapshot"]["path_references"].append({
        "path": str(source), "protected": False, "kind": "evidence", "youtube_ids": [SOURCE]})
    run = env.service.run(apply=True)
    assert not run["actions"]
    assert run["skipped"]["DB_REFERENCE"] == 1


def test_payload_open_or_referenced_blocks_expired_purge(setup_service):
    env = setup_service
    source = env.artifact()
    env.service.run(apply=True)
    receipt = env.service.store.list_receipts()[0]
    env.now[0] += 8 * DAY
    env.host.facts["open_references"] = [{"pid": 111, "path": receipt["payload"]}]
    assert not env.service.run(apply=True)["actions"]
    env.host.facts["open_references"] = []
    manifest = env.output / "manifest.json"
    manifest.write_text(json.dumps({"asset": receipt["payload"]}))
    run = env.service.run(apply=True)
    assert not run["actions"]
    assert run["skipped"]["PAYLOAD_MANIFEST_REFERENCE"] == 1
    manifest.unlink()
    env.state["snapshot"]["path_references"].append({
        "path": receipt["payload"], "protected": True, "youtube_ids": []})
    run = env.service.run(apply=True)
    assert not run["actions"]
    assert run["skipped"]["PAYLOAD_DB_REFERENCE"] == 1
    assert not source.exists()


def test_new_source_reference_restores_only_under_guard_and_never_overwrites(setup_service):
    env = setup_service
    source = env.artifact()
    env.service.run(apply=True)
    receipt = env.service.store.list_receipts()[0]
    env.state["snapshot"]["path_references"].append({
        "path": str(source), "protected": True, "youtube_ids": [SOURCE]})
    source.write_bytes(b"replacement")
    assert not env.service.run(apply=True)["actions"]
    assert source.read_bytes() == b"replacement"
    assert env.service.store.get_receipt(receipt["id"])["state"] == "QUARANTINED"
    source.unlink()
    run = env.service.run(apply=True)
    assert [row["action"] for row in run["actions"]] == ["RESTORED"]
    assert source.read_bytes() == b"old video"
    assert env.host.locks == 3


def test_fresh_unknown_database_prevents_action_after_preview(setup_service):
    env = setup_service
    source = env.artifact()
    def change_after_inventory(count):
        if count >= 2:
            env.state["snapshot"]["status"] = "UNKNOWN"
    env.state["on_read"] = change_after_inventory
    run = env.service.run(apply=True)
    assert not run["actions"]
    assert source.exists()
    assert env.host.locks == 1


def test_manifest_changed_at_final_lock_prevents_action(setup_service):
    env = setup_service
    source = env.artifact()
    manifest = env.output / "manifest.json"
    manifest.write_text("{}")
    env.host.on_lock = lambda: manifest.write_text(json.dumps({"asset": str(source)}))
    run = env.service.run(apply=True)
    assert not run["actions"]
    assert source.exists()


def test_action_and_byte_budgets_limit_real_changes_without_rescanning(setup_service):
    env = setup_service
    for index in range(4):
        env.artifact(f"{SOURCE}_{index}.mp4")
    env.service.policy = replace(env.policy, max_actions=2)
    run = env.service.run(apply=True)
    assert len(run["actions"]) == 2
    assert env.state["reads"] == 3  # 一次 inventory + 两次只读 DAL，未逐候选扫描。
    assert env.host.captures == 3
    env.service.policy = replace(env.policy, max_bytes=1)
    assert not env.service.run(apply=True)["actions"]


def test_hf_layout_requires_known_hash_frames_and_completion_marker(setup_service):
    env = setup_service
    good = env.output / "known-hf-frame-cache"
    hashdir = good / "hfcache-v7-2f687bf054a168a5"
    hashdir.mkdir(parents=True)
    (hashdir / "frame_0001.jpg").write_bytes(b"frame")
    (hashdir / ".hf-complete").write_bytes(b"")
    (good / ".hf-last-gc").write_bytes(b"")
    bad = env.output / "unknown-hf-frame-cache"
    bad.mkdir()
    (bad / "private.db").write_bytes(b"unknown")
    inventory = RetentionInventory(env.policy, env.state["snapshot"], clock=lambda: env.now[0]).scan()
    assert [(row["path"], row["kind"]) for row in inventory.candidates] == [
        (str(good), "hyperframes_frames")]


def test_owner_lookup_uses_ancestor_index_and_recent_tasks_remain(setup_service):
    env = setup_service
    source = env.artifact("generic/subdir/final.mp4")
    env.state["snapshot"]["path_references"] = [{
        "path": str(source.parent.parent), "protected": False, "youtube_ids": [SOURCE]}]
    inventory = RetentionInventory(env.policy, env.state["snapshot"], clock=lambda: env.now[0]).scan()
    assert inventory.owners(source) == [SOURCE]
    env.state["snapshot"]["sources"][SOURCE]["last_activity_at"] = env.now[0] - DAY
    assert not env.service.run(apply=True)["actions"]
    assert source.exists()
