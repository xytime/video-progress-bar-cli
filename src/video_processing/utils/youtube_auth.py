"""YouTube Cookie 的可验证刷新工具。

不把 Cookie 文件存在或包含某个字段当作可用证明；生产替换必须经过真实
yt-dlp 元数据请求。刷新失败保留旧文件，避免一次失败的浏览器导出破坏当前会话。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-26 | Codex | 新增 Cookie 临时导出、真实探针验收与原子替换。 |
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import fcntl
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


_REQUIRED_AUTH_COOKIES = frozenset({"SID", "SAPISID", "__Secure-3PSID"})


@dataclass(frozen=True)
class YoutubeAuthResult:
    """一次授权验证或刷新的非敏感结果。"""

    ok: bool
    code: str
    detail: str = ""


def validate_youtube_cookie_file(
    cookie_file: Path,
    *,
    probe_url: str,
    ytdlp_path: str,
    timeout_seconds: int = 45,
    environment: Mapping[str, str] | None = None,
) -> YoutubeAuthResult:
    """用临时副本验收 Cookie，避免 yt-dlp 回写生产文件。"""
    if not cookie_file.is_file() or cookie_file.stat().st_size <= 100:
        return YoutubeAuthResult(False, "COOKIE_FILE_MISSING")

    fd, temp_name = tempfile.mkstemp(prefix=".youtube_cookie_check_", dir=cookie_file.parent)
    os.close(fd)
    temp_file = Path(temp_name)
    try:
        shutil.copyfile(cookie_file, temp_file)
        os.chmod(temp_file, 0o600)
        result = subprocess.run(
            [
                ytdlp_path,
                "--cookies", str(temp_file),
                "--skip-download",
                "--no-playlist",
                "--no-warnings",
                "--print", "%(id)s",
                probe_url,
            ],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            env=dict(environment) if environment is not None else None,
        )
    except subprocess.TimeoutExpired:
        return YoutubeAuthResult(False, "PROBE_TIMEOUT")
    except OSError as exc:
        return YoutubeAuthResult(False, "YTDLP_UNAVAILABLE", str(exc))
    finally:
        temp_file.unlink(missing_ok=True)

    if result.returncode == 0 and result.stdout.strip():
        return YoutubeAuthResult(True, "READY")
    detail = " ".join((result.stderr or result.stdout or "yt-dlp probe failed").split())[:300]
    return YoutubeAuthResult(False, "PROBE_REJECTED", detail)


def refresh_youtube_cookie_file(
    cookie_file: Path,
    *,
    browser: str,
    probe_url: str,
    ytdlp_path: str,
    timeout_seconds: int = 60,
    environment: Mapping[str, str] | None = None,
) -> YoutubeAuthResult:
    """从浏览器安全刷新 Cookie；只有独立复验成功才原子替换生产文件。"""
    cookie_file.parent.mkdir(parents=True, exist_ok=True)
    lock_file = (cookie_file.parent / f".{cookie_file.name}.refresh.lock").open("a+")
    fd, temp_name = tempfile.mkstemp(prefix=".youtube_cookie_refresh_", dir=cookie_file.parent)
    os.close(fd)
    temp_file = Path(temp_name)
    try:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return YoutubeAuthResult(False, "REFRESH_BUSY")
        # yt-dlp 把 --cookies 视为 Netscape 文件；空的预创建文件会被拒绝。
        # mkstemp 只负责取得同目录的唯一名字，随后交由 yt-dlp 首次创建。
        temp_file.unlink()
        result = subprocess.run(
            [
                ytdlp_path,
                "--cookies-from-browser", browser,
                "--cookies", str(temp_file),
                "--skip-download",
                "--no-playlist",
                "--no-warnings",
                "--print", "%(id)s",
                probe_url,
            ],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            env=dict(environment) if environment is not None else None,
        )
        if result.returncode != 0 or not result.stdout.strip():
            detail = " ".join((result.stderr or result.stdout or "browser export failed").split())[:300]
            return YoutubeAuthResult(False, "BROWSER_EXPORT_REJECTED", detail)

        present = _cookie_names(temp_file)
        if not _REQUIRED_AUTH_COOKIES.issubset(present):
            return YoutubeAuthResult(False, "AUTH_COOKIE_INCOMPLETE")

        validation = validate_youtube_cookie_file(
            temp_file,
            probe_url=probe_url,
            ytdlp_path=ytdlp_path,
            timeout_seconds=timeout_seconds,
            environment=environment,
        )
        if not validation.ok:
            return YoutubeAuthResult(False, f"REFRESH_{validation.code}", validation.detail)

        os.replace(temp_file, cookie_file)
        os.chmod(cookie_file, 0o600)
        return YoutubeAuthResult(True, "REFRESHED")
    except subprocess.TimeoutExpired:
        return YoutubeAuthResult(False, "BROWSER_EXPORT_TIMEOUT")
    except OSError as exc:
        return YoutubeAuthResult(False, "BROWSER_EXPORT_UNAVAILABLE", str(exc))
    finally:
        temp_file.unlink(missing_ok=True)
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()


def _cookie_names(cookie_file: Path) -> set[str]:
    """仅解析 Cookie 名称，绝不读取或输出 Cookie 值。"""
    names: set[str] = set()
    for line in cookie_file.read_text(errors="ignore").splitlines():
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) >= 7:
            names.add(fields[5])
    return names
