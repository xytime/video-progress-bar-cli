"""具名策略与运维入口的安全边界；真实临时文件树，不调用宿主命令。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-31 | Codex | 覆盖双七天策略、路径准入、初始化及旧隔离回执审批绑定 |
"""
from dataclasses import replace
from datetime import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import subprocess
from types import SimpleNamespace

import pytest

from config.output_retention import OutputRetentionPolicy
from video_processing.core.output_retention import OutputRetentionService
from video_processing.core.output_retention_store import OutputRetentionStore


ROOT = Path(__file__).resolve().parents[2]
VOLUME_UUID = "F09BC95D-B996-4971-8F99-9780C25FCC89"


@pytest.fixture
def cli():
    spec = importlib.util.spec_from_file_location("output_retention_cli_under_test", ROOT / "scripts/run_output_retention.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def policy(tmp_path):
    volume = tmp_path.resolve()
    project = volume / "project"
    output = project / "output"
    output.mkdir(parents=True)
    store = OutputRetentionStore(output, volume / "control/store", create=True)
    return OutputRetentionPolicy(str(project), str(output), str(volume), VOLUME_UUID,
                                 str(store.store_root), store.identity)


def save_policy(policy, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(policy.dump()))


def test_policy_roundtrip_does_not_read_environment_or_change_boundaries(policy, monkeypatch):
    monkeypatch.setenv("OUTPUT_RETENTION_IDLE_DAYS", "0")
    path = Path(policy.store_root).parent / "policy.json"
    save_policy(policy, path)
    loaded = OutputRetentionPolicy.load(path)
    assert loaded == policy
    assert loaded.idle_days == loaded.observation_days == 7


@pytest.mark.parametrize("field", ["idle_days", "observation_days"])
@pytest.mark.parametrize("value", [0, 6, True, 7.0, "7"])
def test_policy_rejects_shorter_or_untyped_seven_day_intervals(policy, field, value):
    with pytest.raises(ValueError, match="SEVEN_DAYS"):
        replace(policy, **{field: value}).validate()


def test_policy_allows_longer_independent_observation_period(policy):
    saved = replace(policy, idle_days=8, observation_days=14).validate()
    assert saved.idle_days == 8 and saved.observation_days == 14


@pytest.mark.parametrize("field", ["scan_entries", "json_bytes", "max_tree_entries", "max_actions", "max_bytes", "max_seconds"])
def test_policy_rejects_invalid_action_and_scan_budgets(policy, field):
    with pytest.raises(ValueError, match="BUDGET_INVALID"):
        replace(policy, **{field: 0}).validate()


@pytest.mark.parametrize("change", ["relative", "different_output", "store_in_project", "store_at_volume", "store_contains_project", "project_outside_volume"])
def test_policy_rejects_paths_that_break_isolation(policy, change):
    project, volume = Path(policy.project_root), Path(policy.volume_root)
    values = {
        "relative": {"project_root": "project"},
        "different_output": {"output_root": str(project / "other-output")},
        "store_in_project": {"store_root": str(project / "quarantine")},
        "store_at_volume": {"store_root": str(volume)},
        "store_contains_project": {"project_root": str(volume / "parent/project"),
                                   "output_root": str(volume / "parent/project/output"), "store_root": str(volume / "parent")},
        "project_outside_volume": {"project_root": str(volume.parent / "other-project"),
                                   "output_root": str(volume.parent / "other-project/output")},
    }[change]
    with pytest.raises(ValueError):
        replace(policy, **values).validate()


def test_policy_rejects_symlink_ancestor_even_for_same_real_directory(policy):
    volume = Path(policy.volume_root)
    alias = volume / "project-alias"
    alias.symlink_to(policy.project_root, target_is_directory=True)
    with pytest.raises(ValueError, match="PATH_UNSAFE"):
        replace(policy, project_root=str(alias), output_root=str(alias / "output")).validate()


@pytest.mark.parametrize("payload", [[], {"unexpected_option": 1}, {"version": 1}])
def test_policy_load_normalizes_invalid_document_errors(policy, payload):
    path = Path(policy.store_root).parent / "invalid-policy.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        OutputRetentionPolicy.load(path)


def test_policy_load_refuses_a_linked_policy_document(policy):
    control = Path(policy.store_root).parent
    save_policy(policy, control / "original.json")
    (control / "policy.json").symlink_to(control / "original.json")
    with pytest.raises(ValueError, match="LINK_REFUSED"):
        OutputRetentionPolicy.load(control / "policy.json")


def test_cli_init_refuses_project_control_before_creating_anything(cli, policy, monkeypatch):
    monkeypatch.setattr(cli, "PROJECT", Path(policy.project_root))
    inside = Path(policy.project_root) / "retention-control"
    with pytest.raises(ValueError, match="BOUNDARY"):
        cli.main(["--control-dir", str(inside), "init", "--volume", "/"])
    assert not inside.exists()


@pytest.mark.parametrize("metadata", [{"MountPoint": "/"}, {"MountPoint": "/", "VolumeUUID": ""},
                                       {"MountPoint": "/unexpected", "VolumeUUID": VOLUME_UUID}])
def test_init_rejects_unknown_volume_identity_before_store_creation(cli, policy, monkeypatch, metadata):
    monkeypatch.setattr(cli, "PROJECT", Path(policy.project_root))
    monkeypatch.setattr(cli.subprocess, "run", lambda args, **kwargs: subprocess.CompletedProcess(
        args, 0, plistlib.dumps(metadata), b""))
    control = Path(policy.volume_root) / "new-control"
    with pytest.raises((ValueError, RuntimeError)):
        cli.initialize(control, Path("/"))
    assert not control.exists()


def test_cli_control_binding_checked_before_host_or_store_access(cli, policy, monkeypatch):
    monkeypatch.setattr(cli, "PROJECT", Path(policy.project_root))
    wrong = Path(policy.volume_root) / "unrelated-control"
    save_policy(policy, wrong / "policy.json")
    with pytest.raises(ValueError, match="CONTROL_BINDING_MISMATCH"):
        cli.main(["--control-dir", str(wrong), "status"])
    assert not (wrong / "latest.json").exists()


def test_cli_run_defaults_to_preview_and_apply_is_explicit(cli, policy, monkeypatch, capsys):
    monkeypatch.setattr(cli, "PROJECT", Path(policy.project_root))
    calls = []
    host = SimpleNamespace(verify_mount=lambda: calls.append("mount"))
    service = SimpleNamespace(run=lambda **kwargs: calls.append(kwargs) or {"state": "CHECKED"})
    monkeypatch.setattr(cli, "guard_for", lambda current: host)
    monkeypatch.setattr(cli, "OutputRetentionService", lambda current, guard: service)
    control = Path(policy.store_root).parent
    save_policy(policy, control / "policy.json")
    assert cli.main(["--control-dir", str(control), "run"]) == 0
    assert cli.main(["--control-dir", str(control), "run", "--apply"]) == 0
    assert calls == ["mount", {"apply": False}, "mount", {"apply": True}]
    assert capsys.readouterr().out.count('"state": "CHECKED"') == 2


class IdleHost:
    def verify_mount(self):
        return {"volume_uuid": VOLUME_UUID}

    def capture(self):
        return {"status": "OK", "open_references": [], "busy_processes": [], "tracked_paths": []}


@pytest.fixture
def legacy(cli, policy, monkeypatch):
    monkeypatch.setattr(cli, "PROJECT", Path(policy.project_root))
    host = IdleHost()
    monkeypatch.setattr(cli, "guard_for", lambda *args, **kwargs: host)
    source = Path(policy.output_root) / "example-hf-frame-cache"
    batch_root = Path(policy.volume_root) / "old-reviewed-batch"
    destination = batch_root / "files/output" / source.name
    destination.mkdir(parents=True)
    (destination / "frame.jpg").write_bytes(b"synthetic-frame")
    info = destination.stat()
    receipt = batch_root / "receipt.json"
    document = {"state": "COMPLETE", "permanent_deletion": False, "project": policy.project_root,
                "quarantine": str(batch_root), "completed_at": "2020-01-01T01:02:03+00:00",
                "moved": [{"source": str(source), "destination": str(destination),
                           "device": info.st_dev, "inode": info.st_ino, "bytes": 15}]}
    receipt.write_text(json.dumps(document))
    return SimpleNamespace(cli=cli, policy=policy, host=host, source=source,
                           destination=destination, receipt=receipt, document=document)


def service_for(case, *, approve=False):
    policy = case.policy
    if approve:
        digest = hashlib.sha256(case.receipt.read_bytes()).hexdigest()
        policy = replace(policy, legacy_approvals={str(case.receipt): digest})
    return OutputRetentionService(policy, case.host)


def test_legacy_import_rejects_self_declared_old_receipt_without_approval(legacy):
    service = service_for(legacy)
    with pytest.raises((ValueError, RuntimeError)):
        legacy.cli.import_legacy(service, legacy.receipt)
    assert legacy.destination.exists() and not legacy.source.exists()
    assert service.store.list_receipts() == []


def test_legacy_import_rejects_receipt_changed_after_digest_approval(legacy):
    service = service_for(legacy, approve=True)
    legacy.document["completed_at"] = "2000-01-01T00:00:00+00:00"
    legacy.receipt.write_text(json.dumps(legacy.document))
    with pytest.raises((ValueError, RuntimeError)):
        legacy.cli.import_legacy(service, legacy.receipt)
    assert legacy.destination.exists() and service.store.list_receipts() == []


def test_legacy_import_rejects_hardlinked_receipt_even_when_digest_approved(legacy):
    service = service_for(legacy, approve=True)
    os.link(legacy.receipt, legacy.receipt.parent / "second-receipt.json")
    with pytest.raises((ValueError, RuntimeError)):
        legacy.cli.import_legacy(service, legacy.receipt)
    assert legacy.destination.exists() and service.store.list_receipts() == []


def test_legacy_import_rejects_nonobject_receipt_with_bounded_error(legacy):
    legacy.receipt.write_text("[]")
    service = service_for(legacy, approve=True)
    with pytest.raises(ValueError):
        legacy.cli.import_legacy(service, legacy.receipt)
    assert legacy.destination.exists() and service.store.list_receipts() == []


def test_legacy_import_checks_destination_identity_before_moving(legacy):
    legacy.document["moved"][0]["inode"] += 1
    legacy.receipt.write_text(json.dumps(legacy.document))
    service = service_for(legacy, approve=True)
    with pytest.raises((ValueError, RuntimeError)):
        legacy.cli.import_legacy(service, legacy.receipt)
    assert legacy.destination.exists() and service.store.list_receipts() == []


def test_trusted_legacy_import_preserves_actual_observation_start_and_is_idempotent(legacy):
    service = service_for(legacy, approve=True)
    first = legacy.cli.import_legacy(service, legacy.receipt)
    assert first["state"] == "COMPLETE" and first["imported_this_run"] == 1
    rows = service.store.list_receipts()
    assert len(rows) == 1 and rows[0]["state"] == "QUARANTINED"
    assert rows[0]["quarantined_at"] == datetime.fromisoformat(legacy.document["completed_at"]).timestamp()
    assert Path(rows[0]["payload"]).joinpath("frame.jpg").read_bytes() == b"synthetic-frame"
    assert not legacy.destination.exists() and not legacy.source.exists()
    second = legacy.cli.import_legacy(service, legacy.receipt)
    assert second["imported_this_run"] == 0 and second["total_items"] == 1
    assert len(service.store.list_receipts()) == 1
