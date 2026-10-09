"""裁剪超时真实进程树与副本清理生命周期回归；仅隔离临时夹具。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-09 | Codex | 关闭全局开关仍终止后代；保护终态绑定和未完成任务。 |
"""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from config.settings import settings
from video_processing.core import ffmpeg_slot
from video_processing.pipeline_manager import PipelineManager
from video_processing.utils.speech_opening_cache import evict_opening_caches, remove_opening_cache


def cache(root, video_id):
    path = root / "speech_opening" / video_id / f"{video_id}.mp4"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"cropped media")
    path.with_suffix(".ass").write_text("zero-based subtitles")
    for entry in path.parent.iterdir():
        os.utime(entry, (1, 1))
    return path


def manager(root, *, evictable=(), pinned=()):
    pm = PipelineManager.__new__(PipelineManager)
    pm._OUT_DIR = root
    pm._ORIG_VIDEO_DIR = root / "original_video"
    pm._ORIG_VIDEO_DIR.mkdir(exist_ok=True)
    pm.db = SimpleNamespace(
        get_source_cache_evictable_ids=lambda days: set(evictable),
        wallstreet_pinned_sources=lambda: set(pinned),
        clear_video_preparation_state=lambda *a, **kw: None,
    )
    return pm


def test_reset_clears_own_cache_and_binding_but_preserves_other_sources(tmp_path):
    pm = manager(tmp_path)
    own, other = cache(tmp_path, "abcdefghijk"), cache(tmp_path, "other")
    raw = pm._ORIG_VIDEO_DIR / "abcdefghijk.mp4"
    raw.write_bytes(b"immutable raw")
    vertical = tmp_path / "abcdefghijk_vertical.mp4"
    vertical.write_bytes(b"vertical")
    binding = vertical.with_suffix(".source.json")
    binding.write_text("{}")
    deleted = pm.reset_video_artifacts("abcdefghijk")
    assert "speech_opening/abcdefghijk/abcdefghijk.mp4" in deleted
    assert not own.parent.exists() and not binding.exists() and not vertical.exists()
    assert other.exists() and raw.read_bytes() == b"immutable raw"


def test_slice_reset_keeps_parent_opening_cache(tmp_path):
    pm = manager(tmp_path)
    parent = cache(tmp_path, "abcdefghijk")
    pm.reset_video_artifacts("abcdefghijk_s1")
    assert parent.exists()


def test_failed_vertical_reset_keeps_bound_inputs(tmp_path, monkeypatch):
    pm = manager(tmp_path)
    prepared = cache(tmp_path, "abcdefghijk")
    vertical = tmp_path / "abcdefghijk_vertical.mp4"
    vertical.write_bytes(b"still referenced")
    binding = vertical.with_suffix(".source.json")
    binding.write_text("{}")
    real_unlink = Path.unlink

    def deny_vertical(path, *args, **kwargs):
        if path == vertical:
            raise PermissionError("test denied")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", deny_vertical)
    pm.reset_video_artifacts("abcdefghijk")
    assert vertical.exists() and binding.exists() and prepared.exists()


def test_ttl_cleans_only_unreferenced_expired_terminal_cache(tmp_path):
    pm = manager(tmp_path, evictable=("done", "bound", "recent", "pinned"), pinned=("pinned",))
    paths = {key: cache(tmp_path, key) for key in ("done", "bound", "recent", "pinned", "pending", "failed", "unknown")}
    (tmp_path / "bound_vertical.source.json").write_text("{}")
    os.utime(paths["recent"], None)
    pm._evict_original_video_dir()
    assert not paths["done"].exists()
    assert all(path.exists() for key, path in paths.items() if key != "done")


@pytest.mark.parametrize("kind", ["cache_parent", "task_directory", "binding", "nested_file"])
def test_ttl_and_reset_cannot_follow_cache_symlinks(tmp_path, kind):
    outside = tmp_path / "unrelated"
    outside.mkdir()
    valuable = outside / "keep.mp4"
    valuable.write_bytes(b"unchanged")
    if kind == "cache_parent":
        (tmp_path / "speech_opening").symlink_to(outside, target_is_directory=True)
    elif kind == "task_directory":
        (tmp_path / "speech_opening").mkdir()
        (tmp_path / "speech_opening/done").symlink_to(outside, target_is_directory=True)
    else:
        prepared = cache(tmp_path, "done")
        if kind == "binding":
            (tmp_path / "done_vertical.source.json").symlink_to(outside / "missing")
        else:
            (prepared.parent / "linked.mp4").symlink_to(valuable)
    assert evict_opening_caches(tmp_path, {"done"}, before=time.time()) == []
    if kind in ("cache_parent", "task_directory"):
        with pytest.raises(ValueError):
            remove_opening_cache(tmp_path, "done")
    else:
        remove_opening_cache(tmp_path, "done")
    assert valuable.read_bytes() == b"unchanged"


def test_invalid_video_id_cannot_escape_cache_root(tmp_path):
    with pytest.raises(ValueError):
        remove_opening_cache(tmp_path, "../unrelated")


@pytest.mark.parametrize("ignore_term", [False, True])
def test_forced_group_timeout_releases_nested_ffmpeg_slot(tmp_path, monkeypatch, ignore_term):
    monkeypatch.setattr(settings, "enable_sigterm_kill", False)
    pm = PipelineManager.__new__(PipelineManager)
    slot, events = tmp_path / "slot", tmp_path / "events"
    fake = tmp_path / "ffmpeg-review"
    fake.write_text(f"#!{sys.executable}\n" +
        "import os,signal,sys,time\n" +
        ("signal.signal(signal.SIGTERM, signal.SIG_IGN)\n" if ignore_term else "") +
        "with open(sys.argv[1],'a') as f: f.write(str(os.getpid())+'\\n'); f.flush()\n"
        "time.sleep(float(sys.argv[2]))\n")
    fake.chmod(0o700)
    wrapper = (
        "from pathlib import Path; import subprocess,sys; "
        "from video_processing.core import ffmpeg_slot as g; "
        "g._DIRECTORY=Path(sys.argv[1]); g.install(); "
        "subprocess.run([sys.argv[2],sys.argv[3],sys.argv[4]],check=True)"
    )
    args = [sys.executable, "-c", wrapper, str(slot), str(fake), str(events), "10"]
    env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src"),
           "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            pm._run_tracked(args, "abcdefghijk", capture_output=True, env=env,
                            timeout=1.5, isolate_process_group=True)
        assert events.is_file(), "后代必须确实启动，不能把启动失败当成清理成功"
        assert (slot / "last-start.json").is_file()
        # 实际重新取得同一个 FFmpeg 执行锁；旧后代仍持锁会使此进程超时。
        next_args = [*args[:-1], "0.05"]
        result = ffmpeg_slot._BASE_POPEN(next_args, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            _, errors = result.communicate(timeout=2)
            assert result.returncode == 0, errors
        finally:
            if result.poll() is None:
                result.kill()
                result.wait(timeout=2)
        assert len(events.read_text().splitlines()) == 2
    finally:
        # 仅清理本测试登记的后代，即使回归失败也不遗留夹具进程。
        if events.is_file():
            for pid in events.read_text().splitlines():
                try:
                    os.kill(int(pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
