"""失败字幕的有界离线音频旁证；只诊断，不改 ASR、译文或业务状态。

依赖：字幕 provider -> 本模块 -> 独立 worker；默认模型位置仅从 settings 读取。
# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-27 | Codex | 最多两段邻接短音频、离线 medium、内容绑定及不可变诊断回执。 |
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import wave


RECIPE = {
    "version": 1, "model": "medium", "language": "en", "device": "cpu",
    "threads": 4, "temperature": 0, "condition_on_previous_text": False,
    "word_timestamps": True, "fp16": False, "max_windows": 2,
    "max_window_seconds": 30, "max_total_audio_seconds": 60,
}
_WORKER = Path(__file__).with_name("subtitle_audio_review_worker.py")
_SYSTEM_PATH = "/opt/homebrew/bin:/usr/bin:/bin"


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     allow_nan=False).encode()).hexdigest()


def _digest(path, deadline=None):
    checksum = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("review_budget_exhausted")
            checksum.update(chunk)
    return checksum.hexdigest()


def _default_model_path():
    from config.settings import settings
    root = getattr(settings, "whisper_download_root", None)
    if root is None:
        root = Path(settings.source_audio_model_path).expanduser().parent
    return (Path(root).expanduser() / "medium.pt").resolve()


def _windows(segments, quality_details):
    previous = -1.0
    for segment in segments:
        if not isinstance(segment, dict) or not isinstance(segment.get("text"), str):
            raise ValueError("invalid_source_segments")
        start, end = segment.get("start"), segment.get("end")
        if (type(start) not in (float, int) or type(end) not in (float, int)
                or not math.isfinite(start) or not math.isfinite(end)
                or start < 0 or end < start or start < previous):
            raise ValueError("invalid_source_segments")
        previous = start
    targets = sorted({detail["source_id"] for detail in quality_details
                      if isinstance(detail, dict) and type(detail.get("source_id")) is int
                      and 0 <= detail["source_id"] < len(segments)
                      and ("segment_number" not in detail
                           or (type(detail["segment_number"]) is int
                               and detail["segment_number"] == detail["source_id"] + 1))})
    windows = []
    for target in targets[:RECIPE["max_windows"]]:
        segment = segments[target]
        duration = segment["end"] - segment["start"]
        if not 0 < duration <= RECIPE["max_window_seconds"]:
            continue
        ids = list(range(max(0, target - 1), min(len(segments), target + 2)))
        earliest = min(segments[index]["start"] for index in ids)
        latest = max(segments[index]["end"] for index in ids)
        extra = RECIPE["max_window_seconds"] - duration
        left = min(segment["start"] - earliest, extra / 2)
        right = min(latest - segment["end"], extra - left)
        left = min(segment["start"] - earliest, extra - right)
        windows.append({"target_source_id": target, "source_ids": ids,
                        "start": segment["start"] - left, "end": segment["end"] + right})
    return targets, windows


@contextmanager
def _interruptible():
    previous = None
    if threading.current_thread() is threading.main_thread():
        previous = signal.getsignal(signal.SIGTERM)
        def interrupted(number, frame):
            if callable(previous):
                previous(number, frame)
            raise InterruptedError("audio_review_interrupted")
        signal.signal(signal.SIGTERM, interrupted)
    try:
        yield
    finally:
        if previous is not None:
            signal.signal(signal.SIGTERM, previous)


def _run_command(args, directory, timeout):
    """只建立自有进程组；超时、信号或异常均清理该组，不继承业务环境。"""
    if timeout <= 0:
        raise TimeoutError("review_budget_exhausted")
    environment = {"PATH": str(Path(sys.executable).parent) + ":" + _SYSTEM_PATH,
                   "LANG": "en_US.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"}
    with _interruptible():
        process = subprocess.Popen(args, cwd=directory, env=environment,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True)
        try:
            stdout, stderr = process.communicate(timeout=timeout)
            return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
        finally:
            # TERM 后即使直接子进程已退出，也清理仍占有同组的后代。
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.communicate(timeout=.5)
            except subprocess.TimeoutExpired:
                pass
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    process.communicate(timeout=.5)
                except subprocess.TimeoutExpired:
                    # 异常后代即使逃离该组且持有管道，也不得使主字幕任务无限等待。
                    for stream in (process.stdout, process.stderr):
                        if stream is not None:
                            stream.close()
                    try:
                        process.wait(timeout=.5)
                    except subprocess.TimeoutExpired:
                        raise TimeoutError("audio_process_cleanup_timeout")


def _sandbox_command(arguments):
    sandbox = Path("/usr/bin/sandbox-exec")
    if not sandbox.is_file():
        raise FileNotFoundError("offline_sandbox_unavailable")
    return [str(sandbox), "-p", "(version 1)(allow default)(deny network*)", *arguments]


def _offline_command(request):
    return _sandbox_command([sys.executable, "-I", "-B", str(_WORKER), str(request)])


def _atomic_json(path, value):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".receipt-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _validated_clips(data, windows, directory):
    if data.get("status") != "reviewed" or len(data.get("clips", [])) != len(windows):
        raise ValueError("worker_output_invalid")
    for index, (clip, window) in enumerate(zip(data["clips"], windows)):
        if (clip.get("window") != window or clip.get("audio_sha256") != _digest(directory / f"clip-{index}.wav")
                or not isinstance(clip.get("segments"), list) or not clip["segments"]):
            raise ValueError("worker_binding_invalid")
        for segment in clip["segments"]:
            if (not isinstance(segment, dict) or not isinstance(segment.get("text"), str)
                    or not isinstance(segment.get("words"), list)):
                raise ValueError("worker_output_invalid")
            for metric in ("avg_logprob", "compression_ratio", "no_speech_prob"):
                if type(segment.get(metric)) not in (float, int) or not math.isfinite(segment[metric]):
                    raise ValueError("worker_confidence_missing")
            for item in [segment, *segment.get("words", [])]:
                start, end = item.get("start"), item.get("end")
                if (type(start) not in (float, int) or type(end) not in (float, int)
                        or not math.isfinite(start) or not math.isfinite(end)
                        or not 0 <= start <= end <= window["end"] - window["start"] + .1
                        or item.get("absolute_start") != window["start"] + start
                        or item.get("absolute_end") != window["start"] + end):
                    raise ValueError("worker_timing_invalid")
    return data["clips"]


def review_failed_segments(input_path: Path, segments: list[dict], quality_details: list[dict],
                           state_dir: Path, *, model_path: Path | None = None,
                           timeout_sec=120) -> dict:
    """返回不可变诊断回执；无模型/超时/失败均不覆盖调用方的翻译错误。"""
    started = time.monotonic()
    receipt = {"status": "unavailable", "diagnostic_only": True, "reason_code": "uninitialized",
               "clips": [], "source_unchanged": None}
    directory = None
    try:
        if type(timeout_sec) not in (float, int) or not math.isfinite(timeout_sec) or timeout_sec <= 0:
            raise ValueError("invalid_review_budget")
        deadline = started + timeout_sec
        source = Path(input_path).resolve(strict=True)
        targets, windows = _windows(segments, quality_details)
        model = Path(model_path) if model_path is not None else _default_model_path()
        if not model.is_absolute():
            raise ValueError("absolute_model_path_required")
        model = model.resolve()
        identity = {"recipe": dict(RECIPE), "timeout_sec": timeout_sec,
                    "input_path": str(source), "source_sha256": _digest(source, deadline),
                    "segments_sha256": _fingerprint(segments), "target_source_ids": targets,
                    "windows": windows, "model_path": str(model),
                    "model_sha256": _digest(model, deadline) if model.is_file() else None,
                    "worker_sha256": _digest(_WORKER), "helper_sha256": _digest(Path(__file__))}
        directory = Path(state_dir).resolve() / "subtitle-audio-review" / _fingerprint(identity)
        directory.mkdir(parents=True, exist_ok=True)
        receipt.update(identity=identity, receipt_path=str(directory / "receipt.json"))
        with (directory / "review.lock").open("a+") as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return dict(receipt, reason_code="review_busy")
            path = directory / "receipt.json"
            if path.exists():
                saved = json.loads(path.read_text(encoding="utf-8"))
                unsigned = {key: value for key, value in saved.items() if key != "result_sha256"}
                if saved.get("identity") != identity or saved.get("result_sha256") != _fingerprint(unsigned):
                    return dict(receipt, status="blocked", reason_code="receipt_integrity_invalid")
                if saved.get("status") == "reviewed":
                    _validated_clips(saved, windows, directory)
                return dict(saved, receipt_sha256=_digest(path))
            try:
                if any(item.name != "review.lock" for item in directory.iterdir()):
                    receipt.update(status="blocked", reason_code="previous_attempt_incomplete")
                elif not targets or not windows:
                    receipt.update(reason_code="no_bounded_review_targets")
                elif identity["model_sha256"] is None or model.suffix != ".pt":
                    receipt.update(reason_code="local_medium_missing")
                else:
                    _perform_review(source, model, identity, windows, directory, deadline, receipt)
                receipt["source_unchanged"] = _digest(source, deadline) == identity["source_sha256"]
                if not receipt["source_unchanged"]:
                    receipt.update(status="blocked", reason_code="source_changed")
                elif identity["model_sha256"] is not None and _digest(model, deadline) != identity["model_sha256"]:
                    receipt.update(status="blocked", reason_code="model_changed")
            except BaseException as exc:
                _record_failure(receipt, exc)
            receipt["result_sha256"] = _fingerprint(receipt)
            _atomic_json(path, receipt)
            # 文件自身的 SHA 只放返回值，避免自引用或改写已完成的回执。
            return dict(receipt, receipt_sha256=_digest(path))
    except BaseException as exc:
        _record_failure(receipt, exc)
    return receipt


def _record_failure(receipt, exc):
    if isinstance(exc, (KeyboardInterrupt, InterruptedError)):
        receipt.update(status="interrupted", reason_code="audio_review_interrupted")
    elif isinstance(exc, (TimeoutError, subprocess.TimeoutExpired)):
        receipt.update(status="timeout", reason_code="review_budget_exhausted")
    elif isinstance(exc, Exception):
        code = str(exc) if isinstance(exc, (ValueError, FileNotFoundError)) else type(exc).__name__
        receipt.update(status="unavailable", reason_code=code[:160])
    else:
        raise exc


def _perform_review(source, model, identity, windows, directory, deadline, receipt):
    ffmpeg = shutil.which("ffmpeg", path=_SYSTEM_PATH)
    if ffmpeg is None:
        raise FileNotFoundError("ffmpeg_unavailable")
    request_clips = []
    for index, window in enumerate(windows):
        audio = directory / f"clip-{index}.wav"
        result = _run_command(_sandbox_command([
                               ffmpeg, "-nostdin", "-v", "error", "-n", "-ss", str(window["start"]),
                               "-i", str(source), "-t", str(window["end"] - window["start"]),
                               "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", str(audio)]),
                              directory, deadline - time.monotonic())
        if result.returncode != 0:
            raise ValueError("audio_extract_failed")
        with wave.open(str(audio)) as stream:
            duration = stream.getnframes() / stream.getframerate()
            if (stream.getframerate() != 16000 or stream.getnchannels() != 1
                    or abs(duration - (window["end"] - window["start"])) > .1):
                raise ValueError("audio_clip_invalid")
        request_clips.append({"path": str(audio), "audio_sha256": _digest(audio, deadline), "window": window})
    request = {"recipe": dict(RECIPE), "model_path": str(model), "model_sha256": identity["model_sha256"],
               "worker_sha256": identity["worker_sha256"], "clips": request_clips,
               "output_path": str(directory / "worker-result.json")}
    request_path = directory / "request.json"
    _atomic_json(request_path, request)
    result = _run_command(_offline_command(request_path), directory, deadline - time.monotonic())
    if result.returncode != 0:
        raise ValueError("audio_worker_failed")
    data = json.loads((directory / "worker-result.json").read_text(encoding="utf-8"))
    receipt.update(status="reviewed", reason_code="diagnosis_only",
                   clips=_validated_clips(data, windows, directory),
                   unreviewed_source_ids=[target for target in identity["target_source_ids"]
                                          if target not in {item["target_source_id"] for item in windows}])
