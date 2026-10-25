# -*- coding: utf-8 -*-
"""专业宏观财经数据卡片与画布遮罩生成器 (card_generator.py)

负责生成：
1. 980x240 RGBA 玻璃态宏观财经数据指标卡片，用于在视频关键论点呈现时动态悬浮展示。
2. 1080x1920 RGBA 竖屏前景画框与专属栏目徽标遮罩（用于遮盖外媒右上角水印）。

# Modification History
| Version | Date       | Author      | Description |
| ------- | ---------- | ----------- | ----------- |
| 1.0.0   | 2026-10-25 | Antigravity | 初始创建，提供标准数据卡片与 9:16 画布遮罩生成服务 |
| 1.2.0 | 2026-10-25 | Codex | 批量卡片目标预检与目录约束 |
| 1.1.0   | 2026-10-25 | Antigravity | 增强中文字体解析优先级，优先挂载 assets/fonts 开源中文字体与 Linux 标准路径 |
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont
from .manifest_contract import safe_card_path, validate_identifier

logger = logging.getLogger(__name__)


# 字体候选优先级列表 (macOS + 仓库内置 + Linux)
FONT_CANDIDATES = [
    "/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
]


def resolve_system_font(preferred_path: Optional[str] = None) -> Optional[str]:
    """解析系统可用的中文字体路径。"""
    if preferred_path and os.path.exists(preferred_path):
        return preferred_path
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def get_font(size: int, bold: bool = False, preferred_font: Optional[str] = None) -> ImageFont.ImageFont:
    """获取指定字号的字体，支持缺失时平滑回退。"""
    font_path = resolve_system_font(preferred_font)
    if not font_path:
        return ImageFont.load_default()
    try:
        # Hiragino Sans GB / PingFang ttc 通常 index 0/1 分别为 W3/W6
        font_index = 1 if bold else 0
        return ImageFont.truetype(font_path, size, index=font_index)
    except Exception:
        try:
            return ImageFont.truetype(font_path, size)
        except Exception:
            return ImageFont.load_default()


class FinancialCardGenerator:
    """宏观财经数据卡片生成引擎。"""

    def __init__(self, font_path: Optional[str] = None):
        self.font_path = resolve_system_font(font_path)

    def generate_card(
        self,
        output_path: Path | str,
        tag: str,
        title: str,
        col1_lbl: str,
        col1_val: str,
        col2_lbl: str,
        col2_val: str,
        note: Optional[str] = None,
        width: int = 980,
        height: int = 240,
    ) -> Path:
        """生成一张 980x240 RGBA 磨砂玻璃态宏观对比卡片。"""
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)

        im = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(im)

        # 1. 磨砂深蓝灰底板 + 金色描边
        bg_box = [0, 0, width, height]
        draw.rounded_rectangle(
            bg_box,
            radius=20,
            fill=(12, 18, 28, 230),
            outline=(212, 175, 55, 180),
            width=2,
        )

        # 2. 顶部金色小标签
        font_tag = get_font(22, bold=True, preferred_font=self.font_path)
        tag_w = int(draw.textlength(tag, font=font_tag)) + 24
        tag_w = max(tag_w, 130)
        draw.rounded_rectangle([30, 22, 30 + tag_w, 52], radius=6, fill=(212, 175, 55, 230))
        draw.text((42, 24), tag, font=font_tag, fill=(10, 15, 25, 255))

        # 3. 标题
        font_title = get_font(26, bold=True, preferred_font=self.font_path)
        draw.text((40 + tag_w + 15, 22), title, font=font_title, fill=(255, 255, 255, 255))

        # 4. 横向细分割线
        draw.line([(30, 68), (width - 30, 68)], fill=(255, 255, 255, 40), width=1)

        # 5. 左列指标
        font_lbl = get_font(24, bold=False, preferred_font=self.font_path)
        font_val = get_font(34, bold=True, preferred_font=self.font_path)
        draw.text((40, 85), col1_lbl, font=font_lbl, fill=(180, 195, 215, 255))
        draw.text((40, 125), col1_val, font=font_val, fill=(255, 215, 0, 255))

        # 6. 中间竖直分割线
        mid_x = width // 2
        draw.line([(mid_x, 85), (mid_x, 175)], fill=(255, 255, 255, 40), width=1)

        # 7. 右列指标
        draw.text((mid_x + 35, 85), col2_lbl, font=font_lbl, fill=(180, 195, 215, 255))
        draw.text((mid_x + 35, 125), col2_val, font=font_val, fill=(80, 210, 255, 255))

        # 8. 底部小字注释
        if note:
            font_note = get_font(20, bold=False, preferred_font=self.font_path)
            draw.text((40, 190), f"◆ {note}", font=font_note, fill=(150, 165, 185, 220))

        im.save(out_p, "PNG")
        logger.info(f"Financial card generated: {out_p}")
        return out_p

    def batch_generate_from_manifest(
        self,
        cards_data: List[Dict[str, Any]],
        output_dir: Path | str,
    ) -> List[Path]:
        """按制作清单批量生成数据卡片，返回生成文件路径列表。"""
        out_dir = Path(output_dir)
        # 先校验全部目标，避免后续非法路径造成部分生成。
        paths = []
        for idx, card in enumerate(cards_data, 1):
            validate_identifier(card.get("id"))
            paths.append(safe_card_path(out_dir, card.get("filename") or f"card_{idx}_{card['id']}.png"))
        out_dir.mkdir(parents=True, exist_ok=True)
        results: List[Path] = []

        for idx, card in enumerate(cards_data, start=1):
            filename = card.get("filename") or f"card_{idx}_{card.get('id', 'item')}.png"
            card_path = paths[idx - 1]
            self.generate_card(
                output_path=card_path,
                tag=card.get("tag", "核心洞察"),
                title=card.get("title", ""),
                col1_lbl=card.get("col1_lbl", ""),
                col1_val=card.get("col1_val", ""),
                col2_lbl=card.get("col2_lbl", ""),
                col2_val=card.get("col2_val", ""),
                note=card.get("note", None),
            )
            results.append(card_path)

        return results


def generate_vertical_frame_overlay(
    output_path: Path | str,
    canvas_w: int = 1080,
    canvas_h: int = 1920,
    video_w: int = 1080,
    video_h: int = 608,
    video_y: int = 656,
    badge_text: str = "◆ 六维时空 ｜ 独家观察",
    mask_watermark: bool = True,
    border_color: Tuple[int, int, int, int] = (212, 175, 55, 180),
) -> Path:
    """生成 1080x1920 RGBA 竖屏前景画框与水印遮盖徽标。"""
    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    im = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)

    # 1. 16:9 居中视频画框金色描边 (y=656 to 1264)
    draw.rectangle(
        [0, video_y, canvas_w - 1, video_y + video_h],
        outline=border_color,
        width=2,
    )

    # 2. 右上角栏目徽标（精准压盖外媒原台标水印，位于 x=780, y=668, w=280, h=50）
    if mask_watermark:
        badge_font = get_font(22, bold=True)
        text_w = int(draw.textlength(badge_text, font=badge_font))
        badge_w = max(text_w + 30, 270)
        badge_h = 46
        badge_x = canvas_w - badge_w - 20
        badge_y = video_y + 12

        # 暗蓝黑微透胶囊底板 + 金色细边
        draw.rounded_rectangle(
            [badge_x, badge_y, badge_x + badge_w, badge_y + badge_h],
            radius=8,
            fill=(10, 15, 22, 245),
            outline=(212, 175, 55, 200),
            width=1,
        )
        draw.text((badge_x + 15, badge_y + 10), badge_text, font=badge_font, fill=(212, 175, 55, 255))

    im.save(out_p, "PNG")
    logger.info(f"Vertical frame overlay generated: {out_p}")
    return out_p


def main():
    parser = argparse.ArgumentParser(description="宏观数据卡片与遮罩生成工具")
    parser.add_argument("--cards-json", type=str, help="卡片定义的 JSON 文件路径")
    parser.add_argument("--output-dir", type=str, default="output/finance_cards", help="输出目录")
    parser.add_argument("--generate-overlay", action="store_true", help="同时生成 1080x1920 竖屏画框遮罩")
    parser.add_argument("--overlay-output", type=str, default="output/vertical_overlay.png", help="画框遮罩保存路径")
    args = parser.parse_args()

    gen = FinancialCardGenerator()

    if args.cards_json:
        path = Path(args.cards_json)
        cards = json.loads(path.read_text(encoding="utf-8"))
        gen.batch_generate_from_manifest(cards, args.output_dir)
        print(f"Cards generated in {args.output_dir}")

    if args.generate_overlay:
        generate_vertical_frame_overlay(args.overlay_output)
        print(f"Overlay generated: {args.overlay_output}")


if __name__ == "__main__":
    main()
