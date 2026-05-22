import os
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

W, H = 1080, 1920
OUT_DIR = Path("output/covers_demo")
OUT_DIR.mkdir(parents=True, exist_ok=True)

font_paths = [
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
]
FONT_PATH = None
for p in font_paths:
    if os.path.exists(p):
        FONT_PATH = p
        break

def get_font(size, weight="regular"):
    if not FONT_PATH: return ImageFont.load_default()
    try:
        if "PingFang" in FONT_PATH:
            idx = 5 if weight == "bold" else 0 # 5 is Semibold, 0 is Regular, 6 is Medium
            if weight == "black": idx = 4 # Heavy
            return ImageFont.truetype(FONT_PATH, size, index=idx)
        return ImageFont.truetype(FONT_PATH, size)
    except:
        return ImageFont.load_default()

def draw_text_centered(draw, text, font, y, fill, stroke_width=0, stroke_fill=None):
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    x = (W - w) / 2
    draw.text((x, y), text, font=font, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill)
    return bbox[3] - bbox[1]

# ── V1: 基础高对比度 (Base High Contrast) ──
# 简单粗暴，黑底白字，确保在极小尺寸下依然清晰可读。
def make_v1():
    img = Image.new('RGB', (W, H), color='#111111')
    draw = ImageDraw.Draw(img)
    font = get_font(120, "bold")
    
    y = H/2 - 200
    for line in ["AI重塑未来", "2026企业级AI", "爆发式增长"]:
        h = draw_text_centered(draw, line, font, y, fill='#FFFFFF')
        y += h + 40
    img.save(OUT_DIR / "v1_contrast.jpg", quality=90)

# ── V2: 视觉层级与高亮 (Visual Hierarchy & Highlight) ──
# 按照缩略图设计原则，区分主次。用极致的亮黄色抓住眼球，副标题用白色。
def make_v2():
    img = Image.new('RGB', (W, H), color='#0a0a0a')
    draw = ImageDraw.Draw(img)
    
    # Main hook
    font_main = get_font(180, "black")
    h1 = draw_text_centered(draw, "AI重塑未来", font_main, H/2 - 300, fill='#facc15') # Canva Yellow
    
    # Subtitle
    font_sub = get_font(90, "bold")
    draw_text_centered(draw, "2026企业级AI的", font_sub, H/2 - 300 + h1 + 60, fill='#f8fafc')
    draw_text_centered(draw, "爆发式增长与落地实践", font_sub, H/2 - 300 + h1 + 180, fill='#94a3b8')
    
    img.save(OUT_DIR / "v2_hierarchy.jpg", quality=90)

# ── V3: 动感与张力 (Dynamic & Tension) ──
# 引入对角线/斜切元素，打破画面的平静，营造“速度、突破”的视觉心理暗示。
def make_v3():
    img = Image.new('RGB', (W, H), color='#020617') # Very dark slate
    draw = ImageDraw.Draw(img)
    
    # Draw a bold diagonal slash in the background
    draw.polygon([(0, 400), (W, 200), (W, 900), (0, 1100)], fill='#b91c1c') # Deep Red
    
    font_main = get_font(190, "black")
    font_sub = get_font(90, "bold")
    
    # We add a heavy stroke (shadow) so it pops off the red background
    h1 = draw_text_centered(draw, "AI重塑未来", font_main, H/2 - 350, fill='#ffffff', stroke_width=8, stroke_fill='#000000')
    
    draw_text_centered(draw, "2026 企业级AI", font_sub, H/2 - 350 + h1 + 80, fill='#fef08a', stroke_width=5, stroke_fill='#000000')
    draw_text_centered(draw, "爆发式增长实战", font_sub, H/2 - 350 + h1 + 200, fill='#fef08a', stroke_width=5, stroke_fill='#000000')
    
    img.save(OUT_DIR / "v3_dynamic.jpg", quality=90)

# ── V4: 深度与质感 (Depth & Texture) ──
# 背景加入网格质感（Tech Grid），文字加入发光特效，营造高级科技感。
def make_v4():
    img = Image.new('RGB', (W, H), color='#0f172a') # Dark blue
    draw = ImageDraw.Draw(img)
    
    # Draw Tech Grid
    for i in range(0, W, 80):
        draw.line([(i, 0), (i, H)], fill='#1e293b', width=2)
    for i in range(0, H, 80):
        draw.line([(0, i), (W, i)], fill='#1e293b', width=2)
        
    font_main = get_font(180, "black")
    font_sub = get_font(100, "bold")
    
    # Simulate text glow by drawing multiple layers of blurred text behind
    glow_img = Image.new('RGBA', (W, H), (0,0,0,0))
    glow_draw = ImageDraw.Draw(glow_img)
    draw_text_centered(glow_draw, "AI重塑未来", font_main, H/2 - 350, fill='#38bdf8')
    glow_img = glow_img.filter(ImageFilter.GaussianBlur(30))
    
    img.paste(glow_img, (0,0), glow_img)
    
    # Actual text
    h1 = draw_text_centered(draw, "AI重塑未来", font_main, H/2 - 350, fill='#ffffff')
    draw_text_centered(draw, "2026 企业级落地", font_sub, H/2 - 350 + h1 + 100, fill='#38bdf8')
    
    img.save(OUT_DIR / "v4_depth.jpg", quality=95)

# ── V5: 情绪化色彩+微玻璃态 (Emotion Color & Glassmorphism) ──
# 最顶级的流行设计。高饱和度环境光晕 + 玻璃态卡片框住内容，极具高端“大厂”调性。
def make_v5():
    img = Image.new('RGBA', (W, H), color='#030712')
    
    # Ambient glowing orbs
    orbs = Image.new('RGBA', (W, H), (0,0,0,0))
    o_draw = ImageDraw.Draw(orbs)
    o_draw.ellipse([-400, 200, 800, 1400], fill=(147, 51, 234, 180)) # Purple
    o_draw.ellipse([400, 800, 1600, 2000], fill=(59, 130, 246, 180)) # Blue
    orbs = orbs.filter(ImageFilter.GaussianBlur(200))
    img = Image.alpha_composite(img, orbs)
    
    # Glass Card
    card = Image.new('RGBA', (W, H), (0,0,0,0))
    c_draw = ImageDraw.Draw(card)
    margin = 80
    cw = W - margin*2
    ch = 900
    cy = H/2 - ch/2
    
    # Translucent fill + stroke
    c_draw.rounded_rectangle([margin, cy, margin+cw, cy+ch], radius=60, fill=(255,255,255,15), outline=(255,255,255,60), width=4)
    
    # Badge inside card
    badge_font = get_font(50, "bold")
    c_draw.rounded_rectangle([W/2 - 180, cy + 80, W/2 + 180, cy + 180], radius=50, fill=(255,255,255,255))
    draw_text_centered(c_draw, "TECH INSIGHTS", badge_font, cy + 105, fill='#0f172a')
    
    # Main Text
    font_main = get_font(180, "black")
    h1 = draw_text_centered(c_draw, "AI重塑", font_main, cy + 280, fill='#ffffff')
    draw_text_centered(c_draw, "商业未来", font_main, cy + 280 + h1 + 20, fill='#ffffff')
    
    # Sub Text
    font_sub = get_font(70, "bold")
    draw_text_centered(c_draw, "2026 企业级应用爆发指南", font_sub, cy + ch - 160, fill=(255,255,255,200))
    
    img = Image.alpha_composite(img, card)
    img.convert('RGB').save(OUT_DIR / "v5_glassmorphism.jpg", quality=95)

if __name__ == "__main__":
    make_v1()
    make_v2()
    make_v3()
    make_v4()
    make_v5()
    print("All covers generated in output/covers_demo/")
