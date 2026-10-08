#!/usr/bin/env python3
"""Generate Page 1 preview for David Kushner - Daylight."""

import json
from pathlib import Path
from PIL import Image, ImageDraw

from video_processing.handwritten_pager.canvas_builder import CanvasBuilder, is_cjk
from video_processing.handwritten_pager.contracts import HandwrittenPagerConfig

PROJECT_ROOT = Path(__file__).resolve().parent.parent
work_dir = PROJECT_ROOT / "output/handwritten_pager/daylight"
work_dir.mkdir(parents=True, exist_ok=True)

# 1. Page 1 lyrics (Verse 1, Lines 1 to 6)
page1_lyrics = [
    {
        "en": "Telling myself I won't go there",
        "zh": "告诫自己不可深陷其中",
        "words": [
            {"word": "Telling", "start": 2.392, "end": 3.549},
            {"word": "myself", "start": 3.549, "end": 4.540},
            {"word": "I", "start": 4.540, "end": 4.705},
            {"word": "won't", "start": 4.705, "end": 5.531},
            {"word": "go", "start": 5.531, "end": 5.862},
            {"word": "there", "start": 5.862, "end": 6.688},
        ]
    },
    {
        "en": "Oh, but I know that I won't care",
        "zh": "噢，但我深知自己难以自拔",
        "words": [
            {"word": "Oh,", "start": 6.771, "end": 7.028},
            {"word": "but", "start": 7.028, "end": 7.414},
            {"word": "I", "start": 7.414, "end": 7.543},
            {"word": "know", "start": 7.543, "end": 8.057},
            {"word": "that", "start": 8.057, "end": 8.572},
            {"word": "I", "start": 8.572, "end": 8.700},
            {"word": "won't", "start": 8.700, "end": 9.343},
            {"word": "care", "start": 9.343, "end": 9.858},
        ]
    },
    {
        "en": "Tryna wash away all the blood I've spilt",
        "zh": "试图洗净双手沾染的罪愆与伤痛",
        "words": [
            {"word": "Tryna", "start": 9.941, "end": 10.677},
            {"word": "wash", "start": 10.677, "end": 11.168},
            {"word": "away", "start": 11.168, "end": 11.658},
            {"word": "all", "start": 11.658, "end": 12.026},
            {"word": "the", "start": 12.026, "end": 12.395},
            {"word": "blood", "start": 12.395, "end": 13.008},
            {"word": "I've", "start": 13.008, "end": 13.499},
            {"word": "spilt", "start": 13.499, "end": 14.112},
        ]
    },
    {
        "en": "This lust is a burden that we both share",
        "zh": "这种欲望是我们共同背负的沉沦与枷锁",
        "words": [
            {"word": "This", "start": 17.449, "end": 18.062},
            {"word": "lust", "start": 18.062, "end": 18.675},
            {"word": "is", "start": 18.675, "end": 19.135},
            {"word": "a", "start": 19.135, "end": 19.442},
            {"word": "burden", "start": 19.442, "end": 20.055},
            {"word": "that", "start": 20.055, "end": 20.362},
            {"word": "we", "start": 20.362, "end": 20.669},
            {"word": "both", "start": 20.669, "end": 20.976},
            {"word": "share", "start": 20.976, "end": 21.119},
        ]
    },
    {
        "en": "Two sinners can't atone from a lone prayer",
        "zh": "两个罪人岂能凭一人的祈祷救赎",
        "words": [
            {"word": "Two", "start": 21.202, "end": 21.682},
            {"word": "sinners", "start": 21.682, "end": 22.322},
            {"word": "can't", "start": 22.322, "end": 22.962},
            {"word": "atone", "start": 22.962, "end": 23.602},
            {"word": "from", "start": 23.602, "end": 24.082},
            {"word": "a", "start": 24.082, "end": 24.242},
            {"word": "lone", "start": 24.242, "end": 24.562},
            {"word": "prayer", "start": 24.562, "end": 25.040},
        ]
    },
    {
        "en": "Souls tied, intertwined by our pride and guilt",
        "zh": "灵魂被傲慢与愧疚深深纠缠交织",
        "words": [
            {"word": "Souls", "start": 25.123, "end": 25.568},
            {"word": "tied,", "start": 25.568, "end": 26.013},
            {"word": "intertwined", "start": 26.013, "end": 27.126},
            {"word": "by", "start": 27.126, "end": 27.422},
            {"word": "our", "start": 27.422, "end": 27.719},
            {"word": "pride", "start": 27.719, "end": 28.164},
            {"word": "and", "start": 28.164, "end": 28.461},
            {"word": "guilt", "start": 28.461, "end": 28.960},
        ]
    },
]

# Custom Study Notes for Page 1
page1_notes = [
    ("• atone /əˈtəʊn/：v. 弥补，赎罪（源自 at-one，表化解罪孽与神圣和解）", ""),
    ("• intertwine /ˌɪntəˈtwaɪn/：v. 缠绕，交织纠葛（喻情感与宿命难分难舍）", ""),
    ("• lone prayer：孤单无依的祈祷（强调个体在面对宏大宿命时的无力感）", ""),
    ("• lust is a burden：欲望是一种沉重的负担（深刻的人性自省表达）", ""),
]

print("Building Daylight Page 1...")
# We build a custom canvas builder specifically tuned for Daylight
config = HandwrittenPagerConfig()
builder = CanvasBuilder(config)

# Let's inspect the layout and draw Daylight custom elements
W, H = 1080, 1920
canvas = Image.new("RGBA", (W, H), (254, 251, 246, 255))

# Paper texture
tex_path = PROJECT_ROOT / "src/video_processing/handwritten_pager/assets/paper_texture_ivory.jpg"
if tex_path.exists():
    tex = Image.open(tex_path).convert("RGBA").resize((W, H), Image.Resampling.BILINEAR)
    canvas = Image.blend(canvas, tex, alpha=0.14)

draw = ImageDraw.Draw(canvas)

# Left margin line & binder holes
draw.line([(130, 80), (130, 1840)], fill=(215, 95, 95, 160), width=2)
for hy in [250, 600, 960, 1320, 1680]:
    draw.ellipse([45, hy - 14, 75, hy + 14], fill=(225, 220, 212, 255), outline=(190, 185, 178, 255), width=2)

# Ruled lines
for ry in range(410, 1450, 64):
    draw.line([(110, ry), (1020, ry)], fill=(220, 230, 242, 160), width=1)

# Top Masthead
builder.draw_handdrawn_circle_seal(canvas, (175, 82), radius=26, logo_size=42)
draw.text((215, 66), "六维时空号", font=builder.font_zh_tian_32, fill=(30, 42, 60))
draw.text((375, 68), "｜", font=builder.font_sym_hiragino_26, fill=(190, 175, 150))
builder.draw_mixed_text(draw, (405, 72), "“不同的视角，看见更大的世界。”", builder.font_zh_tian_23, builder.font_sym_hiragino_21, fill=(195, 125, 30))
builder.draw_mixed_text(draw, (800, 72), "✎ 音乐手账 · NO.083", builder.font_zh_tian_22, builder.font_sym_arial_20, fill=(120, 130, 145))

for dx in range(150, 1000, 16):
    draw.line([(dx, 120), (dx + 8, 120)], fill=(215, 205, 185, 180), width=1)

# Title: Daylight (Dark Gothic Midnight + Ember Crimson)
t1 = "Daylight"
draw.text((150, 134), t1, font=builder.font_en_bradley_56, fill=(145, 35, 35))
w_t1 = draw.textlength(t1, font=builder.font_en_bradley_56)

zh_title_text = "《白昼暗影》"
zh_w = builder.get_mixed_text_width(draw, zh_title_text, builder.font_zh_tian_36, builder.font_sym_hiragino_32)
zh_x = 150 + w_t1 + 30
draw.rounded_rectangle([zh_x - 8, 144, zh_x + zh_w + 8, 188], radius=8, fill=(255, 218, 90, 170))
builder.draw_mixed_text(draw, (zh_x, 140), zh_title_text, builder.font_zh_tian_36, builder.font_sym_hiragino_32, fill=(30, 38, 48))

underline_end = int(150 + w_t1 + 10)
draw.line([(150, 204), (underline_end, 204)], fill=(145, 35, 35, 220), width=3)

artist_desc = "原唱：David Kushner (2023)  ·  全球现象级暗黑福音诗意神作  ·  全曲双语伴读"
builder.draw_mixed_text(draw, (150, 218), artist_desc, builder.font_zh_tian_22, builder.font_sym_hiragino_21, fill=(90, 100, 115))

# Accolades Badges
builder.draw_handdrawn_rect(draw, (145, 248, 1005, 376), fill=(255, 250, 240, 245), outline=(225, 175, 95, 240), width=2, roughness=1.4)

badges = [
    ("★ 全球流媒体超 18 亿播放", (245, 130, 15), (255, 255, 255), (210, 85, 0)),
    ("◆ 现象级低音叙事殿堂神作", (20, 120, 210), (255, 255, 255), (10, 90, 170)),
    ("● Billboard 全球单曲榜 Top 5", (125, 60, 200), (255, 255, 255), (95, 35, 165)),
]
box_x0 = 145
box_w = 860
by = 264
b_widths = []
for b_text, _, _, _ in badges:
    w = 0
    for ch in b_text:
        f = builder.font_zh_tian_22 if is_cjk(ch) else builder.font_sym_arial_21
        w += draw.textlength(ch, font=f)
    b_widths.append(w + 36)
gap = (box_w - sum(b_widths)) / 4
cur_bx = box_x0 + gap
for idx, (b_text, b_fill, b_text_c, b_border) in enumerate(badges):
    bw = b_widths[idx]
    builder.draw_handdrawn_rect(draw, (cur_bx, by, cur_bx + bw, by + 40), fill=b_fill, outline=b_border, width=2, roughness=1.0)
    builder.draw_mixed_text(draw, (cur_bx + 18, by + 8), b_text, builder.font_zh_tian_22, builder.font_sym_arial_21, fill=b_text_c)
    cur_bx += bw + gap

quote_prefix = "✎ 策展手记: “以深沉男低音与管风琴大提琴，"
quote_highlight = "写尽深渊中的挣扎、救赎与矛盾爱恨"
quote_suffix = "。”"
w_qp = builder.get_mixed_text_width(draw, quote_prefix, builder.font_zh_tian_22, builder.font_sym_arial_21)
w_qh = builder.get_mixed_text_width(draw, quote_highlight, builder.font_zh_tian_22, builder.font_sym_arial_21)
hl_x0 = 175 + w_qp
hl_x1 = hl_x0 + w_qh
draw.rounded_rectangle([hl_x0 - 4, 327, hl_x1 + 4, 353], radius=6, fill=(255, 215, 130, 160))
builder.draw_mixed_text(draw, (175, 326), quote_prefix, builder.font_zh_tian_22, builder.font_sym_arial_21, fill=(100, 90, 80))
builder.draw_mixed_text(draw, (hl_x0, 326), quote_highlight, builder.font_zh_tian_22, builder.font_sym_arial_21, fill=(175, 45, 20))
builder.draw_mixed_text(draw, (hl_x1, 326), quote_suffix, builder.font_zh_tian_22, builder.font_sym_arial_21, fill=(100, 90, 80))

# Lyrics: 6 lines on Page 1 (y = 405..1350)
stanza_y = [405, 565, 725, 885, 1045, 1205]
tracking = -1.2
font_en_40 = builder._resolve_font([("/System/Library/Fonts/Noteworthy.ttc", 40, 1)])

doodle_specs = [
    ((895, 400), 95),
    ((890, 560), 95),
    ((895, 720), 90),
    ((880, 880), 105),
    ((900, 1040), 85),
    ((885, 1200), 95),
]

for i, item in enumerate(page1_lyrics):
    en_text = item["en"]
    zh_text = item["zh"]
    sy = stanza_y[i]
    
    # Auto-scale font for long lines
    raw_w = sum(draw.textlength(ch, font=builder.font_en_noteworthy_45) + tracking for ch in en_text)
    cur_font = font_en_40 if raw_w > 680 else builder.font_en_noteworthy_45
    
    # English
    cur_x = 150.0
    for ch in en_text:
        draw.text((cur_x, sy), ch, font=cur_font, fill=(22, 28, 38))
        cur_x += draw.textlength(ch, font=cur_font) + tracking
        
    # Chinese (+72px)
    builder.draw_mixed_text(draw, (150, sy + 72), zh_text, builder.font_zh_tian_28, builder.font_sym_hiragino_26, fill=(75, 85, 100))
    
    # Doodles (only if no overlap)
    if i < len(builder.doodles):
        d_img = builder.doodles[i]
        d_xy, d_w = doodle_specs[i]
        # Shift doodle right if text is wide
        if cur_x + 15 > d_xy[0]:
            d_xy = (int(cur_x + 20), d_xy[1])
        aspect = d_img.height / d_img.width
        d_h = int(d_w * aspect)
        d_scaled = d_img.resize((d_w, d_h), Image.Resampling.LANCZOS)
        canvas.paste(d_scaled, d_xy, d_scaled)

# Study Notes Card at bottom (y = 1395..1760)
card_y0, card_y1 = 1395, 1750
builder.draw_handdrawn_rect(draw, (145, card_y0, 1005, card_y1), fill=(255, 252, 245, 240), outline=(215, 200, 175, 230), width=2, roughness=1.5)
header_txt = "◆ 重点表达手账解析 (第一幕 · 罪与救赎)"
hw = builder.get_mixed_text_width(draw, header_txt, builder.font_zh_tian_28, builder.font_sym_hiragino_26)
draw.rounded_rectangle([170, card_y0 + 16, 170 + hw + 24, card_y0 + 58], radius=6, fill=(255, 220, 110, 180))
builder.draw_mixed_text(draw, (182, card_y0 + 22), header_txt, builder.font_zh_tian_28, builder.font_sym_hiragino_26, fill=(40, 48, 60))

ny = card_y0 + 78
for note_text, _ in page1_notes:
    builder.draw_mixed_text(draw, (175, ny), note_text, builder.font_zh_tian_23, builder.font_sym_arial_21, fill=(48, 56, 68))
    ny += 54

out_preview = work_dir / "preview_page1.png"
canvas.save(out_preview)
print(f"Page 1 preview generated at: {out_preview}")
