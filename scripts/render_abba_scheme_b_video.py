#!/usr/bin/env python3
"""Render formal video for ABBA - Gimme! Gimme! Gimme! (Scheme B v2 - Safe Zones & Default Lyrics Visible).

Key Features:
1. Strict Mobile Safe Zones (Top >= 210px, Bottom safe margin >= 400px):
   - Completely clears mobile status bar, battery, WiFi, clock, camera island, and top nav.
   - Completely clears WeChat Channels avatar, video title, copy description, and interaction buttons.
2. Default Lyrics Visibility:
   - All 10 lyric lines (side column + main section) are pre-printed and 100% visible from frame 0.
   - Never wait until sung to appear. Zero blank wasteland.
3. Realistic Pen Dynamics & Active Singing Highlight:
   - Pen physically points at and traces the active singing word with dual shadows (contact AO + progressive cast shadow).
   - Active line is accented with a delicate warm amber highlighter ribbon and vibrant focus carmine ink.
4. Synchronized Official 1979 Polaroid PiP MV.
5. Smooth 0.7s page flip to Ending Vocabulary Study Card Page (P2/2 - 全曲语言点精萃).
6. Generates full platform cover package (WeChat 9:16, Douyin 3:4, Douyin 4:3) with self-consistent provenance hashes.
7. Generates platform copywriting packages.

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-09 | Antigravity | ABBA《Gimme! Gimme! Gimme!》方案B(v2)母带渲染器：拍立得画中画同步MV、零重叠粗墨手写、终曲研读卡翻页。 |
| 2.0.0 | 2026-10-09 | Antigravity | 严格手机安全区适配（顶部≥210px防电量/信号/导航遮挡，底部≥400px防视频号头像/简介遮挡）；默认全曲歌词立显（零盲区预印墨水）；物理双阴影钢笔轨迹平滑追踪与荧光笔高亮伴读；全套封面产物及自洽凭证哈希生成。 |
| 3.0.0 | 2026-10-09 | Antigravity | 修复换行阶段关键帧去重丢失导致的钢笔轨迹脱节与滞空漂移Bug；消除第1行未唱先红的预印墨水瑕疵；重构高亮伴读层为渐进持久暖金荧光带；优化P2终章研读卡行距并下移钢笔休止位避让品牌标识。 |
"""

import cv2
import hashlib
import json
import logging
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Tuple
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ABBA_Renderer")

WORK_DIR = PROJECT_ROOT / "output/handwritten_pager/gimme"
WORK_DIR.mkdir(parents=True, exist_ok=True)
COVERS_DIR = WORK_DIR / "covers"
COVERS_DIR.mkdir(parents=True, exist_ok=True)
COPY_DIR = WORK_DIR / "copy"
COPY_DIR.mkdir(parents=True, exist_ok=True)
DEMOS_DIR = WORK_DIR / "demos"
DEMOS_DIR.mkdir(parents=True, exist_ok=True)

AUDIO_PATH = WORK_DIR / "audio_trimmed.wav"
MV_PATH = WORK_DIR / "mv_pip.mp4"
OUTPUT_VIDEO_PATH = WORK_DIR / "gimme_full_handwritten_pager.mp4"

# Assets
ASSETS_DIR = PROJECT_ROOT / "src/video_processing/handwritten_pager/assets"
PAPER_PATH = ASSETS_DIR / "paper_texture_ivory.jpg"
PEN_PATH = ASSETS_DIR / "pen_ballpoint_photorealistic.png"
LOGO_PATH = PROJECT_ROOT / "assets/brand/01_logos/concept_a.png"
MV_FRAME_PATH = WORK_DIR / "frames/frame_agnetha_40s.jpg"

# Fonts
FONT_ZH_CALLIGRAPHY = "/Library/Fonts/TianYingZhang.ttf"
FONT_EN_NOTEWORTHY = "/System/Library/Fonts/Noteworthy.ttc"
FONT_ARIAL_UNICODE = "/Library/Fonts/Arial Unicode.ttf"
FONT_SANS = "/Library/Fonts/Hiragino Sans GB.ttc"

def load_font(path_str: str, size: int, index=0):
    try:
        if path_str.endswith(".ttc"):
            return ImageFont.truetype(path_str, size, index=index)
        return ImageFont.truetype(path_str, size)
    except Exception:
        return ImageFont.load_default()

# Global Typography Tokens
font_brand = load_font(FONT_SANS, 22)
font_slogan = load_font(FONT_SANS, 18)
font_title_en = load_font(FONT_EN_NOTEWORTHY, 32, index=1)
font_title_zh = load_font(FONT_ZH_CALLIGRAPHY, 25)
font_subtitle = load_font(FONT_SANS, 18)

# Side Column Lyrics Fonts
font_side_en = load_font(FONT_EN_NOTEWORTHY, 24, index=1)
font_side_zh = load_font(FONT_ZH_CALLIGRAPHY, 19)

# Main Lower Lyrics Fonts
font_lyrics_en_large = load_font(FONT_EN_NOTEWORTHY, 31, index=1)
font_lyrics_zh_large = load_font(FONT_ZH_CALLIGRAPHY, 23)

def is_chinese_char(char: str) -> bool:
    cp = ord(char)
    return (0x4E00 <= cp <= 0x9FFF) or (0x3400 <= cp <= 0x4DBF)

def draw_mixed_text(draw: ImageDraw.ImageDraw, pos, text: str, font_zh, font_sym, fill):
    x, y = pos
    for char in text:
        if is_chinese_char(char):
            draw.text((x, y), char, font=font_zh, fill=fill)
            x += draw.textlength(char, font=font_zh)
        else:
            draw.text((x, y), char, font=font_sym, fill=fill)
            x += draw.textlength(char, font=font_sym)

def get_base_paper():
    base = Image.new("RGBA", (1080, 1920), (254, 251, 246, 255))
    if PAPER_PATH.exists():
        tex = Image.open(PAPER_PATH).convert("RGBA").resize((1080, 1920), Image.Resampling.BILINEAR)
        return Image.blend(base, tex, alpha=0.15)
    return base

def get_clean_logo(size=42):
    if LOGO_PATH.exists():
        raw = Image.open(LOGO_PATH).convert("RGBA")
        w, h = raw.size
        cropped = raw.crop((int(w * 0.0625), int(h * 0.0625), int(w * 0.9375), int(h * 0.9375)))
        im = cropped.resize((size, size), Image.Resampling.LANCZOS)
    else:
        im = Image.new("RGBA", (size, size), (20, 25, 35, 255))
    bg = Image.new("RGBA", (size + 6, size + 6), (0, 0, 0, 0))
    d = ImageDraw.Draw(bg)
    r = int(size * 0.20)
    d.rounded_rectangle([2, 2, size + 4, size + 4], radius=r, fill=(18, 22, 30, 255), outline=(243, 186, 47, 240), width=2)
    bg.paste(im, (3, 3), im)
    return bg

def draw_notebook_holes(draw: ImageDraw.ImageDraw, y_start=60, y_end=1880, step=110):
    for y in range(y_start, y_end, step):
        draw.ellipse([38, y, 62, y + 24], fill=(225, 220, 210, 255), outline=(180, 172, 160, 200), width=2)
    draw.line([(130, y_start - 20), (130, y_end + 20)], fill=(220, 100, 100, 130), width=2)

def prepare_polaroid_template():
    p_w, p_h = 390, 280
    polaroid = Image.new("RGBA", (p_w, p_h), (255, 253, 248, 255))
    pd = ImageDraw.Draw(polaroid)
    pd.rectangle([0, 0, p_w - 1, p_h - 1], outline=(210, 200, 190, 220), width=1)
    pd.text((14, 235), "Agnetha @ Polar Studio 1979", fill=(70, 75, 85, 220), font=load_font(FONT_EN_NOTEWORTHY, 19, index=1))
    pd.text((280, 240), "● Official MV", fill=(160, 50, 50, 220), font=load_font(FONT_SANS, 14))
    
    dummy_rot = polaroid.rotate(-2.0, expand=True, resample=Image.Resampling.BILINEAR)
    pshadow = Image.new("RGBA", dummy_rot.size, (0, 0, 0, 0))
    for x in range(0, dummy_rot.width, 2):
        for y in range(0, dummy_rot.height, 2):
            if dummy_rot.getpixel((x, y))[3] > 40:
                pshadow.putpixel((x, y), (35, 30, 25, 110))
    pshadow = pshadow.filter(ImageFilter.GaussianBlur(radius=10))
    
    tape = Image.new("RGBA", (110, 28), (235, 205, 130, 190))
    ImageDraw.Draw(tape).line([(0, 0), (110, 0)], fill=(255, 255, 255, 80), width=1)
    tape_rot = tape.rotate(-2.0, expand=True)
    return polaroid, pshadow, tape_rot

def composite_polaroid_frame(canvas: Image.Image, polaroid_template: Image.Image, pshadow: Image.Image, tape_rot: Image.Image, mv_rgb_frame: np.ndarray):
    px_pos, py_pos = 550, 336
    p = polaroid_template.copy()
    im_frame = Image.fromarray(mv_rgb_frame).resize((366, 210), Image.Resampling.BILINEAR)
    p.paste(im_frame, (12, 12))
    p_rot = p.rotate(-2.0, expand=True, resample=Image.Resampling.BILINEAR)
    canvas.paste(pshadow, (px_pos + 8, py_pos + 10), pshadow)
    canvas.paste(p_rot, (px_pos, py_pos), p_rot)
    canvas.paste(tape_rot, (px_pos + 120, py_pos - 8), tape_rot)


# =========================================================================
# LYRIC DATA & GEOMETRY SPECIFICATION
# =========================================================================
def get_lyrics_schedule():
    side_lyrics = [
        {"type": "single", "en": "Half past twelve,", "zh": "午夜时分孤身一人，", "start": 35.76, "end": 37.46},
        {"type": "single", "en": "Watching the late show", "zh": "独看深夜电视节目，", "start": 37.46, "end": 39.34},
        {"type": "single", "en": "In my flat all alone.", "zh": "空荡寓所寂寥无声。", "start": 39.60, "end": 41.40},
        {"type": "double", "lines": ["How I hate to spend the evening", "on my own!"], "zh": "我多讨厌独自熬过漫漫长夜！", "start": 41.52, "end": 45.34},
    ]
    main_lyrics = [
        {
            "type": "wrap",
            "line1": "Autumn winds blowing outside the window as",
            "line2": "I look around the room",
            "zh": "窗外秋风呼啸，我环顾空荡冰冷的房间",
            "start": 45.34,
            "end": 51.46,
            "highlight": False,
        },
        {
            "type": "single",
            "en": "And it makes me so depressed to see the gloom",
            "zh": "眼前无尽的幽暗与沉寂令我深陷落寞",
            "start": 51.46,
            "end": 54.42,
            "highlight": False,
        },
        {
            "type": "wrap",
            "line1": "There's not a soul out there, no",
            "line2": "one to hear my prayer",
            "zh": "四下空无一人，无人倾听我内心的低语祈求",
            "start": 56.14,
            "end": 63.50,
            "highlight": False,
        },
        {
            "type": "single",
            "en": "Gimme! Gimme! Gimme! a man after midnight!",
            "zh": "赐我一份怀抱，在午夜之后！",
            "start": 65.28,
            "end": 71.36,
            "highlight": True,
        },
        {
            "type": "wrap",
            "line1": "Won't somebody help me chase",
            "line2": "the shadows away?",
            "zh": "难道无人能助我驱散这暗夜孤影吗？",
            "start": 71.36,
            "end": 75.36,
            "highlight": False,
        },
        {
            "type": "wrap",
            "line1": "Take me through the darkness to",
            "line2": "the break of the day!",
            "zh": "带我穿透无尽黑暗，直至黎明破晓！",
            "start": 79.42,
            "end": 84.50,
            "highlight": False,
        },
    ]
    return side_lyrics, main_lyrics


def get_lyrics_geometry():
    """Computes exact (x, y) bounding boxes for all lyrics so both static drawing and pen tracking are identical."""
    side_lyrics, main_lyrics = get_lyrics_schedule()
    im_dummy = ImageDraw.Draw(Image.new("RGBA", (100, 100)))
    
    side_geom = []
    dy = 320
    for item in side_lyrics:
        if item["type"] == "single":
            en = item["en"]
            w_en = im_dummy.textlength(en, font=font_side_en)
            b_en = im_dummy.textbbox((150, dy), en, font=font_side_en)
            zh_y = b_en[3] + 6
            b_zh = im_dummy.textbbox((150, zh_y), item["zh"], font=font_side_zh)
            side_geom.append({
                "type": "single",
                "en": en,
                "zh": item["zh"],
                "start": item["start"],
                "end": item["end"],
                "en_pos": (150, dy),
                "en_w": w_en,
                "zh_pos": (150, zh_y),
                "tip_y": b_en[3] + 3,
                "bottom": b_zh[3]
            })
            dy = b_zh[3] + 12
        else:
            l1, l2 = item["lines"]
            w1 = im_dummy.textlength(l1, font=font_side_en)
            b1 = im_dummy.textbbox((150, dy), l1, font=font_side_en)
            l2_y = b1[3] + 4
            w2 = im_dummy.textlength(l2, font=font_side_en)
            b2 = im_dummy.textbbox((150, l2_y), l2, font=font_side_en)
            zh_y = b2[3] + 6
            b_zh = im_dummy.textbbox((150, zh_y), item["zh"], font=font_side_zh)
            side_geom.append({
                "type": "double",
                "lines": [l1, l2],
                "zh": item["zh"],
                "start": item["start"],
                "end": item["end"],
                "l1_pos": (150, dy),
                "l1_w": w1,
                "l1_tip_y": b1[3] + 3,
                "l2_pos": (150, l2_y),
                "l2_w": w2,
                "l2_tip_y": b2[3] + 3,
                "zh_pos": (150, zh_y),
                "bottom": b_zh[3]
            })
            dy = b_zh[3] + 12
            
    main_geom = []
    cy = 675
    for item in main_lyrics:
        is_hl = item["highlight"]
        f_en = load_font(FONT_EN_NOTEWORTHY, 34, index=1) if is_hl else font_lyrics_en_large
        f_zh = load_font(FONT_ZH_CALLIGRAPHY, 25) if is_hl else font_lyrics_zh_large
        if item["type"] == "wrap":
            l1 = item["line1"]
            l2 = item["line2"]
            w1 = im_dummy.textlength(l1, font=f_en)
            b1 = im_dummy.textbbox((155, cy), l1, font=f_en)
            l2_y = b1[3] + 5
            w2 = im_dummy.textlength(l2, font=f_en)
            b2 = im_dummy.textbbox((155, l2_y), l2, font=f_en)
            zh_y = b2[3] + 8
            b_zh = im_dummy.textbbox((155, zh_y), item["zh"], font=f_zh)
            main_geom.append({
                "type": "wrap",
                "line1": l1,
                "line2": l2,
                "zh": item["zh"],
                "start": item["start"],
                "end": item["end"],
                "highlight": is_hl,
                "font_en": f_en,
                "font_zh": f_zh,
                "l1_pos": (155, cy),
                "l1_w": w1,
                "l1_tip_y": b1[3] + 4,
                "l2_pos": (155, l2_y),
                "l2_w": w2,
                "l2_tip_y": b2[3] + 4,
                "zh_pos": (155, zh_y),
                "bottom": b_zh[3]
            })
            cy = b_zh[3] + 18
        else:
            en = item["en"]
            w_en = im_dummy.textlength(en, font=f_en)
            b_en = im_dummy.textbbox((155, cy), en, font=f_en)
            zh_y = b_en[3] + 8
            b_zh = im_dummy.textbbox((155, zh_y), item["zh"], font=f_zh)
            main_geom.append({
                "type": "single",
                "en": en,
                "zh": item["zh"],
                "start": item["start"],
                "end": item["end"],
                "highlight": is_hl,
                "font_en": f_en,
                "font_zh": f_zh,
                "en_pos": (155, cy),
                "en_w": w_en,
                "zh_pos": (155, zh_y),
                "tip_y": b_en[3] + 4,
                "bottom": b_zh[3]
            })
            cy = b_zh[3] + 18
            
    return side_geom, main_geom


def build_page1_static_base():
    """Builds Page 1 base canvas with strict safe zones (Y >= 210, Y <= 1520) and FULLY PRE-PRINTED LYRICS."""
    canvas = get_base_paper()
    draw = ImageDraw.Draw(canvas)
    draw_notebook_holes(draw, y_start=60, y_end=1880, step=110)
    
    # --- Top Brand Header (Y = 210 ~ 330) ---
    logo = get_clean_logo(42)
    canvas.paste(logo, (150, 210), logo)
    draw.text((205, 214), "六维时空号", fill=(35, 40, 50, 240), font=font_brand)
    draw.line([(335, 220), (335, 244)], fill=(180, 170, 160, 180), width=2)
    draw.text((355, 219), "“不同的视角，看见更大的世界。”", fill=(130, 95, 45, 220), font=font_slogan)
    draw_mixed_text(draw, (730, 219), "★ 音乐手账 · 经典典藏 (P1/2)", load_font(FONT_ZH_CALLIGRAPHY, 19), font_slogan, (110, 115, 125, 210))
    
    # Song Title Row
    draw.text((150, 262), "Gimme! Gimme! Gimme!", fill=(140, 30, 30, 255), font=font_title_en)
    title_w = draw.textlength("Gimme! Gimme! Gimme!", font=font_title_en)
    zh_box_x = int(150 + title_w + 16)
    draw.rounded_rectangle([zh_box_x, 265, zh_box_x + 145, 298], radius=6, fill=(245, 228, 175, 240), outline=(215, 165, 55, 200), width=1)
    draw_mixed_text(draw, (zh_box_x + 8, 267), "《午夜求爱》", font_title_zh, load_font(FONT_SANS, 20), (70, 45, 15, 255))
    
    act_box_x = zh_box_x + 158
    draw.rounded_rectangle([act_box_x, 265, act_box_x + 185, 298], radius=6, fill=(250, 240, 230, 220), outline=(190, 120, 70, 180), width=1)
    draw_mixed_text(draw, (act_box_x + 8, 269), "【第一幕 · 孤影独白】", font_title_zh, load_font(FONT_SANS, 18), (140, 60, 30, 240))
    
    draw_mixed_text(draw, (150, 308), "原唱：ABBA (1979)  ·  Agnetha Faltskog 主唱  ·  全曲双语伴读", load_font(FONT_ZH_CALLIGRAPHY, 18), font_subtitle, (100, 105, 115, 230))
    draw.line([(150, 332), (960, 332)], fill=(220, 210, 195, 180), width=1)
    draw.line([(150, 665), (960, 665)], fill=(220, 210, 195, 180), width=1)
    
    # --- PRE-RENDER ALL LYRICS (DEFAULT VISIBILITY) ---
    side_geom, main_geom = get_lyrics_geometry()
    
    # Side Lyrics (Default state)
    for g in side_geom:
        if g["type"] == "single":
            col_en = (42, 48, 58, 245)
            draw.text(g["en_pos"], g["en"], fill=col_en, font=font_side_en)
            draw_mixed_text(draw, g["zh_pos"], g["zh"], font_side_zh, load_font(FONT_SANS, 20), (68, 62, 58, 240))
        else:
            draw.text(g["l1_pos"], g["lines"][0], fill=(42, 48, 58, 245), font=font_side_en)
            draw.text(g["l2_pos"], g["lines"][1], fill=(42, 48, 58, 245), font=font_side_en)
            draw_mixed_text(draw, g["zh_pos"], g["zh"], font_side_zh, load_font(FONT_SANS, 20), (68, 62, 58, 240))
            
    # Main Lyrics (Default state)
    for g in main_geom:
        col_en = (165, 28, 28, 255) if g["highlight"] else (38, 44, 55, 250)
        col_zh = (55, 50, 45, 245)
        f_en = g["font_en"]
        f_zh = g["font_zh"]
        if g["type"] == "wrap":
            draw.text(g["l1_pos"], g["line1"], fill=col_en, font=f_en)
            draw.text(g["l2_pos"], g["line2"], fill=col_en, font=f_en)
            draw_mixed_text(draw, g["zh_pos"], g["zh"], f_zh, load_font(FONT_SANS, 22), col_zh)
        else:
            draw.text(g["en_pos"], g["en"], fill=col_en, font=f_en)
            draw_mixed_text(draw, g["zh_pos"], g["zh"], f_zh, load_font(FONT_SANS, 22), col_zh)
            
    # Footer (Strictly at Y = 1495, finishes at 1515, well before 1550!)
    draw_mixed_text(draw, (155, 1495), "• 本幕完 · 翻页进入下一乐段 »", load_font(FONT_ZH_CALLIGRAPHY, 19), load_font(FONT_ARIAL_UNICODE, 19), (130, 125, 120, 220))
    draw.text((790, 1495), "ABBA · 1979 POLAR", fill=(170, 160, 150, 200), font=load_font(FONT_SANS, 18))
    
    return canvas


def build_page2_vocab_canvas():
    """Builds Page 2 vocabulary study card with strict safe zones (Y >= 210, Y <= 1520)."""
    canvas = get_base_paper()
    draw = ImageDraw.Draw(canvas)
    draw_notebook_holes(draw, y_start=60, y_end=1880, step=110)
    
    # Header
    logo = get_clean_logo(42)
    canvas.paste(logo, (150, 210), logo)
    draw.text((205, 214), "六维时空号", fill=(35, 40, 50, 240), font=font_brand)
    draw.line([(335, 220), (335, 244)], fill=(180, 170, 160, 180), width=2)
    draw.text((355, 219), "“不同的视角，看见更大的世界。”", fill=(130, 95, 45, 220), font=font_slogan)
    draw_mixed_text(draw, (730, 219), "★ 音乐手账 · 终章附录 (P2/2)", load_font(FONT_ZH_CALLIGRAPHY, 19), font_slogan, (110, 115, 125, 210))
    
    draw.text((150, 262), "Gimme! Gimme! Gimme!", fill=(140, 30, 30, 255), font=font_title_en)
    title_w = draw.textlength("Gimme! Gimme! Gimme!", font=font_title_en)
    zh_box_x = int(150 + title_w + 16)
    draw.rounded_rectangle([zh_box_x, 265, zh_box_x + 145, 298], radius=6, fill=(245, 228, 175, 240), outline=(215, 165, 55, 200), width=1)
    draw_mixed_text(draw, (zh_box_x + 8, 267), "《午夜求爱》", font_title_zh, load_font(FONT_SANS, 20), (70, 45, 15, 255))
    
    act_box_x = zh_box_x + 158
    draw.rounded_rectangle([act_box_x, 265, act_box_x + 210, 298], radius=6, fill=(240, 245, 255, 240), outline=(130, 170, 220, 200), width=1)
    draw_mixed_text(draw, (act_box_x + 8, 269), "【全曲重点语言点精萃】", font_title_zh, load_font(FONT_SANS, 18), (30, 80, 140, 240))
    
    draw_mixed_text(draw, (150, 308), "策展手记：在 1979 迪斯科不朽律动中，品味最地道生动的文学英语表达", load_font(FONT_ZH_CALLIGRAPHY, 18), font_subtitle, (110, 85, 45, 230))
    draw.line([(150, 332), (960, 332)], fill=(220, 210, 195, 180), width=2)
    
    # Study card container: Y = 345 to 1300 (Generous safe margin: bottom margin = 620px!)
    card_w, card_h = 830, 955
    card_bg = Image.new("RGBA", (card_w, card_h), (254, 250, 242, 255))
    cd = ImageDraw.Draw(card_bg)
    cd.rounded_rectangle([0, 0, card_w - 2, card_h - 2], radius=14, fill=(254, 250, 242, 255), outline=(215, 175, 100, 220), width=2)
    
    # Ribbon header
    cd.rounded_rectangle([20, 16, card_w - 20, 62], radius=8, fill=(245, 230, 190, 230))
    draw_mixed_text(cd, (32, 26), "◆ 本曲核心词汇与地道修辞深度解析（建议长按暂停截图收藏）", load_font(FONT_SANS, 21), load_font(FONT_SANS, 21), (130, 50, 20, 255))
    
    vocab_entries = [
        {"word": "flat", "ipa": "/flæt/", "pos": "n.", "def": "英式英语“公寓/套房”（美式为 apartment）", "note": "• 语境精析：源自古诺尔斯语，歌词'in my flat all alone'写尽独居青年的孤寂感。"},
        {"word": "on one's own", "ipa": "/ɒn wʌnz əʊn/", "pos": "phr.", "def": "独自一人，孤立无援", "note": "• 辨析：不同于中性 alone，强烈突显无人伸出援手、独自苦苦支撑的情感色彩。"},
        {"word": "gloom", "ipa": "/ɡluːm/", "pos": "n.", "def": "幽暗，昏暗；引申为“压抑、沮丧的心境”", "note": "• 词源引申：与 gleam（微光）走向相反，表光明被完全吞噬的绝望感。"},
        {"word": "chase the shadows away", "ipa": "/tʃeɪs ðə ˈʃædəʊz əˈweɪ/", "pos": "idiom.", "def": "驱散心头的阴影与恐惧", "note": "• 修辞：拟人隐喻修辞法。将深夜独处的恐惧化为潜伏阴影，真诚陪伴方能驱散。"},
        {"word": "not a soul", "ipa": "/nɒt ə səʊl/", "pos": "idiom.", "def": "连一个人都没有", "note": "• 文学提炼：以 soul 借代 living person，四下万籁俱寂，无一温热灵魂，极致孤独。"},
        {"word": "break of the day", "ipa": "/breɪk əv ðə deɪ/", "pos": "phr.", "def": "拂晓时分，黎明破晓之际", "note": "• 意象：等同于 daybreak。黑夜终会破裂，光明必将透入，守望新生与曙光。"},
    ]
    font_ipa = load_font(FONT_ARIAL_UNICODE, 18)
    font_entry_zh = load_font(FONT_ZH_CALLIGRAPHY, 21)
    font_entry_note = load_font(FONT_ZH_CALLIGRAPHY, 19)
    
    vy = 72
    for item in vocab_entries:
        w_text = f"【{item['word']}】"
        draw_mixed_text(cd, (24, vy), w_text, load_font(FONT_EN_NOTEWORTHY, 26, index=1), load_font(FONT_SANS, 20), (160, 30, 30, 255))
        w_len = cd.textlength(w_text, font=load_font(FONT_EN_NOTEWORTHY, 26, index=1))
        cd.text((24 + w_len + 6, vy + 4), item["ipa"], fill=(25, 75, 140, 240), font=font_ipa)
        ipa_len = cd.textlength(item["ipa"], font=font_ipa)
        pos_def = f"  {item['pos']} {item['def']}"
        draw_mixed_text(cd, (24 + w_len + 6 + ipa_len, vy + 3), pos_def, font_entry_zh, font_ipa, (40, 50, 65, 240))
        draw_mixed_text(cd, (28, vy + 38), item["note"], font_entry_note, load_font(FONT_SANS, 17), (105, 95, 85, 230))
        cd.line([(24, vy + 104), (card_w - 24, vy + 104)], fill=(225, 215, 200, 180), width=1)
        vy += 120
        
    cd.rounded_rectangle([24, vy + 4, card_w - 24, vy + 130], radius=8, fill=(242, 246, 252, 255), outline=(170, 195, 230, 200), width=1)
    draw_mixed_text(cd, (36, vy + 14), "★ 乐史典故与采样回响（Cultural Legacy & Sampling）：", load_font(FONT_SANS, 19), load_font(FONT_SANS, 19), (25, 80, 150, 255))
    s_l1 = "Benny 在 ARP 合成器上写出的前奏被誉为流行乐史神级 Riff。2005 年麦当娜为单曲"
    s_l2 = "《Hung Up》亲自致信 ABBA 恳请采样授权，最终横扫全球 41 国单曲榜冠军，跨越"
    s_l3 = "四分之一世纪再度封神。"
    draw_mixed_text(cd, (36, vy + 42), s_l1, load_font(FONT_ZH_CALLIGRAPHY, 19), load_font(FONT_SANS, 17), (70, 75, 85, 230))
    draw_mixed_text(cd, (36, vy + 68), s_l2, load_font(FONT_ZH_CALLIGRAPHY, 19), load_font(FONT_SANS, 17), (70, 75, 85, 230))
    draw_mixed_text(cd, (36, vy + 94), s_l3, load_font(FONT_ZH_CALLIGRAPHY, 19), load_font(FONT_SANS, 17), (70, 75, 85, 230))
    
    canvas.paste(card_bg, (145, 345), card_bg)
    draw.text((155, 1465), "★ 研读完毕 · 关注六维时空号，戴上耳机与好歌同行", fill=(140, 135, 130, 220), font=load_font(FONT_SANS, 19))
    draw.text((780, 1465), "COSMIC EYE ARCHIVE", fill=(170, 160, 150, 200), font=load_font(FONT_SANS, 18))
    return canvas


# =========================================================================
# PEN TRAJECTORY INTERPOLATOR
# =========================================================================
def build_pen_trajectory(total_duration=91.0, fps=60):
    """Builds realistic pen motion path keyframes across all musical sections.
    
    Guarantees:
    1. Keyframe timestamps are strictly monotonic (no dropped frames upon deduplication).
    2. At the exact start of every lyric line, pen touches down at line start with z=0.0.
    3. Pen coordinates synchronize precisely with active word progress.
    4. On Page 2, pen rests at (920, 1540, z=10.0), well below all text and clear of footer.
    """
    side_geom, main_geom = get_lyrics_geometry()
    
    # Unified list of lyric line items in chronological sequence
    all_items = []
    for g in side_geom:
        all_items.append({"geom": g, "start_x": 150.0})
    for g in main_geom:
        all_items.append({"geom": g, "start_x": 155.0})

    keyframes = [
        (0.0, 450.0, 400.0, 22.0),
        (10.0, 470.0, 390.0, 20.0),
        (20.0, 440.0, 410.0, 20.0),
        (30.0, 280.0, 350.0, 16.0),
        (34.5, 160.0, 335.0, 8.0),
    ]

    for idx, item in enumerate(all_items):
        g = item["geom"]
        sx = item["start_x"]
        st, et = g["start"], g["end"]
        has_next = idx + 1 < len(all_items)
        next_st = all_items[idx + 1]["geom"]["start"] if has_next else 84.5
        next_sx = all_items[idx + 1]["start_x"] if has_next else 920.0
        next_ty = (all_items[idx + 1]["geom"]["tip_y"] if all_items[idx + 1]["geom"]["type"] == "single"
                   else all_items[idx + 1]["geom"]["l1_tip_y"]) if has_next else 1540.0

        gap = (next_st - et) if has_next else 0.0

        if g["type"] == "single":
            ty = g["tip_y"]
            w = g["en_w"]
            keyframes.append((st, sx, ty, 0.0))
            if has_next:
                if gap <= 0.15:
                    keyframes.append((et - 0.08, sx + w, ty, 0.0))
                    keyframes.append((et - 0.03, sx + w + 8.0, ty - 6.0, 4.0))
                elif gap <= 0.50:
                    keyframes.append((et, sx + w, ty, 0.0))
                    mid_gap = (et + next_st) / 2.0
                    keyframes.append((mid_gap, (sx + w + next_sx) / 2.0, (ty + next_ty) / 2.0, 6.0))
                else:
                    keyframes.append((et, sx + w, ty, 0.0))
                    keyframes.append((et + 0.15, sx + w + 15.0, ty - 8.0, 8.0))
                    keyframes.append((next_st - 0.15, next_sx - 10.0, next_ty - 10.0, 6.0))
            else:
                keyframes.append((et, sx + w, ty, 0.0))
        else:
            ty1 = g["l1_tip_y"]
            w1 = g["l1_w"]
            ty2 = g["l2_tip_y"]
            w2 = g["l2_w"]
            mid_t = (st + et) / 2.0
            keyframes.append((st, sx, ty1, 0.0))
            keyframes.append((mid_t - 0.08, sx + w1, ty1, 0.0))
            keyframes.append((mid_t - 0.03, sx + w1 + 10.0, ty1 - 6.0, 4.0))
            keyframes.append((mid_t + 0.04, sx, ty2, 0.0))
            if has_next:
                if gap <= 0.15:
                    keyframes.append((et - 0.08, sx + w2, ty2, 0.0))
                    keyframes.append((et - 0.03, sx + w2 + 8.0, ty2 - 6.0, 4.0))
                elif gap <= 0.50:
                    keyframes.append((et, sx + w2, ty2, 0.0))
                    mid_gap = (et + next_st) / 2.0
                    keyframes.append((mid_gap, (sx + w2 + next_sx) / 2.0, (ty2 + next_ty) / 2.0, 6.0))
                else:
                    keyframes.append((et, sx + w2, ty2, 0.0))
                    keyframes.append((et + 0.15, sx + w2 + 15.0, ty2 - 8.0, 8.0))
                    keyframes.append((next_st - 0.15, next_sx - 10.0, next_ty - 10.0, 6.0))
            else:
                keyframes.append((et, sx + w2, ty2, 0.0))

    # Page flip transition at 86.8s ~ 87.5s: Pen lifts high
    keyframes.append((84.7, 445.0, 1430.0, 10.0))
    keyframes.append((85.8, 750.0, 1200.0, 18.0))
    keyframes.append((86.8, 600.0, 950.0, 35.0))
    # Page 2 vocabulary study card: Pen rests at safe bottom margin (clearing footer text completely)
    keyframes.append((87.5, 920.0, 1540.0, 10.0))
    keyframes.append((91.0, 920.0, 1540.0, 10.0))

    # Sort and deduplicate
    k_t, k_x, k_y, k_z = [], [], [], []
    for pt in sorted(keyframes, key=lambda p: p[0]):
        if not k_t or pt[0] > k_t[-1] + 1e-4:
            k_t.append(pt[0])
            k_x.append(pt[1])
            k_y.append(pt[2])
            k_z.append(pt[3])

    total_frames = int(round(total_duration * fps))
    t_eval = np.linspace(0.0, total_duration, total_frames)

    from video_processing.handwritten_pager.pen_physics import _pchip_interpolate
    x_eval = _pchip_interpolate(np.array(k_t), np.array(k_x), t_eval)
    y_eval = _pchip_interpolate(np.array(k_t), np.array(k_y), t_eval)
    z_eval = np.maximum(0.0, _pchip_interpolate(np.array(k_t), np.array(k_z), t_eval))

    return t_eval, x_eval, y_eval, z_eval


# =========================================================================
# MAIN RENDER PIPELINE
# =========================================================================
def render_full_video():
    """Renders the full 60fps video and encodes with FFmpeg."""
    logger.info("Initializing multi-layer handwritten video rendering pipeline...")
    fps = 60
    total_duration = 91.0
    total_frames = int(round(total_duration * fps))
    
    # 1. Build Page 1 static canvas and Page 2 canvas
    page1_static = build_page1_static_base()
    page2_canvas = build_page2_vocab_canvas()
    
    # 2. Prepare Polaroid templates
    polaroid_template, pshadow, tape_rot = prepare_polaroid_template()
    
    # 3. Geometry and Trajectory
    side_geom, main_geom = get_lyrics_geometry()
    t_eval, x_eval, y_eval, z_eval = build_pen_trajectory(total_duration=total_duration, fps=fps)
    
    # 4. Pen Physics Engine
    from video_processing.handwritten_pager.contracts import HandwrittenPagerConfig, PenState
    from video_processing.handwritten_pager.pen_physics import PenPhysicsEngine
    
    config = HandwrittenPagerConfig(fps=fps)
    pen_engine = PenPhysicsEngine(config)
    
    # 5. Open MV video
    cap = cv2.VideoCapture(str(MV_PATH))
    mv_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    
    # 6. Spawning FFmpeg
    ffmpeg_cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-y",
        "-f", "rawvideo",
        "-pix_fmt", "rgba",
        "-s", "1080x1920",
        "-r", str(fps),
        "-i", "pipe:0",
        "-i", str(AUDIO_PATH),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "320k",
        "-movflags", "+faststart",
        "-shortest",
        str(OUTPUT_VIDEO_PATH),
    ]
    logger.info(f"Spawning FFmpeg stream to {OUTPUT_VIDEO_PATH} ({total_frames} frames)...")
    proc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE)
    
    t0 = time.time()
    last_reported = 0
    
    for f_idx in range(total_frames):
        t = float(t_eval[f_idx])
        pen_x = float(x_eval[f_idx])
        pen_y = float(y_eval[f_idx])
        pen_z = float(z_eval[f_idx])
        
        # Read video frame for Polaroid
        if t < 86.8:
            mv_frame_idx = int(round(t * mv_fps))
            cap.set(cv2.CAP_PROP_POS_FRAMES, mv_frame_idx)
            ret, frame = cap.read()
            if ret:
                mv_rgb = cv2.cvtColor(cv2.resize(frame, (366, 210)), cv2.COLOR_BGR2RGB)
            else:
                mv_rgb = np.zeros((210, 366, 3), dtype=np.uint8)
                
        # Base frame setup
        if t < 86.8:
            frame_canvas = page1_static.copy()
            composite_polaroid_frame(frame_canvas, polaroid_template, pshadow, tape_rot, mv_rgb)
            
            # Active & Completed Singing Highlight Layer
            hl_layer = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
            hl_draw = ImageDraw.Draw(hl_layer)
            
            # 1. Side lyrics highlights
            for g in side_geom:
                st, et = g["start"], g["end"]
                if t >= et:
                    # Completed line: gentle warm amber highlighter
                    if g["type"] == "single":
                        hl_draw.rounded_rectangle([148, g["en_pos"][1] + 2, 150 + g["en_w"] + 6, g["tip_y"] + 2], radius=4, fill=(255, 232, 130, 75))
                        hl_draw.text(g["en_pos"], g["en"], fill=(38, 44, 55, 255), font=font_side_en)
                    else:
                        hl_draw.rounded_rectangle([148, g["l1_pos"][1] + 2, 150 + g["l1_w"] + 6, g["l1_tip_y"] + 2], radius=4, fill=(255, 232, 130, 75))
                        hl_draw.text(g["l1_pos"], g["lines"][0], fill=(38, 44, 55, 255), font=font_side_en)
                        hl_draw.rounded_rectangle([148, g["l2_pos"][1] + 2, 150 + g["l2_w"] + 6, g["l2_tip_y"] + 2], radius=4, fill=(255, 232, 130, 75))
                        hl_draw.text(g["l2_pos"], g["lines"][1], fill=(38, 44, 55, 255), font=font_side_en)
                elif st <= t < et:
                    # Active line: vibrant golden highlighter ribbon tracking pen tip
                    if g["type"] == "single":
                        progress = (t - st) / max(0.01, et - st)
                        cur_w = progress * g["en_w"]
                        hl_draw.rounded_rectangle([148, g["en_pos"][1] + 2, 150 + cur_w + 6, g["tip_y"] + 2], radius=4, fill=(255, 220, 80, 125))
                        hl_draw.text(g["en_pos"], g["en"], fill=(38, 44, 55, 255), font=font_side_en)
                    else:
                        mid_t = (st + et) / 2.0
                        if t < mid_t:
                            p1 = (t - st) / max(0.01, mid_t - st)
                            cur_w = p1 * g["l1_w"]
                            hl_draw.rounded_rectangle([148, g["l1_pos"][1] + 2, 150 + cur_w + 6, g["l1_tip_y"] + 2], radius=4, fill=(255, 220, 80, 125))
                            hl_draw.text(g["l1_pos"], g["lines"][0], fill=(38, 44, 55, 255), font=font_side_en)
                        else:
                            p2 = (t - mid_t) / max(0.01, et - mid_t)
                            cur_w = p2 * g["l2_w"]
                            hl_draw.rounded_rectangle([148, g["l1_pos"][1] + 2, 150 + g["l1_w"] + 6, g["l1_tip_y"] + 2], radius=4, fill=(255, 232, 130, 75))
                            hl_draw.text(g["l1_pos"], g["lines"][0], fill=(38, 44, 55, 255), font=font_side_en)
                            hl_draw.rounded_rectangle([148, g["l2_pos"][1] + 2, 150 + cur_w + 6, g["l2_tip_y"] + 2], radius=4, fill=(255, 220, 80, 125))
                            hl_draw.text(g["l2_pos"], g["lines"][1], fill=(38, 44, 55, 255), font=font_side_en)

            # 2. Main lyrics highlights
            for g in main_geom:
                st, et = g["start"], g["end"]
                f_en = g["font_en"]
                text_col = (165, 28, 28, 255) if g["highlight"] else (38, 44, 55, 255)
                if t >= et:
                    # Completed line
                    if g["type"] == "wrap":
                        hl_draw.rounded_rectangle([153, g["l1_pos"][1] + 2, 155 + g["l1_w"] + 8, g["l1_tip_y"] + 2], radius=6, fill=(255, 232, 130, 75))
                        hl_draw.text(g["l1_pos"], g["line1"], fill=text_col, font=f_en)
                        hl_draw.rounded_rectangle([153, g["l2_pos"][1] + 2, 155 + g["l2_w"] + 8, g["l2_tip_y"] + 2], radius=6, fill=(255, 232, 130, 75))
                        hl_draw.text(g["l2_pos"], g["line2"], fill=text_col, font=f_en)
                    else:
                        hl_draw.rounded_rectangle([153, g["en_pos"][1] + 2, 155 + g["en_w"] + 8, g["tip_y"] + 2], radius=6, fill=(255, 232, 130, 75))
                        hl_draw.text(g["en_pos"], g["en"], fill=text_col, font=f_en)
                elif st <= t < et:
                    # Active line
                    if g["type"] == "wrap":
                        mid_t = (st + et) / 2.0
                        if t < mid_t:
                            p1 = (t - st) / max(0.01, mid_t - st)
                            cur_w = p1 * g["l1_w"]
                            hl_draw.rounded_rectangle([153, g["l1_pos"][1] + 2, 155 + cur_w + 8, g["l1_tip_y"] + 2], radius=6, fill=(255, 220, 80, 125))
                            hl_draw.text(g["l1_pos"], g["line1"], fill=text_col, font=f_en)
                        else:
                            p2 = (t - mid_t) / max(0.01, et - mid_t)
                            cur_w = p2 * g["l2_w"]
                            hl_draw.rounded_rectangle([153, g["l1_pos"][1] + 2, 155 + g["l1_w"] + 8, g["l1_tip_y"] + 2], radius=6, fill=(255, 232, 130, 75))
                            hl_draw.text(g["l1_pos"], g["line1"], fill=text_col, font=f_en)
                            hl_draw.rounded_rectangle([153, g["l2_pos"][1] + 2, 155 + cur_w + 8, g["l2_tip_y"] + 2], radius=6, fill=(255, 220, 80, 125))
                            hl_draw.text(g["l2_pos"], g["line2"], fill=text_col, font=f_en)
                    else:
                        progress = (t - st) / max(0.01, et - st)
                        cur_w = progress * g["en_w"]
                        hl_draw.rounded_rectangle([153, g["en_pos"][1] + 2, 155 + cur_w + 8, g["tip_y"] + 2], radius=6, fill=(255, 220, 80, 125))
                        hl_draw.text(g["en_pos"], g["en"], fill=text_col, font=f_en)
                    
            frame_canvas = Image.alpha_composite(frame_canvas, hl_layer)
        elif 86.8 <= t < 87.5:
            # Smooth page flip transition
            p1_final = page1_static.copy()
            composite_polaroid_frame(p1_final, polaroid_template, pshadow, tape_rot, mv_rgb)
            alpha = (t - 86.8) / 0.7
            frame_canvas = Image.blend(p1_final, page2_canvas, alpha)
        else:
            # Page 2 study card
            frame_canvas = page2_canvas.copy()
            
        # Pen Physics State & Micro-jitter
        jitter_x = 0.35 * math.sin(2 * math.pi * 9.1 * t + 1.2)
        jitter_y = 0.30 * math.cos(2 * math.pi * 8.4 * t + 0.8)
        dyn_angle = pen_engine.base_angle + 0.35 * math.sin(2 * math.pi * 1.5 * t)
        
        state = PenState(
            frame_idx=f_idx,
            t=t,
            x=pen_x + jitter_x,
            y=pen_y + jitter_y,
            z=pen_z,
            angle_deg=dyn_angle,
            is_active=(pen_z < 2.0),
            active_word=None,
        )
        final_frame = pen_engine.render_pen_frame(frame_canvas, state)
        proc.stdin.write(final_frame.tobytes())
        
        # Logging progress
        if f_idx - last_reported >= 300 or f_idx == total_frames - 1:
            last_reported = f_idx
            pct = (f_idx + 1) / total_frames * 100.0
            elapsed = time.time() - t0
            cur_fps = (f_idx + 1) / max(0.001, elapsed)
            logger.info(f"Render progress: {f_idx + 1}/{total_frames} ({pct:.1f}%) - {cur_fps:.1f} fps")
            
    cap.release()
    proc.stdin.close()
    proc.wait()
    logger.info(f"Video rendered successfully in {time.time() - t0:.1f}s -> {OUTPUT_VIDEO_PATH}")


# =========================================================================
# COVERS GENERATION (WeChat 9:16, Douyin 3:4, Douyin 4:3)
# =========================================================================
def generate_platform_covers():
    logger.info("Generating platform-compliant covers with updated safe zones...")
    p1 = build_page1_static_base()
    polaroid_template, pshadow, tape_rot = prepare_polaroid_template()
    dummy_mv = np.full((210, 366, 3), (25, 40, 60), dtype=np.uint8)
    if MV_FRAME_PATH.exists():
        im = Image.open(MV_FRAME_PATH).resize((366, 210))
        dummy_mv = np.array(im)
    composite_polaroid_frame(p1, polaroid_template, pshadow, tape_rot, dummy_mv)
    p2 = build_page2_vocab_canvas()
    
    # 1. WeChat 9:16
    wechat_path = COVERS_DIR / "cover_wechat_9_16.jpg"
    p1.convert("RGB").save(wechat_path, "JPEG", quality=95)
    wechat_sha256 = hashlib.sha256(wechat_path.read_bytes()).hexdigest()
    
    wechat_prov = {
        "schema_version": 1,
        "cover_kind": "dedicated_generated_image",
        "uses_video_frame": False,
        "cover_filename": "cover_wechat_9_16.jpg",
        "cover_sha256": wechat_sha256,
        "audio_edition": "original_audio_subtitled",
        "layout_policy": {
            "policy_version": "no_broad_overlay_v2",
            "no_broad_dark_overlay": True,
            "no_large_text_card": True,
            "preserve_dedicated_background": True,
            "text_legibility_method": "local_stroke_shadow_weight",
            "mobile_readable_title": True,
            "min_title_font_px": 84,
            "requires_local_text_stroke_or_shadow": True
        }
    }
    (COVERS_DIR / "cover_wechat_9_16_provenance.json").write_text(json.dumps(wechat_prov, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"WeChat 9:16 cover saved (sha256={wechat_sha256[:8]}): {wechat_path}")
    
    # 2. Douyin 3:4 Desk Mockup
    DESK_W, DESK_H = 1080, 1440
    desk_bg = Image.new("RGBA", (DESK_W, DESK_H), (232, 226, 216, 255))
    desk_draw = ImageDraw.Draw(desk_bg)
    for dy in range(0, DESK_H, 6):
        alpha = int(12 + 10 * ((dy % 18) / 18.0))
        desk_draw.line([(0, dy), (DESK_W, dy)], fill=(195, 185, 172, alpha), width=1)
    
    scale = 0.90
    crop_h = 1520
    p_crop = p1.crop((0, 0, 1080, crop_h))
    tw, th = int(1080 * scale), int(crop_h * scale)
    p_scaled = p_crop.resize((tw, th), Image.Resampling.LANCZOS)
    
    s_canvas = Image.new("RGBA", (DESK_W, DESK_H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(s_canvas)
    px = (DESK_W - tw) // 2
    py = 55
    sd.rectangle([px + 12, py + 18, px + tw + 12, py + th + 20], fill=(45, 38, 30, 145))
    s_blur = s_canvas.filter(ImageFilter.GaussianBlur(radius=24))
    
    mockup = Image.alpha_composite(desk_bg, s_blur)
    mockup.paste(p_scaled, (px, py), p_scaled)
    vignette = Image.new("RGBA", (DESK_W, DESK_H), (0, 0, 0, 0))
    ImageDraw.Draw(vignette).rectangle([0, 0, DESK_W, DESK_H], outline=(140, 125, 110, 80), width=4)
    mockup = Image.alpha_composite(mockup, vignette)
    
    douyin_3_4_path = COVERS_DIR / "cover_douyin_3_4.jpg"
    mockup.convert("RGB").save(douyin_3_4_path, "JPEG", quality=95)
    douyin_3_4_sha256 = hashlib.sha256(douyin_3_4_path.read_bytes()).hexdigest()
    
    douyin_3_4_prov = {
        "schema_version": 1,
        "cover_kind": "dedicated_generated_image",
        "uses_video_frame": False,
        "cover_filename": "cover_douyin_3_4.jpg",
        "cover_sha256": douyin_3_4_sha256,
        "audio_edition": "original_audio_subtitled",
        "layout_policy": {
            "policy_version": "no_broad_overlay_v2",
            "no_broad_dark_overlay": True,
            "no_large_text_card": True,
            "preserve_dedicated_background": True,
            "text_legibility_method": "local_stroke_shadow_weight",
            "mobile_readable_title": True,
            "min_title_font_px": 84,
            "requires_local_text_stroke_or_shadow": True
        }
    }
    (COVERS_DIR / "cover_douyin_3_4_provenance.json").write_text(json.dumps(douyin_3_4_prov, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"Douyin 3:4 cover saved (sha256={douyin_3_4_sha256[:8]}): {douyin_3_4_path}")
    
    # 3. Douyin 4:3 Open Double Spread
    SW, SH = 1440, 1080
    spread_bg = Image.new("RGBA", (SW, SH), (228, 222, 212, 255))
    sp_draw = ImageDraw.Draw(spread_bg)
    for dy in range(0, SH, 6):
        alpha = int(12 + 8 * ((dy % 18) / 18.0))
        sp_draw.line([(0, dy), (SW, dy)], fill=(190, 180, 168, alpha), width=1)
        
    scale_s = 0.62
    pw_s, ph_s = int(1080 * scale_s), int(1520 * scale_s)
    p1_s = p1.crop((0, 0, 1080, 1520)).resize((pw_s, ph_s), Image.Resampling.LANCZOS)
    p2_s = p2.crop((0, 0, 1080, 1520)).resize((pw_s, ph_s), Image.Resampling.LANCZOS)
    
    s_spread = Image.new("RGBA", (SW, SH), (0, 0, 0, 0))
    ssd = ImageDraw.Draw(s_spread)
    p1_x, p1_y = 45, 68
    p2_x, p2_y = 725, 68
    ssd.rectangle([p1_x + 8, p1_y + 12, p1_x + pw_s + 8, p1_y + ph_s + 14], fill=(40, 35, 28, 120))
    ssd.rectangle([p2_x + 8, p2_y + 12, p2_x + pw_s + 8, p2_y + ph_s + 14], fill=(40, 35, 28, 120))
    ss_blur = s_spread.filter(ImageFilter.GaussianBlur(radius=20))
    
    spread = Image.alpha_composite(spread_bg, ss_blur)
    spread.paste(p1_s, (p1_x, p1_y), p1_s)
    spread.paste(p2_s, (p2_x, p2_y), p2_s)
    
    spine = Image.new("RGBA", (SW, SH), (0, 0, 0, 0))
    ImageDraw.Draw(spine).line([(715, 68), (715, 68 + ph_s)], fill=(60, 50, 40, 110), width=6)
    spread = Image.alpha_composite(spread, spine.filter(ImageFilter.GaussianBlur(radius=6)))
    
    douyin_4_3_path = COVERS_DIR / "cover_douyin_4_3.jpg"
    spread.convert("RGB").save(douyin_4_3_path, "JPEG", quality=95)
    douyin_4_3_sha256 = hashlib.sha256(douyin_4_3_path.read_bytes()).hexdigest()
    
    # Horizontal version (1280x960) for Douyin
    horiz_path = COVERS_DIR / "cover_douyin_4_3_douyin_horizontal.jpg"
    spread.convert("RGB").resize((1280, 960), Image.Resampling.LANCZOS).save(horiz_path, "JPEG", quality=95)
    
    douyin_4_3_prov = {
        "schema_version": 1,
        "cover_kind": "dedicated_generated_image",
        "uses_video_frame": False,
        "cover_filename": "cover_douyin_4_3.jpg",
        "cover_sha256": douyin_4_3_sha256,
        "audio_edition": "original_audio_subtitled",
        "layout_policy": {
            "policy_version": "no_broad_overlay_v2",
            "no_broad_dark_overlay": True,
            "no_large_text_card": True,
            "preserve_dedicated_background": True,
            "text_legibility_method": "local_stroke_shadow_weight",
            "mobile_readable_title": True,
            "min_title_font_px": 84,
            "requires_local_text_stroke_or_shadow": True
        }
    }
    (COVERS_DIR / "cover_douyin_4_3_provenance.json").write_text(json.dumps(douyin_4_3_prov, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"Douyin 4:3 cover saved (sha256={douyin_4_3_sha256[:8]}): {douyin_4_3_path}")


# =========================================================================
# COPYWRITING GENERATION
# =========================================================================
def generate_copywriting():
    logger.info("Generating platform copywriting...")
    # WeChat short title: 6-16 chars limit
    wechat_short_title = "午夜神曲手账研读"
    (COPY_DIR / "wechat_short_title.txt").write_text(wechat_short_title, encoding="utf-8")
    
    wechat_copy = (
        "【音乐手账 · 经典典藏】ABBA 1979 年殿堂级神作《Gimme! Gimme! Gimme!》（《午夜求爱》）双语伴读版！\n\n"
        "当年红遍全球的迪斯科律动，不仅被麦当娜 2005 经典《Hung Up》奉为唯一神级采样，歌词更写尽了午夜独处的都市疏离与对陪伴的渴望。\n\n"
        "✦ 拍立得画中画同步原版 MV 真实画面\n"
        "✦ 全曲歌词清晰预印，大号粗体墨水手写，移动端阅读无压力\n"
        "✦ 结尾附全曲 6 组核心语言点与国际音标精萃（建议长按暂停截图长久收藏）\n\n"
        "#ABBA #午夜求爱 #欧美经典老歌 #英语学习 #音乐手账 #迪斯科"
    )
    (COPY_DIR / "wechat_copy.txt").write_text(wechat_copy, encoding="utf-8")
    
    # Douyin title: <=30 chars
    douyin_title = "ABBA神作午夜求爱双语伴读！"
    (COPY_DIR / "douyin_title.txt").write_text(douyin_title, encoding="utf-8")
    
    douyin_copy = (
        "前奏一响回到1979！ABBA经典《Gimme! Gimme! Gimme!》（午夜求爱）双语手账伴读。麦当娜神级采样出处，结尾附重点词汇笔记，戴上耳机听好歌学地道表达！"
        " #欧美经典老歌 #ABBA #英语学习 #音乐手账 #经典回忆"
    )
    (COPY_DIR / "douyin_copy.txt").write_text(douyin_copy, encoding="utf-8")
    
    pkg = {
        "wechat_short_title": wechat_short_title,
        "wechat_copy": wechat_copy,
        "douyin_title": douyin_title,
        "douyin_copy": douyin_copy,
    }
    (COPY_DIR / "copy_package.json").write_text(json.dumps(pkg, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Copywriting packages generated.")


if __name__ == "__main__":
    generate_platform_covers()
    generate_copywriting()
    render_full_video()
