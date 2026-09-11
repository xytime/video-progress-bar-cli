"""评论区互动建议的格式校验与回执展示；不执行平台操作。

# Modification History
| Version | Date | Author | Description |
|---------|------|--------|-------------|
| 1.1.0 | 2026-09-11 | Codex | 收紧互动帖四段结构校验，并在回执中单独展示视频名称。 |
| 1.0.0 | 2026-09-07 | Codex | 保存互动选择题并安全合并到发布回执。 |

依赖：copywriter / pipeline_manager → 本模块 → 标准库。
"""

import html
import re
from pathlib import Path


ENGAGEMENT_PROMPT = (
    "- engagement_post：仅输出可直接粘贴到评论区的帖子正文，80-500字，纯文本；"
    "不要输出视频标题、标题标签、原视频链接、写作说明或任何机器人套话。"
    "严格按四段输出，段落之间空一行："
    "第一段为背景提炼，仅一段且不超过两句话，点出核心事件和矛盾点；"
    "第二段为一句核心提问，直接抛出议题；"
    "第三段仅包含 A.、B.、C.、D. 四行，每个选项独立成行，采用“核心观点 + 简明因果/前提”结构，"
    "概括不同博弈视角，不预设正确答案，其中一个选项保留证据不足/继续观望的可能；"
    "第四段为一句追问，引导观众站队并追问会确认或改变判断的关键数据、现象或证据。"
    "必须忠实于所给来源，观点标明为观点，不编造数字、原因或事实，"
    "不得套用其他视频案例，不做荐股、收益承诺或诱导点赞。"
    "来源不足以支持具体讨论时返回空字符串。此字段仅供人工选用，不自动发布。\n"
)


_FORBIDDEN_META_TEXT_RE = re.compile(
    r"以下是为您生成的文案|原视频链接|标题\s*[:：]"
)


def _terminal_punctuation_count(text: str) -> int:
    """统计中文/英文句末标点，用于限制背景、提问和追问的句数。"""
    return len(re.findall(r"[。！？!?]", text))


def normalize_engagement_post(value: object) -> str:
    """拒绝缺段、套话或不完整选择题；不截断选项或冒充已完成事实核查。"""
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if not 80 <= len(text) <= 500:
        return ""
    if _FORBIDDEN_META_TEXT_RE.search(text):
        return ""

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if len(paragraphs) != 4:
        return ""
    background, question, options_block, followup = paragraphs
    if "\n" in background or "\n" in question or "\n" in followup:
        return ""
    if not 1 <= _terminal_punctuation_count(background) <= 2:
        return ""
    if _terminal_punctuation_count(question) != 1 or not re.search(r"[？?]$", question):
        return ""
    if _terminal_punctuation_count(followup) != 1:
        return ""

    option_lines = options_block.splitlines()
    options = [re.fullmatch(r"([A-D])[.．、][ \t]*([^\n]+)", line.strip()) for line in option_lines]
    if len(options) != 4 or any(match is None for match in options):
        return ""
    if [match[1] for match in options] != list("ABCD"):
        return ""
    if len({match[2].strip() for match in options}) != 4:
        return ""
    return text


def engagement_receipt_section(path: Path, video_title: str | None = None) -> str:
    """读取独立建议产物，异常不影响已确认的发布回执。"""
    try:
        # 有界读取，历史文件损坏或缺失均按待补充处理。
        with path.open(encoding="utf-8") as source:
            post = normalize_engagement_post(source.read(501))
    except (OSError, UnicodeError):
        post = ""
    title = str(video_title or "").strip()
    title_block = f"\n\n<b>视频名称</b>\n{html.escape(title)}" if title else ""
    heading = "\n\n<b>评论区互动建议（人工选用，未自动发布）</b>\n"
    if not post:
        return title_block + heading + "暂无有效建议（历史产物缺失或生成未通过校验），待补充。"
    return title_block + heading + html.escape(post)
