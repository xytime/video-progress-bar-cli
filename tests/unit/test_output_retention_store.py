"""隔离库的真实文件系统安全边界与中断恢复测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-31 | Codex | 覆盖七天保留、外部软链接、身份改变、冲突、篡改及崩溃恢复。 |
"""

import json
import os
from pathlib import Path

import pytest

import video_processing.core.output_retention_store as store_module

from video_processing.core.output_retention_store import (
    MIN_QUARANTINE_SECONDS,
    OutputRetentionStore,
    RetentionBudgetExceeded,
    RetentionStoreError,
)


class Crash(BaseException):
    """模拟进程被终止，跳过普通异常处理。"""


@pytest.fixture
def store_case(tmp_path):
    base = tmp_path.resolve()
    output = base / "output"
    output.mkdir()
    now = [1_800_000_000.0]
    store = OutputRetentionStore(output, base / "owned-store", create=True, clock=lambda: now[0])
    return store, output, now


def _payload(store, receipt):
    return store.store_root / "items" / receipt["id"] / "payload"


def _cache(output, name="cache"):
    cache = output / name
    cache.mkdir()
    (cache / "frame.jpg").write_bytes(b"synthetic-frame")
    return cache


def test_purge_never_follows_tree_symlinks_and_accepts_fifo(store_case):
    store, output, now = store_case
    outside = output.parent / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("must survive")
    cache = _cache(output)
    (cache / "outside-link").symlink_to(outside, target_is_directory=True)
    os.mkfifo(cache / "pipe")
    receipt = store.quarantine(cache, metadata={"owner": "synthetic-cache"})
    assert receipt["snapshot"]["symlinks"] == 1
    assert receipt["snapshot"]["other_entries"] == 1
    assert not cache.exists()
    now[0] += MIN_QUARANTINE_SECONDS
    purged = store.purge(receipt["id"])
    assert purged["state"] == "PURGED"
    assert not _payload(store, receipt).exists()
    assert (outside / "keep.txt").read_text() == "must survive"
    assert store.get_receipt(receipt["id"])["metadata"]["owner"] == "synthetic-cache"


def test_old_source_mtime_does_not_shorten_quarantine(store_case):
    store, output, now = store_case
    old = output / "old.mp4"
    old.write_bytes(b"video")
    os.utime(old, (1, 1))
    receipt = store.quarantine(old)
    assert receipt["quarantined_at"] == now[0]
    assert receipt["snapshot"]["kind"] == "file"
    now[0] += MIN_QUARANTINE_SECONDS - 1
    with pytest.raises(RetentionStoreError, match="七天"):
        store.purge(receipt["id"])
    assert _payload(store, receipt).read_bytes() == b"video"
    assert store.get_receipt(receipt["id"])["state"] == "QUARANTINED"


def test_restore_regular_file_and_refuse_original_path_conflict(store_case):
    store, output, _ = store_case
    source = output / "final.mp4"
    source.write_bytes(b"approved-video")
    receipt = store.quarantine(source)
    source.write_bytes(b"new-output")
    with pytest.raises(RetentionStoreError, match="冲突"):
        store.restore(receipt["id"])
    assert source.read_bytes() == b"new-output"
    assert _payload(store, receipt).read_bytes() == b"approved-video"
    source.unlink()
    restored = store.restore(receipt["id"])
    assert restored["state"] == "RESTORED"
    assert source.read_bytes() == b"approved-video"


def test_restore_kernel_exclusive_rename_preserves_racing_new_file(store_case, monkeypatch):
    store, output, _ = store_case
    source = output / "final.mp4"
    source.write_bytes(b"approved-video")
    receipt = store.quarantine(source)
    rename = store_module._rename_noreplace

    def new_output_arrives(src_fd, src, dst_fd, dst):
        source.write_bytes(b"concurrent-new-output")
        return rename(src_fd, src, dst_fd, dst)

    monkeypatch.setattr(store_module, "_rename_noreplace", new_output_arrives)
    with pytest.raises(RetentionStoreError):
        store.restore(receipt["id"])
    assert source.read_bytes() == b"concurrent-new-output"
    assert _payload(store, receipt).read_bytes() == b"approved-video"


def test_unknown_and_missing_receipt_cannot_authorize_purge(store_case):
    store, output, now = store_case
    receipt = store.quarantine(_cache(output))
    now[0] += MIN_QUARANTINE_SECONDS
    with pytest.raises(RetentionStoreError):
        store.purge("a" * 32)
    path = store.store_root / "items" / receipt["id"] / "receipt.json"
    path.unlink()
    with pytest.raises(RetentionStoreError, match="缺失"):
        store.purge(receipt["id"])
    assert (_payload(store, receipt) / "frame.jpg").exists()


def test_receipt_tampering_is_rejected(store_case):
    store, output, now = store_case
    receipt = store.quarantine(_cache(output))
    path = store.store_root / "items" / receipt["id"] / "receipt.json"
    body = json.loads(path.read_text())
    body["identity"]["output_inode"] += 1
    path.write_text(json.dumps(body))
    now[0] += MIN_QUARANTINE_SECONDS
    with pytest.raises(RetentionStoreError, match="身份"):
        store.purge(receipt["id"])
    assert _payload(store, receipt).exists()


def test_replaced_output_root_identity_stops_existing_and_reopened_store(store_case):
    store, output, _ = store_case
    receipt = store.quarantine(_cache(output))
    output.rename(output.with_name("old-output"))
    output.mkdir()
    with pytest.raises(RetentionStoreError, match="identity"):
        store.get_receipt(receipt["id"])
    with pytest.raises(RetentionStoreError, match="identity"):
        OutputRetentionStore(output, store.store_root, expected_identity=store.identity)
    assert _payload(store, receipt).exists()


def test_refuse_symlink_ancestors_and_root_symlink(store_case):
    store, output, _ = store_case
    outside = output.parent / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep")
    (output / "alias").symlink_to(outside, target_is_directory=True)
    with pytest.raises(RetentionStoreError):
        store.quarantine(output / "alias" / "keep.txt")
    with pytest.raises(RetentionStoreError, match="根条目"):
        store.quarantine(output / "alias")
    assert (outside / "keep.txt").read_text() == "keep"


def test_tree_mutation_even_with_restored_mtime_blocks_purge(store_case):
    store, output, now = store_case
    receipt = store.quarantine(_cache(output))
    frame = _payload(store, receipt) / "frame.jpg"
    before = frame.stat()
    frame.write_bytes(b"changed-content")
    os.utime(frame, ns=(before.st_atime_ns, before.st_mtime_ns))
    now[0] += MIN_QUARANTINE_SECONDS
    with pytest.raises(RetentionStoreError, match="元数据"):
        store.purge(receipt["id"])
    assert frame.read_bytes() == b"changed-content"
    assert store.get_receipt(receipt["id"])["state"] == "BLOCKED"


def test_replaced_payload_symlink_is_never_followed(store_case):
    store, output, now = store_case
    receipt = store.quarantine(_cache(output))
    payload = _payload(store, receipt)
    retained = payload.with_name("retained")
    payload.rename(retained)
    outside = output.parent / "outside"
    outside.mkdir()
    (outside / "keep").write_text("safe")
    payload.symlink_to(outside, target_is_directory=True)
    now[0] += MIN_QUARANTINE_SECONDS
    # Unknown item-directory entries also fail closed before touching payload.
    with pytest.raises(RetentionStoreError):
        store.purge(receipt["id"])
    assert (outside / "keep").read_text() == "safe"
    assert (retained / "frame.jpg").exists()


def test_preview_budget_refuses_move_and_preserves_source(store_case):
    store, output, _ = store_case
    cache = _cache(output)
    limited = OutputRetentionStore(output, store.store_root, expected_identity=store.identity, max_entries=1)
    with pytest.raises(RetentionBudgetExceeded):
        limited.quarantine(cache)
    assert (cache / "frame.jpg").exists()
    assert store.list_receipts() == []


def test_expected_signature_prevents_preview_to_move_drift(store_case):
    store, output, _ = store_case
    cache = _cache(output)
    preview = store.preview(cache)
    (cache / "new.txt").write_text("arrived after reference check")
    with pytest.raises(RetentionStoreError, match="预览"):
        store.quarantine(cache, expected_signature=preview["metadata_signature"])
    assert cache.exists()
    assert store.list_receipts() == []


def test_register_existing_preserves_actual_legacy_isolation_clock(store_case):
    store, output, now = store_case
    legacy = output.parent / "legacy-cache"
    legacy.mkdir()
    (legacy / "frame.jpg").write_bytes(b"frame")
    when = now[0] - MIN_QUARANTINE_SECONDS - 10
    receipt = store.register_existing(output / "original-cache", legacy, when, store.identity,
                                      metadata={"legacy_receipt": "explicit-import"})
    assert receipt["quarantined_at"] == when
    assert not legacy.exists()
    assert store.purge(receipt["id"])["state"] == "PURGED"


def test_register_existing_rejects_foreign_identity_and_source_conflict(store_case):
    store, output, now = store_case
    legacy = output.parent / "legacy-cache"
    legacy.mkdir()
    source = _cache(output)
    with pytest.raises(RetentionStoreError, match="identity"):
        store.register_existing(source, legacy, now[0], {**store.identity, "store_inode": 1})
    with pytest.raises(RetentionStoreError, match="源路径"):
        store.register_existing(source, legacy, now[0], store.identity)
    assert legacy.exists() and source.exists()


def test_crash_after_rename_recovers_without_backdating_quarantine(store_case, monkeypatch):
    store, output, now = store_case
    cache = _cache(output)
    save = store._save

    def interrupted_save(fd, receipt):
        if receipt["state"] == "QUARANTINED":
            raise Crash()
        save(fd, receipt)

    monkeypatch.setattr(store, "_save", interrupted_save)
    with pytest.raises(Crash):
        store.quarantine(cache)
    receipt = store.list_receipts()[0]
    assert receipt["state"] == "MOVING"
    assert not cache.exists() and _payload(store, receipt).exists()
    now[0] += 100
    reopened = OutputRetentionStore(output, store.store_root, expected_identity=store.identity, clock=lambda: now[0])
    recovered = reopened.recover(receipt["id"])
    assert recovered["state"] == "QUARANTINED"
    assert recovered["quarantined_at"] == now[0]


def test_crash_mid_purge_is_blocked_without_automatic_continuation(store_case, monkeypatch):
    store, output, now = store_case
    cache = _cache(output)
    (cache / "other.txt").write_text("retain after interruption")
    receipt = store.quarantine(cache)
    now[0] += MIN_QUARANTINE_SECONDS

    def interrupted_unlink(parent_fd, name, snapshot):
        (_payload(store, receipt) / "frame.jpg").unlink()
        raise Crash()

    monkeypatch.setattr(store, "_unlink_snapshot", interrupted_unlink)
    with pytest.raises(Crash):
        store.purge(receipt["id"])
    assert store.get_receipt(receipt["id"])["state"] == "PURGING"
    recovered = store.recover(receipt["id"])
    assert recovered["state"] == "BLOCKED"
    assert (_payload(store, receipt) / "other.txt").read_text() == "retain after interruption"
    with pytest.raises(RetentionStoreError):
        store.purge(receipt["id"])


def test_crash_after_restore_rename_recovers_as_restored(store_case, monkeypatch):
    store, output, _ = store_case
    source = _cache(output)
    receipt = store.quarantine(source)
    save = store._save

    def interrupted_save(fd, body):
        if body["state"] == "RESTORED":
            raise Crash()
        save(fd, body)

    monkeypatch.setattr(store, "_save", interrupted_save)
    with pytest.raises(Crash):
        store.restore(receipt["id"])
    reopened = OutputRetentionStore(output, store.store_root, expected_identity=store.identity)
    assert reopened.recover(receipt["id"])["state"] == "RESTORED"
    assert (source / "frame.jpg").read_bytes() == b"synthetic-frame"


def test_reopen_requires_expected_identity_and_public_marker_has_no_token(store_case):
    store, output, _ = store_case
    with pytest.raises(RetentionStoreError, match="identity"):
        OutputRetentionStore(output, store.store_root)
    assert "token" not in store.marker
    assert store.marker["identity"] == store.identity
    assert OutputRetentionStore(output, store.store_root, expected_identity=store.identity).list_receipts() == []
