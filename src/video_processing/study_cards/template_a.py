# -*- coding: utf-8 -*-
"""模板 A：原片小窗、唱片旋转、右栏词卡与逐词红线的静态版式。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0 | 2026-08-02 | Codex | 初始创建：输出模板 A 静态画布、唱片素材和逐词下划线坐标。 |
| 1.1.0 | 2026-08-02 | Codex | 正文严格对齐新闻精读参考图：意群英文、词下小注、段后中文释义和右栏词卡。 |
| 1.2.0 | 2026-08-02 | Codex | 正文改为透明长画布，供渲染器逐段滚动；同时提升手机端词注、段译及头部信息层级。 |
| 1.3.0 | 2026-08-02 | Codex | 静态稿重置为首张新闻精读模板：报纸式双栏、固定栏目头、窄词栏与无底色段后译文。 |
| 1.4.0 | 2026-08-02 | Codex | 中文统一改用随项目分发的思源宋体；英文正文采用 Avenir Next Condensed，词卡标题采用 Baskerville。 |
| 1.4.1 | 2026-08-02 | Codex | 音标单独改用支持 IPA 的 Arial，避免 Avenir Next Condensed 缺字。 |
| 1.4.2 | 2026-08-02 | Codex | 英文正文与词卡英文标题改用随项目分发的 Rojal.ttf，并适配其较高字面调整正文行距。 |
| 1.4.3 | 2026-08-02 | Codex | 正文英文恢复为 Avenir Next Condensed；右栏词卡英文保留 Rojal 并增加轻微字距。 |
| 1.4.4 | 2026-08-02 | Codex | 右栏词卡英文换为 Baskerville SemiBold；视频上方内容标题加大并使用思源宋体。 |
| 1.5.0 | 2026-08-02 | Codex | 正文支持多词生词短语：词卡、红底标记和词下中文注释使用同一份词组匹配结果。 |
| 1.5.1 | 2026-08-02 | Codex | 正文标题改为金色加粗，增强手机端新闻主题辨识。 |
| 1.6.0 | 2026-08-02 | Codex | 降低生词红色强调强度、为微笔记预留独立行距，并增加六维时空小程序码位。 |
| 1.7.0 | 2026-08-03 | Codex | 在词卡展示离线词表的友好标签与最低学习门槛，保留 IPA 与词义的手机端可读性。 |
| 1.8.0 | 2026-08-03 | Codex | 右栏词卡改为随正文 y 坐标对齐滚动，移除小程序码位，并以影子跟读 Banner 替换唱片素材。 |
| 1.9.0 | 2026-08-03 | Codex | 左侧保留最多十个微笔记，右侧只展示难度最高五词，并清洗重复词性与过早省略的释义。 |
| 1.10.0 | 2026-08-04 | Codex | 右栏为长正文滚动屏补充兜底词卡组，避免后半段核心词汇区空白。 |
| 1.11.0 | 2026-08-04 | Codex | 放大栏目标题与新闻标题并增加描边阴影，提升手机端首屏辨识；配合长文微笔记池保证每屏学习信息密度。 |
| 1.12.0 | 2026-08-04 | Codex | 按真实阅读窗挑选微笔记：不设全篇总量，只保证每屏 8–12 个，避免首屏过密和后屏稀疏。 |
| 1.13.0 | 2026-08-05 | Codex | 取消单屏微笔记上限；词下中文释义改为完整多行排版，空间不足通过阅读区提前滚动解决。 |
| 1.14.0 | 2026-08-05 | Codex | 微笔记按同一英文行分层避让；右栏按每个阅读屏的左侧候选稳定填充五张词卡。 |
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .models import StudyCardContent, StudyWord, VocabularyItem
from .vocabulary import difficulty_level

CANVAS_WIDTH = 1080
CANVAS_HEIGHT = 1920
VIDEO_BOX = (54, 274, 700, 637)
FEATURE_BOX = (760, 248, 1018, 568)
TEXT_LEFT = 54
TEXT_TOP = 720
TEXT_WIDTH = 650
ENGLISH_LINE_WIDTH = 570
READING_VIEWPORT_BOTTOM = 1840
VOCAB_BOX = (724, 604, 1025, 1820)
PROJECT_ROOT = Path(__file__).resolve().parents[3]
CHINESE_FONT = PROJECT_ROOT / "assets/fonts/SourceHanSerifCN-Medium.otf"
AVENIR_NEXT_CONDENSED = Path("/System/Library/Fonts/Avenir Next Condensed.ttc")
BASKERVILLE = Path("/System/Library/Fonts/Supplemental/Baskerville.ttc")
ARIAL = Path("/System/Library/Fonts/Supplemental/Arial.ttf")
FEATURE_REFERENCE = PROJECT_ROOT / "assets/study_cards/reference/shadowing_feature_banner_v1.png"
ACCENT = "#C6432D"
GOLD = "#A87914"
PAPER = "#FFFDF8"
INK = "#1E1A18"
MUTED = "#6E625A"
MARKED_WORD_BACKGROUND = "#F3DDD5"
MARKED_WORD_TEXT = "#A53C2B"
RIGHT_VOCABULARY_LIMIT = 5
MIN_MICRO_NOTES_PER_SCREEN = 8
RIGHT_CARD_TOP = 730
RIGHT_CARD_HEIGHT = 174
RIGHT_CARD_GAP = 11
POS_PATTERN = re.compile(r"\b(?:interj|conj|prep|pron|adj|adv|aux|det|num|vt|vi|int|n|v)\.?", re.IGNORECASE)


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
    feature_image: Path
    word_boxes: tuple[WordBox, ...]


class RecordUnderlineTemplate:
    """只处理视觉排版；不读取视频、不调用 AI，也不启动 FFmpeg。"""

    name = "record_underline"

    def __init__(self, feature_reference: Path | None = None) -> None:
        self.feature_reference = feature_reference or FEATURE_REFERENCE

    def render_static(self, content: StudyCardContent, output_dir: Path) -> TemplateAAssets:
        output_dir.mkdir(parents=True, exist_ok=True)
        page = Image.new("RGB", (CANVAS_WIDTH, CANVAS_HEIGHT), PAPER)
        draw = ImageDraw.Draw(page)
        self._draw_page_frame(draw)
        self._draw_heading(draw, content)

        reading_height = max(
            CANVAS_HEIGHT,
            self._measure_reading_bottom(content) + 64,
            TEXT_TOP + len(content.vocabulary) * 150 + 80,
        )
        reading = Image.new("RGBA", (CANVAS_WIDTH, reading_height), (0, 0, 0, 0))
        reading_draw = ImageDraw.Draw(reading)
        word_boxes, _ = self._draw_reading_body(reading_draw, content)
        # 右栏词卡由渲染器按当前阅读屏绘制为独立动态层，避免下一屏卡片
        # 在尚未滚动时提前露到本屏底部。

        base_image = output_dir / "template_a_base.png"
        page.save(base_image)
        reading_image = output_dir / "template_a_reading.png"
        reading.save(reading_image)
        feature_image = output_dir / "template_a_feature.png"
        self._draw_feature_banner(feature_image)
        return TemplateAAssets(base_image, reading_image, feature_image, tuple(word_boxes))

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

    def select_vocabulary_for_screens(
        self,
        candidates: tuple[VocabularyItem, ...],
        boxes: tuple[WordBox, ...],
        screen_offsets: Iterable[int],
    ) -> tuple[VocabularyItem, ...]:
        """在真实阅读窗中挑选微笔记，不以全篇词数设隐性上限。

        每个候选按其所有正文出现位置映射到滚动后的各屏；仅保证每屏至少
        八项，不为全文或单屏施加上限。若某屏没有足够的可审阅候选，直接报错
        而非静默交付稀疏页面，交由上游补充离线词表或短语 JSON。
        """
        offsets = tuple(dict.fromkeys(int(offset) for offset in screen_offsets))
        if not offsets or not candidates:
            return candidates
        occurrences = {
            _normalise_phrase(item.word): _vocabulary_occurrence_y_positions(item, boxes)
            for item in candidates
        }
        screen_items: list[set[str]] = []
        for offset in offsets:
            screen_items.append({
                key for key, ys in occurrences.items()
                if any(TEXT_TOP <= y - offset <= READING_VIEWPORT_BOTTOM - 80 for y in ys)
            })
        ranked = sorted(candidates, key=lambda item: (-difficulty_level(item.level), -len(item.word), item.word.lower()))
        selected: list[VocabularyItem] = []
        selected_keys: set[str] = set()
        screen_counts = [0] * len(screen_items)
        memberships = {
            key: tuple(index for index, keys in enumerate(screen_items) if key in keys)
            for key in occurrences
        }
        for screen_index, available in enumerate(screen_items):
            for item in ranked:
                if screen_counts[screen_index] >= MIN_MICRO_NOTES_PER_SCREEN:
                    break
                key = _normalise_phrase(item.word)
                if key in selected_keys or key not in available:
                    continue
                selected.append(item)
                selected_keys.add(key)
                for index in memberships[key]:
                    screen_counts[index] += 1
            if screen_counts[screen_index] < MIN_MICRO_NOTES_PER_SCREEN:
                raise ValueError(
                    f"第 {screen_index + 1} 个阅读屏只有 {screen_counts[screen_index]} 个可用微笔记；"
                    "需补充离线词表候选或审核短语 JSON"
                )
        return tuple(selected)

    def _draw_page_frame(self, draw: ImageDraw.ImageDraw) -> None:
        draw.rectangle(VIDEO_BOX, outline="#8E786A", width=3, fill="#EDE7DF")
        draw.rounded_rectangle(FEATURE_BOX, radius=18, outline="#BBA376", width=3, fill="#10263C")
        for y in range(254, 1850, 14):
            draw.line((708, y, 708, y + 7), fill="#A99180", width=2)
        draw.text((VOCAB_BOX[0] + 16, VOCAB_BOX[1] + 14), "核心词汇", font=_font(27, bold=True), fill=INK)
        draw.line((VOCAB_BOX[0] + 16, VOCAB_BOX[1] + 52, VOCAB_BOX[2] - 16, VOCAB_BOX[1] + 52), fill="#BA9F8C", width=2)

    def _draw_heading(self, draw: ImageDraw.ImageDraw, content: StudyCardContent) -> None:
        badge = (54, 66, 146, 158)
        draw.rectangle(badge, fill="#B73520")
        draw.text((61, 80), "新闻", font=_font(37, bold=True), fill="#FFFDF8")
        title_font = _font(52, bold=True)
        sub_font = _font(24, bold=True)
        draw.text(
            (160, 61), "世界英语新闻时事深度阅读", font=title_font, fill=INK,
            stroke_width=1, stroke_fill="#FFF8EA",
        )
        draw.text(
            (160, 123),
            "每日打卡 / 时文时报 / 高效突破8000词汇量",
            font=sub_font,
            fill=INK,
        )
        draw.rectangle((54, 182, 1025, 214), fill="#B73520")
        draw.text((66, 187), f"单词数 · {len(content.words)}个", font=_font(18, bold=True), fill="#FFFDF8")
        draw.text((916, 187), "DATE:", font=_latin_font(17, bold=True), fill="#FFFDF8")
        headline_font = _font(40, bold=True)
        headline = _ellipsize(content.headline_zh, headline_font, 640)
        draw.text(
            (54, 225), headline, font=headline_font, fill=GOLD,
            stroke_width=1, stroke_fill="#6B4914",
        )

    def _draw_reading_body(self, draw: ImageDraw.ImageDraw, content: StudyCardContent) -> tuple[list[WordBox], int]:
        """严格采用参考图的阅读稿：英文意群 → 词下小注 → 本段中文释义。"""
        english_font = _latin_font(40, bold=True)
        gloss_font = _font(22, bold=True)
        translation_font = _font(30)
        y = TEXT_TOP
        boxes: list[WordBox] = []
        for paragraph in content.paragraphs:
            lines = _wrap_words(re.findall(r"\S+", paragraph.english_text), english_font, ENGLISH_LINE_WIDTH)
            translation_lines = _wrap_chinese(paragraph.translation_zh, translation_font, TEXT_WIDTH - 10)
            for line in lines:
                highlights = _highlighted_token_indices(line, content.vocabulary)
                note_layout, line_height = _layout_line_notes(line, highlights, english_font, gloss_font)
                x = TEXT_LEFT
                for token_index, token in enumerate(line):
                    width = int(draw.textlength(token, font=english_font))
                    meaning, show_note = highlights.get(token_index, ("", False))
                    if meaning:
                        draw.rounded_rectangle(
                            (x - 5, y - 3, x + width + 5, y + 48), radius=7, fill=MARKED_WORD_BACKGROUND,
                        )
                    draw.text((x, y), token, font=english_font, fill=MARKED_WORD_TEXT if meaning else INK)
                    boxes.append(WordBox(token, x, y + 53, max(8, width)))
                    if meaning and show_note:
                        note_lines, note_x, note_y = note_layout[token_index]
                        for note_line_index, note_line in enumerate(note_lines):
                            draw.text(
                                (note_x, y + note_y + note_line_index * 27),
                                note_line,
                                font=gloss_font,
                                fill=MUTED,
                            )
                    x += width + int(draw.textlength(" ", font=english_font))
                y += line_height
            translation_line_height = 43
            y += 11
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
            lines = _wrap_words(re.findall(r"\S+", paragraph.english_text), english_font, ENGLISH_LINE_WIDTH)
            translation_lines = _wrap_chinese(paragraph.translation_zh, translation_font, TEXT_WIDTH - 10)
            for line in lines:
                highlights = _highlighted_token_indices(line, content.vocabulary)
                _, line_height = _layout_line_notes(line, highlights, english_font, _font(22, bold=True))
                y += line_height
            y += 13 + len(translation_lines) * 43 + 28
        return y

    def right_vocabulary_for_screens(
        self,
        items: tuple[VocabularyItem, ...],
        boxes: tuple[WordBox, ...],
        screen_offsets: Iterable[int],
    ) -> dict[int, tuple[VocabularyItem, ...]]:
        """返回每个阅读屏对应的五张右栏词卡，不修改页面长图。"""
        result: dict[int, tuple[VocabularyItem, ...]] = {}
        for offset in tuple(dict.fromkeys(int(value) for value in screen_offsets)) or (0,):
            visible_items = tuple(
                item for item in items
                if any(
                    TEXT_TOP <= y - offset <= READING_VIEWPORT_BOTTOM - 80
                    for y in _vocabulary_occurrence_y_positions(item, boxes)
                )
            )
            result[offset] = _right_vocabulary_items(visible_items or items)
        return result

    def draw_right_vocabulary_group(
        self,
        draw: ImageDraw.ImageDraw,
        items: tuple[VocabularyItem, ...],
        *,
        viewport_y: int,
    ) -> None:
        """在当前阅读窗内绘制完整五卡组。"""
        for index, item in enumerate(items):
            _draw_vocabulary_card(
                draw,
                item,
                index,
                viewport_y + index * (RIGHT_CARD_HEIGHT + RIGHT_CARD_GAP),
            )

    def _draw_feature_banner(self, output_path: Path) -> None:
        size = (FEATURE_BOX[2] - FEATURE_BOX[0], FEATURE_BOX[3] - FEATURE_BOX[1])
        if self.feature_reference.is_file():
            with Image.open(self.feature_reference) as source:
                ImageOps.fit(
                    source.convert("RGB"),
                    size,
                    method=Image.Resampling.LANCZOS,
                    centering=(0.5, 0.5),
                ).save(output_path)
            return
        fallback = Image.new("RGB", size, "#10263C")
        draw = ImageDraw.Draw(fallback)
        draw.rounded_rectangle((4, 4, size[0] - 4, size[1] - 4), radius=18, outline="#D8B56A", width=4)
        draw.text((32, 90), "影子跟读", font=_font(42, bold=True), fill="#F7E8BD")
        draw.text((34, 150), "紧跟原声 · 逐词训练", font=_font(23, bold=True), fill="#F7E8BD")
        fallback.save(output_path)


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
        index = 5 if bold and italic else 4 if bold else 2 if italic else 0
        return ImageFont.truetype(BASKERVILLE, size, index=index)
    return ImageFont.truetype(CHINESE_FONT, size)


def _latin_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    """正文英文使用紧凑清晰的 Avenir Next Condensed，给手机阅读留出空间。"""
    return ImageFont.truetype(AVENIR_NEXT_CONDENSED, size, index=2 if bold else 5)


def _ipa_font(size: int) -> ImageFont.FreeTypeFont:
    """音标必须使用已实测覆盖 /ˈspiːʃiːz/ 等 IPA 字形的字体。"""
    return ImageFont.truetype(ARIAL, size)


def _ellipsize(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> str:
    if font.getlength(text) <= max_width:
        return text
    ellipsis = "…"
    while text and font.getlength(text + ellipsis) > max_width:
        text = text[:-1]
    return text + ellipsis


def _learning_label(item: VocabularyItem) -> str:
    """将词表的学习友好标签和最低门槛压缩为窄卡中的一行信息。"""
    parts = [part for part in (item.friendly_tag.strip(), item.level.strip()) if part]
    return " · ".join(parts)


def _right_vocabulary_items(items: tuple[VocabularyItem, ...]) -> tuple[VocabularyItem, ...]:
    """右侧窄栏只承载左侧已标注词中的最高难度五个，避免和正文争夺注意力。"""
    ranked = sorted(items, key=lambda item: (-difficulty_level(item.level), item.word.lower()))
    return tuple(ranked[:RIGHT_VOCABULARY_LIMIT])


def _layout_line_notes(
    line: list[str],
    highlights: dict[int, tuple[str, bool]],
    english_font: ImageFont.FreeTypeFont,
    gloss_font: ImageFont.FreeTypeFont,
) -> tuple[dict[int, tuple[list[str], int, int]], int]:
    """为同一英文行的词下注释分层避让，保留完整中文而不重叠。"""
    token_positions: list[tuple[int, int]] = []
    x = TEXT_LEFT
    space_width = int(english_font.getlength(" "))
    for token in line:
        width = int(english_font.getlength(token))
        token_positions.append((x, width))
        x += width + space_width

    lanes: list[dict[str, object]] = []
    placements: dict[int, tuple[list[str], int, int]] = {}
    for token_index, (meaning, show_note) in highlights.items():
        if not meaning or not show_note:
            continue
        token_x, token_width = token_positions[token_index]
        available_width = max(150, min(220, token_width + 38))
        note_lines = _wrap_chinese(meaning, gloss_font, available_width)
        note_width = max(int(gloss_font.getlength(note_line)) for note_line in note_lines)
        note_x = max(TEXT_LEFT, min(token_x + (token_width - note_width) // 2, TEXT_LEFT + ENGLISH_LINE_WIDTH - note_width))
        range_start, range_end = note_x - 4, note_x + note_width + 4
        note_height = len(note_lines) * 27
        lane_index = next(
            (
                index for index, lane in enumerate(lanes)
                if all(range_end <= left or range_start >= right for left, right in lane["ranges"])
            ),
            None,
        )
        if lane_index is None:
            lane_index = len(lanes)
            lanes.append({"ranges": [], "height": 0})
        lane = lanes[lane_index]
        lane["ranges"].append((range_start, range_end))
        lane["height"] = max(int(lane["height"]), note_height)
        placements[token_index] = (note_lines, note_x, lane_index)

    lane_tops: list[int] = []
    next_y = 56
    for lane in lanes:
        lane_tops.append(next_y)
        next_y += int(lane["height"])
    resolved = {
        token_index: (note_lines, note_x, lane_tops[lane_index])
        for token_index, (note_lines, note_x, lane_index) in placements.items()
    }
    return resolved, max(92, next_y + 8)


def _draw_vocabulary_card(
    draw: ImageDraw.ImageDraw,
    item: VocabularyItem,
    index: int,
    y: int,
) -> None:
    """绘制一个右侧词卡；对齐卡和兜底卡共用同一视觉规格。"""
    palette = (ACCENT, "#EDE6DA", "#365E8B", "#EDE6DA", ACCENT)
    fill = palette[index % len(palette)]
    dark = fill in {ACCENT, "#365E8B"}
    text_color = "#FFFDF8" if dark else INK
    card = (VOCAB_BOX[0] + 12, y, VOCAB_BOX[2] - 12, y + RIGHT_CARD_HEIGHT)
    draw.rounded_rectangle(card, radius=14, fill=fill)
    word_font = _font(26, bold=True, serif=True)
    word_lines = _wrap_words(item.word.split(), word_font, 250)
    word_line_height = 29
    for line_index, word_line in enumerate(word_lines):
        draw.text(
            (card[0] + 15, card[1] + 10 + line_index * word_line_height),
            " ".join(word_line),
            font=word_font,
            fill=text_color,
        )
    detail_y = card[1] + 14 + len(word_lines) * word_line_height
    detail = item.phonetic.strip()
    if detail:
        ipa_font = _ipa_font(17)
        draw.text((card[0] + 15, detail_y), _ellipsize(detail, ipa_font, 250), font=ipa_font, fill=text_color)
    learning_label = _learning_label(item)
    if learning_label:
        draw.text(
            (card[0] + 15, detail_y + 22),
            _ellipsize(learning_label, _font(16, bold=True), 250),
            font=_font(16, bold=True),
            fill=text_color,
        )
    meaning_font = _font(19)
    _draw_wrapped_text(
        draw,
        _meaning_line(item),
        (card[0] + 15, detail_y + 45),
        meaning_font,
        text_color,
        250,
        max_lines=2,
        line_height=21,
    )


def _meaning_line(item: VocabularyItem) -> str:
    """合并词性和释义，但避免 ECDICT 释义自带词性导致 ``vt. vt.``。"""
    pos = _clean_pos(item.part_of_speech)
    meaning = _strip_leading_pos(item.meaning_zh).replace(";", "；").replace(",", "，")
    meaning = re.sub(r"([；，])\s+", r"\1", meaning)
    return " ".join(part for part in (pos, meaning) if part).strip()


def _micro_note_text(item: VocabularyItem) -> str:
    note = _strip_leading_pos(item.meaning_zh).replace(";", "；").replace(",", "，")
    note = re.sub(r"([；，])\s+", r"\1", note)
    # 正文词下注释只呈现语境中的主释义，避免把完整词典多义项塞进一行；
    # 这里不是按字符截断，右栏仍保留完整释义。
    primary = next((part.strip() for part in re.split(r"[；;]", note) if part.strip()), "")
    return primary or item.meaning_zh.strip()


def _clean_pos(value: str) -> str:
    seen: list[str] = []
    for token in POS_PATTERN.findall(value):
        normal = token.rstrip(".").lower() + "."
        if normal not in seen:
            seen.append(normal)
    return " ".join(seen)


def _strip_leading_pos(value: str) -> str:
    text = value.strip()
    while True:
        match = POS_PATTERN.match(text)
        if match is None:
            return text.lstrip(" ;；,，")
        text = text[match.end():].lstrip(" .;；,，")


def _draw_wrapped_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    xy: tuple[int, int],
    font: ImageFont.FreeTypeFont,
    fill: str,
    max_width: int,
    *,
    max_lines: int,
    line_height: int,
) -> None:
    lines = _wrap_limited_text(text, font, max_width, max_lines)
    x, y = xy
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += line_height


def _wrap_limited_text(text: str, font: ImageFont.FreeTypeFont, max_width: int, max_lines: int) -> list[str]:
    lines = _wrap_chinese(text, font, max_width)
    if len(lines) <= max_lines:
        return lines
    kept = lines[:max_lines]
    remainder = "".join(lines[max_lines - 1:])
    kept[-1] = _ellipsize(remainder, font, max_width)
    return kept


def _vocabulary_anchor_y(item: VocabularyItem, boxes: tuple[WordBox, ...]) -> int | None:
    phrase = tuple(part for part in (_normalise_word(part) for part in item.word.split()) if part)
    if not phrase:
        return None
    page_words = tuple(_normalise_word(box.text) for box in boxes)
    for index in range(0, len(page_words) - len(phrase) + 1):
        if page_words[index:index + len(phrase)] == phrase:
            return boxes[index].y - 53
    return None


def _normalise_phrase(value: str) -> str:
    return " ".join(part for part in (_normalise_word(part) for part in value.split()) if part)


def _vocabulary_occurrence_y_positions(item: VocabularyItem, boxes: tuple[WordBox, ...]) -> tuple[int, ...]:
    phrase = tuple(part for part in _normalise_phrase(item.word).split() if part)
    if not phrase:
        return ()
    page_words = tuple(_normalise_word(box.text) for box in boxes)
    return tuple(
        boxes[index].y - 53
        for index in range(0, len(page_words) - len(phrase) + 1)
        if page_words[index:index + len(phrase)] == phrase
    )


def _normalise_word(value: str) -> str:
    return re.sub(r"[^a-z0-9']+", "", value.lower())


def _highlighted_token_indices(
    tokens: list[str], items: tuple[VocabularyItem, ...],
) -> dict[int, tuple[str, bool]]:
    """贪心匹配最长词组，确保 ``heat wave`` 等词卡在正文有完整红底对应。"""
    phrase_items = sorted(
        (
            (tuple(_normalise_word(part) for part in item.word.split()), _micro_note_text(item))
            for item in items
        ),
        key=lambda item: len(item[0]),
        reverse=True,
    )
    normalized_tokens = tuple(_normalise_word(token) for token in tokens)
    matched: dict[int, tuple[str, bool]] = {}
    index = 0
    while index < len(tokens):
        for phrase, meaning in phrase_items:
            end = index + len(phrase)
            if phrase and normalized_tokens[index:end] == phrase:
                matched[index] = (meaning, True)
                for nested_index in range(index + 1, end):
                    matched[nested_index] = (meaning, False)
                index = end
                break
        else:
            index += 1
    return matched
