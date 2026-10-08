"""Platform-compliant cover generator for WeChat Channels and Douyin.

Generates:
1. WeChat Channels 9:16 vertical poster (1080x1920)
2. Douyin 3:4 vertical poster (1080x1440) - tailored full-bleed single-page layout
3. Douyin 4:3 horizontal banner (1440x1080) - tailored full-bleed open journal spread

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-08 | Antigravity | Initial implementation of cover generator |
| 1.1.0 | 2026-10-08 | Antigravity | Full-bleed Douyin 3:4 tailored poster and 4:3 two-page open journal spread |
"""

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont, ImageFilter

from .canvas_builder import CanvasBuilder
from .contracts import HandwrittenPagerConfig, LyricLine, PenState
from .pen_physics import PenPhysicsEngine


class CoverGenerator:
    """Generates platform-compliant cover images with safe zones and viral visual hooks."""

    def __init__(self, config: Optional[HandwrittenPagerConfig] = None):
        self.config = config or HandwrittenPagerConfig()
        self.config.validate()
        self.canvas_builder = CanvasBuilder(self.config)
        self.pen_engine = PenPhysicsEngine(self.config)

    def generate_covers(
        self,
        raw_lyrics: List[dict],
        output_dir: Path,
        title: str = "Let Me Down Slowly",
        artist: str = "Alec Benjamin",
        study_notes: Optional[List[Tuple[str, str]]] = None,
    ) -> Dict[str, str]:
        """Generates all 3 cover formats and returns their file paths."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # ----------------------------------------------------
        # 1. WeChat Channels 9:16 (1080x1920)
        # ----------------------------------------------------
        base_canvas, lines = self.canvas_builder.build_canvas(
            raw_lyrics=raw_lyrics,
            title=title,
            artist=artist,
            study_notes=study_notes,
        )

        target_line = lines[3] if len(lines) > 3 else lines[0]
        climax_word = target_line.words[-2] if len(target_line.words) >= 2 else target_line.words[0]

        pen_state_wechat = PenState(
            frame_idx=0,
            t=0.0,
            x=climax_word.x_start + climax_word.width * 0.5,
            y=target_line.y_en + self.config.tip_y_offset,
            z=0.0,
            angle_deg=-3.5,
            is_active=True,
            active_word=climax_word.word,
        )

        wechat_cover = self.pen_engine.render_pen_frame(base_canvas, pen_state_wechat)
        wechat_path = output_dir / "cover_wechat_9_16.png"
        wechat_cover.save(wechat_path, quality=95)

        # ----------------------------------------------------
        # 2. Douyin 3:4 Vertical Poster (1080x1440) - Physical Stationery Desk Mockup
        # ----------------------------------------------------
        # Renders the journal notebook page placed on a warm desk background with soft drop shadow
        # and rounded corners. This creates an authentic stationery mock-up aesthetic that prevents
        # platform OCR/CV false-positives for "screenshots of notes".
        W34, H34 = 1080, 1440
        pw34, ph34 = 960, 1340
        px34 = (W34 - pw34) // 2
        py34 = (H34 - ph34) // 2

        desk_34 = Image.new("RGBA", (W34, H34), (238, 233, 224, 255))
        d_draw34 = ImageDraw.Draw(desk_34)
        for step in range(30):
            alpha = int(2 + step * 2)
            d_draw34.rectangle([step * 3, step * 3, W34 - step * 3, H34 - step * 3], outline=(200, 192, 180, alpha), width=3)

        shadow_box34 = Image.new("RGBA", (pw34 + 40, ph34 + 40), (0, 0, 0, 0))
        s_draw34 = ImageDraw.Draw(shadow_box34)
        s_draw34.rounded_rectangle([15, 15, pw34 + 25, ph34 + 25], radius=20, fill=(40, 32, 25, 80))
        s_blurred34 = shadow_box34.filter(ImageFilter.GaussianBlur(16.0))
        desk_34.alpha_composite(s_blurred34, (px34 - 20, py34 - 16))

        cropped_rich = wechat_cover.crop((0, 0, 1080, 1420))
        page_34 = cropped_rich.resize((pw34, ph34), Image.Resampling.LANCZOS).convert("RGBA")

        mask34 = Image.new("L", (pw34, ph34), 0)
        m_draw34 = ImageDraw.Draw(mask34)
        m_draw34.rounded_rectangle([0, 0, pw34, ph34], radius=16, fill=255)
        desk_34.paste(page_34, (px34, py34), mask34)

        p_draw34 = ImageDraw.Draw(desk_34)
        p_draw34.rounded_rectangle([px34, py34, px34 + pw34, py34 + ph34], radius=16, outline=(210, 202, 190, 200), width=2)

        douyin_3_4_path = output_dir / "cover_douyin_3_4.png"
        desk_34.save(douyin_3_4_path, quality=95)
        desk_34.convert("RGB").save(output_dir / "cover_douyin_3_4.jpg", format="JPEG", quality=95)

        # ----------------------------------------------------
        # 3. Douyin 4:3 Horizontal Banner (1440x1080) - Open Journal Spread
        # ----------------------------------------------------
        W43, H43 = 1440, 1080
        canvas_4_3 = Image.new("RGBA", (W43, H43), (242, 238, 230, 255))
        d43 = ImageDraw.Draw(canvas_4_3)

        for step in range(40):
            alpha = int(2 + step * 1.5)
            d43.rectangle([step * 4, step * 4, W43 - step * 4, H43 - step * 4], outline=(210, 202, 190, alpha), width=4)

        pw, ph = 640, 960
        py = (H43 - ph) // 2

        # Page drop shadow
        shadow_box = Image.new("RGBA", (1320, 980), (0, 0, 0, 0))
        s_draw = ImageDraw.Draw(shadow_box)
        s_draw.rounded_rectangle([10, 10, 1310, 970], radius=12, fill=(40, 32, 25, 75))
        s_blurred = shadow_box.filter(ImageFilter.GaussianBlur(16.0))
        canvas_4_3.alpha_composite(s_blurred, (60, py - 4))

        left_page = Image.new("RGBA", (pw, ph), (250, 247, 242, 255))
        lp_draw = ImageDraw.Draw(left_page)
        right_page = Image.new("RGBA", (pw, ph), (250, 247, 242, 255))
        rp_draw = ImageDraw.Draw(right_page)

        tex_path = Path(__file__).parent / "assets" / "paper_texture_ivory.jpg"
        if tex_path.exists():
            tex = Image.open(tex_path).convert("RGBA").resize((pw, ph), Image.Resampling.BILINEAR)
            left_page = Image.blend(left_page, tex, alpha=0.10)
            lp_draw = ImageDraw.Draw(left_page)
            right_page = Image.blend(right_page, tex, alpha=0.10)
            rp_draw = ImageDraw.Draw(right_page)

        # Left page: lines & lyrics
        for ry in range(220, 920, 52):
            lp_draw.line([(50, ry), (pw - 40, ry)], fill=(215, 225, 235, 180), width=1)
        lp_draw.line([(70, 40), (70, ph - 40)], fill=(235, 180, 180, 180), width=2)

        font_title_43 = self.canvas_builder._resolve_font([("/System/Library/Fonts/Noteworthy.ttc", 36, 1)])
        font_sub_43 = self.canvas_builder._resolve_font([("/System/Library/Fonts/STHeiti Light.ttc", 19, 1)])
        font_en_43 = self.canvas_builder._resolve_font([("/System/Library/Fonts/Noteworthy.ttc", 28, 1)])
        font_zh_43 = self.canvas_builder._resolve_font([("/System/Library/Fonts/STHeiti Light.ttc", 18, 1)])

        font_meta_43 = self.canvas_builder._resolve_font([("/System/Library/Fonts/Noteworthy.ttc", 22, 0), ("/Library/Fonts/Arial Unicode.ttf", 22, -1)])
        lp_draw.text((90, 50), "DAILY ENGLISH & MUSIC JOURNAL", font=font_meta_43, fill=(130, 138, 150))
        lp_draw.text((90, 85), title, font=font_title_43, fill=(35, 42, 55))
        lp_draw.text((90, 140), f"原唱：{artist} ｜ 治愈跟唱 & 沉浸伴读", font=font_sub_43, fill=(105, 115, 130))
        lp_draw.line([(70, 175), (pw - 40, 175)], fill=(200, 210, 220, 220), width=2)

        stanza_y_43 = 210
        pitch_43 = 52
        for i, item in enumerate(raw_lyrics):
            by = stanza_y_43 + i * (pitch_43 * 2.6)
            lp_draw.text((90, int(by)), item["en"], font=font_en_43, fill=self.config.en_ink_color)
            lp_draw.text((90, int(by + pitch_43 * 0.9)), item["zh"], font=font_zh_43, fill=self.config.zh_ink_color)

        # Center spine fold
        spine = Image.new("RGBA", (40, ph), (0, 0, 0, 0))
        sp_draw = ImageDraw.Draw(spine)
        for sx in range(40):
            alpha = int(45 * (1.0 - abs(sx - 20) / 20.0))
            sp_draw.line([(sx, 0), (sx, ph)], fill=(50, 42, 35, alpha), width=1)

        # Right page: study card & learning notes
        for ry in range(120, 920, 52):
            rp_draw.line([(40, ry), (pw - 50, ry)], fill=(215, 225, 235, 180), width=1)

        # Right page: Header metadata
        rp_draw.text((65, 50), "DAILY ENGLISH & MUSIC JOURNAL", font=font_meta_43, fill=(130, 138, 150))
        rp_draw.text((pw - 220, 50), "Oct 08  |  Page 02", font=font_meta_43, fill=(140, 148, 160))

        # Right page: Study notes card
        rp_draw.rounded_rectangle([40, 80, pw - 50, 890], radius=14, fill=(246, 242, 235, 255), outline=(222, 216, 206, 255), width=2)
        font_notes_h43 = self.canvas_builder._resolve_font([("/System/Library/Fonts/STHeiti Light.ttc", 22, 1)])
        font_notes_t43 = self.canvas_builder._resolve_font([("/System/Library/Fonts/STHeiti Light.ttc", 19, 1)])
        font_ipa43 = self.canvas_builder._resolve_font([("/Library/Fonts/Arial Unicode.ttf", 19, -1), ("/System/Library/Fonts/STHeiti Light.ttc", 19, 1)])

        rp_draw.text((65, 105), "◆ 核心地道词汇与语法解析", font=font_notes_h43, fill=(50, 60, 75))
        rp_draw.line([(65, 145), (pw - 75, 145)], fill=(225, 220, 210, 255), width=1)

        notes_items = [
            ("• let sb down slowly", "温柔地让某人面对失望 / 委婉提出分手\n【例】If you must go, please let me down slowly."),
            ("• sympathy /ˈsɪmpəθi/", "n. 同情，怜悯；理解与共情\n【辨析】empathy (感同身受) vs sympathy (怜悯)"),
            ("• wanna = want to", "口语极高频连读缩略，表“想要、打算”\n【搭配】wanna go / wanna tell you"),
            ("• lonely /ˈləʊnli/", "adj. 孤独的，寂寞的（强调情感孤独）\n【区别】alone (客观单独) vs lonely (内心孤独)"),
        ]
        cur_ny = 165
        for term, expl in notes_items:
            term_f = font_ipa43 if "/" in term else font_notes_t43
            rp_draw.text((65, cur_ny), term, font=term_f, fill=(35, 45, 60))
            rp_draw.text((85, cur_ny + 30), expl, font=font_notes_t43, fill=(105, 115, 130))
            cur_ny += 115

        rp_draw.line([(65, 750), (pw - 75, 750)], fill=(225, 220, 210, 255), width=1)
        rp_draw.text((65, 775), "◆ 沉浸式听歌学英语 ｜ 每日精选双语手账", font=font_sub_43, fill=(120, 130, 145))
        rp_draw.text((65, 810), "Bilingual Reading & Study Notes Journal", font=font_meta_43, fill=(140, 148, 160))

        canvas_4_3.alpha_composite(left_page, (70, py))
        canvas_4_3.alpha_composite(right_page, (730, py))
        canvas_4_3.alpha_composite(spine, (710, py))

        pen_state_43 = PenState(
            frame_idx=0,
            t=0.0,
            x=430.0,
            y=py + 590.0,
            z=0.0,
            angle_deg=-3.5,
            is_active=True,
            active_word="slowly",
        )
        douyin_4_3 = self.pen_engine.render_pen_frame(canvas_4_3, pen_state_43)
        douyin_4_3_path = output_dir / "cover_douyin_4_3.png"
        douyin_4_3.save(douyin_4_3_path, quality=95)

        return {
            "wechat_9_16": str(wechat_path),
            "douyin_3_4": str(douyin_3_4_path),
            "douyin_4_3": str(douyin_4_3_path),
        }
