#!/usr/bin/env python3
"""Generate platform-compliant high-prestige covers for David Kushner - Daylight."""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter
from video_processing.handwritten_pager.canvas_builder import CanvasBuilder
from video_processing.handwritten_pager.contracts import HandwrittenPagerConfig
from video_processing.handwritten_pager.daylight_pages import get_daylight_pages_data, render_daylight_page_canvas

PROJECT_ROOT = Path(__file__).resolve().parent.parent
work_dir = PROJECT_ROOT / "output/handwritten_pager/daylight"
covers_dir = work_dir / "covers"
covers_dir.mkdir(parents=True, exist_ok=True)

builder = CanvasBuilder(HandwrittenPagerConfig())
pages = get_daylight_pages_data()
page1_canvas, _ = render_daylight_page_canvas(pages[0], builder)

# 1. WeChat 9:16 (1080x1920)
wechat_path = covers_dir / "cover_wechat_9_16.jpg"
page1_canvas.convert("RGB").save(wechat_path, "JPEG", quality=95)
print(f"WeChat 9:16 cover saved: {wechat_path}")

# 2. Douyin 3:4 (1080x1440) - Physical Stationery Desk Mockup (Strictly anti-screenshot)
DESK_W, DESK_H = 1080, 1440
desk_bg = Image.new("RGBA", (DESK_W, DESK_H), (232, 226, 216, 255))
desk_draw = ImageDraw.Draw(desk_bg)

# Wood grain / linen desk texture
for dy in range(0, DESK_H, 6):
    alpha = int(12 + 10 * ((dy % 18) / 18.0))
    desk_draw.line([(0, dy), (DESK_W, dy)], fill=(195, 185, 172, alpha), width=1)

# Notebook page on desk
scale = 0.90
crop_h = 1520
page_cropped = page1_canvas.crop((0, 0, 1080, crop_h))
target_w = int(1080 * scale)
target_h = int(crop_h * scale)
page_scaled = page_cropped.resize((target_w, target_h), Image.Resampling.LANCZOS)

# Deep physical shadow
shadow_pad = 70
shadow_canvas = Image.new("RGBA", (DESK_W, DESK_H), (0, 0, 0, 0))
s_draw = ImageDraw.Draw(shadow_canvas)
px = (DESK_W - target_w) // 2
py = 55
s_draw.rectangle([px + 12, py + 18, px + target_w + 12, py + target_h + 20], fill=(45, 38, 30, 145))
s_draw.rectangle([px + 6, py + 8, px + target_w + 6, py + target_h + 10], fill=(25, 20, 15, 90))
shadow_blurred = shadow_canvas.filter(ImageFilter.GaussianBlur(radius=24))

mockup = Image.alpha_composite(desk_bg, shadow_blurred)
mockup.paste(page_scaled, (px, py), page_scaled)

# Subtle vignette border
vignette = Image.new("RGBA", (DESK_W, DESK_H), (0, 0, 0, 0))
v_draw = ImageDraw.Draw(vignette)
v_draw.rectangle([0, 0, DESK_W, DESK_H], outline=(140, 125, 110, 80), width=4)
mockup = Image.alpha_composite(mockup, vignette)

douyin_3_4_path = covers_dir / "cover_douyin_3_4.jpg"
mockup.convert("RGB").save(douyin_3_4_path, "JPEG", quality=95)
print(f"Douyin 3:4 desk mockup cover saved: {douyin_3_4_path}")

# 3. Douyin 4:3 (1440x1080) - Open Journal Double-Page Spread
SPREAD_W, SPREAD_H = 1440, 1080
spread_bg = Image.new("RGBA", (SPREAD_W, SPREAD_H), (228, 222, 212, 255))
spread_draw = ImageDraw.Draw(spread_bg)
for dy in range(0, SPREAD_H, 6):
    alpha = int(12 + 8 * ((dy % 18) / 18.0))
    spread_draw.line([(0, dy), (SPREAD_W, dy)], fill=(190, 180, 168, alpha), width=1)

page2_canvas, _ = render_daylight_page_canvas(pages[1], builder)
scale_s = 0.62
p_w, p_h = int(1080 * scale_s), int(1520 * scale_s)
p1_s = page1_canvas.crop((0, 0, 1080, 1520)).resize((p_w, p_h), Image.Resampling.LANCZOS)
p2_s = page2_canvas.crop((0, 0, 1080, 1520)).resize((p_w, p_h), Image.Resampling.LANCZOS)

# Shadows for both pages
s_spread = Image.new("RGBA", (SPREAD_W, SPREAD_H), (0, 0, 0, 0))
ss_draw = ImageDraw.Draw(s_spread)
p1_x, p1_y = 45, 68
p2_x, p2_y = 725, 68
ss_draw.rectangle([p1_x + 8, p1_y + 12, p1_x + p_w + 8, p1_y + p_h + 14], fill=(40, 35, 28, 120))
ss_draw.rectangle([p2_x + 8, p2_y + 12, p2_x + p_w + 8, p2_y + p_h + 14], fill=(40, 35, 28, 120))
s_spread_blurred = s_spread.filter(ImageFilter.GaussianBlur(radius=20))

spread_final = Image.alpha_composite(spread_bg, s_spread_blurred)
spread_final.paste(p1_s, (p1_x, p1_y), p1_s)
spread_final.paste(p2_s, (p2_x, p2_y), p2_s)

# Spine shadow in the middle
spine = Image.new("RGBA", (SPREAD_W, SPREAD_H), (0, 0, 0, 0))
sp_draw = ImageDraw.Draw(spine)
sp_draw.line([(715, 68), (715, 68 + p_h)], fill=(60, 50, 40, 110), width=6)
spine_blur = spine.filter(ImageFilter.GaussianBlur(radius=6))
spread_final = Image.alpha_composite(spread_final, spine_blur)

douyin_4_3_path = covers_dir / "cover_douyin_4_3.jpg"
spread_final.convert("RGB").save(douyin_4_3_path, "JPEG", quality=95)
print(f"Douyin 4:3 open spread cover saved: {douyin_4_3_path}")
