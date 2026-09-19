# -*- coding: utf-8 -*-
"""跑道级流光互动转化系统 (Project Runway-CTA) 视频图层处理器

为视频号竖屏全自动发布流水线开发广播级互动引导组件：
- 中央视平线三联微动胶囊 [ 👍 点赞 | 关注 | 💬 评论 ] (Y=820)
- 尾部转化钩子顶栏标语 [ • 觉得有收获？点赞关注防走丢 • ] (Y=760)
- 左下角黑曜石磨砂胶囊 [ + 关注创作者 ] (X=85, Y=1680)
- 三级 45° 跑道级流光航标（行波脉冲指向视频号原生左下角关注区域）
- 双频 Pop 交互音效（标准 wave 模块兜底合成，毫秒级音画同步）
- 100% 避让中英双语字幕区（Y=1040~1260）

# Modification History
| Version | Date       | Author      | Description |
| ------- | ---------- | ----------- | ----------- |
| 1.0.0   | 2026-09-19 | Antigravity | 初始创建：跑道级流光互动处理器 InteractionOverlayProcessor，支持 4x 超采样、跨平台字体回退、PTS 时延编排与双频 Pop 音效合成 |
"""
from __future__ import annotations

import logging
import math
import os
import shutil
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from config.settings import settings
from ..core.base import VideoProcessorBase, VideoProcessingError
from ..utils.video_metadata import get_video_duration_ffprobe

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ASSETS_SOUNDS = PROJECT_ROOT / "assets" / "sounds"


def resolve_render_font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """跨平台字体解析器：依次查找工程资源与多操作系统预装字体，失败则平滑降级。"""
    candidates = [
        # Settings 配置字体
        getattr(settings, "default_font_path", None),
        # macOS 常见字体
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        # 工程自带开源字体
        str(PROJECT_ROOT / "assets" / "fonts" / "SourceHanSerifCN-Medium.otf"),
        # Linux (Ubuntu / Debian / CentOS)
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        # Windows
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
    ]
    for c in candidates:
        if c and os.path.exists(c):
            try:
                index = 1 if (bold and str(c).endswith(".ttc")) else 0
                return ImageFont.truetype(str(c), size, index=index)
            except Exception:
                try:
                    return ImageFont.truetype(str(c), size)
                except Exception:
                    continue
    return ImageFont.load_default()


def synthesize_pop_audio(output_wav: Path) -> Path:
    """使用标准 wave 模块合成双频清脆 Pop 气泡提示音，零外部音频库依赖。"""
    sample_rate = 44100
    duration = 0.22
    num_samples = int(sample_rate * duration)
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_wav), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        for i in range(num_samples):
            t = i / sample_rate
            freq = 380 + 340 * (1.0 - math.exp(-18 * t))
            envelope = math.exp(-22 * t)
            val = math.sin(2 * math.pi * freq * t) * envelope
            sample = int(val * 12000)
            wf.writeframes(sample.to_bytes(2, byteorder="little", signed=True))
    return output_wav


def draw_rounded_rect(draw: ImageDraw.ImageDraw, box, radius: int, fill=None, outline=None, width: int = 1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def draw_plus_icon(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int, color, stroke: int = 3):
    hs = size // 2
    draw.line([cx - hs, cy, cx + hs, cy], fill=color, width=stroke)
    draw.line([cx, cy - hs, cx, cy + hs], fill=color, width=stroke)


def draw_check_icon(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int, color, stroke: int = 3):
    hs = size // 2
    p1 = (cx - hs, cy)
    p2 = (cx - hs // 3, cy + hs // 2)
    p3 = (cx + hs, cy - hs // 2)
    draw.line([p1, p2], fill=color, width=stroke)
    draw.line([p2, p3], fill=color, width=stroke)


def draw_thumb_up(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int, color):
    hs = size // 2
    draw.rectangle([cx - hs, cy - hs // 3, cx - hs // 3, cy + hs], fill=color)
    draw.polygon([
        (cx - hs // 3, cy - hs // 3),
        (cx - hs // 6, cy - hs),
        (cx + hs // 4, cy - hs),
        (cx + hs // 6, cy - hs // 3),
        (cx + hs, cy - hs // 3),
        (cx + hs * 0.8, cy + hs),
        (cx - hs // 3, cy + hs),
    ], fill=color)


def draw_speech_bubble(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int, color):
    hs = size // 2
    draw.rounded_rectangle([cx - hs, cy - hs * 0.7, cx + hs, cy + hs * 0.5], radius=hs * 0.4, fill=color)
    draw.polygon([
        (cx - hs * 0.4, cy + hs * 0.4),
        (cx - hs * 0.7, cy + hs * 0.9),
        (cx, cy + hs * 0.4),
    ], fill=color)
    dot_r = max(1, int(size * 0.08))
    for dx in [-hs * 0.4, 0, hs * 0.4]:
        draw.ellipse([cx + dx - dot_r, cy - hs * 0.1 - dot_r, cx + dx + dot_r, cy - hs * 0.1 + dot_r], fill=(255, 255, 255, 255))


def draw_cursor(draw: ImageDraw.ImageDraw, x: int, y: int, scale: float = 1.0):
    pts = [
        (x, y),
        (x, y + int(24 * scale)),
        (x + int(6 * scale), y + int(19 * scale)),
        (x + int(11 * scale), y + int(29 * scale)),
        (x + int(15 * scale), y + int(27 * scale)),
        (x + int(10 * scale), y + int(17 * scale)),
        (x + int(17 * scale), y + int(17 * scale)),
    ]
    draw.polygon(pts, fill=(255, 255, 255, 255))
    draw.line(pts + [(x, y)], fill=(20, 20, 25, 255), width=int(2 * scale))


def create_badge_a(scale: float = 1.0, liked: bool = False, followed: bool = False, like_pop: float = 1.0) -> Image.Image:
    """中央白瓷三联微动胶囊 [ 点赞 | 关注 | 评论 ]。"""
    w = int(640 * scale)
    h = int(104 * scale)
    padding = int(24 * scale)

    img = Image.new("RGBA", (w + padding * 2, h + padding * 2), (0, 0, 0, 0))
    s = Image.new("RGBA", (w + padding * 2, h + padding * 2), (0, 0, 0, 0))
    s_draw = ImageDraw.Draw(s)
    draw_rounded_rect(
        s_draw,
        (padding, padding + int(8 * scale), padding + w, padding + h + int(8 * scale)),
        radius=int(52 * scale),
        fill=(0, 0, 0, 110),
    )
    s = s.filter(ImageFilter.GaussianBlur(radius=int(10 * scale)))
    img.paste(s, (0, 0), s)

    draw = ImageDraw.Draw(img)
    draw_rounded_rect(
        draw,
        (padding, padding, padding + w, padding + h),
        radius=int(52 * scale),
        fill=(255, 255, 255, 250),
        outline=(240, 242, 246, 255),
        width=int(2 * scale),
    )

    c_red = (235, 45, 45, 255)
    font_btn = resolve_render_font(int(30 * scale), bold=True)
    font_follow = resolve_render_font(int(26 * scale), bold=True)

    # 1. Like
    like_cx = padding + int(w * 0.17)
    like_cy = padding + int(h * 0.5)
    draw_thumb_up(draw, like_cx - int(45 * scale), like_cy, size=int(34 * scale * like_pop), color=c_red)
    draw.text((like_cx - int(10 * scale), like_cy), "点赞", font=font_btn, fill=c_red, anchor="lm")

    div1_x = padding + int(w * 0.35)
    draw.line([div1_x, padding + int(h * 0.28), div1_x, padding + int(h * 0.72)], fill=(225, 227, 232, 255), width=2)

    # 2. Follow
    fol_cx = padding + int(w * 0.51)
    fol_cy = padding + int(h * 0.5)
    bw = int(176 * scale)
    bh = int(74 * scale)
    badge_box = (fol_cx - bw // 2, fol_cy - bh // 2, fol_cx + bw // 2, fol_cy + bh // 2)

    if followed:
        draw_rounded_rect(draw, badge_box, radius=int(37 * scale), fill=(240, 242, 245, 255))
        draw_check_icon(draw, fol_cx - int(45 * scale), fol_cy, size=int(20 * scale), color=(100, 110, 120, 255), stroke=int(3 * scale))
        draw.text((fol_cx + int(10 * scale), fol_cy), "已关注", font=font_follow, fill=(100, 110, 120, 255), anchor="mm")
    else:
        draw_rounded_rect(draw, badge_box, radius=int(37 * scale), fill=c_red)
        draw_plus_icon(draw, fol_cx - int(42 * scale), fol_cy, size=int(20 * scale), color=(255, 255, 255, 255), stroke=int(3 * scale))
        draw.text((fol_cx + int(12 * scale), fol_cy), "关注", font=font_follow, fill=(255, 255, 255, 255), anchor="mm")

    div2_x = padding + int(w * 0.67)
    draw.line([div2_x, padding + int(h * 0.28), div2_x, padding + int(h * 0.72)], fill=(225, 227, 232, 255), width=2)

    # 3. Comment
    com_cx = padding + int(w * 0.83)
    com_cy = padding + int(h * 0.5)
    draw_speech_bubble(draw, com_cx - int(45 * scale), com_cy, size=int(34 * scale), color=c_red)
    draw.text((com_cx - int(10 * scale), com_cy), "评论", font=font_btn, fill=c_red, anchor="lm")
    return img


def create_hook_banner(scale: float = 1.0, text: str = "觉得有收获？点赞关注防走丢") -> Image.Image:
    """尾部转化钩子顶栏横幅。"""
    hw = int(540 * scale)
    hh = int(48 * scale)
    img = Image.new("RGBA", (hw + 20, hh + 20), (0, 0, 0, 0))
    s = Image.new("RGBA", (hw + 20, hh + 20), (0, 0, 0, 0))
    s_draw = ImageDraw.Draw(s)
    draw_rounded_rect(s_draw, (10, 12, 10 + hw, 12 + hh), radius=int(24 * scale), fill=(0, 0, 0, 70))
    s = s.filter(ImageFilter.GaussianBlur(radius=int(6 * scale)))
    img.paste(s, (0, 0), s)

    draw = ImageDraw.Draw(img)
    draw_rounded_rect(
        draw,
        (10, 10, 10 + hw, 10 + hh),
        radius=int(24 * scale),
        fill=(22, 26, 35, 235),
        outline=(245, 60, 60, 140),
        width=1,
    )

    font_h = resolve_render_font(int(24 * scale), bold=True)
    draw.text((10 + hw // 2, 10 + hh // 2), f"• {text} •", font=font_h, fill=(245, 248, 255, 245), anchor="mm")
    return img


def render_option_c_pointer(scale: int = 4, phase: float = 0.0, alpha: float = 1.0) -> Image.Image:
    """渲染 Option C Refined 左下角黑曜石磨砂胶囊与三级 45° 跑道微标（无内置文本箭头）。"""
    w, h = 360 * scale, 180 * scale
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))

    if alpha <= 0.01:
        return canvas.resize((w // scale, h // scale), Image.Resampling.LANCZOS)

    bx, by = 48 * scale, 16 * scale
    bw, bh = 196 * scale, 54 * scale
    r = 27 * scale

    # 1. 投影
    shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    s_draw = ImageDraw.Draw(shadow)
    s_draw.rounded_rectangle((bx, by + 8 * scale, bx + bw, by + bh + 8 * scale), radius=r, fill=(0, 0, 0, int(160 * alpha)))
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=8 * scale))
    canvas.paste(shadow, (0, 0), shadow)

    draw = ImageDraw.Draw(canvas)

    # 2. 黑曜石磨砂胶囊
    draw.rounded_rectangle(
        (bx, by, bx + bw, by + bh),
        radius=r,
        fill=(18, 22, 30, int(242 * alpha)),
        outline=(255, 255, 255, int(45 * alpha)),
        width=int(1.8 * scale),
    )

    # 顶缘弧线高光
    rim_col = (255, 255, 255, int(75 * alpha))
    rw = int(1.5 * scale)
    draw.arc((bx, by, bx + 2 * r, by + 2 * r), start=205, end=270, fill=rim_col, width=rw)
    draw.line([(bx + r, by), (bx + bw - r, by)], fill=rim_col, width=rw)
    draw.arc((bx + bw - 2 * r, by, bx + bw, by + 2 * r), start=270, end=335, fill=rim_col, width=rw)

    # 红色加号微标
    p_cx = bx + 32 * scale
    p_cy = by + bh // 2
    draw.ellipse((p_cx - 15 * scale, p_cy - 15 * scale, p_cx + 15 * scale, p_cy + 15 * scale), fill=(255, 48, 64, int(255 * alpha)))
    draw_plus_icon(draw, p_cx, p_cy, size=13 * scale, color=(255, 255, 255, int(255 * alpha)), stroke=int(3 * scale))

    # 居中文案：关注创作者
    font_main = resolve_render_font(21 * scale, bold=True)
    draw.text((bx + 60 * scale, p_cy), "关注创作者", font=font_main, fill=(255, 255, 255, int(255 * alpha)), anchor="lm")

    # 3. 三级 45° 跑道微标
    start_x = bx + 36 * scale
    start_y = by + bh + 18 * scale
    step_d = 20 * scale
    dir_x = -math.sqrt(2) / 2
    dir_y = math.sqrt(2) / 2

    arm_len = 16 * scale
    ang_center = 45 * (math.pi / 180)
    spread = 34 * (math.pi / 180)
    ang1 = ang_center + spread
    ang2 = ang_center - spread

    for i in range(3):
        cur_phase = (phase - i * 0.3) % 1.0
        pulse = 0.30 + 0.70 * math.sin(cur_phase * math.pi)
        dist = i * step_d + int(cur_phase * 4 * scale)
        apex = (start_x + dir_x * dist, start_y + dir_y * dist)

        s_factor = 1.0 - i * 0.12
        cur_arm = arm_len * s_factor
        w1 = (apex[0] + cur_arm * math.cos(ang1), apex[1] - cur_arm * math.sin(ang1))
        w2 = (apex[0] + cur_arm * math.cos(ang2), apex[1] - cur_arm * math.sin(ang2))

        col = (255, 55, 75, int(255 * pulse * alpha))
        sw = int(3.5 * scale * s_factor)
        draw.line([w1, apex], fill=col, width=sw)
        draw.line([apex, w2], fill=col, width=sw)

    return canvas.resize((w // scale, h // scale), Image.Resampling.LANCZOS)


def build_overlay_frame(
    t: float,
    duration: float = 5.5,
    with_hook: bool = False,
    hook_text: str = "觉得有收获？点赞关注防走丢",
) -> Image.Image:
    """
    单帧渲染工厂函数：
    - 0.0s~0.4s: 中央胶囊弹出 (scale 0.7 -> 1.06 -> 1.0)
    - 0.4s~1.0s: 光标移向点赞并在 t=0.8s 点击 (+1 粒子浮空消散)
    - 1.0s~1.6s: 光标移向关注并在 t=1.4s 点击 (状态切换为 ✓已关注)
    - 1.6s~2.0s: 光标淡出
    - 2.0s (错峰延时 2.0s): 左下角角标淡入 (alpha 0.0 -> 1.0)
    - 2.0s~5.2s: 三级 45° 跑道微标持续执行 2 个波纹周期 (单周期 1.6s)
    - 5.0s~5.5s: 全局淡出
    """
    overlay = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))

    scale = 1.0
    alpha = 1.0
    dy = 0
    liked = False
    followed = False
    like_pop = 1.0
    cursor_pos = None
    plus_one_pos = None
    corner_alpha = 0.0
    corner_phase = 0.0

    if t < 0.4:
        prog = t / 0.4
        alpha = min(1.0, prog * 1.5)
        scale = 0.7 + 0.36 * math.sin(prog * math.pi * 0.7)
        dy = int(12 * (1.0 - prog))
    elif t < 1.0:
        c_prog = (t - 0.4) / 0.6
        start_cx, start_cy = 700, 1000
        target_cx, target_cy = 320, 875
        cur_x = int(start_cx + (target_cx - start_cx) * c_prog)
        cur_y = int(start_cy + (target_cy - start_cy) * c_prog)
        cursor_pos = (cur_x, cur_y)
        if t >= 0.8:
            liked = True
            like_pop = 1.18
    elif t < 1.6:
        liked = True
        c_prog = (t - 1.0) / 0.6
        start_cx, start_cy = 320, 875
        target_cx, target_cy = 540, 875
        cur_x = int(start_cx + (target_cx - start_cx) * c_prog)
        cur_y = int(start_cy + (target_cy - start_cy) * c_prog)
        cursor_pos = (cur_x, cur_y)
        if t >= 1.4:
            followed = True
        p_prog = (t - 0.8) / 0.8
        if p_prog < 1.0:
            plus_one_pos = (310, int(840 - 35 * p_prog), max(0.0, 1.0 - p_prog))
    elif t < 2.0:
        liked = True
        followed = True
        c_alpha = max(0.0, 1.0 - (t - 1.6) / 0.3)
        if c_alpha > 0.05:
            cursor_pos = (540, 875)
    elif t < 5.0:
        liked = True
        followed = True
        corner_alpha = min(1.0, (t - 2.0) / 0.3)
        corner_phase = (t - 2.0) / 1.6
    else:
        liked = True
        followed = True
        out_prog = (t - 5.0) / 0.5
        alpha = max(0.0, 1.0 - out_prog)
        corner_alpha = alpha
        corner_phase = (t - 2.0) / 1.6
        dy = int(20 * out_prog)

    # 1. 中央三联胶囊 (Y=820)
    badge = create_badge_a(scale=scale, liked=liked, followed=followed, like_pop=like_pop)
    if alpha < 1.0:
        r_ch, g_ch, b_ch, a_ch = badge.split()
        a_ch = a_ch.point(lambda p: int(p * alpha))
        badge.putalpha(a_ch)

    pos_x = (1080 - badge.width) // 2
    pos_y = 820 + dy
    overlay.paste(badge, (pos_x, pos_y), badge)

    # 2. 尾部转化横幅 (Y=760)
    if with_hook:
        hb = create_hook_banner(scale=0.95, text=hook_text)
        if alpha < 1.0:
            r_ch, g_ch, b_ch, a_ch = hb.split()
            a_ch = a_ch.point(lambda p: int(p * alpha))
            hb.putalpha(a_ch)
        hx = (1080 - hb.width) // 2
        hy = 760 + dy
        overlay.paste(hb, (hx, hy), hb)

    # 3. 浮空 +1 粒子
    o_draw = ImageDraw.Draw(overlay)
    if plus_one_pos:
        px, py, pa = plus_one_pos
        font_p = resolve_render_font(26, bold=True)
        o_draw.text((px, py), "+1", font=font_p, fill=(245, 50, 65, int(255 * pa)), anchor="mm")

    # 4. 手势光标
    if cursor_pos and alpha > 0.3 and t < 1.9:
        draw_cursor(o_draw, cursor_pos[0], cursor_pos[1], scale=1.0)

    # 5. 左下角角标 (X=85, Y=1680)
    if corner_alpha > 0.01:
        c_guide = render_option_c_pointer(scale=4, phase=corner_phase, alpha=corner_alpha)
        overlay.paste(c_guide, (85, 1680), c_guide)

    return overlay


@dataclass(frozen=True)
class InteractionTrigger:
    """互动引导触发点定义"""
    start_sec: float
    duration_sec: float = 5.5
    with_hook: bool = False
    hook_text: str = "觉得有收获？点赞关注防走丢"


def compute_triggers(
    video_duration: float,
    early_ratio: float = 0.18,
    end_offset: float = 14.0,
    min_video_duration: float = 22.0,
) -> List[InteractionTrigger]:
    """
    计算视频触发时机：
    - 短于 min_video_duration (22s) 则降级为 0 或 1 处触发，杜绝覆盖与密集干扰；
    - 常规视频返回 [Trigger 1 (黄金认知点), Trigger 2 (尾部转化点)]。
    """
    if video_duration < 12.0:
        return []

    if video_duration < min_video_duration:
        # 短视频仅在中间触发一次单组件
        mid_time = max(2.0, video_duration * 0.5 - 2.75)
        return [InteractionTrigger(start_sec=mid_time, duration_sec=min(5.5, video_duration - mid_time))]

    t1_start = max(6.0, video_duration * early_ratio)
    t2_start = max(t1_start + 8.0, video_duration - end_offset)

    # 保证 t2 不溢出视频长度
    if t2_start + 5.5 > video_duration:
        t2_start = max(t1_start + 6.0, video_duration - 5.8)

    return [
        InteractionTrigger(start_sec=round(t1_start, 2), duration_sec=5.5, with_hook=False),
        InteractionTrigger(start_sec=round(t2_start, 2), duration_sec=5.5, with_hook=True),
    ]


class InteractionOverlayProcessor(VideoProcessorBase):
    """跑道级流光互动转化系统处理器 (Project Runway-CTA)"""

    def __init__(
        self,
        input_path: Path,
        output_path: Optional[Path] = None,
        sound_enabled: Optional[bool] = None,
        sound_volume: Optional[float] = None,
        hook_text: str = "觉得有收获？点赞关注防走丢",
    ):
        super().__init__(input_path, output_path)
        self.sound_enabled = sound_enabled if sound_enabled is not None else getattr(settings, "interaction_sound_enabled", True)
        self.sound_volume = sound_volume if sound_volume is not None else getattr(settings, "interaction_sound_volume", 0.40)
        self.hook_text = hook_text

        if self.output_path is None:
            # 默认命名: {stem}_interactive.mp4
            self.output_path = self.input_path.with_name(f"{self.input_path.stem}_interactive.mp4")

    def _render_frames(self, output_dir: Path, trigger: InteractionTrigger, fps: int = 30) -> None:
        """渲染单次触发的透明 PNG 序列帧"""
        output_dir.mkdir(parents=True, exist_ok=True)
        total_frames = int(trigger.duration_sec * fps)
        for i in range(total_frames):
            t = i / float(fps)
            frame = build_overlay_frame(
                t,
                duration=trigger.duration_sec,
                with_hook=trigger.with_hook,
                hook_text=self.hook_text,
            )
            frame.save(output_dir / f"frame_{i:04d}.png")

    def process(self, **kwargs) -> Path:
        """
        合成互动组件图层至目标成片
        """
        self._ensure_output_dir()
        work_dir = kwargs.get("work_dir")
        cleanup_temp = False

        if work_dir is None:
            work_dir = Path(tempfile.mkdtemp(prefix="runway_cta_proc_"))
            cleanup_temp = True
        else:
            work_dir = Path(work_dir)
            work_dir.mkdir(parents=True, exist_ok=True)

        try:
            duration = get_video_duration_ffprobe(self.input_path)
            early_ratio = kwargs.get("early_ratio", getattr(settings, "interaction_trigger_early_ratio", 0.18))
            end_seconds = kwargs.get("end_seconds", getattr(settings, "interaction_trigger_end_seconds", 14.0))

            triggers = compute_triggers(duration, early_ratio=early_ratio, end_offset=end_seconds)
            if not triggers:
                logger.warning("[RunwayCTA] 视频时长过短 (%.1fs)，跳过互动图层合成，拷贝原片。", duration)
                shutil.copy2(self.input_path, self.output_path)
                return self.output_path

            fps = 30
            mov_files: List[Path] = []
            filter_chunks: List[str] = []
            input_args: List[str] = ["-i", str(self.input_path)]

            # 1. 渲染各触发点透明 mov 视频流
            for idx, trigger in enumerate(triggers):
                seq_dir = work_dir / f"trigger_{idx}_frames"
                self._render_frames(seq_dir, trigger, fps=fps)
                mov_path = work_dir / f"trigger_{idx}.mov"

                cmd_enc = [
                    "ffmpeg", "-y", "-framerate", str(fps),
                    "-i", str(seq_dir / "frame_%04d.png"),
                    "-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le",
                    str(mov_path),
                ]
                subprocess.run(cmd_enc, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                mov_files.append(mov_path)
                input_args.extend(["-i", str(mov_path)])

            # 2. 准备音效
            pop_wav = ASSETS_SOUNDS / "pop.wav"
            if self.sound_enabled and not pop_wav.is_file():
                synthesize_pop_audio(pop_wav)

            audio_stream_idx = None
            if self.sound_enabled and pop_wav.is_file():
                audio_stream_idx = len(input_args) // 2
                input_args.extend(["-i", str(pop_wav)])

            # 3. 构建视频 overlay 滤镜网络
            current_v = "0:v"
            for idx, trigger in enumerate(triggers):
                t_in = trigger.start_sec
                t_out = trigger.start_sec + trigger.duration_sec
                stream_idx = idx + 1
                ov_pts_label = f"v_ov{idx}"
                next_v = f"v_step{idx}" if idx < len(triggers) - 1 else "vout"

                filter_chunks.append(f"[{stream_idx}:v]setpts=PTS-STARTPTS+{t_in}/TB[{ov_pts_label}]")
                filter_chunks.append(
                    f"[{current_v}][{ov_pts_label}]overlay=0:0:enable='between(t,{t_in},{t_out})'[{next_v}]"
                )
                current_v = next_v

            # 4. 构建音频 adelay & amix 滤镜网络
            if audio_stream_idx is not None:
                audio_cues: List[str] = []
                p_idx = 0
                for trigger in triggers:
                    # 点赞 click @ +0.8s, 关注 click @ +1.4s
                    t_like_ms = int((trigger.start_sec + 0.8) * 1000)
                    t_follow_ms = int((trigger.start_sec + 1.4) * 1000)

                    p1_label = f"p_{p_idx}"
                    filter_chunks.append(
                        f"[{audio_stream_idx}:a]adelay={t_like_ms}|{t_like_ms},volume={self.sound_volume * 1.1:.2f}[{p1_label}]"
                    )
                    audio_cues.append(f"[{p1_label}]")
                    p_idx += 1

                    p2_label = f"p_{p_idx}"
                    filter_chunks.append(
                        f"[{audio_stream_idx}:a]adelay={t_follow_ms}|{t_follow_ms},volume={self.sound_volume:.2f}[{p2_label}]"
                    )
                    audio_cues.append(f"[{p2_label}]")
                    p_idx += 1

                total_inputs = 1 + len(audio_cues)
                cues_concat = "".join(audio_cues)
                filter_chunks.append(f"[0:a]{cues_concat}amix=inputs={total_inputs}:dropout_transition=0:normalize=0[aout]")
                map_args = ["-map", "[vout]", "-map", "[aout]"]
            else:
                map_args = ["-map", "[vout]", "-map", "0:a?"]

            filter_complex = ";".join(filter_chunks)
            ffmpeg_cmd = [
                "ffmpeg", "-y",
                *input_args,
                "-filter_complex", filter_complex,
                *map_args,
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "20",
                "-c:a", "aac",
                "-b:a", "192k",
                str(self.output_path),
            ]

            logger.info("[RunwayCTA] 开始合成互动视频: %s -> %s", self.input_path.name, self.output_path.name)
            subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            # 5. 校验成片完整性
            if not self.output_path.is_file() or self.output_path.stat().st_size <= 1_000_000:
                raise VideoProcessingError(f"成片文件无效或体积异常: {self.output_path}")

            out_duration = get_video_duration_ffprobe(self.output_path)
            if abs(out_duration - duration) > 0.8:
                raise VideoProcessingError(
                    f"合成后时长偏差异常: 源片 {duration:.2f}s, 成片 {out_duration:.2f}s"
                )

            logger.info("[RunwayCTA] 成功生成跑道互动成片: %s (时长 %.2fs)", self.output_path.name, out_duration)
            return self.output_path

        except Exception as exc:
            logger.error("[RunwayCTA] 互动图层处理失败: %s", exc, exc_info=True)
            raise VideoProcessingError(f"互动图层处理失败: {exc}") from exc
        finally:
            if cleanup_temp and work_dir and work_dir.exists():
                shutil.rmtree(work_dir, ignore_errors=True)
