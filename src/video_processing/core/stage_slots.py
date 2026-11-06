"""阶段资源槽：替代整片 pipeline.lock 的跨视频并行限流。

配置与 FFmpeg 名额共用 resource-limits.json；每次 acquire 重读文件（热生效）。
enable_stage_resource_slots=false 时调用方应回退整片 pipeline.lock。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-06 | Grok Bot | 阶段槽 + 组合上限 + 非阻塞延后；后台可配。 |
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

_LOG = logging.getLogger(__name__)

STAGE_NAMES = (
    "download",
    "copywriting",
    "asr",
    "ffmpeg",
    "cover_local",
    "agy_image",
)

# 多槽同时申请时的固定顺序，降低死锁概率。
ACQUIRE_ORDER = STAGE_NAMES

DEFAULTS: dict[str, Any] = {
    "ffmpeg_slots": 1,
    "enable_stage_resource_slots": True,
    "stage_slots": {
        "download": 1,
        "copywriting": 2,
        "asr": 1,
        "ffmpeg": 1,
        "cover_local": 1,
        "agy_image": 1,
        "asr_ffmpeg_combined_max": 2,
    },
}


def _default_config_directory() -> Path:
    try:
        return Path.home() / "Library" / "Application Support" / "VideoProcessing" / "ffmpeg-slot"
    except Exception:
        return Path("/tmp") / "VideoProcessing" / "ffmpeg-slot"


def _default_slot_directory() -> Path:
    try:
        return Path.home() / "Library" / "Application Support" / "VideoProcessing" / "stage-slots"
    except Exception:
        return Path("/tmp") / "VideoProcessing" / "stage-slots"


_CONFIG_DIRECTORY = _default_config_directory()
_SLOT_DIRECTORY = _default_slot_directory()
_STATE_LOCK = threading.Lock()


class StageSlotUnavailable(RuntimeError):
    """非阻塞申请失败；调用方应延后任务，禁止死等制造假 PROCESSING。"""

    def __init__(self, stage: str):
        self.stage = stage
        super().__init__(f"stage slot unavailable: {stage}")


def config_path(directory: Path | None = None) -> Path:
    return (directory or _CONFIG_DIRECTORY) / "resource-limits.json"


def slot_directory(directory: Path | None = None) -> Path:
    return directory or _SLOT_DIRECTORY


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _clamp_int(value: Any, *, default: int, lo: int = 1, hi: int = 64) -> int:
    if type(value) is not int or not lo <= value <= hi:
        return default
    return value


def normalize_config(raw: Any) -> dict[str, Any]:
    """容错合并默认值；非法字段回退默认，不放开无上限。"""
    data = raw if isinstance(raw, dict) else {}
    stage_raw = data.get("stage_slots") if isinstance(data.get("stage_slots"), dict) else {}
    defaults_stage = DEFAULTS["stage_slots"]
    stages = {
        name: _clamp_int(stage_raw.get(name, defaults_stage[name]), default=defaults_stage[name])
        for name in STAGE_NAMES
    }
    stages["asr_ffmpeg_combined_max"] = _clamp_int(
        stage_raw.get("asr_ffmpeg_combined_max", defaults_stage["asr_ffmpeg_combined_max"]),
        default=defaults_stage["asr_ffmpeg_combined_max"],
        lo=1,
        hi=128,
    )
    enable = data.get("enable_stage_resource_slots", DEFAULTS["enable_stage_resource_slots"])
    if type(enable) is not bool:
        enable = DEFAULTS["enable_stage_resource_slots"]
    return {
        "ffmpeg_slots": _clamp_int(
            data.get("ffmpeg_slots", DEFAULTS["ffmpeg_slots"]),
            default=DEFAULTS["ffmpeg_slots"],
        ),
        "enable_stage_resource_slots": enable,
        "stage_slots": stages,
    }


def load_config(directory: Path | None = None) -> dict[str, Any]:
    path = config_path(directory)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return normalize_config(DEFAULTS)
    except (ValueError, OSError) as exc:
        raise ValueError(f"无法读取资源槽配置：{path}") from exc
    return normalize_config(raw)


def save_config(payload: dict[str, Any], directory: Path | None = None) -> dict[str, Any]:
    """后台写入；原子替换。每次 acquire 重读，故写入后立即热生效。"""
    normalized = normalize_config(payload)
    # 保留未知顶层键，避免抹掉未来扩展字段。
    path = config_path(directory)
    existing: dict[str, Any] = {}
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(existing, dict):
            existing = {}
    except (FileNotFoundError, ValueError, OSError):
        existing = {}
    merged = dict(existing)
    merged["ffmpeg_slots"] = normalized["ffmpeg_slots"]
    merged["enable_stage_resource_slots"] = normalized["enable_stage_resource_slots"]
    merged["stage_slots"] = normalized["stage_slots"]
    _atomic_write(path, merged)
    return normalized


def stage_slots_enabled(directory: Path | None = None) -> bool:
    try:
        return bool(load_config(directory)["enable_stage_resource_slots"])
    except ValueError:
        # 配置损坏时拒绝并行，回到调用方的整片锁路径更安全。
        return False


def config_status(directory: Path | None = None) -> dict[str, Any]:
    path = config_path(directory)
    status: dict[str, Any] = {
        "resource_config": str(path),
        "stage_slot_directory": str(slot_directory()),
        "reload_policy": "每次数额申请重读 resource-limits.json（热生效）",
    }
    try:
        cfg = load_config(directory)
        status.update(
            config=cfg,
            enable_stage_resource_slots=cfg["enable_stage_resource_slots"],
            stage_slots=cfg["stage_slots"],
            ffmpeg_slots=cfg["ffmpeg_slots"],
            config_error=None,
        )
    except ValueError as exc:
        status.update(
            config=None,
            enable_stage_resource_slots=False,
            stage_slots=None,
            ffmpeg_slots=None,
            config_error=str(exc),
        )
    return status


def _busy_count(stage: str, directory: Path) -> int:
    busy = 0
    for path in directory.glob(f"{stage}-execution-*.lock"):
        try:
            fd = os.open(path, os.O_RDWR)
        except FileNotFoundError:
            continue
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            busy += 1
        else:
            # 空闲锁：立刻释放探测 fd
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
    return busy


class StageSlot:
    """单个阶段的非阻塞/可阻塞名额；内核 flock，进程退出即释放。"""

    def __init__(self, stage: str, *, config_directory: Path | None = None, slot_dir: Path | None = None):
        if stage not in STAGE_NAMES:
            raise ValueError(f"unknown stage: {stage}")
        self.stage = stage
        self.config_directory = config_directory or _CONFIG_DIRECTORY
        self.directory = slot_directory(slot_dir)
        self.fd: int | None = None
        self.limit = 1

    def _combined_ok(self, cfg: dict[str, Any], busy_asr: int, busy_ffmpeg: int) -> bool:
        limit = int(cfg["stage_slots"]["asr_ffmpeg_combined_max"])
        if self.stage == "asr":
            return (busy_asr + 1 + busy_ffmpeg) <= limit
        if self.stage == "ffmpeg":
            return (busy_asr + busy_ffmpeg + 1) <= limit
        return True

    def try_acquire(self) -> bool:
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        cfg = load_config(self.config_directory)
        self.limit = int(cfg["stage_slots"][self.stage])
        admission = self.directory / "admission.lock"
        with admission.open("a+") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            busy_asr = _busy_count("asr", self.directory)
            busy_ffmpeg = _busy_count("ffmpeg", self.directory)
            if self.stage in {"asr", "ffmpeg"} and not self._combined_ok(cfg, busy_asr, busy_ffmpeg):
                return False
            busy = _busy_count(self.stage, self.directory)
            if busy >= self.limit:
                return False
            # 找一个空闲 execution 锁
            for index in range(max(self.limit, busy + 1)):
                path = self.directory / f"{self.stage}-execution-{index}.lock"
                fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    os.close(fd)
                    continue
                except BaseException:
                    os.close(fd)
                    raise
                self.fd = fd
                return True
            return False

    def acquire(self, *, blocking: bool = False, poll_seconds: float = 0.25) -> "StageSlot":
        if self.try_acquire():
            return self
        if not blocking:
            raise StageSlotUnavailable(self.stage)
        logged = False
        while True:
            if self.try_acquire():
                if logged:
                    _LOG.warning("[StageSlot] 获得 %s 名额 pid=%s", self.stage, os.getpid())
                return self
            if not logged:
                _LOG.warning("[StageSlot] 等待 %s 名额 pid=%s", self.stage, os.getpid())
                logged = True
            time.sleep(poll_seconds)

    def release(self) -> None:
        if self.fd is not None:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
            finally:
                os.close(self.fd)
                self.fd = None

    def close(self) -> None:
        self.release()

    def __enter__(self) -> "StageSlot":
        return self.acquire(blocking=False)

    def __exit__(self, *exc) -> None:
        self.release()


@contextmanager
def hold_stage(
    stage: str,
    *,
    blocking: bool = False,
    config_directory: Path | None = None,
    slot_dir: Path | None = None,
) -> Iterator[StageSlot]:
    slot = StageSlot(stage, config_directory=config_directory, slot_dir=slot_dir)
    slot.acquire(blocking=blocking)
    try:
        yield slot
    finally:
        slot.release()


@contextmanager
def hold_stages(
    stages: list[str],
    *,
    blocking: bool = False,
    config_directory: Path | None = None,
    slot_dir: Path | None = None,
) -> Iterator[list[StageSlot]]:
    """按 ACQUIRE_ORDER 申请多槽，失败时释放已持有槽。"""
    ordered = [name for name in ACQUIRE_ORDER if name in stages]
    held: list[StageSlot] = []
    try:
        for name in ordered:
            slot = StageSlot(name, config_directory=config_directory, slot_dir=slot_dir)
            slot.acquire(blocking=blocking)
            held.append(slot)
        yield held
    finally:
        for slot in reversed(held):
            slot.release()


class PipelineExclusiveLock:
    """整片 pipeline.lock（feature flag 关闭时的串行回退）。"""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        self.handle = handle
        return self

    def __exit__(self, *exc):
        if self.handle is not None:
            try:
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            finally:
                self.handle.close()
                self.handle = None
