"""保留 JSON3 原词与事件依据，不用猜测时长制造逐词锚点。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-09 | Codex | 确定性解析、规范化记录和 ASR 差异证据。 |
| 1.0.1 | 2026-09-09 | Codex | 保留片段边界跨越的原字幕，并仅以 ASR 确定边界内词序。 |
| 1.0.2 | 2026-09-09 | Codex | 仅将 ASR 的 U S 和数字年龄拆词作受限排印等价，保留原文词形与全部差异。 |
| 1.0.3 | 2026-09-09 | Codex | 仅修复同一锚点堆叠的零宽 ASR 词时长，并逐组保留审计证据。 |
| 1.0.4 | 2026-09-11 | Codex | 允许同值数字、连字符拆分和有真实 ASR 锚点的冠词差异，保留其他词义差异。 |
"""
import difflib
import math
import re

TOKEN = re.compile(r"[+-]?[$£€]?[A-Za-z0-9]+(?:[’'][A-Za-z0-9]+)*(?:[.,]\d+)*(?:[-–][A-Za-z0-9]+)*%?")
PARSER_VERSION = "json3-asr-v1.4"
_ARTICLES = frozenset({"a", "an", "the"})
_NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20,
}


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
    """只记录实义差异；被允许的排印/冠词归一化另存为审计记录。"""
    left, right = [x.lower() for x in tokens(expected)], [x.lower() for x in tokens(observed)]
    return [record for record in _transcript_comparison(left, right) if "normalization" not in record]


def transcript_normalizations(expected, observed):
    """返回已放行的受限等价项，供来源证据审计，不掩盖正文差异。"""
    left, right = [x.lower() for x in tokens(expected)], [x.lower() for x in tokens(observed)]
    return [record for record in _transcript_comparison(left, right) if "normalization" in record]


def _transcript_comparison(left, right):
    records = []
    for tag, a, b, c, d in difflib.SequenceMatcher(None, left, right, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        expected, observed = left[a:b], right[c:d]
        normalization = _normalization_kind(expected, observed)
        record = {"kind": tag, "expected_span": [a, b], "observed_span": [c, d],
                  "expected": expected, "observed": observed}
        if normalization:
            record["normalization"] = normalization
        records.append(record)
    return records


def _normalization_kind(expected, observed):
    if len(expected) == len(observed) == 1:
        if _comparison_key(expected[0]) == _comparison_key(observed[0]) and expected[0] != observed[0]:
            return "same_numeric_value"
        if expected[0] in _ARTICLES and observed[0] in _ARTICLES:
            return "article_substitution"
    if len(expected) == 1 and ("-" in expected[0] or "–" in expected[0]):
        canonical_expected = expected[0].replace("–", "-")
        if "-".join(observed) == canonical_expected:
            return "hyphenated_compound_split"
    if not expected and observed and all(word in _ARTICLES for word in observed):
        return "asr_extra_article"
    return ""


def _comparison_key(value):
    lowered = value.lower().replace("’", "'")
    if lowered.isdigit():
        return f"number:{int(lowered)}"
    if lowered in _NUMBER_WORDS:
        return f"number:{_NUMBER_WORDS[lowered]}"
    return lowered


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
    """多词字幕以真实 ASR 锚点对齐；只放行已审计的有限文本等价。"""
    expected = tokens(parsed["english_text"])
    observed = []
    for word in asr_words:
        parts = tokens(word.get("word", ""))
        if len(parts) != 1:
            raise ValueError("UNCERTAIN: ASR 词片不能唯一绑定字幕词")
        observed.append(parts[0])
    expected_units = [(_comparison_key(word), index, index + 1) for index, word in enumerate(expected)]
    observed_units = [(_comparison_key(word), start, end)
                      for word, start, end in _asr_comparison_units(observed, expected)]
    matched_units = _align_comparison_units(
        expected_units, observed_units, parsed.get("boundary_clipped", {}), len(expected),
    )
    result, previous = [], 0.0
    for expected_unit, observed_unit in matched_units:
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


def _align_comparison_units(expected_units, observed_units, boundary, expected_count):
    """在不推断缺失字幕词时间的前提下，对齐有限文本等价。"""
    start_offsets = range(len(expected_units) + 1) if boundary.get("start") else (0,)
    matches = []
    for offset in start_offsets:
        expected_index, observed_index, current = offset, 0, []
        while expected_index < len(expected_units) and observed_index < len(observed_units):
            expected = expected_units[expected_index]
            observed = observed_units[observed_index]
            if expected[0] == observed[0] or (expected[0] in _ARTICLES and observed[0] in _ARTICLES):
                current.append((expected, observed))
                expected_index += 1
                observed_index += 1
            elif observed[0] in _ARTICLES:
                observed_index += 1  # ASR 多出的冠词没有进入来源正文，无需制造时间锚点。
            else:
                break
        while observed_index < len(observed_units) and observed_units[observed_index][0] in _ARTICLES:
            observed_index += 1
        if observed_index != len(observed_units):
            continue
        if expected_index != len(expected_units) and not boundary.get("end"):
            continue
        if not current:
            continue
        if offset and not boundary.get("start"):
            continue
        if expected_index < expected_count and not boundary.get("end"):
            continue
        matches.append(current)
    if len(matches) != 1:
        raise ValueError("UNCERTAIN: ASR 与字幕词序不一致，不自动覆盖字幕")
    return matches[0]


def _asr_comparison_units(words, expected=()):
    """只接受受限的缩写、数字年龄和已出现连字符词的 ASR 拆词。"""
    units, index = [], 0
    hyphenated = {word.lower().replace("–", "-") for word in expected if "-" in word or "–" in word}
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
            compound_end = next((end for end in range(min(len(words), index + 4), index + 1, -1)
                                 if "-".join(word.lower() for word in words[index:end]) in hyphenated), None)
            if compound_end:
                units.append(("-".join(word.lower() for word in words[index:compound_end]), index, compound_end))
                index = compound_end
            else:
                units.append((current, index, index + 1))
                index += 1
    return units
