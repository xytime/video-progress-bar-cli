"""洞察契约、卡片、失败隔离和真实合成测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-06 | Codex | 验证生产开关、回退、输入绑定与真实 FFmpeg 输出 |
"""
import json
import subprocess
import wave
from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image
from pydantic import ValidationError

from config.settings import Settings, settings
from video_processing.core.insight_script import InsightScript
from video_processing.processors import insight_processor as module
from video_processing.processors.insight_processor import InsightProcessor, valid_enrichment


@pytest.fixture
def payload():
    return {"hook_title": "观察制度的边界", "hook_narration": "应当如何理解这段发言？",
            "highlight_window": {"start_sec": 0, "end_sec": 1},
            "context_cards": [
                {"trigger_sec": 0.1, "duration_sec": 0.3, "badge": "制度透视", "points": ["先区分事实与判断"]},
                {"trigger_sec": 0.5, "duration_sec": 0.3, "badge": "适用边界", "points": ["个案不能替代规律"]}],
            "closing_takeaway": {"quote": "从证据出发", "narration": "哪些信息仍然值得核验？",
                                 "poll_topic": "你会先核验什么？"}}


def test_defaults_and_review_text(payload):
    defaults = Settings(_env_file=None)
    assert defaults.enable_deep_insight_enrichment is False
    assert defaults.insight_default_voice == "zh-CN-YunyangNeural"
    script = InsightScript.model_validate(payload)
    assert all(text in script.review_text() for text in ["制度透视", "个案不能替代规律", "你会先核验什么？"])


@pytest.mark.parametrize("change", ["reverse", "nan", "overlap", "outside", "blank", "extra"])
def test_invalid_schema(payload, change):
    if change == "reverse":
        payload["highlight_window"]["end_sec"] = 0
    elif change == "nan":
        payload["highlight_window"]["start_sec"] = float("nan")
    elif change == "overlap":
        payload["context_cards"][1]["trigger_sec"] = 0.2
    elif change == "outside":
        payload["context_cards"][1]["duration_sec"] = 3
    elif change == "blank":
        payload["hook_narration"] = " "
    else:
        payload["extra"] = True
    with pytest.raises(ValidationError):
        InsightScript.model_validate(payload)


def test_real_cards_preserve_transparent_regions(tmp_path):
    processor = InsightProcessor(tts=Mock())
    for overlay in [False, True]:
        path = tmp_path / f"{overlay}.png"
        processor.render_card(path, "制度透视", ["证据和判断需要区分"], overlay=overlay)
        with Image.open(path) as image:
            assert image.size == (1080, 1920)
            assert image.getpixel((0, 0))[3] == (0 if overlay else 255)
            assert image.getpixel((80, 400))[3] > 0


def test_layout_overflow_rejected(tmp_path):
    with pytest.raises(ValueError, match="超出"):
        InsightProcessor(tts=Mock()).render_card(tmp_path / "bad.png", "长文", ["长" * 500], overlay=True)


@pytest.mark.parametrize("failure", ["schema", "card", "tts", "ffmpeg"])
def test_failure_preserves_base_and_never_creates_output(tmp_path, payload, monkeypatch, caplog, failure):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"original")
    script = tmp_path / "insight.json"
    script.write_text(json.dumps(payload) if failure != "schema" else "{}")
    output = tmp_path / "insight.mp4"
    tts = Mock()
    processor = InsightProcessor(tts=tts)
    monkeypatch.setattr(module, "duration", lambda _: 1)
    if failure == "card":
        monkeypatch.setattr(processor, "render_card", Mock(side_effect=ValueError("card")))
    elif failure == "tts":
        tts.generate_audio.side_effect = RuntimeError("tts")
    elif failure == "ffmpeg":
        monkeypatch.setattr(processor, "run", Mock(side_effect=RuntimeError("ffmpeg")))
    assert processor.process(source, script, output, allow_legacy=True) is False
    assert source.read_bytes() == b"original"
    assert not output.exists()
    assert "InsightFallback" in caplog.text
    assert not list(tmp_path.glob("insight-*"))


def test_window_outside_source_fails_before_tts(tmp_path, payload, monkeypatch):
    source, script = tmp_path / "source.mp4", tmp_path / "script.json"
    source.write_bytes(b"original")
    script.write_text(json.dumps(payload))
    monkeypatch.setattr(module, "duration", lambda _: 0.2)
    tts = Mock()
    assert not InsightProcessor(tts=tts).process(source, script, tmp_path / "output.mp4", allow_legacy=True)
    tts.generate_audio.assert_not_called()


class LocalSpeech:
    def generate_audio(self, text, output_file, voice):
        # 离线音轨替身；保留真实 ffprobe / FFmpeg / 音画时长验证。
        with wave.open(str(output_file), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(16000)
            stream.writeframes(b"\0\0" * 6400)


def test_real_ffmpeg_composition_and_cache_binding(tmp_path, payload, monkeypatch):
    monkeypatch.setattr(settings, "insight_default_voice", "zh-CN-YunyangNeural")
    source = tmp_path / "base.mp4"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=blue:s=1080x1920:r=30", "-f", "lavfi", "-i",
                    "sine=frequency=400:sample_rate=16000", "-t", "1", "-c:v", "libx264",
                    "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(source)],
                   check=True, capture_output=True, timeout=60)
    before = module.sha256(source)
    script = tmp_path / "script.json"
    script.write_text(json.dumps(payload))
    output = script.with_suffix(".mp4")
    assert InsightProcessor(tts=LocalSpeech()).process(source, script, output, allow_legacy=True)
    assert module.sha256(source) == before
    assert InsightScript.model_validate_json(script.read_text()).hook_title == payload["hook_title"]
    assert output.with_suffix(".receipt.json").is_file()
    # 显式历史复现可以读取，但自动生产不得采用 V1 缓存。
    assert not valid_enrichment(source, script, output)


def manager(tmp_path):
    from video_processing.pipeline_manager import PipelineManager
    result = PipelineManager.__new__(PipelineManager)
    from video_processing.db.database import PipelineDB
    result.db = PipelineDB(str(tmp_path / "pipeline.db"))
    result._OUT_DIR = tmp_path
    result._PRJ_ROOT = tmp_path
    result._SRC_DIR = tmp_path / "src"
    result._VENV_PYTHON = "python"
    return result


def test_pipeline_flag_off_never_dispatches(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "enable_deep_insight_enrichment", False)
    pm = manager(tmp_path)
    pm._run_tracked = Mock(side_effect=AssertionError("must not run"))
    assert not pm._process_insight_enrichment("id", "id", "title", tmp_path / "base.ass")
    assert pm._get_published_video_path("id") == tmp_path / "id_vertical.mp4"


def test_pipeline_processor_failure_falls_back(tmp_path, payload, monkeypatch):
    monkeypatch.setattr(settings, "enable_deep_insight_enrichment", True)
    monkeypatch.setattr(module, "valid_enrichment", lambda *args: False)
    pm = manager(tmp_path)
    (tmp_path / "id_insight.json").write_text(json.dumps(payload))
    (tmp_path / "id_insight.mp4").write_bytes(b"old output")
    pm._run_tracked = Mock(side_effect=subprocess.TimeoutExpired("insight", 1800))
    assert not pm._process_insight_enrichment("id", "id", "title", tmp_path / "base.ass")
    assert pm._get_published_video_path("id") == tmp_path / "id_vertical.mp4"


def test_pipeline_selects_valid_enrichment_and_reviews_all_text(tmp_path, payload, monkeypatch):
    monkeypatch.setattr(settings, "enable_deep_insight_enrichment", True)
    monkeypatch.setattr(module, "valid_enrichment", lambda *args: True)
    pm = manager(tmp_path)
    (tmp_path / "id_insight.json").write_text(json.dumps(payload))
    assert pm._get_published_video_path("id", expected_duration=999) == tmp_path / "id_insight.mp4"
    assert "个案不能替代规律" in pm._insight_review_text("id")


def test_censorship_receives_enrichment_even_without_subtitle_flag(tmp_path, payload, monkeypatch):
    from video_processing import pipeline_manager
    monkeypatch.setattr(settings, "enable_deep_insight_enrichment", True)
    monkeypatch.setattr(settings, "enable_subtitle_censorship", False)
    monkeypatch.setattr(module, "valid_enrichment", lambda *args: True)
    pm = manager(tmp_path)
    pm.db = Mock()
    pm.db.wallstreet_uses_normal_a.return_value = False
    pm.send_telegram_msg = Mock()
    service = Mock()
    service.check.return_value = True
    monkeypatch.setattr(pipeline_manager, "CensorshipService", Mock(return_value=service))
    (tmp_path / "id_insight.json").write_text(json.dumps(payload))
    assert pm._check_censorship("id", "title", "copy", stage="wechat_publish", fail_closed=True)
    assert "你会先核验什么？" in service.check.call_args.args[2]


def test_planner_rejects_legacy_provider_result(tmp_path, payload, monkeypatch):
    from video_processing.utils import insight_planner
    monkeypatch.setattr(settings, "enable_deep_insight_enrichment", True)
    monkeypatch.setattr(settings, "copywriter_content_provider", "agy")
    subtitle = tmp_path / "base.srt"
    subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\n观察制度边界\n", encoding="utf-8")
    monkeypatch.setattr(insight_planner, "get_video_duration_ffprobe", lambda _: 1)
    def provider(prompt, *, schema, model, command, timeout_sec, quota_cooldown_sec, cache_dir, validate):
        assert "观察制度边界" in prompt
        assert "不编造" in prompt
        return validate(payload)
    monkeypatch.setattr(insight_planner, "generate_cached_agy_copy", provider)
    output = tmp_path / "id_insight.json"
    assert not insight_planner.generate_insight_script("title", tmp_path / "base.mp4", subtitle, output)
    assert not output.exists()


def test_planner_failure_and_disabled_never_write(tmp_path, monkeypatch):
    from video_processing.utils.insight_planner import generate_insight_script
    output = tmp_path / "id_insight.json"
    for enabled in [False, True]:
        monkeypatch.setattr(settings, "enable_deep_insight_enrichment", enabled)
        assert not generate_insight_script("title", tmp_path / "missing.mp4", tmp_path / "missing.ass", output)
        assert not output.exists()


def test_pipeline_replans_when_automatic_plan_source_changes(tmp_path, payload, monkeypatch):
    monkeypatch.setattr(settings, "enable_deep_insight_enrichment", True)
    calls = []
    monkeypatch.setattr(module, "valid_enrichment", lambda *args: len(calls) == 2)
    pm = manager(tmp_path)
    source = tmp_path / "id_vertical.mp4"
    subtitle = tmp_path / "base.ass"
    script = tmp_path / "id_insight.json"
    source.write_bytes(b"new source")
    subtitle.write_bytes(b"subtitle")
    script.write_text(json.dumps(payload))
    (tmp_path / "id_insight_plan.json").write_text(json.dumps({
        "source_sha256": "old", "subtitle_sha256": "old", "script_sha256": "old",
    }))
    def tracked(cmd, *args, **kwargs):
        calls.append(cmd)
        if "--insight-only" in cmd:
            from video_processing.utils.insight_v2_prompt import FEW_SHOT_EXAMPLE_CORNELL
            script.write_text(json.dumps(FEW_SHOT_EXAMPLE_CORNELL))
    pm._run_tracked = tracked
    assert pm._process_insight_enrichment("id", "id", "title", subtitle)
    assert "--insight-only" in calls[0]
    assert "video_processing.processors.insight_processor" in calls[1]
    receipt = json.loads((tmp_path / "id_insight_plan.json").read_text())
    assert receipt["source_sha256"] == module.sha256(source)
