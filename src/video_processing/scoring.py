"""自动评分 — 纯函数式热度评分

从 PipelineManager.score_pending_videos 抽出的纯计算，便于单测与复用（架构 B 第 1 步：
降低 PipelineManager 职责、为此前无直接单测的核心评分曲线补测试）。无 I/O、无副作用。

评分曲线（与抽出前逐字一致）：
- views <= 0                          → 0
- views > 1500 且 like_rate > 3.0%    → 对数加权 [80, 95]（满足热度门槛，进发布队列）
- 否则                                 → 比例评分 [0, 70]（永不进发布队列）

# Modification History
| Version | Date       | Author          | Description                                                  |
|---------|------------|-----------------|--------------------------------------------------------------|
| 1.0.0   | 2026-06-22 | Claude_Opus_4.8 | 从 pipeline_manager.score_pending_videos 抽出 compute_auto_score（v3.9.0 曲线逐字保留） |
| 1.1.0   | 2026-08-08 | Codex           | 增加频道评分上限：The Economist 的任何写入评分不得超过 60 |
"""
import math

# 热度门槛（v3.9.0：从 (2000, 3.5%) 下调至 (1500, 3.0%)，消除悬崖效应导致的发布断流）
HEAT_VIEW_THRESHOLD = 1500
HEAT_LIKE_RATE_THRESHOLD = 3.0
# 发布线：score >= 75 才进入 process_high_score_videos
PUBLISH_SCORE_LINE = 75

# 频道评分上限是发布策略的一部分，必须在统一写入入口执行，避免自动评分、
# 人工调分、重算或审查复核从不同路径绕过。
THE_ECONOMIST_CHANNEL_ID = "UC0p5jTq6Xx_DosDFxVXnWaQ"
CHANNEL_SCORE_CAPS = {THE_ECONOMIST_CHANNEL_ID: 60}


def cap_channel_score(channel_id: str | None, score: int) -> int:
    """返回遵守频道评分上限后的分数；未配置上限的频道保持原分数。"""
    cap = CHANNEL_SCORE_CAPS.get(channel_id or "")
    return min(score, cap) if cap is not None else score


def compute_auto_score(view_count: int, like_count: int) -> int:
    """根据播放量与点赞率计算自动评分（0–95 的整数）。

    Args:
        view_count: YouTube 播放量（None/负数按 0 处理）。
        like_count: YouTube 点赞数（None/负数按 0 处理）。

    Returns:
        整数评分。>=75 方可进入自动发布队列（见 PUBLISH_SCORE_LINE）。
    """
    views = max(0, view_count or 0)
    likes = max(0, like_count or 0)
    if views <= 0:
        return 0

    like_rate = min(100.0, likes / views * 100)
    if views > HEAT_VIEW_THRESHOLD and like_rate > HEAT_LIKE_RATE_THRESHOLD:
        # 满足热度门槛：对数加权评分 [80, 95]
        v_bonus = min(10.0, 5 * math.log10(views / HEAT_VIEW_THRESHOLD))
        l_bonus = min(5.0, 5 * (like_rate - 3.0) / 7.0)
        return max(80, min(95, round(80 + v_bonus + l_bonus)))
    # 未满足门槛：比例评分 [0, 70]
    v_ratio = min(1.0, views / HEAT_VIEW_THRESHOLD)
    l_ratio = min(1.0, like_rate / 3.0) if like_rate > 0 else 0.0
    return max(0, min(70, round(70 * v_ratio * l_ratio)))
