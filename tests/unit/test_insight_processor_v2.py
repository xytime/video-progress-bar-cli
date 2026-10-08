"""InsightProcessor V2 深度二创、全幅安全横栏、0.6s Dip to Black + 60Hz Hit 母带转场与门禁降级测试 (RFC-2026-DEEP-CREATION-001)。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-08 | Antigravity | 覆盖 V2 原片零裁切、Y=265~555 安全横栏、VTT 事实引证门禁、三级收据与自动降级 |
| 1.1.0 | 2026-10-08 | Antigravity | 消除 VTT 门禁测试静默跳过漏洞，增加片头图腾/片尾二维码渲染、严格 V2 网关及 CLI 错误报告单测 |
| 1.2.0 | 2026-10-09 | Codex | 使用明确时码夹具验收真实编码及缓存，不把静音替身当真实 ASR |
"""
import copy
import json
import subprocess
import wave
from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image

from config.settings import settings
from video_processing.core.insight_script import InsightScriptV2
from video_processing.processors import insight_processor as module
from video_processing.processors.insight_processor import InsightProcessor, valid_enrichment
from video_processing.utils.insight_planner import verify_vtt_evidence, generate_insight_script
from video_processing.utils.insight_v2_prompt import FEW_SHOT_EXAMPLE_CORNELL, FEW_SHOT_EXAMPLE_NOBEL


class LocalSpeech44100:
    """离线 44.1kHz 音轨生成替身，支持全流程媒体校验。"""
    def generate_audio(self, text, output_file, voice=None):
        with wave.open(str(output_file), "wb") as stream:
            stream.setnchannels(2)
            stream.setsampwidth(2)
            stream.setframerate(44100)
            # 生成约 0.5s 静音
            stream.writeframes(b"\0\0\0\0" * 22050)


class TestInsightProcessorV2:
    def test_missing_original_falls_back_before_tts(self, tmp_path, monkeypatch):
        source = tmp_path / "base_vertical.mp4"
        source.write_bytes(b"base")
        script = tmp_path / "script.json"
        script.write_text(json.dumps(FEW_SHOT_EXAMPLE_CORNELL))
        tts = Mock()
        monkeypatch.setattr(module, "duration", lambda _: 180.0)
        assert not InsightProcessor(tts=tts).process(source, script, tmp_path / "output.mp4")
        tts.generate_audio.assert_not_called()
        assert source.read_bytes() == b"base"

    @pytest.mark.parametrize("provider", ["edge", "doubao"])
    def test_three_level_sha256_receipt_system(self, tmp_path, monkeypatch, provider):
        """验证三级 SHA-256 收据系统结构与 valid_enrichment 双向校验。"""
        from video_processing.core.tts_engine import TTSProvider
        tts = LocalSpeech44100()
        tts.provider = TTSProvider(provider)
        monkeypatch.setattr(settings, "tts_provider", provider)
        monkeypatch.setattr(settings, "doubao_tts_api_key", "offline-test-placeholder")
        processor = InsightProcessor(tts=tts)
        monkeypatch.setattr(settings, "insight_default_voice", "zh-CN-YunyangNeural")

        # 生成 14 秒真实测试视频 (44.1kHz 立体声, 1080x1920 @ 30fps)
        original = tmp_path / "base.mp4"
        source = tmp_path / "base_vertical.mp4"
        subprocess.run([
            "ffmpeg", "-nostdin", "-v", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
            "-t", "14",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ar", "44100", "-ac", "2",
            str(original)
        ], check=True)
        source.write_bytes(original.read_bytes())
        (tmp_path / "base.ass").write_text("[Script Info]\nScriptType: v4.00+\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\nDialogue: 0,0:00:00.00,0:00:14.00,Default,,0,0,0,,The complete source frame is preserved.\\N完整保留原始视频画面。\n")

        # 调整测试脚本卡片时间，单卡时长须满足 5.0~45.0s 契约约束
        test_script = copy.deepcopy(FEW_SHOT_EXAMPLE_CORNELL)
        test_script["cards"][0]["start_sec"] = 1.0
        test_script["cards"][0]["end_sec"] = 6.5  # 5.5s
        test_script["cards"][1]["start_sec"] = 7.0
        test_script["cards"][1]["end_sec"] = 13.0  # 6.0s

        # 静音只用于编码和收据测试；真实语音对齐由单独实片验收。
        from video_processing.processors import insight_mobile
        from video_processing.processors.mobile_editorial_layout import clean
        def fixture_alignment(processor, path, output):
            text = (test_script['hook']['narration'] if path.name=='voice-0.wav'
                    else InsightScriptV2.model_validate(test_script).outro.tts_narration if path.name=='voice-1.wav'
                    else 'The complete source frame is preserved.')
            chars = clean(text)
            length = .5 if path.suffix=='.wav' else 14
            return [{'word':c,'start':i*length/len(chars),'end':(i+1)*length/len(chars)}
                    for i,c in enumerate(chars)]
        monkeypatch.setattr(insight_mobile,'align_audio',fixture_alignment)

        script_file = tmp_path / "cornell_script.json"
        script_file.write_text(json.dumps(test_script), encoding="utf-8")
        output = tmp_path / "masterpiece_output.mp4"

        ok = processor.process(source, script_file, output)
        assert ok is True
        assert output.is_file()

        receipt_file = output.with_suffix(".receipt.json")
        assert receipt_file.is_file()
        receipt = json.loads(receipt_file.read_text(encoding="utf-8"))

        # Level 1 验证
        assert "level1_manifest" in receipt
        assert receipt["level1_manifest"]["source_sha256"] == module.sha256(source)
        assert receipt["level1_manifest"]["script_sha256"] == module.sha256(script_file)

        # Level 2 验证 (三大段落)
        assert "level2_segments" in receipt
        segments = receipt["level2_segments"]
        assert len(segments) == 3
        assert segments[0]["segment"] == "intro"
        assert segments[1]["segment"] == "main"
        assert segments[2]["segment"] == "outro"

        # Level 3 验证
        assert "level3_receipt" in receipt
        assert receipt["level3_receipt"]["output_sha256"] == module.sha256(output)
        assert receipt["level3_receipt"]["sample_rate"] == 44100
        assert receipt["level3_receipt"]["validate_media_passed"] is True

        # valid_enrichment 双向校验通过
        assert valid_enrichment(source, script_file, output) is True
        assert receipt["tts_provider"] == provider
        assert len(receipt["point_timeline"]) == 6
        assert segments[1]["duration"] == 14
        for input_file in (original, tmp_path / "base.ass"):
            data = input_file.read_bytes()
            input_file.write_bytes(data + b"changed")
            assert not valid_enrichment(source, script_file, output)
            input_file.write_bytes(data)
            assert valid_enrichment(source, script_file, output)
        expected_voice = settings.doubao_tts_speaker if provider == "doubao" else settings.insight_default_voice
        assert receipt["voice"] == expected_voice
        # 重复校验复用同一母带；改变任何实际渲染参数必须使缓存失效。
        for name, changed in [("transition_sfx_volume", 0.73),
                              ("doubao_tts_speech_rate", 29) if provider == "doubao"
                              else ("insight_default_voice", "another-voice")]:
            with monkeypatch.context() as patch:
                patch.setattr(settings, name, changed)
                assert not valid_enrichment(source, script_file, output)
            assert valid_enrichment(source, script_file, output)
        with monkeypatch.context() as patch:
            patch.setattr(module, "RENDER_RECIPE", "new-layout")
            assert not valid_enrichment(source, script_file, output)
        receipt.pop("render_spec")
        receipt_file.write_text(json.dumps(receipt))
        assert not valid_enrichment(source, script_file, output)


class TestEvidenceVerificationGate:
    def test_verify_vtt_evidence_real_benchmarks(self):
        """真实 VTT 字幕文件引证 100% 通过门禁 (无静默跳过)。"""
        # 测试 Cornell 标杆
        vtt_cornell = Path("tests/fixtures/vtt/SfNypZIb0H4_source_subtitle.en.vtt")
        if not vtt_cornell.is_file():
            vtt_cornell = Path("output/SfNypZIb0H4_source_subtitle.en.vtt")
        assert vtt_cornell.is_file(), "Cornell 标杆 VTT 测试资产缺失"
        script_cornell = InsightScriptV2.model_validate(FEW_SHOT_EXAMPLE_CORNELL)
        assert verify_vtt_evidence(script_cornell, vtt_cornell) is True

        # 测试 Nobel 标杆
        vtt_nobel = Path("tests/fixtures/vtt/RaUWCtcJtK8_source_subtitle.en.vtt")
        if not vtt_nobel.is_file():
            vtt_nobel = Path("output/RaUWCtcJtK8_source_subtitle.en.vtt")
        assert vtt_nobel.is_file(), "Nobel 标杆 VTT 测试资产缺失"
        script_nobel = InsightScriptV2.model_validate(FEW_SHOT_EXAMPLE_NOBEL)
        assert verify_vtt_evidence(script_nobel, vtt_nobel) is True

    def test_verify_vtt_evidence_hallucination_intercepted(self, tmp_path):
        """AI 幻觉或伪造引证台词未能达到 80% 词频匹配时必须被 Fail-Closed 拦截。"""
        vtt = tmp_path / "mock.vtt"
        vtt.write_text(
            "WEBVTT\n\n"
            "00:00:01.000 --> 00:00:06.000\n"
            "The governor announced a new transportation plan today.\n",
            encoding="utf-8",
        )

        bad_script_data = copy.deepcopy(FEW_SHOT_EXAMPLE_CORNELL)
        # 台词引用被篡改为完全不相关的文本
        bad_script_data["cards"][0]["points"][0]["vtt_reference"]["source_quote"] = (
            "signed an executive order appointing Attorney General Letitia James"
        )
        bad_script = InsightScriptV2.model_validate(bad_script_data)

        # 必须拦截返回 False
        assert verify_vtt_evidence(bad_script, vtt) is False

    def test_generate_insight_script_records_quote_warning_without_blocking(self, tmp_path, monkeypatch):
        """普通事实疑点须留档，但不停止脚本生成。"""
        monkeypatch.setattr(settings, "enable_deep_insight_enrichment", True)
        monkeypatch.setattr(settings, "copywriter_content_provider", "agy")

        subtitle = tmp_path / "base.srt"
        subtitle.write_text("1\n00:00:00,000 --> 00:00:10,000\n无关新闻报道文本\n", encoding="utf-8")

        from video_processing.utils import insight_planner
        monkeypatch.setattr(insight_planner, "get_video_duration_ffprobe", lambda _: 180.0)

        # 模拟 LLM 返回了 Cornell 脚本（但当前 subtitle 里根本没有这些台词）
        def provider(*args, validate=None, **kw):
            return validate(FEW_SHOT_EXAMPLE_CORNELL)

        monkeypatch.setattr(insight_planner, "generate_cached_agy_copy", provider)
        from video_processing.utils import insight_evidence
        monkeypatch.setattr(insight_evidence, "generate_cached_agy_copy", Mock(side_effect=TimeoutError))

        output = tmp_path / "test_insight.json"
        success = generate_insight_script("测试标题", tmp_path / "dummy.mp4", subtitle, output)

        assert success is True
        assert output.exists()
        report = json.loads(output.with_suffix(".evidence.json").read_text())
        assert report["status"] == "NEEDS_REVIEW"
        assert report["publication_blocked"] is False
        assert report["semantic_review"]["status"] == "UNAVAILABLE"



class TestGracefulDegradation:
    def test_pipeline_manager_enrichment_degraded_status(self, tmp_path, monkeypatch):
        """当二创增强失败时，DAL 状态机置为 DEGRADED，记录错误日志，并自动使用常规视频发布。"""
        from video_processing.pipeline_manager import PipelineManager
        monkeypatch.setattr(settings, "enable_deep_insight_enrichment", True)
        monkeypatch.setattr(module, "valid_enrichment", lambda *args: False)

        pm = PipelineManager.__new__(PipelineManager)
        pm._OUT_DIR = tmp_path
        pm._PRJ_ROOT = tmp_path
        pm._SRC_DIR = tmp_path / "src"
        pm._VENV_PYTHON = "python"
        pm.db = Mock()
        pm.send_telegram_msg = Mock()

        # 模拟 run_tracked 抛出异常
        pm._run_tracked = Mock(side_effect=RuntimeError("FFmpeg mother-tape assembly failed"))
        pm.db.wallstreet_uses_normal_a.return_value = False

        source = tmp_path / "Vid01_vertical.mp4"
        source.write_bytes(b"base video")
        subtitle = tmp_path / "Vid01.ass"
        subtitle.write_bytes(b"subtitle")
        script = tmp_path / "Vid01_insight.json"
        script.write_text(json.dumps(FEW_SHOT_EXAMPLE_CORNELL), encoding="utf-8")

        success = pm._process_insight_enrichment("Vid01", "Vid01", "测试", subtitle, slice_index=0)

        assert success is False
        # 1. 验证 DAL 状态机回写为 DEGRADED
        pm.db.update_enrichment_status.assert_called_with("Vid01", "DEGRADED", slice_index=0)

        # 2. 验证写入错误日志
        error_log = tmp_path / "logs/enrichment_error.log"
        assert error_log.is_file()
        assert "RuntimeError" in error_log.read_text(encoding="utf-8")

        # 3. 验证 Telegram 发出告警
        assert pm.send_telegram_msg.called

        # 4. 验证发布路径自动平滑降级至基础竖版成片
        assert pm._get_published_video_path("Vid01") == source


class TestMasterpieceCliExecution:
    def test_run_masterpiece_json_error_output_and_dal_failure(self, tmp_path, monkeypatch, capsys):
        """run_masterpiece.py 失败且带有 --json 时，必须向 stdout 打印结构化 JSON 错误报告并记录 DAL FAILED。"""
        import scripts.run_masterpiece as masterpiece_mod

        mock_db = Mock()
        monkeypatch.setattr(masterpiece_mod, "PipelineDB", lambda: mock_db)

        # 触发 run_masterpiece_pipeline 抛出异常 (输入不存在)
        test_args = ["run_masterpiece.py", "SfNypZIb0H4", "--output-dir", str(tmp_path), "--json",
                     "--source-video", str(tmp_path / "nonexistent.mp4")]
        monkeypatch.setattr("sys.argv", test_args)

        ret = masterpiece_mod.main()
        assert ret == 1

        # 验证 stdout 包含了合法且包含 FAILED 的 JSON
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["youtube_id"] == "SfNypZIb0H4"
        assert data["status"] == "FAILED"
        assert "error" in data

        # 验证 DAL 状态机被置为 FAILED
        mock_db.update_enrichment_status.assert_called_with("SfNypZIb0H4", "FAILED", slice_index=0)
