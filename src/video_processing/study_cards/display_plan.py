"""提前冻结教学内容与真实排版；渲染不得从大候选池补词。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-09 | Codex | A2-B1 展示计划、出现位置校验和共享布局验证。 |
"""
from dataclasses import asdict, replace
from pathlib import Path
import tempfile

from .language_qa import VERSION, digest
from .models import StudyCardContent, VocabularyItem
from .template_a import (RecordUnderlineTemplate, TEXT_TOP, READING_VIEWPORT_BOTTOM,
                          _vocabulary_occurrence_y_positions, _normalise_phrase,
                          _meaning_line, _wrap_chinese, _font, _ipa_font)


def reviewed_content(payload):
    """仅接受显式出现位置的编辑候选，不沿用 confidence/难度自动过滤。"""
    content = StudyCardContent.from_mapping(payload)
    items, occupied = [], set()
    for raw in sorted(payload.get("learning_points", []), key=lambda p: p["word_index"]):
        index = raw["word_index"]
        word = raw["word"]
        if type(index) is not int or not 0 <= index < len(content.words):
            raise ValueError("学习点出现位置非法")
        size = len(word.split())
        actual = " ".join(w.text for w in content.words[index:index + size])
        if _normalise_phrase(actual) != _normalise_phrase(word):
            raise ValueError("学习点与出现位置不一致")
        positions = set(range(index, index + size))
        if occupied & positions:
            raise ValueError("学习点不能重复或重叠")
        occupied |= positions
        for field in ("context_meaning_zh", "pos", "phonetic", "dictionary_source", "phonetic_word"):
            if not isinstance(raw.get(field), str) or not raw[field].strip():
                raise ValueError(f"学习点缺少 {field}")
        if raw["phonetic_word"].lower() != word.lower():
            if f"0:{raw['phonetic_word']}" not in raw.get("dictionary_senses", {}).get("exchange", "").split("/"):
                raise ValueError("词元音标缺少词典词形依据")
        meaning = raw["context_meaning_zh"]
        if any(x in meaning for x in ("…", "...", ";", "；")):
            raise ValueError("学习点需单一完整语境义，不可堆词典义或省略")
        item = VocabularyItem(word=word, meaning_zh=meaning, phonetic=raw["phonetic"],
                              part_of_speech=raw["pos"], level=raw.get("level", ""),
                              source=raw["dictionary_source"], word_index=index,
                              item_id=f"word:{index}:{size}", phonetic_word=raw["phonetic_word"])
        if len(_wrap_chinese(_meaning_line(item), _font(19), 250)) > 2:
            raise ValueError("右栏释义过长，请编辑后重新审校")
        detail = item.phonetic if item.phonetic_word.lower() == item.word.lower() else f"{item.phonetic_word}: {item.phonetic}"
        if _ipa_font(17).getlength(detail) > 250:
            raise ValueError("右栏音标溢出")
        items.append(item)
    if "".join(p.translation_zh for p in content.paragraphs) != content.translation_zh:
        raise ValueError("全文中文与逐段中文不一致")
    return replace(content, vocabulary=tuple(items), vocabulary_candidates=tuple(items))


def layout(content, template, directory, *, enforce_density=True):
    # 外层在调用时导入，避免 renderer -> display_plan -> renderer 模块循环。
    from .renderer import StudyCardRenderer
    assets = template.render_static(content, directory)
    for item in content.vocabulary:
        positions = assets.word_boxes[item.word_index:item.word_index + len(item.word.split())]
        if len({b.y for b in positions}) > 1:
            raise ValueError("学习短语跨行，无法完整标注；请调整段落或学习点")
    boxes = template.map_word_boxes(content.words, assets.word_boxes)
    steps = StudyCardRenderer(template)._build_scroll_steps(content, boxes, paragraph_bottoms=assets.paragraph_bottoms)
    screens = []
    for i, offset in enumerate((0, *(s.to_offset for s in steps))):
        visible = [v for v in content.vocabulary if any(TEXT_TOP <= y - offset <= READING_VIEWPORT_BOTTOM - 80
                    for y in _vocabulary_occurrence_y_positions(v, assets.word_boxes))]
        lower, upper = (0, 3) if i == len(steps) else (3, 5)
        if enforce_density and not lower <= len(visible) <= upper:
            raise ValueError(f"第 {i+1} 屏有 {len(visible)} 个学习点，要求 {lower}–{upper}；请重新分屏一次")
        screens.append({"index": i, "offset": offset, "micro_notes": [v.item_id for v in visible],
                        "right_cards": [v.item_id for v in visible[:5]],
                        "visible_word_indices": [j for j, b in enumerate(assets.word_boxes)
                            if TEXT_TOP <= b.y - offset <= READING_VIEWPORT_BOTTOM - 80]})
    used = {v for s in screens for v in s["micro_notes"]}
    if used != {v.item_id for v in content.vocabulary}:
        raise ValueError("存在从未上屏的学习点")
    return assets, boxes, steps, screens


def build_plan(payload, timeline_sha256, template=None):
    content = reviewed_content(payload)
    if _font(40, bold=True).getlength(content.headline_zh) > 640:
        raise ValueError("标题超出展示宽度，不允许截断")
    publication = payload.get("publication_text")
    if not isinstance(publication, dict) or any(not publication.get(k) for k in ("title", "copy", "cover_payload")):
        raise ValueError("冻结前必须提供实际投稿 title/copy/cover_payload")
    from cover.english_world import validate_english_world_cover_payload
    publication = dict(publication)
    publication["cover_payload"] = validate_english_world_cover_payload(publication["cover_payload"])
    template = template or RecordUnderlineTemplate()
    template.language_reviewed = True
    with tempfile.TemporaryDirectory(prefix="english_display_plan_") as directory:
        _, _, steps, screens = layout(content, template, Path(directory))
    return {"version": VERSION, "layout_version": "template-a-language-v1.1",
            "presentation_text": ["世界英语新闻时事深度阅读", "A2–B1 家庭精读 / 原声 · 语境 · 跟读",
                                  "影子跟读", "紧跟原声 · 逐词训练", "核心词汇"],
            "timeline_sha256": timeline_sha256, "content": asdict(content),
            "screens": screens, "scroll_steps": [asdict(x) for x in steps],
            "learning_evidence": payload["learning_points"],
            "publication_text": publication}


def verify_plan(payload, plan, timeline_sha256, template=None):
    if digest(build_plan(payload, timeline_sha256, template)) != digest(plan):
        raise ValueError("实际布局或内容与冻结展示计划不一致")
    return reviewed_content(payload)
