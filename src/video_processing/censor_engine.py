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
| 1.8.0   | 2026-06-22 | Claude_Opus_4.8                        | [🅰️ 词库热加载] 硬编码 _BLOCKLIST/_CHANNEL_POLICY 改名 _DEFAULT_* 作兜底；新增外部 JSON（config/censor_rules.json）按 mtime 热加载，运维可在线增删词无需重部署；缺失/损坏/P0 空 → 安全回退默认（绝不置空）；选 JSON 而非 YAML 避免 P0 路径引入 pyyaml 依赖；由 enable_external_censor_rules 控制 |
| 1.9.0   | 2026-06-22 | Claude_Opus_4.8                        | [🅱️ CP 精准制导] 美国政客/政党裸人名从 CP 硬命中迁至 person_*，仅与 policy_context_*/conflict_* 共现时才拦截，根治审计「症结 3 过宽杀」（传记/大选科普/科技顺带提名误杀）；中国政治实体/领导人/武装组织/冲突复合词仍硬命中不变；scan_all_matches 同步；person_*/policy_context_* 为热加载可选键 |
| 2.0.0   | 2026-07-23 | Codex                                  | P0/P1/P2 支持 cooccurrence_zh/en 近距离共现规则，用于拦截“中国+独裁/威权/侵略/制裁规避”等字幕风险而不误杀泛地缘政治 |
| 2.1.0   | 2026-07-26 | Codex                                  | 中国领导人姓名提升为 P0 红线；新增“中国/敏感人物+爆炸/袭击/死亡”P0 兜底与严重负面事件 P1 人工复核 |
| 2.2.0   | 2026-07-27 | Codex                                  | 导出当前规则包 fingerprint，供审查台账记录命中时实际生效的规则版本 |
| 2.3.0   | 2026-08-04 | Codex                                  | P2 新增博彩/投注平台风控：预测市场/Polymarket/Kalshi 与投注语义近距离共现拦截，避免恢复裸 betting 误杀财经隐喻 |
| 2.3.1   | 2026-08-04 | Codex                                  | 整理博彩/赌博/体育投注/赌场玩法双语 P2 词表，补齐平台、网站、APP、赌场游戏等硬命中词 |
| 2.3.2   | 2026-08-04 | Codex                                  | 回测修正“预测市场”中文歧义：裸预测市场仅配强博彩上下文，Polymarket/Kalshi 平台词保留宽上下文 |
| 2.3.3   | 2026-08-04 | Codex                                  | 回测收窄博彩误杀：裸赌场改为平台/游戏/广告组合词，并豁免“美元级 gamble”财经隐喻 |
"""

import re
import copy
import json
import hashlib
import logging
import unicodedata
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

from config.settings import settings

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

_DEFAULT_BLOCKLIST: dict = {
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
            "习近平", "李强", "赵乐际", "王沪宁", "蔡奇", "丁薛祥",
            "李希", "韩正", "王毅", "李克强", "胡锦涛", "江泽民",
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
            "li qiang", "zhao leji", "wang huning", "cai qi", "ding xuexiang",
            "li xi", "han zheng", "wang yi", "li keqiang", "hu jintao", "jiang zemin",
            "overthrow the government",
            "split china",
        ],
        "cooccurrence_zh": [
            {
                "primary": [
                    "中国人", "中国公民", "中国工程师", "中国工人", "中方人员",
                    "中国项目", "中资项目", "中巴经济走廊", "一带一路",
                    "中国在中东", "中国战略", "中国政策",
                ],
                "context": [
                    "杀", "杀害", "伤害", "袭击", "攻击", "爆炸", "炸弹",
                    "阻止", "破坏", "报复", "发动者", "目标",
                ],
                "max_gap": 160,
                "matched": "anti_china_targeted_violence",
            },
            {
                "primary": ["中国", "中国政府", "中共", "中国共产党", "北京", "习近平", "李强", "王毅"],
                "context": ["爆炸", "火灾", "袭击", "枪击", "空袭", "死亡", "遇难", "伤亡", "坠毁", "灾难", "事故"],
                "max_gap": 120,
                "matched": "china_sensitive_negative_news",
            },
        ],
        "cooccurrence_en": [
            {
                "primary": [
                    "chinese nationals", "chinese citizens", "chinese engineers",
                    "chinese workers", "chinese personnel", "chinese projects",
                    "china-backed projects", "chinese-backed projects", "cpec",
                    "china-pakistan economic corridor", "belt and road",
                    "belt and road initiative", "china's strategy", "chinese strategy",
                    "china's policy", "chinese policy",
                ],
                "context": [
                    "kill", "killing", "killed", "target", "targeted", "attack",
                    "attacked", "blast", "explosion", "bomb", "bombing", "hurt",
                    "harm", "stop", "prevent", "disrupt", "sabotage",
                ],
                "max_gap": 320,
                "matched": "anti_china_targeted_violence",
            },
            {
                "primary": [
                    "china", "chinese", "beijing", "chinese government", "ccp", "prc",
                    "xi jinping", "li qiang", "wang yi",
                ],
                "context": [
                    "explosion", "blast", "fire", "attack", "attacks", "strike", "airstrike",
                    "shooting", "killing", "killed", "dead", "death", "deaths",
                    "casualties", "crash", "disaster", "accident",
                ],
                "max_gap": 240,
                "matched": "china_sensitive_negative_news",
            },
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
        "cooccurrence_zh": [
            {
                "primary": ["中国", "中国政府", "中共", "中国共产党"],
                "context": ["独裁", "专制", "威权", "极权", "侵略", "敌对政权", "敌对阵营", "改写国际规则"],
                "max_gap": 80,
            },
            {
                "primary": ["中国", "中国银行", "中资银行"],
                "context": ["规避制裁", "逃避制裁", "绕过制裁", "制裁规避"],
                "max_gap": 80,
            },
            {
                "primary": ["爆炸", "袭击", "枪击", "轰炸", "坠毁", "火灾"],
                "context": ["死亡", "遇难", "受伤", "伤亡", "造成", "至少"],
                "max_gap": 80,
                "matched": "severe_negative_news",
            },
        ],
        "cooccurrence_en": [
            {
                "primary": ["china", "chinese", "beijing", "chinese government", "ccp", "prc"],
                "context": [
                    "dictatorship", "dictatorships", "authoritarian", "authoritarian governance",
                    "totalitarian", "aggression", "acts of aggression", "hostile regime",
                    "hostile regimes", "rewrite the rules",
                ],
                "max_gap": 240,
            },
            {
                "primary": ["china", "chinese", "chinese banks", "beijing", "prc"],
                "context": ["evading sanctions", "sanctions evasion", "evade sanctions", "circumvent sanctions"],
                "max_gap": 180,
            },
            {
                "primary": ["explosion", "blast", "attack", "shooting", "bombing", "crash", "fire"],
                "context": ["killing", "killed", "dead", "death", "deaths", "injured", "casualties", "at least"],
                "max_gap": 180,
                "matched": "severe_negative_news",
            },
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
            "赌博", "博彩", "网络赌博", "网络博彩", "博彩平台",
            "赌博平台", "赌博网站", "赌博app", "赌博软件",
            "博彩网站", "博彩app", "博彩软件", "投注平台",
            "投注网站", "体育博彩", "体育投注", "体育竞猜",
            "赌球", "赌马", "赌盘", "线上赌场", "在线赌场", "网络赌场",
            "赌场平台", "赌场app", "赌场软件", "赌场游戏", "赌场广告",
            "百家乐", "老虎机", "轮盘赌", "德州扑克",
            "六合彩", "彩票投注", "购彩平台",
            "色情", "成人内容", "网络招嫖",
            "日赚几千", "网赚", "兼职月入",
        ],
        "en": [
            # 2026-06-25: 移除 "gamble"/"betting"——英文财经标题/描述中 "gamble"(豪赌/押注)、
            # "betting"(押注) 几乎都是隐喻，曾把 "The $400B AI infrastructure gamble" 误杀降权。
            # 保留无歧义的 "gambling"；预测市场/投注平台类 betting 风险由下方上下文共现规则承接。
            "get rich quick", "overnight millionaire",
            "gambling", "online gambling", "gambling site", "gambling app",
            "casino", "online casino", "casino games", "betting site",
            "betting app", "betting platform", "sports betting",
            "sportsbook", "online sportsbook", "sports betting site",
            "betting exchange", "bookmaker", "bookie", "parlay betting",
            "slot machine", "roulette", "blackjack", "poker room",
            "porn", "adult content", "escort",
            "make money online", "passive income secret",
        ],
        "exemptions_zh": [
            "亿美元的赌博", "美元的赌博",
            "亿美元 赌博", "美元 赌博",
        ],
        "exemptions_en": [],
        "cooccurrence_zh": [
            {
                "primary": ["预测市场", "事件合约", "竞猜市场"],
                "context": [
                    "下注", "投注", "赌注", "赌局", "博彩", "赌博",
                    "赢家", "输家", "盘口", "赔率", "封盘", "庄家",
                    "投注者", "赌客",
                ],
                "max_gap": 120,
                "matched": "prediction_market_betting_risk",
            },
            {
                "primary": ["polymarket", "kalshi", "卡尔希", "预测市场平台", "投注平台"],
                "context": [
                    "下注", "投注", "赌注", "押注", "赌局", "博彩", "赌博",
                    "赢家", "输家", "结算", "盘口", "赔率", "开盘",
                    "封盘", "庄家", "投注者", "赌客",
                ],
                "max_gap": 160,
                "matched": "prediction_market_betting_risk",
            },
        ],
        "cooccurrence_en": [
            {
                "primary": [
                    "prediction market", "prediction markets", "polymarket",
                    "kalshi", "event contract", "event contracts",
                ],
                "context": [
                    "bet", "bets", "betting", "wager", "wagers", "wagering",
                    "gamble", "gambling", "settle", "settlement", "odds", "punters",
                ],
                "max_gap": 320,
                "matched": "prediction_market_betting_risk",
            },
        ],
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

_DEFAULT_CHANNEL_POLICY: dict = {
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
        # [Claude_Opus_4.8] v1.9.0 🅱️ 精准制导：美国政客/政党「裸人名」已从硬命中迁至
        # 下方 person_zh —— 仅在与 policy_context_zh / conflict_zh 共现时才拦截，消除
        # 传记/历史/大选科普/科技视频里「顺带提到人名」的误杀（详见 person_zh 注释）。
        # 中国政治实体/领导人（习近平/李克强/王毅 等）仍保留在上方硬命中，不受影响。
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
        # 美国国内政治（补充）—— 政党名（民主党/共和党/两党）已迁至 person_zh 上下文判定
        "国会听证",
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
        # [Claude_Opus_4.8] v1.9.0 🅱️ 精准制导：美国政客/政党裸人名已迁至 person_en
        # （仅在与 policy_context_en / conflict_en 共现时拦截），消除科技/传记/大选科普
        # 视频里顺带提及人名的误杀。"trump administration" 等也由 trump+administration 共现覆盖。
        # 聚合词（本身已含明确政治语境，保留硬命中）
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
        # 政党名（republican party / democratic party）已迁至 person_en 上下文判定
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
    # ── 政治人物/政党「裸名」(须与 policy_context_* 或 conflict_* 共现才拦截)──────
    # [Claude_Opus_4.8] v1.9.0 🅱️ 精准制导：人名/党名单独出现（传记、历史、大选科普、
    # 科技视频顺带提及）不再拦截；仅当同段文本另有「政策/选举/立法/制裁/听证」等政治
    # 语境词（policy_context_*）或冲突词（conflict_*）共现时，才判为频道越界并拦截。
    # 这把审计「症结 3 过宽杀」从地毯式人名匹配升级为上下文制导，显著降低误杀。
    "person_zh": [
        "特朗普", "川普", "万斯", "卢比奥", "贝森特", "赫格塞斯", "邦迪",
        "拜登", "哈里斯", "布林肯", "耶伦", "奥斯汀",
        "舒默", "麦卡锡", "马斯克",
        "民主党", "共和党", "两党",
    ],
    "person_en": [
        "donald trump", "trump", "jd vance", "marco rubio", "scott bessent",
        "pete hegseth", "pam bondi", "joe biden", "kamala harris",
        "antony blinken", "janet yellen", "lloyd austin",
        "chuck schumer", "kevin mccarthy", "mike johnson", "elon musk",
        "republican party", "democratic party",
    ],
    # ── 政治语境信号词（解锁 person_* 共现判定）────────────────────────────────
    "policy_context_zh": [
        "政策", "政府", "法案", "行政令", "总统令", "大选", "选举", "竞选", "弹劾",
        "制裁", "关税", "执政", "连任", "投票", "听证", "内阁", "国务卿",
        "白宫", "国会", "参议院", "众议院", "政变", "外交政策", "峰会",
        "集会", "竞选集会", "移民政策", "签证令", "党争",
    ],
    "policy_context_en": [
        "policy", "policies", "government", "bill", "legislation", "executive order",
        "election", "campaign", "rally", "impeach", "impeachment",
        "sanction", "sanctions", "tariff", "tariffs", "administration",
        "white house", "congress", "senate", "cabinet", "secretary of state",
        "ballot", "hearing", "inauguration", "reelection", "diplomacy", "coup",
        "president", "presidential",
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


# ── 外部规则热加载 (External Rules Hot-Reload) ─────────────────────────────────
# [Claude_Opus_4.8] 🅰️ 进化：把上面的硬编码词库迁到可热加载的外部 JSON
# （config/censor_rules.json）。运维可在线增删敏感词、无需改代码重部署，闭合
# 「突发敏感事件 → 词库更新」之间数小时到数天的空窗期。
#
# 安全底线（吸取 R8「.env 回退致审查全失效」的教训）：
#   • 由 settings.enable_external_censor_rules 控制；关闭 → 永远用硬编码默认。
#   • 文件缺失 / 解析失败 / 结构非法 → 回退到「上一次成功加载的缓存」或硬编码默认，
#     绝不返回空词库（否则等于静默关闭审查）。
#   • P0 层 zh+en 不得同时为空，否则判文件非法并回退（防误清空导致政治违禁全失效）。
#   • 选用 JSON 而非报告建议的 YAML：JSON 是标准库、零新增依赖；censor_engine 处于
#     P0 导入路径，绝不能因第三方库（pyyaml）缺失而 import 失败。
#   • 按 st_mtime 热加载：每次检测 stat 文件，mtime 变化才重解析，常态零开销。

_REQUIRED_BLOCK_LEVELS = ("P0", "P1", "P2")
_REQUIRED_CP_LIST_KEYS = ("zh", "en", "country_zh", "country_en", "conflict_zh", "conflict_en")

# 缓存：mtime 不变则直接复用，避免每次审查都读盘解析
_rules_cache: dict = {"mtime": None, "blocklist": None, "channel_policy": None}


def _validate_cooccurrence_rules(items: list, path: str) -> None:
    """校验 P0/P1/P2 的近距离共现规则，避免外部 JSON 写错后静默放行。"""
    if not isinstance(items, list):
        raise ValueError(f"{path} must be a list")
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"{path}[{idx}] must be an object")
        for key in ("primary", "context"):
            values = item.get(key)
            if not isinstance(values, list) or not values or not all(isinstance(v, str) and v.strip() for v in values):
                raise ValueError(f"{path}[{idx}].{key} must be a non-empty string list")
        max_gap = item.get("max_gap", 240)
        if not isinstance(max_gap, int) or max_gap < 0:
            raise ValueError(f"{path}[{idx}].max_gap must be a non-negative integer")
        label = item.get("matched")
        if label is not None and not isinstance(label, str):
            raise ValueError(f"{path}[{idx}].matched must be a string")


def _validate_rules(data: dict) -> tuple:
    """校验外部规则结构并补全可选字段，返回 (blocklist, channel_policy)。结构非法抛 ValueError。"""
    if not isinstance(data, dict):
        raise ValueError("top-level must be a JSON object")
    bl = data.get("blocklist")
    cp = data.get("channel_policy")
    if not isinstance(bl, dict) or not isinstance(cp, dict):
        raise ValueError("missing 'blocklist' or 'channel_policy' object")

    for lvl in _REQUIRED_BLOCK_LEVELS:
        r = bl.get(lvl)
        if not isinstance(r, dict):
            raise ValueError(f"blocklist.{lvl} must be an object")
        for k in ("tag", "action"):
            if not isinstance(r.get(k), str):
                raise ValueError(f"blocklist.{lvl}.{k} must be a string")
        for k in ("zh", "en"):
            if not isinstance(r.get(k), list):
                raise ValueError(f"blocklist.{lvl}.{k} must be a list")
        r.setdefault("score", 0)
        r.setdefault("exemptions_zh", [])
        r.setdefault("exemptions_en", [])
        for k in ("cooccurrence_zh", "cooccurrence_en"):
            r.setdefault(k, [])
            _validate_cooccurrence_rules(r[k], f"blocklist.{lvl}.{k}")
    # P0 是政治安全红线，绝不允许被（误）清空
    if not (bl["P0"]["zh"] or bl["P0"]["en"]):
        raise ValueError("blocklist.P0 has no words — refusing to disable the political red line")

    for k in ("tag", "action"):
        if not isinstance(cp.get(k), str):
            raise ValueError(f"channel_policy.{k} must be a string")
    for k in _REQUIRED_CP_LIST_KEYS:
        if not isinstance(cp.get(k), list):
            raise ValueError(f"channel_policy.{k} must be a list")
    # [Claude_Opus_4.8] v1.9.0 🅱️：person_*/policy_context_* 为可选键（旧文件无则默认空，
    # 退化为纯硬命中+国名共现，不报错），存在时必须是 list。
    for k in ("person_zh", "person_en", "policy_context_zh", "policy_context_en"):
        cp.setdefault(k, [])
        if not isinstance(cp[k], list):
            raise ValueError(f"channel_policy.{k} must be a list")
    cp.setdefault("exemptions_zh", [])
    cp.setdefault("exemptions_en", [])
    return bl, cp


def _load_external_rules() -> tuple:
    """返回当前生效的 (blocklist, channel_policy)。

    flag 关闭 → 硬编码默认；开启 → 外部 JSON（按 mtime 热加载，任何失败均安全回退）。
    """
    if not settings.enable_external_censor_rules:
        return _DEFAULT_BLOCKLIST, _DEFAULT_CHANNEL_POLICY

    def _fallback(reason: str) -> tuple:
        if _rules_cache["blocklist"] is not None:
            logger.error(f"[Censor] external rules unusable ({reason}); keeping last-good cache")
            return _rules_cache["blocklist"], _rules_cache["channel_policy"]
        logger.error(f"[Censor] external rules unusable ({reason}); falling back to built-in defaults")
        return _DEFAULT_BLOCKLIST, _DEFAULT_CHANNEL_POLICY

    try:
        path = Path(settings.censor_rules_path)
        if not path.is_file():
            return _fallback(f"file not found: {path}")
        mtime = path.stat().st_mtime
        if mtime == _rules_cache["mtime"] and _rules_cache["blocklist"] is not None:
            return _rules_cache["blocklist"], _rules_cache["channel_policy"]
        bl, cp = _validate_rules(json.loads(path.read_text(encoding="utf-8")))
        _rules_cache.update(mtime=mtime, blocklist=bl, channel_policy=cp)
        logger.info(f"[Censor] external rules (re)loaded from {path}")
        return bl, cp
    except Exception as e:
        return _fallback(str(e))


def _get_blocklist() -> dict:
    """当前生效的违法词库（P0/P1/P2）。"""
    return _load_external_rules()[0]


def _get_channel_policy() -> dict:
    """当前生效的频道策略词库（CP）。"""
    return _load_external_rules()[1]


def dump_default_rules() -> dict:
    """导出硬编码默认规则为可 JSON 序列化的 dict，用于生成/重置 config/censor_rules.json。

    [Claude_Opus_4.8] 返回深拷贝：调用方（或误传入 _validate_rules 的 setdefault）对返回值的
    任何改动都不会污染模块级 _DEFAULT_* 兜底词库。
    """
    return {
        "_comment": "内容审查词库（热加载）。编辑保存后无需重启，由 enable_external_censor_rules 开关控制；"
                    "P0 层不得为空；action 取值见 censor_engine.ACTION_* 常量。",
        "version": 1,
        "blocklist": copy.deepcopy(_DEFAULT_BLOCKLIST),
        "channel_policy": copy.deepcopy(_DEFAULT_CHANNEL_POLICY),
    }


def current_rules_fingerprint() -> str:
    """返回当前生效规则包的短 hash，用于事故复盘时确认命中依据。"""
    blocklist, channel_policy = _load_external_rules()
    payload = json.dumps(
        {"blocklist": blocklist, "channel_policy": channel_policy},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


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


def _term_spans_zh(dense_text: str, term: str) -> list[tuple[int, int]]:
    dense_term = _strip_spaces(_normalize(term))
    if not dense_term:
        return []
    return [(m.start(), m.end()) for m in re.finditer(re.escape(dense_term), dense_text)]


def _term_spans_en(normalized_text: str, term: str) -> list[tuple[int, int]]:
    norm_term = _normalize(term)
    if not norm_term:
        return []
    return [(m.start(), m.end()) for m in re.finditer(rf"\b{re.escape(norm_term)}\b", normalized_text)]


def _cooccurrence_hit(text: str, rules: list[dict], *, channel: str, dense_text: str = "") -> Optional[str]:
    """返回首个近距离共现命中，matched 形如 "china+dictatorship"。"""
    if not text or not rules:
        return None
    span_fn = _term_spans_zh if channel == "zh" else _term_spans_en
    haystack = dense_text if channel == "zh" else text

    for rule in rules:
        max_gap = rule.get("max_gap", 240)
        for primary in rule["primary"]:
            primary_spans = span_fn(haystack, primary)
            if not primary_spans:
                continue
            for context in rule["context"]:
                context_spans = span_fn(haystack, context)
                if not context_spans:
                    continue
                for p_start, p_end in primary_spans:
                    for c_start, c_end in context_spans:
                        gap = max(c_start - p_end, p_start - c_end, 0)
                        if gap <= max_gap:
                            return rule.get("matched") or f"{primary}+{context}"
    return None


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

    _blocklist = _get_blocklist()
    for level in ("P0", "P1", "P2"):
        rule        = _blocklist[level]
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

            cohit = _cooccurrence_hit(
                zh_norm,
                rule.get("cooccurrence_zh", []),
                channel="zh",
                dense_text=zh_dense,
            )
            if cohit and not _is_exempted(zh_norm, exempts_zh):
                logger.warning(f"[Censor] {level} zh-channel co-occurrence hit: '{cohit}'")
                return CensorResult(
                    hit=True, level=level, tag=tag,
                    score=score, action=action,
                    matched=cohit, channel="zh",
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

            cohit = _cooccurrence_hit(en_norm, rule.get("cooccurrence_en", []), channel="en")
            if cohit and not _is_exempted(en_norm, exempts_en):
                logger.warning(f"[Censor] {level} en-channel co-occurrence hit: '{cohit}'")
                return CensorResult(
                    hit=True, level=level, tag=tag,
                    score=score, action=action,
                    matched=cohit, channel="en",
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
    rule = _get_channel_policy()
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
        # [Claude_Opus_4.8] v1.9.0 🅱️：政治人名/党名 仅在与政治语境/冲突词共现时拦截
        person = _find_zh(rule.get("person_zh", []))
        if person:
            pctx = _find_zh(rule.get("policy_context_zh", [])) or _find_zh(rule.get("conflict_zh", []))
            if pctx:
                logger.warning(f"[ChannelPolicy] zh-channel person co-occurrence hit: '{person}'+'{pctx}'")
                return _result(f"{person}+{pctx}", "zh")
            logger.debug(f"[ChannelPolicy] zh person '{person}' without policy context → pass")

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
        # [Claude_Opus_4.8] v1.9.0 🅱️：政治人名/党名 仅在与政治语境/冲突词共现时拦截
        person = _find_en(rule.get("person_en", []))
        if person:
            pctx = _find_en(rule.get("policy_context_en", [])) or _find_en(rule.get("conflict_en", []))
            if pctx:
                logger.warning(f"[ChannelPolicy] en-channel person co-occurrence hit: '{person}'+'{pctx}'")
                return _result(f"{person}+{pctx}", "en")
            logger.debug(f"[ChannelPolicy] en person '{person}' without policy context → pass")

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
    _blocklist = _get_blocklist()
    for level in ("P0", "P1", "P2"):
        rule = _blocklist[level]
        tag = rule["tag"]
        if zh_norm:
            for word in rule.get("zh", []):
                if _zh_hit(word):
                    _add(word, level, tag, "zh")
        if en_norm:
            for word in rule.get("en", []):
                if _en_hit(word):
                    _add(word, level, tag, "en")
        cohit_zh = _cooccurrence_hit(
            zh_norm,
            rule.get("cooccurrence_zh", []),
            channel="zh",
            dense_text=zh_dense,
        )
        if cohit_zh:
            _add(cohit_zh, level, tag, "zh")
        cohit_en = _cooccurrence_hit(en_norm, rule.get("cooccurrence_en", []), channel="en")
        if cohit_en:
            _add(cohit_en, level, tag, "en")

    # ── Channel Policy（硬命中词 + 国名/冲突共现）────────────────────────────────
    cp = _get_channel_policy()
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
        # [Claude_Opus_4.8] v1.9.0 🅱️：政治人名/党名 + 政治语境/冲突词 共现
        zh_person = [w for w in cp.get("person_zh", []) if _zh_hit(w)]
        zh_pctx = [w for w in cp.get("policy_context_zh", []) if _zh_hit(w)]
        if zh_person and (zh_pctx or zh_conflict):
            for c in zh_person + zh_pctx:
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
        # [Claude_Opus_4.8] v1.9.0 🅱️：政治人名/党名 + 政治语境/冲突词 共现
        en_person = [w for w in cp.get("person_en", []) if _en_hit(w)]
        en_pctx = [w for w in cp.get("policy_context_en", []) if _en_hit(w)]
        if en_person and (en_pctx or en_conflict):
            for c in en_person + en_pctx:
                _add(c, "CP", cp_tag, "en")

    return hits
