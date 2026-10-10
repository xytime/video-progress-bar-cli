"""只移除已核验且完整音画相同的 TED 原片包装，未知内容保留。

不依赖角色识别、OCR 或语音概率；不接触二创母带和历史成片。
# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-10 | Codex | 首尾完整音画匹配、一次精确编码、可观察回退和缓存校验。 |
"""
import argparse
import errno
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from . import speech_opening as media

RECIPE = "ted-source-cleanup-v1"
PACKAGING = Path(__file__).resolve().parents[3] / "resources/ted-source-packaging.json"


def suffix_digest(source: Path, start: float, shape: dict) -> str:
    """从精确时刻解码至文件结束；所有帧和所有声道都参与比较。"""
    result = subprocess.run([
        media.resolve_ffmpeg_cmd(), "-v", "error", "-xerror", "-ss", str(start),
        "-i", str(source), "-map", "0:v:0", "-map", "0:a:0",
        "-c:v", "rawvideo", "-threads", "2", "-c:a", "pcm_f32le",
        "-f", "streamhash", "-hash", "sha256", "pipe:1",
    ], check=True, capture_output=True, text=True, timeout=60)
    return hashlib.sha256((json.dumps(shape, sort_keys=True) + result.stdout.strip()).encode()).hexdigest()


def detect_packaging(source: Path, info: dict) -> dict:
    """模板只记录无讲话的包装，不含讲者画面；引用编号仅用于追溯。"""
    starts = [float(info["streams"][kind].get("start_time", "nan")) for kind in ("video", "audio")]
    end = float(info["streams"]["video"].get("duration", "nan"))
    if (any(not math.isfinite(t) or abs(t) > .001 for t in starts)
            or not math.isfinite(end) or abs(end - info["duration"]) > .15):
        return {"offset_seconds": 0.0, "end_seconds": info["duration"],
                "reason": "UNSUPPORTED_SOURCE_TIMEBASE"}
    manifest = json.loads(PACKAGING.read_text(encoding="utf-8"))
    legacy = json.loads(media.PREFIXES.read_text(encoding="utf-8"))
    if manifest.get("version") != 1 or legacy.get("version") != 1:
        raise ValueError("UNKNOWN_PACKAGING_MANIFEST")
    shape, first, last, references = media.prefix_shape(info), 0.0, info["duration"], []
    for kind, entries in (("prefix", manifest["prefixes"] + legacy["prefixes"]),
                          ("suffix", manifest["suffixes"])):
        hashes = {}
        for entry in sorted(entries, key=lambda e: e["seconds"], reverse=True):
            seconds = entry["seconds"]
            if not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or not 2 <= seconds <= 30:
                raise ValueError("INVALID_PACKAGING_DURATION")
            if entry["shape"] != shape or seconds >= end - first - 2:
                continue
            if seconds not in hashes:
                hashes[seconds] = (media.decoded_prefix_sha256(source, seconds, shape) if kind == "prefix"
                                   else suffix_digest(source, round(end - seconds, 6), shape))
            if hashes[seconds] == entry["decoded_av_sha256"]:
                if kind == "prefix":
                    first = seconds
                else:
                    last = round(end - seconds, 6)
                references.append({"edge": kind, "reference_id": entry.get("reference_id", "")})
                break
    return {"offset_seconds": first, "end_seconds": last, "references": references,
            "reason": "VERIFIED_AV_PACKAGING" if references else "UNVERIFIED_AV_PACKAGING"}


def prepare_source(source: Path, output_dir: Path) -> tuple[Path, dict]:
    """独立副本统一零起点；失败收据不能阻止下一次正常重试。"""
    receipt = {"recipe": RECIPE, "offset_seconds": 0.0, "end_seconds": None}
    output = output_dir / f"{source.stem}.mp4"
    receipt_path = output.with_suffix(".opening.json")
    started = time.monotonic()
    safe_output = False
    try:
        if (output.resolve() == source.resolve() or source.is_symlink() or output.is_symlink()
                or receipt_path.is_symlink() or output_dir.resolve() != output_dir.absolute()):
            raise ValueError("UNSAFE_SOURCE_OUTPUT_PATH")
        safe_output = True
        output_dir.mkdir(parents=True, exist_ok=True)
        receipt.update(source_sha256=media.sha256(source),
                       packaging_sha256=media.sha256(PACKAGING),
                       prefix_manifest_sha256=media.sha256(media.PREFIXES))
        info = media.media_info(source)
        receipt.update(source_duration=info["duration"], source_bytes=source.stat().st_size)
        if receipt_path.is_file():
            try:
                previous = json.loads(receipt_path.read_text(encoding="utf-8"))
                same = all(previous.get(k) == v for k, v in receipt.items()
                           if k not in {"offset_seconds", "end_seconds"})
                first, last = previous["offset_seconds"], previous["end_seconds"]
                if same and previous["reason"] == "UNVERIFIED_AV_PACKAGING":
                    return source, previous
                if (same and previous["reason"] == "VERIFIED_AV_PACKAGING"
                        and isinstance(first, (int, float)) and isinstance(last, (int, float))
                        and math.isfinite(first) and math.isfinite(last)
                        and 0 <= first <= 30 and first + 2 < last <= info["duration"]
                        and info["duration"] - last <= 30.15
                        and output.is_file() and media.sha256(output) == previous["output_sha256"]):
                    media.validate_prepared(output, last - first)
                    return output, previous
            except (ValueError, KeyError, TypeError, OSError):
                pass  # 坏收据/副本重新检测，不把旧加工副本作为本次输入。
        receipt.update(detect_packaging(source, info))
        receipt["analysis_seconds"] = round(time.monotonic() - started, 3)
        first, last = receipt["offset_seconds"], receipt["end_seconds"]
        if receipt["reason"] == "VERIFIED_AV_PACKAGING":
            if shutil.disk_usage(output_dir).free < max(512 * 1024**2, source.stat().st_size * 3):
                raise ValueError("INSUFFICIENT_STORAGE")
            encoding = time.monotonic()
            with tempfile.TemporaryDirectory(dir=output_dir) as temporary:
                candidate = Path(temporary) / "prepared.mp4"
                subprocess.run([
                    media.resolve_ffmpeg_cmd(), "-v", "error", "-xerror", "-y", "-i", str(source),
                    "-ss", str(first), "-t", str(last - first), "-map", "0:v:0", "-map", "0:a:0",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-threads", "2",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(candidate),
                ], check=True, capture_output=True, timeout=1200)
                media.validate_prepared(candidate, last - first)
                subprocess.run([media.resolve_ffmpeg_cmd(), "-v", "error", "-xerror", "-i", str(candidate),
                                "-f", "null", "-"], check=True, capture_output=True, timeout=120)
                if media.sha256(source) != receipt["source_sha256"]:
                    raise ValueError("SOURCE_CHANGED_DURING_CLEANUP")
                receipt.update(output_sha256=media.sha256(candidate), output_bytes=candidate.stat().st_size,
                               encode_and_decode_seconds=round(time.monotonic() - encoding, 3),
                               removed_seconds=round(info["duration"] - (last - first), 6))
                candidate.replace(output)
            media.atomic_json(receipt_path, receipt)
            return output, receipt
    except Exception as exc:
        receipt.update(offset_seconds=0.0, end_seconds=receipt.get("source_duration"),
                       reason=f"UNAVAILABLE_{type(exc).__name__}")
        receipt["failure_code"] = (str(exc)[:100] if isinstance(exc, ValueError) else
                                   errno.errorcode.get(exc.errno, type(exc).__name__)
                                   if isinstance(exc, OSError) else type(exc).__name__)
    if not safe_output:
        return source, receipt
    try:
        media.atomic_json(receipt_path, receipt)
    except OSError:
        receipt["receipt_write_failed"] = True
    return source, receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    selected, receipt = prepare_source(args.source, args.output_dir)
    print(json.dumps({"selected": str(selected), "receipt": receipt}, ensure_ascii=False))


if __name__ == "__main__":
    main()
