# -*- coding: utf-8 -*-
"""模板 A：原片小窗、唱片旋转、右栏词卡与逐词红线的静态版式。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0 | 2026-08-02 | Codex | 初始创建：输出模板 A 静态画布、唱片素材和逐词下划线坐标。 |
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
VIDEO_BOX = (54, 238, 682, 600)
DISC_BOX = (748, 274, 982, 508)
TEXT_LEFT = 54
TEXT_TOP = 682
TEXT_WIDTH = 650
TEXT_BOTTOM = 1430
VOCAB_BOX = (730, 548, 1025, 1820)
TRANSLATION_BOX = (54, 1480, 682, 1818)
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
        word_boxes = self._draw_english_body(draw, content.english_text)
        self._draw_translation(draw, content.translation_zh)
        self._draw_vocabulary(draw, content.vocabulary)

        base_image = output_dir / "template_a_base.png"
        page.save(base_image)
        disc_image = output_dir / "template_a_disc.png"
        self._draw_disc(disc_image)
        return TemplateAAssets(base_image, disc_image, tuple(word_boxes))

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
        draw.rounded_rectangle(TRANSLATION_BOX, radius=22, fill="#F2EEE5")
        draw.text((DISC_BOX[0], DISC_BOX[1] - 54), "Listening", font=_font(34, bold=True), fill=INK)
        draw.text((VOCAB_BOX[0] + 22, VOCAB_BOX[1] + 20), "Vocabulary", font=_font(40, bold=True, serif=True), fill=INK)

    def _draw_heading(self, draw: ImageDraw.ImageDraw, content: StudyCardContent) -> None:
        zh_font = _font(35)
        en_font = _font(24, serif=True, italic=True)
        draw.text((54, 72), _ellipsize(content.headline_zh, zh_font, 900), font=zh_font, fill=INK)
        draw.text((54, 120), _ellipsize(content.headline_en, en_font, 900), font=en_font, fill=MUTED)
        draw.line((54, 178, 1025, 178), fill="#C9BDB0", width=3)

    def _draw_english_body(self, draw: ImageDraw.ImageDraw, text: str) -> list[WordBox]:
        tokens = re.findall(r"\S+", text)
        for size in range(64, 38, -2):
            font = _font(size, serif=True, bold=True)
            lines = _wrap_words(tokens, font, TEXT_WIDTH)
            line_height = int(size * 1.33)
            if len(lines) * line_height <= TEXT_BOTTOM - TEXT_TOP:
                return _draw_word_lines(draw, lines, font, line_height)
        raise ValueError("英文正文过长，无法在模板 A 的阅读区保持可读字号")

    def _draw_translation(self, draw: ImageDraw.ImageDraw, translation: str) -> None:
        label_font = _font(28)
        text_font = _font(35)
        draw.text((82, 1512), "中文翻译", font=label_font, fill=MUTED)
        lines = _wrap_chinese(translation, text_font, TRANSLATION_BOX[2] - TRANSLATION_BOX[0] - 56)
        y = 1555
        for line in lines[:5]:
            draw.text((82, y), line, font=text_font, fill=INK)
            y += 48

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


def _draw_word_lines(draw: ImageDraw.ImageDraw, lines: list[list[str]], font: ImageFont.FreeTypeFont, line_height: int) -> list[WordBox]:
    boxes: list[WordBox] = []
    y = TEXT_TOP
    space_width = int(draw.textlength(" ", font=font))
    for line in lines:
        x = TEXT_LEFT
        for token in line:
            draw.text((x, y), token, font=font, fill=INK)
            width = int(draw.textlength(token, font=font))
            boxes.append(WordBox(token, x, y + line_height - 8, max(8, width)))
            x += width + space_width
        y += line_height
    return boxes


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


def _latin_font(size: int) -> ImageFont.FreeTypeFont:
    """IPA 走支持音标字形的拉丁字体，避免中文字体把 /ˈspiːʃiːz/ 渲染成方框。"""
    return ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", size)


def _ellipsize(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> str:
    if font.getlength(text) <= max_width:
        return text
    ellipsis = "…"
    while text and font.getlength(text + ellipsis) > max_width:
        text = text[:-1]
    return text + ellipsis


def _normalise_word(value: str) -> str:
    return re.sub(r"[^a-z0-9']+", "", value.lower())
