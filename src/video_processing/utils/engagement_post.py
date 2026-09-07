"""评论区互动建议的格式校验与回执展示；不执行平台操作。

# Modification History
| Version | Date | Author | Description |
|---------|------|--------|-------------|
| 1.0.0 | 2026-09-07 | Codex | 保存互动选择题并安全合并到发布回执。 |

依赖：copywriter / pipeline_manager → 本模块 → 标准库。
"""

import html
import re
from pathlib import Path


ENGAGEMENT_PROMPT = (
    "- engagement_post：评论区互动帖建议，150-500字，纯文本无markdown；"
    "从来源核心内容或受众更关心的具体矛盾中选择一个讨论点。"
    "先用一至两段说明背景与为什么值得讨论，再提出一个判断题；"
    "A.、B.、C.、D. 各占一行，观点有区分度、不预设正确答案，"
    "其中一个选项保留证据不足/尚待观察的可能；"
    "最后追问什么数据、现象或证据会确认或改变读者的判断。"
    "必须忠实于所给来源，观点标明为观点，不编造数字、原因或事实，"
    "不得套用其他视频案例，不做荐股、收益承诺或诱导点赞。"
    "来源不足以支持具体讨论时返回空字符串。此字段仅供人工选用，不自动发布。\n"
)


def normalize_engagement_post(value: object) -> str:
    """拒绝不完整选择题；不截断选项或冒充已完成事实核查。"""
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if not 80 <= len(text) <= 500:
        return ""
    options = list(re.finditer(r"(?m)^([A-D])[.．、][ \t]*([^\n]+)$", text))
    if [match[1] for match in options] != list("ABCD"):
        return ""
    if len({match[2].strip() for match in options}) != 4:
        return ""
    intro = text[:options[0].start()].strip()
    followup = text[options[-1].end():].strip()
    if not intro or not re.search(r"[？?]", followup):
        return ""
    return text


def engagement_receipt_section(path: Path) -> str:
    """读取独立建议产物，异常不影响已确认的发布回执。"""
    try:
        # 有界读取，历史文件损坏或缺失均按待补充处理。
        with path.open(encoding="utf-8") as source:
            post = normalize_engagement_post(source.read(501))
    except (OSError, UnicodeError):
        post = ""
    heading = "\n\n💬 <b>评论区互动帖建议（人工选用，未自动发布）</b>\n"
    if not post:
        return heading + "暂无有效建议（历史产物缺失或生成未通过校验），待补充。"
    return heading + html.escape(post)
