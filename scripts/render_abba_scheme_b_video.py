#!/usr/bin/env python3
"""Render formal video for ABBA - Gimme! Gimme! Gimme! (Scheme B v2).

Features:
1. Scheme B (v2) handwritten notebook canvas (zero overlap, 44px Noteworthy Bold, 32px TianYingZhang).
2. Polaroid PiP playing official 1979 MV synchronized with audio.
3. Natural pen physics dynamics & realistic dual shadow.
4. Seamless 0.7s page flip to the 3-second Ending Study Card Page (P2/2 - 全曲语言点精萃).
5. Output 1080x1920 60fps H.264 + AAC 320k.
6. Generates WeChat 9:16, Douyin 3:4, and Douyin 4:3 covers.
7. Generates platform copywriting packages.

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-09 | Antigravity | ABBA《Gimme! Gimme! Gimme!》方案B(v2)母带渲染器：拍立得画中画同步MV、零重叠粗墨手写、终曲研读卡翻页。 |
"""

import cv2
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

AUDIO_PATH = WORK_DIR / "audio_trimmed.wav"
MV_PATH = WORK_DIR / "mv_pip.mp4"
OUTPUT_VIDEO_PATH = WORK_DIR / "gimme_full_handwritten_pager.mp4"

# Assets
ASSETS_DIR = PROJECT_ROOT / "src/video_processing/handwritten_pager/assets"
PAPER_PATH = ASSETS_DIR / "paper_texture_ivory.jpg"
PEN_PATH = ASSETS_DIR / "pen_ballpoint_photorealistic.png"
LOGO_PATH = PROJECT_ROOT / "assets/brand/01_logos/concept_a.png"

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

font_brand = load_font(FONT_SANS, 24)
font_slogan = load_font(FONT_SANS, 20)
font_title_en = load_font(FONT_EN_NOTEWORTHY, 36, index=1)
font_title_zh = load_font(FONT_ZH_CALLIGRAPHY, 28)
font_subtitle = load_font(FONT_SANS, 20)

font_lyrics_en_large = load_font(FONT_EN_NOTEWORTHY, 44, index=1)
font_lyrics_zh_large = load_font(FONT_ZH_CALLIGRAPHY, 32)
font_side_en = load_font(FONT_EN_NOTEWORTHY, 32, index=1)
font_side_zh = load_font(FONT_ZH_CALLIGRAPHY, 24)

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

def get_clean_logo(size=50):
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

def build_page1_static_base():
    """Builds the static base canvas for Page 1 (header, margins, holes, divider lines)."""
    canvas = get_base_paper()
    draw = ImageDraw.Draw(canvas)
    draw_notebook_holes(draw, y_start=60, y_end=1880, step=110)
    
    # 1. Top Brand Header
    logo = get_clean_logo(48)
    canvas.paste(logo, (145, 30), logo)
    draw.text((210, 34), "六维时空号", fill=(35, 40, 50, 240), font=font_brand)
    draw.line([(345, 40), (345, 66)], fill=(180, 170, 160, 180), width=2)
    draw.text((365, 39), "“不同的视角，看见更大的世界。”", fill=(130, 95, 45, 220), font=font_slogan)
    draw_mixed_text(draw, (790, 39), "✎ 音乐手账 · 经典典藏 (P1/2)", load_font(FONT_ZH_CALLIGRAPHY, 20), font_slogan, (110, 115, 125, 210))
    
    # Song Title Row
    draw.text((150, 92), "Gimme! Gimme! Gimme!", fill=(140, 30, 30, 255), font=font_title_en)
    title_w = draw.textlength("Gimme! Gimme! Gimme!", font=font_title_en)
    zh_box_x = int(150 + title_w + 18)
    draw.rounded_rectangle([zh_box_x, 95, zh_box_x + 155, 133], radius=6, fill=(245, 228, 175, 240), outline=(215, 165, 55, 200), width=1)
    draw_mixed_text(draw, (zh_box_x + 10, 98), "《午夜求爱》", font_title_zh, load_font(FONT_SANS, 22), (70, 45, 15, 255))
    
    act_box_x = zh_box_x + 170
    draw.rounded_rectangle([act_box_x, 95, act_box_x + 195, 133], radius=6, fill=(250, 240, 230, 220), outline=(190, 120, 70, 180), width=1)
    draw_mixed_text(draw, (act_box_x + 10, 101), "【第一幕 · 孤影独白】", font_title_zh, load_font(FONT_SANS, 20), (140, 60, 30, 240))
    
    draw_mixed_text(draw, (150, 145), "原唱：ABBA (1979)  ·  Agnetha Faltskog 主唱  ·  全曲双语伴读", load_font(FONT_ZH_CALLIGRAPHY, 20), font_subtitle, (100, 105, 115, 230))
    draw.line([(150, 176), (1020, 176)], fill=(220, 210, 195, 180), width=1)
    draw.line([(150, 665), (1020, 665)], fill=(220, 210, 195, 180), width=1)
    
    # Footer
    draw_mixed_text(draw, (155, 1852), "• 本幕完 · 翻页进入下一乐段 »", load_font(FONT_ZH_CALLIGRAPHY, 20), load_font(FONT_ARIAL_UNICODE, 20), (130, 125, 120, 220))
    draw.text((850, 1852), "ABBA · 1979 POLAR", fill=(170, 160, 150, 200), font=load_font(FONT_SANS, 18))
    
    return canvas

def build_page2_vocab_canvas():
    """Builds the 3-second Ending Study Card Page (P2/2 - 全曲语言点精萃)."""
    canvas = get_base_paper()
    draw = ImageDraw.Draw(canvas)
    draw_notebook_holes(draw, y_start=60, y_end=1880, step=110)
    
    logo = get_clean_logo(52)
    canvas.paste(logo, (145, 30), logo)
    draw.text((215, 34), "六维时空号", fill=(35, 40, 50, 240), font=font_brand)
    draw.line([(355, 40), (355, 66)], fill=(180, 170, 160, 180), width=2)
    draw.text((375, 39), "“不同的视角，看见更大的世界。”", fill=(130, 95, 45, 220), font=font_slogan)
    draw_mixed_text(draw, (770, 39), "✎ 音乐手账 · 终章附录 (P2/2)", load_font(FONT_ZH_CALLIGRAPHY, 20), font_slogan, (110, 115, 125, 210))
    
    draw.text((150, 92), "Gimme! Gimme! Gimme!", fill=(140, 30, 30, 255), font=font_title_en)
    title_w = draw.textlength("Gimme! Gimme! Gimme!", font=font_title_en)
    zh_box_x = int(150 + title_w + 18)
    draw.rounded_rectangle([zh_box_x, 95, zh_box_x + 155, 133], radius=6, fill=(245, 228, 175, 240), outline=(215, 165, 55, 200), width=1)
    draw_mixed_text(draw, (zh_box_x + 10, 98), "《午夜求爱》", font_title_zh, load_font(FONT_SANS, 22), (70, 45, 15, 255))
    
    act_box_x = zh_box_x + 170
    draw.rounded_rectangle([act_box_x, 95, act_box_x + 220, 133], radius=6, fill=(240, 245, 255, 240), outline=(130, 170, 220, 200), width=1)
    draw_mixed_text(draw, (act_box_x + 10, 101), "【全曲重点语言点精萃】", font_title_zh, load_font(FONT_SANS, 20), (30, 80, 140, 240))
    
    draw_mixed_text(draw, (150, 145), "策展手记：在 1979 迪斯科不朽律动中，品味最地道生动的文学英语表达", load_font(FONT_ZH_CALLIGRAPHY, 21), font_subtitle, (110, 85, 45, 230))
    draw.line([(150, 178), (1020, 178)], fill=(220, 210, 195, 180), width=2)
    
    card_w, card_h = 880, 1580
    card_bg = Image.new("RGBA", (card_w, card_h), (254, 250, 242, 255))
    cd = ImageDraw.Draw(card_bg)
    cd.rounded_rectangle([0, 0, card_w - 2, card_h - 2], radius=16, fill=(254, 250, 242, 255), outline=(215, 175, 100, 220), width=2)
    cd.rounded_rectangle([25, 25, card_w - 25, 80], radius=8, fill=(245, 230, 190, 230))
    draw_mixed_text(cd, (40, 36), "◆ 本曲核心词汇与地道修辞深度解析（建议长按暂停截图收藏）", load_font(FONT_SANS, 23), load_font(FONT_SANS, 23), (130, 50, 20, 255))
    
    vocab_entries = [
        {"word": "flat", "ipa": "/flæt/", "pos": "n.", "def": "英式英语中的“公寓/套房”（美式为 apartment）", "note": "• 语境精析：源自古诺尔斯语，特指在一栋建筑内独占一整层的居住单元。歌词中'in my flat all alone'写尽了城市单身青年独居的疏离与孤寂感。"},
        {"word": "on one's own", "ipa": "/ɒn wʌnz əʊn/", "pos": "phr.", "def": "独自一人，孤立无援", "note": "• 辨析：不同于中性的 alone，'on my own'强烈突显'无人伸出援手、独自苦苦支撑'的情感色彩。例句：How I hate to spend the evening on my own!（我多讨厌独自熬过漫漫长夜！）"},
        {"word": "gloom", "ipa": "/ɡluːm/", "pos": "n.", "def": "幽暗，昏暗；引申为“压抑、沮丧的心境”", "note": "• 词源引申：与 gleam（微光）同源但走向相反，表光明被完全吞噬的绝望感。在文学中常借物理上的昏暗天色，映照人物内心被虚空笼罩的阴郁。"},
        {"word": "chase the shadows away", "ipa": "/tʃeɪs ðə ˈʃædəʊz əˈweɪ/", "pos": "idiom.", "def": "驱散心头的阴影与恐惧", "note": "• 修辞：拟人隐喻修辞法。将深夜独处的恐惧与胡思乱想具象化为'潜伏的阴影'（shadows），而真诚的爱与陪伴则是驱散这些暗影的唯一日光。"},
        {"word": "not a soul", "ipa": "/nɒt ə səʊl/", "pos": "idiom.", "def": "连一个人都没有", "note": "• 文学提炼：以 soul（灵魂）借代 living person（活人），源自戏剧与诗歌传统。四下万籁俱寂，连一个具有生命温度的灵魂都寻觅不到，道尽极致孤独。"},
        {"word": "break of the day", "ipa": "/breɪk əv ðə deɪ/", "pos": "phr.", "def": "拂晓时分，黎明破晓之际", "note": "• 意象：等同于 daybreak 或 dawn。黑夜终会破裂，光明必将透入。表达在绝境中对新生、清醒与黎明的坚韧守望。"},
    ]
    font_ipa = load_font(FONT_ARIAL_UNICODE, 22)
    font_entry_zh = load_font(FONT_ZH_CALLIGRAPHY, 25)
    font_entry_note = load_font(FONT_ZH_CALLIGRAPHY, 23)
    
    vy = 110
    for item in vocab_entries:
        w_text = f"【{item['word']}】"
        draw_mixed_text(cd, (30, vy), w_text, load_font(FONT_EN_NOTEWORTHY, 32, index=1), load_font(FONT_SANS, 26), (160, 30, 30, 255))
        w_len = cd.textlength(w_text, font=load_font(FONT_EN_NOTEWORTHY, 32, index=1))
        cd.text((30 + w_len + 10, vy + 4), item["ipa"], fill=(25, 75, 140, 240), font=font_ipa)
        ipa_len = cd.textlength(item["ipa"], font=font_ipa)
        pos_def = f"   {item['pos']}   {item['def']}"
        draw_mixed_text(cd, (30 + w_len + 10 + ipa_len, vy + 4), pos_def, font_entry_zh, font_ipa, (40, 50, 65, 240))
        draw_mixed_text(cd, (35, vy + 48), item["note"], font_entry_note, load_font(FONT_SANS, 20), (105, 95, 85, 230))
        cd.line([(30, vy + 125), (card_w - 30, vy + 125)], fill=(225, 215, 200, 180), width=1)
        vy += 140
    
    cd.rounded_rectangle([30, vy + 15, card_w - 30, vy + 130], radius=10, fill=(242, 246, 252, 255), outline=(170, 195, 230, 200), width=1)
    draw_mixed_text(cd, (45, vy + 28), "★ 乐史典故与采样回响（Cultural Legacy & Sampling）：", load_font(FONT_SANS, 22), load_font(FONT_SANS, 22), (25, 80, 150, 255))
    sampling_text = "Benny 在 ARP 合成器上写出的前奏被誉为流行乐史神级 Riff。2005 年麦当娜为单曲《Hung Up》亲自致信 ABBA 恳请采样授权，最终横扫全球 41 国单曲榜冠军，跨越四分之一世纪再度封神。"
    draw_mixed_text(cd, (45, vy + 68), sampling_text, load_font(FONT_ZH_CALLIGRAPHY, 24), load_font(FONT_SANS, 21), (70, 75, 85, 230))
    
    canvas.paste(card_bg, (145, 205), card_bg)
    draw.text((155, 1850), "✎ 研读完毕 · 关注六维时空号，戴上耳机与好歌同行", fill=(140, 135, 130, 220), font=load_font(FONT_SANS, 20))
    draw.text((800, 1850), "COSMIC EYE ARCHIVE", fill=(170, 160, 150, 200), font=load_font(FONT_SANS, 18))
    return canvas

def prepare_polaroid_template():
    """Builds static elements of Polaroid frame (shadow, borders, text, washi tape)."""
    p_w, p_h = 490, 390
    polaroid = Image.new("RGBA", (p_w, p_h), (255, 253, 248, 255))
    pd = ImageDraw.Draw(polaroid)
    pd.rectangle([0, 0, p_w - 1, p_h - 1], outline=(210, 200, 190, 220), width=1)
    pd.text((18, 326), "Agnetha @ Polar Studio 1979", fill=(70, 75, 85, 220), font=load_font(FONT_EN_NOTEWORTHY, 24, index=1))
    pd.text((350, 332), "● Official MV", fill=(160, 50, 50, 220), font=load_font(FONT_SANS, 16))
    
    # Shadow mask
    dummy_rot = polaroid.rotate(-2.0, expand=True, resample=Image.Resampling.BILINEAR)
    pshadow = Image.new("RGBA", dummy_rot.size, (0, 0, 0, 0))
    for x in range(0, dummy_rot.width, 2):
        for y in range(0, dummy_rot.height, 2):
            if dummy_rot.getpixel((x, y))[3] > 40:
                pshadow.putpixel((x, y), (35, 30, 25, 110))
    pshadow = pshadow.filter(ImageFilter.GaussianBlur(radius=10))
    
    # Tape
    tape = Image.new("RGBA", (140, 36), (235, 205, 130, 190))
    ImageDraw.Draw(tape).line([(0, 0), (140, 0)], fill=(255, 255, 255, 80), width=1)
    tape_rot = tape.rotate(-2.0, expand=True)
    
    return polaroid, pshadow, tape_rot

def composite_polaroid_frame(canvas: Image.Image, polaroid_template: Image.Image, pshadow: Image.Image, tape_rot: Image.Image, mv_rgb_frame: np.ndarray):
    """Pastes the current MV video frame into the Polaroid and onto the canvas."""
    px_pos, py_pos = 525, 182
    p = polaroid_template.copy()
    im_frame = Image.fromarray(mv_rgb_frame).resize((466, 296), Image.Resampling.BILINEAR)
    p.paste(im_frame, (12, 12))
    p_rot = p.rotate(-2.0, expand=True, resample=Image.Resampling.BILINEAR)
    
    canvas.paste(pshadow, (px_pos + 8, py_pos + 10), pshadow)
    canvas.paste(p_rot, (px_pos, py_pos), p_rot)
    canvas.paste(tape_rot, (px_pos + 150, py_pos - 12), tape_rot)


# =========================================================================
# LYRIC DATA SPECIFICATION WITH PRECISE TIMESTAMPS
# =========================================================================
def get_lyrics_schedule():
    """Returns scheduled lyric units with precise word timestamps and layout positions."""
    side_lyrics = [
        {"type": "single", "en": "Half past twelve,", "zh": "午夜时分孤身一人，", "start": 35.76, "end": 37.46},
        {"type": "single", "en": "Watching the late show", "zh": "独看深夜电视节目，", "start": 37.46, "end": 39.34},
        {"type": "single", "en": "In my flat all alone.", "zh": "空荡寓所寂寥无声。", "start": 39.60, "end": 41.40},
        {"type": "double", "lines": ["How I hate to spend", "the evening on my own!"], "zh": "我多讨厌独自熬过漫漫长夜！", "start": 41.52, "end": 45.34},
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


# =========================================================================
# PEN TRAJECTORY INTERPOLATOR
# =========================================================================
def build_pen_trajectory(total_duration=91.0, fps=60):
    """Builds realistic pen motion path keyframes across all musical sections."""
    side_lyrics, main_lyrics = get_lyrics_schedule()
    
    keyframes = []  # (t, x, y, z)
    
    # 0.0s ~ 35.0s: Synthesizer intro hover
    keyframes.append((0.0, 480.0, 220.0, 25.0))
    keyframes.append((10.0, 490.0, 215.0, 22.0))
    keyframes.append((20.0, 475.0, 225.0, 20.0))
    keyframes.append((30.0, 320.0, 210.0, 16.0))
    keyframes.append((35.0, 160.0, 210.0, 6.0))
    
    # Measure side lyrics
    im_dummy = ImageDraw.Draw(Image.new("RGBA", (100, 100)))
    dy = 185
    for item in side_lyrics:
        st = item["start"]
        et = item["end"]
        if item["type"] == "single":
            en = item["en"]
            w_len = im_dummy.textlength(en, font=font_side_en)
            b_en = im_dummy.textbbox((150, dy), en, font=font_side_en)
            tip_y = b_en[3] + 4
            keyframes.append((st, 150.0, tip_y, 0.0))
            keyframes.append((et, 150.0 + w_len, tip_y, 0.0))
            # inter-line lift
            zh_y = b_en[3] + 12
            b_zh = im_dummy.textbbox((150, zh_y), item["zh"], font=font_side_zh)
            dy = b_zh[3] + 16
            keyframes.append((et + 0.12, 150.0 + w_len + 15.0, tip_y - 10.0, 8.0))
        else:
            l1, l2 = item["lines"]
            w1 = im_dummy.textlength(l1, font=font_side_en)
            b1 = im_dummy.textbbox((150, dy), l1, font=font_side_en)
            tip_y1 = b1[3] + 4
            keyframes.append((st, 150.0, tip_y1, 0.0))
            mid_t = (st + et) / 2.0
            keyframes.append((mid_t - 0.05, 150.0 + w1, tip_y1, 0.0))
            
            l2_y = b1[3] + 6
            w2 = im_dummy.textlength(l2, font=font_side_en)
            b2 = im_dummy.textbbox((150, l2_y), l2, font=font_side_en)
            tip_y2 = b2[3] + 4
            keyframes.append((mid_t + 0.05, 150.0, tip_y2, 0.0))
            keyframes.append((et, 150.0 + w2, tip_y2, 0.0))
            
            zh_y = b2[3] + 12
            b_zh = im_dummy.textbbox((150, zh_y), item["zh"], font=font_side_zh)
            dy = b_zh[3] + 16
            keyframes.append((et + 0.15, 150.0 + w2 + 15.0, tip_y2 - 12.0, 10.0))

    # Move from side section to main lyrics section (t ~ 45.4s)
    cy = 685
    for item in main_lyrics:
        st = item["start"]
        et = item["end"]
        if item["type"] == "wrap":
            l1 = item["line1"]
            l2 = item["line2"]
            w1 = im_dummy.textlength(l1, font=font_lyrics_en_large)
            b1 = im_dummy.textbbox((155, cy), l1, font=font_lyrics_en_large)
            tip_y1 = b1[3] + 4
            keyframes.append((st, 155.0, tip_y1, 0.0))
            
            mid_t = (st + et) / 2.0
            keyframes.append((mid_t - 0.08, 155.0 + w1, tip_y1, 0.0))
            
            line2_y = b1[3] + 8
            w2 = im_dummy.textlength(l2, font=font_lyrics_en_large)
            b2 = im_dummy.textbbox((155, line2_y), l2, font=font_lyrics_en_large)
            tip_y2 = b2[3] + 4
            keyframes.append((mid_t + 0.08, 155.0, tip_y2, 0.0))
            keyframes.append((et, 155.0 + w2, tip_y2, 0.0))
            
            zh_y = b2[3] + 22
            b_zh = im_dummy.textbbox((155, zh_y), item["zh"], font=font_lyrics_zh_large)
            cy = b_zh[3] + 18
            keyframes.append((et + 0.15, 155.0 + w2 + 25.0, tip_y2 - 15.0, 12.0))
        else:
            en = item["en"]
            w_len = im_dummy.textlength(en, font=font_lyrics_en_large)
            b_en = im_dummy.textbbox((155, cy), en, font=font_lyrics_en_large)
            tip_y = b_en[3] + 4
            keyframes.append((st, 155.0, tip_y, 0.0))
            keyframes.append((et, 155.0 + w_len, tip_y, 0.0))
            
            zh_y = b_en[3] + 22
            b_zh = im_dummy.textbbox((155, zh_y), item["zh"], font=font_lyrics_zh_large)
            cy = b_zh[3] + 18
            keyframes.append((et + 0.15, 155.0 + w_len + 25.0, tip_y - 15.0, 12.0))
            
    # Page flip transition at 86.8s ~ 87.5s: Pen lifts high
    keyframes.append((85.5, 920.0, 1750.0, 18.0))
    keyframes.append((86.8, 600.0, 1000.0, 35.0))
    keyframes.append((87.5, 960.0, 1780.0, 15.0))
    keyframes.append((91.0, 960.0, 1780.0, 15.0))
    
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
    
    # Linear/Hermite interpolation
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
    
    # 3. Trajectory
    t_eval, x_eval, y_eval, z_eval = build_pen_trajectory(total_duration=total_duration, fps=fps)
    
    # 4. Pen Physics Engine
    import sys
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
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
    
    side_lyrics, main_lyrics = get_lyrics_schedule()
    
    # Accumulator layer for written lyrics on Page 1
    lyrics_layer = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    lyr_draw = ImageDraw.Draw(lyrics_layer)
    
    t0 = time.time()
    last_reported = 0
    
    for f_idx in range(total_frames):
        t = float(t_eval[f_idx])
        pen_x = float(x_eval[f_idx])
        pen_y = float(y_eval[f_idx])
        pen_z = float(z_eval[f_idx])
        
        # Read video frame
        if t < 86.8:
            mv_frame_idx = int(round(t * mv_fps))
            cap.set(cv2.CAP_PROP_POS_FRAMES, mv_frame_idx)
            ret, frame = cap.read()
            if ret:
                mv_rgb = cv2.cvtColor(cv2.resize(frame, (466, 296)), cv2.COLOR_BGR2RGB)
            else:
                mv_rgb = np.zeros((296, 466, 3), dtype=np.uint8)
        
        # Determine active lyrics to draw onto lyrics_layer
        # Side lyrics
        dy = 185
        for item in side_lyrics:
            st = item["start"]
            et = item["end"]
            if item["type"] == "single":
                en = item["en"]
                b_en = lyr_draw.textbbox((150, dy), en, font=font_side_en)
                zh_y = b_en[3] + 12
                b_zh = lyr_draw.textbbox((150, zh_y), item["zh"], font=font_side_zh)
                if t >= st:
                    # Draw English
                    color_en = (150, 35, 35, 255) if "Half" in en else (35, 40, 50, 245)
                    lyr_draw.text((150, dy), en, fill=color_en, font=font_side_en)
                    # Draw Chinese
                    draw_mixed_text(lyr_draw, (150, zh_y), item["zh"], font_side_zh, load_font(FONT_SANS, 21), (55, 50, 45, 245))
                dy = b_zh[3] + 16
            else:
                l1, l2 = item["lines"]
                b1 = lyr_draw.textbbox((150, dy), l1, font=font_side_en)
                l2_y = b1[3] + 6
                b2 = lyr_draw.textbbox((150, l2_y), l2, font=font_side_en)
                zh_y = b2[3] + 12
                b_zh = lyr_draw.textbbox((150, zh_y), item["zh"], font=font_side_zh)
                if t >= st:
                    lyr_draw.text((150, dy), l1, fill=(35, 40, 50, 245), font=font_side_en)
                if t >= st + 1.8:
                    lyr_draw.text((150, l2_y), l2, fill=(35, 40, 50, 245), font=font_side_en)
                    draw_mixed_text(lyr_draw, (150, zh_y), item["zh"], font_side_zh, load_font(FONT_SANS, 21), (55, 50, 45, 245))
                dy = b_zh[3] + 16
                
        # Main lyrics
        cy = 685
        for item in main_lyrics:
            st = item["start"]
            et = item["end"]
            is_hl = item["highlight"]
            color_en = (165, 28, 28, 255) if is_hl else (25, 30, 40, 250)
            color_zh = (45, 40, 35, 255)
            
            if item["type"] == "wrap":
                l1 = item["line1"]
                l2 = item["line2"]
                b1 = lyr_draw.textbbox((155, cy), l1, font=font_lyrics_en_large)
                line2_y = b1[3] + 8
                b2 = lyr_draw.textbbox((155, line2_y), l2, font=font_lyrics_en_large)
                zh_y = b2[3] + 22
                b_zh = lyr_draw.textbbox((155, zh_y), item["zh"], font=font_lyrics_zh_large)
                
                mid_t = (st + et) / 2.0
                if t >= st:
                    lyr_draw.text((155, cy), l1, fill=color_en, font=font_lyrics_en_large)
                if t >= mid_t:
                    lyr_draw.text((155, line2_y), l2, fill=color_en, font=font_lyrics_en_large)
                    draw_mixed_text(lyr_draw, (155, zh_y), item["zh"], font_lyrics_zh_large, load_font(FONT_SANS, 26), color_zh)
                cy = b_zh[3] + 18
            else:
                en = item["en"]
                b_en = lyr_draw.textbbox((155, cy), en, font=font_lyrics_en_large)
                zh_y = b_en[3] + 22
                b_zh = lyr_draw.textbbox((155, zh_y), item["zh"], font=font_lyrics_zh_large)
                if t >= st:
                    lyr_draw.text((155, cy), en, fill=color_en, font=font_lyrics_en_large)
                    draw_mixed_text(lyr_draw, (155, zh_y), item["zh"], font_lyrics_zh_large, load_font(FONT_SANS, 26), color_zh)
                cy = b_zh[3] + 18
        
        # Frame Compositing
        if t < 86.8:
            frame_canvas = page1_static.copy()
            composite_polaroid_frame(frame_canvas, polaroid_template, pshadow, tape_rot, mv_rgb)
            frame_canvas.paste(lyrics_layer, (0, 0), lyrics_layer)
        elif 86.8 <= t < 87.5:
            # Smooth page flip transition
            p1_final = page1_static.copy()
            composite_polaroid_frame(p1_final, polaroid_template, pshadow, tape_rot, mv_rgb)
            p1_final.paste(lyrics_layer, (0, 0), lyrics_layer)
            alpha = (t - 86.8) / 0.7
            frame_canvas = Image.blend(p1_final, page2_canvas, alpha)
        else:
            # Page 2 study card
            frame_canvas = page2_canvas.copy()
            
        # Pen Physics State
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
    logger.info("Generating platform-compliant covers...")
    # Use the finalized static Page 1 image
    from scripts.generate_abba_scheme_b_v2 import build_scheme_b_lyrics_page, build_scheme_b_vocab_end_page
    p1 = build_scheme_b_lyrics_page()
    p2 = build_scheme_b_vocab_end_page()
    
    # 1. WeChat 9:16
    wechat_path = COVERS_DIR / "cover_wechat_9_16.jpg"
    p1.convert("RGB").save(wechat_path, "JPEG", quality=95)
    logger.info(f"WeChat 9:16 cover: {wechat_path}")
    
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
    logger.info(f"Douyin 3:4 cover: {douyin_3_4_path}")
    
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
    logger.info(f"Douyin 4:3 cover: {douyin_4_3_path}")


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
        "✦ 44px 特大粗体墨水手写，移动端阅读无压力\n"
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
