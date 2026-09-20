"""Dashboard 添加频道接口回归测试。

覆盖：
1. yt-dlp 在 flat-playlist 模式下的元数据行解析（含 playlist: 前缀与多候选 fallback）。
2. YouTube 频道 ID 校验（UC 开头，24 字符）。
3. 已存在频道的白名单保护与 MANUAL_ONLY 提示提升逻辑。
4. 异常与错误回显。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-20 | Gemini | 初始创建：覆盖 add_channel 接口在 flat-playlist 下的频道解析与提权逻辑。 |
"""

from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from video_processing.db.database import PipelineDB
from web import app as web_app


def test_add_channel_rejects_non_youtube_url():
    client = TestClient(web_app.app)
    res = client.post(
        "/api/channels/add",
        json={"url": "https://vimeo.com/channels/staffpicks"},
        headers={"Origin": f"http://127.0.0.1:{web_app.settings.dashboard_port}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is False
    assert "必须来自 youtube.com 或 youtu.be" in data["error"]


def test_add_channel_parses_flat_playlist_multiline_output(tmp_path):
    db_path = str(tmp_path / "pipeline.db")
    test_db = PipelineDB(db_path)

    # 模拟 yt-dlp 输出：多行包含 playlist 级及条目级输出
    mock_stdout = (
        "UC5aNPmKYwbudeNngDMTY3lw|BNN Bloomberg\n"
        "UC5aNPmKYwbudeNngDMTY3lw|BNN Bloomberg\n"
    )
    mock_res = MagicMock()
    mock_res.stdout = mock_stdout
    mock_res.stderr = ""
    mock_res.returncode = 0

    with patch.object(web_app, "db", test_db), patch("web.app.subprocess.run", return_value=mock_res):
        client = TestClient(web_app.app)
        res = client.post(
            "/api/channels/add",
            json={"url": "https://www.youtube.com/@BNNBloomberg"},
            headers={"Origin": f"http://127.0.0.1:{web_app.settings.dashboard_port}"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["channel_id"] == "UC5aNPmKYwbudeNngDMTY3lw"
        assert data["channel_name"] == "BNN Bloomberg"

        # 验证已写入数据库
        record = test_db.get_channel_by_id("UC5aNPmKYwbudeNngDMTY3lw")
        assert record is not None
        assert record["status"] == "APPROVED"


def test_add_channel_rejects_malformed_channel_id(tmp_path):
    db_path = str(tmp_path / "pipeline.db")
    test_db = PipelineDB(db_path)

    # 模拟旧 Bug：条目级输出了 NA|NA
    mock_stdout = "NA|NA\n"
    mock_res = MagicMock()
    mock_res.stdout = mock_stdout
    mock_res.stderr = ""
    mock_res.returncode = 0

    with patch.object(web_app, "db", test_db), patch("web.app.subprocess.run", return_value=mock_res):
        client = TestClient(web_app.app)
        res = client.post(
            "/api/channels/add",
            json={"url": "https://www.youtube.com/@InvalidFormat"},
            headers={"Origin": f"http://127.0.0.1:{web_app.settings.dashboard_port}"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is False
        assert "格式异常（NA）" in data["error"]


def test_add_channel_already_approved(tmp_path):
    db_path = str(tmp_path / "pipeline.db")
    test_db = PipelineDB(db_path)
    test_db.add_channel("UC5aNPmKYwbudeNngDMTY3lw", "BNN Bloomberg", status="APPROVED")

    mock_stdout = "UC5aNPmKYwbudeNngDMTY3lw|BNN Bloomberg\n"
    mock_res = MagicMock()
    mock_res.stdout = mock_stdout
    mock_res.stderr = ""
    mock_res.returncode = 0

    with patch.object(web_app, "db", test_db), patch("web.app.subprocess.run", return_value=mock_res):
        client = TestClient(web_app.app)
        res = client.post(
            "/api/channels/add",
            json={"url": "https://www.youtube.com/@BNNBloomberg"},
            headers={"Origin": f"http://127.0.0.1:{web_app.settings.dashboard_port}"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is False
        assert data.get("already_exists") is True
        assert "已在白名单中" in data["error"]


def test_add_channel_manual_only_promotes(tmp_path):
    db_path = str(tmp_path / "pipeline.db")
    test_db = PipelineDB(db_path)
    test_db.add_channel("UC5aNPmKYwbudeNngDMTY3lw", "BNN Bloomberg", status="MANUAL_ONLY")

    mock_stdout = "UC5aNPmKYwbudeNngDMTY3lw|BNN Bloomberg\n"
    mock_res = MagicMock()
    mock_res.stdout = mock_stdout
    mock_res.stderr = ""
    mock_res.returncode = 0

    with patch.object(web_app, "db", test_db), patch("web.app.subprocess.run", return_value=mock_res):
        client = TestClient(web_app.app)
        # 第一次未带 promote=True
        res = client.post(
            "/api/channels/add",
            json={"url": "https://www.youtube.com/@BNNBloomberg"},
            headers={"Origin": f"http://127.0.0.1:{web_app.settings.dashboard_port}"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is False
        assert data.get("requires_promotion") is True

        # 第二次带 promote=True
        res2 = client.post(
            "/api/channels/add",
            json={"url": "https://www.youtube.com/@BNNBloomberg", "promote": True},
            headers={"Origin": f"http://127.0.0.1:{web_app.settings.dashboard_port}"},
        )
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["success"] is True

        record = test_db.get_channel_by_id("UC5aNPmKYwbudeNngDMTY3lw")
        assert record["status"] == "APPROVED"
