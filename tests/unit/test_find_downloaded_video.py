"""共享源视频定位器 (utils.file_utils.find_downloaded_video) 单元测试

锁定 BUG-3 修复行为——bot 与管线共用同一实现，杜绝把 `.ass` 字幕 /
`{yid}.f398.mp4` 无音轨分片误当源视频喂给 ffmpeg：

- 只接受 VIDEO_CONTAINER_SUFFIXES 白名单扩展名（拒绝 .ass/.srt/.json/.jpg）
- 文件名主干 stem 必须严格等于 yid（拒绝 {yid}.f398.mp4 / {yid}_vertical.mp4）
- 体积必须 > min_size（拒绝占位/碎片）
- 热目录优先，回退冷归档 original_video/
- 选择确定性（同目录多命中时按文件名排序取首个）

纯文件系统逻辑，无需 mock 任何外部对象。

# Modification History
| Version | Date       | Author          | Description                          |
|---------|------------|-----------------|--------------------------------------|
| 1.0.0   | 2026-06-15 | Claude_Opus_4.8 | 初始创建：锁定 BUG-3 共享源视频定位行为 |
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from video_processing.utils.file_utils import (
    find_downloaded_video,
    VIDEO_CONTAINER_SUFFIXES,
)

BIG = 60_000  # > 50KB 默认门槛


def _w(path, size=BIG):
    path.write_bytes(b"\0" * size)
    return path


class TestRejectsNonSourceFiles:
    def test_rejects_ass_subtitle(self, tmp_path):
        # 这正是历史 exit-234 崩溃的根源：.ass 被当成视频
        _w(tmp_path / "vid123.ass")
        assert find_downloaded_video(tmp_path, "vid123") is None

    def test_rejects_format_fragment_by_stem(self, tmp_path):
        # {yid}.f398.mp4 是无音轨 DASH 分片，stem='vid123.f398' != 'vid123'
        _w(tmp_path / "vid123.f398.mp4")
        assert find_downloaded_video(tmp_path, "vid123") is None

    def test_rejects_derived_vertical(self, tmp_path):
        _w(tmp_path / "vid123_vertical.mp4")
        assert find_downloaded_video(tmp_path, "vid123") is None

    def test_rejects_too_small(self, tmp_path):
        _w(tmp_path / "vid123.mp4", size=1000)  # < 50KB
        assert find_downloaded_video(tmp_path, "vid123") is None

    def test_rejects_metadata_and_images(self, tmp_path):
        for ext in (".json", ".jpg", ".webp", ".description", ".part"):
            _w(tmp_path / f"vid123{ext}")
        assert find_downloaded_video(tmp_path, "vid123") is None


class TestAcceptsRealSource:
    def test_finds_mp4(self, tmp_path):
        src = _w(tmp_path / "vid123.mp4")
        assert find_downloaded_video(tmp_path, "vid123") == str(src)

    def test_finds_webm(self, tmp_path):
        src = _w(tmp_path / "vid123.webm")
        assert find_downloaded_video(tmp_path, "vid123") == str(src)

    def test_ass_alongside_real_video_picks_video(self, tmp_path):
        # 混合场景：.ass 与真实源同在，必须选源视频而非字幕
        _w(tmp_path / "vid123.ass")
        src = _w(tmp_path / "vid123.mp4")
        assert find_downloaded_video(tmp_path, "vid123") == str(src)


class TestArchiveFallback:
    def test_falls_back_to_archive(self, tmp_path):
        archive = tmp_path / "original_video"
        archive.mkdir()
        src = _w(archive / "vid123.mp4")
        assert find_downloaded_video(tmp_path, "vid123", archive) == str(src)

    def test_hot_dir_takes_precedence_over_archive(self, tmp_path):
        archive = tmp_path / "original_video"
        archive.mkdir()
        _w(archive / "vid123.mkv")
        hot = _w(tmp_path / "vid123.mp4")
        assert find_downloaded_video(tmp_path, "vid123", archive) == str(hot)

    def test_missing_archive_dir_is_safe(self, tmp_path):
        assert find_downloaded_video(tmp_path, "nope", tmp_path / "nonexistent") is None


class TestDeterminism:
    def test_sorted_selection_is_stable(self, tmp_path):
        # 多个合法命中时，应按文件名排序确定性选首个（旧实现依赖 glob 任意顺序）
        _w(tmp_path / "vid123.webm")
        _w(tmp_path / "vid123.mkv")
        first = find_downloaded_video(tmp_path, "vid123")
        for _ in range(5):
            assert find_downloaded_video(tmp_path, "vid123") == first


def test_whitelist_constant_is_shared():
    # 白名单必须是单一真相源（pipeline_manager 的 _VIDEO_SUFFIXES 是它的别名）
    from video_processing.pipeline_manager import _VIDEO_SUFFIXES
    assert _VIDEO_SUFFIXES is VIDEO_CONTAINER_SUFFIXES
