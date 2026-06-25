"""自动评分曲线 (scoring.compute_auto_score) 单元测试

锁定 v3.9.0 评分曲线（架构 B 抽出后补的回归测试，抽出前该曲线无直接单测）：
- 热度门槛 (views>1500 且 like_rate>3.0%) → [80,95]，可进发布队列
- 未达门槛 → [0,70]，永不进队列
- 消除悬崖效应：views=1999/like_rate=3.49% 等不再被硬限 70

# Modification History
| Version | Date       | Author          | Description                          |
|---------|------------|-----------------|--------------------------------------|
| 1.0.0   | 2026-06-22 | Claude_Opus_4.8 | 初始创建：锁定 compute_auto_score 曲线 |
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from video_processing.scoring import (
    compute_auto_score, PUBLISH_SCORE_LINE,
    HEAT_VIEW_THRESHOLD, HEAT_LIKE_RATE_THRESHOLD,
)


# ── 边界与零值 ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("views,likes", [(0, 0), (0, 100), (-5, 10)])
def test_zero_or_negative_views_score_zero(views, likes):
    assert compute_auto_score(views, likes) == 0


def test_none_inputs_treated_as_zero():
    assert compute_auto_score(None, None) == 0


# ── 精确值（证明抽出后与 v3.9.0 公式逐字一致）────────────────────────────────

def test_exact_heat_branch_value():
    # views=3000, like_rate=4.0%: v_bonus=5*log10(2)=1.505, l_bonus=5*(1/7)=0.714 → round(82.22)=82
    assert compute_auto_score(3000, 120) == 82


def test_exact_ratio_branch_value():
    # views=1000(<=1500 比例 0.667), like_rate=2.0%(比例 0.667) → round(70*0.4444)=31
    assert compute_auto_score(1000, 20) == 31


# ── 门槛语义：热度分支可发布，比例分支永不可发布 ─────────────────────────────

def test_heat_branch_minimum_is_publishable():
    # 刚过门槛即应 >=80，>= 发布线
    s = compute_auto_score(HEAT_VIEW_THRESHOLD + 1, int((HEAT_VIEW_THRESHOLD + 1) * 0.031) + 1)
    assert s >= 80 and s >= PUBLISH_SCORE_LINE


def test_ratio_branch_caps_below_publish_line():
    # 即便点赞率拉满，未过 views 门槛也最多 70，进不了发布队列
    assert compute_auto_score(HEAT_VIEW_THRESHOLD, HEAT_VIEW_THRESHOLD) == 70
    assert compute_auto_score(HEAT_VIEW_THRESHOLD, HEAT_VIEW_THRESHOLD) < PUBLISH_SCORE_LINE


def test_at_view_threshold_exact_is_ratio_branch():
    # views == 1500 不满足 “> 1500”，走比例分支
    assert compute_auto_score(HEAT_VIEW_THRESHOLD, 60) <= 70


# ── 悬崖效应消除（v3.9.0 修复点）────────────────────────────────────────────

def test_no_cliff_effect_near_old_thresholds():
    # 旧公式 (2000, 3.5%) 下：views=1999 或 like_rate=3.49% 会被硬限 70。
    # 新曲线：只要 views>1500 且 like_rate>3.0% 即进入 [80,95]。
    assert compute_auto_score(1999, int(1999 * 0.0349)) >= 80   # like_rate≈3.49%
    assert compute_auto_score(1600, int(1600 * 0.031)) >= 80    # like_rate≈3.1%


# ── 上限封顶 ──────────────────────────────────────────────────────────────────

def test_score_capped_at_95():
    assert compute_auto_score(10_000_000, 5_000_000) == 95


def test_monotonic_more_engagement_not_lower():
    low = compute_auto_score(2000, 80)
    high = compute_auto_score(50000, 5000)
    assert high >= low
