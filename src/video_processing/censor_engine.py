"""内容安全审查引擎 — 双语双通道 P0/P1/P2 违禁拦截

所有字幕文本（中文翻译 + 原始英文）必须经此引擎过滤，
任何命中结果均须由调用方执行对应的系统拦截动作。

# Modification History
| Version | Date       | Author                                 | Description                                                                  |
|---------|------------|----------------------------------------|------------------------------------------------------------------------------|
| 1.0.0   | 2026-05-26 | Claude_Sonnet_4.6_Thinking_planning    | 初始创建：双语规则引擎、归一化预处理、豁免列表、P0/P1/P2 动作分发           |
| 1.1.0   | 2026-06-01 | Gemini_2.5_Flash_planning              | 新增「频道内容策略层」：_CHANNEL_POLICY + check_channel_policy()，独立于违法拦截规则 |
| 1.2.0   | 2026-06-01 | Gemini_2.5_Flash_planning              | [Code Review Fix] 移除 CP 层 exemptions（文本层豁免会让违禁词被商业词庚护）；移除 CP 层重复的 xi jinping |
| 1.3.0   | 2026-06-04 | Claude_Sonnet_4.6_Thinking_fast        | _CHANNEL_POLICY 新增美国国家领导人名单（中英双通道），与中国政治人名对等处理 |
| 1.4.0   | 2026-06-04 | Gemini_3.5_Flash_planning           | [风控优化] 英文通道引入 \b 单词边界正则匹配，解决 Patriot 包含 riot 导致误杀的问题 |
| 1.5.0   | 2026-06-11 | Claude_Opus_4.8                        | _CHANNEL_POLICY 新增中东战争、乌克兰战争、伊朗冲突关键词，全面覆盖地缘政治内容 |
| 1.6.0   | 2026-06-13 | Claude_Opus_4.8                        | [误杀优化] CP 层裸国名（iran/ukraine/israel…）改为「国名+冲突词」上下文共现判定，单独出现不再拦截；新增 country_*/conflict_* 词组 |
| 1.7.0   | 2026-06-13 | Claude_Opus_4.8                        | 新增 scan_all_matches()：不短路扫描全部层，返回文本命中的所有审查词，供「复核放行」标签云高亮与人工决策展示 |
"""

import re
import logging
import unicodedata
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# ── 动作常量 (Action Constants) ────────────────────────────────────────────────
# 调用方根据 action 字段决定执行何种系统干预动作

ACTION_REJECT_SIGTERM     = "REJECT_SIGTERM"       # P0: 一票否决，立即 SIGTERM + FAILED
ACTION_SUSPEND_MANUAL     = "SUSPEND_MANUAL_REVIEW"  # P1: 挂起，等待人工复核
ACTION_DEPRIORITIZE       = "DEPRIORITIZE"         # P2: 降权，进入 PENDING 屏蔽队列
ACTION_CHANNEL_POLICY     = "CHANNEL_POLICY_SKIP"  # CP: 超出频道内容策略边界 → FAILED + Telegram 警告

# ── 违禁规则库 (Blocklist Rules) ───────────────────────────────────────────────
# [Claude_Sonnet_4.6_Thinking_planning] 双语规则：zh 通道检测中文字幕，en 通道检测原始英文字幕
# 设计原则：翻译引擎风控失效导致中文字幕为空时，en 通道独立兜底拦截

_BLOCKLIST: dict = {
    "P0": {
        "tag":    "🔴 政治安全违禁",
        "score":  95,
        "action": ACTION_REJECT_SIGTERM,
        "zh": [
            "港独", "台独", "疆独", "藏独",
            "天安门事件", "六四事件", "六四",
            "法轮功", "真善忍", "李洪志",
            "达赖喇嘛", "班禅喇嘛",
            "大纪元", "新唐人", "看中国", "阿波罗网",
            "郭文贵", "郝海东",
            "分裂中国", "推翻政府", "颠覆国家",
            "支那",
        ],
        "en": [
            "falun gong", "falungong",
            "tiananmen", "june 4th", "june fourth",
            "epoch times", "epochtimes", "ntd news",
            "dalai lama", "panchen lama",
            "hong kong independence",
            "taiwan independence",
            "xi jinping", "xijinping",
            "overthrow the government",
            "split china",
        ],
        # 豁免：命中上述词汇但包含以下上下文字符串时，不触发拦截
        "exemptions_zh": [],
        "exemptions_en": [],
    },
    "P1": {
        "tag":    "🟡 政策敏感拦截",
        "score":  75,
        "action": ACTION_SUSPEND_MANUAL,
        "zh": [
            "维权", "上访", "越级上访",
            "罢工", "暴动",
            "封锁消息", "被消音",
            "翻墙", "翻墙软件", "梯子软件", "科学上网",
            # [Claude_Sonnet_4.6_Thinking_planning] BUG-4 修复: 加入"北京"触发词，配合 exemptions_zh 豁免逻辑。
            # 测试证明："北京大学"/"北京时间"等安全词组必须豁免拦截。
            "北京",
        ],
        "en": [
            "vpn", "gfw", "great firewall",
            "climb over the wall", "circumvention",
            "riot", "protest suppression",
        ],
        # "北京大学"、"北京时间" 等不触发拦截（仅中文通道）
        "exemptions_zh": [
            "北京大学", "北京时间", "北京烤鸭", "北京协和", "北京中关村",
            "北京奥运", "北京冬奥", "北京故宫", "北京天坛",
        ],
        "exemptions_en": [
            "peking university", "beijing university",
            "beijing olympics", "beijing time",
        ],
    },

    "P2": {
        "tag":    "🔵 商业合规预警",
        "score":  50,
        "action": ACTION_DEPRIORITIZE,
        "zh": [
            "一夜暴富", "快速致富", "暴利",
            "赌博", "博彩", "网络赌博",
            "色情", "成人内容", "网络招嫖",
            "日赚几千", "网赚", "兼职月入",
        ],
        "en": [
            "get rich quick", "overnight millionaire",
            "gamble", "gambling", "betting",
            "porn", "adult content", "escort",
            "make money online", "passive income secret",
        ],
        "exemptions_zh": [],
        "exemptions_en": [],
    },
}

# ── 频道内容策略规则表 (Channel Policy Rules) ─────────────────────────────────
# [Gemini_2.5_Flash_planning] 设计原则：
#   1. 与 _BLOCKLIST（违法内容）完全分离，独立开关控制（enable_channel_policy_filter）
#   2. 这里的词汇不违法，但超出频道内容定位边界，由用户根据运营需要自由调整
#   3. 触发后的动作为 ACTION_CHANNEL_POLICY → 调用方标记 FAILED + Telegram 警告
#
# [Claude_Opus_4.8] v1.6.0 — 词表分三类，区分「硬命中」与「上下文共现」：
#   • zh / en          : 硬命中词。政治人物、政党机构、武装组织/领导人，以及本身
#                        已含「国家+冲突」语义的复合词（如 "iran nuclear"、"俄乌战争"）。
#                        命中任意一词即直接拦截（行为同 v1.5.0）。
#   • country_zh/en    : 「裸国名/地名」软命中词（iran、ukraine、israel、加沙…）。
#                        单独出现 *不* 拦截——避免旅游/美食/历史/体育类视频被误杀。
#   • conflict_zh/en   : 冲突/军事信号词（war、strike、sanctions、空袭、制裁…）。
#                        单独出现 *不* 拦截。
#   仅当「某个 country 词」与「某个 conflict 词」在同一段文本中共现时，才判定为
#   地缘政治内容并拦截；matched 字段记为 "<country>+<conflict>"，便于事后复盘。
#   注意：单字冲突词（如 "核"）会误伤 "核心/核实"，故 conflict_zh 只收多字词，
#   "核问题/核设施/核武器" 而非裸 "核"。

_CHANNEL_POLICY: dict = {
    "tag":   "🚫 频道策略限制",
    "action": ACTION_CHANNEL_POLICY,
    # ── 硬命中词（命中即拦截）──────────────────────────────────────────────────
    "zh": [
        # 用户明确声明：不做中国政治/外交/地缘话题
        "中国政府", "中国共产党", "中共", "中南海",
        "中美关系", "中美贸易", "对华关税",
        "台湾问题", "台海", "台海局势",
        "习近平", "李克强", "王毅",
        "新疆问题", "西藏问题",
        "一带一路政治",
        # [Claude_Sonnet_4.6_Thinking_fast] v1.3.0 — 美国国家领导人（与中国政治人名对等处理）
        # 现任政府核心（第47届，2025─）
        "特朗普", "川普",      # Donald Trump，总统
        "万斯",               # JD Vance，副总统
        "卢比奥",             # Marco Rubio，国务卿
        "贝森特",             # Scott Bessent，财政部长
        "赫格塞斯",           # Pete Hegseth，国防部长
        "邦迪",               # Pam Bondi，司法部长
        # 前任政府（第46届，2021—2025）
        "拜登",               # Joe Biden，前总统
        "哈里斯",             # Kamala Harris，前副总统
        "布林肯",             # Antony Blinken，前国务卿
        "耶伦",               # Janet Yellen，前财政部长
        "奥斯汀",             # Lloyd Austin，前国防部长
        # 国会领导层
        "舒默",               # Chuck Schumer，参议院民主党领袖
        "麦卡锡",             # Kevin McCarthy，前众议院议长
        "约翰逊",             # Mike Johnson，现任众议院议长
        # 其他高曝光度政治人物（精确限定政治语境，避免误杀 SpaceX/Tesla/AI 视频）
        "马斯克政府",            # Elon Musk + 政府语境
        "马斯克DOGE", "马斯克doge",
        # 聚合词（泛政治化上下文）
        "美国总统",
        "美国国会", "美参议院", "美众议院",
        "白宫政策", "美国政府政策",
        # [Claude_Opus_4.8] v1.5.0 — 武装组织/领导人，及「国家+冲突」复合词（硬命中）
        "以军", "真主党", "哈马斯", "胡塞武装", "胡塞",
        "内塔尼亚胡", "伊斯兰革命卫队",
        "以黎冲突", "以哈冲突",
        "泽连斯基", "俄乌战争", "俄乌冲突",
        "伊朗核", "伊朗导弹",
        "也门战争", "红海袭击",
        "联合国安理会制裁",
        # 美国国内政治（补充）
        "民主党", "共和党", "两党", "国会听证",
        "众议院民主党", "参议院共和党",
        "CIA", "中情局",
    ],
    "en": [
        # [Gemini_2.5_Flash_planning] Code Review Fix v1.2.0:
        # 移除 "xi jinping"——P0 _BLOCKLIST 已包含，重复定义会导致认知混乱：
        # 两层同时开启时 P0 先拦截， CP 层永远不会执行到；
        # 两层分开开启时行为不一致，难以解释。
        "chinese communist party", "ccp",
        "china-us relations", "us china trade", "tariffs on china",
        "taiwan strait", "taiwan issue", "cross-strait",
        "xinjiang issue", "tibet issue",
        "belt and road politics",
        "beijing policy", "chinese government policy",
        # [Claude_Sonnet_4.6_Thinking_fast] v1.3.0 — 美国国家领导人（英文通道，与中文通道对等）
        # 现任政府核心（第47届）
        "donald trump", "trump administration",
        "jd vance",
        "marco rubio",
        "scott bessent",
        "pete hegseth",
        "pam bondi",
        # 前任政府（第46届）
        "joe biden", "biden administration",
        "kamala harris",
        "antony blinken",
        "janet yellen",
        "lloyd austin",
        # 国会领导层
        "chuck schumer",
        "kevin mccarthy",
        "mike johnson",
        # 其他高曝光度政治人物（精确限定政治语境，避免误杀 SpaceX/Tesla/AI 视频）
        "elon musk doge",          # DOGE 政府效率部门语境
        "elon musk government",    # 政府顾问语境
        "elon musk white house",   # 白宫语境
        "elon musk trump",         # 与 Trump 政治绑定
        # 聚合词（泛政治化上下文）
        "us president policy", "white house policy",
        "us congress", "us senate politics", "us house of representatives",
        # [Claude_Opus_4.8] v1.5.0 — 武装组织/领导人，及「国家+冲突」复合词（硬命中）
        "hezbollah", "hamas", "houthi",
        "netanyahu", "idf",
        "zelensky", "volodymyr", "russia-ukraine",
        "irgc", "revolutionary guard",
        "iran nuclear", "iran sanctions",
        "red sea attack", "yemen war",
        # 美国国内政治（补充）
        "house democrats", "senate republicans", "house republicans",
        "senate democrats",
        "republican party", "democratic party",
        "partisan", "senate hearing", "house hearing",
        "congressional hearing", "senate committee", "house committee",
        "cia director",
        "us military strike", "us sanctions",
    ],
    # ── 「裸国名/地名」软命中词（须与 conflict_* 共现才拦截）────────────────────
    # [Claude_Opus_4.8] v1.6.0：单独出现放行，仅在与冲突信号词共现时判定为地缘政治内容。
    "country_zh": [
        "以色列", "加沙", "黎巴嫩", "贝鲁特", "约旦河西岸",
        "乌克兰", "基辅", "顿巴斯", "乌东",
        "伊朗", "德黑兰",
    ],
    "country_en": [
        "israel", "israeli", "gaza", "lebanon", "beirut", "west bank",
        "ukraine", "ukrainian", "kyiv", "donbas",
        "iran", "iranian", "tehran",
    ],
    # ── 冲突/军事信号词（单独出现放行，仅用于解锁 country_* 共现）────────────────
    # [Claude_Opus_4.8] v1.6.0：zh 侧只收多字词，避免单字 "核" 误伤 "核心/核实"。
    "conflict_zh": [
        "战争", "冲突", "空袭", "轰炸", "导弹", "导弹袭击",
        "制裁", "入侵", "袭击", "进攻", "地面进攻",
        "停火", "停战", "战争罪", "平民伤亡", "难民危机",
        "军事冲突", "核武器", "核设施", "核问题", "核计划",
    ],
    "conflict_en": [
        "war", "wars", "conflict", "strike", "strikes",
        "airstrike", "airstrikes", "air strike",
        "missile", "missiles", "nuclear",
        "sanction", "sanctions", "invasion", "invade",
        "military", "troops", "bombing", "bombard",
        "attack", "attacks", "casualties", "offensive",
        "siege", "ceasefire", "war crime", "war crimes",
    ],
    # [Gemini_2.5_Flash_planning] Code Review Fix v1.2.0:
    # CP 层不应设置 exemptions。
    # 原因：_is_exempted 工作在整段文本级别（只要文本中出现任意一个豁免词，就豁免该检测层所有命中词）。
    # 这导致安全漏洞："xi jinping discusses china economy" 将因 "china economy" 而豁免。
    # CP 层的词汇本身应足够精确，不依赖豁免词容错率。
    # 如需豁免特定商业场景，应直接精减违禁词列表。
    "exemptions_zh": [],
    "exemptions_en": [],
}


@dataclass
class CensorResult:
    """违禁检测结果。

    Attributes:
        hit:       是否命中违禁规则。
        level:     违禁级别（'P0'/'P1'/'P2'），未命中时为 None。
        tag:       前端展示用违禁标签字符串。
        score:     违禁度分值（0-100）。
        action:    系统应执行的拦截动作常量。
        matched:   命中的原始词汇（调试用）。
        channel:   命中通道（'zh'/'en'），调试用。
    """
    hit: bool
    level: Optional[str] = None
    tag: Optional[str] = None
    score: int = 0
    action: Optional[str] = None
    matched: Optional[str] = None
    channel: Optional[str] = None

    def __repr__(self) -> str:
        if not self.hit:
            return "<CensorResult: PASS>"
        return f"<CensorResult: {self.level} | {self.tag} | score={self.score} | matched='{self.matched}' via {self.channel}>"


# ── 归一化预处理 (Text Normalization) ─────────────────────────────────────────

def _normalize(text: str) -> str:
    """归一化文本：全角→半角、大小写统一、去除多余空白符和标点。

    这一步是防绕过的第一道关卡。任何利用特殊字符规避的尝试（如"天　安　门"、
    "F̶a̶l̶u̶n̶G̶o̶n̶g̶"）都会在此被标准化。
    """
    # 全角字符转半角（Unicode NFKC 标准化）
    text = unicodedata.normalize("NFKC", text)
    # 统一小写
    text = text.lower()
    # 压缩所有空白（包括 tab、全角空格）为单个普通空格
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _strip_spaces(text: str) -> str:
    """移除所有空格，用于中文词汇的连续匹配（防止'天 安 门'拆空格绕过）。"""
    return re.sub(r"\s", "", text)


# ── 豁免检查 (Exemption Check) ───────────────────────────────────────────────

def _is_exempted(normalized_text: str, exemptions: list[str]) -> bool:
    """检查文本中是否包含豁免上下文字符串。

    只要豁免词汇出现在文本中，就视为豁免，不触发拦截。
    """
    if not exemptions:
        return False
    for exemption in exemptions:
        if _normalize(exemption) in normalized_text:
            return True
    return False


# ── 主检测函数 (Main Censor Function) ─────────────────────────────────────────

def check_text(zh_text: str = "", en_text: str = "") -> CensorResult:
    """对双语字幕文本执行违禁检测。

    采用双通道策略：
    - zh_text: 中文字幕（可来自翻译）
    - en_text: 原始英文字幕（独立备用通道，防翻译失效绕过）

    按 P0 → P1 → P2 的严重程度顺序检测，命中最高级别立即返回，不继续检测。

    Args:
        zh_text: 中文字幕文本（翻译结果，可为空）。
        en_text: 原始英文字幕文本（可为空）。

    Returns:
        CensorResult 实例。hit=False 表示合规通过。
    """
    # 归一化两个通道的文本
    zh_norm   = _normalize(zh_text)
    zh_dense  = _strip_spaces(zh_norm)  # 去空格版，用于中文词汇匹配
    en_norm   = _normalize(en_text)

    for level in ("P0", "P1", "P2"):
        rule        = _BLOCKLIST[level]
        tag         = rule["tag"]
        score       = rule["score"]
        action      = rule["action"]
        exempts_zh  = rule.get("exemptions_zh", [])
        exempts_en  = rule.get("exemptions_en", [])

        # ── 中文通道检测 ──────────────────────────────────────────────────────
        if zh_norm:
            for word in rule["zh"]:
                word_norm  = _normalize(word)
                word_dense = _strip_spaces(word_norm)

                # 在去空格的文本中匹配（防拆字绕过）
                if word_dense in zh_dense:
                    # 豁免检查：以完整归一化文本（含空格）做上下文判断
                    if _is_exempted(zh_norm, exempts_zh):
                        logger.debug(f"[Censor] zh exemption hit for '{word}' in level {level}")
                        continue
                    logger.warning(f"[Censor] {level} zh-channel hit: '{word}'")
                    return CensorResult(
                        hit=True, level=level, tag=tag,
                        score=score, action=action,
                        matched=word, channel="zh",
                    )

        # ── 英文通道检测（独立备用，翻译失效时也能拦截）─────────────────────
        if en_norm:
            for word in rule["en"]:
                word_norm = _normalize(word)
                # [Gemini_3.5_Flash_planning] v1.4.0: 英文单词必须独立匹配（使用 \b 单词边界检测），
                # 避免 "Patriot" 中的 "riot" 等子串引发误杀。
                if re.search(rf"\b{re.escape(word_norm)}\b", en_norm):
                    if _is_exempted(en_norm, exempts_en):
                        logger.debug(f"[Censor] en exemption hit for '{word}' in level {level}")
                        continue
                    logger.warning(f"[Censor] {level} en-channel hit: '{word}'")
                    return CensorResult(
                        hit=True, level=level, tag=tag,
                        score=score, action=action,
                        matched=word, channel="en",
                    )

    # 全部通过
    return CensorResult(hit=False)


# ── 频道内容策略检测函数 (Channel Policy Check) ───────────────────────────────

def check_channel_policy(zh_text: str = "", en_text: str = "") -> CensorResult:
    """检测视频内容是否超出频道内容策略边界（与违法内容拦截完全独立）。

    [Gemini_2.5_Flash_planning] 设计说明：
    - 本函数仅检测「频道运营策略」层，不检测法律合规层。
    - 触发词汇均合法，但超出频道内容定位（如：用户声明不做中国政治话题）。
    - 命中时返回 action=ACTION_CHANNEL_POLICY，调用方负责标记 FAILED 并发 Telegram 警告。

    [Claude_Opus_4.8] v1.6.0 检测顺序（命中即返回）：
      1. 硬命中词（zh/en）——政治人物、机构、武装组织、「国家+冲突」复合词，直接拦截。
      2. 上下文共现——「裸国名」(country_*) 与「冲突信号词」(conflict_*) 同时出现才拦截；
         单独的国名（如旅游视频里的 "iran"）或单独的冲突词（如 "price war"）均放行，
         matched 记为 "<country>+<conflict>"。

    Args:
        zh_text: 中文标题或文案（可为空）。
        en_text: 英文标题或描述（可为空）。

    Returns:
        CensorResult 实例。hit=False 表示通过策略检测。
    """
    rule = _CHANNEL_POLICY
    tag    = rule["tag"]
    action = rule["action"]
    exempts_zh = rule.get("exemptions_zh", [])
    exempts_en = rule.get("exemptions_en", [])

    zh_norm  = _normalize(zh_text)
    zh_dense = _strip_spaces(zh_norm)
    en_norm  = _normalize(en_text)

    def _result(matched: str, channel: str) -> CensorResult:
        return CensorResult(
            hit=True, level="CP", tag=tag,
            score=0, action=action,
            matched=matched, channel=channel,
        )

    # 中文：去空格后做连续子串匹配（防拆字绕过），返回首个命中的原始词。
    def _find_zh(words: list[str]) -> Optional[str]:
        for word in words:
            if _strip_spaces(_normalize(word)) in zh_dense:
                return word
        return None

    # 英文：\b 单词边界匹配（避免子串误杀，如 Patriot 含 riot），返回首个命中的原始词。
    def _find_en(words: list[str]) -> Optional[str]:
        for word in words:
            if re.search(rf"\b{re.escape(_normalize(word))}\b", en_norm):
                return word
        return None

    # ── 中文通道 ────────────────────────────────────────────────────────────
    # 豁免词为空（见 _CHANNEL_POLICY 注释）；命中任意豁免词则整通道跳过。
    if zh_norm and not _is_exempted(zh_norm, exempts_zh):
        hard = _find_zh(rule["zh"])
        if hard:
            logger.warning(f"[ChannelPolicy] zh-channel hard hit: '{hard}'")
            return _result(hard, "zh")
        country = _find_zh(rule["country_zh"])
        if country:
            conflict = _find_zh(rule["conflict_zh"])
            if conflict:
                logger.warning(f"[ChannelPolicy] zh-channel co-occurrence hit: '{country}'+'{conflict}'")
                return _result(f"{country}+{conflict}", "zh")
            logger.debug(f"[ChannelPolicy] zh country '{country}' without conflict word → pass")

    # ── 英文通道 ────────────────────────────────────────────────────────────
    if en_norm and not _is_exempted(en_norm, exempts_en):
        hard = _find_en(rule["en"])
        if hard:
            logger.warning(f"[ChannelPolicy] en-channel hard hit: '{hard}'")
            return _result(hard, "en")
        country = _find_en(rule["country_en"])
        if country:
            conflict = _find_en(rule["conflict_en"])
            if conflict:
                logger.warning(f"[ChannelPolicy] en-channel co-occurrence hit: '{country}'+'{conflict}'")
                return _result(f"{country}+{conflict}", "en")
            logger.debug(f"[ChannelPolicy] en country '{country}' without conflict word → pass")

    return CensorResult(hit=False)


# ── 全量扫描（人工复核辅助）─────────────────────────────────────────────────

def scan_all_matches(zh_text: str = "", en_text: str = "") -> list:
    """[Claude_Opus_4.8] 不短路扫描全部审查层，返回文本命中的「所有」审查词。

    与 check_text / check_channel_policy 不同：本函数不在首个命中处返回，而是遍历
    P0/P1/P2 违法词库与 Channel Policy 运营词库的全部词，收集所有命中项，供「复核
    放行」弹窗的关键词标签云高亮、以及人工决策展示使用（仅展示，不执行任何拦截）。

    注意：本函数不应用 exemptions（豁免）——它的目的是把文本里「所有可能敏感的词」
    都摊给人看，由人决策，而非自动判定是否拦截。

    Returns:
        去重后的命中列表（按 P0→P1→P2→CP 顺序）：
        [{"term": 原始词, "layer": 'P0'/'P1'/'P2'/'CP', "tag": 展示标签, "channel": 'zh'/'en'}]
    """
    zh_norm  = _normalize(zh_text)
    zh_dense = _strip_spaces(zh_norm)
    en_norm  = _normalize(en_text)

    hits: list = []
    seen: set = set()  # (term, layer) 去重

    def _add(term: str, layer: str, tag: str, channel: str) -> None:
        key = (term, layer)
        if key not in seen:
            seen.add(key)
            hits.append({"term": term, "layer": layer, "tag": tag, "channel": channel})

    def _zh_hit(word: str) -> bool:
        return _strip_spaces(_normalize(word)) in zh_dense

    def _en_hit(word: str) -> bool:
        return re.search(rf"\b{re.escape(_normalize(word))}\b", en_norm) is not None

    # ── 违法词库 P0/P1/P2（不短路）────────────────────────────────────────────
    for level in ("P0", "P1", "P2"):
        rule = _BLOCKLIST[level]
        tag = rule["tag"]
        if zh_norm:
            for word in rule.get("zh", []):
                if _zh_hit(word):
                    _add(word, level, tag, "zh")
        if en_norm:
            for word in rule.get("en", []):
                if _en_hit(word):
                    _add(word, level, tag, "en")

    # ── Channel Policy（硬命中词 + 国名/冲突共现）────────────────────────────────
    cp = _CHANNEL_POLICY
    cp_tag = cp["tag"]
    if zh_norm:
        for word in cp["zh"]:
            if _zh_hit(word):
                _add(word, "CP", cp_tag, "zh")
        zh_country = [w for w in cp["country_zh"] if _zh_hit(w)]
        zh_conflict = [w for w in cp["conflict_zh"] if _zh_hit(w)]
        if zh_country and zh_conflict:  # 仅当国名与冲突词共现时才视为命中
            for c in zh_country + zh_conflict:
                _add(c, "CP", cp_tag, "zh")
    if en_norm:
        for word in cp["en"]:
            if _en_hit(word):
                _add(word, "CP", cp_tag, "en")
        en_country = [w for w in cp["country_en"] if _en_hit(w)]
        en_conflict = [w for w in cp["conflict_en"] if _en_hit(w)]
        if en_country and en_conflict:
            for c in en_country + en_conflict:
                _add(c, "CP", cp_tag, "en")

    return hits
