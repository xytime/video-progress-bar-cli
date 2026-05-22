#!/usr/bin/env python3
import os
import argparse
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# 1080x1920 (竖屏标准分辨率)
W, H = 1080, 1920

def get_font_path():
    paths = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
    ]
    for p in paths:
        if os.path.exists(p):
            return p
    return None

FONT_PATH = get_font_path()

def get_font(size, weight="regular"):
    if not FONT_PATH: 
        return ImageFont.load_default()
    try:
        if "PingFang" in FONT_PATH:
            idx = 5 if weight == "bold" else 0 # 5=Semibold, 0=Regular
            if weight == "black": idx = 4 # Heavy
            return ImageFont.truetype(FONT_PATH, size, index=idx)
        return ImageFont.truetype(FONT_PATH, size)
    except:
        return ImageFont.load_default()

def draw_text_centered(draw, text, font, y, fill):
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    x = (W - w) / 2
    draw.text((x, y), text, font=font, fill=fill)
    return bbox[3] - bbox[1]

def split_text_by_width(text, font, max_width):
    """按像素宽度智能折行，绝不打断英文单词"""
    import re
    # 分离出所有的单词、汉字、标点
    tokens = re.findall(r'[a-zA-Z0-9]+|[^a-zA-Z0-9]', text)
    lines = []
    current_line = ""
    
    # 忽略前导空格
    tokens = [t for t in tokens if t != ""]
    
    for token in tokens:
        test_line = current_line + token
        # 去除开头可能多出的空格用于测试宽度
        bbox = font.getbbox(test_line.strip())
        width = bbox[2] - bbox[0] if bbox else 0
        
        if width <= max_width:
            current_line = test_line
        else:
            if current_line.strip():
                lines.append(current_line.strip())
            # 如果单个 token 已经超过最大宽度（比如超长英文），没办法只能硬塞
            current_line = token.lstrip()
            
    if current_line.strip():
        lines.append(current_line.strip())
    return lines

def generate_cover(title: str, output_path: str):
    # Base dark background
    img = Image.new('RGBA', (W, H), color='#030712')
    
    # Draw ambient glowing orbs
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
    
    # Translucent fill + stroke for glassmorphism
    c_draw.rounded_rectangle([margin, cy, margin+cw, cy+ch], radius=60, fill=(255,255,255,15), outline=(255,255,255,60), width=4)
    
    # Badge inside card
    badge_font = get_font(50, "bold")
    c_draw.rounded_rectangle([W/2 - 180, cy + 80, W/2 + 180, cy + 180], radius=50, fill=(255,255,255,255))
    draw_text_centered(c_draw, "TECH INSIGHTS", badge_font, cy + 105, fill='#0f172a')
    
    # Determine Main Font and Split Text by pixel width
    font_main = get_font(130, "black")
    max_text_width = cw - 120 # Leave padding inside the card
    lines = split_text_by_width(title, font_main, max_text_width)
    
    # Render lines (always use same font size)
    total_text_height = sum([font_main.getbbox(l)[3] - font_main.getbbox(l)[1] for l in lines]) + (len(lines)-1)*40
    current_y = cy + 250 + (500 - total_text_height)/2 # Center vertically in the remaining space
    
    for line in lines:
        h = draw_text_centered(c_draw, line, font_main, current_y, fill='#ffffff')
        current_y += h + 40
            
    # Composite card
    img = Image.alpha_composite(img, card)
    
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.convert('RGB').save(out_path, quality=95)
    print(f"Cover generated: {out_path}")

def main():
    parser = argparse.ArgumentParser(description="Generate video cover (V5 Glassmorphism).")
    parser.add_argument("--title", required=True, help="Video title")
    parser.add_argument("--video", help="Video path (ignored, just for compat)")
    parser.add_argument("--output", required=True, help="Output image path (.jpg)")
    args = parser.parse_args()
    
    generate_cover(args.title, args.output)

if __name__ == "__main__":
    main()
