"""Dashboard 频道控制（暂停/恢复）与生产漏斗 API 测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-09-20 | Gemini | 补充 /api/videos?funnel_stage=... 穿透参数校验与下钻接口测试。 |
| 1.0.0 | 2026-09-20 | Gemini | 初始创建：覆盖受管白名单列表聚合、频道暂停与恢复端点、多时间窗口漏斗统计 API。 |
"""

from unittest.mock import patch
from fastapi.testclient import TestClient

from video_processing.db.database import PipelineDB
from web import app as web_app


def test_list_channels_returns_approved_and_paused(tmp_path):
    test_db = PipelineDB(str(tmp_path / "pipeline.db"))
    test_db.add_channel("UC_1", "Channel 1", status="APPROVED")
    test_db.add_channel("UC_2", "Channel 2", status="PAUSED")
    test_db.add_channel("UC_3", "Channel 3", status="MANUAL_ONLY")

    with patch.object(web_app, "db", test_db):
        client = TestClient(web_app.app)
        res = client.get("/api/channels")
        assert res.status_code == 200
        data = res.json()
        assert data["total_approved"] == 1
        assert data["total_paused"] == 1
        assert data["total_managed"] == 2
        channels = data["channels"]
        ids = [c["channel_id"] for c in channels]
        assert "UC_1" in ids
        assert "UC_2" in ids
        assert "UC_3" not in ids


def test_channel_pause_and_resume_endpoints(tmp_path):
    test_db = PipelineDB(str(tmp_path / "pipeline.db"))
    test_db.add_channel("UC_TARGET", "Target Channel", status="APPROVED")

    with patch.object(web_app, "db", test_db):
        client = TestClient(web_app.app)
        origin_header = {"Origin": f"http://127.0.0.1:{web_app.settings.dashboard_port}"}

        # 1. 暂停频道
        res_pause = client.post("/api/channels/UC_TARGET/pause", headers=origin_header)
        assert res_pause.status_code == 200
        assert res_pause.json()["success"] is True
        assert res_pause.json()["status"] == "PAUSED"
        assert test_db.get_channel_by_id("UC_TARGET")["status"] == "PAUSED"

        # 2. 恢复频道
        res_resume = client.post("/api/channels/UC_TARGET/resume", headers=origin_header)
        assert res_resume.status_code == 200
        assert res_resume.json()["success"] is True
        assert res_resume.json()["status"] == "APPROVED"
        assert test_db.get_channel_by_id("UC_TARGET")["status"] == "APPROVED"

        # 3. 对不存在的频道暂停
        res_fail = client.post("/api/channels/UC_NONE/pause", headers=origin_header)
        assert res_fail.status_code == 200
        assert res_fail.json()["success"] is False


def test_channel_funnel_endpoint(tmp_path):
    test_db = PipelineDB(str(tmp_path / "pipeline.db"))
    cid = "UC_FUNNEL_API"
    test_db.add_channel(cid, "Funnel API Channel", status="APPROVED")
    test_db.add_video("vid_1", "Video 1", cid, score=80)
    test_db.update_video_status("vid_1", "PUBLISHED")

    with patch.object(web_app, "db", test_db):
        client = TestClient(web_app.app)

        # 7d 查询
        res_7d = client.get(f"/api/channels/{cid}/funnel?window=7d")
        assert res_7d.status_code == 200
        data_7d = res_7d.json()
        assert data_7d["success"] is True
        assert data_7d["window"] == "7d"
        assert data_7d["metrics"]["total_ingested"] == 1
        assert data_7d["metrics"]["qualified"] == 1
        assert data_7d["metrics"]["published"] == 1

        # 30d 查询
        res_30d = client.get(f"/api/channels/{cid}/funnel?window=30d")
        assert res_30d.status_code == 200
        assert res_30d.json()["window"] == "30d"

        # all 查询
        res_all = client.get(f"/api/channels/{cid}/funnel?window=all")
        assert res_all.status_code == 200
        assert res_all.json()["window"] == "all"


def test_global_funnel_endpoint(tmp_path):
    test_db = PipelineDB(str(tmp_path / "pipeline.db"))
    test_db.add_channel("UC_A", "Channel A", status="APPROVED")
    test_db.add_channel("UC_B", "Channel B", status="APPROVED")
    test_db.add_video("vid_a", "Video A", "UC_A", score=85)
    test_db.update_video_status("vid_a", "PUBLISHED")
    test_db.add_video("vid_b", "Video B", "UC_B", score=30)

    with patch.object(web_app, "db", test_db):
        client = TestClient(web_app.app)
        res = client.get("/api/funnel?window=all")
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["window"] == "all"
        assert data["metrics"]["total_ingested"] == 2
        assert data["metrics"]["qualified"] == 1
        assert data["metrics"]["published"] == 1
        assert data["metrics"]["qualification_rate"] == 50.0
        assert data["metrics"]["overall_conversion_rate"] == 50.0

        # 测试 24h 窗口
        res_24h = client.get("/api/funnel?window=24h")
        assert res_24h.status_code == 200
        assert res_24h.json()["window"] == "24h"

        # 测试 today_bj 窗口
        res_today = client.get("/api/funnel?window=today_bj")
        assert res_today.status_code == 200
        assert res_today.json()["window"] == "today_bj"


def test_get_videos_created_window_api(tmp_path):
    test_db = PipelineDB(str(tmp_path / "pipeline.db"))
    test_db.add_channel("UC_API", "API Channel", status="APPROVED")
    test_db.add_video("vid_err", "Error Video", "UC_API", score=60)
    test_db.update_video_status("vid_err", "FAILED", error_msg="policy reject")

    with patch.object(web_app, "db", test_db):
        client = TestClient(web_app.app)
        # 1. 正常入参
        res = client.get("/api/videos?tab=error&created_window=7d")
        assert res.status_code == 200
        data = res.json()
        assert "videos" in data
        assert data["total_count"] == 1

        # 2. 非法时间窗口应抛出 422
        res_bad = client.get("/api/videos?tab=error&created_window=invalid_win")
        assert res_bad.status_code == 422
        assert "unknown created window" in res_bad.text


def test_get_videos_funnel_stage_api(tmp_path):
    test_db = PipelineDB(str(tmp_path / "pipeline.db"))
    test_db.add_channel("UC_API2", "API Channel 2", status="APPROVED")
    test_db.add_video("vid_qual", "Qualified Video", "UC_API2", score=80)
    test_db.add_video("vid_low", "Low Score Video", "UC_API2", score=50)

    with patch.object(web_app, "db", test_db):
        client = TestClient(web_app.app)
        # 1. 正常入参 funnel_stage=qualified
        res = client.get("/api/videos?funnel_stage=qualified")
        assert res.status_code == 200
        data = res.json()
        assert data["total_count"] == 1
        assert data["videos"][0]["youtube_id"] == "vid_qual"

        # 2. 非法漏斗阶段应抛出 422
        res_bad = client.get("/api/videos?funnel_stage=invalid_stage_xyz")
        assert res_bad.status_code == 422
        assert "unknown funnel stage" in res_bad.text


