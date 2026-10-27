"""离线 medium 复核 worker；只读已有模型和短 WAV，不修改原字幕。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-27 | Codex | 固定 CPU 解码、禁网络、保存完整相对及绝对时间旁证。 |
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import socket
import sys
import tempfile
import wave


_DECODE = {"model": "medium", "language": "en", "device": "cpu", "threads": 4,
           "temperature": 0, "condition_on_previous_text": False,
           "word_timestamps": True, "fp16": False}


def _digest(path):
    checksum = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


@contextmanager
def _offline():
    names = ("connect", "connect_ex", "bind", "sendto", "sendmsg")
    methods = {name: getattr(socket.socket, name) for name in names if hasattr(socket.socket, name)}
    original_connect, original_lookup = socket.create_connection, socket.getaddrinfo
    def denied(*args, **kwargs):
        raise OSError("audio_review_network_disabled")
    for name in methods:
        setattr(socket.socket, name, denied)
    socket.create_connection, socket.getaddrinfo = denied, denied
    try:
        yield
    finally:
        for name, method in methods.items():
            setattr(socket.socket, name, method)
        socket.create_connection, socket.getaddrinfo = original_connect, original_lookup


def _load_model(path):
    import torch
    import whisper
    torch.set_num_threads(4)
    model = whisper.load_model(str(path), device="cpu")
    if any(getattr(model.dims, key, None) != expected for key, expected in {
            "n_audio_layer": 24, "n_text_layer": 24, "n_audio_state": 1024, "n_text_state": 1024}.items()):
        raise ValueError("local_model_is_not_medium")
    return model


def review(request):
    if any(request.get("recipe", {}).get(key) != value for key, value in _DECODE.items()):
        raise ValueError("review_recipe_invalid")
    model = Path(request["model_path"])
    if not model.is_absolute() or not model.is_file() or model.suffix != ".pt":
        raise ValueError("existing_absolute_model_required")
    if _digest(model) != request["model_sha256"] or _digest(Path(__file__)) != request["worker_sha256"]:
        raise ValueError("worker_identity_mismatch")
    clips = request["clips"]
    if not 0 < len(clips) <= 2:
        raise ValueError("review_windows_invalid")
    bounds = [(item["window"]["start"], item["window"]["end"]) for item in clips]
    if any(type(value) not in (float, int) or not math.isfinite(value)
           for pair in bounds for value in pair):
        raise ValueError("review_duration_invalid")
    durations = [end - start for start, end in bounds]
    if any(start < 0 or not 0 < end - start <= 30 for start, end in bounds) or sum(durations) > 60:
        raise ValueError("review_duration_invalid")
    # 在加载大模型前先拒绝错误音频，避免无效诊断占用模型预算。
    for item, duration in zip(clips, durations):
        audio = Path(item["path"])
        if not audio.is_absolute() or _digest(audio) != item["audio_sha256"]:
            raise ValueError("audio_binding_mismatch")
        with wave.open(str(audio)) as stream:
            if (stream.getframerate() != 16000 or stream.getnchannels() != 1
                    or abs(stream.getnframes() / stream.getframerate() - duration) > .1):
                raise ValueError("audio_clip_invalid")
    result = {"status": "reviewed", "diagnostic_only": True, "clips": []}
    with _offline():
        engine = _load_model(model)
        for item in clips:
            audio = Path(item["path"])
            decoded = engine.transcribe(str(audio), language="en", fp16=False, temperature=0,
                                        condition_on_previous_text=False, word_timestamps=True, verbose=None)
            segments = deepcopy(decoded.get("segments", []))
            if not segments:
                raise ValueError("audio_transcript_empty")
            for segment in segments:
                for timed in [segment, *segment.get("words", [])]:
                    timed["absolute_start"] = item["window"]["start"] + timed["start"]
                    timed["absolute_end"] = item["window"]["start"] + timed["end"]
            result["clips"].append({"window": item["window"], "audio_sha256": item["audio_sha256"],
                                    "text": decoded.get("text", ""), "language": decoded.get("language"),
                                    "segments": segments})
    if _digest(model) != request["model_sha256"]:
        raise ValueError("model_changed_during_review")
    return result


def main():
    request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    result = review(request)
    destination = Path(request["output_path"])
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=destination.parent,
                                     suffix=".tmp", delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(result, stream, ensure_ascii=False, allow_nan=False)
    temporary.replace(destination)


if __name__ == "__main__":
    main()
