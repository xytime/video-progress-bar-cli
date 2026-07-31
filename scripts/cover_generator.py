#!/usr/bin/env python3
"""封面图像生成服务 (cover_generator.py)

# Modification History
| Version | Date       | Author                       | Description                                                     |
|---------|------------|------------------------------|-----------------------------------------------------------------|
| 1.0.0   | 2026-05-24 | Claude_Sonnet_4.6_Thinking   | Pillow 基础玻璃态排版绘制                                        |
| 2.0.0   | 2026-05-26 | Gemini_3.5_Flash_planning    | 增加 --payload 参数，支持集成 CoverEngine v2.0，且保留 Pillow 兜底  |
| 2.1.0   | 2026-07-29 | Codex                        | 优先从已渲染竖版成片取真实画面，保留片头标题/日期戳生成内容贴合封面 |
| 2.2.0   | 2026-07-29 | Codex                        | 消费独立视觉策划 JSON，为真实视频封面注入题材化色彩和可审计产物      |
| 2.3.0   | 2026-07-30 | Codex                        | 仅按已确认的成片音轨版本渲染配音角标，杜绝字幕版误标为译制版          |
| 2.3.1   | 2026-07-31 | Codex                        | 角标文案改为普通话译制并采用右上角彩带样式，确保文字完整可见          |
| 2.4.0   | 2026-07-31 | Codex                        | 禁止视频截帧封面，并为专门生成封面写入可验证来源清单                  |
| 2.5.0   | 2026-07-31 | Codex                        | 支持独立主视觉资产，并将实际渲染语义写回可审计封面简报                |
| 2.6.0   | 2026-07-31 | Codex                        | 独立主视觉合成失败时禁止静默回退，避免默认图伪装为已使用 AI 底图       |
"""

import os
import sys
import json
import argparse
import hashlib
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# 旧 Pillow 兜底海报的竖屏标准分辨率。
W, H = 1080, 1920
# 视频号等平台使用的 6:7 封面安全尺寸。
COVER_W, COVER_H = 1080, 1260

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
    font_size = 130
    font_main = get_font(font_size, "black")
    max_text_width = cw - 120 # Leave padding inside the card
    lines = split_text_by_width(title, font_main, max_text_width)
    
    # [Gemini_3.1_Pro_High_planning] 增加基于 Y 坐标的高度衰减算法，防止超长文本溢出边界
    total_text_height = sum([font_main.getbbox(l)[3] - font_main.getbbox(l)[1] for l in lines]) + (len(lines)-1)*40
    while total_text_height > 600 and font_size > 40:
        font_size -= 10
        font_main = get_font(font_size, "black")
        lines = split_text_by_width(title, font_main, max_text_width)
        total_text_height = sum([font_main.getbbox(l)[3] - font_main.getbbox(l)[1] for l in lines]) + (len(lines)-1)*40

    # Render lines (always use same font size)
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


def _hex_to_rgb(color: str, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
    value = str(color or "").strip().lstrip("#")
    if len(value) != 6:
        return fallback
    try:
        return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))
    except ValueError:
        return fallback


def _draw_cover_title(image: Image.Image, title: str, brief: dict | None = None) -> None:
    """在封面头部重绘短标题，避免历史缓存成片没有片头标题时留出黑区。"""
    if not title.strip():
        return
    has_creative_brief = brief is not None
    brief = brief or {}
    draw = ImageDraw.Draw(image)
    accent_color = _hex_to_rgb(brief.get("accent_color", ""), (242, 201, 76))
    title_color = _hex_to_rgb(brief.get("title_color", ""), (245, 245, 243))
    secondary_title_color = _hex_to_rgb(brief.get("secondary_title_color", ""), accent_color)
    badge = str(brief.get("badge") or "").strip()
    if has_creative_brief and badge:
        badge_font = get_font(30, "bold")
        draw.rounded_rectangle((82, 28, 82 + 38 + badge_font.getlength(badge), 72), radius=10, fill=accent_color)
        draw.text((101, 34), badge, font=badge_font, fill="#101418")
    if has_creative_brief:
        draw.rectangle((42, 30, 56, 300), fill=accent_color)
    max_width = COVER_W - 100
    font_size = 86
    lines = []
    while font_size >= 46:
        font = get_font(font_size, "black")
        lines = split_text_by_width(title, font, max_width)
        if len(lines) <= 2:
            break
        font_size -= 4
    lines = lines[:2]
    if not lines:
        return
    line_heights = [font.getbbox(line)[3] - font.getbbox(line)[1] for line in lines]
    total_height = sum(line_heights) + (len(lines) - 1) * 16
    y = max(90 if has_creative_brief and badge else 36, (330 - total_height) // 2)
    for index, (line, height) in enumerate(zip(lines, line_heights)):
        bbox = draw.textbbox((0, 0), line, font=font)
        x = (COVER_W - (bbox[2] - bbox[0])) // 2
        draw.text((x, y), line, font=font, fill=title_color if index == 0 else secondary_title_color)
        y += height + 16


def resolve_edition_label(payload: dict) -> str:
    """把可审计的音轨版本映射为封面角标，拒绝消费任意自由文本。"""
    return "普通话译制" if payload.get("audio_edition") == "mandarin_dubbed" else ""


def _draw_edition_label(image: Image.Image, edition_label: str) -> None:
    """在右上角用彩带标注真实的译制版本；空标签表示原声字幕版。"""
    if not edition_label:
        return
    draw = ImageDraw.Draw(image)
    font = get_font(34, "bold")
    text_bbox = draw.textbbox((0, 0), edition_label, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    pad_x, pad_y = 26, 15
    right, top = COVER_W - 28, 24
    body_width = max(238, text_width + pad_x * 2)
    left, bottom = right - body_width, top + text_height + pad_y * 2
    notch = 18
    shadow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    ribbon = [
        (left + notch, top),
        (right - 14, top),
        (right, top + 12),
        (right, bottom),
        (left + notch, bottom),
        (left, (top + bottom) // 2),
    ]
    shadow_draw.polygon([(x + 4, y + 5) for x, y in ribbon], fill=(0, 0, 0, 86))
    image.alpha_composite(shadow) if image.mode == "RGBA" else image.paste(
        Image.alpha_composite(image.convert("RGBA"), shadow).convert("RGB")
    )
    draw = ImageDraw.Draw(image)
    draw.polygon(ribbon, fill="#b1124a")
    draw.polygon(
        [(right - 40, bottom), (right, bottom), (right - 16, bottom + 20), (right - 56, bottom + 20)],
        fill="#6f0f2f",
    )
    draw.line([(left + notch, top), (right - 14, top)], fill="#f7a8c3", width=2)
    text_x = left + notch + (body_width - notch - text_width) // 2
    text_y = top + pad_y - text_bbox[1]
    draw.text((text_x, text_y), edition_label, font=font, fill="#ffffff")


def _write_cover_provenance(output_path: str, provenance_output: str | None, payload: dict) -> None:
    """为封面写入不可把视频帧冒充为专门设计图的来源证明。"""
    if not provenance_output:
        return
    cover_path = Path(output_path)
    digest = hashlib.sha256(cover_path.read_bytes()).hexdigest()
    provenance_path = Path(provenance_output)
    provenance_path.parent.mkdir(parents=True, exist_ok=True)
    visual_asset_path = str(payload.get("visual_asset_path", "") or "").strip()
    visual_asset = Path(visual_asset_path) if visual_asset_path else None
    visual_asset_payload = None
    if visual_asset and visual_asset.is_file():
        visual_asset_payload = {
            "filename": visual_asset.name,
            "sha256": hashlib.sha256(visual_asset.read_bytes()).hexdigest(),
            "kind": "dedicated_generated_visual",
        }
    provenance_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "cover_kind": "dedicated_generated_image",
                "uses_video_frame": False,
                "cover_filename": cover_path.name,
                "cover_sha256": digest,
                "audio_edition": payload.get("audio_edition", "original_audio_subtitled"),
                "visual_asset": visual_asset_payload,
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )


def _applied_creative_brief(payload: dict, layout: dict) -> dict:
    """只记录真正送入模板的视觉决策，避免审计与成图语义漂移。"""
    visual_asset_path = str(layout.get("visual_asset_path", "") or "").strip()
    return {
        "schema_version": 1,
        "style_id": layout["style_id"],
        "badge": layout["badge"],
        "template_variant": layout["template_variant"],
        "headline_position": layout["headline_position"],
        "has_visual_asset": layout["has_visual_asset"],
        "visual_asset_filename": Path(visual_asset_path).name if visual_asset_path else None,
        "visual_keywords": list(payload.get("content_hints", []) or []),
        "visual_direction": str(payload.get("visual_direction", "") or "").strip(),
    }


def main():
    # [Gemini_3.5_Flash_planning] 支持 --payload 参数接入 CoverEngine v2.0，同时支持 Pillow 降级兜底
    parser = argparse.ArgumentParser(description="Generate a dedicated non-frame video cover.")
    parser.add_argument("--title", help="Video title (fallback Pillow generator)")
    parser.add_argument("--payload", help="JSON payload for Cover Engine v2.0")
    parser.add_argument("--content-aware", action="store_true", help="Apply the deterministic content-aware creative brief")
    parser.add_argument("--brief-output", help="Write the applied creative brief JSON after a successful render")
    parser.add_argument("--provenance-output", help="Write dedicated-cover provenance JSON")
    parser.add_argument("--output", required=True, help="Output image path (.jpg)")
    args = parser.parse_args()
    payload = {}
    if args.payload:
        try:
            payload = json.loads(args.payload)
        except json.JSONDecodeError:
            payload = {}
    title_to_use = args.title or str(payload.get("title") or "")
    creative_brief_requested = False
    creative_brief = None
    if args.content_aware:
        try:
            sys.path.append(str(Path(__file__).parent.parent / "src"))
            from cover import validate_cover_brief_input

            validation = validate_cover_brief_input(payload)
            if validation.ok:
                creative_brief_requested = True
                if validation.warnings:
                    print(f"Cover brief warnings: {', '.join(validation.warnings)}")
            else:
                print(f"Content-aware cover unavailable: {', '.join(validation.warnings)}")
        except Exception as e:
            print(f"Content-aware cover briefing unavailable: {e}")

    def persist_creative_brief() -> None:
        if creative_brief is not None and args.brief_output:
            brief_path = Path(args.brief_output)
            brief_path.parent.mkdir(parents=True, exist_ok=True)
            brief_path.write_text(json.dumps(creative_brief, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.payload:
        try:
            # 引入项目 src 目录
            sys.path.append(str(Path(__file__).parent.parent / "src"))
            from cover import CoverEngine
            
            print(f"Using CoverEngine v2.0 (Playwright HTML) for payload: {payload}")
            engine = CoverEngine()
            layout = engine.generate(payload, args.output)
            if creative_brief_requested:
                creative_brief = _applied_creative_brief(payload, layout)
                print(f"Content-aware cover style: {creative_brief['style_id']}")
            persist_creative_brief()
            _write_cover_provenance(args.output, args.provenance_output, payload)
            return
        except Exception as e:
            # 有独立底图时，Pillow 回退会丢失底图却仍可能写出来源证明，必须失败关闭。
            if str(payload.get("visual_asset_path", "") or "").strip():
                raise RuntimeError(
                    "Dedicated visual composition failed; refusing to fall back to a default cover."
                ) from e
            # [Gemini_3.5_Flash_planning] 无独立主视觉时可降级，避免普通封面链路被浏览器故障阻断。
            print(f"Error running CoverEngine v2.0: {e}. Falling back to Pillow.")
            
    # Pillow 渲染流程
    title_to_use = args.title
    if not title_to_use and args.payload:
        try:
            title_to_use = payload.get("title", "Untitled")
        except Exception:
            title_to_use = "Untitled"
            
    if not title_to_use:
        parser.error("Either --title or --payload is required")
        
    generate_cover(title_to_use, args.output)
    persist_creative_brief()
    _write_cover_provenance(args.output, args.provenance_output, payload)

if __name__ == "__main__":
    main()
