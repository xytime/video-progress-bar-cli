"""日更故障复现：真实临时账本及文件，全部外部发送使用本地适配器。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-06 | Codex | 覆盖序列化、QA 覆盖、通知恢复、未知状态、调度漂移与失败分类。 |
"""
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
import plistlib

import pytest
import requests

from scripts import notify_english_world_review as notifier
from scripts import run_english_world_daily as runner
from video_processing.db.database import PipelineDB
from video_processing.english_world.delivery_progress import ReviewDelivery
from video_processing.english_world.daily_schedule import calendar_intervals, validate_installed_schedule
from video_processing.study_cards import StudyCardContent
from video_processing.study_cards.qa_integrity import validate_audio_qa
from video_processing.study_cards.template_a import _normalise_word
from video_processing.telegram_delivery import TelegramDeliveryResult
from video_processing import telegram_delivery


def _package(tmp_path, policy="AUTO_POLICY"):
    db = PipelineDB(str(tmp_path / "output/pipeline.db"))
    paths = {}
    hashes = {}
    for field, digest_field in (
        ("mp4", "artifact"), ("manifest", "manifest"), ("title", "title"),
        ("copy", "copy"), ("cover", "cover"), ("cover_provenance", "cover_provenance"),
    ):
        path = tmp_path / field
        path.write_text(json.dumps({"source_provenance": {"youtube_id": "eF5tl9SVZhY"}}) if field == "manifest" else field)
        paths[field + "_path"] = str(path)
        hashes[digest_field + "_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    item = db.create_english_world_review_item(
        **paths, **hashes, title="测试", source_youtube_id="eF5tl9SVZhY", delivery_policy=policy,
    )
    return db, item


def _qa(tmp_path):
    paths = {key: tmp_path / key for key in ("mp4", "manifest", "timeline")}
    for path in paths.values():
        path.write_text("original")
    report = {"state": "PASS", "passed": True,
              **{key: str(path) for key, path in paths.items()},
              **{key + "_sha256": hashlib.sha256(path.read_bytes()).hexdigest()
                 for key, path in paths.items()}}
    report_path = tmp_path / "qa.json"
    report_path.write_text(json.dumps(report))
    return paths, report_path


def test_currency_and_typographic_apostrophe_share_model_and_render_contract():
    tokens = "Here's $2 and $250.".split()
    payload = {"headline_zh": "新闻", "headline_en": "News", "translation_zh": "金额",
               "english_text": "Here’s $2 and $250.", "vocabulary": [],
               "words": [{"text": token, "start": index, "end": index + 0.5}
                         for index, token in enumerate(tokens)]}
    content = StudyCardContent.from_mapping(payload)
    assert len(content.words) == 4
    assert _normalise_word("Here’s") == _normalise_word("Here's")
    payload["english_text"] = "Here’s and ."
    with pytest.raises(ValueError, match="序列化损坏"):
        StudyCardContent.from_mapping(payload)


@pytest.mark.parametrize("changed", ["mp4", "manifest", "timeline"])
def test_qa_rejects_same_path_changed_bytes(tmp_path, changed):
    paths, report = _qa(tmp_path)
    validate_audio_qa(report, mp4=paths["mp4"], manifest=paths["manifest"])
    paths[changed].write_text("modified")
    with pytest.raises(ValueError, match="指纹"):
        validate_audio_qa(report, mp4=paths["mp4"], manifest=paths["manifest"])


def test_legacy_pass_requires_fresh_qa(tmp_path):
    paths, report = _qa(tmp_path)
    payload = json.loads(report.read_text())
    del payload["timeline_sha256"]
    report.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="重新质检"):
        validate_audio_qa(report, mp4=paths["mp4"], manifest=paths["manifest"])


def test_delivery_resumes_only_unsent_steps_and_keeps_policy(tmp_path):
    db, item = _package(tmp_path)
    progress = ReviewDelivery(db, item["id"])
    accepted = TelegramDeliveryResult(state="ACCEPTED", message_id="1")
    progress.send("text", lambda: accepted)
    with pytest.raises(RuntimeError):
        progress.send("cover", lambda: TelegramDeliveryResult(state="NOT_SENT", error_kind="ConnectTimeout"))
    restored = db.get_english_world_review_by_artifact(item["artifact_sha256"])
    assert restored["delivery_policy"] == "AUTO_POLICY"
    progress = ReviewDelivery(PipelineDB(db.db_path), restored["id"])
    assert progress.send("text", lambda: pytest.fail("已接受步骤不得重发")).message_id == "1"
    assert progress.send("cover", lambda: accepted).state == "ACCEPTED"


@pytest.mark.parametrize("state", ["UNKNOWN", "IN_FLIGHT", "FAILED"])
def test_delivery_unknown_or_inflight_does_not_resend(tmp_path, state):
    db, item = _package(tmp_path)
    assert db.claim_english_world_delivery_stage(item["id"], "text")
    if state != "IN_FLIGHT":
        db.finish_english_world_delivery_stage(item["id"], "text", state=state)
    with pytest.raises(RuntimeError, match="禁止盲目重发"):
        ReviewDelivery(db, item["id"]).send("text", lambda: pytest.fail("不确定结果不得重发"))


def test_main_delivery_resumes_after_second_attachment_disconnect(tmp_path, monkeypatch):
    db, item = _package(tmp_path, policy="MANUAL")
    calls = []
    failures = [True]

    def send_document(**kwargs):
        name = kwargs["path"].name
        calls.append(name)
        if name == "mp4" and failures:
            failures.pop()
            return TelegramDeliveryResult(state="NOT_SENT", error_kind="ConnectTimeout")
        return TelegramDeliveryResult(state="ACCEPTED", message_id=str(len(calls)))

    monkeypatch.setattr(notifier, "PipelineDB", lambda: db)
    monkeypatch.setattr(notifier, "send_document", send_document)
    monkeypatch.setattr(notifier, "send_text", lambda **kw: TelegramDeliveryResult(state="ACCEPTED", message_id="100"))
    args = SimpleNamespace(manual_review_only=True, delivery_receipt=tmp_path / "receipt.json")
    with pytest.raises(RuntimeError):
        notifier._deliver_review(args, item)
    assert json.loads(args.delivery_receipt.read_text())["artifact_state"] == "QA_PASSED"
    assert notifier._deliver_review(args, db.get_english_world_review_item(item["id"])) == 0
    assert calls == ["cover", "mp4", "mp4", "manifest"]
    assert db.get_english_world_review_item(item["id"])["state"] == "READY_FOR_REVIEW"


def test_completion_notification_failure_preserves_submission_state(tmp_path, monkeypatch):
    db, item = _package(tmp_path)
    db.approve_english_world_submission(item["id"], authorization="AUTO_POLICY")
    claimed = db.claim_english_world_submission(item["id"], evidence_dir=str(tmp_path / "evidence"))
    # IN_FLIGHT 投稿必须只回报状态，不再次调用上传器。
    calls = []

    def send_text(**kwargs):
        calls.append(kwargs["text"])
        if len(calls) == 2:
            return TelegramDeliveryResult(state="NOT_SENT", error_kind="ConnectTimeout")
        return TelegramDeliveryResult(state="ACCEPTED", message_id=str(len(calls)))

    monkeypatch.setattr(notifier.settings, "enable_english_world_auto_publish", True)
    monkeypatch.setattr(notifier.settings, "wechat_publishing_paused", False)
    monkeypatch.setattr(notifier, "PipelineDB", lambda: db)
    monkeypatch.setattr(notifier, "send_text", send_text)
    monkeypatch.setattr(notifier, "send_document", lambda **kw: TelegramDeliveryResult(state="ACCEPTED", message_id="200"))
    args = SimpleNamespace(manual_review_only=False, delivery_receipt=tmp_path / "receipt.json")
    with pytest.raises(RuntimeError):
        notifier._deliver_review(args, claimed)
    receipt = json.loads(args.delivery_receipt.read_text())
    assert receipt["phase"] == "SUBMISSION_RECORDED"
    assert receipt["review_state"] == "SUBMITTING"
    assert notifier._deliver_review(args, claimed) == 0
    assert len(calls) == 3  # 已接受审计正文没有再发
    assert db.get_english_world_review_item(item["id"])["state"] == "SUBMITTING"


def test_schedule_drift_is_rejected(tmp_path):
    path = tmp_path / "schedule.plist"
    path.write_bytes(plistlib.dumps({"StartCalendarInterval": calendar_intervals()}))
    validate_installed_schedule(path)
    path.write_bytes(plistlib.dumps({"StartCalendarInterval": [{"Hour": 7, "Minute": 0}]}))
    with pytest.raises(ValueError, match="禁止自动补跑"):
        validate_installed_schedule(path)


def test_internal_failure_does_not_blacklist_source(tmp_path):
    (tmp_path / "run.delivery-request.json").write_text(json.dumps({
        "kind": "failure", "failure": "渲染失败", "rejected_youtube_ids": ["eF5tl9SVZhY"],
        "source_rejections": [{"youtube_id": "eF5tl9SVZhY", "kind": "internal_error"},
                              {"youtube_id": "3xP_CqKF_9I", "kind": "source_quality"}],
    }))
    assert runner._recent_rejected_youtube_ids(tmp_path) == ("3xP_CqKF_9I",)


def test_connect_retry_rewinds_attachments_but_read_timeout_never_retries(tmp_path, monkeypatch):
    path = tmp_path / "attachment"
    path.write_bytes(b"complete")
    calls = []

    def post(_url, **kwargs):
        calls.append(kwargs["files"]["document"][1].read())
        if len(calls) < 3:
            raise requests.ConnectTimeout()
        return "accepted"

    monkeypatch.setattr(telegram_delivery.requests, "post", post)
    monkeypatch.setattr(telegram_delivery.time, "sleep", lambda _: None)
    with path.open("rb") as stream:
        assert telegram_delivery._post_with_connect_retry("https://example.invalid", files={"document": ("x", stream)}) == "accepted"
    assert calls == [b"complete"] * 3
    assert telegram_delivery._transport_error(requests.ConnectTimeout())[0] == "NOT_SENT"
    assert telegram_delivery._transport_error(requests.ReadTimeout())[0] == "UNKNOWN"
    assert telegram_delivery._transport_error(requests.exceptions.SSLError())[0] == "UNKNOWN"


def _host_fixture(tmp_path):
    db, item = _package(tmp_path)
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    timeline = tmp_path / "timeline.json"
    timeline.write_text("{}")
    paths = {"mp4": Path(item["mp4_path"]), "manifest": Path(item["manifest_path"]), "timeline": timeline}
    qa = tmp_path / "qa.json"
    qa.write_text(json.dumps({"state": "PASS", "passed": True,
        **{key: str(path) for key, path in paths.items()},
        **{key + "_sha256": hashlib.sha256(path.read_bytes()).hexdigest() for key, path in paths.items()}}))
    request = log_dir / "run.delivery-request.json"
    request.write_text(json.dumps({"kind": "production", "title": "新闻",
        "mp4": item["mp4_path"], "manifest": item["manifest_path"], "audio_qa_report": str(qa)}))
    runtime = runner.RuntimePaths(project_root=tmp_path, codex_home=tmp_path, codex_bin=tmp_path / "codex",
        python_bin=tmp_path / "python", notifier_script=tmp_path / "notifier", log_dir=log_dir,
        lock_dir=tmp_path / "lock", coordinator_timeout_seconds=1)
    return db, item, runtime, request


def test_host_resumes_exact_auto_package_despite_source_protection(tmp_path, monkeypatch):
    from io import StringIO
    db, item, runtime, request = _host_fixture(tmp_path)
    calls = []
    monkeypatch.setattr(runner.subprocess, "run", lambda command, **kw: calls.append(command) or SimpleNamespace(returncode=0))
    assert runner._deliver_request_from_host(runtime, request, runtime.log_dir / "receipt.json", StringIO()) == (0, False)
    assert len(calls) == 1
    assert "--audio-qa-report" in calls[0]
    assert db.get_english_world_review_item(item["id"])["state"] == "READY_FOR_REVIEW"


def test_pending_scan_retains_paused_delivery_but_skips_completed_audit(tmp_path):
    _, _, runtime, request = _host_fixture(tmp_path)
    receipt = request.with_name("run.delivery.json")
    assert runner._pending_auto_delivery_request(runtime) == request
    receipt.write_text(json.dumps({"kind": "review_and_auto_submission", "status": "ACCEPTED"}))
    assert runner._pending_auto_delivery_request(runtime) is None
    receipt.write_text(json.dumps({"kind": "review_and_auto_submission", "status": "ACCEPTED", "submission_deferred": True}))
    assert runner._pending_auto_delivery_request(runtime) == request


def test_safe_connect_failure_is_recorded_in_legacy_notification_ledger(tmp_path, monkeypatch):
    db, _ = _package(tmp_path)
    monkeypatch.setattr(telegram_delivery, "_post_with_connect_retry", lambda *a, **kw: (_ for _ in ()).throw(requests.ConnectTimeout()))
    result = telegram_delivery.send_text(event_type="test", priority="P0", text="test", token="fake", chat_id="fake", db=db)
    assert result.state == "NOT_SENT"
    with db.get_connection() as conn:
        receipt = conn.execute("SELECT delivery_state, error_kind FROM telegram_notification_receipts").fetchone()
    assert tuple(receipt) == ("FAILED", "ConnectTimeout")
