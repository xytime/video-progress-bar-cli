"""自动去开场的保护边界、真实离线 VAD 与精确音画裁剪。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-09 | Codex | 保护短问候、历史/手工/切片，验证真实 VAD、检查点及二创输入绑定。 |
| 1.1.0 | 2026-10-09 | Codex | 验证完整音画前缀、损坏缓存、有限时间轴及真实整片结束时码回归。 |
"""
import json
import subprocess
from pathlib import Path

import pytest

from video_processing.processors import speech_opening as opening
from video_processing.processors.insight_editorial import resolve_inputs
from video_processing.utils.render_source_binding import (
    bind_render_source, bound_render_inputs, render_source_matches,
)

ROOT = Path(__file__).resolve().parents[2]


def test_clear_prefix_cuts_before_earliest_voice():
    decision = opening.decide_opening([.01] * 150 + [.3, .6, .95, .95, .95])
    assert decision.offset_seconds == 4.3


@pytest.mark.parametrize("probabilities,reason", [
    ([.95] * 200, "SPEECH_AT_START_OR_SMALL_GAIN"),
    ([.01] * 40 + [.95] * 10, "SPEECH_AT_START_OR_SMALL_GAIN"),
    ([.01] * 100 + [.3] + [.01] * 80 + [.95] * 10, "UNCERTAIN_EARLY_VOICE"),
    ([.01] * 1000, "NO_RELIABLE_SPEECH"),
    ([.01, float("nan")], "INVALID_VAD_OUTPUT"),
    ([-.1], "INVALID_VAD_OUTPUT"),
    ([], "INVALID_VAD_OUTPUT"),
])
def test_uncertainty_and_short_greeting_preserve_original(probabilities, reason):
    decision = opening.decide_opening(probabilities)
    assert decision.offset_seconds == 0
    assert decision.reason == reason


@pytest.fixture
def speech_source(tmp_path, monkeypatch):
    """真实合成语音前加4秒纯音；不以此替代真实 TED 样本准确率。"""
    source = tmp_path / "abcdefghijk.mp4"
    fixture = ROOT / "tests/fixtures/media/caption_speech.wav"
    subprocess.run([
        opening.resolve_ffmpeg_cmd(), "-v", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=8",
        "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=16000:duration=4",
        "-i", str(fixture), "-filter_complex",
        "[1:a][2:a]concat=n=2:v=0:a=1,apad[a]",
        "-map", "0:v", "-map", "[a]", "-t", "8", "-c:v", "libx264",
        "-threads", "2", "-c:a", "aac", str(source),
    ], check=True, capture_output=True, timeout=30)
    # 测试夹具明确登记纯音测试图前缀；生产模板只来自真实品牌片头。
    shape = opening.prefix_shape(opening.media_info(source))
    manifest = tmp_path / "prefixes.json"
    manifest.write_text(json.dumps({"version": 1, "prefixes": [{
        "seconds": 3.5, "shape": shape,
        "decoded_av_sha256": opening.decoded_prefix_sha256(source, 3.5, shape),
    }]}))
    monkeypatch.setattr(opening, "PREFIXES", manifest)
    return source


def test_real_vad_exact_trim_and_checkpoint(speech_source, tmp_path, monkeypatch):
    before = opening.sha256(speech_source)
    prepared, receipt = opening.prepare_opening(speech_source, tmp_path / "prepared")
    assert prepared != speech_source, receipt
    assert 3.2 <= receipt["offset_seconds"] <= 4
    assert opening.sha256(speech_source) == before
    info = opening.media_info(prepared)
    assert abs(info["duration"] - (8 - receipt["offset_seconds"])) < .15
    subprocess.run([opening.resolve_ffmpeg_cmd(), "-v", "error", "-xerror", "-i", str(prepared),
                    "-f", "null", "-"], check=True, capture_output=True, timeout=30)
    subprocess.run([opening.resolve_ffmpeg_cmd(), "-v", "error", "-y", "-i", str(speech_source),
                    "-frames:v", "1", str(tmp_path / "original.png")],
                   check=True, capture_output=True, timeout=30)
    subprocess.run([opening.resolve_ffmpeg_cmd(), "-v", "error", "-y", "-i", str(prepared),
                    "-frames:v", "1", str(tmp_path / "prepared.png")],
                   check=True, capture_output=True, timeout=30)
    monkeypatch.setattr(opening, "speech_probabilities", lambda *_: pytest.fail("重复检测"))
    again, second = opening.prepare_opening(speech_source, tmp_path / "prepared")
    assert again == prepared and second == receipt
    prepared.write_bytes(b"corrupt")
    monkeypatch.setattr(opening, "speech_probabilities", lambda *_: [.01] * 1000)
    chosen, failed = opening.prepare_opening(speech_source, tmp_path / "prepared")
    assert chosen == speech_source and failed["offset_seconds"] == 0


def test_detection_error_continues_original(speech_source, tmp_path, monkeypatch):
    def broken(*_):
        raise RuntimeError("test error")
    monkeypatch.setattr(opening, "speech_probabilities", broken)
    chosen, receipt = opening.prepare_opening(speech_source, tmp_path / "prepared")
    assert chosen == speech_source
    assert receipt["reason"] == "UNAVAILABLE_RuntimeError"
    assert receipt["offset_seconds"] == 0
    monkeypatch.setattr(opening, "speech_probabilities", lambda *_: [.01] * 1000)
    _, receipt = opening.prepare_opening(speech_source, tmp_path / "prepared")
    assert receipt["reason"] == "NO_RELIABLE_SPEECH"


def test_output_cannot_overwrite_source(speech_source, monkeypatch):
    before = opening.sha256(speech_source)
    monkeypatch.setattr(opening, "speech_probabilities", lambda *_: pytest.fail("路径重合不得裁剪"))
    chosen, receipt = opening.prepare_opening(speech_source, speech_source.parent)
    assert chosen == speech_source and receipt["reason"] == "OUTPUT_OVERLAPS_SOURCE"
    assert opening.sha256(speech_source) == before


def make_bound_inputs(tmp_path):
    original = tmp_path / "speech_opening/abcdefghijk/abcdefghijk.mp4"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"prepared body")
    subtitles = original.with_suffix(".ass")
    subtitles.write_text("zero based subtitles")
    vertical = tmp_path / "abcdefghijk_vertical.mp4"
    vertical.write_bytes(b"vertical body only")
    bind_render_source(vertical, original, subtitles)
    return original, subtitles, vertical


def test_enrichment_uses_bound_body_and_zero_based_subtitles(tmp_path):
    original, subtitles, vertical = make_bound_inputs(tmp_path)
    (tmp_path / "abcdefghijk.mp4").write_bytes(b"untrimmed original")
    assert resolve_inputs(vertical) == (original, subtitles)
    assert render_source_matches(vertical, original)
    assert not render_source_matches(vertical, tmp_path / "abcdefghijk.mp4")


@pytest.mark.parametrize("changed", ["original", "subtitles", "vertical"])
def test_corrupt_binding_never_falls_back_to_untrimmed_original(tmp_path, changed):
    original, subtitles, vertical = make_bound_inputs(tmp_path)
    (tmp_path / "abcdefghijk.mp4").write_bytes(b"untrimmed")
    (tmp_path / "abcdefghijk.ass").write_bytes(b"old subtitles")
    {"original": original, "subtitles": subtitles, "vertical": vertical}[changed].write_bytes(b"changed")
    with pytest.raises(ValueError):
        resolve_inputs(vertical)
    assert not render_source_matches(vertical, original)


def test_binding_rejects_path_escape(tmp_path):
    _, _, vertical = make_bound_inputs(tmp_path)
    path = vertical.with_suffix(".source.json")
    payload = json.loads(path.read_text())
    payload["original"]["path"] = "../other.mp4"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        bound_render_inputs(vertical)


@pytest.mark.parametrize("overrides", [
    {"channel_id": "other"}, {"slice_index": 1}, {"trim_start": "0"}, {"trim_end": "30"},
])
def test_pipeline_preserves_unsupported_tasks(tmp_path, overrides, monkeypatch):
    from video_processing.pipeline_manager import PipelineManager
    pm = PipelineManager.__new__(PipelineManager)
    monkeypatch.setattr(pm, "_run_tracked", lambda *_args, **_kwargs: pytest.fail("不应加工"))
    video = {"youtube_id": "abcdefghijk", "channel_id": "UCAuUUnT6oDeKwE6v1NGQxug", **overrides}
    source = tmp_path / "abcdefghijk.mp4"
    assert pm._prepare_speech_opening(video, source) == source


def test_pipeline_preserves_existing_video(tmp_path, monkeypatch):
    from video_processing.pipeline_manager import PipelineManager
    pm = PipelineManager.__new__(PipelineManager)
    pm._OUT_DIR = tmp_path
    monkeypatch.setattr(pm, "_run_tracked", lambda *_args, **_kwargs: pytest.fail("不应加工历史成片"))
    (tmp_path / "abcdefghijk_vertical.mp4").write_bytes(b"existing")
    source = tmp_path / "abcdefghijk.mp4"
    assert pm._prepare_speech_opening({"youtube_id": "abcdefghijk", "channel_id":
                                      "UCAuUUnT6oDeKwE6v1NGQxug"}, source) == source


def test_pipeline_adopts_prepared_source_without_confirmation(tmp_path, monkeypatch):
    from video_processing.pipeline_manager import PipelineManager
    pm = PipelineManager.__new__(PipelineManager)
    pm._OUT_DIR, pm._PRJ_ROOT, pm._SRC_DIR = tmp_path, ROOT, ROOT / "src"
    pm._VENV_PYTHON = "python"
    source = tmp_path / "abcdefghijk.mp4"
    source.write_bytes(b"original")
    prepared = tmp_path / "speech_opening/abcdefghijk/abcdefghijk.mp4"
    prepared.parent.mkdir(parents=True)
    prepared.write_bytes(b"body")
    calls = []
    def processed(command, yid, **kwargs):
        calls.append((command, yid, kwargs))
        return subprocess.CompletedProcess(command, 0, json.dumps({
            "selected": str(prepared), "receipt": {"offset_seconds": 4.3,
                                                     "reason": "CLEAR_INITIAL_NON_SPEECH"},
        }))
    monkeypatch.setattr(pm, "_run_tracked", processed)
    assert pm._prepare_speech_opening({"youtube_id": "abcdefghijk", "channel_id":
                                      "UCAuUUnT6oDeKwE6v1NGQxug"}, source) == prepared
    assert calls[0][0][1:3] == ["-m", "video_processing.processors.speech_opening"]
    assert calls[0][2]["timeout"] == 1320


def test_pipeline_flag_off_preserves_source(tmp_path, monkeypatch):
    from config.settings import settings
    from video_processing.pipeline_manager import PipelineManager
    monkeypatch.setattr(settings, "enable_ted_opening_trim", False)
    pm = PipelineManager.__new__(PipelineManager)
    monkeypatch.setattr(pm, "_run_tracked", lambda *_args, **_kwargs: pytest.fail("关闭时不得执行"))
    source = tmp_path / "abcdefghijk.mp4"
    assert pm._prepare_speech_opening({"youtube_id": "abcdefghijk", "channel_id":
                                      "UCAuUUnT6oDeKwE6v1NGQxug"}, source) == source


@pytest.mark.parametrize("kind,field,value", [
    ("video", "start_time", "nan"), ("audio", "duration", "nan"),
    ("video", "duration", "inf"), ("audio", "start_time", "1.0"),
])
def test_prepared_rejects_invalid_timebase(monkeypatch, kind, field, value):
    info = {"duration": 8, "streams": {k: {"duration": "8", "start_time": "0"}
                                      for k in ("video", "audio")}}
    info["streams"][kind][field] = value
    monkeypatch.setattr(opening, "media_info", lambda _: info)
    with pytest.raises(ValueError, match="PREPARED_"):
        opening.validate_prepared(Path("candidate.mp4"), 8)


def test_prepared_compares_absolute_stream_ends(monkeypatch):
    # 真实535jVKx0_DI整片复现值；旧算法比较时长误报95ms，实际末端差55ms。
    info = {"duration": 663.575011, "streams": {
        "video": {"start_time": ".04", "duration": "663.48"},
        "audio": {"start_time": "0", "duration": "663.575011"}}}
    monkeypatch.setattr(opening, "media_info", lambda _: info)
    opening.validate_prepared(Path("candidate.mp4"), 663.575283)


def test_unverified_visual_and_voice_changes_preserve_original(speech_source, tmp_path):
    # 同一讲话起点，但画面新增无声内容；也检验音轨改动不能借用品牌模板。
    for kind, flags in [("visual", ["-vf", "drawbox=x=0:y=0:w=iw:h=30:color=white:t=fill"]),
                        ("voice", ["-af", "volume=0.5"])]:
        changed = tmp_path / f"{kind}.mp4"
        subprocess.run([opening.resolve_ffmpeg_cmd(), "-v", "error", "-y", "-i", str(speech_source),
                        *flags, "-c:v", "libx264", "-threads", "2", "-c:a", "aac", str(changed)],
                       check=True, capture_output=True, timeout=30)
        chosen, receipt = opening.prepare_opening(changed, tmp_path / kind)
        assert chosen == changed and receipt["reason"] == "UNVERIFIED_AV_PREFIX"


def test_manifest_change_invalidates_positive_checkpoint(speech_source, tmp_path):
    output_dir = tmp_path / "prepared"
    chosen, _ = opening.prepare_opening(speech_source, output_dir)
    assert chosen != speech_source
    opening.PREFIXES.write_text(json.dumps({"version": 1, "prefixes": []}))
    chosen, receipt = opening.prepare_opening(speech_source, output_dir)
    assert chosen == speech_source and receipt["reason"] == "UNVERIFIED_AV_PREFIX"


def test_corrupt_model_cannot_reuse_positive_checkpoint(speech_source, tmp_path, monkeypatch):
    output_dir = tmp_path / "prepared"
    assert opening.prepare_opening(speech_source, output_dir)[0] != speech_source
    model = tmp_path / "corrupt.jit"
    model.write_bytes(b"invalid model")
    monkeypatch.setattr(opening, "MODEL", model)
    chosen, receipt = opening.prepare_opening(speech_source, output_dir)
    assert chosen == speech_source and receipt["failure_code"] == "VAD_MODEL_HASH_MISMATCH"


def test_nonzero_source_timebase_preserves_original(speech_source):
    info = opening.media_info(speech_source)
    info["streams"]["audio"]["start_time"] = ".1"
    decision = opening.protect_visual_prefix(speech_source, info, opening.OpeningDecision(3.5))
    assert decision.offset_seconds == 0 and decision.reason == "UNSUPPORTED_SOURCE_TIMEBASE"
