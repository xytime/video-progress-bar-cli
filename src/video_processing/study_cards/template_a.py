# -*- coding: utf-8 -*-
"""模板 A：原片小窗、唱片旋转、右栏词卡与逐词红线的静态版式。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0 | 2026-08-02 | Codex | 初始创建：输出模板 A 静态画布、唱片素材和逐词下划线坐标。 |
| 1.1.0 | 2026-08-02 | Codex | 正文严格对齐新闻精读参考图：意群英文、词下小注、段后中文释义和右栏词卡。 |
| 1.2.0 | 2026-08-02 | Codex | 正文改为透明长画布，供渲染器逐段滚动；同时提升手机端词注、段译及头部信息层级。 |
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont

from .models import StudyCardContent, StudyWord, VocabularyItem

CANVAS_WIDTH = 1080
CANVAS_HEIGHT = 1920
VIDEO_BOX = (54, 274, 702, 638)
DISC_BOX = (756, 298, 990, 532)
TEXT_LEFT = 54
TEXT_TOP = 720
TEXT_WIDTH = 650
READING_VIEWPORT_BOTTOM = 1840
VOCAB_BOX = (730, 574, 1025, 1820)
ENGLISH_FONT = "/System/Library/Fonts/Supplemental/Georgia.ttf"
CHINESE_FONT = "/System/Library/Fonts/Hiragino Sans GB.ttc"
ACCENT = "#C6432D"
PAPER = "#FFFDF8"
INK = "#1E1A18"
MUTED = "#6E625A"


@dataclass(frozen=True)
class WordBox:
    """一个单词在静态画布中的下划线几何位置。"""

    text: str
    x: int
    y: int
    width: int


@dataclass(frozen=True)
class TemplateAAssets:
    """渲染器所需的模板资产与逐词几何。"""

    base_image: Path
    reading_image: Path
    disc_image: Path
    word_boxes: tuple[WordBox, ...]


class RecordUnderlineTemplate:
    """只处理视觉排版；不读取视频、不调用 AI，也不启动 FFmpeg。"""

    name = "record_underline"

    def render_static(self, content: StudyCardContent, output_dir: Path) -> TemplateAAssets:
        output_dir.mkdir(parents=True, exist_ok=True)
        page = Image.new("RGB", (CANVAS_WIDTH, CANVAS_HEIGHT), PAPER)
        draw = ImageDraw.Draw(page)
        self._draw_page_frame(draw)
        self._draw_heading(draw, content)
        self._draw_vocabulary(draw, content.vocabulary)

        reading_height = max(CANVAS_HEIGHT, self._measure_reading_bottom(content) + 64)
        reading = Image.new("RGBA", (CANVAS_WIDTH, reading_height), (0, 0, 0, 0))
        word_boxes, _ = self._draw_reading_body(ImageDraw.Draw(reading), content)

        base_image = output_dir / "template_a_base.png"
        page.save(base_image)
        reading_image = output_dir / "template_a_reading.png"
        reading.save(reading_image)
        disc_image = output_dir / "template_a_disc.png"
        self._draw_disc(disc_image)
        return TemplateAAssets(base_image, reading_image, disc_image, tuple(word_boxes))

    def map_word_boxes(self, words: Iterable[StudyWord], boxes: tuple[WordBox, ...]) -> list[tuple[StudyWord, WordBox]]:
        """按规范化词面一一匹配时间轴，拒绝静默错位。"""
        result: list[tuple[StudyWord, WordBox]] = []
        box_index = 0
        for word in words:
            normal = _normalise_word(word.text)
            while box_index < len(boxes) and not _normalise_word(boxes[box_index].text):
                box_index += 1
            if box_index >= len(boxes):
                raise ValueError(f"页面正文没有可匹配的单词位置: {word.text!r}")
            current = boxes[box_index]
            if normal != _normalise_word(current.text):
                raise ValueError(
                    "逐词时间轴与 english_text 不一致，拒绝生成错误红线: "
                    f"timeline={word.text!r}, page={current.text!r}"
                )
            result.append((word, current))
            box_index += 1
        return result

    def _draw_page_frame(self, draw: ImageDraw.ImageDraw) -> None:
        draw.rounded_rectangle((28, 28, 1052, 1888), radius=44, outline="#CFC5BC", width=4)
        draw.rounded_rectangle(VIDEO_BOX, radius=22, outline="#AFA49A", width=4, fill="#EDE7DF")
        draw.rounded_rectangle(VOCAB_BOX, radius=24, outline="#AFA49A", width=4, fill="#FFFEFB")
        draw.text((DISC_BOX[0], DISC_BOX[1] - 46), "Listening", font=_font(30, bold=True), fill=INK)
        draw.text((VOCAB_BOX[0] + 22, VOCAB_BOX[1] + 20), "Vocabulary", font=_font(40, bold=True, serif=True), fill=INK)

    def _draw_heading(self, draw: ImageDraw.ImageDraw, content: StudyCardContent) -> None:
        badge = (54, 70, 142, 158)
        draw.rectangle(badge, fill="#B73520")
        draw.text((61, 82), "新闻", font=_font(35, bold=True), fill="#FFFDF8")
        title_font = _font(43, bold=True)
        sub_font = _font(23, bold=True)
        draw.text((160, 69), _ellipsize(content.headline_zh, title_font, 845), font=title_font, fill=INK)
        draw.text(
            (160, 125),
            _ellipsize(content.headline_en, sub_font, 845),
            font=sub_font,
            fill=INK,
        )
        draw.rectangle((54, 182, 1025, 214), fill="#B73520")
        draw.text((66, 187), f"单词数 · {len(content.words)}个", font=_font(18, bold=True), fill="#FFFDF8")
        draw.text((866, 187), "DATE: NEWS", font=_latin_font(17, bold=True), fill="#FFFDF8")
        draw.text(
            (54, 228),
            "每日打卡 / 时文精读 / 高频词汇同步标记",
            font=_font(21, bold=True),
            fill=MUTED,
        )

    def _draw_reading_body(self, draw: ImageDraw.ImageDraw, content: StudyCardContent) -> tuple[list[WordBox], int]:
        """严格采用参考图的阅读稿：英文意群 → 词下小注 → 本段中文释义。"""
        english_font = _latin_font(40, bold=True)
        gloss_font = _font(22, bold=True)
        translation_font = _font(30)
        line_height = 74
        marked_words = { _normalise_word(item.word): item.meaning_zh for item in content.vocabulary }
        y = TEXT_TOP
        boxes: list[WordBox] = []
        for paragraph in content.paragraphs:
            lines = _wrap_words(re.findall(r"\S+", paragraph.english_text), english_font, TEXT_WIDTH)
            translation_lines = _wrap_chinese(paragraph.translation_zh, translation_font, TEXT_WIDTH - 10)
            for line in lines:
                x = TEXT_LEFT
                for token in line:
                    width = int(draw.textlength(token, font=english_font))
                    normal = _normalise_word(token)
                    meaning = marked_words.get(normal)
                    if meaning:
                        draw.rounded_rectangle((x - 5, y - 3, x + width + 5, y + 48), radius=7, fill=ACCENT)
                    draw.text((x, y), token, font=english_font, fill="#FFFDF8" if meaning else INK)
                    boxes.append(WordBox(token, x, y + 53, max(8, width)))
                    if meaning:
                        note = _ellipsize(meaning, gloss_font, max(width + 22, 80))
                        note_width = int(draw.textlength(note, font=gloss_font))
                        draw.text((x + max(0, (width - note_width) // 2), y + 52), note, font=gloss_font, fill=MUTED)
                    x += width + int(draw.textlength(" ", font=english_font))
                y += line_height
            translation_line_height = 43
            draw.rounded_rectangle((TEXT_LEFT, y + 4, TEXT_LEFT + TEXT_WIDTH, y + 4 + len(translation_lines) * translation_line_height + 20), radius=10, fill="#F8F2EA")
            y += 13
            for line in translation_lines:
                draw.text((TEXT_LEFT + 10, y), line, font=translation_font, fill=INK)
                y += translation_line_height
            y += 28
        return boxes, y

    def _measure_reading_bottom(self, content: StudyCardContent) -> int:
        """用与实际绘制完全相同的字级测量长正文，避免按固定屏高截断内容。"""
        english_font = _latin_font(40, bold=True)
        translation_font = _font(30)
        y = TEXT_TOP
        for paragraph in content.paragraphs:
            lines = _wrap_words(re.findall(r"\S+", paragraph.english_text), english_font, TEXT_WIDTH)
            translation_lines = _wrap_chinese(paragraph.translation_zh, translation_font, TEXT_WIDTH - 10)
            y += len(lines) * 74
            y += 13 + len(translation_lines) * 43 + 28
        return y

    def _draw_vocabulary(self, draw: ImageDraw.ImageDraw, items: tuple[VocabularyItem, ...]) -> None:
        y = VOCAB_BOX[1] + 84
        palette = (ACCENT, "#EDE6DA", "#365E8B", "#EDE6DA", ACCENT)
        for index, item in enumerate(items[:5]):
            fill = palette[index % len(palette)]
            dark = fill in {ACCENT, "#365E8B"}
            text_color = "#FFFDF8" if dark else INK
            card = (VOCAB_BOX[0] + 18, y, VOCAB_BOX[2] - 18, y + 184)
            draw.rounded_rectangle(card, radius=20, fill=fill)
            draw.text((card[0] + 18, card[1] + 16), _ellipsize(item.word, _font(34, bold=True, serif=True), 220), font=_font(34, bold=True, serif=True), fill=text_color)
            detail = " ".join(part for part in (item.phonetic, item.level) if part).strip()
            if detail:
                ipa_font = _latin_font(21)
                draw.text((card[0] + 18, card[1] + 68), _ellipsize(detail, ipa_font, 220), font=ipa_font, fill=text_color)
            meaning = " ".join(part for part in (item.part_of_speech, item.meaning_zh) if part).strip()
            draw.text((card[0] + 18, card[1] + 110), _ellipsize(meaning, _font(27), 220), font=_font(27), fill=text_color)
            y += 202

    def _draw_disc(self, output_path: Path) -> None:
        size = DISC_BOX[2] - DISC_BOX[0]
        disc = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(disc)
        draw.ellipse((4, 4, size - 4, size - 4), fill="#151515", outline="#403B36", width=4)
        for inset in range(22, size // 2 - 20, 17):
            draw.ellipse((inset, inset, size - inset, size - inset), outline="#5B554F", width=2)
        centre = size // 2
        draw.ellipse((centre - 44, centre - 44, centre + 44, centre + 44), fill="#C18B3A")
        # 非中心标记让旋转在静态纹路以外仍有清晰可感知的运动参照。
        draw.ellipse((centre + 17, centre - 20, centre + 29, centre - 8), fill="#F7E8BD")
        draw.ellipse((centre - 8, centre - 8, centre + 8, centre + 8), fill="#F7E8BD")
        disc.save(output_path)


def _wrap_words(tokens: list[str], font: ImageFont.FreeTypeFont, max_width: int) -> list[list[str]]:
    lines: list[list[str]] = [[]]
    current_width = 0.0
    space = font.getlength(" ")
    for token in tokens:
        token_width = font.getlength(token)
        addition = token_width if not lines[-1] else space + token_width
        if lines[-1] and current_width + addition > max_width:
            lines.append([token])
            current_width = token_width
        else:
            lines[-1].append(token)
            current_width += addition
    return lines


def _wrap_chinese(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines: list[str] = []
    line = ""
    for char in text:
        candidate = line + char
        if line and font.getlength(candidate) > max_width:
            lines.append(line)
            line = char
        else:
            line = candidate
    if line:
        lines.append(line)
    return lines


def _font(size: int, *, serif: bool = False, bold: bool = False, italic: bool = False) -> ImageFont.FreeTypeFont:
    if serif:
        suffix = " Bold" if bold else ""
        suffix += " Italic" if italic else ""
        candidate = f"/System/Library/Fonts/Supplemental/Georgia{suffix}.ttf"
        path = candidate if Path(candidate).exists() else ENGLISH_FONT
    else:
        path = CHINESE_FONT
    return ImageFont.truetype(path, size)


def _latin_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    """IPA 走支持音标字形的拉丁字体，避免中文字体把 /ˈspiːʃiːz/ 渲染成方框。"""
    name = "Arial Bold.ttf" if bold else "Arial.ttf"
    return ImageFont.truetype(f"/System/Library/Fonts/Supplemental/{name}", size)


def _ellipsize(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> str:
    if font.getlength(text) <= max_width:
        return text
    ellipsis = "…"
    while text and font.getlength(text + ellipsis) > max_width:
        text = text[:-1]
    return text + ellipsis


def _normalise_word(value: str) -> str:
    return re.sub(r"[^a-z0-9']+", "", value.lower())
