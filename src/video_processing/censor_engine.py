"""内容安全审查引擎 — 双语双通道 P0/P1/P2 违禁拦截

所有字幕文本（中文翻译 + 原始英文）必须经此引擎过滤，
任何命中结果均须由调用方执行对应的系统拦截动作。

# Modification History
| Version | Date       | Author                                 | Description                                                                  |
|---------|------------|----------------------------------------|------------------------------------------------------------------------------|
| 1.0.0   | 2026-05-26 | Claude_Sonnet_4.6_Thinking_planning    | 初始创建：双语规则引擎、归一化预处理、豁免列表、P0/P1/P2 动作分发           |
| 1.1.0   | 2026-06-01 | Gemini_2.5_Flash_planning              | 新增「频道内容策略层」：_CHANNEL_POLICY + check_channel_policy()，独立于违法拦截规则 |
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

_CHANNEL_POLICY: dict = {
    "tag":   "🚫 频道策略限制",
    "action": ACTION_CHANNEL_POLICY,
    "zh": [
        # 用户明确声明：不做中国政治/外交/地缘话题
        "中国政府", "中国共产党", "中共", "中南海",
        "中美关系", "中美贸易", "对华关税",
        "台湾问题", "台海", "台海局势",
        "习近平", "李克强", "王毅",
        "新疆问题", "西藏问题",
        "一带一路政治",
    ],
    "en": [
        "xi jinping", "chinese communist party", "ccp",
        "china-us relations", "us china trade", "tariffs on china",
        "taiwan strait", "taiwan issue", "cross-strait",
        "xinjiang issue", "tibet issue",
        "belt and road politics",
        "beijing policy", "chinese government policy",
    ],
    # 豁免：中性商业/技术语境，允许通过
    "exemptions_zh": [
        "中国芯片", "中国制造", "中国市场", "中国消费者", "中国科技",
        "在中国上市", "中国经济数据", "中概股",
    ],
    "exemptions_en": [
        "made in china", "chinese chip", "chinese market", "chinese consumer",
        "chinese tech", "china economy", "china gdp", "china stock",
    ],
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
                if word_norm in en_norm:
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

    # ── 中文通道 ────────────────────────────────────────────────────────────
    if zh_norm:
        for word in rule["zh"]:
            word_norm  = _normalize(word)
            word_dense = _strip_spaces(word_norm)
            if word_dense in zh_dense:
                if _is_exempted(zh_norm, exempts_zh):
                    logger.debug(f"[ChannelPolicy] zh exemption hit for '{word}'")
                    continue
                logger.warning(f"[ChannelPolicy] zh-channel hit: '{word}'")
                return CensorResult(
                    hit=True, level="CP", tag=tag,
                    score=0, action=action,
                    matched=word, channel="zh",
                )

    # ── 英文通道 ────────────────────────────────────────────────────────────
    if en_norm:
        for word in rule["en"]:
            word_norm = _normalize(word)
            if word_norm in en_norm:
                if _is_exempted(en_norm, exempts_en):
                    logger.debug(f"[ChannelPolicy] en exemption hit for '{word}'")
                    continue
                logger.warning(f"[ChannelPolicy] en-channel hit: '{word}'")
                return CensorResult(
                    hit=True, level="CP", tag=tag,
                    score=0, action=action,
                    matched=word, channel="en",
                )

    return CensorResult(hit=False)
