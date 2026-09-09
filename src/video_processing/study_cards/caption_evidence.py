"""保留 JSON3 原词与事件依据，不用猜测时长制造逐词锚点。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-09 | Codex | 确定性解析、规范化记录和 ASR 差异证据。 |
| 1.0.1 | 2026-09-09 | Codex | 保留片段边界跨越的原字幕，并仅以 ASR 确定边界内词序。 |
"""
import difflib
import math
import re

TOKEN = re.compile(r"[+-]?[$£€]?[A-Za-z0-9]+(?:[’'][A-Za-z0-9]+)*(?:[.,]\d+)*(?:[-–][A-Za-z0-9]+)*%?")


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


def align_json3(parsed, asr_words):
    """多词字幕以真实 ASR 锚点对齐；仅允许裁去已记录的片段边界残词。"""
    expected = tokens(parsed["english_text"])
    observed = []
    for word in asr_words:
        parts = tokens(word.get("word", ""))
        if len(parts) != 1:
            raise ValueError("UNCERTAIN: ASR 词片不能唯一绑定字幕词")
        observed.append(parts[0])
    expected_lower, observed_lower = [w.lower() for w in expected], [w.lower() for w in observed]
    offset = 0
    if expected_lower != observed_lower:
        matches = [i for i in range(len(expected_lower) - len(observed_lower) + 1)
                   if expected_lower[i:i + len(observed_lower)] == observed_lower]
        if len(matches) != 1:
            raise ValueError("UNCERTAIN: ASR 与字幕词序不一致，不自动覆盖字幕")
        offset = matches[0]
        boundary = parsed.get("boundary_clipped", {})
        if (offset and not boundary.get("start")) or (offset + len(observed_lower) < len(expected_lower)
                                                       and not boundary.get("end")):
            raise ValueError("UNCERTAIN: ASR 与字幕词序不一致，不自动覆盖字幕")
    result, previous = [], 0.0
    for text, word in zip(expected[offset:offset + len(observed)], asr_words):
        start, end = round(float(word["start"]), 3), round(float(word["end"]), 3)
        if not math.isfinite(start + end) or start < previous or not start < end <= parsed["source_end"] - parsed["source_start"]:
            raise ValueError("UNCERTAIN: ASR 锚点重叠或越界")
        result.append({"text": text, "start": start, "end": end})
        previous = end
    return result
