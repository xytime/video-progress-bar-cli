"""独立完整文案、缓存与临时排队合同。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-22 | Codex | 覆盖零 API 依赖、校验后缓存、限流、锁竞争与投稿保护。 |
"""

import fcntl
import json
import subprocess
import time

import pytest

from config.settings import settings
from video_processing.utils import agy_copy_service as service


def _raw():
    return dict(short_title="让学习充满乐趣", display_title="让孩子在探索中感受学习乐趣",
                hook_subtitle="在探索中学习", wechat_copy="视频讨论如何让学习充满乐趣。",
                category="教育", content_hints=["education"], content_label="")


def _call(tmp_path, **overrides):
    args = dict(schema={"type": "object"}, model="test", command="agy", timeout_sec=2,
                quota_cooldown_sec=21600, cache_dir=tmp_path, validate=lambda raw: raw)
    args.update(overrides)
    return service.generate_cached_agy_copy("source", **args)


def test_validated_cache_and_input_identity(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(service, "run_agy_structured", lambda *a, **k: calls.append(k) or _raw())
    assert _call(tmp_path) == _call(tmp_path)
    assert len(calls) == 1
    _call(tmp_path, model="different")
    assert len(calls) == 2
    assert calls[0]["timeout_sec"] == 2
    assert "GEMINI_API_KEY" not in calls[0]["environment"]


def test_invalid_output_not_cached_and_cache_revalidated(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "run_agy_structured", lambda *a, **k: _raw())
    def reject(raw):
        raise ValueError("quality rejected")
    with pytest.raises(ValueError, match="quality rejected"):
        _call(tmp_path, validate=reject)
    assert list(tmp_path.glob("*.json")) == []
    _call(tmp_path)
    with pytest.raises(ValueError, match="quality rejected"):
        _call(tmp_path, validate=reject)


@pytest.mark.parametrize("error,reason,delay", [
    ("agy exit 1: rate limit", "quota", 21600),
    ("agy timed out after 2s", "unavailable", 300),
    ("agy command not found", "unavailable", 300),
])
def test_failure_cools_down_without_repeat_requests(tmp_path, monkeypatch, error, reason, delay):
    calls = []
    def fail(*a, **k):
        calls.append(1)
        raise service.AgyProviderError(error)
    monkeypatch.setattr(service, "run_agy_structured", fail)
    with pytest.raises(service.CopyProviderDeferred) as first:
        _call(tmp_path)
    assert first.value.reason == reason
    assert first.value.notify
    assert abs(first.value.until - time.time() - delay) < 2
    with pytest.raises(service.CopyProviderDeferred) as second:
        _call(tmp_path)
    assert not second.value.notify
    assert second.value.reason == "cooldown"
    assert len(calls) == 1
    (tmp_path / "cooldown.json").write_text(json.dumps({"until": 0}))
    with pytest.raises(service.CopyProviderDeferred):
        _call(tmp_path)
    assert len(calls) == 2


def test_nonblocking_single_concurrency(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(service, "run_agy_structured", lambda *a, **k: calls.append(1))
    with (tmp_path / "provider.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(service.CopyProviderDeferred, match="reason=busy"):
            _call(tmp_path)
    assert calls == []


def test_app_environment_excludes_business_credentials(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "not-a-real-key")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "not-a-real-token")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "not-a-real-key")
    monkeypatch.setenv("HTTPS_PROXY", "http://localhost:1234")
    env = settings.agy_app_environment()
    assert "GEMINI_API_KEY" not in env
    assert "TELEGRAM_BOT_TOKEN" not in env
    assert "DEEPSEEK_API_KEY" not in env
    assert env["HTTPS_PROXY"] == "http://localhost:1234"


def test_full_copy_works_without_api_or_fallback(tmp_path, monkeypatch):
    import scripts.copywriter as copywriter
    monkeypatch.setattr(settings, "copywriter_content_provider", "agy")
    monkeypatch.setattr(settings, "gemini_api_key", None)
    monkeypatch.setattr(type(settings), "default_output_dir", property(lambda _: tmp_path))
    calls = []
    monkeypatch.setattr(service, "run_agy_structured", lambda *a, **k: calls.append(k) or _raw())
    def forbidden(*a, **k):
        pytest.fail("AGY must not require a legacy API/fallback/title candidate")
    monkeypatch.setattr(copywriter, "_translate_fallback", forbidden)
    monkeypatch.setattr(copywriter, "_title_provider_candidates", forbidden)
    report = tmp_path / "quality.json"
    for _ in range(2):
        result = copywriter.generate_wechat_content("让学习充满乐趣", "视频讨论如何让学习充满乐趣。", audit_path=report)
        assert result["copy"] == _raw()["wechat_copy"]
    assert len(calls) == 1
    assert "wechat_copy" in calls[0]["schema"]["properties"]
    assert "agy:" in report.read_text()


@pytest.mark.parametrize("raw", [{"short_title": "只有标题"}, {**_raw(), "wechat_copy": "This is English only."}])
def test_full_copy_rejects_incomplete_or_english_response(tmp_path, monkeypatch, raw):
    import scripts.copywriter as copywriter
    monkeypatch.setattr(settings, "copywriter_content_provider", "agy")
    monkeypatch.setattr(type(settings), "default_output_dir", property(lambda _: tmp_path))
    monkeypatch.setattr(service, "run_agy_structured", lambda *a, **k: raw)
    with pytest.raises(ValueError):
        copywriter.generate_wechat_content("让学习充满乐趣", "视频讨论如何让学习充满乐趣。")
    assert list((tmp_path / "agy_copy_cache").glob("*.json")) == []


def test_cli_deferred_protocol_has_no_publishable_checkpoint(tmp_path, monkeypatch, capsys):
    import runpy
    import sys
    import scripts.copywriter as copywriter
    monkeypatch.setattr(settings, "copywriter_content_provider", "agy")
    monkeypatch.setattr(type(settings), "default_output_dir", property(lambda _: tmp_path))
    def unavailable(*a, **k):
        raise service.AgyProviderError("agy exit 1: rate limit")
    monkeypatch.setattr(service, "run_agy_structured", unavailable)
    monkeypatch.setattr(sys, "argv", ["copywriter.py", "--youtube-id", "not-submitted",
                                     "--title", "让学习充满乐趣", "--output-dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(copywriter.__file__, run_name="__main__")
    assert exc.value.code == 75
    assert "COPY_PROVIDER_DEFERRED until=" in capsys.readouterr().err
    assert not (tmp_path / "not-submitted_copy.txt").exists()
    assert not (tmp_path / "not-submitted_label.txt").exists()
    assert json.loads((tmp_path / "not-submitted_copy_quality.json").read_text())["events"][0]["status"] == "deferred"


def _manager(tmp_path):
    from video_processing.pipeline_manager import PipelineManager
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager._OUT_DIR = tmp_path
    manager.db.add_video("copy-test", "让学习充满乐趣", "test-channel", score=80)
    manager.db.update_video_status("copy-test", "COPYWRITING")
    return manager


def test_deferred_queue_excludes_claim_until_due(tmp_path):
    manager = _manager(tmp_path)
    messages = []
    manager.send_telegram_msg = messages.append
    error = subprocess.CalledProcessError(75, ["copywriter.py"], stderr=str(
        service.CopyProviderDeferred(int(time.time()) + 3600, "quota", True)))
    assert manager._defer_copy_provider_failure("copy-test", "title", error)
    row = manager.db.get_video_by_youtube_id("copy-test")
    assert (row["status"], row["retry_count"]) == ("PENDING", 0)
    assert not manager.db.claim_video_for_processing("copy-test")
    assert manager.db.get_high_score_pending_videos() == []
    assert manager.db.get_high_score_preparation_candidates() == []
    assert len(messages) == 1
    with manager.db.get_connection() as conn:
        conn.execute("UPDATE copywriter_deferred SET next_attempt_at = datetime('now', '-1 second')")
        conn.commit()
    assert manager.db.get_high_score_pending_videos()[0]["youtube_id"] == "copy-test"
    assert manager.db.claim_video_for_processing("copy-test")


@pytest.mark.parametrize("protection", ["ledger", "evidence", "wrong_status", "wrong_exit"])
def test_defer_never_requeues_submitted_or_unrelated_failure(tmp_path, protection):
    manager = _manager(tmp_path)
    if protection == "ledger":
        manager.db.record_wechat_publication_confirmation(
            "copy-test", state="SUBMITTED_BOUND", platform_post_id="export/protected", evidence_path="receipt",
        )
        manager.db.update_video_status("copy-test", "COPYWRITING")  # 即使旧状态漂移，账本优先
    elif protection == "evidence":
        manager._wechat_submission_evidence_paths = lambda _: [tmp_path / "receipt"]
    elif protection == "wrong_status":
        manager.db.update_video_status("copy-test", "PUBLISHED")
    error = subprocess.CalledProcessError(1 if protection == "wrong_exit" else 75, [], stderr=str(
        service.CopyProviderDeferred(int(time.time()) + 3600, "quota", True)))
    manager.send_telegram_msg = lambda _: pytest.fail("must not send queued notice")
    assert not manager._defer_copy_provider_failure("copy-test", "title", error)
    assert manager.db.get_video_by_youtube_id("copy-test")["status"] != "PENDING"
