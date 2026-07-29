"""配音版中文语义字幕分页与 ASS 渲染。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-29 | Codex | 按完整句子分页，超长句仅在自然停顿处分屏，并生成大字号中文 ASS |
| 1.0.1 | 2026-07-29 | Codex | 为单个语义页加入安全宽度内的视觉折行，防止大字号字幕横向溢出 |
| 1.0.2 | 2026-07-29 | Codex | 视觉折行保护中文数字短语与英文代号，避免百分比等关键信息被拆开 |
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Iterable, List

import pysubs2

from ..utils.layout import VerticalLayout


_SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？!?])")
_PAUSE_BOUNDARY = re.compile(r"(?<=[，；：,;:])")
_LINE_BREAK_PUNCTUATION = set("，；：。！？,;:!?")
_PROTECTED_INLINE_TOKEN = re.compile(r"百分之[零一二三四五六七八九十百千万亿兆两〇0-9.]+|[A-Za-z][A-Za-z0-9.-]*")


def build_semantic_pages(entries: Iterable[Dict[str, Any]], *, max_chars: int) -> List[Dict[str, Any]]:
    """将 MiniMax 实际时间戳改写为语义页时间轴，不在连贯表达中间断页。"""
    if max_chars < 8:
        raise ValueError("max_chars 必须至少为 8")

    pages: List[Dict[str, Any]] = []
    for entry in entries:
        text = _clean_text(str(entry.get("text") or ""))
        start_ms = int(entry.get("start_ms") or 0)
        end_ms = int(entry.get("end_ms") or 0)
        if not text or end_ms <= start_ms:
            continue
        fragments = _split_at_semantic_boundaries(text, max_chars=max_chars)
        weights = [max(1, _reading_weight(fragment)) for fragment in fragments]
        duration = end_ms - start_ms
        accrued = 0
        for index, (fragment, weight) in enumerate(zip(fragments, weights)):
            page_start = start_ms + round(duration * accrued / sum(weights))
            accrued += weight
            page_end = end_ms if index == len(fragments) - 1 else start_ms + round(duration * accrued / sum(weights))
            if page_end > page_start:
                pages.append({"start_ms": page_start, "end_ms": page_end, "text": fragment})
    return pages


def write_page_ass(
    pages: Iterable[Dict[str, Any]], output: Path, *, font_size: int, subtitle_y: int, max_line_chars: int,
) -> Path:
    """写入单语大字号 ASS；每一个事件即为一个语义字幕页。"""
    if font_size < 36:
        raise ValueError("font_size 过小，不适合作为配音字幕")
    subs = pysubs2.SSAFile()
    subs.info["PlayResX"] = VerticalLayout.CANVAS_WIDTH
    subs.info["PlayResY"] = VerticalLayout.CANVAS_HEIGHT
    subs.info["WrapStyle"] = "0"
    subs.styles["DubbingPage"] = pysubs2.SSAStyle(
        fontname="Hiragino Sans GB",
        fontsize=font_size,
        primarycolor=pysubs2.Color(242, 239, 233),
        outlinecolor=pysubs2.Color(0, 0, 0, 120),
        backcolor=pysubs2.Color(0, 0, 0, 120),
        borderstyle=3,
        outline=12,
        shadow=0,
        alignment=8,
        marginl=24,
        marginr=24,
        marginv=subtitle_y,
    )
    for page in pages:
        text = _clean_text(str(page.get("text") or ""))
        if text:
            display_text = wrap_page_lines(text, max_line_chars=max_line_chars)
            subs.events.append(
                pysubs2.SSAEvent(
                    start=int(page["start_ms"]),
                    end=int(page["end_ms"]),
                    style="DubbingPage",
                    text=display_text.replace("\n", r"\N"),
                )
            )
    output.parent.mkdir(parents=True, exist_ok=True)
    subs.save(str(output))
    return output


def wrap_page_lines(text: str, *, max_line_chars: int) -> str:
    """仅在同一语义页内折行；优先取附近标点，保证任何一行不会越过安全宽度。"""
    if max_line_chars < 8:
        raise ValueError("max_line_chars 必须至少为 8")
    remaining = _clean_text(text)
    lines: List[str] = []
    while len(remaining) > max_line_chars:
        # 为标点留一个字符的弹性，避免逗号、句号孤零零地掉到下一行。
        upper_bound = min(len(remaining), max_line_chars + 1)
        lower_bound = max(1, max_line_chars - 4)
        split_at = next(
            (index for index in range(upper_bound, lower_bound - 1, -1) if remaining[index - 1] in _LINE_BREAK_PUNCTUATION),
            max_line_chars,
        )
        split_at = _avoid_protected_token_break(remaining, split_at, max_line_chars)
        lines.append(remaining[:split_at])
        remaining = remaining[split_at:]
    if remaining:
        lines.append(remaining)
    return "\n".join(lines)


def _avoid_protected_token_break(text: str, split_at: int, max_line_chars: int) -> int:
    """调整落在百分比/英文代号内部的断点，优先把整个关键短语放到下一行。"""
    for match in _PROTECTED_INLINE_TOKEN.finditer(text):
        if match.start() < split_at < match.end():
            if match.start() > 0:
                return match.start()
            # 首行本身就是超长不可拆 token 时才退化为安全宽度截断。
            return min(match.end(), max_line_chars + 1)
    return split_at


def _split_at_semantic_boundaries(text: str, *, max_chars: int) -> List[str]:
    sentences = [item.strip() for item in _SENTENCE_BOUNDARY.split(text) if item.strip()]
    return [page for sentence in sentences for page in _split_long_sentence(sentence, max_chars=max_chars)]


def _split_long_sentence(sentence: str, *, max_chars: int) -> List[str]:
    if _reading_weight(sentence) <= max_chars:
        return [sentence]
    clauses = [item.strip() for item in _PAUSE_BOUNDARY.split(sentence) if item.strip()]
    if len(clauses) <= 1:
        # 无自然停顿的长句宁可保持完整，不用字符截断破坏语义。
        return [sentence]
    pages: List[str] = []
    current = ""
    for clause in clauses:
        if current and _reading_weight(current + clause) > max_chars:
            pages.append(current)
            current = clause
        else:
            current += clause
    if current:
        pages.append(current)
    return pages


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", "", text.replace(r"\N", " ")).strip()


def _reading_weight(text: str) -> int:
    return len(re.sub(r"\s+", "", text))
