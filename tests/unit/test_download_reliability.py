"""生产源下载恢复边界。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-05 | Codex | 锁定身份冷却、无效轨隔离、有界降级及取消后的缓存保留。 |
"""
import subprocess

import pytest

from video_processing.utils.download_strategy import DownloadBlockedError, DownloadOptions, execute_download_with_fallback
from video_processing.utils import file_utils


@pytest.mark.parametrize("message,category", [
    ("ERROR: Sign in to confirm you’re not a bot. https://media.invalid/?token=private", "auth"),
    ("ERROR: HTTP Error 429: Too Many Requests", "rate_limit"),
])
def test_upstream_block_does_not_fallback_and_persists_cooldown(tmp_path, message, category):
    options = DownloadOptions("yt-dlp", "https://youtu.be/test", "test.%(ext)s", cooldown_path=tmp_path / "cooldown.json")
    calls = []
    def runner(cmd, timeout=None):
        calls.append(cmd)
        raise subprocess.CalledProcessError(1, cmd, stderr=message)
    with pytest.raises(DownloadBlockedError) as blocked:
        execute_download_with_fallback(options, runner, lambda: None)
    assert blocked.value.category == category
    assert len(calls) == 1
    assert "token=private" not in options.cooldown_path.read_text()
    with pytest.raises(DownloadBlockedError):
        execute_download_with_fallback(options, runner, lambda: None)
    assert len(calls) == 1


@pytest.mark.parametrize("code", [1, -15])
def test_final_failure_quarantines_empty_video_and_retains_good_audio(tmp_path, monkeypatch, code):
    video, audio = tmp_path / "test.f298.mp4", tmp_path / "test.f140.m4a"
    audio.write_bytes(b"valid complete audio")
    monkeypatch.setattr(file_utils, "media_streams", lambda path: frozenset({"audio"}) if path == audio else frozenset())
    def runner(cmd, timeout=None):
        video.touch()
        raise subprocess.CalledProcessError(code, cmd, stderr="Invalid data found when processing input")
    options = DownloadOptions("yt-dlp", "https://youtu.be/test", str(tmp_path / "test.%(ext)s"))
    with pytest.raises((subprocess.CalledProcessError, InterruptedError)):
        execute_download_with_fallback(options, runner, lambda: None,
                                       cleaner=lambda: file_utils.clean_partial_downloads(tmp_path, "test"))
    assert not video.exists()
    assert list(tmp_path.glob("test.f298.mp4.invalid-*"))
    assert audio.read_bytes() == b"valid complete audio"


def test_runner_typeerror_is_not_invoked_twice():
    calls = []
    def runner(cmd, timeout=None):
        calls.append(cmd)
        raise TypeError("runner internal failure")
    with pytest.raises(TypeError):
        execute_download_with_fallback(DownloadOptions("yt-dlp", "url", "test"), runner, lambda: None)
    assert len(calls) == 2  # 两个策略各一次，不能因签名探测重复执行。


def test_time_used_by_cleaner_is_deducted_before_fallback(monkeypatch):
    from video_processing.utils import download_strategy as module
    now = [100.0]
    monkeypatch.setattr(module.time, "time", lambda: now[0])
    calls = []
    def cleaner():
        now[0] += 2
    def runner(cmd, timeout=None):
        calls.append(timeout)
        now[0] += 3
        if len(calls) == 1:
            raise RuntimeError("EOF")
    assert execute_download_with_fallback(DownloadOptions("yt-dlp", "url", "test"), runner,
                                          lambda: "valid" if len(calls) == 2 else None,
                                          cleaner=cleaner, total_timeout=10) == "valid"
    assert calls == [8, 3]
