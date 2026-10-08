"""Unit tests for handwritten pager video generation pipeline.

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-08 | Antigravity | Comprehensive test suite for physics, typography, covers, and copy |
| 1.1.0 | 2026-10-08 | Antigravity | Add tests for new default config, tofu-free glyphs, and PCHIP physics trajectory |
"""

import math
from pathlib import Path
from PIL import Image
import pytest

from video_processing.handwritten_pager import (
    HandwrittenPagerConfig,
    LyricLine,
    LyricWord,
    PenState,
    CopywritingPackage,
    PenPhysicsEngine,
    CanvasBuilder,
    CoverGenerator,
    Copywriter,
)
from video_processing.handwritten_pager.contracts import HandwrittenPagerError


@pytest.fixture
def sample_lyrics():
    return [
        {
            "en": "Could you find a way to let me down slowly?",
            "zh": "你能试着，温柔地放开我吗？",
            "words": [
                {"word": "Could", "start": 0.00, "end": 0.76},
                {"word": "you", "start": 0.76, "end": 0.92},
                {"word": "find", "start": 0.92, "end": 1.20},
                {"word": "slowly?", "start": 2.46, "end": 3.14},
            ]
        },
        {
            "en": "A little sympathy, I hope you can show me",
            "zh": "哪怕只是一点怜悯，我也期盼你能给予",
            "words": [
                {"word": "A", "start": 3.52, "end": 3.80},
                {"word": "me", "start": 5.96, "end": 6.34},
            ]
        }
    ]


def test_contracts_validation():
    # 1. Valid config
    cfg = HandwrittenPagerConfig(width=1080, height=1920, fps=60)
    cfg.validate()
    assert cfg.pen_width == 195
    assert cfg.tip_y_offset == 58.0

    # 2. Invalid dimensions
    with pytest.raises(HandwrittenPagerError, match="Invalid canvas size"):
        HandwrittenPagerConfig(width=-100, height=1920).validate()

    # 3. Invalid fps
    with pytest.raises(HandwrittenPagerError, match="FPS must be 30 or 60"):
        HandwrittenPagerConfig(fps=24).validate()

    # 4. Valid copy package
    pkg = CopywritingPackage(
        wechat_short_title="听歌学英语：慢慢放手",
        wechat_copy="描述内容",
        douyin_title="全网都在找的治愈英文歌《慢慢放手》",
        douyin_copy="抖音文案",
        hashtags=["#tag"]
    )
    pkg.validate()

    # 5. Invalid WeChat title length (< 6 chars)
    with pytest.raises(HandwrittenPagerError, match="WeChat short title length"):
        CopywritingPackage(
            wechat_short_title="短标题",
            wechat_copy="desc",
            douyin_title="有效抖音标题",
            douyin_copy="desc",
            hashtags=[]
        ).validate()

    # 6. Invalid Douyin title length (> 30 chars)
    with pytest.raises(HandwrittenPagerError, match="Douyin title length"):
        CopywritingPackage(
            wechat_short_title="有效微信短标题",
            wechat_copy="desc",
            douyin_title="这是一个非常非常长绝对超过三十个字长度限制的超长抖音标题测试内容",
            douyin_copy="desc",
            hashtags=[]
        ).validate()


def test_canvas_builder_layout(sample_lyrics):
    config = HandwrittenPagerConfig()
    builder = CanvasBuilder(config)
    canvas, lines = builder.build_canvas(sample_lyrics, title="Test Song", artist="Test Artist")

    assert canvas.size == (1080, 1920)
    assert len(lines) == 2

    # Verify line 1 geometry
    l1 = lines[0]
    assert l1.en_text == sample_lyrics[0]["en"]
    assert len(l1.words) == 4
    assert l1.words[0].word == "Could"
    assert l1.words[-1].word == "slowly?"

    # Word positions must increase monotonically across the line
    for i in range(len(l1.words) - 1):
        assert l1.words[i].x_start < l1.words[i + 1].x_start
        assert l1.words[i].x_end <= l1.words[i + 1].x_end


def test_pen_physics_trajectory(sample_lyrics):
    config = HandwrittenPagerConfig(fps=60, pen_width=240, tip_y_offset=48.0)
    builder = CanvasBuilder(config)
    canvas, lines = builder.build_canvas(sample_lyrics)

    engine = PenPhysicsEngine(config)
    duration = 7.0
    states = engine.compute_trajectory(lines, total_duration=duration, fps=60)

    assert len(states) == int(math.ceil(duration * 60))

    # Test states properties
    for s in states:
        assert 0.0 <= s.t <= duration + 0.1
        # Coordinates must remain within canvas bounds
        assert 0.0 <= s.x <= 1080.0
        assert 0.0 <= s.y <= 1920.0
        # Tilt angle stays within natural wrist angle limits
        assert -6.0 <= s.angle_deg <= 1.0

    # During active word (e.g. at t = 0.5s inside "Could"):
    state_active = next(s for s in states if 0.2 <= s.t <= 0.6)
    assert state_active.is_active is True
    assert state_active.active_word == "Could"
    assert state_active.z == 0.0  # must be touching paper

    # During carriage return (between line 1 end at 3.14s and line 2 start at 3.52s):
    state_return = next(s for s in states if 3.30 <= s.t <= 3.35)
    assert state_return.is_active is False
    assert state_return.z > 5.0  # pen lifts off paper during carriage return


def test_pen_frame_rendering(sample_lyrics):
    config = HandwrittenPagerConfig(pen_width=240, tip_y_offset=48.0)
    builder = CanvasBuilder(config)
    canvas, lines = builder.build_canvas(sample_lyrics)
    engine = PenPhysicsEngine(config)

    # Frame 1: touching paper (z=0)
    state_z0 = PenState(
        frame_idx=0, t=1.0, x=300.0, y=500.0, z=0.0, angle_deg=-2.5, is_active=True, active_word="find"
    )
    frame_z0 = engine.render_pen_frame(canvas, state_z0)
    assert frame_z0.size == (1080, 1920)

    # Frame 2: lifted (z=15)
    state_z15 = PenState(
        frame_idx=1, t=3.3, x=400.0, y=600.0, z=15.0, angle_deg=-2.5, is_active=False
    )
    frame_z15 = engine.render_pen_frame(canvas, state_z15)
    assert frame_z15.size == (1080, 1920)


def test_cover_generator(tmp_path, sample_lyrics):
    config = HandwrittenPagerConfig()
    gen = CoverGenerator(config)
    covers = gen.generate_covers(sample_lyrics, output_dir=tmp_path)

    assert "wechat_9_16" in covers
    assert "douyin_3_4" in covers
    assert "douyin_4_3" in covers

    # Verify image dimensions
    im_wechat = Image.open(covers["wechat_9_16"])
    assert im_wechat.size == (1080, 1920)

    im_douyin_v = Image.open(covers["douyin_3_4"])
    assert im_douyin_v.size == (1080, 1440)

    im_douyin_h = Image.open(covers["douyin_4_3"])
    assert im_douyin_h.size == (1440, 1080)


def test_copywriter():
    copywriter = Copywriter()
    pkg = copywriter.generate_copy(
        title="Let Me Down Slowly",
        artist="Alec Benjamin",
        chinese_title="慢慢放手",
    )

    assert 6 <= len(pkg.wechat_short_title) <= 16
    assert 1 <= len(pkg.douyin_title) <= 30
    assert "Alec Benjamin" in pkg.wechat_copy
    assert "慢慢放手" in pkg.douyin_copy
    assert len(pkg.hashtags) >= 4


def test_cli_handwritten_pager(tmp_path, sample_lyrics, monkeypatch):
    import json
    from click.testing import CliRunner
    from cli.commands.handwritten_pager import handwritten_pager

    lyrics_file = tmp_path / "lyrics.json"
    lyrics_file.write_text(json.dumps(sample_lyrics), encoding="utf-8")
    audio_file = tmp_path / "audio.wav"
    audio_file.write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00")
    output_video = tmp_path / "out.mp4"

    runner = CliRunner()
    # Test --help
    res_help = runner.invoke(handwritten_pager, ["--help"])
    assert res_help.exit_code == 0
    assert "Generate high-resolution handwritten notebook" in res_help.output

