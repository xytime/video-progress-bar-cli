"""离线音频 worker 的本地模型、固定解码与完整旁证测试；不加载真实权重。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-27 | Codex | 合成 worker 验证网络关闭、模型绑定、绝对时间和解码证据保留。 |
"""
from copy import deepcopy
from pathlib import Path
import socket
import sys
from types import SimpleNamespace
import wave

import pytest

from video_processing.utils.subtitle_audio_review import RECIPE
from video_processing.utils import subtitle_audio_review_worker as worker


@pytest.fixture
def request_payload(tmp_path):
    model, audio = tmp_path / "medium.pt", tmp_path / "clip.wav"
    model.write_bytes(b"synthetic-local-weights")
    with wave.open(str(audio), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(b"\0\0" * 16000)
    return dict(recipe=dict(RECIPE), model_path=str(model), model_sha256=worker._digest(model),
                worker_sha256=worker._digest(Path(worker.__file__)),
                clips=[dict(path=str(audio), audio_sha256=worker._digest(audio),
                            window=dict(target_source_id=79, source_ids=[78, 79, 80], start=20., end=21.))])


def _decoded():
    return dict(text="Oil is $115.", language="en", segments=[
        dict(id=0, start=0., end=.9, seek=0, text="Oil is $115.", temperature=0.,
             avg_logprob=-.12, compression_ratio=.9, no_speech_prob=.001, tokens=[1, 2, 3],
             words=[dict(word=" Oil", start=.1, end=.2, probability=.98),
                    dict(word=" $115.", start=.3, end=.9, probability=.99)])])


def test_worker_keeps_full_decode_and_absolute_time_without_mutating_source(request_payload, monkeypatch):
    calls, decoded = [], _decoded()
    original = deepcopy(decoded)
    class Engine:
        def transcribe(self, path, **kwargs):
            calls.append((path, kwargs))
            with pytest.raises(OSError, match="audio_review_network_disabled"):
                socket.getaddrinfo("example.invalid", 443)
            return decoded
    monkeypatch.setattr(worker, "_load_model", lambda path: Engine())
    result = worker.review(request_payload)
    assert result["status"] == "reviewed" and result["diagnostic_only"] is True
    assert decoded == original
    assert calls == [(request_payload["clips"][0]["path"], dict(language="en", fp16=False,
        temperature=0, condition_on_previous_text=False, word_timestamps=True, verbose=None))]
    clip = result["clips"][0]
    assert clip["audio_sha256"] == request_payload["clips"][0]["audio_sha256"]
    assert clip["window"] == request_payload["clips"][0]["window"]
    segment = clip["segments"][0]
    assert (segment["absolute_start"], segment["absolute_end"]) == (20, 20.9)
    assert segment["words"][1]["absolute_start"] == 20.3
    for key in ("avg_logprob", "no_speech_prob", "compression_ratio", "tokens", "temperature", "seek"):
        assert segment[key] == original["segments"][0][key]
    assert segment["words"][1]["probability"] == .99


@pytest.mark.parametrize("change,reason", [
    ("relative_model", "existing_absolute_model_required"),
    ("model_name", "existing_absolute_model_required"),
    ("missing_model", "existing_absolute_model_required"),
    ("model_sha", "worker_identity_mismatch"),
    ("worker_sha", "worker_identity_mismatch"),
    ("audio_sha", "audio_binding_mismatch"),
    ("audio_name", "audio_binding_mismatch"),
    ("too_many_clips", "review_windows_invalid"),
    ("empty_clips", "review_windows_invalid"),
    ("over_duration", "review_duration_invalid"),
    ("negative_start", "review_duration_invalid"),
    ("nonfinite", "review_duration_invalid"),
    ("recipe", "review_recipe_invalid"),
])
def test_invalid_request_is_rejected_before_loading_model(request_payload, monkeypatch, change, reason):
    if change == "relative_model":
        request_payload["model_path"] = "local/medium.pt"
    elif change == "model_name":
        request_payload["model_path"] = "medium"
    elif change == "missing_model":
        request_payload["model_path"] = str(Path(request_payload["model_path"]).with_name("missing.pt"))
    elif change in {"model_sha", "worker_sha"}:
        request_payload[change + "256"] = "0" * 64
    elif change == "audio_sha":
        request_payload["clips"][0]["audio_sha256"] = "0" * 64
    elif change == "audio_name":
        request_payload["clips"][0]["path"] = "clip.wav"
    elif change == "too_many_clips":
        request_payload["clips"] *= 3
    elif change == "empty_clips":
        request_payload["clips"] = []
    elif change == "over_duration":
        request_payload["clips"][0]["window"]["end"] = 51
    elif change == "negative_start":
        request_payload["clips"][0]["window"].update(start=-1, end=0)
    elif change == "nonfinite":
        request_payload["clips"][0]["window"]["end"] = float("nan")
    elif change == "recipe":
        request_payload["recipe"]["temperature"] = 1
    monkeypatch.setattr(worker, "_load_model", lambda path: pytest.fail("invalid evidence must not load model"))
    with pytest.raises(ValueError, match=reason):
        worker.review(request_payload)


def test_audio_format_is_checked_before_model_load(request_payload, monkeypatch):
    audio = Path(request_payload["clips"][0]["path"])
    with wave.open(str(audio), "wb") as stream:
        stream.setnchannels(2)
        stream.setsampwidth(2)
        stream.setframerate(8000)
        stream.writeframes(b"\0\0" * 8000 * 2)
    request_payload["clips"][0]["audio_sha256"] = worker._digest(audio)
    monkeypatch.setattr(worker, "_load_model", lambda path: pytest.fail("wrong audio format admitted"))
    with pytest.raises(ValueError, match="audio_clip_invalid"):
        worker.review(request_payload)


def test_empty_transcription_and_changed_model_are_never_reviewed(request_payload, monkeypatch):
    mode = {"value": "empty"}
    class Engine:
        def transcribe(self, *args, **kwargs):
            if mode["value"] == "empty":
                return dict(segments=[])
            Path(request_payload["model_path"]).write_bytes(b"changed-local-model")
            return _decoded()
    monkeypatch.setattr(worker, "_load_model", lambda path: Engine())
    with pytest.raises(ValueError, match="audio_transcript_empty"):
        worker.review(request_payload)
    mode["value"] = "changed"
    with pytest.raises(ValueError, match="model_changed_during_review"):
        worker.review(request_payload)


def test_network_block_restores_socket_class_and_functions():
    original_class, original_lookup = socket.socket, socket.getaddrinfo
    original_connect, original_method = socket.create_connection, socket.socket.connect
    with worker._offline():
        assert socket.socket is original_class
        with pytest.raises(OSError, match="audio_review_network_disabled"):
            socket.create_connection(("example.invalid", 443))
        with socket.socket() as connection:
            with pytest.raises(OSError, match="audio_review_network_disabled"):
                connection.connect(("127.0.0.1", 9))
    assert socket.socket is original_class and socket.socket.connect is original_method
    assert socket.getaddrinfo is original_lookup and socket.create_connection is original_connect


@pytest.mark.parametrize("audio_layers", [24, 12])
def test_loader_passes_only_existing_path_and_checks_medium_dimensions(request_payload, monkeypatch, audio_layers):
    calls = []
    model = SimpleNamespace(dims=SimpleNamespace(n_audio_layer=audio_layers, n_text_layer=24,
                                                n_audio_state=1024, n_text_state=1024))
    def load(path, **kwargs):
        calls.append((path, kwargs))
        return model
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(set_num_threads=lambda value: calls.append(value)))
    monkeypatch.setitem(sys.modules, "whisper", SimpleNamespace(load_model=load))
    path = Path(request_payload["model_path"])
    if audio_layers == 24:
        assert worker._load_model(path) is model
    else:
        with pytest.raises(ValueError, match="local_model_is_not_medium"):
            worker._load_model(path)
    assert calls == [4, (str(path), dict(device="cpu"))]
