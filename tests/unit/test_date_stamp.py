# -*- coding: utf-8 -*-
"""源视频发布日期毛玻璃戳 — 单元测试

覆盖：
  - format_upload_date：YYYYMMDD→YYYY-MM-DD 与各类非法输入的安全回退
  - compute_geometry：几何/缩放/定位（锚定画面上沿）
  - generate_assets：圆角遮罩(L) + 软白边框(RGBA) 两张 PNG 的尺寸/模式/像素
  - build_filter_chain：纯字符串拼接的标签/输入索引/关键滤镜/转义
  - CLI --source-date 透传至 VerticalCaptionProcessor（1 个 mock，符合 mock 闸门）

# Modification History
| Version | Date       | Author          | Description |
| ------- | ---------- | --------------- | ----------- |
| 1.0.0   | 2026-06-25 | Claude_Opus_4.8 | 初始创建：date_stamp 全函数覆盖 + CLI 透传 wiring 测试 |
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from video_processing.processors import date_stamp as ds


# ───────────────────────── format_upload_date ─────────────────────────
class TestFormatUploadDate:
    @pytest.mark.parametrize("raw,expected", [
        ("20260625", "2026-06-25"),
        ("19991231", "1999-12-31"),
        ("20000101", "2000-01-01"),
        (20260625, "2026-06-25"),          # 数字也可
        (" 20260625 ", "2026-06-25"),      # 前后空白
    ])
    def test_valid(self, raw, expected):
        assert ds.format_upload_date(raw) == expected

    @pytest.mark.parametrize("raw", [
        None, "", "  ", "2026-06-25",       # 已带连字符 → 非 8 位数字
        "2026062", "202606250",             # 长度不符
        "abcdefgh", "2026XX25",
        "20261301",                         # 月=13 非法
        "20260632",                         # 日=32 非法
        "20260600",                         # 日=00 非法
        "18991231",                         # 年<1900
    ])
    def test_invalid_returns_none(self, raw):
        assert ds.format_upload_date(raw) is None


# ───────────────────────── compute_geometry ─────────────────────────
class TestComputeGeometry:
    def test_text_is_label_plus_date(self):
        g = ds.compute_geometry("2026-06-25")
        assert g.text == "发布日期：2026-06-25"

    def test_custom_label(self):
        g = ds.compute_geometry("2026-06-25", label="原视频 ")
        assert g.text == "原视频 2026-06-25"

    def test_anchored_to_frame_top(self):
        # 横屏 frame_top_y=350 → py = 350 + _TOP_OFFSET(24)
        g = ds.compute_geometry("2026-06-25", frame_top_y=350)
        assert g.px == ds._MARGIN_X       # 引用常量而非硬编码，左边距调整时不脆裂
        assert g.px % 2 == 0              # 偶数(yuv420p crop 对齐)
        assert g.px <= 12                 # 贴近左缘的小边距
        assert g.py == 350 + ds._TOP_OFFSET
        # 竖屏居中 frame_top_y=0 → py = 24
        g0 = ds.compute_geometry("2026-06-25", frame_top_y=0)
        assert g0.py == ds._TOP_OFFSET

    def test_panel_wider_than_text(self):
        g = ds.compute_geometry("2026-06-25")
        text_w = ds._measure_text_width(g.text, g.font_path, g.font_size)
        assert g.pw >= text_w + 2 * g.pad_x      # ≥ 因偶数向上取整
        assert g.pw > text_w
        assert g.ph >= g.font_size + 2 * round(g.font_size * ds._PAD_Y_FACTOR)

    def test_dimensions_and_offset_are_even(self):
        # 回归护栏：yuv420p 下 crop 奇数尺寸会被取整 → alphamerge 尺寸不匹配渲染崩溃。
        for ftop in (0, 350, 351, 437):
            g = ds.compute_geometry("2026-06-25", frame_top_y=ftop)
            assert g.pw % 2 == 0, g.pw
            assert g.ph % 2 == 0, g.ph
            assert g.py % 2 == 0, g.py

    def test_scales_with_canvas_width(self):
        small = ds.compute_geometry("2026-06-25", canvas_w=1080)
        big = ds.compute_geometry("2026-06-25", canvas_w=2160)
        assert big.font_size > small.font_size
        assert big.sigma >= small.sigma

    def test_radius_positive(self):
        g = ds.compute_geometry("2026-06-25")
        assert 0 < g.radius <= g.ph // 2 + 1


# ───────────────────────── generate_assets ─────────────────────────
class TestGenerateAssets:
    def test_creates_two_pngs_correct_size_mode(self, tmp_path):
        g = ds.compute_geometry("2026-06-25")
        mask_path, border_path = ds.generate_assets(g, tmp_path)
        assert mask_path.exists() and border_path.exists()
        assert mask_path.name == ds.MASK_FILENAME
        assert border_path.name == ds.BORDER_FILENAME

        from PIL import Image
        mask = Image.open(mask_path)
        border = Image.open(border_path)
        assert mask.size == (g.pw, g.ph)
        assert border.size == (g.pw, g.ph)
        assert mask.mode == "L"
        assert border.mode == "RGBA"

    def test_mask_corner_transparent_center_opaque(self, tmp_path):
        g = ds.compute_geometry("2026-06-25")
        mask_path, _ = ds.generate_assets(g, tmp_path)
        from PIL import Image
        mask = Image.open(mask_path).convert("L")
        # 角(0,0)应被圆角切掉=透明(0)，中心应保留=不透明(255)
        assert mask.getpixel((0, 0)) == 0
        assert mask.getpixel((g.pw // 2, g.ph // 2)) == 255

    def test_creates_missing_dir(self, tmp_path):
        sub = tmp_path / "nested" / "dir"
        g = ds.compute_geometry("2026-06-25")
        mask_path, _ = ds.generate_assets(g, sub)
        assert mask_path.exists()


# ───────────────────────── build_filter_chain ─────────────────────────
class TestBuildFilterChain:
    def _chain(self, mask_idx=2, border_idx=3):
        g = ds.compute_geometry("2026-06-25", frame_top_y=350)
        return g, ds.build_filter_chain(
            g, in_label="ds_subbed", out_label="out",
            mask_idx=mask_idx, border_idx=border_idx,
        )

    def test_consumes_in_produces_out(self):
        _, chain = self._chain()
        assert chain.startswith("[ds_subbed]split")
        assert chain.endswith("[out]")

    def test_references_input_indices(self):
        _, chain = self._chain(mask_idx=2, border_idx=3)
        assert "[2:v]alphamerge" in chain
        assert "[3:v]overlay" in chain

    def test_input_indices_shift_without_audio(self):
        _, chain = self._chain(mask_idx=1, border_idx=2)
        assert "[1:v]alphamerge" in chain
        assert "[2:v]overlay" in chain

    def test_contains_core_filters(self):
        g, chain = self._chain()
        assert f"gblur=sigma={g.sigma}" in chain
        assert "alphamerge" in chain
        assert f"crop={g.pw}:{g.ph}:{g.px}:{g.py}" in chain
        assert "drawtext=" in chain
        assert f"color=black@{ds.TINT_ALPHA}" in chain

    def test_fullwidth_colon_not_escaped(self):
        # 默认文案用全角冒号「：」，不应被半角 ':' 转义命中
        _, chain = self._chain()
        assert "发布日期：2026-06-25" in chain

    def test_ascii_colon_in_label_is_escaped(self):
        g = ds.compute_geometry("2026-06-25", label="date: ")
        chain = ds.build_filter_chain(
            g, in_label="ds_subbed", out_label="out", mask_idx=1, border_idx=2,
        )
        # 半角冒号必须转义成 \: 以免被 filtergraph 当作选项分隔符
        assert "date\\: " in chain

    def test_uses_prefixed_labels_no_collision(self):
        _, chain = self._chain()
        for lbl in ("ds_base", "ds_src", "ds_pf", "ds_rp", "ds_p1", "ds_p2"):
            assert f"[{lbl}]" in chain


# ───────────────────────── CLI 透传 ─────────────────────────
class TestCliSourceDateWiring:
    def test_source_date_forwarded_to_processor(self, tmp_path, monkeypatch):
        """--source-date 应原样透传到 VerticalCaptionProcessor(source_date=...)。"""
        from click.testing import CliRunner
        import cli.commands.auto_caption as ac

        captured = {}

        class _StubProc:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            def process(self):
                return Path("out.mp4")

        monkeypatch.setattr(ac, "VerticalCaptionProcessor", _StubProc)

        fake_input = tmp_path / "clip.mp4"
        fake_input.write_bytes(b"\x00")

        runner = CliRunner()
        result = runner.invoke(ac.auto_caption, [
            str(fake_input), "--vertical", "--bilingual",
            "--source-date", "2026-06-25",
        ])
        assert result.exit_code == 0, result.output
        assert captured.get("source_date") == "2026-06-25"
