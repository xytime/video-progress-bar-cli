#!/usr/bin/env python3
"""Generate 3 perfectly tuned layout demo options for 'Handwritten Pager + Original MV Footage':
- Demo A: Gallery Split-Screen (Cinema Top 35% + Journal Bottom 65%)
- Demo B: Polaroid Scrapbook PIP (Floating Washi-Tape Polaroid MV on Notebook)
- Demo C: Editorial Cinema Masterpiece (Three-Stage Magazine: Brand Header + Wide MV + Journal)
"""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output/handwritten_pager/gimme/demos"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

ASSETS_DIR = PROJECT_ROOT / "src/video_processing/handwritten_pager/assets"
PAPER_PATH = ASSETS_DIR / "paper_texture_ivory.jpg"
PEN_PATH = ASSETS_DIR / "pen_ballpoint_photorealistic.png"
LOGO_PATH = PROJECT_ROOT / "assets/brand/01_logos/concept_a.png"
MV_FRAME_PATH = PROJECT_ROOT / "output/handwritten_pager/gimme/frames/frame_agnetha_26s.jpg"

# Fonts
FONT_ZH_CALLIGRAPHY = "/Library/Fonts/TianYingZhang.ttf"
FONT_EN_SCRIPT = "/System/Library/Fonts/Supplemental/Bradley Hand Bold.ttf"
FONT_ARIAL_UNICODE = "/Library/Fonts/Arial Unicode.ttf"
FONT_SANS = "/Library/Fonts/Hiragino Sans GB.ttc"

def load_font(path_str: str, size: int):
    try:
        return ImageFont.truetype(path_str, size)
    except Exception:
        return ImageFont.load_default()

font_brand = load_font(FONT_SANS, 24)
font_slogan = load_font(FONT_SANS, 20)
font_title_en = load_font(FONT_EN_SCRIPT, 32)
font_title_zh = load_font(FONT_ZH_CALLIGRAPHY, 26)
font_subtitle = load_font(FONT_SANS, 20)
font_card_head = load_font(FONT_SANS, 21)
font_card_body = load_font(FONT_ARIAL_UNICODE, 19)
font_badge = load_font(FONT_SANS, 18)

def draw_mixed_text(draw: ImageDraw.ImageDraw, pos, text: str, font_zh, font_sym, fill):
    x, y = pos
    for char in text:
        if ord(char) < 128 or char in "·【】《》“”‘’◆•★●✎—…":
            draw.text((x, y), char, font=font_sym, fill=fill)
            x += draw.textlength(char, font=font_sym)
        else:
            draw.text((x, y), char, font=font_zh, fill=fill)
            x += draw.textlength(char, font=font_zh)

def get_base_paper():
    if PAPER_PATH.exists():
        im = Image.open(PAPER_PATH).convert("RGBA").resize((1080, 1920), Image.Resampling.LANCZOS)
    else:
        im = Image.new("RGBA", (1080, 1920), (250, 246, 237, 255))
    return im

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

def get_pen_sprite(width=135):
    if PEN_PATH.exists():
        im = Image.open(PEN_PATH).convert("RGBA")
        aspect = im.height / im.width
        h = int(width * aspect)
        return im.resize((width, h), Image.Resampling.LANCZOS)
    return None

def draw_notebook_holes(draw: ImageDraw.ImageDraw, y_start=60, y_end=1860, step=120):
    for y in range(y_start, y_end, step):
        draw.ellipse([38, y, 62, y + 24], fill=(225, 220, 210, 255), outline=(180, 172, 160, 200), width=2)
    draw.line([(130, y_start - 20), (130, y_end + 20)], fill=(220, 100, 100, 130), width=2)

def draw_pen_at(canvas: Image.Image, tip_x: int, tip_y: int):
    pen = get_pen_sprite(135)
    if not pen:
        return
    shadow = Image.new("RGBA", pen.size, (0, 0, 0, 0))
    for x in range(pen.width):
        for y in range(pen.height):
            a = pen.getpixel((x, y))[3]
            if a > 30:
                shadow.putpixel((x, y), (40, 35, 30, int(a * 0.35)))
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=8))
    
    px = tip_x - 12
    py = tip_y - pen.height + 15
    canvas.paste(shadow, (px + 14, py + 16), shadow)
    canvas.paste(pen, (px, py), pen)


# =========================================================================
# DEMO A: 【上下分屏 · 经典影音画廊流】(Gallery Cinema Split)
# =========================================================================
def build_demo_a():
    canvas = get_base_paper()
    draw = ImageDraw.Draw(canvas)
    
    # 1. Top Minimalist Brand Header (y=30~92)
    logo = get_clean_logo(48)
    canvas.paste(logo, (145, 30), logo)
    draw.text((210, 34), "六维时空号", fill=(35, 40, 50, 240), font=font_brand)
    draw.line([(345, 40), (345, 66)], fill=(180, 170, 160, 180), width=2)
    draw.text((365, 39), "“不同的视角，看见更大的世界。”", fill=(130, 95, 45, 220), font=font_slogan)
    draw_mixed_text(draw, (790, 39), "✎ 音乐手账 · NO.084 (P1/6)", load_font(FONT_ZH_CALLIGRAPHY, 20), font_slogan, (110, 115, 125, 210))
    draw.line([(145, 92), (1020, 92)], fill=(225, 220, 210, 180), width=1)
    
    # 2. Upper Cinema MV Frame (y=108~628, 16:9 ratio: 924x520)
    mv_w, mv_h = 924, 520
    mv_x, mv_y = 78, 108
    
    v_shadow = Image.new("RGBA", (mv_w + 40, mv_h + 40), (0, 0, 0, 0))
    v_sd = ImageDraw.Draw(v_shadow)
    v_sd.rounded_rectangle([15, 15, mv_w + 25, mv_h + 25], radius=16, fill=(30, 25, 20, 120))
    v_shadow = v_shadow.filter(ImageFilter.GaussianBlur(radius=12))
    canvas.paste(v_shadow, (mv_x - 20, mv_y - 12), v_shadow)
    
    if MV_FRAME_PATH.exists():
        mv_im = Image.open(MV_FRAME_PATH).convert("RGBA").resize((mv_w, mv_h), Image.Resampling.LANCZOS)
    else:
        mv_im = Image.new("RGBA", (mv_w, mv_h), (25, 30, 45, 255))
    
    mask = Image.new("L", (mv_w, mv_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, mv_w, mv_h], radius=14, fill=255)
    mv_im.putalpha(mask)
    canvas.paste(mv_im, (mv_x, mv_y), mv_im)
    
    draw.rounded_rectangle([mv_x, mv_y, mv_x + mv_w, mv_y + mv_h], radius=14, outline=(212, 175, 55, 220), width=2)
    
    draw.rounded_rectangle([mv_x + mv_w - 205, mv_y + 14, mv_x + mv_w - 16, mv_y + 44], radius=8, fill=(10, 15, 25, 180), outline=(243, 186, 47, 180), width=1)
    draw.text((mv_x + mv_w - 192, mv_y + 17), "● 原版 1080P 官方 MV", fill=(255, 255, 255, 230), font=load_font(FONT_SANS, 15))
    
    draw.rounded_rectangle([mv_x + 16, mv_y + mv_h - 44, mv_x + 315, mv_y + mv_h - 14], radius=6, fill=(10, 15, 25, 180))
    draw.text((mv_x + 24, mv_y + mv_h - 39), "ABBA · Polar Studio 1979", fill=(240, 230, 210, 220), font=load_font(FONT_SANS, 15))
    
    # 3. Middle Separator Banner (y=645~745)
    draw.text((150, 646), "Gimme! Gimme! Gimme!", fill=(140, 30, 30, 255), font=font_title_en)
    title_w = draw.textlength("Gimme! Gimme! Gimme!", font=font_title_en)
    
    zh_box_x = int(150 + title_w + 18)
    draw.rounded_rectangle([zh_box_x, 648, zh_box_x + 155, 686], radius=6, fill=(245, 228, 175, 240), outline=(215, 165, 55, 200), width=1)
    draw_mixed_text(draw, (zh_box_x + 10, 651), "《午夜求爱》", font_title_zh, load_font(FONT_SANS, 22), (70, 45, 15, 255))
    
    act_box_x = zh_box_x + 170
    draw.rounded_rectangle([act_box_x, 648, act_box_x + 195, 686], radius=6, fill=(250, 240, 230, 220), outline=(190, 120, 70, 180), width=1)
    draw_mixed_text(draw, (act_box_x + 10, 654), "【第一幕 · 孤影独白】", font_title_zh, load_font(FONT_SANS, 20), (140, 60, 30, 240))
    
    draw_mixed_text(draw, (150, 700), "原唱：ABBA (1979)  ·  迪斯科殿堂名作  ·  麦当娜《Hung Up》原版神级采样", load_font(FONT_ZH_CALLIGRAPHY, 20), font_subtitle, (100, 105, 115, 230))
    draw.line([(150, 735), (1020, 735)], fill=(220, 210, 195, 180), width=2)
    
    # 4. Notebook Holes & Red Line
    draw_notebook_holes(draw, y_start=660, y_end=1880, step=110)
    
    # 5. Lower Lyrics Section (y=755~1520) - 4 spacious lyric pairs
    lyrics = [
        ("Half past twelve, and I'm watching the late show in my flat all alone", "午夜十二点半，我独自在公寓看着深夜电视"),
        ("How I hate to spend the evening on my own", "我多讨厌孤身一人度过这漫漫长夜"),
        ("Autumn winds blowing outside the window as I look around the room", "窗外秋风呼啸，我环顾空荡冰冷的房间"),
        ("And it makes me so depressed to see the gloom", "眼前无尽的幽暗与沉寂令我深陷落寞"),
    ]
    cur_y = 755
    for i, (en, zh) in enumerate(lyrics):
        font_en_cur = load_font(FONT_EN_SCRIPT, 27 if len(en) > 55 else 32)
        font_zh_cur = load_font(FONT_ZH_CALLIGRAPHY, 26)
        color_en = (150, 30, 30, 255) if i == 1 else (45, 50, 60, 230)
        draw.text((155, cur_y), en, fill=color_en, font=font_en_cur)
        draw_mixed_text(draw, (155, cur_y + 45), zh, font_zh_cur, load_font(FONT_SANS, 24), (90, 80, 70, 230))
        cur_y += 140
    
    # Pen placed on line 2 "on my own" (y=895) - avoids clipping top video
    draw_pen_at(canvas, tip_x=720, tip_y=895)
    
    # 6. Study Notes Card (y=1540~1850)
    card_bg = Image.new("RGBA", (880, 260), (252, 248, 238, 250))
    cd = ImageDraw.Draw(card_bg)
    cd.rounded_rectangle([0, 0, 878, 258], radius=10, fill=(253, 249, 240, 255), outline=(215, 180, 110, 180), width=1)
    draw_mixed_text(cd, (20, 16), "◆ 重点表达手账解析【第一幕 · 孤影独白】", font_card_head, font_card_head, (140, 70, 25, 255))
    notes = [
        ("flat /flæt/：", "n. 英式公寓（美式为 apartment，指城市中独居的一套套间）"),
        ("on one's own：", "phr. 独自一人（强调孤立无援的寂寥境遇，比 alone 更有凄冷感）"),
        ("gloom /ɡluːm/：", "n. 幽暗阴郁；引申为孤独中压抑沉郁的消极心绪"),
        ("chase shadows away：", "phr. 驱散心头阴霾与无助（隐喻渴望爱与陪伴解救孤独）"),
    ]
    ny = 56
    for h, b in notes:
        cd.text((22, ny), "• " + h, fill=(150, 35, 35, 255), font=font_card_body)
        w_h = cd.textlength("• " + h, font=font_card_body)
        cd.text((22 + w_h, ny), b, fill=(75, 70, 65, 230), font=font_card_body)
        ny += 46
    canvas.paste(card_bg, (145, 1540), card_bg)
    
    out_path = OUTPUT_DIR / "demo_a_gallery_split.png"
    canvas.convert("RGB").save(out_path, quality=95)
    print(f"Demo A saved: {out_path}")
    return canvas


# =========================================================================
# DEMO B: 【拍立得画中画 · 典藏剪贴手账流】(Polaroid Scrapbook PIP)
# =========================================================================
def build_demo_b():
    canvas = get_base_paper()
    draw = ImageDraw.Draw(canvas)
    
    draw_notebook_holes(draw, y_start=60, y_end=1880, step=110)
    
    # 1. Top Brand Header
    logo = get_clean_logo(48)
    canvas.paste(logo, (145, 30), logo)
    draw.text((210, 34), "六维时空号", fill=(35, 40, 50, 240), font=font_brand)
    draw.line([(345, 40), (345, 66)], fill=(180, 170, 160, 180), width=2)
    draw.text((365, 39), "“不同的视角，看见更大的世界。”", fill=(130, 95, 45, 220), font=font_slogan)
    draw_mixed_text(draw, (790, 39), "✎ 音乐手账 · NO.084 (P1/6)", load_font(FONT_ZH_CALLIGRAPHY, 20), font_slogan, (110, 115, 125, 210))
    
    # Title
    draw.text((150, 95), "Gimme! Gimme! Gimme!", fill=(140, 30, 30, 255), font=font_title_en)
    title_w = draw.textlength("Gimme! Gimme! Gimme!", font=font_title_en)
    zh_box_x = int(150 + title_w + 18)
    draw.rounded_rectangle([zh_box_x, 97, zh_box_x + 155, 135], radius=6, fill=(245, 228, 175, 240), outline=(215, 165, 55, 200), width=1)
    draw_mixed_text(draw, (zh_box_x + 10, 100), "《午夜求爱》", font_title_zh, load_font(FONT_SANS, 22), (70, 45, 15, 255))
    
    act_box_x = zh_box_x + 170
    draw.rounded_rectangle([act_box_x, 97, act_box_x + 195, 135], radius=6, fill=(250, 240, 230, 220), outline=(190, 120, 70, 180), width=1)
    draw_mixed_text(draw, (act_box_x + 10, 103), "【第一幕 · 孤影独白】", font_title_zh, load_font(FONT_SANS, 20), (140, 60, 30, 240))
    
    draw_mixed_text(draw, (150, 148), "原唱：ABBA (1979)  ·  Agnetha Faltskog 主唱  ·  全曲双语伴读", load_font(FONT_ZH_CALLIGRAPHY, 20), font_subtitle, (100, 105, 115, 230))
    draw.line([(150, 180), (1020, 180)], fill=(220, 210, 195, 180), width=1)
    
    # 2. Right-Angled Polaroid Picture-in-Picture (x=460, y=200)
    p_w, p_h = 560, 470
    polaroid = Image.new("RGBA", (p_w, p_h), (255, 255, 255, 255))
    pd = ImageDraw.Draw(polaroid)
    pd.rectangle([0, 0, p_w, p_h], fill=(255, 253, 248, 255), outline=(210, 200, 190, 220), width=1)
    
    if MV_FRAME_PATH.exists():
        mv_im = Image.open(MV_FRAME_PATH).convert("RGBA").resize((p_w - 30, 360), Image.Resampling.LANCZOS)
    else:
        mv_im = Image.new("RGBA", (p_w - 30, 360), (25, 30, 45, 255))
    polaroid.paste(mv_im, (15, 15))
    
    pd.text((25, 395), "Agnetha @ Polar Studio 1979", fill=(70, 75, 85, 220), font=load_font(FONT_EN_SCRIPT, 26))
    pd.text((400, 402), "● Official MV", fill=(160, 50, 50, 220), font=load_font(FONT_SANS, 18))
    
    pol_rot = polaroid.rotate(-2.5, expand=True, resample=Image.Resampling.BICUBIC)
    
    pshadow = Image.new("RGBA", pol_rot.size, (0, 0, 0, 0))
    for x in range(0, pol_rot.width, 2):
        for y in range(0, pol_rot.height, 2):
            if pol_rot.getpixel((x, y))[3] > 40:
                pshadow.putpixel((x, y), (35, 30, 25, 110))
    pshadow = pshadow.filter(ImageFilter.GaussianBlur(radius=10))
    
    px_pos, py_pos = 460, 200
    canvas.paste(pshadow, (px_pos + 8, py_pos + 10), pshadow)
    canvas.paste(pol_rot, (px_pos, py_pos), pol_rot)
    
    # Washi Tape
    tape = Image.new("RGBA", (140, 36), (235, 205, 130, 190))
    ImageDraw.Draw(tape).line([(0, 0), (140, 0)], fill=(255, 255, 255, 80), width=1)
    tape_rot = tape.rotate(-2.5, expand=True)
    canvas.paste(tape_rot, (px_pos + 180, py_pos - 12), tape_rot)
    
    # 3. Left Column Diary Lyrics (x=150~430, y=205~680)
    diary_lines = [
        ("Half past twelve,", "午夜时分孤身一人，"),
        ("watching the late show", "独看深夜电视，"),
        ("in my flat all alone.", "空荡寓所寂寥无声。"),
        ("How I hate to spend", "我多讨厌虚掷时光，"),
        ("the evening on my own!", "独自熬过漫漫长夜！"),
    ]
    dy = 205
    for en, zh in diary_lines:
        draw.text((150, dy), en, fill=(150, 35, 35, 255) if "Half" in en else (45, 50, 60, 230), font=load_font(FONT_EN_SCRIPT, 27))
        draw_mixed_text(draw, (150, dy + 36), zh, load_font(FONT_ZH_CALLIGRAPHY, 23), load_font(FONT_SANS, 22), (90, 80, 70, 230))
        dy += 92
    
    draw.line([(150, 700), (1020, 700)], fill=(220, 210, 195, 180), width=1)
    
    # 4. Lower Grand Chorus Section (y=725~1520)
    chorus_lines = [
        ("Autumn winds blowing outside the window as I look around the room", "窗外秋风呼啸，我环顾空荡冰冷的房间"),
        ("And it makes me so depressed to see the gloom", "眼前无尽的幽暗与沉寂令我深陷落寞"),
        ("Gimme! Gimme! Gimme! a man after midnight!", "赐我一份怀抱，在午夜之后！"),
        ("Won't somebody help me chase the shadows away?", "难道无人能助我驱散这暗夜孤影吗？"),
        ("Take me through the darkness to the break of the day!", "带我穿透无尽黑暗，直至黎明破晓！"),
    ]
    cy = 725
    for i, (en, zh) in enumerate(chorus_lines):
        f_size = 28 if len(en) > 55 else 32
        font_en_c = load_font(FONT_EN_SCRIPT, f_size)
        color_en = (160, 30, 30, 255) if i == 2 else (40, 45, 55, 230)
        draw.text((155, cy), en, fill=color_en, font=font_en_c)
        draw_mixed_text(draw, (155, cy + 44), zh, load_font(FONT_ZH_CALLIGRAPHY, 26), load_font(FONT_SANS, 24), (90, 80, 70, 230))
        cy += 122
    
    draw_pen_at(canvas, tip_x=860, tip_y=965)
    
    # 5. Study Notes Card (y=1550~1850)
    card_bg = Image.new("RGBA", (880, 260), (252, 248, 238, 250))
    cd = ImageDraw.Draw(card_bg)
    cd.rounded_rectangle([0, 0, 878, 258], radius=10, fill=(253, 249, 240, 255), outline=(215, 180, 110, 180), width=1)
    draw_mixed_text(cd, (20, 16), "◆ 重点表达手账解析【第一幕 · 孤影独白】", font_card_head, font_card_head, (140, 70, 25, 255))
    notes = [
        ("flat /flæt/：", "n. 英式公寓（美式为 apartment，表城市中独居处所）"),
        ("on one's own：", "phr. 独自一人（同 alone，语气更强调无人相伴的孤立无援）"),
        ("chase shadows away：", "phr. 驱散心头孤寂与阴霾（隐喻渴望爱与陪伴解救孤独）"),
        ("break of the day：", "phr. 破晓时分 / 天亮之时（喻重获新生与光明的时刻）"),
    ]
    ny = 56
    for h, b in notes:
        cd.text((22, ny), "• " + h, fill=(150, 35, 35, 255), font=font_card_body)
        w_h = cd.textlength("• " + h, font=font_card_body)
        cd.text((22 + w_h, ny), b, fill=(75, 70, 65, 230), font=font_card_body)
        ny += 46
    canvas.paste(card_bg, (145, 1550), card_bg)
    
    out_path = OUTPUT_DIR / "demo_b_polaroid_scrapbook.png"
    canvas.convert("RGB").save(out_path, quality=95)
    print(f"Demo B saved: {out_path}")
    return canvas


# =========================================================================
# DEMO C: 【上中下典藏画报 · 影音三段式】(Editorial Cinema Masterpiece)
# =========================================================================
def build_demo_c():
    canvas = get_base_paper()
    draw = ImageDraw.Draw(canvas)
    
    # 1. Top Editorial Banner (y=30~215)
    logo = get_clean_logo(52)
    canvas.paste(logo, (145, 30), logo)
    draw.text((215, 34), "六维时空号", fill=(35, 40, 50, 240), font=font_brand)
    draw.line([(355, 40), (355, 66)], fill=(180, 170, 160, 180), width=2)
    draw.text((375, 39), "“不同的视角，看见更大的世界。”", fill=(130, 95, 45, 220), font=font_slogan)
    draw_mixed_text(draw, (790, 39), "✎ 音乐手账 · NO.084 (P1/6)", load_font(FONT_ZH_CALLIGRAPHY, 20), font_slogan, (110, 115, 125, 210))
    
    # Main Editorial Title
    draw.text((150, 90), "Gimme! Gimme! Gimme!", fill=(140, 30, 30, 255), font=font_title_en)
    title_w = draw.textlength("Gimme! Gimme! Gimme!", font=font_title_en)
    zh_box_x = int(150 + title_w + 18)
    draw.rounded_rectangle([zh_box_x, 92, zh_box_x + 155, 130], radius=6, fill=(245, 228, 175, 240), outline=(215, 165, 55, 200), width=1)
    draw_mixed_text(draw, (zh_box_x + 10, 95), "《午夜求爱》", font_title_zh, load_font(FONT_SANS, 22), (70, 45, 15, 255))
    
    act_box_x = zh_box_x + 170
    draw.rounded_rectangle([act_box_x, 92, act_box_x + 195, 130], radius=6, fill=(250, 240, 230, 220), outline=(190, 120, 70, 180), width=1)
    draw_mixed_text(draw, (act_box_x + 10, 98), "【第一幕 · 孤影独白】", font_title_zh, load_font(FONT_SANS, 20), (140, 60, 30, 240))
    
    badges = [
        ("★ 全球12国冠军单曲", (180, 60, 30, 255), (255, 240, 230, 255), (230, 140, 100, 200)),
        ("◆ 麦当娜神级采样原曲", (25, 90, 130, 255), (230, 245, 255, 255), (100, 180, 220, 200)),
        ("● 迪斯科合成器天花板", (130, 80, 20, 255), (255, 248, 225, 255), (220, 180, 90, 200)),
    ]
    bx = 150
    for text, text_col, bg_col, bdr_col in badges:
        bw = int(draw.textlength(text, font=font_badge)) + 24
        draw.rounded_rectangle([bx, 148, bx + bw, 182], radius=12, fill=bg_col, outline=bdr_col, width=1)
        draw.text((bx + 12, 155), text, fill=text_col, font=font_badge)
        bx += bw + 15
    
    # 2. Middle Wide Cinema MV Window (y=200~720, 16:9 ratio: 924x520)
    mv_w, mv_h = 924, 520
    mv_x, mv_y = 78, 200
    
    c_shadow = Image.new("RGBA", (mv_w + 40, mv_h + 40), (0, 0, 0, 0))
    c_sd = ImageDraw.Draw(c_shadow)
    c_sd.rounded_rectangle([15, 15, mv_w + 25, mv_h + 25], radius=16, fill=(20, 18, 15, 140))
    c_shadow = c_shadow.filter(ImageFilter.GaussianBlur(radius=15))
    canvas.paste(c_shadow, (mv_x - 20, mv_y - 12), c_shadow)
    
    if MV_FRAME_PATH.exists():
        mv_im = Image.open(MV_FRAME_PATH).convert("RGBA").resize((mv_w, mv_h), Image.Resampling.LANCZOS)
    else:
        mv_im = Image.new("RGBA", (mv_w, mv_h), (25, 30, 45, 255))
    
    mask = Image.new("L", (mv_w, mv_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, mv_w, mv_h], radius=14, fill=255)
    mv_im.putalpha(mask)
    canvas.paste(mv_im, (mv_x, mv_y), mv_im)
    
    draw.rounded_rectangle([mv_x, mv_y, mv_x + mv_w, mv_y + mv_h], radius=14, outline=(243, 186, 47, 240), width=2)
    
    # Vintage Audio Player Status Bar beneath MV
    draw.rounded_rectangle([mv_x + 10, mv_y + mv_h - 44, mv_x + mv_w - 10, mv_y + mv_h - 10], radius=8, fill=(12, 16, 24, 210))
    draw.text((mv_x + 25, mv_y + mv_h - 38), "● PLAYING  00:26 / 03:16", fill=(255, 220, 120, 255), font=load_font(FONT_SANS, 16))
    draw.text((mv_x + 300, mv_y + mv_h - 38), "STEREO DOLBY [L ■■■■□ | R ■■■■□]", fill=(120, 220, 200, 230), font=load_font(FONT_SANS, 16))
    draw.text((mv_x + mv_w - 230, mv_y + mv_h - 38), "Agnetha Faltskog (ABBA)", fill=(240, 240, 240, 220), font=load_font(FONT_SANS, 16))
    
    # 3. Notebook Holes & Red Line lower half
    draw_notebook_holes(draw, y_start=740, y_end=1880, step=110)
    
    # 4. Lower Lyrics Section (y=750~1510)
    lyrics = [
        ("Half past twelve, and I'm watching the late show in my flat all alone", "午夜十二点半，我独自在公寓看着深夜电视"),
        ("How I hate to spend the evening on my own", "我多讨厌孤身一人度过这漫漫长夜"),
        ("Autumn winds blowing outside the window as I look around the room", "窗外秋风呼啸，我环顾空荡冰冷的房间"),
        ("And it makes me so depressed to see the gloom", "眼前无尽的幽暗与沉寂令我深陷落寞"),
    ]
    cy = 750
    for i, (en, zh) in enumerate(lyrics):
        font_en_cur = load_font(FONT_EN_SCRIPT, 27 if len(en) > 55 else 32)
        font_zh_cur = load_font(FONT_ZH_CALLIGRAPHY, 26)
        color_en = (150, 30, 30, 255) if i == 1 else (45, 50, 60, 230)
        draw.text((155, cy), en, fill=color_en, font=font_en_cur)
        draw_mixed_text(draw, (155, cy + 45), zh, font_zh_cur, load_font(FONT_SANS, 24), (90, 80, 70, 230))
        cy += 140
    
    # Pen on line 2 (y=890)
    draw_pen_at(canvas, tip_x=720, tip_y=890)
    
    # 5. Study Notes Card (y=1540~1850)
    card_bg = Image.new("RGBA", (880, 260), (252, 248, 238, 250))
    cd = ImageDraw.Draw(card_bg)
    cd.rounded_rectangle([0, 0, 878, 258], radius=10, fill=(253, 249, 240, 255), outline=(215, 180, 110, 180), width=1)
    draw_mixed_text(cd, (20, 16), "◆ 重点表达手账解析【第一幕 · 孤影独白】", font_card_head, font_card_head, (140, 70, 25, 255))
    notes = [
        ("flat /flæt/：", "n. 英式公寓（美式为 apartment，指城市中独居的一套套间）"),
        ("on one's own：", "phr. 独自一人（强调孤立无援的寂寥境遇，比 alone 更有凄冷感）"),
        ("gloom /ɡluːm/：", "n. 幽暗阴郁；引申为孤独中压抑沉郁的消极心绪"),
        ("chase shadows away：", "phr. 驱散心头阴霾与无助（隐喻渴望爱与陪伴解救孤独）"),
    ]
    ny = 56
    for h, b in notes:
        cd.text((22, ny), "• " + h, fill=(150, 35, 35, 255), font=font_card_body)
        w_h = cd.textlength("• " + h, font=font_card_body)
        cd.text((22 + w_h, ny), b, fill=(75, 70, 65, 230), font=font_card_body)
        ny += 46
    canvas.paste(card_bg, (145, 1540), card_bg)
    
    out_path = OUTPUT_DIR / "demo_c_editorial_cinema.png"
    canvas.convert("RGB").save(out_path, quality=95)
    print(f"Demo C saved: {out_path}")
    return canvas


# =========================================================================
# BUILD COMPARISON GRID
# =========================================================================
def build_comparison_grid(im_a, im_b, im_c):
    thumb_w, thumb_h = 360, 640
    t_a = im_a.resize((thumb_w, thumb_h), Image.Resampling.LANCZOS)
    t_b = im_b.resize((thumb_w, thumb_h), Image.Resampling.LANCZOS)
    t_c = im_c.resize((thumb_w, thumb_h), Image.Resampling.LANCZOS)
    
    grid_w = thumb_w * 3 + 40
    grid_h = thumb_h + 100
    grid = Image.new("RGBA", (grid_w, grid_h), (242, 238, 228, 255))
    gd = ImageDraw.Draw(grid)
    
    gd.text((20, 20), "ABBA《Gimme! Gimme! Gimme!》手账伴读 + 原版视频 布局方案对比", fill=(30, 35, 45, 255), font=load_font(FONT_SANS, 26))
    
    labels = [
        ("方案 A：上下分屏 · 经典影音画廊流", 10),
        ("方案 B：拍立得贴片 · 沉浸剪贴手账流", 20 + thumb_w),
        ("方案 C：上中下典藏画报 · 影音三段式", 30 + thumb_w * 2),
    ]
    for text, x in labels:
        gd.text((x, 65), text, fill=(130, 50, 30, 255), font=load_font(FONT_SANS, 19))
    
    grid.paste(t_a, (10, 95))
    grid.paste(t_b, (20 + thumb_w, 95))
    grid.paste(t_c, (30 + thumb_w * 2, 95))
    
    out_path = OUTPUT_DIR / "demo_comparison_grid.png"
    grid.convert("RGB").save(out_path, quality=95)
    print(f"Comparison Grid saved: {out_path}")


if __name__ == "__main__":
    im_a = build_demo_a()
    im_b = build_demo_b()
    im_c = build_demo_c()
    build_comparison_grid(im_a, im_b, im_c)
