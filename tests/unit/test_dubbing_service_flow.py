"""人工选片一键端到端流程测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-29 | Codex | 覆盖人工配音任务的质检、发布状态和版本化封面选择 |
| 1.1.0 | 2026-07-30 | Codex | 缺少版本专属封面时拒绝普通话配音版投递 |
| 1.2.0 | 2026-07-31 | Codex | 覆盖平台闸门失败未提交时任务不误记审核中 |
| 1.3.0 | 2026-07-31 | Codex | 锁定普通话译制版投递标题和文案命名 |
"""

import subprocess
from unittest.mock import Mock, call

import pytest

from video_processing.dubbing.service import DubbingService


def test_run_selected_auto_approves_machine_qa_before_explicit_publish():
    service = DubbingService.__new__(DubbingService)
    service.create = Mock(return_value={"state": "QA_REQUIRED"})
    service.approve = Mock(return_value={"state": "READY_TO_PUBLISH"})
    service.publish = Mock(return_value={"state": "UNDER_REVIEW"})

    result = service.run_selected("video-id", platforms=["wechat"], confirm=True)

    service.approve.assert_called_once_with("video-id", slice_index=0)
    service.publish.assert_called_once_with("video-id", slice_index=0, platforms=["wechat"], confirm=True)
    assert result["state"] == "UNDER_REVIEW"


def test_run_selected_expands_all_only_at_publish_time():
    service = DubbingService.__new__(DubbingService)
    service.create = Mock(return_value={"state": "READY_TO_PUBLISH"})
    service.approve = Mock()
    service.publish = Mock(return_value={"state": "UNDER_REVIEW"})

    service.run_selected("video-id", platforms=["all"], confirm=True)

    service.create.assert_called_once_with("video-id", slice_index=0, platforms=[], force_new_version=False)
    service.publish.assert_called_once_with("video-id", slice_index=0, platforms=["all"], confirm=True)


def test_source_date_stamp_uses_source_upload_date(monkeypatch):
    from config.settings import settings

    service = DubbingService.__new__(DubbingService)
    service.db = Mock()
    monkeypatch.setattr(settings, "enable_source_date_stamp", True)

    stamp = service._source_date_stamp({"youtube_id": "video-id", "slice_index": 0, "source_upload_date": "20260728"})

    assert stamp == "2026-07-28"
    service.db.get_video_by_youtube_id.assert_not_called()


def test_source_date_stamp_falls_back_to_parent_slice(monkeypatch):
    from config.settings import settings

    service = DubbingService.__new__(DubbingService)
    service.db = Mock()
    service.db.get_video_by_youtube_id.return_value = {"upload_date": "20260728"}
    monkeypatch.setattr(settings, "enable_source_date_stamp", True)

    stamp = service._source_date_stamp({"youtube_id": "video-id", "slice_index": 2, "source_upload_date": None})

    assert stamp == "2026-07-28"
    service.db.get_video_by_youtube_id.assert_called_once_with("video-id", 0)


def test_render_video_forwards_source_date_to_vertical_processor(tmp_path, monkeypatch):
    import video_processing.dubbing.service as dubbing_service

    captured = {}

    class _Processor:
        def __init__(self, *args, **kwargs):
            captured.update(kwargs)

        def _get_video_resolution(self):
            return 1080, 1920

        def _burn_subtitles(self, ass_path):
            assert ass_path.is_file()
            return tmp_path / "rendered.mp4"

    class _Db:
        def upsert_dubbing_artifact(self, *args, **kwargs):
            return None

    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    service = DubbingService.__new__(DubbingService)
    service.db = _Db()
    service._display_title = lambda job: "测试标题"
    service._source_date_stamp = lambda job: "2026-07-28"
    commands = []
    service._run = commands.append
    monkeypatch.setattr(dubbing_service, "VerticalCaptionProcessor", _Processor)

    service._render_video({"id": 7}, source, [], tmp_path / "narration.wav", workspace)

    assert captured["source_date"] == "2026-07-28"
    assert commands[-1][-1].endswith("dubbing_zh.mp4")


def test_publish_one_maps_platform_under_review_exit_code(tmp_path, monkeypatch):
    video = tmp_path / "dubbing.mp4"
    video.write_bytes(b"video")
    service = DubbingService.__new__(DubbingService)
    service.project_root = tmp_path
    service.db = Mock()
    service._variant_publish_assets = Mock(
        return_value=(
            tmp_path / "title.txt",
            tmp_path / "copy.txt",
            tmp_path / "cover.jpg",
            tmp_path / "category.txt",
            None,
        )
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 6, stdout="", stderr="accepted"),
    )

    service._publish_one({"id": 42, "youtube_id": "video-id", "version": 1, "output_video_path": str(video)}, "douyin")

    service.db.update_dubbing_publication.assert_called_once_with(
        42,
        "douyin",
        "UNDER_REVIEW",
        error_message="已提交，等待平台作品管理页确认可见。",
    )


def test_publish_one_maps_platform_banned_exit_code(tmp_path, monkeypatch):
    video = tmp_path / "dubbing.mp4"
    video.write_bytes(b"video")
    service = DubbingService.__new__(DubbingService)
    service.project_root = tmp_path
    service.db = Mock()
    service._variant_publish_assets = Mock(
        return_value=(
            tmp_path / "title.txt",
            tmp_path / "copy.txt",
            tmp_path / "cover.jpg",
            tmp_path / "category.txt",
            None,
        )
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 7, stdout="", stderr="banned"),
    )

    service._publish_one({"id": 42, "youtube_id": "video-id", "version": 1, "output_video_path": str(video)}, "kuaishou")

    service.db.update_dubbing_publication.assert_called_once_with(
        42,
        "kuaishou",
        "BANNED",
        error_message="banned",
    )


def test_publish_one_passes_versioned_wechat_evidence_dir_and_archives_log(tmp_path, monkeypatch):
    video = tmp_path / "dubbing.mp4"
    video.write_bytes(b"video")
    workspace = tmp_path / "workspace"
    service = DubbingService.__new__(DubbingService)
    service.project_root = tmp_path
    service.db = Mock()
    service._workspace = Mock(return_value=workspace)
    service._variant_publish_assets = Mock(
        return_value=(tmp_path / "title.txt", tmp_path / "copy.txt", tmp_path / "cover.jpg", tmp_path / "category.txt", None)
    )
    run = Mock(return_value=subprocess.CompletedProcess([], 6, stdout="accepted", stderr=""))
    monkeypatch.setattr(subprocess, "run", run)

    service._publish_one({"id": 42, "youtube_id": "video-id", "version": 1, "output_video_path": str(video)}, "wechat")

    command = run.call_args.args[0]
    assert "--evidence-dir" in command
    assert str(workspace / "publish" / "evidence" / "wechat") in command
    assert (workspace / "publish" / "wechat_uploader.log").is_file()


def test_publish_one_keeps_external_result_when_evidence_archiving_fails(tmp_path, monkeypatch):
    video = tmp_path / "dubbing.mp4"
    video.write_bytes(b"video")
    service = DubbingService.__new__(DubbingService)
    service.project_root = tmp_path
    service.db = Mock()
    service.db.upsert_dubbing_artifact.side_effect = OSError("disk full")
    service._workspace = Mock(return_value=tmp_path / "workspace")
    service._variant_publish_assets = Mock(
        return_value=(tmp_path / "title.txt", tmp_path / "copy.txt", tmp_path / "cover.jpg", tmp_path / "category.txt", None)
    )
    monkeypatch.setattr(subprocess, "run", Mock(return_value=subprocess.CompletedProcess([], 6, stdout="accepted", stderr="")))

    service._publish_one({"id": 42, "youtube_id": "video-id", "version": 1, "output_video_path": str(video)}, "wechat")

    service.db.update_dubbing_publication.assert_called_once_with(
        42,
        "wechat",
        "UNDER_REVIEW",
        error_message="已提交，等待平台作品管理页确认可见。",
    )


def test_publish_keeps_job_ready_when_platform_gate_fails():
    service = DubbingService.__new__(DubbingService)
    service.db = Mock()
    service._require_latest_job = Mock(
        return_value={"id": 42, "state": "READY_TO_PUBLISH", "requested_platforms": "[\"wechat\"]"}
    )
    service._normalize_platforms = Mock(return_value=["wechat"])
    service._publish_one = Mock()
    service.db.get_dubbing_publications.return_value = [
        {"platform": "wechat", "state": "RETRYABLE_FAILED", "last_error_message": "封面未验证"}
    ]
    service._job_view = Mock(return_value={"state": "READY_TO_PUBLISH"})

    result = service.publish("video-id", platforms=["wechat"], confirm=True)

    assert result["state"] == "READY_TO_PUBLISH"
    service.db.update_dubbing_job.assert_has_calls([
        call(42, "PUBLISHING"),
        call(42, "READY_TO_PUBLISH", error_message="平台投递未提交成功；请修正平台闸门失败后再重试。"),
    ])


def test_variant_publish_assets_prefers_verified_versioned_cover(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    (output / "video-id_title.txt").write_text("原片标题", encoding="utf-8")
    (output / "video-id_copy.txt").write_text("原片文案", encoding="utf-8")
    (output / "video-id_cover.jpg").write_bytes(b"fallback-cover")
    (output / "video-id_category.txt").write_text("财经", encoding="utf-8")
    workspace = tmp_path / "workspace"
    publish_dir = workspace / "publish"
    publish_dir.mkdir(parents=True)
    verified_cover = publish_dir / "cover_wechat.jpg"
    verified_cover.write_bytes(b"verified-cover")
    service = DubbingService.__new__(DubbingService)
    service.project_root = tmp_path

    title, copy, cover, _, _ = service._variant_publish_assets(
        {"youtube_id": "video-id", "source_title": "fallback"}, workspace
    )

    assert cover == verified_cover
    assert title.read_text(encoding="utf-8").strip() == "原片标题普通话译制"
    assert copy.read_text(encoding="utf-8").endswith("普通话译制版\n")


def test_variant_publish_assets_rejects_original_cover_fallback_for_dubbed_version(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    (output / "video-id_title.txt").write_text("原片标题", encoding="utf-8")
    (output / "video-id_copy.txt").write_text("原片文案", encoding="utf-8")
    (output / "video-id_cover.jpg").write_bytes(b"must-not-be-reused")
    (output / "video-id_category.txt").write_text("财经", encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    service = DubbingService.__new__(DubbingService)
    service.project_root = tmp_path

    with pytest.raises(RuntimeError, match="版本专属封面"):
        service._variant_publish_assets({"youtube_id": "video-id", "source_title": "fallback"}, workspace)
