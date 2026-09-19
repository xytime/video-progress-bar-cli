"""AGY 互动评论提示词与 JSON Schema 契约。

负责将视频元数据转化为针对 AGY 深度思考模型的隔离提示词，
并提供严格的结构化输出模式约束。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-19 | Antigravity | 初始创建：定义 JSON Schema 与动态选题提示词模板 |
"""

from __future__ import annotations

from typing import Any, Dict


INTERACTION_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "interaction_type": {
            "type": "string",
            "enum": [
                "POLL_STAND",
                "WARNING_SHARE",
                "GROUP_DISCUSSION",
                "MEMO_COLLECTION",
                "VOICE_RESONANCE",
            ],
            "description": "选定的核心互动策略类型",
        },
        "topic": {
            "type": "string",
            "description": "引发思考或争论的1句话核心话题（不超40字）",
        },
        "poll_options": {
            "type": "array",
            "items": {"type": "string"},
            "description": "供用户选择的选项列表（2-3项，简练鲜明）",
        },
        "share_hook": {
            "type": "string",
            "description": "针对该视频主题最适合的转发驱动语（利他避坑/转到群聊/备忘收藏/共鸣嘴替）",
        },
        "formatted_comment": {
            "type": "string",
            "description": "最终生成好的带 Emoji、分段换行的完整评论文本（100-250字）",
        },
    },
    "required": [
        "interaction_type",
        "topic",
        "poll_options",
        "share_hook",
        "formatted_comment",
    ],
    "additionalProperties": False,
}


def build_interaction_prompt(
    *,
    title: str,
    description: str,
    category: str = "General",
    retrying: bool = False,
) -> str:
    """构建用于 AGY 深度思考模型的互动生成提示词。"""
    retry_prompt = "\n【注意：上一次输出未通过结构化校验，请严格按规范生成，确保 formatted_comment 包含完整的 Emoji 标识与段落！】\n" if retrying else ""

    return f"""你是微信视频号的高级运营专家，深谙短视频评论区“促活跃、带节奏、引点赞、促转发”的心理机制。
请根据以下视频信息，为作者（带有官方【作者】标签）策划一条置顶的高质量首评互动内容。
{retry_prompt}
【视频信息】
- 标题: {title}
- 类别: {category}
- 摘要与看点: {description}

【核心策略指引】
1. 动态挑选最佳策略 (interaction_type):
   - 若视频涉及鲜明观点碰撞或前沿分歧 -> 优先 POLL_STAND (站队投票) 或 GROUP_DISCUSSION (转到群里看大家怎么选)
   - 若视频包含投资/健康/工具避坑/踩雷警告 -> 优先 WARNING_SHARE (转发给身边人提个醒)
   - 若视频知识点密集/深度干货/步骤拆解 -> 优先 MEMO_COLLECTION (转给文件传输助手备忘慢慢复盘)
   - 若视频说出行业或职场深层痛点 -> 优先 VOICE_RESONANCE (共鸣嘴替)
2. 文本编排规范 (formatted_comment):
   - 必须使用多行换行 \\n 区分模块；
   - 充分利用 Emoji 色块作为视觉锚点（如 📌 话题、🗳️ 投票、🅰️ 🅱️ 选项、💬 引导、📢 转发提示、⚠️ 警示、👍 互动）；
   - 即使多行在某些机型被拉平，Emoji 与 【】 也能让语义模块一眼看清；
   - 总字数严格控制在 90 到 240 字之间；
   - 选项简短有力，降低用户发言门槛（“扣A或扣B”）；
   - 严禁出现虚假宣传、绝对化违禁词或政治敏感讨论。

请只按 JSON Schema 契约输出纯净的 JSON 结果。
"""
