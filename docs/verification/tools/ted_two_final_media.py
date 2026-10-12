"""只读真实原片，在独立目录复现生产清理、竖版、互动层与二创输入绑定。

不实例化生产 DAL、不上传；复用既有译文并映射时间轴，不调用翻译服务。
# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-12 | Codex | 两条真实整片、首末讲话、全程音频及历史产物保护证据。 |
| 1.1.0 | 2026-10-12 | Codex | 依据原字幕锚定已知末句；只允许显式恢复且全媒体/绑定重新校验。 |
"""
import argparse
import copy
import json
from pathlib import Path
import re
import subprocess
import time

import numpy as np
import pysubs2

from config.settings import settings
from video_processing.pipeline_manager import PipelineManager, _validate_rendered_vertical_cache
from video_processing.processors import ted_source_cleanup as cleanup
from video_processing.processors.insight_editorial import resolve_inputs
from video_processing.processors.interaction_overlay import InteractionOverlayProcessor
from video_processing.processors.vertical_processor import VerticalCaptionProcessor
from video_processing.utils.render_source_binding import bind_render_source

CASES = [
    ("CKAyfGItpgg", "职场对话三步开场", "UCAuUUnT6oDeKwE6v1NGQxug", 3.5),
    ("65LZk_S9HBY", "照护如何塑造领导力", "UCsT0YIqwnpJCM-mx7-gSA4Q", 10.0),
]
END_PHRASES = {
    "CKAyfGItpgg": "is the power of the first minute thank you",
    "65LZk_S9HBY": "caregiving is not a detour from leadership it is leadership practice under pressure",
}


class LocalTracking:
    """诊断 PID 记录器；不能访问生产任务或发布。"""
    def update_process_pid(self, *args, **kwargs):
        pass

    def wallstreet_uses_normal_a(self, *args):
        return False


def waveform(path, start=0, seconds=None, rate=16000):
    command = [cleanup.media.resolve_ffmpeg_cmd(), "-v", "error", "-i", str(path), "-ss", str(start)]
    if seconds is not None:
        command += ["-t", str(seconds)]
    command += ["-vn", "-ar", str(rate), "-ac", "1", "-f", "f32le", "pipe:1"]
    result = subprocess.run(command, check=True, capture_output=True, timeout=120)
    return np.frombuffer(result.stdout, dtype="<f4").copy()


def mapped_subtitles(original, destination, offset, end):
    subtitles = pysubs2.load(str(original))
    mapped = copy.deepcopy(subtitles)
    mapped.events = []
    for event in subtitles:
        if event.end <= offset * 1000 or event.start >= end * 1000:
            continue
        item = copy.deepcopy(event)
        item.start = max(0, event.start - round(offset * 1000))
        item.end = min(event.end, round(end * 1000)) - round(offset * 1000)
        mapped.events.append(item)
    # 本轮两条的开场字幕从0秒起跨过切点，正文文字必须全部保留。
    assert [e.text for e in mapped] == [e.text for e in subtitles]
    assert all(0 <= e.start < e.end <= (end - offset) * 1000 + 20 for e in mapped)
    mapped.save(str(destination))
    return {"events": len(mapped), "texts_unchanged": True,
            "kind": "existing_bilingual_translation_mapped_not_new_full_asr",
            "first": mapped[0].plaintext, "last": mapped[-1].plaintext}


def audio_check(source, output, offset):
    """每秒比较整段讲话；AAC重编码允许有损波形差异。"""
    a, b = waveform(source, offset, rate=8000), waveform(output, rate=8000)
    count = min(len(a), len(b))
    correlations = []
    for start in range(0, count - 8000, 8000):
        x, y = a[start:start + 8000], b[start:start + 8000]
        if min(np.linalg.norm(x), np.linalg.norm(y)) > .01:
            correlations.append(float(np.dot(x, y) / (np.linalg.norm(x) * np.linalg.norm(y))))
    assert correlations and min(correlations) > .94 and np.median(correlations) > .98
    # 互动提示音可叠加，基础竖版用于逐秒完整讲话检查。
    return {"compared_seconds": len(correlations), "minimum": min(correlations),
            "median": float(np.median(correlations)), "samples": [len(a), len(b)],
            "lowest_windows": sorted(enumerate(correlations), key=lambda p: p[1])[:5]}


def validate_rendered(path, expected):
    valid, reason = _validate_rendered_vertical_cache(path, expected_duration_seconds=expected)
    assert valid, reason
    info = cleanup.media.media_info(path)
    streams = [info["streams"][kind] for kind in ("video", "audio")]
    starts = [float(s["start_time"]) for s in streams]
    ends = [start + float(s["duration"]) for start, s in zip(starts, streams)]
    assert abs(info["duration"] - expected) <= .15
    assert all(abs(start) <= .05 for start in starts)
    # 成片额外AAC编码可能补一包；不误用原片副本80ms尾点门槛。
    # 仍严格记录各流尾点，配合全程音频对照和完整解码验证。
    assert all(abs(end - expected) <= .15 for end in ends) and abs(ends[0] - ends[1]) <= .15
    return {"start_seconds": starts, "end_seconds": ends, "duration": info["duration"]}


def speech_check(model, source, output, offset, expected, yid):
    rows = {}
    # 第二条末18秒只有掌声，短窗口会幻觉出Thank you；60秒才含实际结束段。
    tail_length = 60 if yid == "65LZk_S9HBY" else 18
    for edge, source_start, output_start, length in (
            ("first", 0, 0, 22), ("last", offset + expected - tail_length, expected - tail_length, tail_length)):
        words = {}
        for name, path, start in (("original", source, source_start), ("final", output, output_start)):
            result = model.transcribe(waveform(path, start, length), language="en", fp16=False,
                                      temperature=0, word_timestamps=True)
            words[name] = {"text": result["text"], "words": re.findall(r"[a-z]+", result["text"].lower())}
        if edge == "first":
            assert words["original"]["words"][:6] == words["final"]["words"][:6], words
        else:
            # 已核对的结束段语句；原始ASR全文保留，不能把掌声标记当讲话。
            phrase = END_PHRASES[yid]
            assert all(phrase in " ".join(item["words"]) for item in words.values()), words
            words["closing_section_anchor"] = phrase
            words["excerpt_seconds"] = length
            words["asr_is_auxiliary_not_word_accuracy_proof"] = True
        rows[edge] = words
    return rows


def run(media_root, output_root, model_path, resume=False):
    output_root.mkdir(parents=True, exist_ok=True)
    assert output_root.resolve() == output_root.absolute()
    assert output_root.resolve() != media_root.resolve()
    # 只改本诊断进程配置；不写生产.env或数据库。
    settings.enable_ted_source_cleanup = True
    settings.enable_interaction_overlay = True
    settings.enable_deep_insight_enrichment = False
    pm = PipelineManager.__new__(PipelineManager)
    pm._OUT_DIR, pm.db = output_root, LocalTracking()
    import torch
    import whisper
    torch.set_num_threads(2)
    model = whisper.load_model(str(model_path), device="cpu")
    rows = []
    for yid, title, channel, offset in CASES:
        source = media_root / "original_video" / f"{yid}.mp4"
        protected = [source, media_root / f"{yid}.ass",
                     media_root / f"{yid}_vertical.mp4", media_root / f"{yid}_vertical_interactive.mp4"]
        before = {str(path): cleanup.media.sha256(path) for path in protected}
        vertical = output_root / f"{yid}_vertical.mp4"
        reused = vertical.exists()
        assert not reused or resume, "已有验证产物须显式--resume并重新验证，不能当作新渲染"
        started = time.monotonic()
        selected = pm._prepare_speech_opening({"youtube_id": yid, "channel_id": channel,
                                              "slice_index": 0}, source)
        assert selected != source, "生产清理入口仍回退原片"
        receipt = json.loads(selected.with_suffix(".opening.json").read_text())
        assert receipt["offset_seconds"] == offset
        assert receipt["end_seconds"] == receipt["source_duration"], "本轮不裁尾"
        expected = receipt["end_seconds"] - offset
        assert receipt["source_sha256"] == before[str(source)]
        assert cleanup.media.sha256(selected) == receipt["output_sha256"]
        cleanup.media.validate_prepared(selected, expected)
        subtitle = mapped_subtitles(media_root / f"{yid}.ass", selected.with_suffix(".ass"),
                                    offset, receipt["end_seconds"])
        print(yid, "source_prepared", receipt, flush=True)
        render_start = time.monotonic()
        if not reused:
            processor = VerticalCaptionProcessor(selected, vertical, title=title, bilingual=True,
                                                 font_path="/System/Library/Fonts/PingFang.ttc")
            processor._burn_subtitles(selected.with_suffix(".ass"))
        base_streams = validate_rendered(vertical, expected)
        if not reused:
            bind_render_source(vertical, selected, selected.with_suffix(".ass"))
        assert resolve_inputs(vertical) == (selected, selected.with_suffix(".ass"))
        print(yid, "vertical_complete", round(time.monotonic() - render_start, 3), flush=True)
        final = vertical.with_name(vertical.stem + "_interactive.mp4")
        if not (resume and final.is_file()):
            final = InteractionOverlayProcessor(vertical).process()
        assert pm._get_published_video_path(yid, expected) == final
        final_streams = validate_rendered(final, expected)
        subprocess.run([cleanup.media.resolve_ffmpeg_cmd(), "-v", "error", "-xerror", "-i", str(final),
                        "-f", "null", "-"], check=True, capture_output=True, timeout=180)
        evidence = {"id": yid, "title": title, "entry": "PipelineManager._prepare_speech_opening",
                    "receipt": receipt, "final": str(final), "final_sha256": cleanup.media.sha256(final),
                    "final_duration": cleanup.media.media_info(final)["duration"],
                    "subtitles": subtitle, "editorial_binding_verified": True,
                    "base_streams": base_streams, "final_streams": final_streams,
                    "base_audio": audio_check(source, vertical, offset),
                    "speech": speech_check(model, source, final, offset, expected, yid),
                    "reused_rendered_files": reused,
                    "protected_artifacts_sha256": before,
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "render_seconds": round(time.monotonic() - render_start, 3)}
        assert all(cleanup.media.sha256(Path(path)) == value for path, value in before.items())
        evidence["source_and_history_unchanged"] = True
        rows.append(evidence)
        (output_root / "results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2))
        print(yid, "REAL_FINAL_VERIFIED", evidence["final_duration"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--media-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    run(args.media_root.resolve(), args.output_root.absolute(), args.model.resolve(), args.resume)
