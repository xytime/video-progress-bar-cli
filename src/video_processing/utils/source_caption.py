"""明确关闭翻译时生成原文 ASS 事件；翻译失败不得静默回退。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-08 | Codex | 修复标准字幕在无翻译/同语种模式下输出空 ASS，保持翻译路径边界 |
"""

import textwrap

import pysubs2


def build_source_caption_event(segment, source_lang, target_lang, font_size, margin, wrap_width):
    """纯函数：仅无翻译请求时返回源文本事件，不变更输入或访问 IO。"""
    if target_lang and target_lang != source_lang:
        return None
    text = segment.get("text", "").strip()
    if not text:
        return None
    wrapped = textwrap.fill(text, width=wrap_width).replace("\n", "\\N")
    return pysubs2.SSAEvent(
        start=int(segment["start"] * 1000), end=int(segment["end"] * 1000),
        text=f"{{\\fs{font_size}}}{wrapped}", marginv=margin,
    )
