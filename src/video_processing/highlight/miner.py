"""基于带时间轴 WebVTT 的本地 Highlight 候选生成器。

本模块只生成可审计候选，当前不调用外部模型，也不切视频、不渲染、不发布。候选的
``raw_*`` 时间轴会在后续声学吸附阶段生成独立的 ``snapped_*`` 边界，避免把启发式边界
误称为精确切点。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-08-20 | Codex | 解析 YouTube 滚动 WebVTT 时仅保留新增词段，消除候选正文的累积重复 |
| 1.0.0 | 2026-08-20 | Codex | 新增 VTT 时间轴候选提取、评分及去重的纯函数实现 |
"""

from __future__ import annotations

from dataclasses import dataclass
import html
import re
from uuid import uuid4


_TIMING_RE = re.compile(
    r"(?P<start>\d{1,2}:\d{2}:\d{2}(?:\.\d{1,3})?|\d{1,2}:\d{2}(?:\.\d{1,3})?)\s+-->\s+"
    r"(?P<end>\d{1,2}:\d{2}:\d{2}(?:\.\d{1,3})?|\d{1,2}:\d{2}(?:\.\d{1,3})?)"
)
_TAG_RE = re.compile(r"<[^>]+>")
_SENTENCE_END_RE = re.compile(r"[.!?。！？…][\"”’']?$")
_CONTRAST_RE = re.compile(
    r"\b(?:but|however|yet|instead|never|cannot|can't|wrong|truth|actually)\b|"
    r"但是|然而|却|而是|并非|从不|真相|事实|颠覆|反而"
    ,
    re.IGNORECASE,
)
_QUESTION_RE = re.compile(r"[?？]")


@dataclass(frozen=True)
class TimedCue:
    """一个清洗后的 WebVTT cue。"""

    start_ms: int
    end_ms: int
    text: str


def parse_webvtt_cues(raw: str) -> list[TimedCue]:
    """解析带时间轴的 WebVTT，并把滚动自动字幕还原为不重复的词段。"""
    cues: list[TimedCue] = []
    start_ms: int | None = None
    end_ms: int | None = None
    text_lines: list[str] = []
    rolling_text = ""

    def flush() -> None:
        nonlocal start_ms, end_ms, text_lines, rolling_text
        if start_ms is None or end_ms is None or not text_lines:
            start_ms, end_ms, text_lines = None, None, []
            return
        text = _clean_text(" ".join(text_lines))
        if text and end_ms > start_ms:
            novel_text, rolling_text = _split_rolling_caption(rolling_text, text)
            if novel_text:
                cues.append(TimedCue(start_ms, end_ms, novel_text))
        start_ms, end_ms, text_lines = None, None, []

    for raw_line in (raw or "").replace("\r\n", "\n").split("\n"):
        line = raw_line.strip()
        timing = _TIMING_RE.search(line)
        if timing:
            flush()
            start_ms = _timestamp_to_ms(timing.group("start"))
            end_ms = _timestamp_to_ms(timing.group("end"))
            continue
        if not line:
            flush()
            continue
        if start_ms is not None:
            text_lines.append(line)
    flush()
    return cues


def mine_candidates(
    cues: list[TimedCue], *, max_clips: int, min_duration_sec: float, max_duration_sec: float,
) -> list[dict[str, object]]:
    """按语义收束点组成候选、评分，并返回互不严重重叠的 Top N。"""
    if not cues:
        return []
    min_ms = max(10_000, int(min_duration_sec * 1000))
    max_ms = max(min_ms, int(max_duration_sec * 1000))
    chunks: list[tuple[int, int, str]] = []
    start_index = 0

    for index, cue in enumerate(cues):
        duration = cue.end_ms - cues[start_index].start_ms
        closes_sentence = bool(_SENTENCE_END_RE.search(cue.text))
        must_flush = duration >= max_ms
        natural_flush = duration >= min_ms and closes_sentence
        if not (must_flush or natural_flush):
            continue
        chunk = _build_chunk(cues[start_index:index + 1])
        if chunk is not None:
            chunks.append(chunk)
        start_index = index + 1

    if start_index < len(cues):
        tail = _build_chunk(cues[start_index:])
        if tail is not None and tail[1] - tail[0] >= min_ms:
            chunks.append(tail)

    ranked = sorted(
        (_candidate_payload(start, end, text, min_ms=min_ms, max_ms=max_ms) for start, end, text in chunks),
        key=lambda item: (-float(item["virality_score"]), int(item["raw_start_ms"])),
    )
    selected: list[dict[str, object]] = []
    for candidate in ranked:
        if len(selected) >= max(1, int(max_clips)):
            break
        if any(_overlap_ratio(candidate, existing) > 0.20 for existing in selected):
            continue
        selected.append(candidate)
    selected.sort(key=lambda item: int(item["raw_start_ms"]))
    return selected


def _build_chunk(cues: list[TimedCue]) -> tuple[int, int, str] | None:
    if not cues:
        return None
    text = _join_cue_texts(cue.text for cue in cues)
    if len(text) < 48:
        return None
    return cues[0].start_ms, cues[-1].end_ms, text


def _candidate_payload(start_ms: int, end_ms: int, text: str, *, min_ms: int, max_ms: int) -> dict[str, object]:
    duration = max(1, end_ms - start_ms)
    density = min(20.0, len(text) / max(duration / 1000, 1.0) * 2.2)
    contrast = 25.0 if _CONTRAST_RE.search(text) else 4.0
    question = 18.0 if _QUESTION_RE.search(text) else 5.0
    complete = 20.0 if _SENTENCE_END_RE.search(text) else 10.0
    midpoint = (min_ms + max_ms) / 2
    duration_fit = max(0.0, 17.0 - abs(duration - midpoint) / max(midpoint, 1) * 17.0)
    score = min(100.0, round(density + contrast + question + complete + duration_fit, 1))
    reason_parts = [
        "存在认知反差" if contrast >= 20 else "叙事表达完整",
        "含问句/反问" if question >= 15 else "非问句表达",
        f"时长 {duration / 1000:.1f}s",
    ]
    return {
        "id": uuid4().hex,
        "raw_start_ms": start_ms,
        "raw_end_ms": end_ms,
        "snapped_start_ms": None,
        "snapped_end_ms": None,
        "virality_score": score,
        "core_quote": _core_quote(text),
        "source_text": text,
        "score_reason": "；".join(reason_parts),
    }


def _timestamp_to_ms(value: str) -> int:
    parts = value.split(":")
    seconds = float(parts[-1])
    minutes = int(parts[-2])
    hours = int(parts[-3]) if len(parts) == 3 else 0
    return int(round((hours * 3600 + minutes * 60 + seconds) * 1000))


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG_RE.sub("", value or ""))).strip()


def _is_duplicate_or_progressive(previous: str, current: str) -> bool:
    return current == previous or current.startswith(previous) or previous.endswith(current)


def _split_rolling_caption(previous: str, current: str) -> tuple[str, str]:
    """从滚动字幕中抽取新增词，并返回累计全文。

    YouTube 自动字幕常把上一屏末尾的多个词复制到下一 cue 开头。每条 cue
    的时间轴仍有价值，但整段显示文本不可直接拼接；这里按连续词的最长
    后缀/前缀重叠剥离旧词，保留当前 cue 的新增尾部。
    """
    current_tokens = current.split()
    if not current_tokens:
        return "", previous
    if not previous:
        return current, current
    previous_tokens = previous.split()
    previous_normalized = [_normalize_caption_token(token) for token in previous_tokens]
    current_normalized = [_normalize_caption_token(token) for token in current_tokens]
    max_overlap = min(len(previous_normalized), len(current_normalized))
    overlap = 0
    for size in range(max_overlap, 0, -1):
        if previous_normalized[-size:] == current_normalized[:size]:
            overlap = size
            break
    if overlap:
        novel = " ".join(current_tokens[overlap:]).strip()
        merged = previous if not novel else f"{previous} {novel}"
        return novel, merged
    normalized_current = " ".join(current_normalized)
    normalized_previous = " ".join(previous_normalized)
    if normalized_current and normalized_current in normalized_previous:
        return "", previous
    return current, f"{previous} {current}"


def _normalize_caption_token(token: str) -> str:
    """比较滚动字幕时忽略大小写和包裹标点，不改变最终展示文本。"""
    return re.sub(r"[^\w%$&'-]+", "", token.lower())


def _join_cue_texts(texts) -> str:
    joined = ""
    for text in texts:
        clean = _clean_text(text)
        if not clean:
            continue
        if not joined:
            joined = clean
        elif clean.startswith(joined):
            joined = clean
        elif joined.endswith(clean):
            continue
        else:
            joined = f"{joined} {clean}"
    return re.sub(r"\s+", " ", joined).strip()


def _core_quote(text: str) -> str:
    sentence = re.split(r"(?<=[.!?。！？])\s+", text.strip(), maxsplit=1)[0].strip()
    return sentence[:180] or text[:180]


def _overlap_ratio(left: dict[str, object], right: dict[str, object]) -> float:
    start = max(int(left["raw_start_ms"]), int(right["raw_start_ms"]))
    end = min(int(left["raw_end_ms"]), int(right["raw_end_ms"]))
    overlap = max(0, end - start)
    shorter = min(
        int(left["raw_end_ms"]) - int(left["raw_start_ms"]),
        int(right["raw_end_ms"]) - int(right["raw_start_ms"]),
    )
    return overlap / max(shorter, 1)
