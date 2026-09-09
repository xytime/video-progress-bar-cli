"""字幕文本与既有 ASS 的硬性合同；不调用模型、不依赖编排层。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-09-09 | Codex | 只检查中文字幕层，并以完整层文本识别被 ASS 换行拆开的错误页 |
| 1.0.0 | 2026-09-09 | Codex | 拦截翻译占位符，并对实际输入旁的双语 ASS 做缓存与提交前校验 |
"""

from pathlib import Path
import re

import pysubs2

from .generated_content_validation import is_upstream_error_response


def is_translation_placeholder(text: str) -> bool:
    """仅匹配整段占位语，不拦截正常句子对“承接上文”的讨论。"""
    plain = re.sub(r"\{[^}]*\}", "", text).replace(r"\N", " ").replace(r"\n", " ")
    plain = re.sub(r"\s+", "", plain).strip("（）()【】[]，,。.!！:：;；")
    return plain in {"承接上文", "接上文", "同上", "译文同上", "翻译同上", "续上文"}


def _chinese_layer_text(event_text: str) -> str | None:
    """提取事件中供烧录的中文字幕层，保留 ASS 强制换行供调用方归一化。"""
    match = re.search(
        r"\{\\fnHiragino Sans GB[^}]*\}(.*)$", event_text, re.DOTALL,
    )
    return match.group(1) if match else None


def bilingual_ass_contract_error(path: Path) -> str | None:
    """检查实际烧录字幕；缺失/不可读不再被当成已验证缓存。

    这是结构底线，不证明语义、时间对齐或成片与 ASS 的哈希绑定。
    """
    try:
        content = path.read_text(encoding="utf-8")
        subtitles = pysubs2.SSAFile.from_string(content, format_="ass")
    except (OSError, UnicodeError, ValueError) as exc:
        return f"字幕检查点不可读：{path.name} ({type(exc).__name__})"
    events = [event for event in subtitles if not event.is_comment]
    if not events or "fnGeorgia" not in content:
        return f"字幕检查点缺少有效双语事件：{path.name}"
    for event in events:
        chinese_layer = _chinese_layer_text(event.text)
        if chinese_layer is None:
            continue
        if is_translation_placeholder(chinese_layer):
            return f"字幕含翻译占位符：{path.name} @{event.start / 1000:.2f}s"
        # 错误页的固定短语可能被 \N 拆到多行；必须在完整中文字幕层上判定。
        normalized_chinese = re.sub(r"\{[^}]*\}", "", chinese_layer)
        normalized_chinese = normalized_chinese.replace(r"\N", " ").replace(r"\n", " ")
        if is_upstream_error_response(normalized_chinese):
            return f"字幕含上游错误响应：{path.name} @{event.start / 1000:.2f}s"
    return None
