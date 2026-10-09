#!/usr/bin/env python3
"""Generate optimized Scheme B (v2) based on user directives:
1. Main Lyric Page: Remove bottom study card to free up 300px space!
   - Use large, bold, high-contrast Noteworthy Bold font (44px) so older audience can read effortlessly.
   - Never shrink font; allow natural line wrapping if needed.
   - Polaroid MV on top-right, spacious lyrics below with generous line spacing.
2. Final 3-Second Vocabulary Recap Page:
   - No video player, but keeps full notebook header & footer.
   - Full-page spacious vocabulary & idiom master study card with IPA, definitions, and doodles.
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
MV_FRAME_PATH = PROJECT_ROOT / "output/handwritten_pager/gimme/frames/frame_agnetha_40s.jpg"

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

# Typography
font_brand = load_font(FONT_SANS, 24)
font_slogan = load_font(FONT_SANS, 20)
font_title_en = load_font(FONT_EN_NOTEWORTHY, 36, index=1)
font_title_zh = load_font(FONT_ZH_CALLIGRAPHY, 28)
font_subtitle = load_font(FONT_SANS, 20)

# Large legible lyrics fonts for mature audience
font_lyrics_en_large = load_font(FONT_EN_NOTEWORTHY, 44, index=1)   # Bold Noteworthy 44px
font_lyrics_zh_large = load_font(FONT_ZH_CALLIGRAPHY, 32)          # TianYingZhang 32px
font_lyrics_en_side  = load_font(FONT_EN_NOTEWORTHY, 36, index=1)   # 36px for left column
font_lyrics_zh_side  = load_font(FONT_ZH_CALLIGRAPHY, 26)

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
            # Everything else (English, IPA, numbers, punctuation, symbols) uses font_sym!
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

def get_pen_sprite(width=140):
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
    pen = get_pen_sprite(140)
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
# 1. OPTIMIZED SCHEME B MAIN LYRIC PAGE (ZERO OVERLAP DYNAMIC BOUNDING BOX)
# =========================================================================
def build_scheme_b_lyrics_page():
    canvas = get_base_paper()
    draw = ImageDraw.Draw(canvas)
    
    draw_notebook_holes(draw, y_start=60, y_end=1880, step=110)
    
    # 1. Top Brand Header (y=30~85)
    logo = get_clean_logo(48)
    canvas.paste(logo, (145, 30), logo)
    draw.text((210, 34), "六维时空号", fill=(35, 40, 50, 240), font=font_brand)
    draw.line([(345, 40), (345, 66)], fill=(180, 170, 160, 180), width=2)
    draw.text((365, 39), "“不同的视角，看见更大的世界。”", fill=(130, 95, 45, 220), font=font_slogan)
    draw_mixed_text(draw, (790, 39), "✎ 音乐手账 · NO.084 (P1/5)", load_font(FONT_ZH_CALLIGRAPHY, 20), font_slogan, (110, 115, 125, 210))
    
    # Song Title Row (y=92~135)
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
    
    # 2. Right Polaroid Picture-in-Picture (x=525, y=182, w=490, h=390)
    p_w, p_h = 490, 390
    polaroid = Image.new("RGBA", (p_w, p_h), (255, 255, 255, 255))
    pd = ImageDraw.Draw(polaroid)
    pd.rectangle([0, 0, p_w, p_h], fill=(255, 253, 248, 255), outline=(210, 200, 190, 220), width=1)
    
    if MV_FRAME_PATH.exists():
        mv_im = Image.open(MV_FRAME_PATH).convert("RGBA").resize((p_w - 24, 296), Image.Resampling.LANCZOS)
    else:
        mv_im = Image.new("RGBA", (p_w - 24, 296), (25, 30, 45, 255))
    polaroid.paste(mv_im, (12, 12))
    
    pd.text((18, 326), "Agnetha @ Polar Studio 1979", fill=(70, 75, 85, 220), font=load_font(FONT_EN_NOTEWORTHY, 24, index=1))
    pd.text((350, 332), "● Official MV", fill=(160, 50, 50, 220), font=load_font(FONT_SANS, 16))
    
    pol_rot = polaroid.rotate(-2.0, expand=True, resample=Image.Resampling.BICUBIC)
    
    pshadow = Image.new("RGBA", pol_rot.size, (0, 0, 0, 0))
    for x in range(0, pol_rot.width, 2):
        for y in range(0, pol_rot.height, 2):
            if pol_rot.getpixel((x, y))[3] > 40:
                pshadow.putpixel((x, y), (35, 30, 25, 110))
    pshadow = pshadow.filter(ImageFilter.GaussianBlur(radius=10))
    
    px_pos, py_pos = 525, 182
    canvas.paste(pshadow, (px_pos + 8, py_pos + 10), pshadow)
    canvas.paste(pol_rot, (px_pos, py_pos), pol_rot)
    
    # Washi Tape
    tape = Image.new("RGBA", (140, 36), (235, 205, 130, 190))
    ImageDraw.Draw(tape).line([(0, 0), (140, 0)], fill=(255, 255, 255, 80), width=1)
    tape_rot = tape.rotate(-2.0, expand=True)
    canvas.paste(tape_rot, (px_pos + 150, py_pos - 12), tape_rot)
    
    # 3. Left Column Diary Lyrics (x=150~510) - Dynamic Bounding Box: Zero Overlap!
    font_side_en = load_font(FONT_EN_NOTEWORTHY, 32, index=1)
    font_side_zh = load_font(FONT_ZH_CALLIGRAPHY, 24)
    
    diary_items = [
        ("single", "Half past twelve,", "午夜时分孤身一人，"),
        ("single", "Watching the late show", "独看深夜电视节目，"),
        ("single", "In my flat all alone.", "空荡寓所寂寥无声。"),
        ("double", ("How I hate to spend", "the evening on my own!"), "我多讨厌独自熬过漫漫长夜！"),
    ]
    dy = 185
    for item in diary_items:
        if item[0] == "single":
            _, en, zh = item
            b_en = draw.textbbox((150, dy), en, font=font_side_en)
            draw.text((150, dy), en, fill=(150, 35, 35, 255) if "Half" in en else (35, 40, 50, 245), font=font_side_en)
            zh_y = b_en[3] + 12
            draw_mixed_text(draw, (150, zh_y), zh, font_side_zh, load_font(FONT_SANS, 21), (55, 50, 45, 245))
            b_zh = draw.textbbox((150, zh_y), zh, font=font_side_zh)
            dy = b_zh[3] + 16
        else:
            _, (l1, l2), zh = item
            b1 = draw.textbbox((150, dy), l1, font=font_side_en)
            draw.text((150, dy), l1, fill=(35, 40, 50, 245), font=font_side_en)
            l2_y = b1[3] + 6
            b2 = draw.textbbox((150, l2_y), l2, font=font_side_en)
            draw.text((150, l2_y), l2, fill=(35, 40, 50, 245), font=font_side_en)
            zh_y = b2[3] + 12
            draw_mixed_text(draw, (150, zh_y), zh, font_side_zh, load_font(FONT_SANS, 21), (55, 50, 45, 245))
            b_zh = draw.textbbox((150, zh_y), zh, font=font_side_zh)
            dy = b_zh[3] + 16
    
    draw.line([(150, 665), (1020, 665)], fill=(220, 210, 195, 180), width=1)
    
    # 4. Lower Grand Lyrics Section (y=685~1830) - 44px Noteworthy Bold, ZERO OVERLAP GUARANTEE!
    main_lyrics = [
        ("Autumn winds blowing outside the window as I look around the room", "窗外秋风呼啸，我环顾空荡冰冷的房间"),
        ("And it makes me so depressed to see the gloom", "眼前无尽的幽暗与沉寂令我深陷落寞"),
        ("There's not a soul out there, no one to hear my prayer", "四下空无一人，无人倾听我内心的低语祈求"),
        ("Gimme! Gimme! Gimme! a man after midnight!", "赐我一份怀抱，在午夜之后！"),
        ("Won't somebody help me chase the shadows away?", "难道无人能助我驱散这暗夜孤影吗？"),
        ("Take me through the darkness to the break of the day!", "带我穿透无尽黑暗，直至黎明破晓！"),
    ]
    
    cy = 685
    for i, (en, zh) in enumerate(main_lyrics):
        is_highlight = ("Gimme" in en)
        color_en = (165, 28, 28, 255) if is_highlight else (25, 30, 40, 250)
        color_zh = (45, 40, 35, 255)  # Rich, crisp, high-contrast dark fountain pen ink
        
        en_w = draw.textlength(en, font=font_lyrics_en_large)
        if en_w > 860:
            words = en.split(" ")
            mid = len(words) // 2 + 1
            line1 = " ".join(words[:mid])
            line2 = " ".join(words[mid:])
            
            # Line 1
            b1 = draw.textbbox((155, cy), line1, font=font_lyrics_en_large)
            draw.text((155, cy), line1, fill=color_en, font=font_lyrics_en_large)
            
            # Line 2: guaranteed 8px clear gap below Line 1
            line2_y = b1[3] + 8
            b2 = draw.textbbox((155, line2_y), line2, font=font_lyrics_en_large)
            draw.text((155, line2_y), line2, fill=color_en, font=font_lyrics_en_large)
            
            # Chinese Translation: guaranteed 22px clear gap below Line 2 descenders!
            zh_y = b2[3] + 22
            draw_mixed_text(draw, (155, zh_y), zh, font_lyrics_zh_large, load_font(FONT_SANS, 26), color_zh)
            b_zh = draw.textbbox((155, zh_y), zh, font=font_lyrics_zh_large)
            cy = b_zh[3] + 18
        else:
            # Single line English
            b_en = draw.textbbox((155, cy), en, font=font_lyrics_en_large)
            draw.text((155, cy), en, fill=color_en, font=font_lyrics_en_large)
            
            # Chinese Translation: guaranteed 22px clear gap below English descenders!
            zh_y = b_en[3] + 22
            draw_mixed_text(draw, (155, zh_y), zh, font_lyrics_zh_large, load_font(FONT_SANS, 26), color_zh)
            b_zh = draw.textbbox((155, zh_y), zh, font=font_lyrics_zh_large)
            cy = b_zh[3] + 18
    
    draw_pen_at(canvas, tip_x=900, tip_y=1345)
    
    draw_mixed_text(draw, (155, 1852), "• 本幕完 · 翻页进入下一乐段 »", load_font(FONT_ZH_CALLIGRAPHY, 20), load_font(FONT_ARIAL_UNICODE, 20), (130, 125, 120, 220))
    draw.text((850, 1852), "ABBA · 1979 POLAR", fill=(170, 160, 150, 200), font=load_font(FONT_SANS, 18))
    
    out_path = OUTPUT_DIR / "scheme_b_v2_lyrics_page.png"
    canvas.convert("RGB").save(out_path, quality=95)
    print(f"Lyrics page saved: {out_path}")
    return canvas


# =========================================================================
# 2. FINAL 3-SECOND VOCABULARY RECAP PAGE (FULL NOTEBOOK STUDY SUMMARY)
# =========================================================================
def build_scheme_b_vocab_end_page():
    canvas = get_base_paper()
    draw = ImageDraw.Draw(canvas)
    
    draw_notebook_holes(draw, y_start=60, y_end=1880, step=110)
    
    # 1. Full Brand Header
    logo = get_clean_logo(52)
    canvas.paste(logo, (145, 30), logo)
    draw.text((215, 34), "六维时空号", fill=(35, 40, 50, 240), font=font_brand)
    draw.line([(355, 40), (355, 66)], fill=(180, 170, 160, 180), width=2)
    draw.text((375, 39), "“不同的视角，看见更大的世界。”", fill=(130, 95, 45, 220), font=font_slogan)
    draw_mixed_text(draw, (770, 39), "✎ 音乐手账 · 终章附录 (P6/6)", load_font(FONT_ZH_CALLIGRAPHY, 20), font_slogan, (110, 115, 125, 210))
    
    # Title & Badge
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
    
    # 2. Grand Full-Page Study Manuscript (y=205~1800)
    card_w, card_h = 880, 1580
    card_bg = Image.new("RGBA", (card_w, card_h), (254, 250, 242, 255))
    cd = ImageDraw.Draw(card_bg)
    cd.rounded_rectangle([0, 0, card_w - 2, card_h - 2], radius=16, fill=(254, 250, 242, 255), outline=(215, 175, 100, 220), width=2)
    
    # Inner Ribbon Header
    cd.rounded_rectangle([25, 25, card_w - 25, 80], radius=8, fill=(245, 230, 190, 230))
    draw_mixed_text(cd, (40, 36), "◆ 本曲核心词汇与地道修辞深度解析（建议截图长久收藏）", load_font(FONT_SANS, 23), load_font(FONT_SANS, 23), (130, 50, 20, 255))
    
    # Vocabulary Entries with clean IPA Unicode font
    vocab_entries = [
        {
            "word": "flat",
            "ipa": "/flæt/",
            "pos": "n.",
            "def": "英式英语中的“公寓/套房”（美式为 apartment）",
            "note": "• 语境精析：源自古诺尔斯语，特指在一栋建筑内独占一整层的居住单元。歌词中'in my flat all alone'写尽了城市单身青年独居的疏离与孤寂感。",
        },
        {
            "word": "on one's own",
            "ipa": "/ɒn wʌnz əʊn/",
            "pos": "phr.",
            "def": "独自一人，孤立无援",
            "note": "• 辨析：不同于中性的 alone，'on my own'强烈突显'无人伸出援手、独自苦苦支撑'的情感色彩。例句：How I hate to spend the evening on my own!（我多讨厌独自熬过漫漫长夜！）",
        },
        {
            "word": "gloom",
            "ipa": "/ɡluːm/",
            "pos": "n.",
            "def": "幽暗，昏暗；引申为“压抑、沮丧的心境”",
            "note": "• 词源引申：与 gleam（微光）同源但走向相反，表光明被完全吞噬的绝望感。在文学中常借物理上的昏暗天色，映照人物内心被虚空笼罩的阴郁。",
        },
        {
            "word": "chase the shadows away",
            "ipa": "/tʃeɪs ðə ˈʃædəʊz əˈweɪ/",
            "pos": "idiom.",
            "def": "驱散心头的阴影与恐惧",
            "note": "• 修辞：拟人隐喻修辞法。将深夜独处的恐惧与胡思乱想具象化为'潜伏的阴影'（shadows），而真诚的爱与陪伴则是驱散这些暗影的唯一日光。",
        },
        {
            "word": "not a soul",
            "ipa": "/nɒt ə səʊl/",
            "pos": "idiom.",
            "def": "连一个人都没有",
            "note": "• 文学提炼：以 soul（灵魂）借代 living person（活人），源自戏剧与诗歌传统。四下万籁俱寂，连一个具有生命温度的灵魂都寻觅不到，道尽极致孤独。",
        },
        {
            "word": "break of the day",
            "ipa": "/breɪk əv ðə deɪ/",
            "pos": "phr.",
            "def": "拂晓时分，黎明破晓之际",
            "note": "• 意象：等同于 daybreak 或 dawn。黑夜终会破裂，光明必将透入。表达在绝境中对新生、清醒与黎明的坚韧守望。",
        },
    ]
    
    font_ipa = load_font(FONT_ARIAL_UNICODE, 22)
    font_entry_zh = load_font(FONT_ZH_CALLIGRAPHY, 25)
    font_entry_note = load_font(FONT_ZH_CALLIGRAPHY, 23)
    
    vy = 110
    for item in vocab_entries:
        # Word
        w_text = f"【{item['word']}】"
        draw_mixed_text(cd, (30, vy), w_text, load_font(FONT_EN_NOTEWORTHY, 32, index=1), load_font(FONT_SANS, 26), (160, 30, 30, 255))
        w_len = cd.textlength(w_text, font=load_font(FONT_EN_NOTEWORTHY, 32, index=1))
        
        # IPA
        cd.text((30 + w_len + 10, vy + 4), item["ipa"], fill=(25, 75, 140, 240), font=font_ipa)
        ipa_len = cd.textlength(item["ipa"], font=font_ipa)
        
        # POS & Def
        pos_def = f"   {item['pos']}   {item['def']}"
        draw_mixed_text(cd, (30 + w_len + 10 + ipa_len, vy + 4), pos_def, font_entry_zh, font_ipa, (40, 50, 65, 240))
        
        # Note
        draw_mixed_text(cd, (35, vy + 48), item["note"], font_entry_note, load_font(FONT_SANS, 20), (105, 95, 85, 230))
        
        cd.line([(30, vy + 125), (card_w - 30, vy + 125)], fill=(225, 215, 200, 180), width=1)
        vy += 140
    
    # Historical Accolade & Sampling Note at bottom of card
    cd.rounded_rectangle([30, vy + 15, card_w - 30, vy + 130], radius=10, fill=(242, 246, 252, 255), outline=(170, 195, 230, 200), width=1)
    draw_mixed_text(cd, (45, vy + 28), "★ 乐史典故与采样回响（Cultural Legacy & Sampling）：", load_font(FONT_SANS, 22), load_font(FONT_SANS, 22), (25, 80, 150, 255))
    sampling_text = "Benny 在 ARP 合成器上写出的前奏被誉为流行乐史神级 Riff。2005 年麦当娜为单曲《Hung Up》亲自致信 ABBA 恳请采样授权，最终横扫全球 41 国单曲榜冠军，跨越四分之一世纪再度封神。"
    draw_mixed_text(cd, (45, vy + 68), sampling_text, load_font(FONT_ZH_CALLIGRAPHY, 24), load_font(FONT_SANS, 21), (70, 75, 85, 230))
    
    canvas.paste(card_bg, (145, 205), card_bg)
    
    draw.text((155, 1850), "✎ 研读完毕 · 关注六维时空号，戴上耳机与好歌同行", fill=(140, 135, 130, 220), font=load_font(FONT_SANS, 20))
    draw.text((800, 1850), "COSMIC EYE ARCHIVE", fill=(170, 160, 150, 200), font=load_font(FONT_SANS, 18))
    
    out_path = OUTPUT_DIR / "scheme_b_v2_vocab_end_page.png"
    canvas.convert("RGB").save(out_path, quality=95)
    print(f"Vocab page saved: {out_path}")
    return canvas


# =========================================================================
# 3. BUILD SIDE-BY-SIDE OVERVIEW
# =========================================================================
def build_overview(im_lyrics, im_vocab):
    thumb_w, thumb_h = 540, 960
    t_l = im_lyrics.resize((thumb_w, thumb_h), Image.Resampling.LANCZOS)
    t_v = im_vocab.resize((thumb_w, thumb_h), Image.Resampling.LANCZOS)
    
    grid_w = thumb_w * 2 + 60
    grid_h = thumb_h + 120
    grid = Image.new("RGBA", (grid_w, grid_h), (242, 238, 228, 255))
    gd = ImageDraw.Draw(grid)
    
    gd.text((25, 22), "ABBA《Gimme! Gimme! Gimme!》方案 B 升级版架构（正片伴读页 + 尾声 3 秒研读精萃页）", fill=(30, 35, 45, 255), font=load_font(FONT_SANS, 26))
    
    gd.text((25, 72), "【正片伴读页】去底卡释放 1200px 空间 · 44px 粗体大字号 · 零挤占零缩小", fill=(140, 40, 25, 255), font=load_font(FONT_SANS, 18))
    gd.text((thumb_w + 40, 72), "【尾声 3 秒整理页】完整头尾手账 · 全画幅 6 组核心词汇音标精解", fill=(30, 85, 150, 255), font=load_font(FONT_SANS, 18))
    
    grid.paste(t_l, (20, 105))
    grid.paste(t_v, (thumb_w + 40, 105))
    
    out_path = OUTPUT_DIR / "scheme_b_v2_comparison_overview.png"
    grid.convert("RGB").save(out_path, quality=95)
    print(f"Overview saved: {out_path}")


if __name__ == "__main__":
    p_l = build_scheme_b_lyrics_page()
    p_v = build_scheme_b_vocab_end_page()
    build_overview(p_l, p_v)
