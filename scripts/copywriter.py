"""微信视频号文案生成器 - 生成短标题、文案正文、分类

# Modification History
| Version | Date       | Author                                  | Description                                      |
|---------|------------|-----------------------------------------|--------------------------------------------------|
| 1.0.0   | 2026-05-21 | Gemini_3.5_Flash_planning               | Initial creation with Gemini API + translator fallback |
| 1.1.0   | 2026-05-21 | Claude_Sonnet_4.6_Thinking_planning     | 移除 os.getenv/load_dotenv，通过 settings 注入   |
| 1.2.0   | 2026-05-22 | Claude_Sonnet_4.6_Thinking_planning     | 结构化输出：短标题/文案/分类三文件；加原创/分类 LLM 推断 |
| 1.3.0   | 2026-05-24 | Claude_Sonnet_4.6_Thinking_planning     | 错误修复: parse_known_args 导致其他参数丢失；改为预处理 sys.argv + parse_args |
| 1.4.0   | 2026-05-24 | Claude_Sonnet_4.6_Thinking_planning     | P0终极修复: 注册全部4个参数，sys.argv预处理'-'前缀ID，彻底解决AttributeError |
| 1.5.0   | 2026-05-26 | Claude_Sonnet_4.6_Thinking_fast         | 标题质量改造: 短标题字数修歗6-16（匹配微信平台真实限制）; 新增 hook_subtitle 和 content_hints 输出 |
| 1.6.0   | 2026-05-26 | Gemini_3.5_Flash_planning               | 标题调性补强：增加专业术语词典映射与负向营销词黑名单，提升文案格调并引入兜底纠偏 |
| 1.7.0   | 2026-05-26 | Gemini_2.5_Pro_planning                 | P0审计修复: ①零分max()按字典顺序随机→显式fallback; ②英文子串污染(cat/war)→词边界正则; ③音乐类覆盖率不足→大幅扩充娱乐关键词库 |
| 1.8.0   | 2026-05-27 | Claude_Sonnet_4.6_Thinking_planning     | AI重构: 用 google-genai + Pydantic response_schema 替换手工JSON解析，彻底解决分类不准问题 |
| 1.9.0   | 2026-05-27 | Claude_Sonnet_4.6_Thinking_planning     | 优雅截断: 引入 graceful_truncate_title，替换全部硬截断，消除半句标题问题 |
| 1.9.1   | 2026-05-27 | Gemini_3.5_Flash_planning               | 算法调优: graceful_truncate_title 预处理过滤括号，并将排序策略由尾部优先改为首部语义优先，防截断偏斜 |
| 1.10.0  | 2026-05-27 | Gemini_3.1_Pro_High_planning            | P0体验修复: 引入斐波那契重试；新增正则提取主干降级方案；graceful_truncate_title 增加悬空词惩罚评分 |
| 1.11.0  | 2026-06-02 | Gemini_2.5_Pro_planning                 | 封面内容角标: 新增 content_label 字段，LLM 自动按内容选择 重磅/突发/独家/最新 等运营标签，写入 {yid}_label.txt |
"""

import re
import sys
import os
import json
import argparse
import logging
import time
from pathlib import Path
from typing import Optional

import pydantic

_src_root = os.path.join(os.path.dirname(__file__), '..', 'src')
if _src_root not in sys.path:
    sys.path.insert(0, _src_root)

from config.settings import settings  # [Claude_Sonnet_4.6_Thinking_planning]

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("copywriter")

# 微信视频号支持的分类（与平台实际菜单保持一致）
WECHAT_CATEGORIES = [
    "科技", "财经", "教育", "生活", "娱乐",
    "游戏", "体育", "时事", "资讯", "健康",
]
DEFAULT_CATEGORY = "科技"

# 每个分类对应的默认标签与引导关注文案
CATEGORY_CONFIG = {
    "科技": {
        "tags": "#科技 #AI #前沿探索",
        "cta": "关注本视频号，解锁更多前沿科技！"
    },
    "财经": {
        "tags": "#财经 #投资 #商业逻辑",
        "cta": "关注本视频号，洞察财富与商业本质！"
    },
    "教育": {
        "tags": "#教育 #知识分享 #成长大讲堂",
        "cta": "关注本视频号，每日获取优质知识！"
    },
    "生活": {
        "tags": "#生活 #日常 #美好生活",
        "cta": "关注本视频号，探索美好生活灵感！"
    },
    "娱乐": {
        "tags": "#音乐 #娱乐 #艺术熏陶",
        "cta": "关注本视频号，享受视听娱乐盛宴！"
    },
    "游戏": {
        "tags": "#游戏 #电竞 #游戏实况",
        "cta": "关注本视频号，解锁更多精彩游戏瞬间！"
    },
    "体育": {
        "tags": "#体育 #健身 #热血运动",
        "cta": "关注本视频号，感受体育竞技魅力！"
    },
    "时事": {
        "tags": "#资讯 #时事热点 #全球视野",
        "cta": "关注本视频号，第一时间掌握时事动态！"
    },
    "资讯": {
        "tags": "#资讯 #全球热点 #每日精选",
        "cta": "关注本视频号，快速掌握全球新鲜事！"
    },
    "健康": {
        "tags": "#健康 #科普 #医疗健康",
        "cta": "关注本视频号，为您 and 家人的健康保驾护航！"
    }
}


# [Gemini_2.5_Pro_planning] v1.7.0 分类关键字库
# 设计原则：
#   EN_KEYWORDS: 仅含英文词，使用 \b 词边界正则匹配，防止子串污染
#               （如 "cat" 误命中 "education"，"war" 误命中 "software"）
#   ZH_KEYWORDS: 仅含中文词，使用 str.count 匹配（中文无空格边界）
_EN_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "财经": [
        "finance", "market", "stock", "invest", "economy", "crypto", "bitcoin",
        "capital", "dollar", "revenue", "profit", "ipo", "fed", "rate", "business",
        "hedge", "fund", "bonds", "equity", "fiscal",
    ],
    "教育": [
        "course", "tutorial", "learn", "lecture", "lesson", "study",
        "education", "university", "college", "school", "curriculum", "teach",
        "instruction", "masterclass", "workshop", "explained",
    ],
    "生活": [
        "travel", "food", "cooking", "vlog", "home", "diy", "fashion",
        "pet", "dog", "cat", "animal", "recipe", "lifestyle",
        "interior", "garden", "decor",
    ],
    "娱乐": [
        "song", "music", "mv", "lyrics", "singer", "cover", "concert", "dance",
        "movie", "film", "actor", "comedy", "drama", "pop", "guitar", "piano",
        "vocal", "album", "track", "band", "official", "audio", "live",
        "ft", "feat", "remix", "acoustic", "jazz", "rap", "hip hop", "r&b",
        "classical", "orchestra", "violin", "cello", "saxophone", "bass",
        "rock", "metal", "indie", "folk", "blues", "edm", "electronic",
        "performance", "recital", "tour", "hits", "single", "ep", "debut",
        "produced", "directed by",
    ],
    "游戏": [
        "game", "gameplay", "playthrough", "walkthrough", "gaming", "xbox",
        "playstation", "nintendo", "steam", "gamer", "console", "rpg",
        "fps", "lol", "dota", "minecraft", "esports", "speedrun",
    ],
    "体育": [
        "sports", "football", "basketball", "soccer", "nba", "fitness",
        "olympic", "athlete", "swim", "workout", "gym", "marathon",
        "championship", "tournament", "league",
    ],
    "时事": [
        "geopolitics", "war", "election", "president", "summit", "geopolitical",
        "sanction", "military", "conflict", "treaty", "nuclear",
    ],
    "资讯": [
        "news", "report", "breaking", "press", "interview", "headlines",
        "briefing", "roundup",
    ],
    "健康": [
        "health", "medical", "doctor", "disease", "vaccine", "medicine",
        "hospital", "therapy", "wellness", "nutrition", "mental", "fitness",
        "diet", "workout",
    ],
    "科技": [
        "tech", "ai", "robot", "algorithm", "chip", "software", "hardware",
        "quantum", "space", "science", "physics", "developer", "coding",
        "programming", "nvidia", "openai", "google", "apple", "tesla",
        "musk", "meta", "microsoft", "startup", "data", "cloud", "cyber",
        "launch", "innovation",
    ],
}

_ZH_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "财经": ["财经", "股票", "投资", "理财", "经济", "资本", "美联储", "降息", "加息", "创业", "商业", "财报", "基金", "债券"],
    "教育": ["教程", "讲座", "学习", "科普", "教育", "大学", "学校", "名校", "公开课", "培训", "课程"],
    "生活": ["生活", "旅行", "美食", "做饭", "日常", "家居", "文化", "艺术", "设计", "时尚", "宠物", "猫", "狗", "动物", "烹饪", "食谱"],
    "娱乐": ["演唱", "歌曲", "音乐", "歌词", "翻唱", "舞蹈", "电影", "电视剧", "综艺", "明星", "搞笑", "喜剧", "吉他", "钢琴", "声乐", "乐团", "乐器", "专辑", "演出", "巡演"],
    "游戏": ["游戏", "实况", "攻略", "手游", "端游", "电竞", "玩家", "主机", "联机"],
    "体育": ["体育", "比赛", "足球", "篮球", "健身", "运动", "奥运", "运动员", "跑步", "游泳", "训练"],
    "时事": ["地缘", "战争", "选举", "总统", "峰会", "制裁", "军事"],
    "资讯": ["新闻", "报道", "日报", "快讯", "播报", "访谈", "专访", "资讯"],
    "健康": ["健康", "医疗", "医生", "疾病", "疫苗", "饮食", "养生", "医院", "治疗", "营养", "心理"],
    "科技": ["科技", "芯片", "智能", "机器人", "前沿", "太空", "物理", "算法", "程序", "开发", "英伟达", "特斯拉", "马斯克"],
}


def classify_category(title: str, description: str) -> str:
    """[Gemini_2.5_Pro_planning] v1.7.0 基于双语关键字的视频分类器。

    修复历史:
    - v1.6: 初版关键字分类（存在3个P0漏洞）
    - v1.7: 修复①零分时 max() 按字典顺序随机取值→显式 fallback DEFAULT_CATEGORY
             修复②英文子串污染（cat/education, war/software）→ \\b 词边界正则
             修复③娱乐类音乐视频覆盖率不足（7用例仅命中1个）→大幅扩充娱乐关键词库
    """
    text = f"{title} {description}".lower()

    scores: dict[str, int] = {cat: 0 for cat in _EN_CATEGORY_KEYWORDS}

    # 英文：词边界正则防止子串污染（"cat" 不再误命中 "education"）
    for cat, kw_list in _EN_CATEGORY_KEYWORDS.items():
        for kw in kw_list:
            scores[cat] += len(re.findall(r'\b' + re.escape(kw) + r'\b', text))

    # 中文：直接 count（中文无空格边界，需逐字匹配）
    for cat, kw_list in _ZH_CATEGORY_KEYWORDS.items():
        for kw in kw_list:
            scores[cat] += text.count(kw)

    max_score = max(scores.values())
    if max_score == 0:
        # 零分时无可靠证据，显式 fallback 到默认分类，避免 max() 字典顺序随机取值
        logger.debug("classify_category: no keyword matched, falling back to DEFAULT_CATEGORY")
        return DEFAULT_CATEGORY

    return max(scores, key=scores.get)


# ── 结构化输出 Schema ────────────────────────────────────────────────────────

class WeChatContentSchema(pydantic.BaseModel):  # [Claude_Sonnet_4.6_Thinking_planning] v1.8.0
    """微信视频号内容的强类型 Pydantic Schema。
    配合 google-genai response_schema 参数，强制 LLM 直接输出合规 JSON，
    无需手工 json.loads，消除解析失败风险。
    """
    short_title: str = pydantic.Field(
        description="纯中文流量型封面标题，6-16字，禁止使用爆款/干货/秘籍/逆天/震惊等廉价营销词"
    )
    hook_subtitle: str = pydantic.Field(
        description="封面副标题Hook，不超过24字，纯中文，制造悬念或承诺具体利益"
    )
    wechat_copy: str = pydantic.Field(
        description="视频号文案正文，约100-200字，含3-5个hashtag和一句引导关注CTA，纯文本无markdown"
    )
    category: str = pydantic.Field(
        description="视频分类，必须从10个选项中选1个：科技、财经、教育、生活、娱乐、游戏、体育、时事、资讯、健康"
    )
    content_hints: list[str] = pydantic.Field(
        description=(
            "2-5个英文语义token，从以下备选词选取: "
            "policy market capital stock robot ai llm coding software algorithm chip hardware "
            "crypto mindset health medical nutrition geopolitics war election military "
            "space physics astronomy science news media report "
            "music song concert film movie drama comedy entertainment gaming esports "
            "sports fitness travel food lifestyle education course tutorial startup innovation"
        )
    )
    # [Gemini_2.5_Pro_planning] v1.11.0 内容角标标签
    content_label: str = pydantic.Field(
        description=(
            "封面角标运营标签，从以下选扨1个（若内容普通则返回空字符串）: "
            "重磅、突发、独家、最新、深度、解析、揭秘、完整版、专访、警示、局势、首发"
            "——符合以下任一条才贴标签："
            "1.重磅/突发→重大政策/紧急事件/大厂崩塑; "
            "2.独家/首发→第一手信息/专访内容; "
            "3.最新→新产品发布/新发现/今日更新; "
            "4.深度/解析→长篇分析/机制拆解; "
            "5.揭秘→幕后/内幕/反转; "
            "6.专访→对话/访谈; "
            "7.完整版→全程/合集; "
            "8.警示→风险警示/安全警示; "
            "9.局势→地缘局势/大国博弈; "
            "不符合以上任一条的正常视频请返回空字符串''"
        )
    )


# ── 工具函数 ─────────────────────────────────────────────────────────────────

def _strip_md_code_block(text: str) -> str:
    """剥除 LLM 可能输出的 ```json ... ``` 包裹"""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # 去掉首行 ```json 和尾行 ```
        lines = lines[1:] if lines[0].startswith("```") else lines
        lines = lines[:-1] if lines and lines[-1].strip() == "```" else lines
        text = "\n".join(lines)
    return text.strip()


def graceful_truncate_title(title: str, max_len: int = 16, min_len: int = 6) -> str:  # [Gemini_3.5_Flash_planning]
    """[v1.9.1] 优雅截断短标题，保证截断后语义完整。

    算法：预处理净化（括号剔除）+ 正则分词 + 滑动窗口穷举 + 首部语义优先排序
    1. 预处理：对于超长标题，优先移除括号/方括号内的补充说明，避免其占据宝贵的短标题字数或导致分词不当
    2. 将处理后的标题按常见分隔符（：、，、|、—、空格等）切分为 token 列表（保留分隔符）
    3. 穷举所有 contiguous token 子序列，收集满足 [min_len, max_len] 的候选
    4. 按 (起始位置升序, 长度降序) 排序，优先保留最左侧（最核心）的语义段
    5. 若无任何合规候选，则进行安全兜底裁剪（末尾虚词/标点剔除）

    Args:
        title:   原始标题字符串（可能超出 max_len）
        max_len: 最大允许字符数，默认 16（微信视频号上限）
        min_len: 最小允许字符数，默认 6（微信视频号下限）

    Returns:
        满足 [min_len, max_len] 的最优子段，实在无法满足则返回安全截断结果
    """
    title = title.strip()
    if len(title) <= max_len:
        return title

    # 1. 预处理：优先移除括号/方括号内的辅助信息 (Try It and See / 尝试一下看看)
    cleaned_title = re.sub(r'\([^)]*\)|（[^）]*）|\[[^\]]*\]|【[^】]*】', '', title).strip()
    cleaned_title = re.sub(r'\s*，\s*，', '，', cleaned_title)
    cleaned_title = re.sub(r'\s*,\s*,', ',', cleaned_title)
    cleaned_title = re.sub(r'\s+', ' ', cleaned_title)

    if min_len <= len(cleaned_title) <= max_len:
        return cleaned_title

    title_for_trunc = cleaned_title if len(cleaned_title) >= min_len else title
    if len(title_for_trunc) <= max_len:
        return title_for_trunc

    # 2. 正则分词，捕获组保留分隔符本身
    sep_pattern = r'([：:\s|｜—–\-+，,、；;]+)'
    tokens = re.split(sep_pattern, title_for_trunc)

    candidates: list[tuple[int, int, str]] = []
    n = len(tokens)

    # 3. 穷举所有以文本段（偶数索引）为起止 of 连续子序列
    for i in range(0, n, 2):
        for j in range(i, n, 2):
            joined = "".join(tokens[i:j + 1]).strip()
            # 清除两端残留分隔符
            cleaned = re.sub(r'^[：:\s|｜—–\-+，,、；;]+|[：:\s|｜—–\-+，,、；;]+$', '', joined)
            if min_len <= len(cleaned) <= max_len:
                # 记录 (起始位置 i, 实际长度) — 排序时优先选最左侧起始（x[0] 越小越好），长度越长越好（-x[1] 越小越好）
                candidates.append((i, len(cleaned), cleaned))

    if candidates:
        # [Gemini_3.1_Pro_High_planning] v1.10.0 核心优化点：引入质量评分惩罚悬空词和转折词
        def score_candidate(cand_tuple):
            start_idx, length, text = cand_tuple
            score = start_idx  # 基础分是起始位置，越小越好 (即优先靠左)
            # 惩罚悬空陈述词结尾
            if re.search(r'(表示|认为|指出|宣布|警告|谈到|说|称|直言|坦言|解析|探讨|强调|证实|透露|预计|预测|建议|呼吁|提醒|坚信)$', text):
                score += 100
            # 惩罚以转折词或连词开头
            if re.match(r'^(但是|但|而且|并且|和|与|或|以及|却)', text):
                score += 50
            # 多余的单边引号惩罚
            if text.count('“') != text.count('”') or text.count('"') % 2 != 0:
                score += 30
            # 长度得分，越长越好，转为负数加上去，影响较小
            score -= (length * 0.1)
            return score

        candidates.sort(key=score_candidate)
        return candidates[0][2]

    # 4. 兜底裁剪：先去末尾标点，再按字符硬截，最后剔除末尾虚词/连接词
    safe = re.sub(r'[？?！!。，,：:\s]+$', '', title_for_trunc)
    if len(safe) <= max_len:
        return safe
    truncated = safe[:max_len]
    truncated = re.sub(r'[的得地与和或而将于在以等着了]$', '', truncated)
    truncated = re.sub(r'[：:，,|｜\s]+$', '', truncated).strip()
    return truncated


# ── 后备路径 ─────────────────────────────────────────────────────────────────

def extract_headline_workaround(translated_title: str) -> tuple[str, str]:
    """[v1.10.0 Workaround] 借鉴专业新闻解析器提取主干语义标题"""
    text = translated_title.strip()
    # 去除常见的末尾时间戳（如 7.30）
    text = re.sub(r'\s*\d+\.\d+\s*$', '', text).strip()
    
    verbs = "表示|认为|指出|宣布|警告|谈到|说|称|直言|坦言|解析|探讨|强调|证实|透露|预计|预测|建议|呼吁|提醒|坚信"
    
    # 模式 1：发言人 + 动词 + 逗号/冒号 + 言论
    # 例：联邦银行老板表示，人工智能要做好准备 -> 人工智能要做好准备
    m1 = re.match(r'^([^，,：:+]+(?:' + verbs + r'))[，,：:\s]+(.+)$', text)
    if m1:
        subject_clause, content_clause = m1.group(1), m1.group(2)
        if len(content_clause.strip()) >= 5: # 长度安全网兜底
            return content_clause.strip(), subject_clause.strip()
            
    # 模式 2：言论 + 逗号 + 发言人 + 动词
    m2 = re.match(r'^(.+?)[，,][\s]*([^，,：:+]+(?:' + verbs + r'))$', text)
    if m2:
        content_clause, subject_clause = m2.group(1), m2.group(2)
        if len(content_clause.strip()) >= 5:
            return content_clause.strip(), subject_clause.strip()
            
    # 模式 3：主题 + 冒号 + 陈述
    m3 = re.match(r'^([^：:+]+)[：:][\s]*(.+)$', text)
    if m3:
        topic_clause, statement_clause = m3.group(1), m3.group(2)
        if len(statement_clause.strip()) >= 5:
            return statement_clause.strip(), topic_clause.strip()
            
    return text, ""


def _translate_fallback(title: str, description: str) -> dict:
    """Gemini 不可用时，用 deep-translator 作兜底翻译"""
    logger.warning("Gemini unavailable — falling back to deep-translator")
    try:
        from deep_translator import GoogleTranslator
        tr = GoogleTranslator(source='auto', target='zh-CN')
        zh_title = tr.translate(title) or title
        desc_lines = [l.strip() for l in description.split("\n") if l.strip()]
        zh_desc = tr.translate(" ".join(desc_lines[:3])) if desc_lines else ""
        
        # [Gemini_3.1_Pro_High_planning] 提取主干并兜底
        core_title, hook_subtitle = extract_headline_workaround(zh_title)
        short_title = graceful_truncate_title(core_title)
        # 如果截断后太短，回退到原始
        if len(short_title) < 6:
            short_title = graceful_truncate_title(zh_title)
            hook_subtitle = ""
        
        # 动态分类与文案装配 (泛化解决)
        cat = classify_category(title, description)
        config = CATEGORY_CONFIG.get(cat, CATEGORY_CONFIG["科技"])
        
        copy_text = f"【双语精选】{zh_title}\n\n"
        if zh_desc:
            copy_text += f"{zh_desc}\n\n"
        copy_text += f"{config['tags']}\n🤖 {config['cta']}"
        return {
            "short_title":   short_title,
            "hook_subtitle": hook_subtitle,
            "copy":          copy_text,
            "category":      cat,
            "content_hints": [],
            "content_label": "",
        }
    except Exception as e:
        logger.error(f"deep-translator fallback failed: {e}")
        cat = classify_category(title, description)
        config = CATEGORY_CONFIG.get(cat, CATEGORY_CONFIG["科技"])
        return {
            "short_title":   graceful_truncate_title(title),  # [Claude_Sonnet_4.6_Thinking_planning] v1.9.0
            "hook_subtitle": "",
            "copy":          f"{title}\n\n{config['tags']}\n🤖 {config['cta']}",
            "category":      cat,
            "content_hints": [],
            "content_label": "",
        }


# ── 主生成函数 ───────────────────────────────────────────────────────────────

# [Claude_Sonnet_4.6_Thinking_planning] v1.8.0 模块级常量
_FORBIDDEN_WORD_REPLACEMENTS: dict[str, str] = {
    "概念本": "原型机", "爆款": "高阶", "秘籍": "指南",
    "公式": "体系", "逆天": "突破", "震惊": "震撼",
}

_SYSTEM_INSTRUCTION = """你是顶级微信视频号内容策划和中文科技媒体专栏主编。

【专业词汇映射规范（禁止生硬直译）】
- concept laptop -> 概念机/原型机  - prompting -> 提示词/向AI提问
- exit trap -> 资本接盘/套现陷阱  - crushes -> 彻底碾压/超越

【格调规范（禁止廉价营销词）】
严禁：爆款、干货、秘籍、公式、逆天、震惊、绝密、必看、收藏、保姆级、悄悄告诉你

【短标题黄金公式】
冲突型/悬念型/利益型/颠覆型/预言型，必须达到流量型标题的情绪张力"""


def _apply_post_processing(short_title: str, hook_subtitle: str) -> tuple[str, str]:
    """[Claude_Sonnet_4.6_Thinking_planning] v1.8.0 后处理纠偏：替换残留禁用词。"""
    for bad_word, good_word in _FORBIDDEN_WORD_REPLACEMENTS.items():
        if bad_word in short_title:
            logger.info(f"Post-processing: '{bad_word}' -> '{good_word}' in title")
            short_title = short_title.replace(bad_word, good_word)
        if bad_word in hook_subtitle:
            logger.info(f"Post-processing: '{bad_word}' -> '{good_word}' in subtitle")
            hook_subtitle = hook_subtitle.replace(bad_word, good_word)
    return short_title, hook_subtitle


def generate_wechat_content(title: str, description: str,
                             model_name: str = "gemini-2.5-flash") -> dict:
    """调用 Gemini 生成微信视频号所需的全部内容。

    [Claude_Sonnet_4.6_Thinking_planning] v1.8.0 重构：
    使用 google-genai SDK + Pydantic response_schema 强制结构化输出，
    替代手工 json.loads，彻底消除分类不准和解析异常风险。

    返回 dict:
        short_title   : str  — 6-16 字，自媒体流量型标题
        hook_subtitle : str  — ≤ 24 字，封面副标题 Hook
        copy          : str  — 文案正文（100-200 字 + hashtag + CTA）
        category      : str  — WECHAT_CATEGORIES 之一
        content_hints : list — 2-5 个语义 token（英文）
        content_label : str  — 运营标签
    """
    api_key = settings.gemini_api_key
    if not api_key:
        return _translate_fallback(title, description)

    try:
        from google import genai
        from google.genai import types as genai_types

        cats = "、".join(WECHAT_CATEGORIES)
        prompt = (
            f"请根据以下 YouTube 视频信息，生成适合微信视频号发布的完整内容。\n\n"
            f"【硬性约束】\n"
            f"- short_title：纯中文，6-16字，流量型标题\n"
            f"- hook_subtitle：纯中文，不超过24字\n"
            f"- copy：100-200字 + 3-5个hashtag + 一句CTA，纯文本无markdown\n"
            f"- category：从以下选1个：{cats}\n"
            f"- content_hints：从备选词选2-5个: "
            f"policy market capital stock robot ai llm coding software algorithm chip hardware "
            f"crypto mindset health medical nutrition geopolitics war election military "
            f"space physics astronomy science news media report "
            f"music song concert film movie drama entertainment gaming esports "
            f"sports fitness travel food lifestyle education course tutorial startup innovation\n"
            f"- content_label：封面角标（重磅/突发/独家/最新/深度/解析/揭秘/完整版/专访/警示/局势/首发）。"
            f"内容普通则返回空字符串''\n"
            f"- 禁止：emoji / 广告废话 / 翻译腔 / 政治敏感词\n\n"
            f"YouTube 标题：{title}\n"
            f"YouTube 简介（节选）：\n{description[:800]}"
        )

        logger.info(f"[v1.8.0] Calling Gemini [{model_name}] with response_schema...")
        client = genai.Client(api_key=api_key)
        
        # [Gemini_3.1_Pro_High_planning] v1.10.0 引入斐波那契重试退避机制
        fib_delays = [1, 2, 3]
        max_retries = len(fib_delays)
        response = None
        
        for attempt in range(max_retries + 1):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=genai_types.GenerateContentConfig(
                        system_instruction=_SYSTEM_INSTRUCTION,
                        response_mime_type="application/json",
                        response_schema=WeChatContentSchema,
                    ),
                )
                break
            except Exception as e:
                if attempt == max_retries:
                    logger.error(f"Gemini API call failed after {max_retries} retries: {e}")
                    raise e
                delay = fib_delays[attempt]
                logger.warning(f"Gemini API attempt {attempt+1} failed: {e}. Retrying in {delay}s...")
                time.sleep(delay)

        parsed: Optional[WeChatContentSchema] = response.parsed
        if parsed is None:
            raise ValueError(f"google-genai returned None parsed output. Raw: {response.text!r}")

        # [Claude_Sonnet_4.6_Thinking_planning] v1.9.0: 优雅截断替换硬截断
        short_title   = graceful_truncate_title(str(parsed.short_title).strip())
        hook_subtitle = str(parsed.hook_subtitle).strip()[:24]
        copy          = str(parsed.wechat_copy).strip()
        category      = str(parsed.category).strip()
        content_hints = parsed.content_hints if isinstance(parsed.content_hints, list) else []
        content_label = str(parsed.content_label).strip()

        if len(short_title) < 6:
            logger.warning(f"short_title too short ({len(short_title)} chars), using graceful fallback")
            short_title = graceful_truncate_title(title)

        if category not in WECHAT_CATEGORIES:
            logger.warning(f"LLM category '{category}' not in WECHAT_CATEGORIES, falling back to classify_category()")
            category = classify_category(title, description)

        if not copy:
            raise ValueError("google-genai returned empty copy")

        short_title, hook_subtitle = _apply_post_processing(short_title, hook_subtitle)

        logger.info(f"AI success: category={category!r}, title={short_title!r}, label={content_label!r}")
        return {
            "short_title":   short_title,
            "hook_subtitle": hook_subtitle,
            "copy":          copy,
            "category":      category,
            "content_hints": content_hints,
            "content_label": content_label,
        }

    except Exception as e:
        logger.error(f"google-genai call failed: {e}")
        return _translate_fallback(title, description)


# ── 兼容旧接口 ───────────────────────────────────────────────────────────────

def generate_wechat_copy(title: str, description: str,
                          model_name: str = "gemini-2.5-flash") -> str:
    """向后兼容：仅返回 copy 字符串"""
    return generate_wechat_content(title, description, model_name)["copy"]


# ── CLI 入口 ─────────────────────────────────────────────────────────────────

def main():
    # [Claude_Sonnet_4.6_Thinking_planning] v1.4 argparse '-'前缀 YouTube ID 终极修复
    # 根因: parse_known_args 只注册了 --youtube-id，导致其他参数全部丢失 → AttributeError
    # 根因2: argparse 把 '--youtube-id -X6YzlY_8tM' 中的 '-X...' 误认为 flag
    # 正确解法: 预处理 sys.argv，将 '--youtube-id -X...' 合并为 '--youtube-id=-X...'
    # 然后正常使用 parse_args()，所有参数都正确注册
    import sys
    argv = list(sys.argv[1:])  # 复制，不修改原始 sys.argv
    for i, arg in enumerate(argv):
        if arg == "--youtube-id" and i + 1 < len(argv):
            next_val = argv[i + 1]
            # 如果下一个值以 '-' 开头但不是 '--'，说明是以连字符开头的 YouTube ID
            if next_val.startswith("-") and not next_val.startswith("--"):
                argv[i] = f"--youtube-id={next_val}"
                argv.pop(i + 1)
            break

    parser = argparse.ArgumentParser(description="Generate WeChat Channels copy.")
    parser.add_argument("--youtube-id",  required=True, type=str)
    parser.add_argument("--title",       required=True, type=str)
    parser.add_argument("--desc-file",   default=None,  help="Path to description text file")
    parser.add_argument("--output-dir",  default="output", type=str)
    args = parser.parse_args(argv)

    description = ""
    if args.desc_file:
        p = Path(args.desc_file)
        if p.exists():
            description = p.read_text(encoding="utf-8")

    content = generate_wechat_content(args.title, description)

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    yid = args.youtube_id
    (out / f"{yid}_title.txt"   ).write_text(content["short_title"],   encoding="utf-8")
    (out / f"{yid}_copy.txt"    ).write_text(content["copy"],           encoding="utf-8")
    (out / f"{yid}_category.txt").write_text(content["category"],       encoding="utf-8")

    # [Claude_Sonnet_4.6_Thinking_fast] v1.5.0 新增：写出封面引擎依赖的两个文件
    if content.get("hook_subtitle"):
        (out / f"{yid}_subtitle.txt").write_text(content["hook_subtitle"], encoding="utf-8")
        logger.info(f"hook_subtitle → {content['hook_subtitle']!r}")
    if content.get("content_hints"):
        (out / f"{yid}_content_hints.json").write_text(
            json.dumps(content["content_hints"], ensure_ascii=False), encoding="utf-8"
        )
        logger.info(f"content_hints → {content['content_hints']!r}")
    # [Gemini_2.5_Pro_planning] v1.11.0: 写出封面角标标签
    if content.get("content_label"):
        (out / f"{yid}_label.txt").write_text(content["content_label"], encoding="utf-8")
        logger.info(f"content_label → {content['content_label']!r}")

    logger.info(f"short_title → {content['short_title']!r} (len={len(content['short_title'])})")
    logger.info(f"category    → {content['category']!r}")
    logger.info(f"copy        → output/{yid}_copy.txt")
    print(out / f"{yid}_copy.txt")


if __name__ == "__main__":
    main()
