"""本机视频虚拟环境的 FFmpeg 共享名额。只用标准库，允许在 Python 启动时装载。

所有 Popen 入口（含 imageio / Whisper / yt-dlp）共用同一组 flock；非 FFmpeg
保持标准库行为。等待发生在创建子进程之前，所以 run(timeout=...) 只计算执行。
锁 FD 传给 FFmpeg：即使 Python 父进程崩溃，仍不会提前放行下一项。
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
from pathlib import Path
import subprocess
import threading
import time
import uuid

_BASE_POPEN = subprocess.Popen
_DIRECTORY = Path.home() / "Library" / "Application Support" / "VideoProcessing" / "ffmpeg-slot"
_CUSTOM_EXECUTABLES: set[str] = set()
_STATE_LOCK = threading.Lock()
_WAITERS = 0
_WAIT_STARTED = 0.0
_WAIT_TOTAL = 0.0
_LOG = logging.getLogger(__name__)


DEFAULT_FFMPEG_SLOTS = 1


def configured_limit(directory: Path | None = None) -> int:
    """共享文件是唯一配置源；缺省为 1，损坏时拒绝启动，绝不放开限制。"""
    path = (directory or _DIRECTORY) / "resource-limits.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return DEFAULT_FFMPEG_SLOTS
    except (ValueError, OSError) as exc:
        raise ValueError(f"无法读取 FFmpeg 名额配置：{path}") from exc
    value = data.get("ffmpeg_slots", DEFAULT_FFMPEG_SLOTS) if isinstance(data, dict) else None
    if type(value) is not int or not 1 <= value <= 64:
        raise ValueError(f"ffmpeg_slots 必须是 1 到 64 的整数：{path}")
    return value


def config_status() -> dict:
    status = {"ffmpeg_config": str(_DIRECTORY / "resource-limits.json")}
    try:
        status.update(ffmpeg_limit=configured_limit(), ffmpeg_config_error=None)
    except ValueError as exc:
        status.update(ffmpeg_limit=None, ffmpeg_config_error=str(exc))
    return status


def register_executable(path: str | None) -> None:
    if path:
        _CUSTOM_EXECUTABLES.add(str(path))


def is_ffmpeg(args, executable=None, shell=False) -> bool:
    if shell:
        return False  # 受维护入口使用 argv；不得把 shell 命令猜测为可安全重写的 argv。
    candidate = executable or (args[0] if isinstance(args, (list, tuple)) and args else args)
    if not isinstance(candidate, (str, bytes, os.PathLike)):
        return False
    candidate = os.fsdecode(candidate)
    name = Path(candidate).name.lower()
    return candidate in _CUSTOM_EXECUTABLES or name == "ffmpeg" or name.startswith("ffmpeg-")


def wait_state() -> dict:
    """本进程等待的墙钟时间并集，避免多个线程重复累加。"""
    with _STATE_LOCK:
        seconds = _WAIT_TOTAL + (time.monotonic() - _WAIT_STARTED if _WAITERS else 0)
        return {"waiting": bool(_WAITERS), "seconds": seconds}


def _waiting(change: int) -> None:
    global _WAITERS, _WAIT_STARTED, _WAIT_TOTAL
    with _STATE_LOCK:
        if change > 0 and _WAITERS == 0:
            _WAIT_STARTED = time.monotonic()
        _WAITERS += change
        if change < 0 and _WAITERS == 0:
            _WAIT_TOTAL += time.monotonic() - _WAIT_STARTED


def _atomic(path: Path, data: dict) -> None:
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x") as stream:
            json.dump(data, stream)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class Slot:
    """FIFO 等候票 + 可配置执行锁池。票与锁均靠内核生命周期，不依赖 PID 文件过期。"""
    def __init__(self, directory: Path | None = None):
        self.directory = directory or _DIRECTORY
        self.fd: int | None = None
        self.ticket: Path | None = None
        self.ticket_fd: int | None = None
        self.token = uuid.uuid4().hex
        self.waited = 0.0
        self.wait_record = None
        self.limit = DEFAULT_FFMPEG_SLOTS

    def _first(self) -> bool:
        for path in sorted(self.directory.glob("*.wait")):
            if path == self.ticket:
                return True
            try:
                with path.open("r") as stream:
                    try:
                        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        return False
                    path.unlink(missing_ok=True)  # 进程已退出，内核已释放票锁。
            except FileNotFoundError:
                continue
        return False

    def _try_acquire(self) -> bool:
        # 准入锁只覆盖计数与占位；执行锁 FD 仍由 FFmpeg 继承。
        with (self.directory / "admission.lock").open("a+") as admission:
            fcntl.flock(admission, fcntl.LOCK_EX)
            if not self._first():
                return False
            self.limit = configured_limit(self.directory)
            paths = {self.directory / "execution.lock"}  # 兼容原单名额 inode。
            paths.update(self.directory / f"execution-{i}.lock" for i in range(1, self.limit))
            # 调低时仍计入旧的高编号名额，等待其自然结束。
            paths.update(self.directory.glob("execution-[0-9]*.lock"))
            free = []
            busy = 0
            try:
                for path in sorted(paths, key=lambda p: (p.name != "execution.lock", p.name)):
                    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        busy += 1
                        os.close(fd)
                    except BaseException:
                        os.close(fd)
                        raise
                    else:
                        free.append(fd)
                if busy < self.limit and free:
                    self.fd = free.pop(0)
                    return True
                return False
            finally:
                for fd in free:
                    os.close(fd)

    def acquire(self) -> int:
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.directory / (self.token + ".ticket")
        started = time.monotonic()
        _waiting(1)
        try:
            self.ticket_fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
            fcntl.flock(self.ticket_fd, fcntl.LOCK_EX)
            os.write(self.ticket_fd, json.dumps({"pid": os.getpid(), "pgid": os.getpgrp(),
                                                "queued_at": time.time()}).encode())
            self.ticket = self.directory / f"{time.monotonic_ns():020d}-{self.token}.wait"
            temporary.rename(self.ticket)
            logged = False
            while True:
                if self._try_acquire():
                    break
                if not logged:
                    self.wait_record = {"pid": os.getpid(), "started_at": time.time(),
                                        "ancestors": _ancestors()}
                    os.lseek(self.ticket_fd, 0, os.SEEK_SET)
                    os.ftruncate(self.ticket_fd, 0)
                    os.write(self.ticket_fd, json.dumps(self.wait_record).encode())
                    _LOG.warning("[FFmpegSlot] 等待全局 FFmpeg 名额 pid=%s", os.getpid())
                    logged = True
                time.sleep(0.25)
            self.waited = time.monotonic() - started
            if logged:
                _LOG.warning("[FFmpegSlot] 获得名额，等待 %.1fs pid=%s", self.waited, os.getpid())
            return self.fd
        except BaseException:
            self.close()
            raise
        finally:
            _waiting(-1)
            temporary.unlink(missing_ok=True)
            if self.ticket is not None:
                if self.wait_record is not None:
                    self.wait_record["ended_at"] = time.time()
                    try:
                        _atomic(self.ticket.with_suffix(".finished"), self.wait_record)
                        # 只清理本机制自己的已完成等待证据，不碰业务文件。
                        finished = sorted(self.directory.glob("*.finished"))
                        for old in finished[:-2048]:
                            old.unlink(missing_ok=True)
                    except OSError:
                        _LOG.warning("[FFmpegSlot] 等待证据写入失败")
                self.ticket.unlink(missing_ok=True)
            if self.ticket_fd is not None:
                os.close(self.ticket_fd)
                self.ticket_fd = None

    def close(self) -> None:
        if self.fd is not None:
            # 不 LOCK_UN：实际子进程继承同一 open-file-description，父进程关闭不释放它。
            os.close(self.fd)
            self.fd = None


class GuardedPopen(_BASE_POPEN):
    """精确拦截 FFmpeg 创建；不改参数、媒体内容、线程数或其他子进程。"""
    def __init__(self, args, *positional, **kwargs):
        self._ffmpeg_slot = None
        if not is_ffmpeg(args, kwargs.get("executable"), kwargs.get("shell", False)):
            super().__init__(args, *positional, **kwargs)
            return
        if positional:
            raise TypeError("FFmpeg Popen options must be keyword arguments")
        slot = Slot()
        fd = slot.acquire()
        self._ffmpeg_slot = slot
        kwargs["pass_fds"] = tuple(set(kwargs.get("pass_fds", ())) | {fd})
        kwargs["close_fds"] = True
        try:
            super().__init__(args, **kwargs)
        except BaseException:
            slot.close()
            self._ffmpeg_slot = None
            raise
        # 元数据失败不影响已经持有的内核锁；日志不包含命令、URL、字幕或密钥。
        try:
            _atomic(slot.directory / "last-start.json", {
                "pid": self.pid, "parent_pid": os.getpid(), "started_at": time.time(),
                "wait_seconds": slot.waited, "limit": slot.limit,
            })
        except OSError:
            _LOG.warning("[FFmpegSlot] 无法写入启动审计，内核互斥仍有效")

    def __del__(self):
        slot = getattr(self, "_ffmpeg_slot", None)
        if slot is not None:
            slot.close()
        super().__del__()

    def _release_if_done(self):
        slot = getattr(self, "_ffmpeg_slot", None)
        if self.returncode is not None and slot is not None:
            slot.close()
            self._ffmpeg_slot = None

    def poll(self):
        result = super().poll()
        self._release_if_done()
        return result

    def wait(self, timeout=None):
        result = super().wait(timeout=timeout)
        self._release_if_done()
        return result


def install() -> None:
    """仅项目虚拟环境/项目入口启用；幂等，避免重复套娃。"""
    if subprocess.Popen is not GuardedPopen:
        subprocess.Popen = GuardedPopen



def _ancestors() -> list[int]:
    """仅在真正排队时读取 PID/PPID，绝不读取进程参数。"""
    ancestors = [os.getpid(), os.getppid()]
    try:
        rows = subprocess.check_output(["/bin/ps", "-axo", "pid=,ppid="], text=True, timeout=2)
        parents = {int(a): int(b) for a, b in (line.split() for line in rows.splitlines())}
        while len(ancestors) < 32:
            parent = parents.get(ancestors[-1], 0)
            if parent <= 1 or parent in ancestors:
                break
            ancestors.append(parent)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return ancestors


class QueueBudget:
    def __init__(self, pid: int):
        self.pid = pid
        self.started_at = time.time()
        self.started_monotonic = time.monotonic()

    def elapsed(self) -> float:
        intervals = []
        now = time.time()
        paths = list(_DIRECTORY.glob("*.wait")) + sorted(_DIRECTORY.glob("*.finished"))[-2048:]
        for path in paths:
            try:
                record = json.loads(path.read_text())
                if self.pid not in record.get("ancestors", []):
                    continue
                start = max(self.started_at, float(record["started_at"]))
                end = min(now, float(record.get("ended_at", now)))
                if path.suffix == ".wait":
                    with path.open() as stream:
                        try:
                            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        except BlockingIOError:
                            pass
                        else:
                            continue  # 死亡等候者不会让父级超时无限延期。
                if end > start:
                    intervals.append((start, end))
            except (OSError, ValueError, KeyError, TypeError):
                continue
        covered = 0.0
        edge = self.started_at
        for start, end in sorted(intervals):
            covered += max(0, end - max(start, edge))
            edge = max(edge, end)
        return max(0, time.monotonic() - self.started_monotonic - covered)


def communicate_with_progress_budget(process, timeout, progress_path=None):
    """包括嵌套子进程在内，FFmpeg 排队不消耗已有总执行预算。"""
    if timeout is None:
        return process.communicate()
    budget = QueueBudget(process.pid)
    while True:
        remaining = timeout - budget.elapsed()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(process.args, timeout)
        try:
            return process.communicate(timeout=min(1, remaining))
        except subprocess.TimeoutExpired:
            continue


def wait_with_queue_budget(process, timeout):
    budget = QueueBudget(process.pid)
    while True:
        remaining = timeout - budget.elapsed()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(process.args, timeout)
        try:
            return process.wait(timeout=min(1, remaining))
        except subprocess.TimeoutExpired:
            continue
