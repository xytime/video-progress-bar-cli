"""视频号封面批量重制与生成脚本 (Review Batch)

# Modification History
| Version | Date       | Author                       | Description                                                     |
|---------|------------|------------------------------|-----------------------------------------------------------------|
| 1.0.0   | 2026-05-26 | Gemini_3.5_Flash_planning    | 初始创建，支持内容感知主题色、主副标题双层结构与网格点阵视觉效果  |
| 1.1.0   | 2026-05-26 | Gemini_3.5_Flash_planning    | 优化视频10的标题与副标题，修正翻译腔，重新渲染封面图像及更新报告  |
| 1.2.0   | 2026-05-26 | Gemini_3.5_Flash_planning    | 优化视频2的标题与副标题，去营销套路化，重新渲染封面图像及更新报告  |
"""

import os
import shutil
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# 1080x1920 (微信视频号竖屏标准分辨率)
W, H = 1080, 1920

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
    if not FONT_PATH:
        return ImageFont.load_default()
    try:
        if "PingFang" in FONT_PATH:
            idx = 5 if weight == "bold" else 0  # 5=Semibold, 0=Regular
            if weight == "black":
                idx = 4  # Heavy
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
    """按像素宽度智能折行，不打断英文单词"""
    import re
    tokens = re.findall(r'[a-zA-Z0-9]+|[^a-zA-Z0-9]', text)
    lines = []
    current_line = ""
    
    tokens = [t for t in tokens if t != ""]
    for token in tokens:
        test_line = current_line + token
        bbox = font.getbbox(test_line.strip())
        width = bbox[2] - bbox[0] if bbox else 0
        
        if width <= max_width:
            current_line = test_line
        else:
            if current_line.strip():
                lines.append(current_line.strip())
            current_line = token.lstrip()
            
    if current_line.strip():
        lines.append(current_line.strip())
    return lines

# [Gemini_3.5_Flash_planning] 主题配色映射配置表
THEME_CONFIGS = {
    "robotics_tech": {
        "bg_color_start": "#030712",
        "bg_color_end": "#0b0f19",
        "orb_colors": [
            {"center": (-200, 300), "radius": 700, "color": (56, 189, 248, 160)},  # Neon Blue
            {"center": (W + 200, H - 300), "radius": 700, "color": (168, 85, 247, 160)}  # Amethyst Purple
        ],
        "grid_color": (56, 189, 248, 15),
        "accent_color": "#38bdf8"
    },
    "market_capital": {
        "bg_color_start": "#020202",
        "bg_color_end": "#121212",
        "orb_colors": [
            {"center": (W + 200, 300), "radius": 800, "color": (250, 204, 21, 150)},  # Amber Gold
            {"center": (-200, H - 300), "radius": 600, "color": (82, 82, 82, 120)}  # Neutral Gray
        ],
        "grid_color": (250, 204, 21, 12),
        "accent_color": "#facc15"
    },
    "policy_security": {
        "bg_color_start": "#080202",
        "bg_color_end": "#090d16",
        "orb_colors": [
            {"center": (W + 200, 400), "radius": 700, "color": (239, 68, 68, 140)},  # Crimson Red
            {"center": (-200, H - 400), "radius": 700, "color": (59, 130, 246, 140)}  # Steel Blue
        ],
        "grid_color": (239, 68, 68, 12),
        "accent_color": "#ef4444"
    },
    "mindset_change": {
        "bg_color_start": "#05020c",
        "bg_color_end": "#110b24",
        "orb_colors": [
            {"center": (-200, 300), "radius": 700, "color": (168, 85, 247, 160)},  # Amethyst Purple
            {"center": (W + 200, H - 300), "radius": 750, "color": (79, 70, 229, 140)}  # Deep Indigo
        ],
        "grid_color": (168, 85, 247, 15),
        "accent_color": "#c084fc"
    }
}

def render_cover_v2(payload: dict, output_path: str):
    """
    [Gemini_3.5_Flash_planning] 渲染精美的双层标题封面，应用玻璃态卡片、点阵网格与主题光晕
    """
    theme_name = payload.get("theme", "robotics_tech")
    cfg = THEME_CONFIGS.get(theme_name, THEME_CONFIGS["robotics_tech"])
    
    # 1. 基础背景渐变
    # Pillow 渐变绘制
    base = Image.new('RGBA', (W, H), (0,0,0,0))
    b_draw = ImageDraw.Draw(base)
    start_color = Image.new('RGBA', (W, H), cfg["bg_color_start"])
    end_color = Image.new('RGBA', (W, H), cfg["bg_color_end"])
    # 纵向线性渐变遮罩
    mask = Image.new('L', (W, H))
    mask_draw = ImageDraw.Draw(mask)
    for y in range(H):
        val = int(255 * (y / H))
        mask_draw.line([(0, y), (W, y)], fill=val)
    img = Image.composite(end_color, start_color, mask)

    # 2. 绘制氛围光晕 (Glowing Orbs)
    orbs = Image.new('RGBA', (W, H), (0,0,0,0))
    o_draw = ImageDraw.Draw(orbs)
    for orb in cfg["orb_colors"]:
        cx, cy = orb["center"]
        r = orb["radius"]
        o_draw.ellipse([cx-r, cy-r, cx+r, cy+r], fill=orb["color"])
    orbs = orbs.filter(ImageFilter.GaussianBlur(180))
    img = Image.alpha_composite(img, orbs)
    
    # 3. 绘制精美点阵网格 (Dot Grid Pattern)
    grid_layer = Image.new('RGBA', (W, H), (0,0,0,0))
    g_draw = ImageDraw.Draw(grid_layer)
    grid_spacing = 80
    dot_color = cfg["grid_color"]
    for x in range(40, W, grid_spacing):
        for y in range(40, H, grid_spacing):
            g_draw.ellipse([x-2, y-2, x+2, y+2], fill=dot_color)
    img = Image.alpha_composite(img, grid_layer)
    
    # 4. 磨砂玻璃容器 (Glass Card)
    card = Image.new('RGBA', (W, H), (0,0,0,0))
    c_draw = ImageDraw.Draw(card)
    margin = 80
    cw = W - margin * 2
    ch = 950
    cy = H / 2 - ch / 2
    
    # 玻璃板半透明填充与极细白边
    c_draw.rounded_rectangle(
        [margin, cy, margin+cw, cy+ch], 
        radius=60, 
        fill=(255, 255, 255, 12), 
        outline=(255, 255, 255, 45), 
        width=3
    )
    
    # 5. 卡片内部文字排版
    # 顶部徽章 (Badge) - 主题色文字药丸框
    badge_text = payload.get("badge", "前沿科技").upper()
    badge_font = get_font(42, "bold")
    badge_bbox = badge_font.getbbox(badge_text)
    badge_w = badge_bbox[2] - badge_bbox[0]
    badge_h = badge_bbox[3] - badge_bbox[1]
    
    # 徽章背景药丸
    badge_margin_x = 40
    badge_margin_y = 15
    bx1 = W / 2 - badge_w / 2 - badge_margin_x
    by1 = cy + 80
    bx2 = W / 2 + badge_w / 2 + badge_margin_x
    by2 = cy + 80 + badge_h + badge_margin_y * 2
    c_draw.rounded_rectangle([bx1, by1, bx2, by2], radius=35, fill=(255, 255, 255, 240))
    # 写入徽章文字
    c_draw.text((W/2 - badge_w/2, by1 + badge_margin_y - 2), badge_text, font=badge_font, fill="#0f172a")
    
    # 6. 主标题文本绘制 (流量短标题)
    title = payload.get("title", "")
    font_size = 120
    font_main = get_font(font_size, "black")
    max_text_width = cw - 120
    lines = split_text_by_width(title, font_main, max_text_width)
    
    # 高度缩放自适应算法
    total_text_height = sum([font_main.getbbox(l)[3] - font_main.getbbox(l)[1] for l in lines]) + (len(lines)-1)*40
    while total_text_height > 400 and font_size > 40:
        font_size -= 10
        font_main = get_font(font_size, "black")
        lines = split_text_by_width(title, font_main, max_text_width)
        total_text_height = sum([font_main.getbbox(l)[3] - font_main.getbbox(l)[1] for l in lines]) + (len(lines)-1)*40

    # 绘制主标题
    start_y = cy + 220 + (380 - total_text_height) / 2
    current_y = start_y
    for line in lines:
        h = draw_text_centered(c_draw, line, font_main, current_y, fill='#ffffff')
        current_y += h + 45
        
    # 7. 副标题文本绘制 (Hook Subtitle)
    subtitle = payload.get("subtitle", "")
    if subtitle:
        font_sub = get_font(60, "bold")
        sub_lines = split_text_by_width(subtitle, font_sub, max_text_width)
        
        # 居中渲染副标题 (最深支持2行)
        sub_y = cy + ch - 220
        for s_line in sub_lines[:2]:
            h = draw_text_centered(c_draw, s_line, font_sub, sub_y, fill=(255, 255, 255, 200))
            sub_y += h + 25

    # 8. 合并图层并保存
    img = Image.alpha_composite(img, card)
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.convert('RGB').save(out_path, quality=95)
    print(f"V2 Cover Generated: {out_path}")

REVIEWS = [
    {
        "yid": "XtCDtibUoK8",
        "orig_title": "Google CEO on Quantum Computers",
        "theme": "robotics_tech",
        "title": "量子计算已来！",
        "subtitle": "谷歌CEO深度预测：世界将被彻底重构",
        "badge": "前沿科技"
    },
    {
        "yid": "G2B0YWuJUgI",
        "orig_title": "The prompting playbook",
        "theme": "robotics_tech",
        "title": "向AI提问的艺术",
        "subtitle": "构建你的高阶提示词体系，彻底榨干大模型潜能",
        "badge": "AI·智能"
    },
    {
        "yid": "8ATK9I4en9w",
        "orig_title": "U.S. and Iran suggest progress on peace talks, but deal ‘not imminent’",
        "theme": "policy_security",
        "title": "美伊秘密谈判？",
        "subtitle": "和平协议现曙光，但关键分歧仍未妥协",
        "badge": "地缘政治"
    },
    {
        "yid": "SbO2uime0vI",
        "orig_title": "Twitch to politics: Hasan Piker on Gaza and the US right-wing | The Take",
        "theme": "policy_security",
        "title": "网红议政风暴",
        "subtitle": "哈桑深度解密：加沙局势背后的舆论战",
        "badge": "地缘政治"
    },
    {
        "yid": "hz0Azz-TKEc",
        "orig_title": "Elon Musk Shocked Everyone with New Optimus Update: Human Skin & Superintelligence",
        "theme": "robotics_tech",
        "title": "特斯拉机器人！",
        "subtitle": "马斯克震撼发布：人类皮肤加超级智能",
        "badge": "前沿科技"
    },
    {
        "yid": "M5DrlI-dMPY",
        "orig_title": "The Market Hit New HIGHS…COMPANIES EXPOSE THE CRACKS in the MARKET",
        "theme": "market_capital",
        "title": "美股新高背后？",
        "subtitle": "大厂财报拉响警报，牛市之下的致命裂痕",
        "badge": "资本财评"
    },
    {
        "yid": "AdkON0lIfAw",
        "orig_title": "canada is killing private messaging.",
        "theme": "policy_security",
        "title": "隐私终结法案！",
        "subtitle": "加拿大强制监控加密聊天，你还安全吗？",
        "badge": "政策安全"
    },
    {
        "yid": "N6wip1DM0BQ",
        "orig_title": "17 minutes to change your life forever (JUST LISTEN!)",
        "theme": "mindset_change",
        "title": "改变你的命运！",
        "subtitle": "听完这17分钟，重新开启你的认知框架",
        "badge": "思维跃迁"
    },
    {
        "yid": "eMT5U3UOgSQ",
        "orig_title": "INVESTORS Are Being SOLD The SpaceX Dream BUT IT'S AN EXIT TRAP...",
        "theme": "market_capital",
        "title": "SpaceX是陷阱？",
        "subtitle": "溢价估值下的接盘阴谋，别被梦想割了野菜",
        "badge": "资本财评"
    },
    {
        "yid": "mpDanDwd7x0",
        "orig_title": "This Prototype Laptop Crushes Everything I’ve Ever Seen",
        "theme": "robotics_tech",
        "title": "未来电脑长这样？",
        "subtitle": "超前原型机震撼曝光，设计与性能彻底颠覆认知",
        "badge": "前沿科技"
    }
]

def main():
    out_dir = Path("output/covers_demo_v2")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    artifact_dir = Path("/Users/ryusei/.gemini/antigravity/brain/11cc548f-1a93-4780-93df-ada5f9761875/artifacts")
    artifact_dir.mkdir(parents=True, exist_ok=True)
    
    markdown_content = [
        "# 视频号封面改版重制 - 10 个近期视频效果 Review\n\n",
        "本次封面重制严格落地了自媒体视觉与文案改进规则：\n",
        "1. **文案升级**：缩短短标题字数至 6-16 字以契合微信要求，摒弃「信息摘要型」，强化「爆款流量型」；增加 Hook 副标题（≤24字）以丰富信息层级。\n",
        "2. **色彩与主题感知**：支持机器人/AI（前沿科技-深蓝）、财经/资本（资本财评-金黄/曜黑）、政治/安全（地缘安全-红蓝博弈）、个人成长（思维跃迁-幻紫）四套主题色自适应。\n",
        "3. **高端视觉要素**：融合磨砂玻璃态容器、细白发光边框、背景点阵网格，显著改善视觉高级感与小图可读性。\n\n",
        "````carousel\n"
    ]
    
    for i, review in enumerate(REVIEWS):
        yid = review["yid"]
        # 输出文件名
        cover_filename = f"{yid}_cover_v2.jpg"
        local_path = out_dir / cover_filename
        artifact_path = artifact_dir / cover_filename
        
        # 渲染
        render_cover_v2(review, local_path)
        
        # 复制到 artifact 目录
        shutil.copy(local_path, artifact_path)
        
        # 写入 markdown
        if i > 0:
            markdown_content.append("<!-- slide -->\n")
        markdown_content.append(f"### 视频 {i+1}: {review['title']}\n")
        markdown_content.append(f"**原视频标题**: `{review['orig_title']}`\n")
        markdown_content.append(f"**主标题**: `{review['title']}` | **副标题**: `{review['subtitle']}`\n")
        markdown_content.append(f"**内容主题**: `{review['badge']}` | **视觉方案**: `{review['theme']}`\n\n")
        markdown_content.append(f"![{review['title']}](/Users/ryusei/.gemini/antigravity/brain/11cc548f-1a93-4780-93df-ada5f9761875/artifacts/{cover_filename})\n\n")

    markdown_content.append("````\n")
    
    # 写入 md 文件头部 frontmatter
    md_header = [
        "---\n",
        "created_by: Gemini_3.5_Flash_planning\n",
        "created_at: 2026-05-26\n",
        "---\n\n",
        "# Version History\n\n",
        "| Version | Date | Author | Description |\n",
        "|---|---|---|---|\n",
        "| 1.0.0 | 2026-05-26 | Gemini_3.5_Flash_planning | 初始化 10 个视频封面重制 Review 报告 |\n\n"
    ]
    
    final_md = "".join(md_header) + "".join(markdown_content)
    with open(artifact_dir / "regenerated_covers.md", "w", encoding="utf-8") as f:
        f.write(final_md)
        
    print("Done. Review report generated at artifacts/regenerated_covers.md")

if __name__ == "__main__":
    main()
