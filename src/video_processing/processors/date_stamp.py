# -*- coding: utf-8 -*-
"""源视频「发布日期」毛玻璃水印戳 — 几何计算 / 圆角资源生成 / FFmpeg 滤镜片段

在竖屏成片左上角叠加一枚圆角毛玻璃日期戳：对戳区做**局部**高斯模糊（仅一小块，
非整帧）+ 半透明深色着色 + 圆角 alpha 遮罩 + 白色文字。目的有二：
  1. 覆盖源视频左上角常见的频道水印（如 @handle），毛玻璃将其糊成不可辨认；
  2. 向观众标明「源视频的发布日期」，区别于视频号原生显示的「我们的发布时间(1小时前)」。

设计要点：
  - 烧录的是静态像素，故只用**绝对日期**（YYYY-MM-DD），绝不用「N天前」这种渲染即过期的相对时间。
  - 戳定位锚定**画面上沿**(frame_top_y)+偏移，适配不同黑边/横竖屏，不写死画布像素。
  - 圆角通过预生成的 alphamerge 遮罩 PNG 实现，每帧复用同一张遮罩 → 成本可忽略。

本模块是纯函数 + PIL 资源生成，不依赖 settings，便于单元测试；调用方（VerticalCaptionProcessor）
负责拼接到既有 filtergraph 并管理输入索引。

# Modification History
| Version | Date       | Author          | Description |
| ------- | ---------- | --------------- | ----------- |
| 1.0.0   | 2026-06-25 | Claude_Opus_4.8 | 初始创建：发布日期毛玻璃戳几何/圆角资源/滤镜片段；format_upload_date(YYYYMMDD→YYYY-MM-DD) |
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

# ── 样式常量（相对画布宽度缩放，1080 为基准）────────────────────────────────
_FONT_FACTOR = 0.032      # 字号 ≈ 画布宽 * 0.032 → 1080 ⇒ 35
_SIGMA_FACTOR = 0.0085    # 高斯模糊 sigma ≈ 画布宽 * 0.0085 → 1080 ⇒ 9
_PAD_X_FACTOR = 0.60      # 水平内边距 = 字号 * 0.60
_PAD_Y_FACTOR = 0.42      # 垂直内边距 = 字号 * 0.42
_RADIUS_FACTOR = 0.34     # 圆角半径 = 面板高 * 0.34
_MARGIN_X = 8             # 距画面左缘（画布像素），贴近左缘小边距；须为偶数(yuv420p 色度对齐)
_TOP_OFFSET = 24          # 距画面上沿（落到源水印所在高度）
_MIN_FONT_SIZE = 24

# 视觉参数
TINT_ALPHA = 0.42         # 深色着色不透明度（0~1）
_BORDER_ALPHA = 130       # 软白边框 alpha（0~255）
_BORDER_WIDTH = 2
_EQ = "eq=brightness=-0.06:saturation=0.62"  # 轻微压暗去饱和，强化「玻璃」观感

DEFAULT_LABEL = "发布日期："

MASK_FILENAME = "datestamp_mask.png"
BORDER_FILENAME = "datestamp_border.png"


def _even(n: int) -> int:
    """向上取偶（yuv420p 色度对齐要求 crop 区域宽高为偶数）。"""
    n = int(n)
    return n + (n & 1)


def format_upload_date(raw: Optional[str]) -> Optional[str]:
    """YouTube upload_date(YYYYMMDD) → YYYY-MM-DD；缺失/非法返回 None（调用方据此跳过渲染）。"""
    if raw is None:
        return None
    s = str(raw).strip()
    if not re.fullmatch(r"\d{8}", s):
        return None
    year, month, day = int(s[0:4]), int(s[4:6]), int(s[6:8])
    if year < 1900 or not (1 <= month <= 12) or not (1 <= day <= 31):
        return None
    return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"


@dataclass(frozen=True)
class DateStampGeometry:
    """日期戳的几何与文字参数（画布像素坐标）。"""
    text: str
    px: int          # 面板左上角 x
    py: int          # 面板左上角 y
    pw: int          # 面板宽
    ph: int          # 面板高
    radius: int      # 圆角半径
    font_size: int
    sigma: int       # 高斯模糊 sigma
    pad_x: int       # 文字左内边距
    font_path: str


def _measure_text_width(text: str, font_path: str, font_size: int) -> int:
    """用 PIL 精确量取文字像素宽度，决定胶囊宽度（避免文字顶边/留白过多）。"""
    from PIL import ImageFont
    try:
        font = ImageFont.truetype(font_path, font_size)
    except Exception:
        font = ImageFont.load_default()
    bbox = font.getbbox(text)
    return int(bbox[2] - bbox[0])


def compute_geometry(
    date_value: str,
    *,
    label: str = DEFAULT_LABEL,
    font_path: str = "/Library/Fonts/Arial Unicode.ttf",
    canvas_w: int = 1080,
    frame_top_y: int = 350,
) -> DateStampGeometry:
    """根据日期值与画布尺寸计算戳的几何参数。

    date_value: 已格式化的日期串（如 "2026-06-25"）。
    frame_top_y: 画面（被缩放后的源视频）在画布中的上沿 y（横屏=video_y=350，竖屏=居中偏移）。
    """
    text = f"{label}{date_value}"
    font_size = max(_MIN_FONT_SIZE, round(canvas_w * _FONT_FACTOR))
    sigma = max(4, round(canvas_w * _SIGMA_FACTOR))
    pad_x = round(font_size * _PAD_X_FACTOR)
    pad_y = round(font_size * _PAD_Y_FACTOR)
    text_w = _measure_text_width(text, font_path, font_size)
    # 关键：面板宽高与叠加 y 必须为偶数。烧录帧为 yuv420p（色度二次采样要求偶数尺寸），
    # 从奇数高度的区域 crop 会被 ffmpeg 向下取整(如 65→64)，导致与圆角遮罩 PNG 尺寸不符、
    # alphamerge 报 "Input frame sizes do not match" 而整条渲染失败。
    pw = _even(text_w + 2 * pad_x)
    ph = _even(font_size + 2 * pad_y)
    radius = round(ph * _RADIUS_FACTOR)
    px = _MARGIN_X
    py = _even(max(0, int(frame_top_y) + _TOP_OFFSET))
    return DateStampGeometry(
        text=text, px=px, py=py, pw=pw, ph=ph, radius=radius,
        font_size=font_size, sigma=sigma, pad_x=pad_x, font_path=font_path,
    )


def generate_assets(geom: DateStampGeometry, out_dir) -> Tuple[Path, Path]:
    """生成圆角 alpha 遮罩(L 模式)与软白边框(RGBA)两张 PNG，供 ffmpeg alphamerge/overlay 使用。

    返回 (mask_path, border_path)。两张图均为 geom.pw × geom.ph。
    """
    from PIL import Image, ImageDraw

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pw, ph, rad = geom.pw, geom.ph, geom.radius

    # 圆角遮罩：白(255)=不透明=保留，黑(0)=透明=切掉四角
    mask = Image.new("L", (pw, ph), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, pw - 1, ph - 1), radius=rad, fill=255)
    mask_path = out_dir / MASK_FILENAME
    mask.save(mask_path)

    # 软白圆角边框（透明底）
    border = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    ImageDraw.Draw(border).rounded_rectangle(
        (1, 1, pw - 2, ph - 2), radius=rad,
        outline=(255, 255, 255, _BORDER_ALPHA), width=_BORDER_WIDTH,
    )
    border_path = out_dir / BORDER_FILENAME
    border.save(border_path)

    return mask_path, border_path


def _escape_drawtext(text: str) -> str:
    """drawtext text= 值的 filtergraph 转义（与本仓库 vertical_processor 标题转义保持一致）。

    注意：默认文案使用全角冒号「：」(U+FF1A)，不会被半角 ':' 替换命中，故安全。
    """
    return text.replace("'", "'\\''").replace(":", "\\:")


def build_filter_chain(
    geom: DateStampGeometry,
    *,
    in_label: str,
    out_label: str,
    mask_idx: int,
    border_idx: int,
    tint_alpha: float = TINT_ALPHA,
) -> str:
    """构建毛玻璃日期戳的 filter_complex 片段（纯字符串，可单测）。

    消费 [in_label]（已烧字幕的整帧），产出 [out_label]。流程：
      split → 取戳区 → 局部高斯模糊 → 压暗去饱和 → 深色着色 → 圆角遮罩 → 叠回 → 边框 → 写字。
    mask_idx / border_idx 为遮罩与边框 PNG 在 ffmpeg 命令中的输入索引（由调用方按音轨情况算出）。
    所有内部标签以 ds_ 前缀，避免与既有 filtergraph 标签冲突。
    """
    px, py, pw, ph = geom.px, geom.py, geom.pw, geom.ph
    text = _escape_drawtext(geom.text)
    return (
        f"[{in_label}]split[ds_base][ds_src];"
        f"[ds_src]crop={pw}:{ph}:{px}:{py},gblur=sigma={geom.sigma},{_EQ},"
        f"drawbox=x=0:y=0:w={pw}:h={ph}:color=black@{tint_alpha}:t=fill[ds_pf];"
        f"[ds_pf][{mask_idx}:v]alphamerge[ds_rp];"
        f"[ds_base][ds_rp]overlay={px}:{py}[ds_p1];"
        f"[ds_p1][{border_idx}:v]overlay={px}:{py}[ds_p2];"
        f"[ds_p2]drawtext=fontfile='{geom.font_path}':text='{text}':"
        f"fontcolor=white:fontsize={geom.font_size}:"
        f"x={px}+{geom.pad_x}:y={py}+({ph}-text_h)/2:"
        f"shadowcolor=black@0.55:shadowx=1:shadowy=1[{out_label}]"
    )
