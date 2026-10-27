"""失败字幕音频旁证的预算、内容绑定及故障关闭测试；不运行真实模型。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-27 | Codex | 合成音频验证不可变回执、全局段号及自有进程组清理。 |
"""
from copy import deepcopy
import json
from pathlib import Path
import signal
import subprocess
import sys
import time
import wave

import pytest

from video_processing.utils import subtitle_audio_review as review


def _wav(path, duration, *, rate=16000, channels=1):
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(channels)
        stream.setsampwidth(2)
        stream.setframerate(rate)
        stream.writeframes(b"\0\0" * round(duration * rate) * channels)


@pytest.fixture
def example(tmp_path):
    source, model = tmp_path / "source.mp4", tmp_path / "medium.pt"
    source.write_bytes(b"unaltered-video-bytes")
    model.write_bytes(b"synthetic-weights-no-real-model")
    segments = [dict(id=index, start=index * 10, end=(index + 1) * 10,
                     text=f"Original English {index}.", avg_logprob=-.2)
                for index in range(8)]
    return dict(input_path=source, segments=segments,
                quality_details=[dict(source_id=4, segment_number=5)],
                state_dir=tmp_path / "state", model_path=model)


@pytest.fixture
def synthetic_runtime(monkeypatch):
    calls, behavior = [], {"mode": "success", "sandboxed": []}
    def run(args, directory, timeout):
        calls.append((args, directory, timeout))
        assert timeout > 0
        if behavior["mode"] == "timeout":
            raise subprocess.TimeoutExpired(args, timeout)
        if behavior["mode"] == "interrupt":
            raise KeyboardInterrupt()
        if args[0] == "/fake/ffmpeg":
            if behavior["mode"] == "ffmpeg_error":
                return subprocess.CompletedProcess(args, 1, b"", b"PRIVATE STDERR")
            _wav(Path(args[-1]), float(args[args.index("-t") + 1]))
        else:
            if behavior["mode"] == "worker_error":
                return subprocess.CompletedProcess(args, 2, b"", b"PRIVATE STDERR")
            request = json.loads(Path(args[-1]).read_text())
            clips = []
            for item in request["clips"]:
                offset = item["window"]["start"]
                segment = dict(start=0.0, end=1.0, text="Oil is one hundred fifteen dollars.",
                               avg_logprob=-.15, compression_ratio=1.1, no_speech_prob=.001,
                               tokens=[12, 34], words=[dict(word=" Oil", start=0., end=.2,
                                                           probability=.99, absolute_start=offset,
                                                           absolute_end=offset + .2)],
                               absolute_start=offset, absolute_end=offset + 1)
                if behavior["mode"] == "missing_confidence":
                    segment.pop("avg_logprob")
                if behavior["mode"] == "wrong_time":
                    segment["absolute_start"] += 1
                clips.append(dict(window=item["window"], audio_sha256=item["audio_sha256"],
                                  text=segment["text"], language="en", segments=[segment]))
            Path(request["output_path"]).write_text(json.dumps(dict(status="reviewed", clips=clips)))
            if behavior["mode"] == "source_changed":
                source = Path(calls[0][0][calls[0][0].index("-i") + 1])
                source.write_bytes(b"source-replaced-during-review")
        return subprocess.CompletedProcess(args, 0, b"", b"")
    monkeypatch.setattr(review, "_run_command", run)
    monkeypatch.setattr(review.shutil, "which", lambda *args, **kwargs: "/fake/ffmpeg")
    def sandbox(arguments):
        behavior["sandboxed"].append(arguments)
        return arguments
    monkeypatch.setattr(review, "_sandbox_command", sandbox)
    return calls, behavior


def test_success_receipt_binds_all_evidence_and_preserves_originals(example, synthetic_runtime):
    calls, behavior = synthetic_runtime
    original = deepcopy(example["segments"])
    source_hash = review._digest(example["input_path"])
    receipt = review.review_failed_segments(**example)
    assert receipt["status"] == "reviewed" and receipt["diagnostic_only"] is True
    assert receipt["source_unchanged"] is True and example["segments"] == original
    assert review._digest(example["input_path"]) == source_hash
    identity = receipt["identity"]
    assert identity["source_sha256"] == source_hash
    assert identity["segments_sha256"] == review._fingerprint(original)
    assert identity["model_sha256"] == review._digest(example["model_path"])
    assert identity["worker_sha256"] == review._digest(review._WORKER)
    assert identity["helper_sha256"] == review._digest(Path(review.__file__))
    assert identity["target_source_ids"] == [4]
    assert identity["windows"] == [dict(target_source_id=4, source_ids=[3, 4, 5], start=30, end=60)]
    assert calls[0][0][calls[0][0].index("-ar") + 1] == "16000"
    assert calls[0][0][calls[0][0].index("-ac") + 1] == "1"
    assert behavior["sandboxed"] == [call[0] for call in calls]
    path = Path(receipt["receipt_path"])
    raw = path.read_bytes()
    assert receipt["receipt_sha256"] == review._digest(path)
    saved = json.loads(raw)
    assert "receipt_sha256" not in saved
    assert saved["result_sha256"] == review._fingerprint({k: v for k, v in saved.items()
                                                         if k != "result_sha256"})
    clip = receipt["clips"][0]
    assert clip["audio_sha256"] == review._digest(path.parent / "clip-0.wav")
    assert clip["segments"][0]["words"][0]["absolute_start"] == 30
    assert clip["segments"][0]["tokens"] == [12, 34]
    assert review.review_failed_segments(**example) == receipt
    assert path.read_bytes() == raw and len(calls) == 2


def test_windows_keep_real_global_neighbors_and_bound_work(example, synthetic_runtime):
    calls, _ = synthetic_runtime
    example["quality_details"] = [dict(source_id=index, segment_number=index + 1) for index in (0, 4, 7)]
    receipt = review.review_failed_segments(**example)
    assert len(receipt["clips"]) == 2 and len(calls) == 3
    assert receipt["clips"][0]["window"]["source_ids"] == [0, 1]
    assert receipt["clips"][1]["window"]["source_ids"] == [3, 4, 5]
    assert receipt["unreviewed_source_ids"] == [7]
    durations = [clip["window"]["end"] - clip["window"]["start"] for clip in receipt["clips"]]
    assert max(durations) <= 30 and sum(durations) <= 60


def test_window_clips_long_neighbors_but_keeps_entire_target():
    segments = [dict(start=0, end=40, text="previous"), dict(start=40, end=45, text="target"),
                dict(start=45, end=100, text="next")]
    targets, windows = review._windows(segments, [dict(source_id=1)])
    assert targets == [1] and len(windows) == 1
    assert windows[0]["start"] <= 40 and windows[0]["end"] >= 45
    assert windows[0]["end"] - windows[0]["start"] == 30


@pytest.mark.parametrize("detail", [dict(source_id=True), dict(source_id=-1), dict(source_id=999),
                                     dict(source_id=0, segment_number=2),
                                     dict(source_id=0, segment_number=True)])
def test_invalid_global_target_never_selects_unrelated_audio(example, detail):
    example["quality_details"] = [detail]
    receipt = review.review_failed_segments(**example)
    assert receipt["status"] == "unavailable" and receipt["reason_code"] == "no_bounded_review_targets"


@pytest.mark.parametrize("mode,status,reason", [
    ("ffmpeg_error", "unavailable", "audio_extract_failed"),
    ("worker_error", "unavailable", "audio_worker_failed"),
    ("missing_confidence", "unavailable", "worker_confidence_missing"),
    ("wrong_time", "unavailable", "worker_timing_invalid"),
    ("timeout", "timeout", "review_budget_exhausted"),
    ("interrupt", "interrupted", "audio_review_interrupted"),
    ("source_changed", "blocked", "source_changed"),
])
def test_failure_diagnostics_are_atomic_immutable_and_safe(example, synthetic_runtime, mode, status, reason):
    calls, behavior = synthetic_runtime
    behavior["mode"] = mode
    receipt = review.review_failed_segments(**example)
    assert receipt["status"] == status and receipt["reason_code"] == reason
    path = Path(receipt["receipt_path"])
    assert receipt["receipt_sha256"] == review._digest(path)
    assert "PRIVATE" not in path.read_text()
    saved = path.read_bytes()
    if mode != "source_changed":
        count = len(calls)
        assert review.review_failed_segments(**example) == receipt
        assert len(calls) == count and path.read_bytes() == saved


@pytest.mark.parametrize("tamper", ["receipt", "audio"])
def test_changed_evidence_is_never_reused_or_overwritten(example, synthetic_runtime, tamper):
    calls, _ = synthetic_runtime
    receipt = review.review_failed_segments(**example)
    path = Path(receipt["receipt_path"])
    if tamper == "receipt":
        data = json.loads(path.read_text())
        data["clips"][0]["segments"][0]["text"] = "altered"
        path.write_text(json.dumps(data))
    else:
        (path.parent / "clip-0.wav").write_bytes(b"altered")
    before = path.read_bytes()
    rejected = review.review_failed_segments(**example)
    assert rejected["status"] != "reviewed"
    assert rejected["reason_code"] in {"receipt_integrity_invalid", "worker_binding_invalid"}
    assert path.read_bytes() == before and len(calls) == 2


def test_missing_local_model_is_explicit_and_does_not_start_process(example, monkeypatch):
    example["model_path"] = example["model_path"].with_name("missing-medium.pt")
    monkeypatch.setattr(review, "_run_command", lambda *args: pytest.fail("must not execute or download"))
    receipt = review.review_failed_segments(**example)
    assert receipt["reason_code"] == "local_medium_missing" and receipt["status"] == "unavailable"
    assert Path(receipt["receipt_path"]).is_file()


def test_default_model_uses_existing_settings_directory(tmp_path, monkeypatch):
    from config.settings import settings
    monkeypatch.setattr(settings, "source_audio_model_path", tmp_path / "base.pt")
    assert review._default_model_path() == tmp_path / "medium.pt"


def test_extractor_and_worker_share_mandatory_network_denial(tmp_path):
    request = tmp_path / "request.json"
    worker = review._offline_command(request)
    extractor = review._sandbox_command(["ffmpeg", "-i", "local.mp4"])
    prefix = ["/usr/bin/sandbox-exec", "-p", "(version 1)(allow default)(deny network*)"]
    assert worker[:3] == extractor[:3] == prefix
    assert worker[3:] == [sys.executable, "-I", "-B", str(review._WORKER), str(request)]
    assert extractor[3:] == ["ffmpeg", "-i", "local.mp4"]


@pytest.mark.parametrize("budget", [0, -1, float("nan"), True])
def test_invalid_budget_returns_diagnostic_without_raising(example, budget):
    receipt = review.review_failed_segments(**example, timeout_sec=budget)
    assert receipt["reason_code"] == "invalid_review_budget" and receipt["status"] == "unavailable"


def test_process_launch_strips_business_environment_and_always_cleans_group(tmp_path, monkeypatch):
    calls, signals = [], []
    class Process:
        pid, returncode = 123, 0
        def communicate(self, timeout=None):
            return b"", b""
    def popen(args, **kwargs):
        calls.append(kwargs)
        return Process()
    monkeypatch.setattr(review.subprocess, "Popen", popen)
    monkeypatch.setattr(review.os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    review._run_command(["worker"], tmp_path, 1)
    assert calls[0]["start_new_session"] is True
    assert set(calls[0]["env"]) == {"PATH", "LANG", "PYTHONDONTWRITEBYTECODE"}
    assert signals == [(123, signal.SIGTERM), (123, signal.SIGKILL)]


def test_keyboard_interrupt_cleans_group_before_propagating(tmp_path, monkeypatch):
    signals = []
    class Process:
        pid, calls = 123, 0
        def communicate(self, timeout=None):
            self.calls += 1
            if self.calls == 1:
                raise KeyboardInterrupt()
            return b"", b""
    process = Process()
    monkeypatch.setattr(review.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(review.os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    with pytest.raises(KeyboardInterrupt):
        review._run_command(["worker"], tmp_path, 1)
    assert signals == [(123, signal.SIGTERM), (123, signal.SIGKILL)] and process.calls == 3


def test_stuck_inherited_pipe_cannot_make_timeout_cleanup_unbounded(tmp_path, monkeypatch):
    closed, waits, signals = [], [], []
    class Stream:
        def close(self):
            closed.append(True)
    class Process:
        pid, stdout, stderr = 123, Stream(), Stream()
        def communicate(self, timeout=None):
            assert timeout is not None
            raise subprocess.TimeoutExpired("worker", timeout)
        def wait(self, timeout=None):
            waits.append(timeout)
    monkeypatch.setattr(review.subprocess, "Popen", lambda *args, **kwargs: Process())
    monkeypatch.setattr(review.os, "killpg", lambda pid, sig: signals.append(sig))
    with pytest.raises(subprocess.TimeoutExpired):
        review._run_command(["worker"], tmp_path, 1)
    assert closed == [True, True] and waits == [.5]
    assert signals == [signal.SIGTERM, signal.SIGKILL]


def test_timeout_terminates_real_owned_descendant_group(tmp_path):
    heartbeat = tmp_path / "heartbeat.txt"
    child = """import signal,sys,time
from pathlib import Path
signal.signal(signal.SIGTERM, signal.SIG_IGN)
path=Path(sys.argv[1])
while True:
    with path.open('a') as stream: stream.write('x'); stream.flush()
    time.sleep(.02)
"""
    parent = """import subprocess,sys,time
subprocess.Popen([sys.executable,'-I','-B','-c',sys.argv[1],sys.argv[2]])
time.sleep(30)
"""
    with pytest.raises(subprocess.TimeoutExpired):
        review._run_command([sys.executable, "-I", "-B", "-c", parent, child, str(heartbeat)], tmp_path, .6)
    assert heartbeat.is_file() and heartbeat.stat().st_size > 0
    size = heartbeat.stat().st_size
    time.sleep(.12)
    assert heartbeat.stat().st_size == size
