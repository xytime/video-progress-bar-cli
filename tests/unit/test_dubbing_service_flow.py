"""人工选片一键端到端流程测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-29 | Codex | 覆盖人工配音任务的质检、发布状态和版本化封面选择 |
| 1.1.0 | 2026-07-30 | Codex | 缺少版本专属封面时拒绝普通话配音版投递 |
| 1.2.0 | 2026-07-31 | Codex | 覆盖平台闸门失败未提交时任务不误记审核中 |
| 1.3.0 | 2026-07-31 | Codex | 锁定普通话译制版投递标题和文案命名 |
| 1.4.0 | 2026-07-31 | Codex | 译制版封面必须具备非视频帧来源清单 |
| 1.5.0 | 2026-08-01 | Codex | 覆盖 TTS 时长失配后的自动短写重合成恢复 |
| 1.6.0 | 2026-08-03 | Codex | 译制版封面夹具携带无大面积遮罩版式来源清单 |
| 1.7.0 | 2026-09-02 | Codex | 覆盖配音抖音发布复用 UI 熔断、提交后未确认语义和禁止审核中盲重传。 |
| 1.8.0 | 2026-09-02 | Codex | 覆盖配音抖音先签发一次性浏览器凭据，并以同一尝试收口避免双计数。 |
| 1.8.1 | 2026-09-02 | Codex | 覆盖配音领取超时但浏览器未启动时恢复为人工显式确认入口，已启动尝试不自动恢复。 |
| 1.8.2 | 2026-09-02 | Codex | 覆盖本地投稿预检失败不会把配音任务卡在 PUBLISHING。 |
"""

import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from video_processing.core.cover_policy import compliant_cover_layout_policy
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


def test_synthesize_and_fit_rewrites_one_overlong_chunk_before_blocking(tmp_path, monkeypatch):
    from config.settings import settings
    import video_processing.dubbing.service as dubbing_service

    source = tmp_path / "source.wav"
    rewritten = tmp_path / "rewritten.wav"
    source.write_bytes(b"source")
    rewritten.write_bytes(b"rewritten")

    class _Client:
        def __init__(self, *args, **kwargs):
            self.calls = 0

        def synthesize(self, text, *, speed, cache_dir):
            self.calls += 1
            path = source if self.calls <= 2 else rewritten
            return SimpleNamespace(
                audio_path=path,
                subtitles=[],
                cache_key=f"key-{self.calls}",
                usage_characters=len(text),
            )

    durations = {source: 1300, rewritten: 1000}
    service = DubbingService.__new__(DubbingService)
    service.db = Mock()
    service._duration_ms = lambda path: durations[Path(path)]
    service._display_title = lambda job: "测试标题"
    service._fit_audio = lambda src, tempo, pad_ms, output: output
    service._actual_subtitles = lambda *args: [{"start_ms": 0, "end_ms": 1000, "text": "短句。"}]
    service._rewrite_chunk_for_timing = Mock(
        return_value={
            "source_start_ms": 0,
            "source_end_ms": 1000,
            "target_ms": 1000,
            "source_text": "Join me every day.",
            "zh_text": "每天看真相炸弹。",
        }
    )
    monkeypatch.setattr(settings, "minimax_tts_preferred_speed", 1.0)
    monkeypatch.setattr(settings, "minimax_tts_min_speed", 0.96)
    monkeypatch.setattr(settings, "minimax_tts_max_speed", 1.28)
    monkeypatch.setattr(dubbing_service, "MiniMaxTTSClient", _Client)

    plans = service._synthesize_and_fit(
        {"id": 42},
        [{
            "source_start_ms": 0,
            "source_end_ms": 1000,
            "target_ms": 1000,
            "source_text": "Join me every day.",
            "zh_text": "朋友们每天来和我一起看华尔街真相炸弹。",
        }],
        tmp_path,
    )

    service._rewrite_chunk_for_timing.assert_called_once()
    assert plans[0]["zh_text"] == "每天看真相炸弹。"
    assert plans[0]["alignment_strategy"] == "micro_tempo"


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
    for filename in ("title.txt", "copy.txt", "cover.jpg"):
        (tmp_path / filename).write_bytes(filename.encode("utf-8"))
    service.db.claim_dubbing_douyin_publication_launch.return_value = {
        "id": 91,
        "_douyin_launch_ticket_id": "dubbing-ticket-91",
        "_douyin_launch_token": "dubbing-token-91",
    }
    run = Mock(return_value=subprocess.CompletedProcess([], 6, stdout="", stderr="accepted"))
    monkeypatch.setattr(subprocess, "run", run)

    service._publish_one({"id": 42, "youtube_id": "video-id", "version": 1, "output_video_path": str(video)}, "douyin")

    service.db.complete_dubbing_douyin_publication_launch.assert_called_once_with(
        91,
        "UNDER_REVIEW",
        error_message="已提交，等待平台作品管理页确认可见。",
    )
    command = run.call_args.args[0]
    assert command[command.index("--douyin-launch-ticket") + 1] == "dubbing-ticket-91"
    assert command[command.index("--douyin-launch-token") + 1] == "dubbing-token-91"


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
    service._prepare_publish_one = Mock(return_value={"platform": "wechat"})
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


def test_dubbing_local_preflight_failure_restores_ready_before_any_douyin_ticket():
    """缺本地产物时必须在启动浏览器和领取 ticket 前回到可人工修复状态。"""
    service = DubbingService.__new__(DubbingService)
    service.db = Mock()
    service._require_latest_job = Mock(return_value={
        "id": 42,
        "state": "READY_TO_PUBLISH",
        "requested_platforms": '["douyin"]',
        "output_video_path": "",
    })
    service._normalize_platforms = Mock(return_value=["douyin"])
    service.db.get_platform_ui_failure_streaks.return_value = []
    service.db.get_dubbing_publications.return_value = []

    with pytest.raises(RuntimeError, match="本地投稿预检未通过"):
        service.publish("video-id", platforms=["douyin"], confirm=True)

    assert call(42, "PUBLISHING") not in service.db.update_dubbing_job.call_args_list
    service.db.update_dubbing_job.assert_called_once()
    update_args, update_kwargs = service.db.update_dubbing_job.call_args
    assert update_args == (42, "READY_TO_PUBLISH")
    assert "本地投稿预检未通过" in update_kwargs["error_message"]
    service.db.claim_dubbing_douyin_publication_launch.assert_not_called()


@pytest.mark.parametrize("stage", ["publish_pre_submit", "future_douyin_ui_stage"])
def test_dubbing_douyin_publish_guard_stops_before_job_state_or_uploader(stage, monkeypatch):
    """配音工作室的显式确认也不能绕过投稿页或未知 UI 熔断。"""
    from config.settings import settings

    service = DubbingService.__new__(DubbingService)
    service.db = Mock()
    service._require_latest_job = Mock(
        return_value={"id": 42, "state": "READY_TO_PUBLISH", "requested_platforms": "[\"douyin\"]"}
    )
    service._normalize_platforms = Mock(return_value=["douyin"])
    service._publish_one = Mock()
    service.db.get_platform_ui_failure_streaks.return_value = [{
        "platform": "douyin",
        "stage": stage,
        "consecutive_failures": 2,
        "active": 1,
    }]
    monkeypatch.setattr(settings, "douyin_ui_failure_recording_threshold", 2)

    with pytest.raises(RuntimeError, match="UI 阶段"):
        service.publish("video-id", platforms=["douyin"], confirm=True)

    service.db.update_dubbing_job.assert_not_called()
    service._publish_one.assert_not_called()


def test_dubbing_management_guard_allows_independently_gated_new_publish(monkeypatch):
    """单独管理页熔断不能阻断仍经投稿前闸门的人工配音新投递。"""
    from config.settings import settings

    service = DubbingService.__new__(DubbingService)
    service.db = Mock()
    service._require_latest_job = Mock(
        return_value={"id": 42, "state": "READY_TO_PUBLISH", "requested_platforms": "[\"douyin\"]"}
    )
    service._normalize_platforms = Mock(return_value=["douyin"])
    service._prepare_publish_one = Mock(return_value={"platform": "douyin"})
    service._publish_one = Mock()
    service.db.get_platform_ui_failure_streaks.return_value = [{
        "platform": "douyin",
        "stage": "management_verify",
        "consecutive_failures": 2,
        "active": 1,
    }]
    service.db.get_dubbing_publications.side_effect = [[], [{"platform": "douyin", "state": "RETRYABLE_FAILED"}]]
    service._job_view = Mock(return_value={"state": "READY_TO_PUBLISH"})
    monkeypatch.setattr(settings, "douyin_ui_failure_recording_threshold", 2)

    service.publish("video-id", platforms=["douyin"], confirm=True)

    service._publish_one.assert_called_once()
    service.db.update_dubbing_job.assert_any_call(42, "PUBLISHING")


@pytest.mark.parametrize("state", ["UPLOADING", "UNDER_REVIEW", "PUBLISHED", "UNCERTAIN", "BANNED"])
def test_dubbing_publish_never_resends_existing_non_retryable_platform_state(state):
    """已上传、审核、公开、未确认或封禁的配音平台记录不能被 --confirm 盲重传。"""
    service = DubbingService.__new__(DubbingService)
    service.db = Mock()
    service._require_latest_job = Mock(
        return_value={"id": 42, "state": "UNDER_REVIEW", "requested_platforms": "[\"douyin\"]"}
    )
    service._normalize_platforms = Mock(return_value=["douyin"])
    service._publish_one = Mock()
    service.db.get_platform_ui_failure_streaks.return_value = []
    service.db.get_dubbing_publications.return_value = [{"platform": "douyin", "state": state}]

    with pytest.raises(ValueError, match="禁止重传"):
        service.publish("video-id", platforms=["douyin"], confirm=True)

    service.db.update_dubbing_job.assert_not_called()
    service._publish_one.assert_not_called()


def test_dubbing_prelaunch_recovery_only_reopens_a_proven_unstarted_attempt(monkeypatch):
    """恢复必须来自 ticket 未启动的 DAL 证明，不能把普通 PUBLISHING 当作可重投。"""
    from config.settings import settings

    service = DubbingService.__new__(DubbingService)
    service.db = Mock()
    job = {"id": 42, "state": "PUBLISHING", "requested_platforms": '["douyin"]'}
    service.db.cancel_stale_dubbing_douyin_prelaunch_attempts.return_value = 1
    service.db.get_dubbing_publications.return_value = [{"platform": "douyin", "state": "CANCELED"}]
    service.db.get_dubbing_job.return_value = {**job, "state": "READY_TO_PUBLISH"}
    monkeypatch.setattr(settings, "douyin_prelaunch_ticket_recovery_ttl_seconds", 900)

    recovered = service._recover_stale_douyin_prelaunch_publish(job)

    assert recovered["state"] == "READY_TO_PUBLISH"
    service.db.cancel_stale_dubbing_douyin_prelaunch_attempts.assert_called_once_with(
        min_age_seconds=900,
        reason="人工配音投稿进程超过恢复等待期仍未启动浏览器；未发生平台提交。",
        job_id=42,
    )
    service.db.update_dubbing_job.assert_called_once_with(
        42,
        "READY_TO_PUBLISH",
        error_message="上次抖音领取在浏览器启动前失联，已安全取消；后续投稿仍需本次显式 --confirm。",
    )


@pytest.mark.parametrize(
    ("returncode", "expected_state"),
    [(3, "CANCELED"), (7, "UNCERTAIN")],
)
def test_dubbing_douyin_exit_codes_preserve_submission_boundary(
    tmp_path,
    monkeypatch,
    returncode,
    expected_state,
):
    """投稿前未提交与最终点击后未确认必须落入不同的不可混淆状态。"""
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
    for filename in ("title.txt", "copy.txt", "cover.jpg"):
        (tmp_path / filename).write_bytes(filename.encode("utf-8"))
    service.db.claim_dubbing_douyin_publication_launch.return_value = {
        "id": 93,
        "_douyin_launch_ticket_id": "dubbing-ticket-93",
        "_douyin_launch_token": "dubbing-token-93",
    }
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], returncode, stdout="", stderr="unconfirmed"),
    )

    service._publish_one(
        {"id": 42, "youtube_id": "video-id", "version": 1, "output_video_path": str(video)},
        "douyin",
    )

    service.db.complete_dubbing_douyin_publication_launch.assert_called_once_with(
        93,
        expected_state,
        error_message="unconfirmed",
    )


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
    (publish_dir / "cover_wechat_provenance.json").write_text(
        json.dumps({
            "cover_kind": "dedicated_generated_image",
            "uses_video_frame": False,
            "cover_filename": verified_cover.name,
            "cover_sha256": hashlib.sha256(verified_cover.read_bytes()).hexdigest(),
            "layout_policy": compliant_cover_layout_policy(),
        }),
        encoding="utf-8",
    )
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
