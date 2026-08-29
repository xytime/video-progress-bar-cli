"""英语世界审核包的不可变文件指纹。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-29 | Codex | 统一计算和核验 MP4、manifest、标题、文案、封面及封面来源指纹。 |
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Mapping


PACKAGE_HASH_PATH_FIELDS = {
    "artifact_sha256": "mp4_path",
    "manifest_sha256": "manifest_path",
    "title_sha256": "title_path",
    "copy_sha256": "copy_path",
    "cover_sha256": "cover_path",
    "cover_provenance_sha256": "cover_provenance_path",
}


def sha256_file(path: Path) -> str:
    """流式计算文件 SHA-256，避免把成片整体读入内存。"""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def calculate_package_hashes(item: Mapping[str, object]) -> dict[str, str]:
    """计算审核项当前绑定的完整投稿包指纹；缺文件立即失败。"""
    result: dict[str, str] = {}
    for hash_field, path_field in PACKAGE_HASH_PATH_FIELDS.items():
        path = Path(str(item.get(path_field) or ""))
        if not path.is_file() or path.stat().st_size <= 0:
            raise FileNotFoundError(f"English World publish package missing: {path_field}")
        result[hash_field] = sha256_file(path)
    return result


def verify_package_hashes(item: Mapping[str, object]) -> dict[str, str]:
    """拒绝审核后发生任何位级变化的投稿包。"""
    actual = calculate_package_hashes(item)
    for field, digest in actual.items():
        expected = str(item.get(field) or "").strip().lower()
        if len(expected) != 64:
            raise ValueError(f"English World review item missing immutable hash: {field}")
        if digest != expected:
            raise ValueError(f"English World publish package changed after review: {field}")
    return actual
