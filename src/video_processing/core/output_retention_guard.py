"""双七天清理的宿主事实与维护锁；未知状态一律禁止文件变更。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-31 | Codex | 卷身份、打开文件、业务进程、Git 跟踪及空闲维护锁校验 |
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import os
import plistlib
import subprocess
import time

from video_processing.core.maintenance import MaintenanceDenied


class RetentionGuardDenied(RuntimeError):
    """只暴露有界原因码，避免把进程参数或工具错误中的凭据写入回执。"""

    def __init__(self, code):
        self.code = str(code)
        super().__init__(self.code)


class RetentionHostGuard:
    """采集事实，不停止服务、不改变维护状态、不读取环境或业务配置。"""

    BUSINESS_MARKERS = (
        "auto-caption", "ffmpeg", "native_caption_vision.js", "pipeline_manager",
        "run_publication_window.py", "run_ready_publications.py", "run_video_task.py",
        "run_english_world_daily.py", "run_wallstreet_ab.py", "compliance_remix.py",
        "wechat_uploader.py", "douyin_uploader.py", "render_", "render-",
    )
    RESIDENT_MARKERS = (
        "bot_daemon.py", "uvicorn", "web.app", "maintenance_control.py",
        "src/bot/telegram_bot.py", "src/web/app.py",
        "output_retention", "run_output_retention",
    )

    def __init__(self, project_root, output_root, volume_root, expected_volume_uuid,
                 maintenance_gate, *, store_root=None, runner=None, max_seconds=20):
        self.project_root = Path(project_root).absolute()
        self.output_root = Path(output_root).absolute()
        self.volume_root = Path(volume_root).absolute()
        self.store_root = Path(store_root).absolute() if store_root is not None else None
        self.expected_volume_uuid = str(expected_volume_uuid).strip().upper()
        self.maintenance_gate = maintenance_gate
        self.runner = runner or subprocess.run
        self.max_seconds = float(max_seconds)
        if not self.expected_volume_uuid or not 0 < self.max_seconds <= 300:
            raise RetentionGuardDenied("GUARD_CONFIGURATION_INVALID")

    @staticmethod
    def _plain_directory(path):
        if any(component.is_symlink() for component in (path, *path.parents)):
            raise RetentionGuardDenied("HOST_PATH_SYMLINK")
        if not path.is_dir() or path.resolve() != path:
            raise RetentionGuardDenied("HOST_PATH_UNAVAILABLE")

    def _command(self, arguments, deadline, *, cwd=None):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RetentionGuardDenied("HOST_CAPTURE_TIMEOUT")
        try:
            result = self.runner(arguments, capture_output=True, check=False,
                                 timeout=remaining, cwd=cwd)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RetentionGuardDenied("HOST_COMMAND_UNAVAILABLE") from exc
        if result.returncode != 0:
            raise RetentionGuardDenied("HOST_COMMAND_FAILED")
        return result

    def _verify_mount(self, deadline):
        for path in (self.volume_root, self.project_root, self.output_root, self.store_root):
            if path is not None:
                self._plain_directory(path)
        if (not self.volume_root.is_mount()
                or not self.project_root.is_relative_to(self.volume_root)
                or self.project_root == self.volume_root
                or not self.output_root.is_relative_to(self.project_root)
                or self.output_root == self.project_root
                or (self.store_root is not None
                    and (not self.store_root.is_relative_to(self.volume_root)
                         or self.store_root == self.volume_root
                         or self.store_root.is_relative_to(self.project_root)))):
            raise RetentionGuardDenied("VOLUME_BOUNDARY_INVALID")
        device = self.volume_root.stat().st_dev
        if any(path.stat().st_dev != device for path in
               (self.project_root, self.output_root, self.store_root) if path is not None):
            raise RetentionGuardDenied("VOLUME_DEVICE_MISMATCH")
        result = self._command(["/usr/sbin/diskutil", "info", "-plist", str(self.volume_root)],
                               deadline)
        if result.stderr:
            raise RetentionGuardDenied("VOLUME_INFO_UNKNOWN")
        try:
            volume = plistlib.loads(result.stdout)
            observed_uuid = str(volume["VolumeUUID"]).strip().upper()
            mount = Path(volume["MountPoint"])
        except (ValueError, TypeError, KeyError, plistlib.InvalidFileException) as exc:
            raise RetentionGuardDenied("VOLUME_INFO_UNKNOWN") from exc
        if observed_uuid != self.expected_volume_uuid or mount != self.volume_root:
            raise RetentionGuardDenied("VOLUME_IDENTITY_MISMATCH")
        return {"volume_uuid": observed_uuid, "mount_point": str(mount), "device": device}

    def verify_mount(self):
        """核对实际挂载卷 UUID，而不是仅凭存在一个同名目录。"""
        return self._verify_mount(time.monotonic() + self.max_seconds)

    def _open_files(self, deadline):
        # NUL 分隔避免空格或换行文件名被拆成另一条路径。f 字段由 lsof 自动提供。
        result = self._command(["/usr/sbin/lsof", "-nP", "-F0pn"], deadline)
        if result.stderr:
            raise RetentionGuardDenied("OPEN_FILES_INCOMPLETE")
        fields = result.stdout.split(b"\0")
        if len(fields) < 2 or fields[-1].strip(b"\n"):
            raise RetentionGuardDenied("OPEN_FILES_UNKNOWN")
        pid, descriptor = None, None
        references, project_pids = [], set()
        roots = tuple(path for path in (self.output_root, self.store_root) if path is not None)
        for field in fields:
            field = field.lstrip(b"\n")
            if not field:
                continue
            marker, value = field[:1], field[1:]
            if marker == b"p":
                try:
                    pid = int(value)
                    if pid < 1:
                        raise ValueError()
                except ValueError as exc:
                    raise RetentionGuardDenied("OPEN_FILES_UNKNOWN") from exc
                descriptor = None
            elif marker == b"f":
                if pid is None:
                    raise RetentionGuardDenied("OPEN_FILES_UNKNOWN")
                descriptor = value
            elif marker == b"n":
                if pid is None or descriptor is None:
                    raise RetentionGuardDenied("OPEN_FILES_UNKNOWN")
                name = value.decode("utf-8")
                if not name.startswith("/"):
                    continue
                path = Path(name)
                if descriptor == b"cwd" and path.is_relative_to(self.project_root):
                    project_pids.add(pid)
                if any(path.is_relative_to(root) for root in roots):
                    references.append({"pid": pid, "path": name})
            else:
                raise RetentionGuardDenied("OPEN_FILES_UNKNOWN")
        if pid is None:
            raise RetentionGuardDenied("OPEN_FILES_UNKNOWN")
        return references, project_pids

    def _processes(self, deadline, project_pids):
        result = self._command(["/bin/ps", "-axo", "pid=,ppid=,comm=,args="], deadline)
        if result.stderr or not result.stdout.strip():
            raise RetentionGuardDenied("PROCESS_CAPTURE_UNKNOWN")
        busy = []
        for line in result.stdout.decode("utf-8").splitlines():
            fields = line.strip().split(None, 2)
            if len(fields) != 3:
                raise RetentionGuardDenied("PROCESS_CAPTURE_UNKNOWN")
            try:
                pid, parent = int(fields[0]), int(fields[1])
                if pid < 1 or parent < 0:
                    raise ValueError()
            except ValueError as exc:
                raise RetentionGuardDenied("PROCESS_CAPTURE_UNKNOWN") from exc
            if pid == os.getpid():
                continue
            command = fields[2]
            owned = pid in project_pids or str(self.project_root) in command
            if not owned:
                continue
            kinds = [marker for marker in self.BUSINESS_MARKERS if marker in command]
            if not kinds and ("python" in command.lower() and ".py" in command
                              and not any(marker in command for marker in self.RESIDENT_MARKERS)):
                kinds = ["PROJECT_PYTHON_WORKER"]
            if kinds:
                busy.append({"pid": pid, "ppid": parent, "kinds": kinds})
        return busy

    def _tracked(self, deadline):
        relative = self.output_root.relative_to(self.project_root)
        result = self._command(
            ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "ls-files", "-z",
             "--", relative.as_posix()], deadline, cwd=self.project_root)
        if result.stderr or (result.stdout and not result.stdout.endswith(b"\0")):
            raise RetentionGuardDenied("GIT_CAPTURE_UNKNOWN")
        paths = []
        for item in result.stdout.split(b"\0"):
            if not item:
                continue
            path = Path(item.decode("utf-8"))
            if path.is_absolute() or ".." in path.parts or not path.is_relative_to(relative):
                raise RetentionGuardDenied("GIT_PATH_UNKNOWN")
            paths.append(str(self.project_root / path))
        return paths

    def capture(self):
        """一次有界事实快照；任一来源失败都不能被解读为“没有引用”。"""
        deadline = time.monotonic() + self.max_seconds
        result = {"status": "UNKNOWN", "unknown_reasons": [], "mount": None,
                  "open_references": [], "busy_processes": [], "tracked_paths": []}
        try:
            result["mount"] = self._verify_mount(deadline)
            references, project_pids = self._open_files(deadline)
            result["open_references"] = references
            result["busy_processes"] = self._processes(deadline, project_pids)
            result["tracked_paths"] = self._tracked(deadline)
            result["status"] = "OK"
        except (RetentionGuardDenied, OSError, UnicodeError, ValueError) as exc:
            result["unknown_reasons"].append(getattr(exc, "code", "HOST_CAPTURE_UNKNOWN"))
        return result

    @contextmanager
    def exclusive_idle(self):
        """持有同一准入锁执行单项操作，防止检查空闲后新任务抢先领取。"""
        try:
            with self.maintenance_gate._locked():
                state = self.maintenance_gate._read()
                active, unknown = self.maintenance_gate._leases()
                if state["state"] != "RUNNING":
                    raise RetentionGuardDenied("MAINTENANCE_NOT_RUNNING")
                if unknown:
                    raise RetentionGuardDenied("MAINTENANCE_LEASE_UNKNOWN")
                if active:
                    raise RetentionGuardDenied("MAINTENANCE_BUSY")
                yield
        except MaintenanceDenied as exc:
            raise RetentionGuardDenied("MAINTENANCE_" + exc.code) from exc
