"""字幕坏例记忆：不可变、内容寻址快照；检测疑点不是人工真值。

这里只存宿主提供的 JSON，不读取媒体、凭据、任务数据库或模型。
人工标签保存在独立文件，原始 bad case 永远不被复盘结果改写。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-27 | Codex | 原子、幂等且拒绝符号链接的字幕案例快照与摘要校验。 |
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Iterator


SCHEMA_VERSION = "subtitle-bad-case-v1"
MAX_CASE_BYTES = 16 * 1024 * 1024
_SHA = re.compile(r"^[0-9a-f]{64}$")


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                       allow_nan=False) + "\n").encode("utf-8")


def _safe_path(path: Path, *, make_directory: bool = False) -> Path:
    """逐分量拒绝链接（含不存在叶子的链接祖先），不用 resolve 跟随链接。"""
    path = Path(os.path.abspath(path))
    for item in (*reversed(path.parents), path):
        try:
            info = item.lstat()
        except FileNotFoundError:
            if make_directory:
                try:
                    item.mkdir(mode=0o700)
                except FileExistsError:
                    pass  # 另一保存者可能刚建好；仍须 lstat 拒绝链接和非目录。
                info = item.lstat()
            else:
                continue
        if stat.S_ISLNK(info.st_mode):
            raise ValueError(f"bad_case_symlink: {item}")
        if item != path or make_directory:
            if not stat.S_ISDIR(info.st_mode):
                raise ValueError(f"bad_case_not_directory: {item}")
    return path


def _read_bytes(path: Path) -> bytes:
    path = _safe_path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_CASE_BYTES:
            raise ValueError("bad_case_invalid_file")
        data = stream.read(MAX_CASE_BYTES + 1)
    if len(data) > MAX_CASE_BYTES:
        raise ValueError("bad_case_too_large")
    return data


def load_bad_case(path: Path, expected_sha256: str | None = None) -> dict:
    """校验文件摘要、内容寻址 ID、格式；返回 envelope（含 payload）。"""
    data = _read_bytes(path)
    digest = hashlib.sha256(data).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError("bad_case_sha256_mismatch")
    value = json.loads(data)
    if (not isinstance(value, dict) or set(value) != {"schema_version", "case_id", "review", "payload"}
            or value.get("schema_version") != SCHEMA_VERSION
            or not isinstance(value.get("payload"), dict)
            or not isinstance(value.get("case_id"), str) or not _SHA.fullmatch(value["case_id"])
            or value.get("review") != {"status": "unreviewed", "ground_truth": False}):
        raise ValueError("bad_case_invalid_envelope")
    identity = {key: value[key] for key in ("schema_version", "review", "payload")}
    if hashlib.sha256(_canonical(identity)).hexdigest() != value["case_id"]:
        raise ValueError("bad_case_content_identity_mismatch")
    if Path(path).name != value["case_id"] + ".json":
        raise ValueError("bad_case_filename_mismatch")
    if data != _canonical(value):
        raise ValueError("bad_case_noncanonical_bytes")
    return value


def save_bad_case(root: Path, payload: dict) -> dict:
    """完整快照先 fsync，再原子 create-if-absent；已有文件必须逐字节一致。

    返回 {case_id, path, sha256}。payload 应由宿主提供原文/译文/时间轴、
    修复历史、检测信号及媒体/ASR/合同/候选身份；本层不把检测信号当真值。
    相同 payload 重复保存不会新增案例或改变原文件。
    """
    if not isinstance(payload, dict):
        raise ValueError("bad_case_payload_not_object")
    identity = {"schema_version": SCHEMA_VERSION,
                "review": {"status": "unreviewed", "ground_truth": False}, "payload": payload}
    case_id = hashlib.sha256(_canonical(identity)).hexdigest()
    data = _canonical({**identity, "case_id": case_id})
    if len(data) > MAX_CASE_BYTES:
        raise ValueError("bad_case_too_large")
    directory = _safe_path(Path(root) / "cases" / case_id[:2], make_directory=True)
    path = directory / f"{case_id}.json"
    fd, temporary_name = tempfile.mkstemp(prefix=".case-", suffix=".tmp", dir=directory)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fchmod(stream.fileno(), 0o400)
            os.fsync(stream.fileno())
        _safe_path(path)
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError:
            if _read_bytes(path) != data:
                raise ValueError("bad_case_existing_content_mismatch")
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)
    result = {"case_id": case_id, "path": str(path), "sha256": hashlib.sha256(data).hexdigest()}
    load_bad_case(path, result["sha256"])
    return result


def iter_bad_cases(root: Path) -> Iterator[dict]:
    """确定顺序读取全部合法快照；损坏或链接必须报错，不能悄悄漏掉坏例。"""
    directory = _safe_path(Path(root) / "cases")
    if not directory.exists():
        return
    for shard in sorted(directory.iterdir()):
        _safe_path(shard)
        if not shard.is_dir() or not re.fullmatch(r"[0-9a-f]{2}", shard.name):
            raise ValueError("bad_case_invalid_shard")
        for path in sorted(shard.iterdir()):
            _safe_path(path)
            if path.name.startswith(".case-") and path.name.endswith(".tmp"):
                continue  # 仍在原子保存中的临时文件不是已落盘案例。
            value = load_bad_case(path)
            if not value["case_id"].startswith(shard.name):
                raise ValueError("bad_case_shard_mismatch")
            yield value
