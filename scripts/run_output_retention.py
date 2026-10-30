#!/usr/bin/env python
"""双七天 output 维护入口；默认预览，外部具名配置，失败保守保留。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-31 | Codex | 初始化、巡检、恢复及既有隔离批次的可恢复接管 |
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import plistlib
import os
import stat
import subprocess
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from config.output_retention import OutputRetentionPolicy
from video_processing.core.maintenance import MaintenanceGate
from video_processing.core.output_retention import OutputRetentionService, overlaps, write_json
from video_processing.core.output_retention_guard import RetentionHostGuard
from video_processing.core.output_retention_store import OutputRetentionStore


def plain(path):
    path = Path(path).absolute()
    if path.resolve() != path or any(x.is_symlink() for x in (path, *path.parents)):
        raise ValueError("PATH_LINK_REFUSED")
    return path


def guard_for(policy, *, store_root=None):
    # 使用既有准入控制，不改变维护状态，不读取凭据或触发数据库迁移。
    from config.settings import settings
    return RetentionHostGuard(policy.project_root, policy.output_root, policy.volume_root,
                              policy.volume_uuid, MaintenanceGate(settings.maintenance_state_path),
                              store_root=store_root or policy.store_root)


def initialize(control, volume):
    control, volume = plain(control), plain(volume)
    if (not volume.is_mount() or not PROJECT.is_relative_to(volume)
            or not control.is_relative_to(volume) or control.is_relative_to(PROJECT)
            or control == volume):
        raise ValueError("CONTROL_VOLUME_BOUNDARY_INVALID")
    if (control / "policy.json").exists():
        return {"state": "ALREADY_INITIALIZED", "policy": str(control / "policy.json")}
    if control.exists() and any(control.iterdir()):
        raise ValueError("REFUSE_NONEMPTY_CONTROL_DIRECTORY")
    result = subprocess.run(["/usr/sbin/diskutil", "info", "-plist", str(volume)],
                            capture_output=True, check=True, timeout=20)
    info = plistlib.loads(result.stdout)
    if (result.stderr or Path(info["MountPoint"]) != volume or not info.get("VolumeUUID")
            or PROJECT.stat().st_dev != volume.stat().st_dev
            or (PROJECT / "output").stat().st_dev != volume.stat().st_dev):
        raise ValueError("MOUNT_IDENTITY_UNKNOWN")
    control.mkdir(parents=True, exist_ok=True)
    store = OutputRetentionStore(PROJECT / "output", control / "store", create=True)
    policy = OutputRetentionPolicy(str(PROJECT), str(PROJECT / "output"), str(volume),
                                   info["VolumeUUID"], str(control / "store"), store.identity)
    guard_for(policy).verify_mount()
    write_json(control / "policy.json", policy.dump(), expected_device=store.identity["store_dev"])
    return {"state": "INITIALIZED", "policy": str(control / "policy.json")}


def import_legacy(service, receipt_path):
    """仅接管逐项列明且身份匹配的旧批次；保留实际隔离成功时间。"""
    receipt_path = plain(receipt_path)
    info = receipt_path.lstat()
    if (receipt_path.name != "receipt.json" or info.st_size > 1024**2
            or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid()):
        raise ValueError("LEGACY_RECEIPT_INVALID")
    raw = receipt_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if service.policy.legacy_approvals.get(str(receipt_path)) != digest:
        raise ValueError("LEGACY_BATCH_APPROVAL_MISSING")
    batch = json.loads(raw)
    if (not isinstance(batch, dict) or not isinstance(batch.get("moved"), list)
            or not isinstance(batch.get("completed_at"), str)
            or any(not isinstance(row, dict) or not
                   {"source", "destination", "device", "inode", "bytes"} <= row.keys()
                   for row in batch.get("moved", []))):
        raise ValueError("LEGACY_RECEIPT_INVALID")
    root = receipt_path.parent
    if (batch.get("state") != "COMPLETE" or batch.get("permanent_deletion") is not False
            or batch.get("project") != service.policy.project_root
            or batch.get("quarantine") != str(root)
            or not root.is_relative_to(Path(service.policy.volume_root))
            or root.is_relative_to(PROJECT)):
        raise ValueError("LEGACY_BATCH_NOT_CONFIRMED")
    completed = batch["completed_at"]
    service.guard.verify_mount()
    facts = guard_for(service.policy, store_root=root).capture()
    if facts["status"] != "OK":
        raise ValueError("LEGACY_HOST_UNKNOWN")
    with service.locked():
        existing = {row["source"]: row for row in service.store.list_receipts()
                    if row.get("metadata", {}).get("legacy_receipt_sha256") == digest}
        count = total = 0
        for item in batch["moved"]:
            source, destination = plain(item["source"]), plain(item["destination"])
            if str(source) in existing:
                continue
            relative = source.relative_to(Path(service.policy.output_root))
            if destination != root / "files" / "output" / relative:
                raise ValueError("LEGACY_PATH_MISMATCH")
            info = destination.lstat()
            if source.exists() or (info.st_dev, info.st_ino) != (item["device"], item["inode"]):
                raise ValueError("LEGACY_IDENTITY_CHANGED")
            for ref in facts["open_references"]:
                if overlaps(destination, ref["path"]):
                    raise ValueError("LEGACY_ITEM_IN_USE")
            # 只接管此次已审核的缓存类别，旧批次内其他历史证据不在范围内。
            if source.name.endswith("-hf-frame-cache"):
                kind = "hyperframes_frames"
            elif (source.name in {"browser", "pytest-tmp"} and source.parent.name == "sandbox"
                  and source.parent.parent.name.startswith("video-pytest-")
                  and "archived-test-temp" in relative.parts):
                kind = "archived_test_" + source.name
            else:
                raise ValueError("LEGACY_KIND_NOT_APPROVED")
            saved = service.store.register_existing(
                source, destination, completed, service.store.identity,
                metadata={"candidate": {"path": str(source), "kind": kind, "owner_ids": []},
                          "legacy_receipt_sha256": digest, "legacy_receipt": str(receipt_path)})
            existing[str(source)] = saved
            count += 1
            total += item["bytes"]
            write_json(service.control / "legacy-import.json", {
                "version": 1, "legacy_receipt_sha256": digest, "quarantined_at": completed,
                "items": {key: value["id"] for key, value in existing.items()}, "state": "IMPORTING"},
                expected_device=service.policy.store_identity["store_dev"])
        result = {"state": "COMPLETE", "imported_this_run": count, "bytes_this_run": total,
                  "total_items": len(existing), "quarantined_at": completed,
                  "legacy_receipt_sha256": digest,
                  "items": {key: value["id"] for key, value in existing.items()}}
        write_json(service.control / "legacy-import.json", result,
                   expected_device=service.policy.store_identity["store_dev"])
        return {key: value for key, value in result.items() if key != "items"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--control-dir", required=True, type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--volume", type=Path, required=True)
    run = commands.add_parser("run")
    run.add_argument("--apply", action="store_true")
    commands.add_parser("status")
    restore = commands.add_parser("restore")
    restore.add_argument("receipt_id")
    legacy = commands.add_parser("import-legacy")
    legacy.add_argument("receipt", type=Path)
    args = parser.parse_args(argv)
    control = plain(args.control_dir)
    if args.command == "init":
        result = initialize(control, args.volume)
    else:
        policy = OutputRetentionPolicy.load(control / "policy.json")
        if Path(policy.store_root).parent != control or Path(policy.project_root) != PROJECT:
            raise ValueError("CONTROL_BINDING_MISMATCH")
        host = guard_for(policy)
        host.verify_mount()
        service = OutputRetentionService(policy, host)
        if args.command == "run":
            result = service.run(apply=args.apply)
        elif args.command == "status":
            rows = service.store.list_receipts()
            result = {"policy": str(control / "policy.json"),
                      "receipts": dict(Counter(row["state"] for row in rows)),
                      "latest": json.loads((control / "latest.json").read_text())
                      if (control / "latest.json").exists() else None}
        elif args.command == "import-legacy":
            result = import_legacy(service, args.receipt)
        else:
            with service.locked(), host.exclusive_idle():
                facts = host.capture()
                row = service.store.get_receipt(args.receipt_id)
                if facts["status"] != "OK" or facts["busy_processes"]:
                    raise ValueError("RESTORE_HOST_BUSY_OR_UNKNOWN")
                if any(overlaps(row["payload"], ref["path"]) for ref in facts["open_references"]):
                    raise ValueError("RESTORE_ITEM_IN_USE")
                saved = service.store.restore(args.receipt_id)
                result = {"id": saved["id"], "state": saved["state"], "source": saved["source"]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(json.dumps({"state": "BLOCKED", "reason": type(error).__name__,
                          "detail": str(error)[:200]}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
