"""固定首个自然句窗口；窗口外词保留为审计上下文，不制造时间锚点。"""
import math

from .caption_evidence import repair_asr_word_timestamps

WINDOW_POLICY = "first-terminal-after-30s-v1"


def select_window(words, duration):
    """先固定首个自然句末，再检查该前缀；失败不尝试后续句末。"""
    ceiling = min(120.0, duration)
    for index, word in enumerate(words):
        try:
            end = float(word["end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("UNCERTAIN: 自然句窗口缺少词尾证据") from exc
        if not math.isfinite(end):
            raise ValueError("UNCERTAIN: 自然句窗口包含非有限时间")
        text = str(word.get("word") or word.get("text") or "").strip()
        if 30 < end <= ceiling and text.endswith((".", "!", "?")):
            return index + 1, round(end, 3)
    raise ValueError("UNCERTAIN: 本地 Whisper 未给出 30--120 秒自然句末窗口")


def validate_window(words, duration):
    count, end = select_window(words, duration)
    # 所有后文都必须落在窗口外；不按 end 过滤，以免静默丢失坏词或跨界词。
    for word in words[count:]:
        try:
            start = float(word["start"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("UNCERTAIN: 无法证明后文位于窗口外") from exc
        if not math.isfinite(start) or start < end - .001:
            raise ValueError("UNCERTAIN: 后文跨越自然句窗口边界")
    repaired, repairs = repair_asr_word_timestamps(words[:count], end)
    return repaired, repairs, {"policy": WINDOW_POLICY, "source_start": 0.0,
                               "source_end": end, "word_count": count,
                               "context_word_count": len(words) - count}
