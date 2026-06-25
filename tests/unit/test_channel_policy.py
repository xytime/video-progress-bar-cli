"""频道内容策略层 (Channel Policy) 单元测试

锁定 censor_engine.check_channel_policy() v1.6.0 的「上下文共现」行为，
防止后续调整词库时回归。覆盖范围：

- 硬命中词：政治人物 / 政党机构 / 武装组织 / 「国家+冲突」复合词 → 直接拦截
- 上下文共现：裸国名 (country_*) 与冲突信号词 (conflict_*) 同时出现 → 拦截
- 误杀回归：裸国名 / 裸冲突词单独出现 → 放行（旅游、美食、历史、商业等）
- 边界：单字 "核" 不应被当作冲突词，避免 "核心/核实" 误伤

# Modification History
| Version | Date       | Author          | Description                                  |
|---------|------------|-----------------|----------------------------------------------|
| 1.0.0   | 2026-06-13 | Claude_Opus_4.8 | 初始创建：锁定 v1.6.0 CP 层上下文共现判定行为 |
| 1.1.0   | 2026-06-22 | Claude_Opus_4.8 | [🅱️ 精准制导] 政客/政党裸名移出硬命中：bare 人名放行、人名+政治语境才拦截；新增 TestChannelPolicyPersonContext |
"""

import os
import sys

import pytest

# 确保 src 在路径中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from video_processing.censor_engine import (
    check_channel_policy,
    ACTION_CHANNEL_POLICY,
)


# ── 硬命中词：命中即拦截（行为同 v1.5.0）────────────────────────────────────────

class TestChannelPolicyHardHit:
    """政治人物 / 机构 / 武装组织 / 国家+冲突复合词，单独出现即拦截。"""

    @pytest.mark.parametrize("zh_text", [
        "习近平出席会议",               # 中国政治人物（仍硬命中）
        "俄乌战争最新进展",             # 国家+冲突复合词
        "伊朗核问题谈判破裂",           # '伊朗核' 复合词
        "哈马斯发表声明",               # 武装组织
        "内塔尼亚胡讲话全文",           # 冲突相关领导人
        "联合国安理会制裁决议",         # 机构性复合词
    ])
    def test_zh_hard_hit_rejects(self, zh_text):
        r = check_channel_policy(zh_text=zh_text, en_text="")
        assert r.hit is True, f"应硬命中拦截: {zh_text} → {r}"
        assert r.action == ACTION_CHANNEL_POLICY
        assert r.channel == "zh"

    @pytest.mark.parametrize("en_text", [
        "Iran nuclear deal explained",
        "Hamas releases a statement",
        "Russia-Ukraine frontline report",
        "Senate hearing on the new bill",
    ])
    def test_en_hard_hit_rejects(self, en_text):
        r = check_channel_policy(zh_text="", en_text=en_text)
        assert r.hit is True, f"应硬命中拦截: {en_text} → {r}"
        assert r.action == ACTION_CHANNEL_POLICY
        assert r.channel == "en"


# ── 上下文共现：国名 + 冲突词 同时出现才拦截 ──────────────────────────────────

class TestChannelPolicyCooccurrence:
    """裸国名与冲突信号词共现 → 判定为地缘政治内容并拦截。"""

    @pytest.mark.parametrize("zh_text, country, conflict", [
        ("以色列空袭加沙难民营",   "以色列", "空袭"),
        ("乌克兰战争最新战况",     "乌克兰", "战争"),
        ("伊朗遭导弹袭击",         "伊朗",   "导弹"),
        ("黎巴嫩冲突再度升级",     "黎巴嫩", "冲突"),
    ])
    def test_zh_cooccurrence_rejects(self, zh_text, country, conflict):
        r = check_channel_policy(zh_text=zh_text, en_text="")
        assert r.hit is True, f"国名+冲突词应共现拦截: {zh_text} → {r}"
        assert r.action == ACTION_CHANNEL_POLICY
        assert r.channel == "zh"
        # matched 记为 "<country>+<conflict>"，便于事后复盘
        assert r.matched == f"{country}+{conflict}", f"matched 格式异常: {r.matched}"

    @pytest.mark.parametrize("en_text", [
        "Israel launches airstrike on Gaza",
        "Ukraine war: latest frontline update",
        "Iran hit by missile strikes",
        "Tehran under new sanctions",
    ])
    def test_en_cooccurrence_rejects(self, en_text):
        r = check_channel_policy(zh_text="", en_text=en_text)
        assert r.hit is True, f"国名+冲突词应共现拦截: {en_text} → {r}"
        assert r.action == ACTION_CHANNEL_POLICY
        assert r.channel == "en"
        assert "+" in (r.matched or ""), f"共现 matched 应含 '+': {r.matched}"


# ── 误杀回归：裸国名 / 裸冲突词 单独出现应放行 ────────────────────────────────

class TestChannelPolicyBareNamesPass:
    """v1.6.0 核心诉求：非冲突语境下的国名视频不再被误杀。"""

    @pytest.mark.parametrize("zh_text", [
        "伊朗美食探店：德黑兰夜市攻略",   # 美食
        "乌克兰旅游攻略：基辅必去景点",   # 旅游
        "以色列科技创新巡礼",            # 科技
        "伊朗的核心技术突破",            # '核心' 不应被当作冲突词 '核'
    ])
    def test_zh_bare_country_passes(self, zh_text):
        r = check_channel_policy(zh_text=zh_text, en_text="")
        assert r.hit is False, f"纯国名/非冲突语境应放行: {zh_text} → {r}"

    @pytest.mark.parametrize("en_text", [
        "Iran travel guide: top 10 places to visit",
        "Best Iranian street food tour",
        "Visit Ukraine: Kyiv city walking tour",
        "The price war between phone makers",   # 裸冲突词无国名 → 放行
    ])
    def test_en_bare_name_passes(self, en_text):
        r = check_channel_policy(zh_text="", en_text=en_text)
        assert r.hit is False, f"纯国名/裸冲突词应放行: {en_text} → {r}"

    def test_lone_conflict_word_passes(self):
        """冲突信号词单独出现（无国名）不应拦截。"""
        r = check_channel_policy(zh_text="一场没有硝烟的价格战争", en_text="")
        assert r.hit is False, f"裸冲突词应放行 → {r}"


# ── 干净内容 / 空输入 ────────────────────────────────────────────────────────

class TestChannelPolicyClean:

    def test_clean_content_passes(self):
        r = check_channel_policy(
            zh_text="今天我们来学习 Python 编程",
            en_text="learning python programming today",
        )
        assert r.hit is False

    def test_empty_input_passes(self):
        r = check_channel_policy(zh_text="", en_text="")
        assert r.hit is False


# ── 🅱️ 精准制导：政客/政党裸名「人名 + 政治语境」共现才拦截 ─────────────────────

class TestChannelPolicyPersonContext:
    """v1.9.0：美国政客/政党人名移出硬命中，仅与政治语境/冲突词共现时拦截。"""

    @pytest.mark.parametrize("zh_text", [
        "特朗普为SpaceX星舰项目投资",     # 科技语境顺带提名 → 放行
        "马斯克发布新一代星舰",          # 同上
        "拜登的家庭生活纪录片",          # 传记语境
        "回顾历届美国大选趣闻",          # '大选' 无具体人名 → 放行
        "他是共和党支持者也爱徒步",       # 党名 + 生活内容 → 放行
    ])
    def test_zh_bare_person_passes(self, zh_text):
        r = check_channel_policy(zh_text=zh_text, en_text="")
        assert r.hit is False, f"裸人名/无政治语境应放行: {zh_text} → {r}"

    @pytest.mark.parametrize("en_text", [
        "Trump made a comment about Tesla stock",   # 科技语境 → 放行
        "the best trump card strategy in this game",# 'trump card' 习语 → 放行
        "Elon Musk unveils the new Starship",       # 科技 → 放行
        "a biography of Joe Biden's early years",   # 传记 → 放行
    ])
    def test_en_bare_person_passes(self, en_text):
        r = check_channel_policy(zh_text="", en_text=en_text)
        assert r.hit is False, f"裸人名/无政治语境应放行: {en_text} → {r}"

    @pytest.mark.parametrize("zh_text, person", [
        ("特朗普签署最新行政令", "特朗普"),
        ("拜登宣布新一轮制裁", "拜登"),
        ("马斯克领导政府效率部门改革", "马斯克"),
    ])
    def test_zh_person_with_context_rejects(self, zh_text, person):
        r = check_channel_policy(zh_text=zh_text, en_text="")
        assert r.hit is True, f"人名+政治语境应拦截: {zh_text} → {r}"
        assert r.channel == "zh"
        assert r.matched.startswith(f"{person}+"), f"matched 应为 人名+语境: {r.matched}"

    @pytest.mark.parametrize("en_text", [
        "Trump signs a new executive order",
        "the republican party wins the election",
        "elon musk joins the government",
    ])
    def test_en_person_with_context_rejects(self, en_text):
        r = check_channel_policy(zh_text="", en_text=en_text)
        assert r.hit is True, f"人名+政治语境应拦截: {en_text} → {r}"
        assert r.channel == "en"
        assert "+" in (r.matched or ""), f"共现 matched 应含 '+': {r.matched}"
