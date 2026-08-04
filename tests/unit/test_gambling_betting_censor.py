"""博彩/投注类商业合规风控回归测试。

锁定两条边界：

1. 预测市场/Polymarket/Kalshi 与下注、投注、bets、odds 等语义近距离共现时，命中 P2。
2. 普通财经语境中的英文 gamble/bet 隐喻仍然放行，避免恢复历史误杀。

# Modification History
| Version | Date       | Author | Description                                      |
|---------|------------|--------|--------------------------------------------------|
| 1.0.0   | 2026-08-04 | Codex  | 初始创建：预测市场投注风险 P2 命中与财经隐喻放行 |
| 1.1.0   | 2026-08-04 | Codex  | 补充博彩平台、赌场玩法、体育投注类硬命中词表测试 |
| 1.2.0   | 2026-08-04 | Codex  | 回测反例：中文“预测市场”动词短语加交易押注不误杀 |
| 1.3.0   | 2026-08-04 | Codex  | 回测反例：美元级 gamble 翻译与赌场行业讨论不误杀 |
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from config.settings import settings
from video_processing import censor_engine
from video_processing.censor_engine import ACTION_DEPRIORITIZE


@pytest.fixture(autouse=True)
def _use_builtin_rules(monkeypatch):
    """固定使用内置规则，避免外部热加载文件影响单元测试判定。"""
    monkeypatch.setattr(settings, "enable_external_censor_rules", False)
    censor_engine._rules_cache.update(mtime=None, blocklist=None, channel_policy=None)
    yield
    censor_engine._rules_cache.update(mtime=None, blocklist=None, channel_policy=None)


def test_prediction_market_betting_copy_hits_p2_zh():
    zh_text = (
        "Kalshi 和 Polymarket 等预测市场，让用户可以对任何事情下注，"
        "最终按事件结果结算赢家和输家。"
    )

    result = censor_engine.check_text(zh_text=zh_text)

    assert result.hit is True
    assert result.level == "P2"
    assert result.action == ACTION_DEPRIORITIZE
    assert result.matched == "prediction_market_betting_risk"
    assert result.channel == "zh"


def test_prediction_market_betting_subtitle_hits_p2_en():
    en_text = (
        "How do prediction markets settle their bets? "
        "Platforms like Polymarket let users wager on future events."
    )

    result = censor_engine.check_text(en_text=en_text)

    assert result.hit is True
    assert result.level == "P2"
    assert result.action == ACTION_DEPRIORITIZE
    assert result.matched == "prediction_market_betting_risk"
    assert result.channel == "en"


@pytest.mark.parametrize(
    "zh_text",
    [
        "这个博彩平台提供体育投注和赌球入口。",
        "开户链接指向线上赌场，里面有百家乐、老虎机和轮盘赌。",
        "该彩票软件宣传六合彩和彩票投注服务。",
    ],
)
def test_explicit_gambling_platform_terms_hit_p2_zh(zh_text):
    result = censor_engine.check_text(zh_text=zh_text)

    assert result.hit is True
    assert result.level == "P2"
    assert result.action == ACTION_DEPRIORITIZE
    assert result.channel == "zh"


def test_predatory_gambling_product_ads_hit_p2_zh():
    zh_text = "平台正在投放掠夺性赌博产品广告，并引导用户进入赌博网站。"

    result = censor_engine.check_text(zh_text=zh_text)

    assert result.hit is True
    assert result.level == "P2"
    assert result.action == ACTION_DEPRIORITIZE
    assert result.channel == "zh"


@pytest.mark.parametrize(
    "en_text",
    [
        "The site promotes an online casino and casino games.",
        "This betting platform advertises a sportsbook and sports betting.",
        "The app is a betting exchange run by a bookmaker.",
    ],
)
def test_explicit_gambling_platform_terms_hit_p2_en(en_text):
    result = censor_engine.check_text(en_text=en_text)

    assert result.hit is True
    assert result.level == "P2"
    assert result.action == ACTION_DEPRIORITIZE
    assert result.channel == "en"


def test_finance_metaphorical_bet_without_prediction_market_still_passes():
    en_text = "The $400B AI infrastructure gamble remains a risky bet by cloud companies."

    result = censor_engine.check_text(en_text=en_text)

    assert result.hit is False


def test_statistical_odds_without_gambling_context_still_passes():
    en_text = "The study reports an odds ratio, while investors bet on stronger cash flow."

    result = censor_engine.check_text(en_text=en_text)

    assert result.hit is False


def test_predict_markets_verb_phrase_with_trading_stake_still_passes():
    zh_text = (
        "为什么了解未来并不总是有助于预测市场。"
        "节目讨论交易实验揭示的市场情况，以及交易中最困难的决定不是买什么，而是押注多少。"
    )

    result = censor_engine.check_text(zh_text=zh_text)

    assert result.hit is False


def test_large_infrastructure_gamble_translation_still_passes():
    zh_text = (
        "它被描述为一台大型超级计算机，"
        "但实际上这是一场价值 5000 亿美元的赌博。"
    )

    result = censor_engine.check_text(zh_text=zh_text)

    assert result.hit is False


def test_casino_industry_mention_without_promotion_still_passes():
    zh_text = "这类财富来自采矿业、自然资源，或经营赌场等行业。"

    result = censor_engine.check_text(zh_text=zh_text)

    assert result.hit is False


def test_scan_all_matches_exposes_prediction_market_risk_for_review_ui():
    zh_text = "预测市场平台围绕未来事件投注，并在结果公布后结算。"

    matches = censor_engine.scan_all_matches(zh_text=zh_text)

    assert {
        "term": "prediction_market_betting_risk",
        "layer": "P2",
        "tag": "🔵 商业合规预警",
        "channel": "zh",
    } in matches
