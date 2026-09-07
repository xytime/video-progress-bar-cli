"""控制面视频筛选、分页与浏览标记测试。

真实临时 SQLite 验证查询必须在服务端分页前执行；浏览标记只影响控制面显示，
绝不能改变任务或平台状态。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-07 | Codex | 初始创建：覆盖 DAL 筛选排序、准确分页、API 参数和浏览标记隔离。 |
| 1.1.0 | 2026-09-07 | Codex | 覆盖来源发布日期默认排序与跨 Tab 的 80 分以上筛选。 |
| 1.2.0 | 2026-09-07 | Codex | 覆盖仅含旧 upload_date 的历史记录按来源日期参与默认排序，并保留同日内的来源时间顺序。 |
"""

from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from video_processing.db.database import PipelineDB
from web import app as web_app


def _seed(db: PipelineDB) -> None:
    today = datetime.now().strftime("%Y%m%d")
    db.add_video("wait-alpha", "Climate Futures", "TEDx Talks", score=20, zh_title="气候未来", source_published_at="2026-09-02T10:00:00Z")
    db.add_video("wait-beta", "Markets", "Bloomberg Television", score=70, zh_title="市场观察", source_published_at="2026-09-04T10:00:00Z")
    db.add_video("wait-legacy-latest", "Legacy latest", "TEDx Talks", score=15, upload_date="20260905")
    db.add_video("wait-source-latest", "Source latest", "TEDx Talks", score=18, source_published_at="2026-09-05T12:00:00Z")
    db.add_video("wait-gamma", "Other", "TEDx Talks", score=10)
    db.add_video("queue-80", "Priority", "Bloomberg Television", score=80)
    db.add_video("eng-reviewed", "Reviewed story", "High Likes Channel", score=10, view_count=2000, like_count=100, upload_date=today)
    db.add_video("eng-review", "Fresh story", "Bloomberg Television", score=30, view_count=1000, like_count=90, upload_date=today)
    db.add_video("eng-submitted", "Bound story", "Bloomberg Television", score=40, view_count=800, like_count=None, upload_date=today)
    db.update_video_status("eng-submitted", "SUBMITTED_BOUND")
    db.add_video("error-policy", "Policy", "TEDx Talks", score=10)
    db.update_video_status("error-policy", "FAILED", error_msg="Channel Policy rejected")
    db.add_video("error-p0", "P0", "TEDx Talks", score=10, censor_tag="🔴 政治安全违禁")
    db.update_video_status("error-p0", "FAILED", error_msg="Censorship P0 rejected")
    db.set_engagement_reviewed("eng-reviewed", True)


def test_dal_filters_before_pagination_and_uses_stable_sort(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _seed(db)

    videos, total = db.get_paginated_videos(
        "waitlist", 1, 1, channel="TEDx Talks", sort="score_desc",
    )
    assert total == 4
    assert [video["youtube_id"] for video in videos] == ["wait-alpha"]

    videos, total = db.get_paginated_videos("waitlist", 1, 20, search="气候")
    assert total == 1
    assert videos[0]["youtube_id"] == "wait-alpha"

    videos, total = db.get_paginated_videos("waitlist", 1, 20, score_band="50_74")
    assert total == 1
    assert videos[0]["youtube_id"] == "wait-beta"

    videos, total = db.get_paginated_videos("queue", 1, 20, score_band="80_plus")
    assert total == 1
    assert videos[0]["youtube_id"] == "queue-80"

    videos, total = db.get_paginated_videos("waitlist", 1, 20, channel="TEDx Talks")
    assert total == 4
    assert [video["youtube_id"] for video in videos[:3]] == ["wait-source-latest", "wait-legacy-latest", "wait-alpha"]


def test_dal_error_categories_and_engagement_mark_are_state_isolated(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _seed(db)

    policy, policy_total = db.get_paginated_videos("error", 1, 20, error_type="channel_policy")
    assert policy_total == 1
    assert policy[0]["youtube_id"] == "error-policy"
    p0, p0_total = db.get_paginated_videos("error", 1, 20, error_type="censorship_p0")
    assert p0_total == 1
    assert p0[0]["youtube_id"] == "error-p0"

    unseen, unseen_total = db.get_paginated_videos("high_likes", 1, 20, engagement_window_days=3)
    assert unseen_total == 2
    assert "eng-reviewed" not in {video["youtube_id"] for video in unseen}
    assert db.get_tab_counts()["high_likes"] == 3
    all_rows, all_total = db.get_paginated_videos(
        "high_likes", 1, 20, engagement_window_days=3, include_processed=True, status="SUBMITTED_BOUND",
    )
    assert all_total == 1
    assert all_rows[0]["youtube_id"] == "eng-submitted"
    assert all_rows[0]["browser_processed"] == 0

    before = db.get_video_by_youtube_id("eng-submitted")
    assert db.set_engagement_reviewed("eng-submitted", True) is True
    after = db.get_video_by_youtube_id("eng-submitted")
    assert after["status"] == before["status"] == "SUBMITTED_BOUND"


def test_api_validates_filters_and_returns_filtered_pagination(tmp_path, monkeypatch):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _seed(db)
    monkeypatch.setattr(web_app, "db", db)
    client = TestClient(web_app.app)

    response = client.get("/api/videos", params={"tab": "waitlist", "search": "Markets", "size": 20})
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_count"] == 1
    assert payload["total_pages"] == 1
    assert payload["videos"][0]["youtube_id"] == "wait-beta"
    assert "Bloomberg Television" in payload["filter_options"]["channels"]

    response = client.get("/api/videos", params={"tab": "waitlist", "channel": "TEDx Talks", "size": 20})
    assert [video["youtube_id"] for video in response.json()["videos"][:3]] == ["wait-source-latest", "wait-legacy-latest", "wait-alpha"]

    assert client.get("/api/videos", params={"tab": "waitlist", "sort": "untrusted"}).status_code == 422
    response = client.get("/api/videos", params={"tab": "queue", "score_band": "80_plus"})
    assert response.status_code == 200
    assert response.json()["videos"][0]["youtube_id"] == "queue-80"

    response = client.post("/api/videos/eng-review/engagement-reviewed", json={"reviewed": True})
    assert response.status_code == 200
    assert db.get_video_by_youtube_id("eng-review")["status"] == "PENDING"


def test_dashboard_template_labels_source_dates_without_claiming_platform_upload():
    template = (Path(web_app.__file__).parent / "templates" / "index.html").read_text(encoding="utf-8")

    assert "sort: 'source_published_at_desc'" in template
    assert '<option value="80_plus">80 以上</option>' in template
    assert "来源发布：${sourcePublishAge" in template
    assert "上传：${uploadAge" not in template
