"""双七天清理服务：任务/引用先行，默认预览，具名隔离后才允许到期清除。

依赖：入口 → 本服务 → 只读 DAL / 主机守卫 / 隔离存储 → 配置；不调用发布流程。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-31 | Codex | 有界扫描、有效引用保护、双七天隔离与每日运行回执 |
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from bisect import bisect_left
import fcntl
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import time
import uuid

from config.output_retention import OutputRetentionPolicy
from video_processing.db.database import PipelineDB
from video_processing.core.output_retention_store import OutputRetentionStore


DAY = 86400
MEDIA_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".wav", ".mp3", ".m4a",
                  ".ass", ".srt", ".vtt", ".jpg", ".jpeg", ".png", ".txt", ".description"}
SOURCE_SUBTITLE_SUFFIXES = {".ass", ".srt", ".vtt"}
MAX_BATCH_ACTIONS = 128
PROTECTED_PARTS = {"subtitle_evidence", "wechat_evidence", "douyin_evidence", "kuaishou_evidence",
                   "evidence", "receipts", "investigations", "recovery", "backups", "backup",
                   "chromium_profile", "browser_profile", "wechat_profile", "auth", "secrets"}
SECRET_NAMES = re.compile(r"(?:cookie|credential|secret|token|wechat_state|wechat.*session|auth|login)", re.I)
PROOF_NAMES = re.compile(r"(?:evidence|receipt|provenance|approval|checkpoint|quality|binding|\.source\.)", re.I)
MANIFEST_NAMES = re.compile(
    r"(?:^|[._-])(?:manifest|timeline|contract|render|publication|job|script)(?:[._-]|$)", re.I)
HISTORICAL_PROOF_NAMES = re.compile(r"(?:evidence|receipt|provenance|approval|checkpoint|binding)", re.I)
EXPLICIT_MANIFEST_NAMES = re.compile(r"(?:manifest|timeline|contract)", re.I)
NO_READ_PARTS = {"chromium_profile", "browser_profile", "wechat_profile", "auth", "secrets"}
VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
TERMINAL_MANIFEST = {"PUBLISHED", "COMPLETED", "DONE", "ARCHIVED", "REJECTED", "IGNORED"}


def epoch(value):
    """无时区 SQLite 时间约定 UTC；损坏/缺失时间绝不解释成很老。"""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) if value > 0 and math.isfinite(value) else None
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).timestamp()
    except (ValueError, OverflowError, OSError):
        return None


def overlaps(first, second):
    first, second = Path(first), Path(second)
    return first == second or first.is_relative_to(second) or second.is_relative_to(first)


@contextmanager
def control_directory(path, *, create_leaf=False):
    """不跟随控制目录祖先软链；只允许创建最后一级回执目录。"""
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("CONTROL_PATH_UNSAFE")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    search_flags = ((getattr(os, "O_SEARCH", 0x40000000 | os.O_DIRECTORY) if sys.platform == "darwin"
                     else getattr(os, "O_PATH", os.O_RDONLY) | os.O_DIRECTORY)
                    | os.O_NOFOLLOW | os.O_CLOEXEC)
    descriptor = os.open("/", search_flags if len(path.parts) > 1 else flags)
    try:
        for index, part in enumerate(path.parts[1:], 1):
            if create_leaf and index == len(path.parts) - 1:
                try:
                    os.mkdir(part, 0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
            child = os.open(part, flags if index == len(path.parts) - 1 else search_flags,
                            dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        yield descriptor
    finally:
        os.close(descriptor)


def write_json(path, value, *, expected_device, create_parent=False):
    path = Path(path)
    temporary = path.name + "." + uuid.uuid4().hex + ".tmp"
    with control_directory(path.parent, create_leaf=create_parent) as parent:
        if os.fstat(parent).st_dev != expected_device:
            raise ValueError("CONTROL_DEVICE_CHANGED")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=parent)
        try:
            with os.fdopen(descriptor, "w", closefd=False) as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(descriptor)
            os.replace(temporary, path.name, src_dir_fd=parent, dst_dir_fd=parent)
            os.fsync(parent)
        finally:
            os.close(descriptor)
            try:
                os.unlink(temporary, dir_fd=parent)
            except FileNotFoundError:
                pass


class RetentionInventory:
    """一次元数据扫描建立候选与引用；预算或解析未知时保守保留。"""

    def __init__(self, policy, snapshot, *, clock=time.time):
        self.policy, self.snapshot, self.clock = policy, snapshot, clock
        self.output, self.project = Path(policy.output_root), Path(policy.project_root)
        self.candidates, self.references, self.unknown = [], [], []
        self.directory_stamps, self.manifest_stamps = {}, {}
        self.owner_paths, self.reference_paths, self._reference_keys = {}, {}, None
        self.entries, self.json_read = 0, 0
        self.started = time.monotonic()
        self.sources = snapshot.get("sources", {})
        self.db_refs = snapshot.get("path_references", [])
        for ref in self.db_refs:
            path = self.path_value(ref.get("path"), self.project)
            if path:
                self.owner_paths.setdefault(path, set()).update(ref.get("youtube_ids", []))
            if ref.get("protected") or ref.get("kind") == "evidence":
                if path:
                    self.add_reference(path, "DB_REFERENCE")

    def add_reference(self, path, reason):
        key = str(path)
        self.references.append({"path": key, "reason": reason})
        self.reference_paths.setdefault(key, reason)
        self._reference_keys = None

    def reference_reason(self, path):
        """祖先字典 + 有序后代前缀，避免每候选遍历数千条引用。"""
        for parent in (path, *path.parents):
            if str(parent) in self.reference_paths:
                return self.reference_paths[str(parent)]
        if self._reference_keys is None:
            self._reference_keys = sorted(self.reference_paths)
        prefix = str(path) + "/"
        index = bisect_left(self._reference_keys, prefix)
        if index < len(self._reference_keys) and self._reference_keys[index].startswith(prefix):
            return self.reference_paths[self._reference_keys[index]]
        return None

    @staticmethod
    def stamp(path):
        info = path.lstat()
        return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    def unchanged(self, *, max_seconds=5):
        """只查已扫描目录/manifest 的元数据；变化时留待下轮重新扫描。"""
        deadline = time.monotonic() + max_seconds
        try:
            for records in (self.directory_stamps, self.manifest_stamps):
                for path, expected in records.items():
                    if time.monotonic() > deadline or self.stamp(path) != expected:
                        return False
            return True
        except OSError:
            return False

    def after_move(self, source):
        # rename 仅改变原父目录；不将其余并发变化静默当成自己的动作。
        for path in list(self.directory_stamps):
            if path.is_relative_to(source):
                self.directory_stamps.pop(path)
        if source.parent in self.directory_stamps:
            self.directory_stamps[source.parent] = self.stamp(source.parent)

    def check_budget(self):
        self.entries += 1
        if (self.entries > self.policy.scan_entries
                or time.monotonic() - self.started > self.policy.max_seconds):
            raise ValueError("INVENTORY_BUDGET_EXHAUSTED")

    def path_value(self, value, parent):
        if not isinstance(value, str) or not value or "\x00" in value or "://" in value:
            return None
        path = Path(value)
        if path.is_absolute():
            result = Path(os.path.normpath(path))
        elif value.startswith("output/"):
            result = Path(os.path.normpath(self.project / path))
        elif path.suffix.lower() in MEDIA_SUFFIXES or "/" in value:
            result = Path(os.path.normpath(parent / path))
        else:
            return None
        roots = (self.output, Path(self.policy.store_root))
        return result if any(result.is_relative_to(root) and result != root for root in roots) else None

    def owners(self, path):
        """只认可真实主键或 DAL 路径归属，禁止把标题中的任意 11 字符当 ID。"""
        owners = set()
        for part in path.relative_to(self.output).parts:
            candidate = part[:11]
            if candidate in self.sources and (len(part) == 11 or part[11] in "_.-"):
                owners.add(candidate)
        for ancestor in (path, *path.parents):
            owners.update(self.owner_paths.get(ancestor, ()))
        return sorted(owners)

    def protected(self, path):
        relative = path.relative_to(self.output)
        return (any(part.lower() in PROTECTED_PARTS for part in relative.parts)
                or bool(SECRET_NAMES.search(path.name)) or bool(PROOF_NAMES.search(path.name))
                or path.name.startswith(".") or path.suffix.lower() in {".db", ".sqlite3", ".pid", ".lock"}
                or path.suffix.lower() in SOURCE_SUBTITLE_SUFFIXES
                or any(part.endswith("-hf-frame-cache") for part in relative.parts[:-1])
                or path.name.endswith(("-wal", "-shm")))

    def cache_kind(self, path):
        parts = path.relative_to(self.output).parts
        if path.name.endswith("-hf-frame-cache"):
            return "hyperframes_frames" if self._valid_hf_cache(path) else None
        if (len(parts) >= 5 and parts[-3].startswith("video-pytest-")
                and parts[-2] == "sandbox" and parts[-1] in {"browser", "pytest-tmp"}
                and "archived-test-temp" in parts[:-3]):
            return "archived_test_" + parts[-1]
        return None

    def _valid_hf_cache(self, path):
        """仅认可审核过的 hash/frame_<digits>.jpg + 完成标记布局。"""
        try:
            self.directory_stamps[path] = self.stamp(path)
            hashes = 0
            with os.scandir(path) as entries:
                for entry in entries:
                    self.check_budget()
                    info = entry.stat(follow_symlinks=False)
                    if stat.S_ISREG(info.st_mode) and entry.name == ".hf-last-gc":
                        continue
                    if (not stat.S_ISDIR(info.st_mode)
                            or not re.fullmatch(r"(?:hfcache-v7-)?[0-9a-f]{16,64}", entry.name)):
                        return False
                    hashes += 1
                    child = path / entry.name
                    self.directory_stamps[child] = self.stamp(child)
                    frames, complete = 0, False
                    with os.scandir(child) as frameset:
                        for frame in frameset:
                            self.check_budget()
                            if not stat.S_ISREG(frame.stat(follow_symlinks=False).st_mode):
                                return False
                            if frame.name == ".hf-complete":
                                complete = True
                            elif re.fullmatch(r"frame_\d+\.jpg", frame.name):
                                frames += 1
                            else:
                                return False
                    if not frames or not complete:
                        return False
            return hashes > 0
        except OSError:
            self.unknown.append({"path": str(path), "reason": "CACHE_LAYOUT_UNKNOWN"})
            return False

    def _manifest(self, path):
        # yt-dlp 静态 info.json、包资源及无关测试数据不属于运行引用清单。
        if (path.suffix.lower() != ".json" or SECRET_NAMES.search(path.name)
                or re.fullmatch(r"[A-Za-z0-9_-]{11}\.info\.json", path.name)
                or (HISTORICAL_PROOF_NAMES.search(path.name)
                    and not EXPLICIT_MANIFEST_NAMES.search(path.name))
                or not MANIFEST_NAMES.search(path.name)):
            return
        try:
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("MANIFEST_NOT_REGULAR")
            self.manifest_stamps[path] = self.stamp(path)
            if info.st_size > 2 * 1024**2 or self.json_read + info.st_size > self.policy.json_bytes:
                raise ValueError("REFERENCE_BUDGET_EXHAUSTED")
            self.json_read += info.st_size
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
            try:
                opened = os.fstat(descriptor)
                if (not stat.S_ISREG(opened.st_mode) or
                        (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns) !=
                        (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)):
                    raise ValueError("MANIFEST_CHANGED")
                with os.fdopen(descriptor, "rb", closefd=False) as stream:
                    content = stream.read(2 * 1024**2 + 1)
            finally:
                os.close(descriptor)
            if self.stamp(path) != self.manifest_stamps[path] or len(content) != info.st_size:
                raise ValueError("MANIFEST_CHANGED")
            data = json.loads(content)
            owners = self.owners(path)
            now = self.clock()
            owner_safe = bool(owners) and all(
                self.sources.get(x, {}).get("terminal")
                and (activity := epoch(self.sources[x].get("last_activity_at"))) is not None
                and now - activity > self.policy.idle_days * DAY for x in owners)
            root_state = str(data.get("status", data.get("state", ""))).upper() if isinstance(data, dict) else ""
            # 渲染 DONE 本身不是投稿终态；没有数据库终态归属的 manifest 保守保留依赖。
            protect = (self.protected(path) or not owner_safe
                       or (root_state and root_state not in TERMINAL_MANIFEST))
            def visit(value, depth=0):
                if depth > 32:
                    raise ValueError("MANIFEST_DEPTH_EXCEEDED")
                if isinstance(value, str):
                    ref = self.path_value(value, path.parent)
                    if ref and protect:
                        self.add_reference(ref, "MANIFEST_REFERENCE")
                elif isinstance(value, dict):
                    for item in value.values():
                        visit(item, depth + 1)
                elif isinstance(value, list):
                    for item in value:
                        visit(item, depth + 1)
            visit(data)
        except (OSError, ValueError, RecursionError) as exc:
            self.unknown.append({"path": str(path), "reason": type(exc).__name__ + ":MANIFEST_UNKNOWN"})

    def _symlink_reference(self, path):
        try:
            self.manifest_stamps[path] = self.stamp(path)
            target = Path(os.readlink(path))
            target = Path(os.path.normpath(target if target.is_absolute() else path.parent / target))
            if any(target.is_relative_to(root) for root in
                   (self.output, Path(self.policy.store_root))):
                self.add_reference(target, "SYMLINK_REFERENCE")
        except OSError:
            self.unknown.append({"path": str(path), "reason": "SYMLINK_REFERENCE_UNKNOWN"})

    def scan(self):
        def onerror(error):
            self.unknown.append({"reason": "SCAN_ERROR", "path": str(error.filename)})
        self.directory_stamps[self.output] = self.stamp(self.output)
        for directory, dirs, files in os.walk(self.output, followlinks=False, onerror=onerror):
            self.check_budget()
            parent = Path(directory)
            if self.directory_stamps.get(parent) != self.stamp(parent):
                raise ValueError("INVENTORY_CHANGED")
            kept = []
            for name in sorted(dirs):
                self.check_budget()
                path = parent / name
                if path.is_symlink():
                    self._symlink_reference(path)
                    continue
                self.directory_stamps[path] = self.stamp(path)
                kind = self.cache_kind(path) if not self.protected(path) else None
                if kind:
                    self.candidates.append({"path": str(path), "kind": kind, "owner_ids": []})
                elif (name.lower() not in NO_READ_PARTS and not SECRET_NAMES.search(name)
                      and not (name == "repo" and "archived-test-temp" in path.parts)):
                    kept.append(name)
            dirs[:] = kept
            for name in sorted(files):
                self.check_budget()
                path = parent / name
                if path.is_symlink():
                    self._symlink_reference(path)
                    continue
                # 即使 manifest 本身属于保护证据，其有效依赖仍必须读入；认证内容从不读取。
                self._manifest(path)
                if self.protected(path) or path.suffix.lower() not in MEDIA_SUFFIXES:
                    continue
                owners = self.owners(path)
                if owners:
                    self.candidates.append({"path": str(path), "kind": "owned_artifact", "owner_ids": owners})
        if not self.unchanged():
            raise ValueError("INVENTORY_CHANGED")
        return self

    def eligible(self, candidate, facts, info, *, check_age=True, aliases=()):
        now = self.clock()
        if (not isinstance(candidate, dict) or not isinstance(candidate.get("path"), str)
                or not isinstance(candidate.get("owner_ids", []), list)
                or not all(isinstance(item, str) for item in candidate.get("owner_ids", []))):
            return "CANDIDATE_UNKNOWN"
        source = Path(candidate["path"])
        if (not source.is_absolute() or not source.is_relative_to(self.output)
                or source == self.output or ".." in source.parts):
            return "CANDIDATE_PATH_UNKNOWN"
        if self.snapshot.get("status") != "OK" or self.unknown:
            return "REFERENCE_STATE_UNKNOWN"
        if facts.get("status") != "OK":
            return "HOST_STATE_UNKNOWN"
        if facts.get("busy_processes"):
            return "ACTIVE_PRODUCTION_PROCESS"
        for tracked in facts.get("tracked_paths", []):
            path = Path(tracked)
            if not path.is_absolute():
                path = self.project / path
            if overlaps(source, path):
                return "GIT_TRACKED"
        reference_reason = self.reference_reason(source)
        if reference_reason:
            return reference_reason
        for alias in aliases:
            reference_reason = self.reference_reason(Path(alias))
            if reference_reason:
                return "PAYLOAD_" + reference_reason
        for ref in facts.get("open_references", []):
            value = ref.get("path") if isinstance(ref, dict) else ref
            if value and overlaps(source, value):
                return "OPEN_FILE"
        if source.suffix.lower() in SOURCE_SUBTITLE_SUFFIXES:
            return "SOURCE_SUBTITLE_RETAINED"
        if self.protected(source):
            return "PROTECTED_RESOURCE"
        kinds = {"owned_artifact", "hyperframes_frames", "archived_test_browser", "archived_test_pytest-tmp"}
        if candidate.get("kind") not in kinds:
            return "CANDIDATE_KIND_UNKNOWN"
        if (candidate["kind"] == "owned_artifact" and source.suffix.lower() not in MEDIA_SUFFIXES
                or candidate["kind"] == "hyperframes_frames" and not source.name.endswith("-hf-frame-cache")):
            return "CANDIDATE_KIND_UNKNOWN"
        owners = sorted(set(candidate.get("owner_ids", [])) | set(self.owners(source)))
        if candidate["kind"] == "owned_artifact" and not owners:
            return "OWNER_UNKNOWN"
        for owner in owners:
            row = self.sources.get(owner)
            if not row or not row.get("terminal"):
                return "TASK_NOT_TERMINAL"
            activity = epoch(row.get("last_activity_at"))
            if activity is None or activity > now or now - activity <= self.policy.idle_days * DAY:
                return "TASK_RECENT_OR_TIME_UNKNOWN"
        if check_age:
            modified = info.get("maxmtime")
            if (not isinstance(modified, (int, float)) or isinstance(modified, bool)
                    or not math.isfinite(modified) or modified > now
                    or now - modified <= self.policy.idle_days * DAY):
                return "RESOURCE_RECENT_OR_TIME_UNKNOWN"
        return None


class OutputRetentionService:
    def __init__(self, policy: OutputRetentionPolicy, guard, *, clock=time.time):
        self.policy, self.guard, self.clock = policy.validate(), guard, clock
        self.store = OutputRetentionStore(policy.output_root, policy.store_root,
                                         expected_identity=policy.store_identity, clock=clock,
                                         max_entries=policy.max_tree_entries,
                                         max_scan_seconds=min(5, policy.max_seconds))
        self.control = Path(policy.store_root).parent

    @contextmanager
    def locked(self):
        with control_directory(self.control) as parent:
            if os.fstat(parent).st_dev != self.policy.store_identity["store_dev"]:
                raise ValueError("CONTROL_DEVICE_CHANGED")
            descriptor = os.open("run.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
                                 0o600, dir_fd=parent)
            try:
                info = os.fstat(descriptor)
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                        or info.st_nlink != 1 or info.st_dev != self.policy.store_identity["store_dev"]):
                    raise ValueError("CONTROL_LOCK_UNSAFE")
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                yield
            finally:
                os.close(descriptor)

    def inventory(self):
        snapshot = PipelineDB.output_retention_snapshot(Path(self.policy.output_root) / "pipeline.db")
        return RetentionInventory(self.policy, snapshot, clock=self.clock).scan()

    def run(self, *, apply=False):
        started = time.monotonic()
        run = {"version": 1, "id": uuid.uuid4().hex, "started_at": self.clock(),
               "apply": apply, "state": "IN_PROGRESS", "actions": [], "skipped": {},
               "moved_bytes": 0, "purged_logical_bytes": 0}
        try:
            self.guard.verify_mount()
            with self.locked():
                before_free = os.statvfs(self.policy.volume_root)
                facts = self.guard.capture()
                run.update(scan_entries=0, candidates=0, reference_unknown=[], host_status=facts.get("status"))
                if facts.get("status") != "OK":
                    run["state"] = "BLOCKED_UNKNOWN"
                elif facts.get("busy_processes"):
                    run["state"] = "SKIPPED_BUSY"
                else:
                    inventory = self.inventory()
                    run.update(scan_entries=inventory.entries, candidates=len(inventory.candidates),
                               reference_unknown=inventory.unknown[:20])
                    if inventory.snapshot.get("status") != "OK" or inventory.unknown:
                        run["state"] = "BLOCKED_UNKNOWN"
                    else:
                        self._process(run, inventory, facts, apply, started)
                        run["state"] = "COMPLETE"
                after_free = os.statvfs(self.policy.volume_root)
                run["observed_free_bytes_delta"] = ((after_free.f_bavail * after_free.f_frsize)
                                                    - (before_free.f_bavail * before_free.f_frsize))
        except (OSError, ValueError, RuntimeError) as exc:
            run.update(state="BLOCKED", error=type(exc).__name__, reason=str(exc)[:200])
        finally:
            run["finished_at"] = self.clock()
            run["seconds"] = round(time.monotonic() - started, 3)
            try:
                self.guard.verify_mount()
                device = self.policy.store_identity["store_dev"]
                write_json(self.control / "runs" / (run["id"] + ".json"), run,
                           expected_device=device, create_parent=True)
                write_json(self.control / "latest.json", run, expected_device=device)
            except (OSError, ValueError, RuntimeError):
                run["receipt_error"] = "CONTROL_WRITE_UNAVAILABLE"
        return run

    def _skip(self, run, reason):
        run["skipped"][reason] = run["skipped"].get(reason, 0) + 1

    def _budget(self, run, started, size=0):
        return (len(run["actions"]) < min(MAX_BATCH_ACTIONS, self.policy.max_actions)
                and run["moved_bytes"] + run["purged_logical_bytes"] + size <= self.policy.max_bytes
                and time.monotonic() - started < self.policy.max_seconds)

    def _fresh(self, inventory):
        """只重新读 DAL；manifest 在锁外以扫描期元数据验证，绝不逐项全盘重扫。"""
        snapshot = PipelineDB.output_retention_snapshot(Path(self.policy.output_root) / "pipeline.db")
        fresh = RetentionInventory(self.policy, snapshot, clock=self.clock)
        for reference in inventory.references:
            if reference["reason"] == "MANIFEST_REFERENCE":
                fresh.add_reference(reference["path"], reference["reason"])
        return fresh

    @staticmethod
    def _payload_open(receipt, facts):
        payload = receipt.get("payload")
        return not payload or any(
            ref.get("path") and overlaps(payload, ref["path"])
            for ref in facts.get("open_references", []) if isinstance(ref, dict))

    @staticmethod
    def _receipt_bytes(receipt):
        snapshot = receipt.get("snapshot", receipt.get("planned", {}))
        value = snapshot.get("bytes") if isinstance(snapshot, dict) else None
        return value if type(value) is int and value >= 0 else None

    def _perform(self, operation, candidate, inventory, info, receipt, run, started):
        """每项最终准入后复核；全盘发现与候选树预览均不持维护锁。"""
        if not inventory.unchanged():
            raise ValueError("INVENTORY_CHANGED")
        size = self._receipt_bytes(receipt) if receipt else info["bytes"]
        if size is None or not self._budget(run, started, size):
            raise ValueError("ACTION_BUDGET")
        with self.guard.exclusive_idle():
            if not inventory.unchanged(max_seconds=1):
                raise ValueError("INVENTORY_CHANGED_OR_RECHECK_BUDGET")
            fresh, facts = self._fresh(inventory), self.guard.capture()
            aliases = (receipt["payload"],) if receipt and receipt.get("payload") else ()
            reason = fresh.eligible(candidate, facts, info, check_age=operation == "QUARANTINED", aliases=aliases)
            if receipt and self._payload_open(receipt, facts):
                raise ValueError("PAYLOAD_OPEN_OR_UNKNOWN")
            if operation == "RESTORED":
                if (facts.get("status") != "OK" or facts.get("busy_processes")
                        or fresh.snapshot.get("status") != "OK"
                        or reason not in {"MANIFEST_REFERENCE", "DB_REFERENCE", "TASK_NOT_TERMINAL"}):
                    raise ValueError("RESTORE_NOT_VERIFIED")
                saved = self.store.restore(receipt["id"])
            else:
                if reason:
                    raise ValueError(reason)
                if not self._budget(run, started, size):
                    raise ValueError("ACTION_BUDGET")
                saved = (self.store.purge(receipt["id"]) if operation == "PURGED" else
                         self.store.quarantine(candidate["path"], metadata={"candidate": candidate},
                                               expected_signature=info["metadata_signature"]))
            if operation != "PURGED":
                inventory.after_move(Path(candidate["path"]))
            return saved

    def _process(self, run, inventory, facts, apply, started):
        # 先复核具名隔离项，再筛新候选；来源不明的其他临时目录永不清除。
        for receipt in self.store.list_receipts():
            if not self._budget(run, started):
                break
            if receipt["state"] != "QUARANTINED":
                self._skip(run, "RECEIPT_" + receipt["state"])
                continue
            candidate = receipt.get("metadata", {}).get("candidate")
            if (not isinstance(candidate, dict) or candidate.get("path") != receipt.get("source")
                    or not isinstance(candidate.get("path"), str)):
                self._skip(run, "RECEIPT_OWNER_UNKNOWN")
                continue
            quarantined_at = epoch(receipt.get("quarantined_at"))
            size = self._receipt_bytes(receipt)
            if quarantined_at is None or quarantined_at > self.clock() or size is None:
                self._skip(run, "RECEIPT_TIME_OR_SIZE_UNKNOWN")
                continue
            due = self.clock() - quarantined_at >= self.policy.observation_days * DAY
            reason = inventory.eligible(candidate, facts, {}, check_age=False,
                                        aliases=(receipt["payload"],) if receipt.get("payload") else ())
            if self._payload_open(receipt, facts):
                self._skip(run, "PAYLOAD_OPEN_OR_UNKNOWN")
                continue
            if reason:
                self._skip(run, reason)
                # 只有明确新引用触发恢复；未知状态不移动任何资源。
                if reason in {"MANIFEST_REFERENCE", "DB_REFERENCE", "TASK_NOT_TERMINAL"}:
                    if not self._budget(run, started, size):
                        self._skip(run, "ACTION_BUDGET")
                        continue
                    try:
                        if apply:
                            self._perform("RESTORED", candidate, inventory, {}, receipt, run, started)
                        run["actions"].append({"action": "RESTORED" if apply else "WOULD_RESTORE",
                                               "id": receipt["id"], "source": candidate["path"], "bytes": size})
                        run["moved_bytes"] += size
                        if apply:
                            return  # 恢复会新增扫描树；其余动作必须等下一轮全量引用普查。
                    except (OSError, ValueError, RuntimeError):
                        self._skip(run, "RESTORE_BLOCKED")
                continue
            if not due:
                self._skip(run, "OBSERVATION_PERIOD")
                continue
            if not self._budget(run, started, size):
                self._skip(run, "ACTION_BUDGET")
                continue
            if apply:
                try:
                    self._perform("PURGED", candidate, inventory, {}, receipt, run, started)
                except (OSError, ValueError, RuntimeError):
                    self._skip(run, "PURGE_BLOCKED")
                    continue
            run["actions"].append({"action": "PURGED" if apply else "WOULD_PURGE", "id": receipt["id"],
                                   "source": candidate["path"], "bytes": size})
            run["purged_logical_bytes"] += size

        for candidate in inventory.candidates:
            if not self._budget(run, started):
                self._skip(run, "RUN_BUDGET")
                break
            try:
                reason = inventory.eligible(candidate, facts, {}, check_age=False)
                if reason:
                    self._skip(run, reason)
                    continue
                info = self.store.preview(candidate["path"])
                reason = inventory.eligible(candidate, facts, info)
                if reason:
                    self._skip(run, reason)
                    continue
                if not self._budget(run, started, info["bytes"]):
                    self._skip(run, "ACTION_BUDGET")
                    continue
                if apply:
                    saved = self._perform("QUARANTINED", candidate, inventory, info, None, run, started)
                else:
                    saved = {}
                run["actions"].append({"action": "QUARANTINED" if apply else "WOULD_QUARANTINE",
                                       "id": saved.get("id"), "source": candidate["path"], "bytes": info["bytes"]})
                run["moved_bytes"] += info["bytes"]
            except (OSError, ValueError, RuntimeError) as exc:
                self._skip(run, type(exc).__name__ + ":CANDIDATE_BLOCKED")
