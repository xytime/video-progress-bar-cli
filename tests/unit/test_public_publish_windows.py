"""公开视频发布时间窗口测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-28 | Codex | 覆盖北京时间黄金发布窗口解析与窗口外平台入队等待 |
| 1.1.0 | 2026-07-29 | Codex | 示例窗口随默认策略整体前移 30 分钟 |
| 1.2.0 | 2026-07-29 | Codex | 覆盖中国大陆节假日、周末和补班日窗口选择 |
| 1.3.0 | 2026-07-31 | Codex | 更新休息日早窗为 07:30-11:00，并覆盖开始边界 |
| 1.4.0 | 2026-08-02 | Codex | 覆盖默认关闭发布时段时，任意时刻均可提交 |
| 1.5.0 | 2026-09-01 | Codex | 覆盖 NYSE 全日休市日不触发视频加工盘中守卫。 |
"""

from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from config.settings import Settings, settings
from video_processing.pipeline_manager import PipelineManager


def test_public_publish_window_uses_configured_timezone():
    previous_enabled = settings.enable_public_publish_windows
    previous_timezone = settings.public_publish_timezone
    previous_windows = settings.public_publish_windows
    settings.enable_public_publish_windows = True
    settings.public_publish_timezone = "Asia/Shanghai"
    settings.public_publish_windows = "07:00-08:00,19:00-20:40"
    try:
        assert settings.is_public_publish_window(datetime(2026, 7, 28, 19, 30, tzinfo=ZoneInfo("Asia/Shanghai")))
        assert not settings.is_public_publish_window(datetime(2026, 7, 28, 20, 41, tzinfo=ZoneInfo("Asia/Shanghai")))
    finally:
        settings.enable_public_publish_windows = previous_enabled
        settings.public_publish_timezone = previous_timezone
        settings.public_publish_windows = previous_windows


def test_public_publish_window_uses_holiday_schedule():
    previous_enabled = settings.enable_public_publish_windows
    previous_timezone = settings.public_publish_timezone
    previous_windows = settings.public_publish_windows
    previous_holiday_windows = settings.public_publish_holiday_windows
    previous_holidays = settings.china_public_holidays
    previous_workdays = settings.china_makeup_workdays
    settings.enable_public_publish_windows = True
    settings.public_publish_timezone = "Asia/Shanghai"
    settings.public_publish_windows = "07:00-08:00,19:00-20:40"
    settings.public_publish_holiday_windows = "07:30-11:00,19:00-21:30"
    settings.china_public_holidays = "2026-02-15..2026-02-23"
    settings.china_makeup_workdays = "2026-02-14"
    try:
        assert not settings.is_china_rest_day(date(2026, 2, 14))
        assert settings.is_china_rest_day(date(2026, 2, 16))
        assert settings.is_china_rest_day(date(2026, 8, 1))

        assert not settings.is_public_publish_window(datetime(2026, 2, 14, 9, 45, tzinfo=ZoneInfo("Asia/Shanghai")))
        assert not settings.is_public_publish_window(datetime(2026, 2, 16, 7, 29, tzinfo=ZoneInfo("Asia/Shanghai")))
        assert settings.is_public_publish_window(datetime(2026, 2, 16, 7, 30, tzinfo=ZoneInfo("Asia/Shanghai")))
        assert settings.is_public_publish_window(datetime(2026, 8, 1, 21, 0, tzinfo=ZoneInfo("Asia/Shanghai")))
    finally:
        settings.enable_public_publish_windows = previous_enabled
        settings.public_publish_timezone = previous_timezone
        settings.public_publish_windows = previous_windows
        settings.public_publish_holiday_windows = previous_holiday_windows
        settings.china_public_holidays = previous_holidays
        settings.china_makeup_workdays = previous_workdays


def test_public_publish_window_is_unrestricted_when_disabled():
    previous_enabled = settings.enable_public_publish_windows
    settings.enable_public_publish_windows = False
    try:
        assert settings.is_public_publish_window(datetime(2026, 8, 2, 3, 0, tzinfo=ZoneInfo("Asia/Shanghai")))
    finally:
        settings.enable_public_publish_windows = previous_enabled


def test_market_guard_uses_nyse_trading_day_not_weekday_only():
    guarded = Settings(enable_market_hours_guard=True)
    eastern = ZoneInfo("America/New_York")

    assert guarded.is_us_market_guard_window(
        datetime(2026, 7, 2, 12, 0, tzinfo=eastern)
    )
    assert not guarded.is_us_market_guard_window(
        datetime(2026, 7, 3, 12, 0, tzinfo=eastern)
    )
    assert not guarded.is_us_market_guard_window(
        datetime(2026, 4, 3, 12, 0, tzinfo=eastern)
    )


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
