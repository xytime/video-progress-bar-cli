"""渲染成片缓存校验回归测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-04 | Codex | 覆盖 cron 最小 PATH 下 ffprobe 定位，以及校验器不可用时保留缓存的 fail-safe 行为 |
| 1.1.0 | 2026-08-17 | Codex | 覆盖历史 ASS 含上游 HTTP 错误页时的缓存失效判定 |
"""

from types import SimpleNamespace

import pytest

from video_processing.pipeline_manager import (
    _ass_contains_upstream_error_response,
    _validate_rendered_vertical_cache,
)
from video_processing.utils import video_metadata


def test_ffprobe_resolver_uses_homebrew_path_when_cron_path_is_minimal(monkeypatch):
    """cron 不带 Homebrew PATH 时，仍应选用绝对 ffprobe 路径。"""
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setattr(video_metadata, "settings", SimpleNamespace(ffmpeg_path=None))

    def fake_exists(path):
        return str(path) == "/opt/homebrew/bin/ffprobe"

    monkeypatch.setattr(video_metadata.Path, "exists", fake_exists)

    assert video_metadata._resolve_ffprobe_cmd() == "/opt/homebrew/bin/ffprobe"


def test_invalid_rendered_cache_is_marked_for_rerender(tmp_path, monkeypatch):
    vertical = tmp_path / "broken_vertical.mp4"
    vertical.write_bytes(b"partial media")
    monkeypatch.setattr(
        video_metadata,
        "get_video_duration_ffprobe",
        lambda _: (_ for _ in ()).throw(ValueError("moov atom not found")),
    )

    assert _validate_rendered_vertical_cache(vertical) == (False, "moov atom not found")


def test_probe_unavailable_preserves_cache_for_manual_or_later_retry(tmp_path, monkeypatch):
    vertical = tmp_path / "existing_vertical.mp4"
    vertical.write_bytes(b"previous completed media")
    monkeypatch.setattr(
        video_metadata,
        "get_video_duration_ffprobe",
        lambda _: (_ for _ in ()).throw(FileNotFoundError("ffprobe missing")),
    )

    with pytest.raises(RuntimeError, match="保留缓存"):
        _validate_rendered_vertical_cache(vertical)

    assert vertical.exists()


def test_ass_with_google_error_page_is_not_a_reusable_bilingual_cache():
    ass = (
        "Dialogue: 0,0:00:00.00,0:00:02.00,Default,,0,0,0,,"
        "{\\fnGeorgia}English\\N{\\fnHiragino Sans GB}Error 500 (Server Error)!!1500. "
        "That's an error. There was an error. Please try again later. That's all we know."
    )

    assert _ass_contains_upstream_error_response(ass)
