"""重大新闻 3-5 分钟高品质二创生产 Prompt 规范库与标杆示例 (RFC-2026-DEEP-CREATION-001 Rev 2.0)。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-08 | Antigravity | 固化 V2 生产 Prompt、Draft-07 Schema 与 100% 真实字幕引证标杆示例 |
"""
from typing import Any, Dict

# 1. Draft-07 JSON Schema 规范 (用于 LLM 结构化输出或网关初筛)
INSIGHT_SCRIPT_V2_JSON_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "InsightScriptV2",
    "description": "重大新闻3-5分钟高信息增量二创脚本规范数据契约 (v2.0.0)",
    "type": "object",
    "required": ["schema_version", "video_id", "headline", "preserve_full_body", "hook", "cards", "outro"],
    "additionalProperties": False,
    "properties": {
        "schema_version": {"type": "string", "enum": ["2.0.0"]},
        "video_id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{11}$"},
        "headline": {"type": "string", "minLength": 4, "maxLength": 24},
        "preserve_full_body": {"type": "boolean", "enum": [True]},
        "hook": {
            "type": "object",
            "required": ["title", "narration", "estimated_sec"],
            "additionalProperties": False,
            "properties": {
                "title": {"type": "string", "minLength": 4, "maxLength": 24},
                "narration": {"type": "string", "minLength": 30, "maxLength": 120},
                "estimated_sec": {"type": "number", "minimum": 12.0, "maximum": 30.0},
            },
        },
        "cards": {
            "type": "array",
            "minItems": 2,
            "maxItems": 2,
            "items": {
                "type": "object",
                "required": ["card_id", "badge", "title", "start_sec", "end_sec", "points"],
                "additionalProperties": False,
                "properties": {
                    "card_id": {"type": "string", "enum": ["card_1", "card_2"]},
                    "badge": {
                        "type": "string",
                        "enum": ["制度透视", "利益博弈", "前沿透视", "底层洞察", "战略剖析", "危机解码"],
                    },
                    "title": {"type": "string", "minLength": 4, "maxLength": 28},
                    "start_sec": {"type": "number", "minimum": 0},
                    "end_sec": {"type": "number", "minimum": 0},
                    "points": {
                        "type": "array",
                        "minItems": 3,
                        "maxItems": 3,
                        "items": {
                            "type": "object",
                            "required": ["point_type", "keyword", "explanation", "vtt_reference"],
                            "additionalProperties": False,
                            "properties": {
                                "point_type": {"type": "string", "enum": ["FACT", "INSIGHT", "BACKGROUND"]},
                                "keyword": {"type": "string", "minLength": 2, "maxLength": 8},
                                "explanation": {"type": "string", "minLength": 10, "maxLength": 36},
                                "vtt_reference": {
                                    "type": "object",
                                    "required": ["start_sec", "end_sec", "source_quote"],
                                    "additionalProperties": False,
                                    "properties": {
                                        "start_sec": {"type": "number", "minimum": 0},
                                        "end_sec": {"type": "number", "minimum": 0},
                                        "source_quote": {"type": "string", "minLength": 3, "maxLength": 150},
                                    },
                                },
                            },
                        },
                    },
                },
            },
        },
        "outro": {
            "type": "object",
            "required": ["philosophical_quote", "reflection_question", "poll_options"],
            "additionalProperties": False,
            "properties": {
                "philosophical_quote": {"type": "string", "minLength": 10, "maxLength": 36},
                "reflection_question": {"type": "string", "minLength": 10, "maxLength": 32},
                "poll_options": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 3,
                    "items": {"type": "string", "minLength": 2, "maxLength": 16},
                },
            },
        },
    },
}

# 2. System Prompt (认知底座指令)
INSIGHT_SCRIPT_V2_SYSTEM_PROMPT = """你是由“六维时空号”设立的高阶时政与商业深度观察智囊。
你的使命是：针对时长为 3~5 分钟的全球重大新闻（宏观政经、前沿科技、法治博弈、企业危机），提炼出高智识密度、直击制度与科学本质的二创认知脚本（InsightScriptV2）。

【强制遵循的核心规范文档（单源真理，执行前必须严格阅读对齐）】
1. 受众契约与内容红线：
   - 相对路径：docs/audience_persona.md
   - 核心红线：40岁以上占 75.8%、男性占 70%、北上广深占 34.4%、高净值与政商决策者；严禁网络热梗、轻浮语气与营销号煽情。
2. 二创增量体系与风控原理：
   - 相对路径：docs/content_strategy/2026-10-06_wechat_video_information_increment_system.md
3. 品牌标准化资产规范：
   - 账号名称：六维时空号
   - 品牌主 Slogan：不同的视角，看见更大的世界。
   - 图腾微标：assets/brand/01_logos/concept_a.png
   - 受控真实二维码：assets/brand/05_qrcodes/liuwei-shikonghao-wechat-channels-code-source.jpeg (中央自带官方地球仪头像)
4. 工程规范与数据契约：
   - 相对路径：docs/content_strategy/2026-10-07_agy_deep_insight_creation_proposal.md

【产出规则与工程约束】
1. 原片 100% 完整：preserve_full_body 必须为 true，绝对禁止裁剪正文；
2. 导读 Hook (15~24s)：开门见山，第一句话必须打破平庸，点出事件背后的核心矛盾焦点；
3. 认知透视卡 (2张，各20~30秒)：
   - 精准阅读全篇字幕，定位正文最适合展开背景深挖的两个时间戳区间；
   - 每张卡必须包含 3 条论据，严格标注 point_type 为 FACT、INSIGHT 或 BACKGROUND；
   - 每条论据必须包含 vtt_reference，注明原文字幕的真实时间范围与原声台词引用，以供下游机器验证；
   - 论述文字精炼，explanation 字符数控制在 15~32 字之间。
4. 尾部思辨 (15~20s)：提炼出一句具备长效穿透力的哲学金句，以及引发理性决策者思考的互动投票议题。
5. 必须输出严格符合 InsightScriptV2 JSON Schema 的纯 JSON 数据，不得带有任何 markdown 解释或多余字符。
"""

# 3. Task Prompt 模版
INSIGHT_SCRIPT_V2_TASK_PROMPT = """请针对以下 3~5 分钟重大新闻视频，生成符合《六维时空号高信息增量二创规范》的 InsightScriptV2 结构化脚本：

【本任务输入资产与上下文路径】
- 目标视频 ID：{{YOUTUBE_ID}}
- 原始英文字幕路径：{{SUBTITLE_VTT_PATH}} (优先检查 output/{{YOUTUBE_ID}}_source_subtitle.en.vtt)
- 视频元数据文件路径：{{INFO_JSON_PATH}} (例如: output/{{YOUTUBE_ID}}.info.json)
- 视频总时长：{{DURATION_SECONDS}} 秒 (严格位于 180s ~ 330s 黄金甜点区)

【规范依赖索引（请参考以下文档确保受众与风格严格合规）】
- 受众画像与禁忌：docs/audience_persona.md
- 二创风控与架构：docs/content_strategy/2026-10-06_wechat_video_information_increment_system.md
- 本评审方案总纲：docs/content_strategy/2026-10-07_agy_deep_insight_creation_proposal.md

【输出要求】
请通读上述字幕与信息，直接输出严格符合 InsightScriptV2 JSON Schema 的纯 JSON。
"""

# 4. 标杆 Few-Shot 案例 1 (纽约州长特检案 · 康奈尔大学，100% 物理真实字幕引证)
FEW_SHOT_EXAMPLE_CORNELL: Dict[str, Any] = {
    "schema_version": "2.0.0",
    "video_id": "SfNypZIb0H4",
    "headline": "纽约州长指派特检重查康奈尔性侵案",
    "preserve_full_body": True,
    "hook": {
        "title": "名校兄弟会黑幕被掩盖",
        "narration": "常春藤名校兄弟会深陷性侵丑闻，地方校警与检方却在调查中涉嫌刻意包庇。当权力与声誉试图遮掩真相，纽约州最高行政长官罕见宣布越级夺权，动用州总检察长重启刑事风暴！",
        "estimated_sec": 18.3,
    },
    "cards": [
        {
            "card_id": "card_1",
            "badge": "制度透视",
            "title": "为什么纽约州长能越级夺权？",
            "start_sec": 22.0,
            "end_sec": 44.0,
            "points": [
                {
                    "point_type": "FACT",
                    "keyword": "宪政纠偏",
                    "explanation": "州长签署紧急行政令指派总检察长作为特检接管案件",
                    "vtt_reference": {
                        "start_sec": 0.9,
                        "end_sec": 7.0,
                        "source_quote": "signed an executive order appointing Attorney General Letitia James as special prosecutor",
                    },
                },
                {
                    "point_type": "BACKGROUND",
                    "keyword": "外部独立",
                    "explanation": "州政府敦促校方启动由外部独立律师主导的全面审查",
                    "vtt_reference": {
                        "start_sec": 16.0,
                        "end_sec": 21.0,
                        "source_quote": "called on Cornell to conduct an independent investigation led by outside lawyers",
                    },
                },
                {
                    "point_type": "INSIGHT",
                    "keyword": "行政施压",
                    "explanation": "州长直接对话大学校长达成整改共识突破地方层层阻力",
                    "vtt_reference": {
                        "start_sec": 22.0,
                        "end_sec": 28.0,
                        "source_quote": "personally spoke with the university president, who agreed to take these steps",
                    },
                },
            ],
        },
        {
            "card_id": "card_2",
            "badge": "利益博弈",
            "title": "常春藤兄弟会背后的权力盲区",
            "start_sec": 70.0,
            "end_sec": 95.0,
            "points": [
                {
                    "point_type": "FACT",
                    "keyword": "掩盖报告",
                    "explanation": "校警向检方提交的初查报告中关键受害陈述竟被完全隐匿",
                    "vtt_reference": {
                        "start_sec": 48.0,
                        "end_sec": 60.0,
                        "source_quote": "shocking that these words never made it into the report that Cornell police gave to prosecutors",
                    },
                },
                {
                    "point_type": "BACKGROUND",
                    "keyword": "案发指控",
                    "explanation": "受害人详尽指控在兄弟会酒局遭到五名醉酒男性的严重侵害",
                    "vtt_reference": {
                        "start_sec": 74.0,
                        "end_sec": 84.0,
                        "source_quote": "victim that she was literally raped by five drunk men at a fraternity",
                    },
                },
                {
                    "point_type": "INSIGHT",
                    "keyword": "司法失职",
                    "explanation": "地方检察官未对涉案人员全面质询便仓促撤案引发公信力危机",
                    "vtt_reference": {
                        "start_sec": 84.0,
                        "end_sec": 94.0,
                        "source_quote": "district attorney not even question her or the others involved, or even demand a full transcript",
                    },
                },
            ],
        },
    ],
    "outro": {
        "philosophical_quote": "当机构的自保本能压过个体正义，法治的阳光该照向何方？",
        "reflection_question": "常春藤名校与地方司法的利益闭环，是否需联邦立法强制监管？",
        "poll_options": ["必须立法穿透", "坚持高校自治", "视案件性质而定"],
    },
}

# 5. 标杆 Few-Shot 案例 2 (2026诺奖光遗传学，100% 物理真实字幕引证)
FEW_SHOT_EXAMPLE_NOBEL: Dict[str, Any] = {
    "schema_version": "2.0.0",
    "video_id": "RaUWCtcJtK8",
    "headline": "光遗传学研究获诺贝尔医学奖",
    "preserve_full_body": True,
    "hook": {
        "title": "2026诺贝尔医学奖揭晓",
        "narration": "2026年诺贝尔医学奖重磅揭晓！斯坦福科学家戴塞尔罗斯因开创光遗传学摘得桂冠。人类首次实现了用一束激光毫秒级精准开启或关闭活体大脑神经元，彻底改写脑科学底层范式！",
        "estimated_sec": 23.6,
    },
    "cards": [
        {
            "card_id": "card_1",
            "badge": "前沿透视",
            "title": "什么是光遗传学 (Optogenetics)？",
            "start_sec": 24.0,
            "end_sec": 54.0,
            "points": [
                {
                    "point_type": "FACT",
                    "keyword": "诺奖揭晓",
                    "explanation": "瑞典诺贝尔大会正式宣布将医学奖授予光遗传学领域开创者",
                    "vtt_reference": {
                        "start_sec": 11.0,
                        "end_sec": 20.0,
                        "source_quote": "selected by the Swedish Nobel Assembly for their work in the field of optogenetics",
                    },
                },
                {
                    "point_type": "BACKGROUND",
                    "keyword": "机理突破",
                    "explanation": "该项技术首次在活体大脑中揭示神经回路如何塑造记忆与行为",
                    "vtt_reference": {
                        "start_sec": 20.0,
                        "end_sec": 27.0,
                        "source_quote": "show how nerve cells shape memories, feelings, and behaviors in the living brain",
                    },
                },
                {
                    "point_type": "INSIGHT",
                    "keyword": "获奖感言",
                    "explanation": "开创者戴塞尔罗斯接受专访表示这是对跨学科坚持的最高肯定",
                    "vtt_reference": {
                        "start_sec": 26.0,
                        "end_sec": 32.0,
                        "source_quote": "Karl Deisseroth told BBC News that it was an incredible honor to win",
                    },
                },
            ],
        },
        {
            "card_id": "card_2",
            "badge": "底层洞察",
            "title": "为什么学术圈曾断定绝无可能？",
            "start_sec": 95.0,
            "end_sec": 125.0,
            "points": [
                {
                    "point_type": "FACT",
                    "keyword": "早期天赋",
                    "explanation": "导师回忆其在精神科住院医期间便展现出罕见的创造力与远见",
                    "vtt_reference": {
                        "start_sec": 90.0,
                        "end_sec": 105.0,
                        "source_quote": "psychiatry resident who we were giving extra time to do research, and it was pretty obvious he was smart, he was creative, and he was visionary",
                    },
                },
                {
                    "point_type": "BACKGROUND",
                    "keyword": "学术孤注",
                    "explanation": "为了将光遗传学推向实用阶段科学家当时甚至押上了学术生涯",
                    "vtt_reference": {
                        "start_sec": 142.0,
                        "end_sec": 151.0,
                        "source_quote": "Because to make optogenetics what it became, Karl was basically risking his academic career",
                    },
                },
                {
                    "point_type": "INSIGHT",
                    "keyword": "卓越特质",
                    "explanation": "深邃的学术洞察力与极度坚韧的科研毅力共同铸就了颠覆式突破",
                    "vtt_reference": {
                        "start_sec": 127.0,
                        "end_sec": 142.0,
                        "source_quote": "incredible intelligence, sophistication, vision, but an incredible drive and work ethic and perseverance",
                    },
                },
            ],
        },
    ],
    "outro": {
        "philosophical_quote": "真正的科学革命，永远诞生于对抗常识的勇气之中。",
        "reflection_question": "当人类能够精准操控脑回路，我们该如何界定自由意志与自我？",
        "poll_options": ["技术至上拥抱攻克", "伦理红线严格受限", "深感担忧保持警惕"],
    },
}
