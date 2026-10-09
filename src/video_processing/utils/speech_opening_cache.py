"""裁剪副本生命周期：硬重置清除；终态过期且无成片引用时回收。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-09 | Codex | 安全清理本任务目录，保留绑定成片、活跃任务及未知素材。 |
"""
from pathlib import Path
import re
import shutil


def remove_opening_cache(root: Path, video_id: str) -> list[str]:
    """只删除专属目录，拒绝路径逃逸及目录符号链接。"""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", video_id):
        raise ValueError("非法裁剪缓存视频标识")
    parent = root / "speech_opening"
    directory = parent / video_id
    if parent.is_symlink() or directory.is_symlink():
        raise ValueError("裁剪缓存目录不能为符号链接")
    if not directory.exists():
        return []
    names = [str(path.relative_to(root)) for path in directory.rglob("*") if path.is_file()]
    shutil.rmtree(directory)
    return names


def evict_opening_caches(root: Path, evictable: set[str], *, before: float) -> list[str]:
    """DAL 决定可清理任务；文件保留期和成片绑定再保护一次。"""
    removed = []
    for video_id in sorted(evictable):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", video_id):
            continue
        parent = root / "speech_opening"
        directory = parent / video_id
        if parent.is_symlink() or directory.is_symlink() or not directory.is_dir():
            continue
        # 已有成片仍需要同一素材校验或二创回读，不能删除或改写其绑定。
        binding = root / f"{video_id}_vertical.source.json"
        if binding.exists() or binding.is_symlink():
            continue
        paths = list(directory.rglob("*"))
        if any(path.is_symlink() or path.stat().st_mtime >= before for path in paths):
            continue
        removed.extend(remove_opening_cache(root, video_id))
    return removed
