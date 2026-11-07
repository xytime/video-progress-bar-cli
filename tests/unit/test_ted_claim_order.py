"""TED/TEDx 自动领取排序降级：有非 TED 时永远先领非 TED，TED 只进队尾。

分数线与点赞率门禁不在此改变。身份只认频道 ID，不认标题里的 TED 字样。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| ted-claim-order-v1 | 2026-11-07 | Grok | 覆盖混批、仅 TED、同档 boost，以及原视频频道身份。 |
"""
import pytest

from config.settings import settings
from video_processing.db.database import PipelineDB
from video_processing.scoring import TED_AUTO_PUBLISH_CHANNEL_IDS

TED, TEDX = TED_AUTO_PUBLISH_CHANNEL_IDS
# 1000 播放、7 赞 = 0.7%，严格大于默认 0.6% 点赞率线。
PASSING = {"view_count": 1000, "like_count": 7}


@pytest.fixture(autouse=True)
def ted_policy(monkeypatch):
    monkeypatch.setattr(settings, "ted_min_like_rate_pct", 0.6)
    monkeypatch.setattr(settings, "ted_auto_publish_after_id", 0)
    monkeypatch.setattr(settings, "ted_publish_score_line", 50)


@pytest.fixture
def db(tmp_path):
    return PipelineDB(str(tmp_path / "pipeline.db"))


def _order(db, query, **kwargs):
    kwargs.setdefault("limit", 20)
    return [(row["youtube_id"], row["slice_index"]) for row in query(**kwargs)]


def _both(db, **kwargs):
    """两个咽喉入口在全部未就绪时必须给出同一领取顺序。"""
    pending = _order(db, db.get_high_score_pending_videos, **kwargs)
    preparation = _order(db, db.get_high_score_preparation_candidates, **kwargs)
    assert pending == preparation
    return pending


def _add(db, youtube_id, title, channel_id, score, **kwargs):
    assert db.add_video(youtube_id, title, channel_id, score=score, **kwargs)


def test_mixed_batch_claims_lower_score_non_ted_before_higher_score_ted(db):
    _add(db, "plain-low", "普通宏观", "UCnot-ted-plain", 76, **PASSING)
    _add(db, "title-trap", "TED 演讲精选：美元与债务", "UCnot-ted-title", 80, **PASSING)
    _add(db, "below-line", "不够入池", "UCnot-ted-low", 74, **PASSING)
    _add(db, "ted-high", "无关标题", TED, 99, **PASSING)
    _add(db, "tedx-next", "另一条无关标题", TEDX, 98, **PASSING)
    _add(db, "ted-blocked", "点赞率不够仍不入池", TED, 99, view_count=1000, like_count=6)

    order = _both(db)
    assert order == [("title-trap", 0), ("plain-low", 0), ("ted-high", 0), ("tedx-next", 0)]
    assert _order(db, db.get_high_score_pending_videos, limit=1) == [("title-trap", 0)]
    assert _order(db, db.get_high_score_preparation_candidates, limit=1) == [("title-trap", 0)]


def test_ted_only_batch_keeps_score_then_created_at(db):
    _add(db, "late-high", "高分较新", TED, 95, **PASSING)
    _add(db, "early-mid", "同分更早", TED, 90, **PASSING)
    _add(db, "late-mid", "同分更晚", TEDX, 90, **PASSING)
    _add(db, "low", "低分", TEDX, 80, **PASSING)
    with db.get_connection() as conn:
        for youtube_id, created_at in (
            ("late-high", "2026-11-01 00:00:00"),
            ("early-mid", "2026-01-01 00:00:00"),
            ("late-mid", "2026-06-01 00:00:00"),
            ("low", "2026-01-02 00:00:00"),
        ):
            conn.execute(
                "UPDATE processed_videos SET created_at = ? WHERE youtube_id = ? AND slice_index = 0",
                (created_at, youtube_id),
            )

    assert _both(db) == [("late-high", 0), ("early-mid", 0), ("late-mid", 0), ("low", 0)]


def test_boost_stays_inside_ted_band(db):
    _add(db, "nted-new", "非 TED 新插队", "UCnot-ted-new", 76, **PASSING)
    _add(db, "nted-old", "非 TED 旧插队", "UCnot-ted-old", 99, **PASSING)
    _add(db, "nted-plain", "非 TED 未插队", "UCnot-ted-plain", 90, **PASSING)
    _add(db, "ted-new", "TED 最新插队", TED, 51, **PASSING)
    _add(db, "ted-old", "TED 较早插队", TEDX, 99, **PASSING)
    _add(db, "ted-plain", "TED 未插队", TED, 95, **PASSING)
    assert db.boost_video_queue("nted-new", now=3000.0)
    assert db.boost_video_queue("nted-old", now=1000.0)
    assert db.boost_video_queue("ted-new", now=4000.0)
    assert db.boost_video_queue("ted-old", now=2000.0)

    assert _both(db) == [
        ("nted-new", 0),
        ("nted-old", 0),
        ("nted-plain", 0),
        ("ted-new", 0),
        ("ted-old", 0),
        ("ted-plain", 0),
    ]


def test_pending_preparation_ready_still_orders_inside_each_band(db):
    _add(db, "ready-plain", "已就绪非 TED", "UCnot-ted-ready", 76, **PASSING)
    _add(db, "raw-plain", "未就绪高分非 TED", "UCnot-ted-raw", 99, **PASSING)
    _add(db, "ready-ted", "已就绪 TED", TED, 99, **PASSING)
    db.mark_video_ready_for_publication("ready-plain")
    db.mark_video_ready_for_publication("ready-ted")

    assert _order(db, db.get_high_score_pending_videos) == [
        ("ready-plain", 0),
        ("raw-plain", 0),
        ("ready-ted", 0),
    ]
    # 预加工入口本来就只看未就绪任务；就绪项离开该队列，不改变 TED 降级。
    assert _order(db, db.get_high_score_preparation_candidates) == [("raw-plain", 0)]


def test_identity_uses_origin_channel_not_title_or_child_channel(db):
    _add(db, "plain-parent", "普通原片", "UCorigin-plain", 80, **PASSING)
    plain_parent = db.get_video_by_youtube_id("plain-parent")
    db.update_video_status("plain-parent", "SEGMENTED")
    _add(
        db, "plain-parent", "切片", TED, 99, slice_index=1, parent_id=plain_parent["id"],
        view_count=1000, like_count=1,
    )

    _add(db, "ted-parent", "宏观访谈", TED, 90, **PASSING)
    ted_parent = db.get_video_by_youtube_id("ted-parent")
    db.update_video_status("ted-parent", "SEGMENTED")
    _add(
        db, "ted-parent", "切片", "UCchild-plain", 99, slice_index=1, parent_id=ted_parent["id"],
        view_count=10, like_count=0,
    )
    _add(db, "tedx-tail", "队尾", TEDX, 97, **PASSING)

    assert _both(db) == [("plain-parent", 1), ("ted-parent", 1), ("tedx-tail", 0)]
