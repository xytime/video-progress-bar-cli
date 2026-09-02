"""抖音浏览器启动凭据的本地产物绑定工具。

低层上传器只接受已领取账本签发的一次性启动凭据。凭据除了绑定成片本身，还绑定
标题、正文和封面，避免同一视频被替换投稿包后借用旧凭据打开浏览器。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-02 | Codex | 新增抖音投稿包规范路径和全量文件哈希，供一次性浏览器启动凭据跨进程复核。 |
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional


def canonical_local_path(path: str | Path) -> str:
    """返回不依赖当前工作目录的规范本地路径。"""
    return str(Path(path).expanduser().resolve())


def sha256_file(path: str | Path | None) -> Optional[str]:
    """计算单个本地文件摘要；不存在或不可读时返回 None。"""
    if not path:
        return None
    target = Path(path)
    if not target.is_file():
        return None
    digest = hashlib.sha256()
    try:
        with target.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def douyin_submission_payload_sha256(
    *,
    video_path: str | Path | None,
    copy_path: str | Path | None,
    title_path: str | Path | None,
    cover_path: str | Path | None,
    horizontal_cover_path: str | Path | None = None,
) -> Optional[str]:
    """返回带字段边界的投稿包摘要；任一必需文件不可读即拒绝签发/启动。"""
    files = (
        ("video", video_path, True),
        ("copy", copy_path, True),
        ("title", title_path, True),
        ("cover", cover_path, True),
        ("horizontal_cover", horizontal_cover_path, False),
    )
    payload = hashlib.sha256()
    for label, path, required in files:
        digest = sha256_file(path)
        if required and not digest:
            return None
        payload.update(label.encode("utf-8"))
        payload.update(b"\0")
        payload.update((digest or "").encode("ascii"))
        payload.update(b"\0")
    return payload.hexdigest()
