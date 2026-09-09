"""保留 JSON3 原词与事件依据，不用猜测时长制造逐词锚点。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-09 | Codex | 确定性解析、规范化记录和 ASR 差异证据。 |
| 1.0.1 | 2026-09-09 | Codex | 保留片段边界跨越的原字幕，并仅以 ASR 确定边界内词序。 |
| 1.0.2 | 2026-09-09 | Codex | 仅将 ASR 的 U S 和数字年龄拆词作受限排印等价，保留原文词形与全部差异。 |
| 1.0.3 | 2026-09-09 | Codex | 仅修复同一锚点堆叠的零宽 ASR 词时长，并逐组保留审计证据。 |
"""
import difflib
import math
import re

TOKEN = re.compile(r"[+-]?[$£€]?[A-Za-z0-9]+(?:[’'][A-Za-z0-9]+)*(?:[.,]\d+)*(?:[-–][A-Za-z0-9]+)*%?")
PARSER_VERSION = "json3-asr-v1.3"


def tokens(text):
    return TOKEN.findall(text.replace("’", "'"))


def parse_json3(payload, start, end):
    """多词 seg 保留全部文字并要求 ASR 对齐；不把一个 seg 误当一个词。"""
    if not all(math.isfinite(x) for x in (start, end)) or not 0 <= start < end:
        raise ValueError("非法来源区间")
    segments, changes, seen = [], [], set()
    boundary_clipped = {"start": False, "end": False}
    for ei, event in enumerate(payload.get("events", [])):
        base = event.get("tStartMs", 0) / 1000
        stop = base + event.get("dDurationMs", 0) / 1000
        for si, seg in enumerate(event.get("segs", [])):
            absolute = base + (seg.get("tOffsetMs") or 0) / 1000
            raw = seg.get("utf8", "")
            words = tokens(raw)
            if not words or stop <= start or absolute >= end:
                continue
            key = (absolute, tuple(words))
            if key in seen:
                continue
            seen.add(key)
            normalized = [re.sub(r"^(\d+)year-olds$", r"\1-year-olds", w) for w in words]
            ref = f"events[{ei}].segs[{si}]"
            if normalized != words:
                changes.append({"kind": "typography", "before": words, "after": normalized,
                                "source_ref": ref, "source_start": absolute})
            starts_before, ends_after = absolute < start, stop > end
            boundary_clipped["start"] |= starts_before
            boundary_clipped["end"] |= ends_after
            segments.append({"tokens": normalized, "raw": raw, "source_ref": ref,
                             "start": max(absolute, start) - start, "event_end": min(stop, end) - start,
                             "clipped_start": starts_before, "clipped_end": ends_after})
    segments.sort(key=lambda x: x["start"])
    if not segments:
        raise ValueError("选定区间没有字幕")
    words, unresolved = [], []
    for i, seg in enumerate(segments):
        stop = min(seg["event_end"], segments[i + 1]["start"] if i + 1 < len(segments) else end - start)
        if len(seg["tokens"]) != 1 or stop <= seg["start"]:
            unresolved.append(seg["source_ref"])
        else:
            words.append({"text": seg["tokens"][0], "start": round(seg["start"], 3), "end": round(stop, 3)})
    return {"schema_version": 1, "segments": segments, "changes": changes,
            "english_text": " ".join(w for s in segments for w in s["tokens"]),
            "words": words if not unresolved else [], "requires_alignment": unresolved,
            "source_start": start, "source_end": end, "boundary_clipped": boundary_clipped}


def transcript_differences(expected, observed):
    """只记录差异；自动 ASR 不是正文修改授权。"""
    left, right = [x.lower() for x in tokens(expected)], [x.lower() for x in tokens(observed)]
    return [{"kind": tag, "expected_span": [a, b], "observed_span": [c, d],
             "expected": left[a:b], "observed": right[c:d]}
            for tag, a, b, c, d in difflib.SequenceMatcher(None, left, right, autojunk=False).get_opcodes()
            if tag != "equal"]


def repair_asr_word_timestamps(words, duration):
    """修复 Whisper 同一锚点的零宽词；其他任何时间异常仍直接失败。

    Whisper 偶尔会把短词和紧邻词同时落在一个时间点，例如 ``The U``。
    仅在零宽词后续连续词的 *开始时间完全相同* 时，才能在该组已知
    ``start`` 到最后一词 ``end`` 的区间内等分。原始值和替换值均留在
    repair 记录中，供语言审校和人工追溯；不得用此函数猜测词序或文本。
    """
    if not isinstance(words, list) or not words or not math.isfinite(duration) or duration <= 0:
        raise ValueError("UNCERTAIN: ASR 逐词时间轴或来源时长非法")
    normalized = [dict(word) for word in words]
    repairs, index = [], 0
    while index < len(normalized):
        try:
            start, end = float(normalized[index]["start"]), float(normalized[index]["end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("UNCERTAIN: ASR 缺少可解析词时间") from exc
        if not math.isfinite(start + end):
            raise ValueError("UNCERTAIN: ASR 词时间不是有限数")
        if end > start:
            index += 1
            continue
        if end != start:
            raise ValueError("UNCERTAIN: ASR 词时间倒退")
        stop = index + 1
        while stop < len(normalized):
            try:
                next_start = float(normalized[stop]["start"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("UNCERTAIN: ASR 缺少可解析词时间") from exc
            if not math.isfinite(next_start) or abs(next_start - start) > 1e-6:
                break
            stop += 1
        try:
            group_end = float(normalized[stop - 1]["end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("UNCERTAIN: ASR 缺少可解析词时间") from exc
        if not math.isfinite(group_end) or group_end <= start:
            raise ValueError("UNCERTAIN: 零宽 ASR 词没有可证明的后续边界")
        before = [{"word": str(word.get("word", "")), "start": word["start"], "end": word["end"]}
                  for word in normalized[index:stop]]
        width = (group_end - start) / (stop - index)
        for offset, word in enumerate(normalized[index:stop]):
            word["start"] = round(start + offset * width, 3)
            word["end"] = round(start + (offset + 1) * width, 3)
        repairs.append({"kind": "zero_width_asr_anchor", "word_indexes": list(range(index, stop)),
                        "before": before,
                        "after": [{"word": str(word.get("word", "")), "start": word["start"], "end": word["end"]}
                                  for word in normalized[index:stop]],
                        "evidence": "同一 ASR 起点、末词有正时长；仅在该已知区间内等分。"})
        index = stop
    previous = 0.0
    for word in normalized:
        try:
            start, end = float(word["start"]), float(word["end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("UNCERTAIN: ASR 缺少可解析词时间") from exc
        if not math.isfinite(start + end) or start < previous - 0.001 or not start < end <= duration + 0.001:
            raise ValueError("UNCERTAIN: ASR 词时间无法修复为单调来源锚点")
        previous = end
    return normalized, repairs


def align_json3(parsed, asr_words):
    """多词字幕以真实 ASR 锚点对齐；仅允许裁去已记录的片段边界残词。"""
    expected = tokens(parsed["english_text"])
    observed = []
    for word in asr_words:
        parts = tokens(word.get("word", ""))
        if len(parts) != 1:
            raise ValueError("UNCERTAIN: ASR 词片不能唯一绑定字幕词")
        observed.append(parts[0])
    expected_units = [(word.lower(), index, index + 1) for index, word in enumerate(expected)]
    observed_units = _asr_comparison_units(observed)
    expected_lower = [unit[0] for unit in expected_units]
    observed_lower = [unit[0] for unit in observed_units]
    unit_offset = 0
    if expected_lower != observed_lower:
        matches = [i for i in range(len(expected_lower) - len(observed_lower) + 1)
                   if expected_lower[i:i + len(observed_lower)] == observed_lower]
        if len(matches) != 1:
            raise ValueError("UNCERTAIN: ASR 与字幕词序不一致，不自动覆盖字幕")
        unit_offset = matches[0]
        expected_start = expected_units[unit_offset][1]
        expected_end = expected_units[unit_offset + len(observed_units) - 1][2]
        boundary = parsed.get("boundary_clipped", {})
        if (expected_start and not boundary.get("start")) or (expected_end < len(expected)
                                                               and not boundary.get("end")):
            raise ValueError("UNCERTAIN: ASR 与字幕词序不一致，不自动覆盖字幕")
    result, previous = [], 0.0
    for expected_unit, observed_unit in zip(expected_units[unit_offset:unit_offset + len(observed_units)], observed_units):
        _, expected_start, expected_end = expected_unit
        _, observed_start, observed_end = observed_unit
        if expected_end - expected_start != 1:
            raise ValueError("UNCERTAIN: 字幕缩写不能唯一保留原文词形")
        start = round(float(asr_words[observed_start]["start"]), 3)
        end = round(float(asr_words[observed_end - 1]["end"]), 3)
        if not math.isfinite(start + end) or start < previous or not start < end <= parsed["source_end"] - parsed["source_start"]:
            raise ValueError("UNCERTAIN: ASR 锚点重叠或越界")
        result.append({"text": expected[expected_start], "start": start, "end": end})
        previous = end
    return result


def _asr_comparison_units(words):
    """只接受 U.S. 与 ``15-year-olds`` 的常见 ASR 拆词，不放宽一般词差异。"""
    units, index = [], 0
    while index < len(words):
        current = words[index].lower()
        if (re.fullmatch(r"\d+", current) and index + 2 < len(words)
                and words[index + 1].lower() == "-year" and words[index + 2].lower() == "-olds"):
            units.append((f"{current}-year-olds", index, index + 3))
            index += 3
        elif current == "u" and index + 1 < len(words) and words[index + 1].lower() == "s":
            units.append(("us", index, index + 2))
            index += 2
        else:
            units.append((current, index, index + 1))
            index += 1
    return units
