"""YouTube Cookie 原子刷新与真实探针回归测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-26 | Codex | 覆盖探针失败保留旧 Cookie 与成功原子替换。 |
"""

from pathlib import Path
from types import SimpleNamespace

from video_processing.utils import youtube_auth


def _cookie_text(*names: str) -> str:
    return "\n".join(f".youtube.com\tTRUE\t/\tFALSE\t0\t{name}\tvalue" for name in names)


def test_refresh_keeps_previous_cookie_when_browser_export_is_rejected(tmp_path: Path, monkeypatch):
    target = tmp_path / "youtube_cookies.txt"
    target.write_text("old-cookie", encoding="utf-8")
    monkeypatch.setattr(
        youtube_auth.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="blocked"),
    )

    result = youtube_auth.refresh_youtube_cookie_file(
        target, browser="chrome", probe_url="https://example.test/watch", ytdlp_path="yt-dlp",
    )

    assert result.code == "BROWSER_EXPORT_REJECTED"
    assert target.read_text(encoding="utf-8") == "old-cookie"


def test_refresh_replaces_cookie_only_after_independent_probe(tmp_path: Path, monkeypatch):
    target = tmp_path / "youtube_cookies.txt"
    target.write_text("old-cookie", encoding="utf-8")

    def fake_run(command, **kwargs):
        cookie_path = Path(command[command.index("--cookies") + 1])
        if "--cookies-from-browser" in command:
            cookie_path.write_text(_cookie_text("SID", "SAPISID", "__Secure-3PSID"), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="probe-id\n", stderr="")

    monkeypatch.setattr(youtube_auth.subprocess, "run", fake_run)
    result = youtube_auth.refresh_youtube_cookie_file(
        target, browser="chrome", probe_url="https://example.test/watch", ytdlp_path="yt-dlp",
    )

    assert result.code == "REFRESHED"
    assert "SID" in target.read_text(encoding="utf-8")
    assert not list(tmp_path.glob(".youtube_cookie_refresh_*"))


def test_validate_uses_copy_and_leaves_production_cookie_unchanged(tmp_path: Path, monkeypatch):
    target = tmp_path / "youtube_cookies.txt"
    target.write_text(_cookie_text("SID", "SAPISID", "__Secure-3PSID"), encoding="utf-8")

    def fake_run(command, **kwargs):
        cookie_path = Path(command[command.index("--cookies") + 1])
        assert cookie_path != target
        cookie_path.write_text("changed-temporary-copy", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="probe-id\n", stderr="")

    monkeypatch.setattr(youtube_auth.subprocess, "run", fake_run)
    result = youtube_auth.validate_youtube_cookie_file(
        target, probe_url="https://example.test/watch", ytdlp_path="yt-dlp",
    )

    assert result.code == "READY"
    assert "SID" in target.read_text(encoding="utf-8")
    assert not list(tmp_path.glob(".youtube_cookie_check_*"))


def test_refresh_returns_busy_without_replacing_cookie(tmp_path: Path):
    target = tmp_path / "youtube_cookies.txt"
    target.write_text("old-cookie", encoding="utf-8")
    lock_path = tmp_path / ".youtube_cookies.txt.refresh.lock"
    lock_handle = lock_path.open("a+")
    try:
        youtube_auth.fcntl.flock(lock_handle.fileno(), youtube_auth.fcntl.LOCK_EX)
        result = youtube_auth.refresh_youtube_cookie_file(
            target, browser="chrome", probe_url="https://example.test/watch", ytdlp_path="yt-dlp",
        )
    finally:
        youtube_auth.fcntl.flock(lock_handle.fileno(), youtube_auth.fcntl.LOCK_UN)
        lock_handle.close()

    assert result.code == "REFRESH_BUSY"
    assert target.read_text(encoding="utf-8") == "old-cookie"
