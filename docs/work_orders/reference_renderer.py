#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Project Runway-CTA: Reference Renderer & Demo Generator
Self-contained, cross-platform reference implementation for the interactive overlay.

Features:
- Option C Refined: Frosted obsidian glass capsule (no internal arrow) + 45° cascading runway chevrons
- Strict timing alignment (5.5s duration):
  * 0.0s~0.4s: Pop-in
  * 0.4s~1.0s: Cursor clicks Like (+1 particle, pop audio @ t=0.8s)
  * 1.0s~1.6s: Cursor clicks Follow (status -> ✓已关注, pop audio @ t=1.4s)
  * 1.6s~2.0s: Cursor fades out
  * 2.0s: Staggered delay (2.0s) -> Left-bottom obsidian capsule emerges (alpha 0->1 in 0.3s)
  * 2.0s~5.2s: Cascading 45° runway lights pulse for 2 full wave cycles (3.2s)
  * 5.0s~5.5s: Global fade-out
- Audio mixing: Pop audio cues mixed at millisecond-accurate timestamps.
- Zero external audio dependencies: Synthesizes pop.wav with standard Python wave module if missing.
"""

import argparse
import math
import os
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEMO_DIR = PROJECT_ROOT / "output" / "demo"
ASSETS_SOUNDS = PROJECT_ROOT / "assets" / "sounds"
DOCS_ASSETS = PROJECT_ROOT / "docs" / "assets" / "runway_cta"

def resolve_render_font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Cross-platform font resolver: searches project assets, system fonts, and falls back to default."""
    candidates = [
        # macOS
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        # Project assets
        str(PROJECT_ROOT / "assets" / "fonts" / "SourceHanSerifCN-Medium.otf"),
        # Linux
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        # Windows
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
    ]
    for c in candidates:
        if os.path.exists(c):
            try:
                index = 1 if (bold and c.endswith(".ttc")) else 0
                return ImageFont.truetype(c, size, index=index)
            except Exception:
                try:
                    return ImageFont.truetype(c, size)
                except Exception:
                    continue
    return ImageFont.load_default()

def synthesize_pop_audio(output_wav: Path) -> Path:
    """Synthesize clean double-frequency pop audio using standard wave module."""
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

def draw_rounded_rect(draw, box, radius, fill=None, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)

def draw_plus_icon(draw, cx, cy, size, color, stroke=3):
    hs = size // 2
    draw.line([cx - hs, cy, cx + hs, cy], fill=color, width=stroke)
    draw.line([cx, cy - hs, cx, cy + hs], fill=color, width=stroke)

def draw_check_icon(draw, cx, cy, size, color, stroke=3):
    hs = size // 2
    p1 = (cx - hs, cy)
    p2 = (cx - hs // 3, cy + hs // 2)
    p3 = (cx + hs, cy - hs // 2)
    draw.line([p1, p2], fill=color, width=stroke)
    draw.line([p2, p3], fill=color, width=stroke)

def draw_thumb_up(draw, cx, cy, size, color):
    hs = size // 2
    draw.rectangle([cx - hs, cy - hs//3, cx - hs//3, cy + hs], fill=color)
    draw.polygon([
        (cx - hs//3, cy - hs//3),
        (cx - hs//6, cy - hs),
        (cx + hs//4, cy - hs),
        (cx + hs//6, cy - hs//3),
        (cx + hs, cy - hs//3),
        (cx + hs*0.8, cy + hs),
        (cx - hs//3, cy + hs)
    ], fill=color)

def draw_speech_bubble(draw, cx, cy, size, color):
    hs = size // 2
    draw.rounded_rectangle([cx - hs, cy - hs*0.7, cx + hs, cy + hs*0.5], radius=hs*0.4, fill=color)
    draw.polygon([
        (cx - hs*0.4, cy + hs*0.4),
        (cx - hs*0.7, cy + hs*0.9),
        (cx, cy + hs*0.4)
    ], fill=color)
    dot_r = max(1, int(size * 0.08))
    for dx in [-hs*0.4, 0, hs*0.4]:
        draw.ellipse([cx + dx - dot_r, cy - hs*0.1 - dot_r, cx + dx + dot_r, cy - hs*0.1 + dot_r], fill=(255, 255, 255, 255))

def draw_cursor(draw, x, y, scale=1.0):
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

def create_badge_a(scale=1.0, liked=False, followed=False, like_pop=1.0):
    """Central white porcelain triple-action capsule [ 点赞 | 关注 | 评论 ]."""
    w = int(640 * scale)
    h = int(104 * scale)
    padding = int(24 * scale)
    
    img = Image.new("RGBA", (w + padding * 2, h + padding * 2), (0, 0, 0, 0))
    s = Image.new("RGBA", (w + padding * 2, h + padding * 2), (0, 0, 0, 0))
    s_draw = ImageDraw.Draw(s)
    draw_rounded_rect(s_draw, (padding, padding + int(8*scale), padding + w, padding + h + int(8*scale)), 
                      radius=int(52*scale), fill=(0, 0, 0, 110))
    s = s.filter(ImageFilter.GaussianBlur(radius=int(10*scale)))
    img.paste(s, (0, 0), s)
    
    draw = ImageDraw.Draw(img)
    draw_rounded_rect(draw, (padding, padding, padding + w, padding + h), 
                      radius=int(52*scale), fill=(255, 255, 255, 250),
                      outline=(240, 242, 246, 255), width=int(2*scale))
    
    c_red = (235, 45, 45, 255)
    font_btn = resolve_render_font(int(30 * scale), bold=True)
    font_follow = resolve_render_font(int(26 * scale), bold=True)
    
    # 1. Like
    like_cx = padding + int(w * 0.17)
    like_cy = padding + int(h * 0.5)
    draw_thumb_up(draw, like_cx - int(45*scale), like_cy, size=int(34*scale*like_pop), color=c_red)
    draw.text((like_cx - int(10*scale), like_cy), "点赞", font=font_btn, fill=c_red, anchor="lm")
    
    div1_x = padding + int(w * 0.35)
    draw.line([div1_x, padding + int(h * 0.28), div1_x, padding + int(h * 0.72)], fill=(225, 227, 232, 255), width=2)
    
    # 2. Follow
    fol_cx = padding + int(w * 0.51)
    fol_cy = padding + int(h * 0.5)
    bw = int(176 * scale)
    bh = int(74 * scale)
    badge_box = (fol_cx - bw//2, fol_cy - bh//2, fol_cx + bw//2, fol_cy + bh//2)
    
    if followed:
        draw_rounded_rect(draw, badge_box, radius=int(37*scale), fill=(240, 242, 245, 255))
        draw_check_icon(draw, fol_cx - int(45*scale), fol_cy, size=int(20*scale), color=(100, 110, 120, 255), stroke=int(3*scale))
        draw.text((fol_cx + int(10*scale), fol_cy), "已关注", font=font_follow, fill=(100, 110, 120, 255), anchor="mm")
    else:
        draw_rounded_rect(draw, badge_box, radius=int(37*scale), fill=c_red)
        draw_plus_icon(draw, fol_cx - int(42*scale), fol_cy, size=int(20*scale), color=(255, 255, 255, 255), stroke=int(3*scale))
        draw.text((fol_cx + int(12*scale), fol_cy), "关注", font=font_follow, fill=(255, 255, 255, 255), anchor="mm")
    
    div2_x = padding + int(w * 0.67)
    draw.line([div2_x, padding + int(h * 0.28), div2_x, padding + int(h * 0.72)], fill=(225, 227, 232, 255), width=2)
    
    # 3. Comment
    com_cx = padding + int(w * 0.83)
    com_cy = padding + int(h * 0.5)
    draw_speech_bubble(draw, com_cx - int(45*scale), com_cy, size=int(34*scale), color=c_red)
    draw.text((com_cx - int(10*scale), com_cy), "评论", font=font_btn, fill=c_red, anchor="lm")
    return img

def create_hook_banner(scale=1.0, text="觉得有收获？点赞关注防走丢"):
    """Frosted top hook banner for Trigger 2 (tail conversion)."""
    hw = int(540 * scale)
    hh = int(48 * scale)
    img = Image.new("RGBA", (hw + 20, hh + 20), (0, 0, 0, 0))
    s = Image.new("RGBA", (hw + 20, hh + 20), (0, 0, 0, 0))
    s_draw = ImageDraw.Draw(s)
    draw_rounded_rect(s_draw, (10, 12, 10 + hw, 12 + hh), radius=int(24*scale), fill=(0, 0, 0, 70))
    s = s.filter(ImageFilter.GaussianBlur(radius=int(6*scale)))
    img.paste(s, (0, 0), s)
    
    draw = ImageDraw.Draw(img)
    draw_rounded_rect(draw, (10, 10, 10 + hw, 10 + hh), radius=int(24*scale), 
                      fill=(22, 26, 35, 235), outline=(245, 60, 60, 140), width=1)
    
    font_h = resolve_render_font(int(24 * scale), bold=True)
    draw.text((10 + hw // 2, 10 + hh // 2), f"• {text} •", font=font_h, fill=(245, 248, 255, 245), anchor="mm")
    return img

def render_option_c_pointer(scale=4, phase=0.0, alpha=1.0):
    """
    Renders Refined Option C: Obsidian glass pill (NO internal arrow)
    with cascading 45° runway lights pulsing toward the bottom-left corner.
    """
    w, h = 360 * scale, 180 * scale
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    
    if alpha <= 0.01:
        return canvas.resize((w // scale, h // scale), Image.Resampling.LANCZOS)
    
    bx, by = 48 * scale, 16 * scale
    bw, bh = 196 * scale, 54 * scale
    r = 27 * scale
    
    # 1. Shadow
    shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    s_draw = ImageDraw.Draw(shadow)
    s_draw.rounded_rectangle((bx, by + 8 * scale, bx + bw, by + bh + 8 * scale), 
                             radius=r, fill=(0, 0, 0, int(160 * alpha)))
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=8 * scale))
    canvas.paste(shadow, (0, 0), shadow)
    
    draw = ImageDraw.Draw(canvas)
    
    # 2. Obsidian Glass Pill
    draw.rounded_rectangle((bx, by, bx + bw, by + bh), radius=r,
                           fill=(18, 22, 30, int(242 * alpha)),
                           outline=(255, 255, 255, int(45 * alpha)), width=int(1.8 * scale))
    
    # Specular rim
    rim_col = (255, 255, 255, int(75 * alpha))
    rw = int(1.5 * scale)
    draw.arc((bx, by, bx + 2 * r, by + 2 * r), start=205, end=270, fill=rim_col, width=rw)
    draw.line([(bx + r, by), (bx + bw - r, by)], fill=rim_col, width=rw)
    draw.arc((bx + bw - 2 * r, by, bx + bw, by + 2 * r), start=270, end=335, fill=rim_col, width=rw)
    
    # Plus button
    p_cx = bx + 32 * scale
    p_cy = by + bh // 2
    draw.ellipse((p_cx - 15 * scale, p_cy - 15 * scale, p_cx + 15 * scale, p_cy + 15 * scale),
                 fill=(255, 48, 64, int(255 * alpha)))
    draw_plus_icon(draw, p_cx, p_cy, size=13 * scale, color=(255, 255, 255, int(255 * alpha)), stroke=int(3 * scale))
    
    # Typography: "关注创作者" (Balanced & Centered)
    font_main = resolve_render_font(21 * scale, bold=True)
    draw.text((bx + 60 * scale, p_cy), "关注创作者", font=font_main, fill=(255, 255, 255, int(255 * alpha)), anchor="lm")
    
    # 3. 45° Cascading Runway Chevrons
    start_x = bx + 36 * scale
    start_y = by + bh + 18 * scale
    step_d = 20 * scale
    dir_x = -math.sqrt(2) / 2
    dir_y =  math.sqrt(2) / 2
    
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

def build_overlay_frame(t: float, duration: float = 5.5, with_hook: bool = False, hook_text: str = "觉得有收获？点赞关注防走丢"):
    """
    Strict lifecycle timing matching Work Order:
    - 0.0s~0.4s: Central badge pops in (scale: 0.7 -> 1.06 -> 1.0)
    - 0.4s~1.0s: Cursor glides to Like and clicks @ t=0.8s (+1 particle)
    - 1.0s~1.6s: Cursor glides to Follow and clicks @ t=1.4s (turns to ✓已关注)
    - 1.6s~2.0s: Cursor fades out
    - 2.0s (delay 2.0s): Left-bottom corner guidance emerges (alpha 0 -> 1.0 in 0.3s)
    - 2.0s~5.2s: Cascading 45° runway lights pulse for 2 full cycles (3.2s)
    - 5.0s~5.5s: Global fade out
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
        # Floating +1 particle
        p_prog = (t - 0.8) / 0.8
        if p_prog < 1.0:
            plus_one_pos = (310, int(840 - 35 * p_prog), max(0.0, 1.0 - p_prog))
    elif t < 2.0:
        liked = True
        followed = True
        # Cursor fades out
        c_alpha = max(0.0, 1.0 - (t - 1.6) / 0.3)
        if c_alpha > 0.05:
            cursor_pos = (540, 875)
    elif t < 5.0:
        liked = True
        followed = True
        # Left-bottom corner emerges strictly at t=2.0s
        corner_alpha = min(1.0, (t - 2.0) / 0.3)
        # Period = 1.6s -> freq = 1 / 1.6 = 0.625
        corner_phase = (t - 2.0) / 1.6
    else:
        liked = True
        followed = True
        out_prog = (t - 5.0) / 0.5
        alpha = max(0.0, 1.0 - out_prog)
        corner_alpha = alpha
        corner_phase = (t - 2.0) / 1.6
        dy = int(20 * out_prog)
        
    # 1. Main CTA Badge
    badge = create_badge_a(scale=scale, liked=liked, followed=followed, like_pop=like_pop)
    if alpha < 1.0:
        r_ch, g_ch, b_ch, a_ch = badge.split()
        a_ch = a_ch.point(lambda p: int(p * alpha))
        badge.putalpha(a_ch)
        
    pos_x = (1080 - badge.width) // 2
    pos_y = 820 + dy
    overlay.paste(badge, (pos_x, pos_y), badge)
    
    # 2. Hook Banner
    if with_hook:
        hb = create_hook_banner(scale=0.95, text=hook_text)
        if alpha < 1.0:
            r_ch, g_ch, b_ch, a_ch = hb.split()
            a_ch = a_ch.point(lambda p: int(p * alpha))
            hb.putalpha(a_ch)
        hx = (1080 - hb.width) // 2
        hy = 760 + dy
        overlay.paste(hb, (hx, hy), hb)
        
    # 3. +1 Particle
    o_draw = ImageDraw.Draw(overlay)
    if plus_one_pos:
        px, py, pa = plus_one_pos
        font_p = resolve_render_font(26, bold=True)
        o_draw.text((px, py), "+1", font=font_p, fill=(245, 50, 65, int(255 * pa)), anchor="mm")
        
    # 4. Cursor
    if cursor_pos and alpha > 0.3 and t < 1.9:
        draw_cursor(o_draw, cursor_pos[0], cursor_pos[1], scale=1.0)
        
    # 5. Left-bottom corner guidance (X=85, Y=1680)
    if corner_alpha > 0.01:
        c_guide = render_option_c_pointer(scale=4, phase=corner_phase, alpha=corner_alpha)
        overlay.paste(c_guide, (85, 1680), c_guide)
        
    return overlay

def generate_overlay_sequence(output_dir: Path, duration: float = 5.5, fps: int = 30, with_hook: bool = False):
    """Render PNG frame sequence for an overlay event."""
    output_dir.mkdir(parents=True, exist_ok=True)
    total_frames = int(duration * fps)
    for i in range(total_frames):
        t = i / float(fps)
        frame = build_overlay_frame(t, duration=duration, with_hook=with_hook)
        frame.save(output_dir / f"frame_{i:04d}.png")

def render_interactive_demo(input_video: Path, output_video: Path, work_dir: Path | None = None):
    """Composites dual-moment Runway-CTA interaction into the target video."""
    if not input_video.is_file():
        raise FileNotFoundError(f"Input video not found: {input_video}")
        
    cleanup_temp = False
    if work_dir is None:
        work_dir = Path(tempfile.mkdtemp(prefix="runway_cta_"))
        cleanup_temp = True
    else:
        work_dir.mkdir(parents=True, exist_ok=True)
        
    try:
        print(f"[Runway-CTA] Work directory: {work_dir}")
        duration = 5.5
        fps = 30
        
        # 1. Overlay 1 (Trigger 1: t=12.0s ~ 17.5s, duration 5.5s)
        ov1_dir = work_dir / "ov1_frames"
        print(f"[Runway-CTA] Generating Overlay 1 frames ({duration}s)...")
        generate_overlay_sequence(ov1_dir, duration=duration, fps=fps, with_hook=False)
        
        # 2. Overlay 2 (Trigger 2: t=46.0s ~ 51.5s, duration 5.5s)
        ov2_dir = work_dir / "ov2_frames"
        print(f"[Runway-CTA] Generating Overlay 2 frames ({duration}s, with hook)...")
        generate_overlay_sequence(ov2_dir, duration=duration, fps=fps, with_hook=True)
        
        ov1_mov = work_dir / "ov1.mov"
        ov2_mov = work_dir / "ov2.mov"
        
        print("[Runway-CTA] Encoding transparent alpha video streams...")
        subprocess.run([
            "ffmpeg", "-y", "-framerate", str(fps),
            "-i", str(ov1_dir / "frame_%04d.png"),
            "-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le",
            str(ov1_mov)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        subprocess.run([
            "ffmpeg", "-y", "-framerate", str(fps),
            "-i", str(ov2_dir / "frame_%04d.png"),
            "-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le",
            str(ov2_mov)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # 3. Audio pop cues
        pop_wav = ASSETS_SOUNDS / "pop.wav"
        if not pop_wav.is_file():
            print(f"[Runway-CTA] Synthesizing missing pop sound to {pop_wav}...")
            synthesize_pop_audio(pop_wav)
            
        output_video.parent.mkdir(parents=True, exist_ok=True)
        print(f"[Runway-CTA] Compositing into final video: {output_video}...")
        
        # Millisecond-accurate audio delays:
        # Trigger 1 @ 12.0s: Like click @ +0.8s (12800ms), Follow click @ +1.4s (13400ms)
        # Trigger 2 @ 46.0s: Like click @ +0.8s (46800ms), Follow click @ +1.4s (47400ms)
        filter_complex = (
            # Visual overlay 1
            "[1:v]setpts=PTS-STARTPTS+12.0/TB[v_ov1];"
            "[0:v][v_ov1]overlay=0:0:enable='between(t,12.0,17.5)'[v1];"
            # Visual overlay 2
            "[2:v]setpts=PTS-STARTPTS+46.0/TB[v_ov2];"
            "[v1][v_ov2]overlay=0:0:enable='between(t,46.0,51.5)'[vout];"
            # Audio pop cues
            "[3:a]adelay=12800|12800,volume=0.45[p1];"
            "[3:a]adelay=13400|13400,volume=0.40[p2];"
            "[3:a]adelay=46800|46800,volume=0.45[p3];"
            "[3:a]adelay=47400|47400,volume=0.40[p4];"
            "[0:a][p1][p2][p3][p4]amix=inputs=5:dropout_transition=0:normalize=0[aout]"
        )
        
        cmd = [
            "ffmpeg", "-y",
            "-i", str(input_video),
            "-i", str(ov1_mov),
            "-i", str(ov2_mov),
            "-i", str(pop_wav),
            "-filter_complex", filter_complex,
            "-map", "[vout]",
            "-map", "[aout]",
            "-t", "60",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "20",
            "-c:a", "aac",
            "-b:a", "192k",
            str(output_video)
        ]
        subprocess.run(cmd, check=True)
        print(f"[Runway-CTA] SUCCESS! Output rendered: {output_video}")
        
        # 4. Refresh doc GIF & capture artifacts
        DOCS_ASSETS.mkdir(parents=True, exist_ok=True)
        print("[Runway-CTA] Updating documentation capture & GIF assets...")
        # Trigger 1 GIF (11.8s to 18.0s)
        subprocess.run([
            "ffmpeg", "-y", "-ss", "11.8", "-t", "6.0",
            "-i", str(output_video),
            "-filter_complex", "fps=20,scale=405:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=128[p];[s1][p]paletteuse=dither=bayer:bayer_scale=3",
            str(DOCS_ASSETS / "real_demo_trigger1_motion.gif")
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # Trigger 2 GIF (45.8s to 52.0s)
        subprocess.run([
            "ffmpeg", "-y", "-ss", "45.8", "-t", "6.0",
            "-i", str(output_video),
            "-filter_complex", "fps=20,scale=405:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=128[p];[s1][p]paletteuse=dither=bayer:bayer_scale=3",
            str(DOCS_ASSETS / "real_demo_trigger2_motion.gif")
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
    finally:
        if cleanup_temp and work_dir and work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)

def main():
    parser = argparse.ArgumentParser(description="Project Runway-CTA Reference Renderer")
    default_input = PROJECT_ROOT / "output" / "-f7evD_gh34_vertical.mp4"
    default_output = DEMO_DIR / "runway_cta_sample_60s.mp4"
    
    parser.add_argument("--input", "-i", type=Path, default=default_input, help="Input vertical video path")
    parser.add_argument("--output", "-o", type=Path, default=default_output, help="Output demo video path")
    parser.add_argument("--work-dir", "-w", type=Path, default=None, help="Working directory for intermediate frames")
    
    args = parser.parse_args()
    
    # Fallback to existing demo if raw source is missing
    if not args.input.is_file() and (DEMO_DIR / "runway_cta_sample_60s.mp4").is_file():
        args.input = DEMO_DIR / "runway_cta_sample_60s.mp4"
        
    render_interactive_demo(args.input, args.output, args.work_dir)

if __name__ == "__main__":
    main()
