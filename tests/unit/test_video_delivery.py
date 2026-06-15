"""成片交付模块 (bot.video_delivery) 单元测试

锁定 v1.0.0 行为：
- finished_video_path：与 pipeline_manager 命名约定一致（整片 / 切片 / 自定义目录）
- compute_target_bitrates：按时长反推码率，紧张时音频降级、视频码率封底
- prepare_for_delivery：
    * 成片缺失 / 过小 → FinishedVideoNotFound
    * ≤ 上限 → 原片直发（不压缩）
    * > 上限 → 调用转码产出压缩副本
    * 已有合格压缩副本 → checkpoint 复用，不重复转码
    * 压缩后仍超限 → CompressionError

设计上 video_delivery 不依赖 telegram / DB / 网络，因此本测试只 monkeypatch 两个
模块内部接缝（ffprobe 时长探测、ffmpeg 转码），无需 mock 任何外部对象（满足 mock gate）。

# Modification History
| Version | Date       | Author          | Description                          |
|---------|------------|-----------------|--------------------------------------|
| 1.0.0   | 2026-06-14 | Claude_Opus_4.8 | 初始创建：锁定成片定位 + 超限自动压缩交付行为 |
"""

import os
import sys

import pytest

# 确保 src 在路径中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from bot import video_delivery as vd
from bot.video_delivery import (
    finished_video_path,
    compute_target_bitrates,
    prepare_for_delivery,
    PreparedVideo,
    FinishedVideoNotFound,
    CompressionError,
    TELEGRAM_BOT_FILE_LIMIT,
    _MIN_VALID_BYTES,
    _MIN_VIDEO_KBPS,
)

ONE_MB = 1024 * 1024


def _write(path, size_bytes):
    """写一个指定体积的占位文件。"""
    path.write_bytes(b"\0" * size_bytes)
    return path


# ── finished_video_path：命名约定 ──────────────────────────────────────────
class TestFinishedVideoPath:
    def test_whole_video(self, tmp_path):
        p = finished_video_path("abc123XYZ_0", output_dir=tmp_path)
        assert p == tmp_path / "abc123XYZ_0_vertical.mp4"

    def test_slice_zero_has_no_suffix(self, tmp_path):
        # slice_index=0 视为整片，不加 _s0
        p = finished_video_path("vid", slice_index=0, output_dir=tmp_path)
        assert p.name == "vid_vertical.mp4"

    def test_slice_nonzero(self, tmp_path):
        p = finished_video_path("vid", slice_index=2, output_dir=tmp_path)
        assert p.name == "vid_s2_vertical.mp4"


# ── compute_target_bitrates：码率反推（纯函数）─────────────────────────────
class TestComputeTargetBitrates:
    def test_normal_duration_keeps_full_audio(self):
        v, a = compute_target_bitrates(600, TELEGRAM_BOT_FILE_LIMIT)
        assert a == 128
        assert v > _MIN_VIDEO_KBPS

    def test_reconstructed_size_within_limit(self):
        # 反推出的码率在该时长下生成的体积应落在上限以内
        duration = 600
        v, a = compute_target_bitrates(duration, TELEGRAM_BOT_FILE_LIMIT)
        est_bytes = (v + a) * 1000 / 8 * duration
        assert est_bytes <= TELEGRAM_BOT_FILE_LIMIT

    def test_long_video_degrades_audio_and_floors_video(self):
        # 1 小时塞进 50MB：音频降到 64k，视频码率触底
        v, a = compute_target_bitrates(3600, TELEGRAM_BOT_FILE_LIMIT)
        assert a == 64
        assert v == _MIN_VIDEO_KBPS

    def test_zero_duration_raises(self):
        with pytest.raises(CompressionError):
            compute_target_bitrates(0, TELEGRAM_BOT_FILE_LIMIT)


# ── prepare_for_delivery：缺失 / 直发 ──────────────────────────────────────
class TestPrepareNotFound:
    def test_missing_file(self, tmp_path):
        with pytest.raises(FinishedVideoNotFound):
            prepare_for_delivery("nope", output_dir=tmp_path)

    def test_too_small_treated_as_not_ready(self, tmp_path):
        _write(tmp_path / "vid_vertical.mp4", 10)  # < _MIN_VALID_BYTES
        with pytest.raises(FinishedVideoNotFound):
            prepare_for_delivery("vid", output_dir=tmp_path)


class TestPreparePassThrough:
    def test_small_file_sent_as_is(self, tmp_path, monkeypatch):
        # 时长探测失败也不应阻断直发路径
        monkeypatch.setattr(vd, "get_video_duration_ffprobe",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no ffprobe")))
        src = _write(tmp_path / "vid_vertical.mp4", 100 * 1024)
        res = prepare_for_delivery("vid", output_dir=tmp_path, size_limit=10 * ONE_MB)
        assert isinstance(res, PreparedVideo)
        assert res.compressed is False
        assert res.path == src
        assert res.original_path == src
        assert res.size_bytes == 100 * 1024


# ── prepare_for_delivery：超限压缩（monkeypatch 转码接缝）───────────────────
class TestPrepareCompress:
    def _patch_duration(self, monkeypatch, seconds=600.0):
        monkeypatch.setattr(vd, "get_video_duration_ffprobe", lambda *a, **k: seconds)

    def test_oversize_triggers_transcode(self, tmp_path, monkeypatch):
        self._patch_duration(monkeypatch)
        calls = {}

        def fake_transcode(src, dst, vk, ak, ffmpeg_path=None):
            calls["v"] = vk
            calls["a"] = ak
            _write(dst, 1024)  # 产出一个远小于上限的副本

        monkeypatch.setattr(vd, "_transcode_to_fit", fake_transcode)
        _write(tmp_path / "vid_vertical.mp4", 2 * ONE_MB)

        res = prepare_for_delivery("vid", output_dir=tmp_path, size_limit=ONE_MB)
        assert res.compressed is True
        assert res.path == tmp_path / "vid_vertical_tg.mp4"
        assert res.original_path == tmp_path / "vid_vertical.mp4"
        assert res.size_bytes == 1024
        assert calls["v"] > 0 and calls["a"] > 0

    def test_reuses_existing_compressed_copy(self, tmp_path, monkeypatch):
        self._patch_duration(monkeypatch)

        def boom(*a, **k):
            raise AssertionError("不应重复转码：应复用已存在的压缩副本")

        monkeypatch.setattr(vd, "_transcode_to_fit", boom)
        # 先写源，再写压缩副本 → 副本 mtime 更新且体积达标
        _write(tmp_path / "vid_vertical.mp4", 2 * ONE_MB)
        _write(tmp_path / "vid_vertical_tg.mp4", 1024)

        res = prepare_for_delivery("vid", output_dir=tmp_path, size_limit=ONE_MB)
        assert res.compressed is True
        assert res.path == tmp_path / "vid_vertical_tg.mp4"
        assert res.size_bytes == 1024

    def test_stale_compressed_copy_is_rebuilt(self, tmp_path, monkeypatch):
        self._patch_duration(monkeypatch)
        # 旧副本（mtime 早于源）应被重新转码覆盖
        old = _write(tmp_path / "vid_vertical_tg.mp4", 1024)
        os.utime(old, (1, 1))  # 设为很旧
        _write(tmp_path / "vid_vertical.mp4", 2 * ONE_MB)

        rebuilt = {"done": False}

        def fake_transcode(src, dst, vk, ak, ffmpeg_path=None):
            rebuilt["done"] = True
            _write(dst, 2048)

        monkeypatch.setattr(vd, "_transcode_to_fit", fake_transcode)
        res = prepare_for_delivery("vid", output_dir=tmp_path, size_limit=ONE_MB)
        assert rebuilt["done"] is True
        assert res.size_bytes == 2048

    def test_compressed_still_too_big_raises(self, tmp_path, monkeypatch):
        self._patch_duration(monkeypatch)

        def fat_transcode(src, dst, vk, ak, ffmpeg_path=None):
            _write(dst, 3 * ONE_MB)  # 仍超 1MB 上限

        monkeypatch.setattr(vd, "_transcode_to_fit", fat_transcode)
        _write(tmp_path / "vid_vertical.mp4", 2 * ONE_MB)

        with pytest.raises(CompressionError):
            prepare_for_delivery("vid", output_dir=tmp_path, size_limit=ONE_MB)
