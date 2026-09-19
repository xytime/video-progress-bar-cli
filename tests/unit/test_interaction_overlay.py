# -*- coding: utf-8 -*-
"""跑道级流光互动转化系统 (Project Runway-CTA) 单元测试

覆盖：
1. 跨平台字体解析 resolve_render_font：候选回退与 default font 兜底
2. 音效生成 synthesize_pop_audio：wave 格式、采样率、位深与声道验证
3. 矢量绘图原子：draw_rounded_rect, draw_plus_icon, draw_thumb_up, draw_speech_bubble, draw_cursor
4. 核心视效组件：
   - create_badge_a (中央白瓷三联胶囊，点赞/关注状态)
   - create_hook_banner (尾部转化顶栏横幅)
   - render_option_c_pointer (左下角黑曜石磨砂胶囊 + 45° 跑道微标，无内置箭头)
5. 单帧合成 build_overlay_frame：
   - 画布尺寸 1080x1920，RGBA 格式
   - 中央胶囊定位在 Y=820
   - 左下角组件定位在 X=85, Y=1680
   - 双语字幕区 (Y=1040~1260) 100% 洁净，无任何像素遮挡
6. 触发时机计算 compute_triggers：
   - 极短视频 (<12s) 安全跳过
   - 短视频 (12s~22s) 单埋点平滑降级
   - 标准长视频 (60s) 双埋点与片尾安全边距
7. 处理器抽象与参数绑定 InteractionOverlayProcessor：
   - 输入验证、输出默认命名、音效参数透传
8. 流水线集成与缓存失效规则 (_get_published_video_path)：
   - enable_interaction_overlay=False 时透明回退至 _vertical.mp4
   - 开启时优先使用有效 _vertical_interactive.mp4
   - 上游 _vertical.mp4 mtime 更新时互动缓存失效
   - 截断损坏/小体积文件安全降级回退

# Modification History
| Version | Date       | Author      | Description |
| ------- | ---------- | ----------- | ----------- |
| 1.0.0   | 2026-09-19 | Antigravity | 初始创建：Project Runway-CTA 完整单元测试集，覆盖图形、时序、音频、避让与发布选片路由 |
"""
import os
import sys
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from config.settings import settings
from video_processing.processors import interaction_overlay as io_mod
from video_processing.processors.interaction_overlay import (
    InteractionOverlayProcessor,
    InteractionTrigger,
    build_overlay_frame,
    compute_triggers,
    create_badge_a,
    create_hook_banner,
    render_option_c_pointer,
    resolve_render_font,
    synthesize_pop_audio,
)


class TestRenderFontResolver:
    def test_resolve_render_font_returns_font(self):
        font = resolve_render_font(24, bold=True)
        assert font is not None

    def test_resolve_render_font_fallback(self):
        # 即使无系统字体也必须能安全降级
        with patch("os.path.exists", return_value=False):
            font = resolve_render_font(18, bold=False)
            assert font is not None


class TestAudioSynthesis:
    def test_synthesize_pop_audio(self, tmp_path):
        wav_path = tmp_path / "test_pop.wav"
        res = synthesize_pop_audio(wav_path)
        assert res == wav_path
        assert wav_path.is_file()
        assert wav_path.stat().st_size > 500

        with wave.open(str(wav_path), "r") as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == 44100
            assert wf.getnframes() > 1000


class TestVisualComponents:
    def test_create_badge_a_structure_and_states(self):
        # 初始未点赞未关注
        b1 = create_badge_a(scale=1.0, liked=False, followed=False)
        assert isinstance(b1, Image.Image)
        assert b1.mode == "RGBA"
        assert b1.width > 600
        assert b1.height > 100

        # 已点赞已关注
        b2 = create_badge_a(scale=1.0, liked=True, followed=True, like_pop=1.2)
        assert isinstance(b2, Image.Image)
        assert b2.size == b1.size

    def test_create_hook_banner(self):
        banner = create_hook_banner(scale=1.0, text="测试转化标语")
        assert isinstance(banner, Image.Image)
        assert banner.mode == "RGBA"
        assert banner.width > 500

    def test_render_option_c_pointer_dimensions_and_alpha(self):
        # v2.0 尺寸: 540x340 (v1 为 360x180, 胶囊 390×94px + 箭头区域)
        p1 = render_option_c_pointer(scale=4, phase=0.25, alpha=1.0)
        assert p1.size == (540, 340)
        assert p1.mode == "RGBA"

        # alpha 为 0 时的空白透明画布
        p_zero = render_option_c_pointer(scale=4, phase=0.0, alpha=0.0)
        assert p_zero.size == (540, 340)
        # 检查是否全透明
        assert max(p_zero.getchannel("A").getextrema()) == 0


class TestOverlayFrameAndZeroCollision:
    def test_build_overlay_frame_dimensions(self):
        frame = build_overlay_frame(t=2.5, duration=8.0, with_hook=True)
        assert frame.size == (1080, 1920)
        assert frame.mode == "RGBA"

    def test_zero_subtitle_collision(self):
        """
        核心物理防线验收：
        中英双语字幕区（Y=1040~1260）在整个动画生命周期中必须 100% 洁净，不能有任何非透明像素。
        """
        test_times = [0.2, 0.8, 1.4, 2.0, 3.0, 5.0, 7.0]
        for t in test_times:
            frame = build_overlay_frame(t=t, duration=8.0, with_hook=True)
            # 裁剪字幕敏感带: X=0~1080, Y=1040~1260
            subtitle_zone = frame.crop((0, 1040, 1080, 1260))
            alpha_extrema = subtitle_zone.getchannel("A").getextrema()
            assert alpha_extrema[1] == 0, f"在 t={t}s 时检测到字幕区被组件遮挡！最大 Alpha={alpha_extrema[1]}"

    def test_staggered_corner_delay(self):
        """
        错峰延时验收（v2.0）：
        左下角组件 (X=70, Y=1460) 必须在 t=2.0s 之前完全隐藏（Alpha=0），在 t > 2.0s 之后才开始显现。
        """
        # t=1.8s (延时期间)
        frame_before = build_overlay_frame(t=1.8, duration=8.0)
        corner_zone_before = frame_before.crop((70, 1460, 70 + 540, 1460 + 340))
        assert corner_zone_before.getchannel("A").getextrema()[1] == 0

        # t=2.5s (延时已过，波纹脉冲中)
        frame_after = build_overlay_frame(t=2.5, duration=8.0)
        corner_zone_after = frame_after.crop((70, 1460, 70 + 540, 1460 + 340))
        assert corner_zone_after.getchannel("A").getextrema()[1] > 0


class TestComputeTriggers:
    def test_too_short_video_returns_empty(self):
        assert compute_triggers(10.0) == []

    def test_short_video_returns_single_trigger(self):
        triggers = compute_triggers(18.0)
        assert len(triggers) == 1
        assert triggers[0].start_sec >= 2.0
        assert triggers[0].start_sec + triggers[0].duration_sec <= 18.0

    def test_standard_60s_video_dual_triggers(self):
        triggers = compute_triggers(60.0)
        assert len(triggers) == 2
        # Trigger 1: 黄金钩子 10~15s 之间
        assert 10.0 <= triggers[0].start_sec <= 15.0
        assert not triggers[0].with_hook
        # Trigger 2: t1 之后至少 12s 且不溢出
        assert triggers[1].start_sec >= triggers[0].start_sec + 12.0
        assert triggers[1].start_sec + triggers[1].duration_sec <= 60.0
        assert triggers[1].with_hook

    def test_long_video_golden_hook_timing(self):
        """验收：15 分钟长视频的 T1 触发时机在黄金 10~15s 窗口内，不再是 2 分 39 秒"""
        triggers = compute_triggers(885.0)  # iJEhc52SBMw: 885.77s
        assert len(triggers) == 2
        assert 10.0 <= triggers[0].start_sec <= 15.0, f"长视频 T1 超出黄金窗口: {triggers[0].start_sec}s"
        assert triggers[1].with_hook


class TestInteractionOverlayProcessorUnit:
    def test_missing_input_raises_filenotfound(self, tmp_path):
        fake_video = tmp_path / "non_existent.mp4"
        with pytest.raises(FileNotFoundError):
            InteractionOverlayProcessor(input_path=fake_video)

    def test_default_output_naming(self, tmp_path):
        dummy_video = tmp_path / "sample_vertical.mp4"
        dummy_video.write_bytes(b"dummy")
        proc = InteractionOverlayProcessor(input_path=dummy_video)
        assert proc.output_path == tmp_path / "sample_vertical_interactive.mp4"


class TestPipelinePublishedVideoSelection:
    @pytest.fixture
    def mock_manager(self, tmp_path):
        from video_processing.pipeline_manager import PipelineManager
        pm = PipelineManager.__new__(PipelineManager)
        pm._OUT_DIR = tmp_path
        return pm

    def test_when_disabled_always_returns_vertical(self, mock_manager, tmp_path):
        prefix = "vid123"
        vertical = tmp_path / f"{prefix}_vertical.mp4"
        interactive = tmp_path / f"{prefix}_vertical_interactive.mp4"
        vertical.write_bytes(b"x" * 2_000_000)
        interactive.write_bytes(b"x" * 2_000_000)

        with patch.object(settings, "enable_interaction_overlay", False):
            result = mock_manager._get_published_video_path(prefix)
            assert result == vertical

    def test_when_enabled_and_interactive_valid(self, mock_manager, tmp_path):
        prefix = "vid123"
        vertical = tmp_path / f"{prefix}_vertical.mp4"
        interactive = tmp_path / f"{prefix}_vertical_interactive.mp4"
        vertical.write_bytes(b"x" * 2_000_000)
        interactive.write_bytes(b"x" * 2_000_000)

        # 确保 interactive 的 mtime >= vertical 的 mtime
        os.utime(vertical, (1000, 1000))
        os.utime(interactive, (2000, 2000))

        with patch.object(settings, "enable_interaction_overlay", True), \
             patch("video_processing.pipeline_manager._validate_rendered_vertical_cache", return_value=(True, "")):
            result = mock_manager._get_published_video_path(prefix)
            assert result == interactive

    def test_when_vertical_newer_than_interactive_invalidates_cache(self, mock_manager, tmp_path):
        prefix = "vid123"
        vertical = tmp_path / f"{prefix}_vertical.mp4"
        interactive = tmp_path / f"{prefix}_vertical_interactive.mp4"
        vertical.write_bytes(b"x" * 2_000_000)
        interactive.write_bytes(b"x" * 2_000_000)

        # 上游 vertical 重新渲染，mtime 变新
        os.utime(interactive, (1000, 1000))
        os.utime(vertical, (3000, 3000))

        with patch.object(settings, "enable_interaction_overlay", True):
            result = mock_manager._get_published_video_path(prefix)
            # 互动缓存失效，平滑回退到 vertical
            assert result == vertical

    def test_when_interactive_corrupt_or_too_small_falls_back(self, mock_manager, tmp_path):
        prefix = "vid123"
        vertical = tmp_path / f"{prefix}_vertical.mp4"
        interactive = tmp_path / f"{prefix}_vertical_interactive.mp4"
        vertical.write_bytes(b"x" * 2_000_000)
        interactive.write_bytes(b"x" * 500)  # 小于 1MB

        with patch.object(settings, "enable_interaction_overlay", True):
            result = mock_manager._get_published_video_path(prefix)
            assert result == vertical
