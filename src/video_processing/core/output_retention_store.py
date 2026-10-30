"""输出产物的同卷可恢复隔离；仅处理调用者明确指定的路径。

源产物的闲置年龄、业务归属和引用检查属于调用层。这里强制校验目录身份、
工具所有权与完整树元数据，并从隔离成功时间起至少保留七天。中断的清除不
自动续删；所有路径操作使用目录 fd，不跟随软链接。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-31 | Codex | 新增有持久收据、身份检查及七天保留门槛的文件系统隔离库。 |
"""

from __future__ import annotations

import contextlib
import ctypes
import datetime as dt
import fcntl
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import stat
import sys
import time
from typing import Any, Callable, Mapping
import uuid


MIN_QUARANTINE_SECONDS = 7 * 24 * 60 * 60
STATES = frozenset({"PLANNED", "MOVING", "QUARANTINED", "PURGING", "PURGED", "RESTORED", "BLOCKED"})
_TOOL = "video-output-retention-v1"
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_SEARCH_FLAGS = ((getattr(os, "O_SEARCH", 0x40000000 | os.O_DIRECTORY) if sys.platform == "darwin"
                  else getattr(os, "O_PATH", os.O_RDONLY) | os.O_DIRECTORY) | os.O_NOFOLLOW | os.O_CLOEXEC)
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK


class RetentionStoreError(RuntimeError):
    """安全条件不满足；调用者不得据此自动放宽门槛或另行删除。"""


class RetentionBudgetExceeded(RetentionStoreError):
    """元数据扫描超过明确预算。"""


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _absolute(path: str | Path) -> Path:
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise RetentionStoreError("必须提供无 .. 的绝对路径")
    return path


@contextlib.contextmanager
def _directory(path: Path, *, create: bool = False):
    """逐级 O_NOFOLLOW 打开；不通过 resolve 隐式接受软链接祖先。"""
    parts = _absolute(path).parts[1:]
    fd = os.open("/", _SEARCH_FLAGS if parts else _DIR_FLAGS)
    try:
        for index, part in enumerate(parts):
            if create:
                try:
                    os.stat(part, dir_fd=fd, follow_symlinks=False)
                except FileNotFoundError:
                    os.mkdir(part, 0o700, dir_fd=fd)
                    # 只有创建发生的可写父目录需要读取/fsync，祖先只请求 search。
                    sync_fd = os.open(".", _DIR_FLAGS, dir_fd=fd)
                    try:
                        os.fsync(sync_fd)
                    finally:
                        os.close(sync_fd)
            nxt = os.open(part, _DIR_FLAGS if index == len(parts) - 1 else _SEARCH_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = nxt
        yield fd
    except OSError as exc:
        raise RetentionStoreError(f"目录不安全或不可访问：{path}") from exc
    finally:
        os.close(fd)


def _exists(fd: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=fd, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False


def _rename_noreplace(source_fd: int, source: str, destination_fd: int, destination: str) -> None:
    """内核保证目标不存在；尤其不能覆盖恢复检查后新出现的业务文件。"""
    libc = ctypes.CDLL(None, use_errno=True)
    symbol, flag = ("renameatx_np", 0x4) if sys.platform == "darwin" else ("renameat2", 0x1)
    if sys.platform not in {"darwin", "linux"} or not hasattr(libc, symbol):
        raise RetentionStoreError("当前平台缺少原子不覆盖 rename，拒绝移动")
    rename = getattr(libc, symbol)
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(source_fd, os.fsencode(source), destination_fd, os.fsencode(destination), flag) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def _read_json(fd: int, name: str) -> dict:
    try:
        file_fd = os.open(name, _FILE_FLAGS, dir_fd=fd)
    except OSError as exc:
        raise RetentionStoreError("收据/所有权文件缺失或不安全") from exc
    try:
        info = os.fstat(file_fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 1024 * 1024 or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise RetentionStoreError("收据/所有权文件必须是本用户的单链接普通小文件")
        with os.fdopen(file_fd, "rb", closefd=False) as handle:
            value = json.load(handle)
        if not isinstance(value, dict):
            raise RetentionStoreError("收据不是对象")
        return value
    except (ValueError, UnicodeError) as exc:
        raise RetentionStoreError("收据 JSON 无效") from exc
    finally:
        os.close(file_fd)


def _write_json(fd: int, name: str, value: dict) -> None:
    temporary = ".writing-" + uuid.uuid4().hex
    file_fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
    try:
        with os.fdopen(file_fd, "wb", closefd=False) as handle:
            handle.write(_json_bytes(value))
            handle.flush()
            os.fsync(file_fd)
        os.replace(temporary, name, src_dir_fd=fd, dst_dir_fd=fd)
        os.fsync(fd)
    finally:
        os.close(file_fd)
        if _exists(fd, temporary):
            os.unlink(temporary, dir_fd=fd)


def _metadata(info: os.stat_result, *, ignore_ctime: bool = False) -> tuple:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns,
            None if ignore_ctime else info.st_ctime_ns, info.st_nlink)


def _timestamp(value: float | str) -> float:
    if isinstance(value, str):
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise RetentionStoreError("历史隔离时间必须包含时区")
        value = parsed.timestamp()
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise RetentionStoreError("隔离时间无效")
    return value


class OutputRetentionStore:
    """显式创建/重新打开一个受控 store；不发现或接管任意 staging 目录。"""

    def __init__(self, output_root: str | Path, store_root: str | Path, *,
                 expected_identity: Mapping[str, Any] | None = None,
                 clock: Callable[[], float] = time.time, max_entries: int = 100_000,
                 max_scan_seconds: float = 30.0, create: bool = False):
        self.output_root, self.store_root = _absolute(output_root), _absolute(store_root)
        if self.output_root == self.store_root or self.output_root in self.store_root.parents or self.store_root in self.output_root.parents:
            raise RetentionStoreError("源根目录和隔离根目录必须互不包含")
        if max_entries < 1 or max_scan_seconds <= 0:
            raise RetentionStoreError("扫描预算必须为正")
        if expected_identity is None and not create:
            raise RetentionStoreError("重新打开 store 必须提供预期 identity")
        self.clock, self.max_entries, self.max_scan_seconds = clock, max_entries, max_scan_seconds
        with _directory(self.output_root) as output_fd, _directory(self.store_root, create=create) as root_fd:
            out, root = os.fstat(output_fd), os.fstat(root_fd)
            if out.st_dev != root.st_dev:
                raise RetentionStoreError("仅允许同卷隔离")
            self.identity = {"output_root": str(self.output_root), "output_dev": out.st_dev, "output_inode": out.st_ino,
                             "store_root": str(self.store_root), "store_dev": root.st_dev, "store_inode": root.st_ino}
            if expected_identity is not None and dict(expected_identity) != self.identity:
                raise RetentionStoreError("目录或卷 identity 已改变")
            if not _exists(root_fd, "owner.json"):
                if not create or os.listdir(root_fd):
                    raise RetentionStoreError("拒绝接管没有所有权标记的非空目录")
                marker = {"tool": _TOOL, "store_id": uuid.uuid4().hex, "identity": self.identity,
                          "token": uuid.uuid4().hex + uuid.uuid4().hex}
                os.mkdir("items", 0o700, dir_fd=root_fd)
                _write_json(root_fd, "owner.json", marker)
            elif expected_identity is None:
                raise RetentionStoreError("既有 store 不允许省略 expected_identity")
            self._marker = _read_json(root_fd, "owner.json")
            self._verify_marker(root_fd)

    @property
    def marker(self) -> dict:
        """仅返回可公开的绑定信息，不暴露收据校验 token。"""
        return json.loads(_json_bytes({key: value for key, value in self._marker.items() if key != "token"}))

    def _verify_marker(self, root_fd: int) -> None:
        marker = _read_json(root_fd, "owner.json")
        if (marker != self._marker or marker.get("tool") != _TOOL or marker.get("identity") != self.identity
                or not isinstance(marker.get("token"), str) or len(marker["token"]) != 64):
            raise RetentionStoreError("工具所有权标记不匹配")
        current = os.fstat(root_fd)
        if (current.st_dev, current.st_ino) != (self.identity["store_dev"], self.identity["store_inode"]):
            raise RetentionStoreError("隔离根目录 identity 改变")
        with _directory(self.output_root) as output_fd:
            current = os.fstat(output_fd)
            if (current.st_dev, current.st_ino) != (self.identity["output_dev"], self.identity["output_inode"]):
                raise RetentionStoreError("源根目录 identity 改变")

    @contextlib.contextmanager
    def _locked(self):
        with _directory(self.store_root) as root_fd:
            self._verify_marker(root_fd)
            lock_fd = os.open(".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=root_fd)
            try:
                lock_info = os.fstat(lock_fd)
                if not stat.S_ISREG(lock_info.st_mode) or lock_info.st_nlink != 1 or lock_info.st_uid != os.getuid():
                    raise RetentionStoreError("store 锁文件不安全")
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
                self._verify_marker(root_fd)
                items_fd = os.open("items", _DIR_FLAGS, dir_fd=root_fd)
                try:
                    yield items_fd
                finally:
                    os.close(items_fd)
            finally:
                os.close(lock_fd)

    def _source(self, source: str | Path) -> Path:
        source = Path(source)
        if not source.is_absolute():
            source = self.output_root / source
        source = _absolute(source)
        if source == self.output_root or self.output_root not in source.parents:
            raise RetentionStoreError("源路径必须严格位于 output 根目录内")
        return source

    def _names(self, fd: int, *, remaining: int | None = None, deadline: float | None = None) -> list[str]:
        names = []
        limit = self.max_entries if remaining is None else remaining
        with os.scandir(fd) as entries:
            for entry in entries:
                if len(names) >= limit or (deadline is not None and time.monotonic() > deadline):
                    raise RetentionBudgetExceeded("目录枚举超出预算")
                names.append(entry.name)
        return sorted(names)

    def _snapshot(self, parent_fd: int, name: str) -> dict:
        """有界、无内容读取的全树指纹；原始记录只在内存中用于安全 unlink。"""
        started = time.monotonic()
        records, move_records = [], []
        stats = {"files": 0, "directories": 0, "symlinks": 0, "other_entries": 0, "bytes": 0, "maxmtime": 0.0}
        root_info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if not (stat.S_ISDIR(root_info.st_mode) or stat.S_ISREG(root_info.st_mode)):
            raise RetentionStoreError("隔离根条目必须为真实目录或普通文件")

        def walk(fd, child, relative, depth):
            if len(records) >= self.max_entries or time.monotonic() - started > self.max_scan_seconds or depth > 128:
                raise RetentionBudgetExceeded("全树元数据扫描超出预算")
            before = os.stat(child, dir_fd=fd, follow_symlinks=False)
            if before.st_dev != self.identity["store_dev"]:
                raise RetentionStoreError("树内出现跨卷条目")
            if not (stat.S_ISDIR(before.st_mode) or stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode) or stat.S_ISFIFO(before.st_mode)):
                raise RetentionStoreError("树内出现不支持的特殊条目")
            link_hash = hashlib.sha256(os.fsencode(os.readlink(child, dir_fd=fd))).hexdigest() if stat.S_ISLNK(before.st_mode) else None
            records.append((relative, _metadata(before), link_hash))
            move_records.append((relative, _metadata(before, ignore_ctime=(relative == ".")), link_hash))
            stats["maxmtime"] = max(stats["maxmtime"], before.st_mtime)
            if stat.S_ISDIR(before.st_mode):
                stats["directories"] += 1
                directory_fd = os.open(child, _DIR_FLAGS, dir_fd=fd)
                try:
                    if _metadata(os.fstat(directory_fd)) != _metadata(before):
                        raise RetentionStoreError("扫描期间目录 identity 改变")
                    for entry in self._names(directory_fd, remaining=self.max_entries - len(records),
                                             deadline=started + self.max_scan_seconds):
                        walk(directory_fd, entry, entry if relative == "." else relative + "/" + entry, depth + 1)
                    if _metadata(os.fstat(directory_fd)) != _metadata(before):
                        raise RetentionStoreError("扫描期间目录发生变化")
                finally:
                    os.close(directory_fd)
            elif stat.S_ISREG(before.st_mode):
                stats["files"] += 1
                stats["bytes"] += before.st_size
            elif stat.S_ISLNK(before.st_mode):
                stats["symlinks"] += 1
            else:
                stats["other_entries"] += 1
            if _metadata(os.stat(child, dir_fd=fd, follow_symlinks=False)) != _metadata(before):
                raise RetentionStoreError("扫描期间条目发生变化")

        walk(parent_fd, name, ".", 0)
        return {**stats, "kind": "directory" if stat.S_ISDIR(root_info.st_mode) else "file",
                "root_dev": root_info.st_dev, "root_inode": root_info.st_ino,
                "metadata_signature": hashlib.sha256(_json_bytes(records)).hexdigest(),
                "move_signature": hashlib.sha256(_json_bytes(move_records)).hexdigest(), "_records": records}

    @staticmethod
    def _public_snapshot(snapshot: dict) -> dict:
        return {key: value for key, value in snapshot.items() if not key.startswith("_")}

    def preview(self, source: str | Path) -> dict:
        source = self._source(source)
        with self._locked(), _directory(source.parent) as parent_fd:
            return self._public_snapshot(self._snapshot(parent_fd, source.name))

    def _signed(self, receipt: dict) -> dict:
        receipt = {key: value for key, value in receipt.items() if key != "seal"}
        receipt["seal"] = hmac.new(self._marker["token"].encode(), _json_bytes(receipt), hashlib.sha256).hexdigest()
        return receipt

    def _save(self, item_fd: int, receipt: dict) -> None:
        receipt["updated_at"] = self.clock()
        sealed = self._signed(receipt)
        _write_json(item_fd, "receipt.json", sealed)
        receipt["seal"] = sealed["seal"]

    @contextlib.contextmanager
    def _item(self, items_fd: int, receipt_id: str):
        if not isinstance(receipt_id, str) or len(receipt_id) != 32 or any(c not in "0123456789abcdef" for c in receipt_id):
            raise RetentionStoreError("未知收据 id")
        try:
            item_fd = os.open(receipt_id, _DIR_FLAGS, dir_fd=items_fd)
        except OSError as exc:
            raise RetentionStoreError("找不到工具收据目录") from exc
        try:
            receipt = _read_json(item_fd, "receipt.json")
            item_info = os.fstat(item_fd)
            if (receipt.get("seal") != self._signed(receipt)["seal"] or receipt.get("id") != receipt_id
                    or receipt.get("tool") != _TOOL or receipt.get("store_id") != self._marker["store_id"]
                    or receipt.get("identity") != self.identity or receipt.get("state") not in STATES
                    or receipt.get("item_inode") != item_info.st_ino or item_info.st_dev != self.identity["store_dev"]
                    or item_info.st_uid != os.getuid()):
                raise RetentionStoreError("未知、改变或身份不匹配的收据")
            self._source(receipt["source"])
            extras = set(self._names(item_fd)) - {"receipt.json", "payload"}
            if any(not (name.startswith(".writing-") and len(name) == 41
                        and all(c in "0123456789abcdef" for c in name[9:])) for name in extras):
                raise RetentionStoreError("收据目录包含未知条目")
            yield item_fd, receipt
        except (KeyError, TypeError, ValueError) as exc:
            raise RetentionStoreError("收据格式无效") from exc
        finally:
            os.close(item_fd)

    def get_receipt(self, receipt_id: str) -> dict:
        with self._locked() as items_fd, self._item(items_fd, receipt_id) as (_, receipt):
            return receipt

    def list_receipts(self) -> list[dict]:
        with self._locked() as items_fd:
            names = self._names(items_fd)
            receipts = []
            for name in names:
                with self._item(items_fd, name) as (_, receipt):
                    receipts.append(receipt)
            return receipts

    def _block(self, item_fd: int, receipt: dict, reason: str) -> None:
        receipt["state"], receipt["blocked_reason"] = "BLOCKED", reason
        self._save(item_fd, receipt)

    def quarantine(self, source: str | Path, *, metadata: dict | None = None,
                   expected_signature: str | None = None) -> dict:
        return self._move_into_store(self._source(source), None, None, metadata, expected_signature)

    def register_existing(self, source: str | Path, isolated: str | Path, quarantined_at: float | str,
                          identity: Mapping[str, Any], *, metadata: dict | None = None) -> dict:
        """仅接管调用层明确列出的已隔离条目；保留其实际成功隔离时间。"""
        if dict(identity) != self.identity:
            raise RetentionStoreError("历史隔离 identity 不匹配")
        isolated = _absolute(isolated)
        if isolated == self.store_root or self.store_root in isolated.parents or isolated == self.output_root or self.output_root in isolated.parents:
            raise RetentionStoreError("历史隔离条目必须在 output/store 之外")
        when = _timestamp(quarantined_at)
        if when > self.clock():
            raise RetentionStoreError("隔离时间不能在未来")
        return self._move_into_store(self._source(source), isolated, when, metadata, None)

    def _move_into_store(self, source: Path, isolated: Path | None, historical_time: float | None,
                         metadata: dict | None, expected_signature: str | None) -> dict:
        if metadata is not None and (not isinstance(metadata, dict) or len(_json_bytes(metadata)) > 65536):
            raise RetentionStoreError("metadata 必须是有界 JSON 对象")
        origin = isolated or source
        with self._locked() as items_fd, _directory(origin.parent) as origin_fd:
            if isolated is not None:
                with _directory(source.parent) as source_fd:
                    if _exists(source_fd, source.name):
                        raise RetentionStoreError("历史源路径已存在，拒绝接管")
            snapshot = self._snapshot(origin_fd, origin.name)
            if expected_signature is not None and snapshot["metadata_signature"] != expected_signature:
                raise RetentionStoreError("源条目在预览后改变")
            receipt_id = uuid.uuid4().hex
            os.mkdir(receipt_id, 0o700, dir_fd=items_fd)
            os.fsync(items_fd)
            item_fd = os.open(receipt_id, _DIR_FLAGS, dir_fd=items_fd)
            receipt = {"tool": _TOOL, "id": receipt_id, "store_id": self._marker["store_id"], "identity": self.identity,
                       "item_inode": os.fstat(item_fd).st_ino, "source": str(source), "move_origin": str(origin),
                       "payload": str(self.store_root / "items" / receipt_id / "payload"),
                       "created_at": self.clock(), "quarantined_at": historical_time, "state": "PLANNED",
                       "operation": "quarantine", "metadata": metadata or {}, "planned": self._public_snapshot(snapshot)}
            try:
                self._save(item_fd, receipt)
                receipt["state"] = "MOVING"
                self._save(item_fd, receipt)
                current = self._snapshot(origin_fd, origin.name)
                if current["metadata_signature"] != snapshot["metadata_signature"]:
                    raise RetentionStoreError("隔离前源条目改变")
                _rename_noreplace(origin_fd, origin.name, item_fd, "payload")
                receipt["quarantined_at"] = historical_time if historical_time is not None else self.clock()
                os.fsync(origin_fd)
                os.fsync(item_fd)
                final = self._snapshot(item_fd, "payload")
                if final["move_signature"] != snapshot["move_signature"]:
                    raise RetentionStoreError("隔离过程中树发生变化")
                receipt["snapshot"], receipt["state"] = self._public_snapshot(final), "QUARANTINED"
                self._save(item_fd, receipt)
                return receipt
            except Exception as exc:
                self._block(item_fd, receipt, type(exc).__name__ + ": " + str(exc))
                raise
            finally:
                os.close(item_fd)

    def _verified_payload(self, item_fd: int, receipt: dict) -> dict:
        if not _exists(item_fd, "payload") or "snapshot" not in receipt:
            raise RetentionStoreError("payload 或完成隔离指纹缺失")
        current = self._snapshot(item_fd, "payload")
        if current["metadata_signature"] != receipt["snapshot"]["metadata_signature"]:
            raise RetentionStoreError("隔离后的完整树元数据已改变")
        return current

    def restore(self, receipt_id: str) -> dict:
        with self._locked() as items_fd, self._item(items_fd, receipt_id) as (item_fd, receipt):
            if receipt["state"] != "QUARANTINED":
                raise RetentionStoreError("只有完整 QUARANTINED 条目可恢复")
            source = self._source(receipt["source"])
            with _directory(source.parent) as source_fd:
                if _exists(source_fd, source.name):
                    raise RetentionStoreError("恢复原路径存在冲突")
                try:
                    self._verified_payload(item_fd, receipt)
                    receipt["state"], receipt["operation"] = "MOVING", "restore"
                    self._save(item_fd, receipt)
                    _rename_noreplace(item_fd, "payload", source_fd, source.name)
                    os.fsync(item_fd)
                    os.fsync(source_fd)
                    receipt["state"], receipt["restored_at"] = "RESTORED", self.clock()
                    self._save(item_fd, receipt)
                    return receipt
                except Exception as exc:
                    self._block(item_fd, receipt, "restore: " + str(exc))
                    raise

    def _unlink_snapshot(self, parent_fd: int, name: str, snapshot: dict) -> None:
        expected = {relative: metadata for relative, metadata, _ in snapshot["_records"]}

        def remove(fd, child, relative):
            current = os.stat(child, dir_fd=fd, follow_symlinks=False)
            if _metadata(current) != expected[relative]:
                raise RetentionStoreError("清除期间条目改变")
            if stat.S_ISDIR(current.st_mode):
                child_fd = os.open(child, _DIR_FLAGS, dir_fd=fd)
                try:
                    if (os.fstat(child_fd).st_dev, os.fstat(child_fd).st_ino) != (current.st_dev, current.st_ino):
                        raise RetentionStoreError("清除期间目录 identity 改变")
                    for entry in self._names(child_fd):
                        rel = entry if relative == "." else relative + "/" + entry
                        if rel not in expected:
                            raise RetentionStoreError("清除期间出现新条目")
                        remove(child_fd, entry, rel)
                    os.fsync(child_fd)
                finally:
                    os.close(child_fd)
                final = os.stat(child, dir_fd=fd, follow_symlinks=False)
                if (final.st_dev, final.st_ino) != (current.st_dev, current.st_ino):
                    raise RetentionStoreError("清除目录被替换")
                os.rmdir(child, dir_fd=fd)
            else:
                os.unlink(child, dir_fd=fd)

        remove(parent_fd, name, ".")
        os.fsync(parent_fd)

    def purge(self, receipt_id: str) -> dict:
        with self._locked() as items_fd, self._item(items_fd, receipt_id) as (item_fd, receipt):
            if receipt["state"] != "QUARANTINED":
                raise RetentionStoreError("只有完整 QUARANTINED 条目可清除")
            when = _timestamp(receipt["quarantined_at"])
            if self.clock() - when < MIN_QUARANTINE_SECONDS:
                raise RetentionStoreError("成功隔离尚未满七天")
            try:
                snapshot = self._verified_payload(item_fd, receipt)
                receipt["state"], receipt["purge_started_at"] = "PURGING", self.clock()
                self._save(item_fd, receipt)
                self._unlink_snapshot(item_fd, "payload", snapshot)
                receipt["state"], receipt["purged_at"] = "PURGED", self.clock()
                self._save(item_fd, receipt)
                return receipt
            except Exception as exc:
                self._block(item_fd, receipt, "purge: " + str(exc))
                raise

    def recover(self, receipt_id: str) -> dict:
        """只协调已记录的 rename；PURGING 中断绝不自动续删。"""
        with self._locked() as items_fd, self._item(items_fd, receipt_id) as (item_fd, receipt):
            if receipt["state"] in {"PURGED", "RESTORED", "QUARANTINED", "BLOCKED"}:
                return receipt
            if receipt["state"] != "MOVING":
                self._block(item_fd, receipt, "操作未完成；禁止自动续删")
                return receipt
            source = self._source(receipt["source"])
            with _directory(source.parent) as source_fd:
                source_exists, payload_exists = _exists(source_fd, source.name), _exists(item_fd, "payload")
                if receipt["operation"] == "restore" and source_exists and not payload_exists:
                    current = self._snapshot(source_fd, source.name)
                    if current["move_signature"] == receipt["snapshot"]["move_signature"]:
                        receipt["state"], receipt["restored_at"] = "RESTORED", self.clock()
                        self._save(item_fd, receipt)
                        return receipt
                elif receipt["operation"] == "quarantine" and payload_exists and not source_exists:
                    current = self._snapshot(item_fd, "payload")
                    if current["move_signature"] == receipt["planned"]["move_signature"]:
                        # 未持久记录成功时间时采用现在，不能追溯早算七天。
                        receipt["quarantined_at"] = receipt.get("quarantined_at") or self.clock()
                        receipt["snapshot"], receipt["state"] = self._public_snapshot(current), "QUARANTINED"
                        self._save(item_fd, receipt)
                        return receipt
            self._block(item_fd, receipt, "中断操作的源/payload 状态无法安全协调")
            return receipt
