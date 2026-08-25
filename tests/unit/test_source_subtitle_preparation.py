"""源字幕先行预检与后台预加工回归测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-31 | Codex | 覆盖 VTT 解析、下载前阻断、AUTO 预加工选择和真实微信补发日限额 |
| 1.1.0 | 2026-08-26 | Codex | 覆盖 YouTube bot 校验后的受限 Cookie 刷新与单次预检重试。 |
"""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

from config.settings import settings
from video_processing.db.database import PipelineDB
from video_processing.pipeline_manager import PipelineManager
from video_processing.utils.file_utils import read_webvtt_text


def _manager(tmp_path: Path) -> PipelineManager:
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager._OUT_DIR = tmp_path
    manager._ORIG_VIDEO_DIR = tmp_path / "original_video"
    manager._ORIG_VIDEO_DIR.mkdir()
    manager.send_telegram_msg = lambda *_args, **_kwargs: None
    return manager


def _add_candidate(db: PipelineDB, yid: str, *, source: str = "AUTO", score: int = 90) -> dict:
    assert db.add_video(yid, "Daily technology update", "channel-a", score=score, source=source)
    return db.get_video_by_youtube_id(yid)


def test_read_webvtt_text_ignores_header_timing_and_tags(tmp_path: Path):
    vtt = tmp_path / "source.en.vtt"
    vtt.write_text(
        "WEBVTT\n\n"
        "00:00:00.000 --> 00:00:02.000 align:start\n"
        "<c.green>Hello &amp; welcome</c>\n\n"
        "2\n00:00:02.000 --> 00:00:04.000\n"
        "to the update.\n",
        encoding="utf-8",
    )

    text = read_webvtt_text([vtt])

    assert "Hello & welcome" in text
    assert "to the update." in text
    assert "WEBVTT" not in text
    assert "-->" not in text


def test_missing_source_subtitle_runs_skip_download_only_and_blocks_video_download(tmp_path: Path, monkeypatch):
    manager = _manager(tmp_path)
    video = _add_candidate(manager.db, "source-preflight-missing")
    manager._run_tracked = MagicMock()
    monkeypatch.setattr(manager, "_check_censorship", MagicMock(return_value=False))

    manager._process_single_video(video)

    manager._run_tracked.assert_called_once()
    command = manager._run_tracked.call_args.args[0]
    assert "--skip-download" in command
    assert not any("bestvideo" in str(arg) for arg in command)
    stored = manager.db.get_video_by_youtube_id("source-preflight-missing")
    assert stored["status"] == "PENDING"
    assert stored["source_subtitle_status"] == "UNAVAILABLE"
    assert not list(tmp_path.glob("source-preflight-missing*.mp4"))


def test_source_subtitle_security_hit_blocks_before_video_download(tmp_path: Path, monkeypatch):
    manager = _manager(tmp_path)
    video = _add_candidate(manager.db, "source-preflight-blocked")
    (tmp_path / "source-preflight-blocked_source_subtitle.en.vtt").write_text(
        "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nToday we discuss falun gong.\n",
        encoding="utf-8",
    )
    manager._run_tracked = MagicMock()
    monkeypatch.setattr(settings, "enable_censorship_engine", True)
    monkeypatch.setattr(settings, "enable_channel_policy_filter", False)
    monkeypatch.setattr(settings, "enable_blacklist_tombstone", False)

    assert not manager._ensure_source_subtitle_preflight(video)

    manager._run_tracked.assert_not_called()
    assert manager.db.get_video_by_youtube_id("source-preflight-blocked")["status"] == "FAILED"
    assert not list(tmp_path.glob("source-preflight-blocked*.mp4"))


def test_bot_check_refreshes_cookie_and_retries_source_preflight_once(tmp_path: Path, monkeypatch):
    manager = _manager(tmp_path)
    video = _add_candidate(manager.db, "source-preflight-auth")
    calls = []

    def run_tracked(command, *_args, **_kwargs):
        calls.append(command)
        if any(str(part).endswith("refresh_yt_cookies.py") for part in command):
            return None
        if sum("--write-auto-subs" in call for call in calls) == 1:
            raise subprocess.CalledProcessError(1, command, stderr=b"Sign in to confirm you're not a bot")
        (tmp_path / "source-preflight-auth_source_subtitle.en.vtt").write_text(
            "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nA safe source transcript.\n",
            encoding="utf-8",
        )

    manager._run_tracked = run_tracked
    monkeypatch.setattr(settings, "enable_youtube_cookie_auto_refresh", True)
    monkeypatch.setattr(settings, "enable_censorship_engine", True)
    monkeypatch.setattr(manager, "_check_censorship", MagicMock(return_value=False))

    assert manager._ensure_source_subtitle_preflight(video) is True
    assert sum("--write-auto-subs" in call for call in calls) == 2
    assert any(any(str(part).endswith("refresh_yt_cookies.py") for part in call) for call in calls)


def test_source_subtitle_preflight_fails_closed_when_censorship_is_disabled(tmp_path: Path, monkeypatch):
    manager = _manager(tmp_path)
    video = _add_candidate(manager.db, "source-preflight-no-engine")
    (tmp_path / "source-preflight-no-engine_source_subtitle.en.vtt").write_text(
        "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nA harmless source transcript.\n",
        encoding="utf-8",
    )
    manager._run_tracked = MagicMock()
    monkeypatch.setattr(settings, "enable_censorship_engine", False)

    assert not manager._ensure_source_subtitle_preflight(video)

    manager._run_tracked.assert_not_called()
    stored = manager.db.get_video_by_youtube_id("source-preflight-no-engine")
    assert stored["status"] == "PENDING"
    assert stored["source_subtitle_status"] == "UNAVAILABLE"


def test_preparation_worker_claims_only_auto_candidates(tmp_path: Path, monkeypatch):
    manager = _manager(tmp_path)
    _add_candidate(manager.db, "auto-candidate", source="AUTO", score=90)
    _add_candidate(manager.db, "manual-candidate", source="MANUAL", score=99)
    _add_candidate(manager.db, "discovery-candidate", source="DISCOVERY", score=99)
    manager._process_single_video = MagicMock()
    monkeypatch.setattr(type(settings), "is_us_market_guard_window", lambda self: False)
    monkeypatch.setattr(type(settings), "is_public_publish_window", lambda self: False)

    assert manager.prepare_high_score_videos(limit=1) == 1

    manager._process_single_video.assert_called_once()
    candidate = manager._process_single_video.call_args.args[0]
    assert candidate["youtube_id"] == "auto-candidate"
    assert manager._process_single_video.call_args.kwargs == {"preparation_only": True}
    assert manager.db.get_video_by_youtube_id("manual-candidate")["status"] == "PENDING"
    assert manager.db.get_video_by_youtube_id("discovery-candidate")["status"] == "PENDING"


def test_deferred_wechat_daily_limit_is_persistent_across_claims(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    for yid in ("deferred-first", "deferred-second"):
        _add_candidate(db, yid)
        db.update_video_status(yid, "WECHAT_DEFERRED")

    first = db.claim_next_deferred_wechat_publication(daily_limit=1)
    second = db.claim_next_deferred_wechat_publication(daily_limit=1)

    assert first is not None
    assert second is None
    assert db.get_video_by_youtube_id("deferred-second")["status"] == "WECHAT_DEFERRED"
