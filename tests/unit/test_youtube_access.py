"""YouTube 媒体通路预检测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-30 | Codex | 覆盖格式 URL 解析、CDN 字节读取与可恢复故障分类。 |
"""

from __future__ import annotations

from types import SimpleNamespace

from video_processing.utils import youtube_access


def test_media_probe_requires_direct_url_and_successful_range_transfer(monkeypatch):
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        if command[0] == "yt-dlp":
            return SimpleNamespace(returncode=0, stdout="https://media.example/video\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(youtube_access.subprocess, "run", fake_run)

    result = youtube_access.probe_youtube_media_access(
        ytdlp_path="yt-dlp",
        cookie_args=["--cookies", "cookies.txt"],
        probe_url="https://www.youtube.com/watch?v=jNQXAC9IVRw",
        environment={"PATH": "/bin"},
        curl_path="curl",
    )

    assert result.ok is True
    assert result.code == "READY"
    assert calls[1][-1] == "https://media.example/video"
    assert "--range" in calls[1]


def test_media_probe_classifies_youtube_bot_challenge(monkeypatch):
    monkeypatch.setattr(
        youtube_access.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="Sign in to confirm you're not a bot",
        ),
    )

    result = youtube_access.probe_youtube_media_access(
        ytdlp_path="yt-dlp", cookie_args=[], probe_url="https://example.test", environment={},
    )

    assert result == youtube_access.YoutubeAccessResult(
        False, "AUTH_REQUIRED", "Sign in to confirm you're not a bot",
    )


def test_media_probe_classifies_cdn_403_as_access_not_candidate_quality(monkeypatch):
    results = iter([
        SimpleNamespace(returncode=0, stdout="https://media.example/video\n", stderr=""),
        SimpleNamespace(returncode=22, stdout="", stderr="curl: (22) The requested URL returned error: 403"),
    ])
    monkeypatch.setattr(youtube_access.subprocess, "run", lambda *_args, **_kwargs: next(results))

    result = youtube_access.probe_youtube_media_access(
        ytdlp_path="yt-dlp", cookie_args=[], probe_url="https://example.test", environment={},
    )

    assert result.ok is False
    assert result.code == "MEDIA_ACCESS_REJECTED"
