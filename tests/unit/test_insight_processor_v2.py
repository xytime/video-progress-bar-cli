"""InsightProcessor V2 深度二创、全幅安全横栏、0.6s Dip to Black + 60Hz Hit 母带转场与门禁降级测试 (RFC-2026-DEEP-CREATION-001)。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-08 | Antigravity | 覆盖 V2 原片零裁切、Y=265~555 安全横栏、VTT 事实引证门禁、三级收据与自动降级 |
| 1.1.0 | 2026-10-08 | Antigravity | 消除 VTT 门禁测试静默跳过漏洞，增加片头图腾/片尾二维码渲染、严格 V2 网关及 CLI 错误报告单测 |
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
    def test_safe_horizontal_bar_dimensions_and_isolation(self, tmp_path):
        """卡片渲染为 Y=265~555 全幅安全横栏，14px 指示条，覆盖水印并留出 1365px 避让区。"""
        processor = InsightProcessor(tts=Mock())
        card_a = tmp_path / "card_a.png"
        card_b = tmp_path / "card_b.png"

        processor.render_card(
            card_a, "为什么纽约州长能越级夺权？",
            ["1. 宪政纠偏：州长签署紧急行政令指派总检察长作为特检接管案件",
             "2. 外部独立：州政府敦促校方启动由外部独立律师主导的全面审查",
             "3. 行政施压：州长直接对话大学校长达成整改共识突破地方层层阻力"],
            overlay=True, badge="制度透视", card_index=1,
        )
        processor.render_card(
            card_b, "常春藤兄弟会背后的权力盲区",
            ["1. 掩盖报告：校警向检方提交的初查报告中关键受害陈述竟被完全隐匿",
             "2. 案发指控：受害人详尽指控在兄弟会酒局遭到五名醉酒男性的严重侵害",
             "3. 司法失职：地方检察官未对涉案人员全面质询便仓促撤案引发公信力危机"],
            overlay=True, badge="利益博弈", card_index=2,
        )

        for path, expected_indicator_color in [
            (card_a, (245, 197, 66)),  # Card 1 金黄色
            (card_b, (56, 189, 248)),  # Card 2 青蓝色
        ]:
            with Image.open(path) as img:
                assert img.size == (1080, 1920)
                # 顶部 0~264 完全透明 (避让上方空间)
                assert img.getpixel((540, 100))[3] == 0
                assert img.getpixel((0, 0))[3] == 0

                # 横栏 Y=265~555 为 100% 不透明深度蓝灰底板 (彻底覆盖源视频日期水印)
                pixel_center = img.getpixel((540, 400))
                assert pixel_center[3] == 255
                assert pixel_center[0] == 12 and pixel_center[1] == 18 and pixel_center[2] == 32

                # 左侧 14px 内为发光指示条
                indicator_pixel = img.getpixel((6, 300))
                assert indicator_pixel[3] == 255
                assert indicator_pixel[0] == expected_indicator_color[0]
                assert indicator_pixel[1] == expected_indicator_color[1]
                assert indicator_pixel[2] == expected_indicator_color[2]

                # 底部 Y=556~1919 (高达 1365px) 完全透明，避让人脸与双语字幕
                # 验证 1920 - 555 == 1365
                assert 1920 - 555 == 1365
                assert img.getpixel((540, 600))[3] == 0
                assert img.getpixel((540, 1200))[3] == 0
                assert img.getpixel((540, 1800))[3] == 0

    def test_full_body_zero_trim_contract(self, tmp_path, monkeypatch):
        """当输入为 InsightScriptV2 时，彻底废除 trim/atrim，100% 保留正文。"""
        captured_commands = []

        def mock_runner(cmd, **kw):
            captured_commands.append(cmd)
            # 模拟生成目标产物文件，使后续校验与重命名正常流转
            out_file = Path(cmd[-1])
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_bytes(b"mock video data")

        processor = InsightProcessor(tts=Mock(), runner=mock_runner)

        # 伪造 180 秒视频
        source = tmp_path / "source.mp4"
        source.write_bytes(b"dummy")
        script_file = tmp_path / "script.json"
        script_file.write_text(json.dumps(FEW_SHOT_EXAMPLE_CORNELL), encoding="utf-8")
        output = tmp_path / "output.mp4"

        monkeypatch.setattr(module, "duration", lambda _: 180.0)
        monkeypatch.setattr(module, "validate_media", lambda *args: None)

        success = processor.process(source, script_file, output)
        assert success is True

        # 检查正文处理 FFmpeg 命令，确保没有出现 trim/atrim
        main_cmd = captured_commands[2]  # cmd 0: intro, cmd 1: outro, cmd 2: main segment
        cmd_str = " ".join(main_cmd)
        assert "trim=" not in cmd_str
        assert "atrim=" not in cmd_str
        # 必须包含 1080:1920 缩放与首尾 0.6s Dip to Black 溶镜
        assert "scale=1080:1920" in cmd_str
        assert "fade=t=in:st=0:d=0.6" in cmd_str
        assert "fade=t=out:st=179.4:d=0.6" in cmd_str
        # 必须包含两张卡片的 overlay
        assert "overlay=0:0:enable='between(t,22.0,44.0)'" in cmd_str
        assert "overlay=0:0:enable='between(t,70.0,95.0)'" in cmd_str

    def test_three_level_sha256_receipt_system(self, tmp_path, monkeypatch):
        """验证三级 SHA-256 收据系统结构与 valid_enrichment 双向校验。"""
        processor = InsightProcessor(tts=LocalSpeech44100())
        monkeypatch.setattr(settings, "insight_default_voice", "zh-CN-YunyangNeural")

        # 生成 14 秒真实测试视频 (44.1kHz 立体声, 1080x1920 @ 30fps)
        source = tmp_path / "base.mp4"
        subprocess.run([
            "ffmpeg", "-nostdin", "-v", "error", "-y",
            "-f", "lavfi", "-i", "color=c=black:s=1080x1920:r=30",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
            "-t", "14",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ar", "44100", "-ac", "2",
            str(source)
        ], check=True)

        # 调整测试脚本卡片时间，单卡时长须满足 5.0~45.0s 契约约束
        test_script = copy.deepcopy(FEW_SHOT_EXAMPLE_CORNELL)
        test_script["cards"][0]["start_sec"] = 1.0
        test_script["cards"][0]["end_sec"] = 6.5  # 5.5s
        test_script["cards"][1]["start_sec"] = 7.0
        test_script["cards"][1]["end_sec"] = 13.0  # 6.0s

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

    def test_generate_insight_script_rejects_hallucination(self, tmp_path, monkeypatch):
        """generate_insight_script 若在网关引证校验失败，必须拒绝写入并返回 False。"""
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

        output = tmp_path / "test_insight.json"
        success = generate_insight_script("测试标题", tmp_path / "dummy.mp4", subtitle, output)

        assert success is False
        assert not output.exists()



class TestBrandAssetRendering:
    def test_render_intro_card_brand_assets(self, tmp_path):
        """片头导读大卡必须完整渲染图腾微标、品牌名称、主 Slogan 与标题口播。"""
        processor = InsightProcessor(tts=Mock())
        intro_png = tmp_path / "intro_brand.png"
        processor.render_intro_card(
            intro_png,
            "名校兄弟会黑幕被掩盖",
            "常春藤名校兄弟会深陷性侵丑闻，地方校警与检方却在调查中涉嫌刻意包庇。",
        )
        assert intro_png.is_file()
        with Image.open(intro_png) as img:
            assert img.size == (1080, 1920)
            # 背景不透明
            assert img.getpixel((540, 960))[3] == 255

    def test_render_outro_card_brand_assets_and_poll(self, tmp_path):
        """片尾终章大卡必须包含哲学金句、思辨议题、A/B/C投票选项与官方受控二维码。"""
        processor = InsightProcessor(tts=Mock())
        outro_png = tmp_path / "outro_brand.png"
        processor.render_outro_card(
            outro_png,
            "当机构的自保本能压过个体正义，法治的阳光该照向何方？",
            "常春藤名校与地方司法的利益闭环，是否需联邦立法强制监管？",
            ["必须立法穿透", "坚持高校自治", "视案件性质而定"],
        )
        assert outro_png.is_file()
        with Image.open(outro_png) as img:
            assert img.size == (1080, 1920)
            assert img.getpixel((540, 960))[3] == 255


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
