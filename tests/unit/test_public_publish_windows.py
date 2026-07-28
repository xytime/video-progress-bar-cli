"""公开视频发布时间窗口测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-28 | Codex | 覆盖北京时间黄金发布窗口解析与窗口外平台入队等待 |
"""

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from config.settings import settings
from video_processing.pipeline_manager import PipelineManager


def test_public_publish_window_uses_configured_timezone():
    previous_enabled = settings.enable_public_publish_windows
    previous_timezone = settings.public_publish_timezone
    previous_windows = settings.public_publish_windows
    settings.enable_public_publish_windows = True
    settings.public_publish_timezone = "Asia/Shanghai"
    settings.public_publish_windows = "07:30-08:30,19:30-21:10"
    try:
        assert settings.is_public_publish_window(datetime(2026, 7, 28, 20, 0, tzinfo=ZoneInfo("Asia/Shanghai")))
        assert not settings.is_public_publish_window(datetime(2026, 7, 28, 21, 11, tzinfo=ZoneInfo("Asia/Shanghai")))
    finally:
        settings.enable_public_publish_windows = previous_enabled
        settings.public_publish_timezone = previous_timezone
        settings.public_publish_windows = previous_windows


def test_kuaishou_new_video_queues_without_upload_outside_publish_window(tmp_path: Path, monkeypatch):
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager._OUT_DIR = tmp_path
    (tmp_path / "video-id_vertical.mp4").write_bytes(b"video")
    manager.db = MagicMock()
    manager.db.is_blacklisted.return_value = False
    manager.db.create_kuaishou_publication.return_value = {
        "id": 7,
        "youtube_id": "video-id",
        "slice_index": 0,
        "state": "QUEUED",
    }
    manager._run_tracked = MagicMock()
    monkeypatch.setattr(PipelineManager, "_is_public_publish_window", lambda self, platform, yid="", slice_index=0: False)

    previous_enabled = settings.enable_kuaishou_browser_publishing
    settings.enable_kuaishou_browser_publishing = True
    try:
        assert manager._queue_and_publish_new_kuaishou_video("video-id", 0)
    finally:
        settings.enable_kuaishou_browser_publishing = previous_enabled

    manager.db.create_kuaishou_publication.assert_called_once()
    manager.db.claim_kuaishou_publication.assert_not_called()
    manager._run_tracked.assert_not_called()
