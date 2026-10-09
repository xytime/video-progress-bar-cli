"""原片首次讲话前的保守裁剪；依赖：pipeline → processors → utils/config。

只读取原片，不读取二创母带；所有失败返回原片，无人工确认状态。
# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-09 | Codex | 固定离线 VAD、保守起点、原片保留及指纹检查点。 |
| 1.1.0 | 2026-10-09 | Codex | 只删除完全匹配已验证音画的品牌前缀；校验零起点及有限时长。 |
"""
from dataclasses import asdict, dataclass
import argparse
import errno
import hashlib
import json
import math
from pathlib import Path
import subprocess
import tempfile

from video_processing.utils.video_metadata import _resolve_ffprobe_cmd, resolve_ffmpeg_cmd

RECIPE = "speech-opening-v2"
MODEL = Path(__file__).resolve().parents[3] / "assets/models/silero-vad/silero_vad.jit"
PREFIXES = Path(__file__).resolve().parents[3] / "assets/models/silero-vad/verified-prefixes.json"
MODEL_SHA256 = "85c48e1f0ecb604e5d2a268f3ccfb912d4f7e935acdc86af5a3fc5b0aea7b29a"
SAMPLE_RATE, FRAME_SAMPLES = 16000, 512
FRAME_SECONDS = FRAME_SAMPLES / SAMPLE_RATE


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(".pending.json")
    pending.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    pending.replace(path)


@dataclass(frozen=True)
class OpeningDecision:
    offset_seconds: float = 0.0
    reason: str = "NO_RELIABLE_SPEECH"
    reference_id: str = ""


def decide_opening(probabilities: list[float], *, pad_seconds: float = .5,
                   min_trim_seconds: float = 2.0) -> OpeningDecision:
    """任何早期疑似语音均保护；短促问候不会被最短语音长度规则丢弃。

    0.2 只用于保护早期语音，0.8 用于确认讲话。首次疑似语音之后
    0.5 秒内必须出现连续三帧高置信语音，否则放弃整次裁剪。
    """
    if not probabilities or any(not math.isfinite(p) or not 0 <= p <= 1 for p in probabilities):
        return OpeningDecision(reason="INVALID_VAD_OUTPUT")
    first = next((i for i, p in enumerate(probabilities) if p >= .2), None)
    if first is None:
        return OpeningDecision()
    offset = max(0.0, first * FRAME_SECONDS - pad_seconds)
    if offset < min_trim_seconds:
        return OpeningDecision(reason="SPEECH_AT_START_OR_SMALL_GAIN")
    stop = min(len(probabilities), first + math.ceil(.5 / FRAME_SECONDS))
    if not any(all(p >= .8 for p in probabilities[i:i + 3])
               for i in range(first, stop - 2)):
        return OpeningDecision(reason="UNCERTAIN_EARLY_VOICE")
    return OpeningDecision(round(offset, 3), "CLEAR_INITIAL_NON_SPEECH")


def speech_probabilities(source: Path, window_seconds: float = 30.0) -> list[float]:
    """固定校验模型后离线加载，FFmpeg 提取 16k 单声道，禁止自动下载。"""
    if sha256(MODEL) != MODEL_SHA256:
        raise ValueError("VAD_MODEL_HASH_MISMATCH")
    import numpy as np
    import torch

    raw = subprocess.run([
        resolve_ffmpeg_cmd(), "-v", "error", "-i", str(source), "-t", str(window_seconds),
        "-map", "0:a:0", "-vn", "-ar", str(SAMPLE_RATE), "-ac", "1",
        "-f", "f32le", "pipe:1",
    ], check=True, capture_output=True, timeout=60).stdout
    samples = np.frombuffer(raw, dtype="<f4").copy()
    if not len(samples) or not np.isfinite(samples).all():
        raise ValueError("NO_VALID_AUDIO")
    torch.set_num_threads(1)
    model = torch.jit.load(str(MODEL), map_location="cpu").eval()
    model.reset_states()
    probabilities = []
    with torch.inference_mode():
        for start in range(0, len(samples), FRAME_SAMPLES):
            frame = samples[start:start + FRAME_SAMPLES]
            if len(frame) < FRAME_SAMPLES:
                frame = np.pad(frame, (0, FRAME_SAMPLES - len(frame)))
            probabilities.append(float(model(torch.from_numpy(frame), SAMPLE_RATE).item()))
    return probabilities


def media_info(path: Path) -> dict:
    result = subprocess.run([
        _resolve_ffprobe_cmd(), "-v", "error", "-show_format", "-show_streams",
        "-of", "json", str(path),
    ], check=True, capture_output=True, text=True, timeout=30)
    data = json.loads(result.stdout)
    streams = {s["codec_type"]: s for s in data["streams"] if s["codec_type"] in {"video", "audio"}}
    if not {"video", "audio"} <= streams.keys():
        raise ValueError("MISSING_AV_STREAM")
    seconds = float(data["format"]["duration"])
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("INVALID_DURATION")
    return {"duration": seconds, "streams": streams}


def prefix_shape(info: dict) -> dict:
    return {kind: {key: info["streams"][kind].get(key) for key in fields}
            for kind, fields in [("video", ["width", "height", "pix_fmt", "r_frame_rate"]),
                                 ("audio", ["sample_rate", "channels"])]}


def decoded_prefix_sha256(source: Path, seconds: float, shape: dict) -> str:
    """完整帧和所有声道解码摘要，不采样图像、不使用模糊相似度。"""
    result = subprocess.run([
        resolve_ffmpeg_cmd(), "-v", "error", "-i", str(source), "-t", str(seconds),
        "-map", "0:v:0", "-map", "0:a:0", "-c:v", "rawvideo", "-threads", "2",
        "-c:a", "pcm_f32le", "-f", "streamhash", "-hash", "sha256", "pipe:1",
    ], check=True, capture_output=True, text=True, timeout=60)
    return hashlib.sha256((json.dumps(shape, sort_keys=True) + result.stdout.strip()).encode()).hexdigest()


def protect_visual_prefix(source: Path, info: dict, decision: OpeningDecision) -> OpeningDecision:
    """音频无讲话不等于视觉可删；未知或内容变化的前缀一律保留。"""
    starts = [float(info["streams"][kind].get("start_time", "nan")) for kind in ("video", "audio")]
    if any(not math.isfinite(start) or abs(start) > .001 for start in starts):
        return OpeningDecision(reason="UNSUPPORTED_SOURCE_TIMEBASE")
    manifest = json.loads(PREFIXES.read_text(encoding="utf-8"))
    if manifest["version"] != 1:
        raise ValueError("UNKNOWN_PREFIX_MANIFEST")
    shape, digests = prefix_shape(info), {}
    for prefix in sorted(manifest["prefixes"], key=lambda p: p["seconds"], reverse=True):
        seconds = prefix["seconds"]
        if not math.isfinite(seconds) or not 2 <= seconds <= 30:
            raise ValueError("INVALID_PREFIX_DURATION")
        if prefix["shape"] != shape or seconds >= info["duration"] - 2:
            continue
        if seconds not in digests:
            digests[seconds] = decoded_prefix_sha256(source, seconds, shape)
        if digests[seconds] == prefix["decoded_av_sha256"]:
            return OpeningDecision(min(seconds, decision.offset_seconds), "VERIFIED_AV_PREFIX",
                                   prefix.get("reference_id", ""))
    return OpeningDecision(reason="UNVERIFIED_AV_PREFIX")


def validate_prepared(path: Path, expected: float) -> None:
    info = media_info(path)
    if not math.isfinite(expected) or expected <= 0 or abs(info["duration"] - expected) > .15:
        raise ValueError("PREPARED_DURATION_MISMATCH")
    video, audio = (info["streams"][kind] for kind in ("video", "audio"))
    starts = [float(stream.get("start_time", "nan")) for stream in (video, audio)]
    durations = [float(stream["duration"]) for stream in (video, audio)]
    if any(not math.isfinite(t) or abs(t) > .05 for t in starts):
        raise ValueError("PREPARED_AV_START_MISMATCH")
    # 结束时间=起点+时长。裁剪落在帧间时，视频起点可能比音频晚一帧。
    ends = [start + duration for start, duration in zip(starts, durations)]
    if (any(not math.isfinite(t) or t <= 0 for t in durations)
            or any(abs(t - expected) > .15 for t in ends) or abs(ends[0] - ends[1]) > .08):
        raise ValueError("PREPARED_AV_END_MISMATCH")


def prepare_opening(source: Path, output_dir: Path) -> tuple[Path, dict]:
    """生成独立原片加工副本；源、配方和副本摘要匹配才可复用。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{source.stem}.mp4"
    receipt_path = output.with_suffix(".opening.json")
    receipt = {"recipe": RECIPE, "model_sha256": MODEL_SHA256, "offset_seconds": 0.0}
    if output.resolve() == source.resolve():
        receipt["reason"] = "OUTPUT_OVERLAPS_SOURCE"
        atomic_json(receipt_path, receipt)
        return source, receipt
    try:
        if sha256(MODEL) != MODEL_SHA256:
            raise ValueError("VAD_MODEL_HASH_MISMATCH")
        receipt["prefix_manifest_sha256"] = sha256(PREFIXES)
        receipt["source_sha256"] = sha256(source)
        source_info = media_info(source)
        receipt["source_duration"] = source_info["duration"]
        if receipt_path.is_file():
            previous = json.loads(receipt_path.read_text(encoding="utf-8"))
            if all(previous.get(k) == v for k, v in receipt.items() if k != "offset_seconds"):
                offset = previous.get("offset_seconds", 0)
                if offset == 0 and not previous.get("reason", "").startswith("UNAVAILABLE_"):
                    return source, previous
                if isinstance(offset, (int, float)) and 2 <= offset < min(30, source_info["duration"] - 2):
                    if output.is_file() and previous.get("output_sha256") == sha256(output):
                        validate_prepared(output, source_info["duration"] - offset)
                        return output, previous
        decision = decide_opening(speech_probabilities(source))
        if decision.offset_seconds:
            decision = protect_visual_prefix(source, source_info, decision)
        receipt.update(asdict(decision))
        if decision.offset_seconds:
            expected = source_info["duration"] - decision.offset_seconds
            if expected < 2:
                receipt.update(offset_seconds=0.0, reason="INSUFFICIENT_BODY")
            else:
                # 精确重新编码并统一零起点，避免流复制关键帧吞首字/黑帧。
                with tempfile.TemporaryDirectory(dir=output_dir) as temporary:
                    candidate = Path(temporary) / "prepared.mp4"
                    subprocess.run([
                        resolve_ffmpeg_cmd(), "-v", "error", "-y", "-i", str(source),
                        "-ss", str(decision.offset_seconds), "-map", "0:v:0", "-map", "0:a:0",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-threads", "2",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                        "-movflags", "+faststart", str(candidate),
                    ], check=True, capture_output=True, timeout=1200)
                    validate_prepared(candidate, expected)
                    receipt["output_sha256"] = sha256(candidate)
                    candidate.replace(output)
                atomic_json(receipt_path, receipt)
                return output, receipt
    except Exception as exc:
        receipt.update(offset_seconds=0.0, reason=f"UNAVAILABLE_{type(exc).__name__}")
        receipt["failure_code"] = (str(exc)[:100] if type(exc) is ValueError else
                                   errno.errorcode.get(exc.errno, type(exc).__name__)
                                   if isinstance(exc, OSError) else type(exc).__name__)
    atomic_json(receipt_path, receipt)
    return source, receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    selected, receipt = prepare_opening(args.source, args.output_dir)
    print(json.dumps({"selected": str(selected), "receipt": receipt}, ensure_ascii=False))


if __name__ == "__main__":
    main()
