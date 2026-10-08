"""Notebook paper canvas builder and word-level typography layout.

Constructs:
1. Warm ivory paper background with organic paper fiber texture.
2. Notebook margin rule, binder punch holes, and crisp ruled notebook lines.
3. Hand-drawn bullet journal header with Cosmic Eye brand seal, Tian Yingzhang calligraphy, and slogan.
4. Artistic multi-color title and vibrant 3-badge prestige washi tape accolades.
5. Mobile-optimized word-measured bilingual lyrics with zero-overlap spacing and contextual hand-drawn doodles.
6. Educational bullet journal study notes card at bottom for viral value.

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-08 | Antigravity | Initial implementation of canvas builder and typography layout |
| 1.1.0 | 2026-10-08 | Antigravity | Fix missing glyph box (tofu) in study notes card header by using universal geometric bullet ◆ |
| 1.2.0 | 2026-10-08 | Antigravity | Upgrade to hand-drawn bullet journal layout: calligraphy, brand seal, vibrant accolades, tightened tracking, +76px non-overlapping translation, and contextual doodles |
"""

import math
import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from .contracts import HandwrittenPagerConfig, LyricLine, LyricWord


def is_cjk(ch: str) -> bool:
    """Checks whether a character belongs to the CJK Unified Ideographs block."""
    code = ord(ch)
    return (0x4E00 <= code <= 0x9FFF) or (0x3400 <= code <= 0x4DBF)


class CanvasBuilder:
    """Builds the 1080x1920 notebook paper canvas and measures lyric word coordinates."""

    def __init__(self, config: Optional[HandwrittenPagerConfig] = None):
        self.config = config or HandwrittenPagerConfig()
        self.config.validate()
        self._load_fonts()
        self._load_assets()

    def _resolve_font(self, candidates: List[Tuple[str, int, int]]) -> ImageFont.ImageFont:
        """Finds first existing font from candidate list (path, size, index)."""
        for path_str, size, idx in candidates:
            p = Path(path_str)
            if p.exists():
                try:
                    if idx >= 0:
                        return ImageFont.truetype(str(p), size, index=idx)
                    return ImageFont.truetype(str(p), size)
                except Exception:
                    continue
        return ImageFont.load_default()

    def _load_fonts(self) -> None:
        """Loads typography fonts for header, lyrics, and notes with graceful fallbacks."""
        # 1. Chinese Calligraphy Font (Tian Yingzhang Hard-Pen Calligraphy)
        self.font_zh_tian_32 = self._resolve_font([("/Library/Fonts/TianYingZhang.ttf", 32, -1)])
        self.font_zh_tian_28 = self._resolve_font([("/Library/Fonts/TianYingZhang.ttf", 28, -1)])
        self.font_zh_tian_23 = self._resolve_font([("/Library/Fonts/TianYingZhang.ttf", 23, -1)])
        self.font_zh_tian_22 = self._resolve_font([("/Library/Fonts/TianYingZhang.ttf", 22, -1)])
        self.font_zh_tian_36 = self._resolve_font([("/Library/Fonts/TianYingZhang.ttf", 36, -1)])

        # 2. English Handwriting & Script Fonts
        self.font_en_noteworthy_45 = self._resolve_font([("/System/Library/Fonts/Noteworthy.ttc", 45, 1)])
        self.font_en_noteworthy_54 = self._resolve_font([("/System/Library/Fonts/Noteworthy.ttc", 54, 1)])
        self.font_en_bradley_56 = self._resolve_font([("/System/Library/Fonts/Supplemental/Bradley Hand Bold.ttf", 56, -1)])
        self.font_en_noteworthy_24 = self._resolve_font([("/System/Library/Fonts/Noteworthy.ttc", 24, 1)])

        # 3. Universal Unicode Symbol Fonts (for IPA, punctuation, bullets)
        self.font_sym_hiragino_26 = self._resolve_font([("/System/Library/Fonts/Hiragino Sans GB.ttc", 26, 0)])
        self.font_sym_hiragino_24 = self._resolve_font([("/System/Library/Fonts/Hiragino Sans GB.ttc", 24, 0)])
        self.font_sym_hiragino_32 = self._resolve_font([("/System/Library/Fonts/Hiragino Sans GB.ttc", 32, 0)])
        self.font_sym_hiragino_21 = self._resolve_font([("/System/Library/Fonts/Hiragino Sans GB.ttc", 21, 0)])
        self.font_sym_arial_21 = self._resolve_font([("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", 21, -1)])
        self.font_sym_arial_20 = self._resolve_font([("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", 20, -1)])

    def _load_assets(self) -> None:
        """Loads logo and doodle assets."""
        root = Path(__file__).resolve().parent.parent.parent.parent
        logo_path = root / "assets/brand/01_logos/concept_a.png"
        if logo_path.exists():
            self.logo_raw = Image.open(logo_path).convert("RGBA")
        else:
            self.logo_raw = Image.new("RGBA", (100, 100), (40, 60, 90, 255))

        doodles_dir = Path(__file__).parent / "assets" / "doodles"
        self.doodles = []
        doodle_names = [
            "doodle_01_leaf.png",
            "doodle_02_bandaid.png",
            "doodle_03_cat_moon.png",
            "doodle_04_cassette.png",
            "doodle_05_notes.png",
        ]
        for name in doodle_names:
            p = doodles_dir / name
            if p.exists():
                self.doodles.append(Image.open(p).convert("RGBA"))
            else:
                self.doodles.append(Image.new("RGBA", (100, 100), (0, 0, 0, 0)))

    def draw_mixed_text(
        self,
        draw: ImageDraw.ImageDraw,
        xy: Tuple[float, float],
        text: str,
        font_zh: ImageFont.ImageFont,
        font_other: ImageFont.ImageFont,
        fill: Any,
        tracking: float = 0.0,
    ) -> float:
        """Draws mixed text using TianYingZhang for Chinese characters and standard font for symbols."""
        x, y = xy
        for ch in text:
            f = font_zh if is_cjk(ch) else font_other
            draw.text((x, y), ch, font=f, fill=fill)
            w = draw.textlength(ch, font=f)
            x += w + tracking
        return x

    def get_mixed_text_width(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        font_zh: ImageFont.ImageFont,
        font_other: ImageFont.ImageFont,
        tracking: float = 0.0,
    ) -> float:
        """Measures width of mixed text."""
        w = 0.0
        for ch in text:
            f = font_zh if is_cjk(ch) else font_other
            w += draw.textlength(ch, font=f) + tracking
        return w

    def draw_handdrawn_rect(
        self,
        draw: ImageDraw.ImageDraw,
        bbox: Tuple[float, float, float, float],
        fill: Optional[Any] = None,
        outline: Optional[Any] = (60, 60, 60, 200),
        width: int = 2,
        roughness: float = 1.4,
    ) -> None:
        """Draws a rectangle with subtle organic hand-drawn wobble."""
        x0, y0, x1, y1 = bbox
        if fill:
            draw.rectangle([x0, y0, x1, y1], fill=fill)
        if outline:
            def jitter_line(p1, p2):
                dx, dy = p2[0] - p1[0], p2[1] - p1[1]
                dist = math.hypot(dx, dy)
                steps = max(3, int(dist / 35))
                pts = [p1]
                for s in range(1, steps):
                    t = s / steps
                    jx = (random.random() - 0.5) * roughness
                    jy = (random.random() - 0.5) * roughness
                    pts.append((p1[0] + dx * t + jx, p1[1] + dy * t + jy))
                pts.append(p2)
                for i in range(len(pts) - 1):
                    draw.line([pts[i], pts[i+1]], fill=outline, width=width)

            jitter_line((x0, y0), (x1, y0))
            jitter_line((x1, y0), (x1, y1))
            jitter_line((x1, y1), (x0, y1))
            jitter_line((x0, y1), (x0, y0))

    def draw_handdrawn_circle_seal(
        self,
        canvas: Image.Image,
        center_xy: Tuple[float, float],
        radius: float,
        logo_size: int = 42,
    ) -> None:
        """Draws a hand-sketched circular seal with the Cosmic Eye logo in center."""
        cx, cy = center_xy
        draw = ImageDraw.Draw(canvas)
        for r_offset, rough in [(0, 1.2), (3, 1.0)]:
            r = radius + r_offset
            pts = []
            num_pts = 36
            for i in range(num_pts + 1):
                angle = 2 * math.pi * (i / num_pts)
                jr = (random.random() - 0.5) * rough
                px = cx + (r + jr) * math.cos(angle)
                py = cy + (r + jr) * math.sin(angle)
                pts.append((px, py))
            for i in range(len(pts) - 1):
                draw.line([pts[i], pts[i+1]], fill=(225, 145, 35, 230), width=2)

        l_resized = self.logo_raw.resize((logo_size, logo_size), Image.Resampling.LANCZOS)
        mask = Image.new("L", (logo_size, logo_size), 0)
        m_draw = ImageDraw.Draw(mask)
        m_draw.ellipse([0, 0, logo_size, logo_size], fill=255)

        out_logo = Image.new("RGBA", (logo_size, logo_size), (0, 0, 0, 0))
        out_logo.paste(l_resized, (0, 0), mask)
        canvas.paste(out_logo, (int(cx - logo_size // 2), int(cy - logo_size // 2)), out_logo)

    def build_canvas(
        self,
        raw_lyrics: List[Dict[str, Any]],
        title: str = "Let Me Down Slowly",
        artist: str = "Alec Benjamin",
        study_notes: Optional[List[Tuple[str, str]]] = None,
    ) -> Tuple[Image.Image, List[LyricLine]]:
        """Constructs hand-drawn bullet journal page and calculates exact word coordinates for physics."""
        random.seed(42)  # Deterministic organic wobble
        W, H = self.config.width, self.config.height
        canvas = Image.new("RGBA", (W, H), (254, 251, 246, 255))

        # 1. Apply paper texture if available
        tex_path = Path(__file__).parent / "assets" / "paper_texture_ivory.jpg"
        if tex_path.exists():
            tex = Image.open(tex_path).convert("RGBA").resize((W, H), Image.Resampling.BILINEAR)
            canvas = Image.blend(canvas, tex, alpha=0.14)

        draw = ImageDraw.Draw(canvas)

        # 2. Left red margin rule & Binder punch holes
        draw.line([(130, 80), (130, 1840)], fill=(230, 110, 110, 160), width=2)
        for hy in [250, 600, 960, 1320, 1680]:
            draw.ellipse([45, hy - 14, 75, hy + 14], fill=(225, 220, 212, 255), outline=(190, 185, 178, 255), width=2)

        # 3. Ruled horizontal lines
        first_rule_y = 410
        last_rule_y = 1420
        for ry in range(first_rule_y, last_rule_y + 1, 64):
            draw.line([(110, ry), (1020, ry)], fill=(220, 230, 242, 160), width=1)

        # 4. Top Branding: Hand-drawn Bullet Journal Masthead (y=50..120)
        self.draw_handdrawn_circle_seal(canvas, (175, 82), radius=26, logo_size=42)
        draw.text((215, 66), "六维时空号", font=self.font_zh_tian_32, fill=(30, 42, 60))
        draw.text((375, 68), "｜", font=self.font_sym_hiragino_26, fill=(190, 175, 150))
        self.draw_mixed_text(
            draw, (405, 72), "“不同的视角，看见更大的世界。”", self.font_zh_tian_23, self.font_sym_hiragino_21, fill=(195, 125, 30)
        )
        self.draw_mixed_text(
            draw, (800, 72), "✎ 音乐手账 · NO.082", self.font_zh_tian_22, self.font_sym_arial_20, fill=(120, 130, 145)
        )
        for dx in range(150, 1000, 16):
            draw.line([(dx, 120), (dx + 8, 120)], fill=(215, 205, 185, 180), width=1)

        # 5. Song Title: Vibrant Artistic Hand-lettering (y=136..235)
        t1 = "Let Me Down "
        t2 = "Slowly"
        draw.text((150, 136), t1, font=self.font_en_noteworthy_54, fill=(24, 46, 80))
        w_t1 = draw.textlength(t1, font=self.font_en_noteworthy_54)
        draw.text((150 + w_t1, 134), t2, font=self.font_en_bradley_56, fill=(230, 72, 32))
        w_t2 = draw.textlength(t2, font=self.font_en_bradley_56)

        zh_title_text = "《慢慢放手》"
        zh_w = self.get_mixed_text_width(draw, zh_title_text, self.font_zh_tian_36, self.font_sym_hiragino_32)
        zh_x = 150 + w_t1 + w_t2 + 28
        draw.rounded_rectangle([zh_x - 8, 144, zh_x + zh_w + 8, 186], radius=8, fill=(255, 220, 80, 160))
        self.draw_mixed_text(draw, (zh_x, 140), zh_title_text, self.font_zh_tian_36, self.font_sym_hiragino_32, fill=(30, 38, 48))

        underline_end_x = int(150 + w_t1 + w_t2 + 10)
        draw.line([(150, 204), (underline_end_x, 204)], fill=(230, 72, 32, 220), width=2)
        draw.arc([underline_end_x - 8, 200, underline_end_x + 8, 208], start=180, end=360, fill=(230, 72, 32, 220), width=2)

        artist_text = "原唱：Alec Benjamin (2018)  ·  欧美流行乐传世治愈神作  ·  双语跟唱"
        self.draw_mixed_text(draw, (150, 218), artist_text, self.font_zh_tian_22, self.font_sym_hiragino_21, fill=(100, 110, 125))

        # 6. Vibrant & Rich Accolade Banner / Washi Tape (y=252..372)
        self.draw_handdrawn_rect(draw, (145, 252, 1005, 372), fill=(255, 250, 240, 245), outline=(225, 175, 95, 240), width=2, roughness=1.6)

        badges = [
            ("★ 全网超 30 亿播放量", (255, 140, 15), (255, 255, 255), (220, 95, 0)),
            ("◆ 现象级传世治愈神曲", (15, 150, 235), (255, 255, 255), (8, 115, 195)),
            ("● RIAA 双白金销量认证", (125, 70, 220), (255, 255, 255), (95, 40, 185)),
        ]
        box_x0 = 145
        box_x1 = 1005
        box_w = box_x1 - box_x0  # 860px
        by = 268

        b_widths = []
        for b_text, _, _, _ in badges:
            w = 0
            for ch in b_text:
                f = self.font_zh_tian_22 if is_cjk(ch) else self.font_sym_arial_21
                w += draw.textlength(ch, font=f)
            b_widths.append(w + 36)

        total_bw = sum(b_widths)
        remaining_space = box_w - total_bw
        gap = remaining_space / 4

        cur_bx = box_x0 + gap
        for idx, (b_text, b_fill, b_text_c, b_border) in enumerate(badges):
            bw = b_widths[idx]
            self.draw_handdrawn_rect(draw, (cur_bx, by, cur_bx + bw, by + 40), fill=b_fill, outline=b_border, width=2, roughness=1.0)
            self.draw_mixed_text(draw, (cur_bx + 18, by + 8), b_text, self.font_zh_tian_22, self.font_sym_arial_21, fill=b_text_c)
            cur_bx += bw + gap

        quote_prefix = "✎ 策展手记: “用最清澈的少年音与深沉吉他，"
        quote_highlight = "唱尽刻骨温柔的心碎与救赎"
        quote_suffix = "。”"
        w_qp = self.get_mixed_text_width(draw, quote_prefix, self.font_zh_tian_22, self.font_sym_arial_21)
        w_qh = self.get_mixed_text_width(draw, quote_highlight, self.font_zh_tian_22, self.font_sym_arial_21)

        hl_x0 = 175 + w_qp
        hl_x1 = hl_x0 + w_qh
        draw.rounded_rectangle([hl_x0 - 4, 325, hl_x1 + 4, 351], radius=6, fill=(255, 215, 130, 160))
        self.draw_mixed_text(draw, (175, 324), quote_prefix, self.font_zh_tian_22, self.font_sym_arial_21, fill=(100, 90, 80))
        self.draw_mixed_text(draw, (hl_x0, 324), quote_highlight, self.font_zh_tian_22, self.font_sym_arial_21, fill=(180, 50, 20))
        self.draw_mixed_text(draw, (hl_x1, 324), quote_suffix, self.font_zh_tian_22, self.font_sym_arial_21, fill=(100, 90, 80))

        # 7. Lyrics & Doodles Layout (y=425..1350)
        # Spacing: Pitch 200px, English at sy, Chinese at sy + 76 (Generous gap, 0% overlap!)
        stanza_y_positions = [425, 625, 825, 1025, 1225]
        doodle_specs = [
            ((890, 415), 110),
            ((880, 615), 120),
            ((895, 810), 100),
            ((865, 1010), 130),
            ((890, 1205), 100),
        ]

        measured_lines: List[LyricLine] = []
        x_origin = 150.0
        tracking = -1.2

        for i, item in enumerate(raw_lyrics):
            en_text = item["en"]
            zh_text = item["zh"]
            raw_words = item["words"]
            sy = stanza_y_positions[i] if i < len(stanza_y_positions) else 425 + i * 200

            # 1. Draw English text with tracking
            cur_x = x_origin
            for ch in en_text:
                draw.text((cur_x, sy), ch, font=self.font_en_noteworthy_45, fill=(24, 32, 44))
                cur_x += draw.textlength(ch, font=self.font_en_noteworthy_45) + tracking

            # 2. Draw Chinese translation with +76px vertical separation (clean breathing room)
            self.draw_mixed_text(
                draw, (x_origin, sy + 76), zh_text, self.font_zh_tian_28, self.font_sym_hiragino_26, fill=(85, 95, 110)
            )

            # 3. Paste contextual matching doodle
            if i < len(self.doodles) and i < len(doodle_specs):
                d_img = self.doodles[i]
                d_xy, d_w = doodle_specs[i]
                aspect = d_img.height / d_img.width
                d_h = int(d_w * aspect)
                d_scaled = d_img.resize((d_w, d_h), Image.Resampling.LANCZOS)
                canvas.paste(d_scaled, d_xy, d_scaled)

            # 4. Measure word positions along the line with exact tracking
            line_words: List[LyricWord] = []
            cur_prefix = ""
            for w_info in raw_words:
                w_str = w_info["word"].strip()
                idx = en_text.find(w_str, len(cur_prefix))
                if idx == -1:
                    idx = len(cur_prefix)
                prefix_before = en_text[:idx]
                prefix_after = en_text[: idx + len(w_str)]

                # Compute prefix widths with tracking
                w_start_x = x_origin
                for ch in prefix_before:
                    w_start_x += draw.textlength(ch, font=self.font_en_noteworthy_45) + tracking

                w_end_x = x_origin
                for ch in prefix_after:
                    w_end_x += draw.textlength(ch, font=self.font_en_noteworthy_45) + tracking

                # Pen target baseline bottom
                y_bottom = sy + 46.0

                line_words.append(
                    LyricWord(
                        word=w_str,
                        start_time=float(w_info["start"]),
                        end_time=float(w_info["end"]),
                        x_start=w_start_x,
                        x_end=w_end_x,
                        y_bottom=y_bottom,
                    )
                )
                cur_prefix = prefix_after

            measured_lines.append(
                LyricLine(
                    line_index=i,
                    en_text=en_text,
                    zh_text=zh_text,
                    words=line_words,
                    y_en=sy,
                    y_zh=sy + 76.0,
                    ruled_line_y=sy + 50.0,
                )
            )

        # 8. Study Notes Card: Hand-drawn Bullet Journal Card (y=1440..1795)
        card_y = 1440
        self.draw_handdrawn_rect(
            draw, (135, card_y, 1005, card_y + 355), fill=(247, 243, 236, 230), outline=(215, 205, 190, 240), width=2, roughness=1.5
        )
        self.draw_mixed_text(
            draw, (165, card_y + 24), "◆ 重点表达手账解析 (Key Expressions)", self.font_zh_tian_28, self.font_sym_hiragino_24, fill=(40, 52, 68)
        )
        for dx in range(165, 975, 12):
            draw.line([(dx, card_y + 68), (dx + 6, card_y + 68)], fill=(210, 200, 185, 200), width=1)

        default_notes = study_notes or [
            ("• let sb down slowly", "温柔地让某人面对失望 / 委婉提出分手"),
            ("• sympathy /ˈsɪmpəθi/", "n. 同情，怜悯；理解与共情"),
            ("• wanna = want to", "口语常用略缩表达，表“想要、意图”"),
            ("• lonely /ˈləʊnli/", "adj. 孤独的，寂寞的（强调主观情感孤立）"),
        ]

        for j, (term, expl) in enumerate(default_notes):
            ny = card_y + 88 + j * 64
            t_font = self.font_sym_arial_21 if "/" in term else self.font_en_noteworthy_24
            draw.text((170, ny), term, font=t_font, fill=(30, 42, 58))
            self.draw_mixed_text(draw, (470, ny), expl, self.font_zh_tian_23, self.font_sym_hiragino_21, fill=(95, 105, 118))

        return canvas, measured_lines
