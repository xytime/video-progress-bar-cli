"""真实离线媒体夹具与产物断言，不接入生产素材或翻译服务。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-08 | Codex | 固定合成语音、CPU 限并发、完整词序/时序与输出证据 |
"""

import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import wave

import pysubs2
import pytest


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/media"


def run_media(command):
    return subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)


def probe_media(path):
    return json.loads(run_media([
        "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)
    ]).stdout)


@pytest.fixture(scope="module")
def offline_models():
    marker = json.loads((ROOT / ".test-sandbox.json").read_text())
    if "media" not in marker:
        pytest.fail("真实媒体验收必须通过 run_isolated_tests.py --media 执行")
    cache = Path(marker["media"]["model_cache"])
    assert cache.resolve() == ROOT.parent / "cache/whisper"
    for model in ("tiny", "base"):
        assert Path(marker["media"]["models"][model]["snapshot"]) == cache / f"{model}.pt"
        assert (cache / f"{model}.pt").is_file()
    import torch

    previous = torch.get_num_threads()
    torch.set_num_threads(marker["media"]["cpu_threads"])
    try:
        yield
    finally:
        torch.set_num_threads(previous)


@pytest.fixture
def speech_video(tmp_path, offline_models):
    def create(name):
        manifest = json.loads((FIXTURES / "manifest.json").read_text())["files"]
        record = manifest[f"{name}.wav"]
        audio = FIXTURES / f"{name}.wav"
        assert hashlib.sha256(audio.read_bytes()).hexdigest() == record["sha256"]
        with wave.open(str(audio)) as wav:
            assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (16000, 1, 2)
            assert wav.getnframes() == record["frames"]
        video = tmp_path / f"{name}.mp4"
        run_media([
            "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=640x480:r=25",
            "-i", str(audio), "-af", "apad=pad_dur=0.5",
            "-t", str(record["duration_seconds"] + .5), "-c:v", "libx264",
            "-threads", "2", "-pix_fmt", "yuv420p", "-c:a", "aac", str(video)
        ])
        metadata = probe_media(video)
        assert {s["codec_type"] for s in metadata["streams"]} == {"video", "audio"}
        return video, record, metadata
    return create


def assert_subtitles(path, expected_text, duration_seconds):
    subs = pysubs2.load(str(path))
    assert subs.events, "实际生成的字幕为空"
    words = lambda text: re.findall(r"[a-z]+", text.lower())
    actual_text = " ".join(event.plaintext for event in subs.events)
    assert words(actual_text) == words(expected_text), actual_text
    previous_end = 0
    for event in subs.events:
        assert previous_end <= event.start < event.end <= duration_seconds * 1000 + 40
        previous_end = event.end
    return subs


def capture_frame(video, seconds, target):
    run_media(["ffmpeg", "-v", "error", "-y", "-ss", str(seconds), "-i", str(video),
               "-frames:v", "1", str(target)])
    return target


def save_media_evidence(name, paths, checks):
    destination = ROOT.parent / "qa/media" / name
    destination.mkdir(parents=True, exist_ok=True)
    files = {}
    for path in paths:
        target = destination / path.name
        shutil.copyfile(path, target)
        files[path.name] = {"sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                            "bytes": target.stat().st_size}
    (destination / "checks.json").write_text(json.dumps({"checks": checks, "files": files}, indent=2))
