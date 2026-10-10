"""首尾清理的隔离回归；合成故障夹具不能充当真实 TED 准确率。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-10 | Codex | 全音画匹配、缓存修复、失败重试、旧绑定及生产入口。 |
"""
import json
from pathlib import Path
import subprocess

import pytest

from video_processing.processors import ted_source_cleanup as cleanup
from video_processing.utils.render_source_binding import bind_render_source


@pytest.fixture
def packaged_source(tmp_path, monkeypatch):
    source = tmp_path / "abcdefghijk.mp4"
    fixture = Path(__file__).resolve().parents[1] / "fixtures/media/caption_speech.wav"
    subprocess.run([
        cleanup.media.resolve_ffmpeg_cmd(), "-v", "error", "-y", "-f", "lavfi", "-i",
        "testsrc2=size=320x180:rate=30:duration=12", "-f", "lavfi", "-i",
        "sine=frequency=880:sample_rate=16000:duration=4", "-i", str(fixture),
        "-filter_complex", "[1:a][2:a]concat=n=2:v=0:a=1,apad[a]",
        "-map", "0:v", "-map", "[a]", "-t", "12", "-c:v", "libx264", "-threads", "2",
        "-c:a", "aac", str(source),
    ], check=True, capture_output=True, timeout=30)
    info = cleanup.media.media_info(source)
    shape = cleanup.media.prefix_shape(info)
    manifest = tmp_path / "packaging.json"
    manifest.write_text(json.dumps({"version": 1, "prefixes": [{"seconds": 3.5, "shape": shape,
        "decoded_av_sha256": cleanup.media.decoded_prefix_sha256(source, 3.5, shape)}],
        "suffixes": [{"seconds": 2, "shape": shape,
        "decoded_av_sha256": cleanup.suffix_digest(source, 10, shape)}]}))
    legacy = tmp_path / "legacy.json"
    legacy.write_text(json.dumps({"version": 1, "prefixes": []}))
    monkeypatch.setattr(cleanup, "PACKAGING", manifest)
    monkeypatch.setattr(cleanup.media, "PREFIXES", legacy)
    return source


def test_real_decode_both_edges_and_corrupt_cache_recovery(packaged_source, tmp_path, monkeypatch):
    before = cleanup.media.sha256(packaged_source)
    target = tmp_path / "prepared"
    selected, receipt = cleanup.prepare_source(packaged_source, target)
    assert selected != packaged_source, receipt
    assert receipt["offset_seconds"] == 3.5 and receipt["end_seconds"] == 10
    cleanup.media.validate_prepared(selected, 6.5)
    assert cleanup.media.sha256(packaged_source) == before
    with monkeypatch.context() as patch:
        patch.setattr(cleanup, "detect_packaging", lambda *_: pytest.fail("缓存不应再次检测"))
        assert cleanup.prepare_source(packaged_source, target) == (selected, receipt)
    selected.write_bytes(b"corrupt")
    repaired, retry = cleanup.prepare_source(packaged_source, target)
    assert repaired == selected and retry["reason"] == "VERIFIED_AV_PACKAGING"
    cleanup.media.validate_prepared(repaired, 6.5)
    repaired.with_suffix(".opening.json").write_text("broken")
    assert cleanup.prepare_source(packaged_source, target)[0] == repaired


@pytest.mark.parametrize("filter_name", ["volume=0.1", "hue=s=0"])
def test_changed_audio_or_visual_packaging_is_preserved(packaged_source, tmp_path, filter_name):
    changed = tmp_path / "changed.mp4"
    subprocess.run([cleanup.media.resolve_ffmpeg_cmd(), "-v", "error", "-y", "-i", str(packaged_source),
                    "-af" if filter_name.startswith("volume") else "-vf", filter_name,
                    "-c:v", "libx264", "-threads", "2", "-c:a", "aac", str(changed)],
                   check=True, capture_output=True, timeout=30)
    selected, receipt = cleanup.prepare_source(changed, tmp_path / "changed-output")
    assert selected == changed and receipt["offset_seconds"] == 0
    assert receipt["reason"] == "UNVERIFIED_AV_PACKAGING"


def test_decode_failure_retries_and_receipt_write_failure_still_returns_original(packaged_source, tmp_path, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(cleanup, "detect_packaging", lambda *_: (_ for _ in ()).throw(RuntimeError("decode")))
        patch.setattr(cleanup.media, "atomic_json", lambda *_: (_ for _ in ()).throw(PermissionError("receipt")))
        selected, receipt = cleanup.prepare_source(packaged_source, tmp_path / "prepared")
        assert selected == packaged_source and receipt["reason"] == "UNAVAILABLE_RuntimeError"
        assert receipt["receipt_write_failed"]
    assert cleanup.prepare_source(packaged_source, tmp_path / "prepared")[0] != packaged_source


def test_storage_failure_does_not_touch_original(packaged_source, tmp_path, monkeypatch):
    from collections import namedtuple
    monkeypatch.setattr(cleanup.shutil, "disk_usage", lambda *_: namedtuple("Usage", "free")(0))
    selected, receipt = cleanup.prepare_source(packaged_source, tmp_path / "prepared")
    assert selected == packaged_source and receipt["failure_code"] == "INSUFFICIENT_STORAGE"
    assert not (tmp_path / "prepared/abcdefghijk.mp4").exists()


def test_overlap_symlink_and_nonzero_timebase_preserve(packaged_source, tmp_path):
    before = cleanup.media.sha256(packaged_source)
    assert cleanup.prepare_source(packaged_source, packaged_source.parent)[0] == packaged_source
    link = tmp_path / "link"
    link.symlink_to(tmp_path, target_is_directory=True)
    assert cleanup.prepare_source(packaged_source, link / "prepared")[0] == packaged_source
    assert not (tmp_path / "prepared").exists(), "非法路径不能借写回退收据跟随链接"
    info = cleanup.media.media_info(packaged_source)
    info["streams"]["audio"]["start_time"] = "0.1"
    assert cleanup.detect_packaging(packaged_source, info)["reason"] == "UNSUPPORTED_SOURCE_TIMEBASE"
    assert cleanup.media.sha256(packaged_source) == before


def manager(tmp_path, monkeypatch):
    from config.settings import settings
    from video_processing.pipeline_manager import PipelineManager
    monkeypatch.setattr(settings, "enable_ted_source_cleanup", True)
    pm = PipelineManager.__new__(PipelineManager)
    pm._OUT_DIR, pm._PRJ_ROOT, pm._SRC_DIR = tmp_path, tmp_path, tmp_path / "src"
    pm._VENV_PYTHON = "python"
    return pm


def test_finished_binding_pinned_even_with_old_receipt(tmp_path, monkeypatch):
    pm = manager(tmp_path, monkeypatch)
    video = {"youtube_id": "abcdefghijk", "channel_id": "UCAuUUnT6oDeKwE6v1NGQxug"}
    source = tmp_path / "original.mp4"
    prepared = tmp_path / "speech_opening/abcdefghijk/abcdefghijk.mp4"
    prepared.parent.mkdir(parents=True)
    prepared.write_bytes(b"historical")
    prepared.with_suffix(".ass").write_text("historical timeline")
    prepared.with_suffix(".opening.json").write_text('{"recipe":"speech-opening-v2"}')
    vertical = tmp_path / "abcdefghijk_vertical.mp4"
    vertical.write_bytes(b"finished")
    monkeypatch.setattr(pm, "_run_tracked", lambda *_args, **_kwargs: pytest.fail("不得改历史时间轴"))
    assert pm._prepare_speech_opening(video, source) == source
    bind_render_source(vertical, prepared, prepared.with_suffix(".ass"))
    assert pm._prepare_speech_opening(video, source) == prepared
    from config.settings import settings
    monkeypatch.setattr(settings, "enable_ted_source_cleanup", False)
    monkeypatch.setattr(settings, "enable_ted_opening_trim", False)
    assert pm._prepare_speech_opening(video, source) == prepared
    prepared.write_bytes(b"broken historical input")
    assert pm._prepare_speech_opening(video, source) == source


def test_new_source_uses_cleanup_and_failed_subprocess_falls_back(tmp_path, monkeypatch):
    pm = manager(tmp_path, monkeypatch)
    source = tmp_path / "abcdefghijk.mp4"
    source.write_bytes(b"source")
    calls = []
    def process(command, *_args, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, json.dumps({"selected": str(source),
            "receipt": {"offset_seconds": 0, "end_seconds": 12, "reason": "UNVERIFIED_AV_PACKAGING"}}))
    monkeypatch.setattr(pm, "_run_tracked", process)
    video = {"youtube_id": "abcdefghijk", "channel_id": "UCAuUUnT6oDeKwE6v1NGQxug"}
    assert pm._prepare_speech_opening(video, source) == source
    assert calls[0][2] == "video_processing.processors.ted_source_cleanup"
    monkeypatch.setattr(pm, "_run_tracked", lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError()))
    assert pm._prepare_speech_opening(video, source) == source


def test_both_flags_off_slices_and_manual_ranges_never_cleanup(tmp_path, monkeypatch):
    from config.settings import settings
    pm = manager(tmp_path, monkeypatch)
    monkeypatch.setattr(pm, "_run_tracked", lambda *_args, **_kwargs: pytest.fail("不应清理"))
    source = tmp_path / "original.mp4"
    base = {"youtube_id": "abcdefghijk", "channel_id": "UCAuUUnT6oDeKwE6v1NGQxug"}
    for change in ({"slice_index": 1}, {"trim_start": "0"}, {"trim_end": "10"}, {"channel_id": "other"}):
        assert pm._prepare_speech_opening({**base, **change}, source) == source
    monkeypatch.setattr(settings, "enable_ted_source_cleanup", False)
    monkeypatch.setattr(settings, "enable_ted_opening_trim", False)
    assert pm._prepare_speech_opening(base, source) == source
