"""真实字幕 CLI 与类型化失败交接的集成测试；合成 ASR，不加载模型或渲染。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| subtitle-manual-gate-v2 | 2026-11-02 | Codex | 真实 CLI 至 DAL 验证人工门控退出码、去重和自动领取阻断。 |
| 1.0.0 | 2026-10-27 | Codex | 验证质量失败携带离线旁证而不改错误、临时故障不诊断及 ASR 复用。 |
"""
import importlib
import json
from pathlib import Path
import time
import uuid

from click.testing import CliRunner
import pytest

from config.settings import settings
from video_processing.processors.caption_processor import AutoCaptionProcessor
from video_processing.utils import subtitle_audio_review
from video_processing.utils.subtitle_audio_review import _digest
from video_processing.utils.subtitle_failure_receipt import (
    SubtitleTranslationFailure, safe_failure, read_bound_receipt,
)


@pytest.mark.parametrize("category,code,exit_code,diagnosis_case", [
    ("quality", "subtitle_quality_NUMBER_AMOUNT_MISSING", 78, "normal"),
    ("network", "connection", 75, "normal"),
    ("quality", "subtitle_quality_NUMBER_AMOUNT_MISSING", 78, "unexpected_exception"),
    ("quality", "subtitle_quality_NUMBER_AMOUNT_MISSING", 78, "non_english"),
])
def test_real_cli_preserves_typed_error_evidence_and_asr_checkpoint(
        tmp_path, monkeypatch, category, code, exit_code, diagnosis_case):
    module = importlib.import_module("cli.commands.auto_caption")
    source, path, progress = tmp_path / "source.mp4", tmp_path / "failure.json", tmp_path / "progress.json"
    source.write_bytes(b"synthetic-media")
    source_hash = _digest(source)
    # 缺少本地 medium 的真实诊断分支，必须保持原质量错误而不启动下载。
    monkeypatch.setattr(settings, "source_audio_model_path", tmp_path / "absent-models" / "base.pt")
    if diagnosis_case != "normal":
        def unexpected(*args, **kwargs):
            if diagnosis_case == "unexpected_exception":
                raise RuntimeError("PRIVATE diagnostic error body")
            pytest.fail("non-English ASR must not be reviewed with forced English")
        monkeypatch.setattr(subtitle_audio_review, "review_failed_segments", unexpected)
    calls = []
    class SyntheticFailureCaption(AutoCaptionProcessor):
        def _source_duration(self):
            return 10.

        def _extract_audio(self):
            calls.append("audio")
            audio = self.input_path.with_suffix(".wav")
            audio.write_bytes(b"synthetic-audio")
            return audio

        def _load_model(self):
            calls.append("model")

        def _transcribe_audio(self, path):
            calls.append("asr")
            self.detected_lang = "ja" if diagnosis_case == "non_english" else "en"
            return [dict(id=0, start=0., end=1., text="Oil is $115.", avg_logprob=-.1)]

        def _translate_segments(self, segments):
            calls.append("translation")
            raise SubtitleTranslationFailure([safe_failure("codex", code, category=category,
                quality_details=[dict(source_id=0, segment_number=1, code="NUMBER_AMOUNT_MISSING",
                                     source_signal="$115", translation_signal="amount_not_in_segment")])])

        def _generate_ass_file(self, segments):
            pytest.fail("failed translation reached subtitle layout")

        def _burn_subtitles(self, path):
            pytest.fail("failed translation reached renderer")

    monkeypatch.setattr(module, "AutoCaptionProcessor", SyntheticFailureCaption)
    attempt, started = uuid.uuid4().hex, time.time()
    arguments = [str(source), "--subtitle-receipt", str(path), "--subtitle-attempt-id", attempt,
                 "--progress-file", str(progress), "--output", str(tmp_path / "output.mp4")]
    result = CliRunner().invoke(module.auto_caption, arguments)
    assert result.exit_code == exit_code, result.output
    assert "PRIVATE" not in result.output
    receipt = read_bound_receipt(path, attempt_id=attempt, input_path=source,
                                input_sha256=source_hash, started_at=started)
    assert receipt and receipt["category"] == category and receipt["code"] == code
    assert receipt["quality_details"][0]["source_id"] == 0
    asr = next(tmp_path.glob(".caption-checkpoints/*/asr.json"))
    original_asr = asr.read_bytes()
    assert not list(tmp_path.glob(".caption-checkpoints/*/translation.json"))
    assert not (tmp_path / "output.mp4").exists() and _digest(source) == source_hash
    assert calls == ["audio", "model", "asr", "translation"]
    if category == "quality" and diagnosis_case == "normal":
        evidence = Path(receipt["evidence_path"])
        assert receipt["evidence_sha256"] == _digest(evidence)
        data = json.loads(evidence.read_text())
        assert data["status"] == "unavailable" and data["reason_code"] == "local_medium_missing"
        assert data["identity"]["source_sha256"] == source_hash
        assert data["identity"]["target_source_ids"] == [0]
        assert json.loads(progress.read_text())["stage"] == "SUBTITLE_DIAGNOSING"
    else:
        assert receipt["evidence_path"] == receipt["evidence_sha256"] == ""
        assert not list(tmp_path.glob(".caption-checkpoints/*/diagnostics/**/receipt.json"))
        stage = "SUBTITLE_DIAGNOSING" if diagnosis_case == "unexpected_exception" else "TRANSLATING"
        assert json.loads(progress.read_text())["stage"] == stage
    # 第二次仍在原翻译位置失败；ASR 和原文时间完整保留。
    again = uuid.uuid4().hex
    arguments[arguments.index("--subtitle-attempt-id") + 1] = again
    result = CliRunner().invoke(module.auto_caption, arguments)
    assert result.exit_code == exit_code
    assert calls == ["audio", "model", "asr", "translation", "translation"]
    assert asr.read_bytes() == original_asr
    assert json.loads(progress.read_text())["reused_steps"] == ["asr"]
    assert json.loads(path.read_text())["attempt_id"] == again


@pytest.mark.parametrize('gate', ['native', 'narrow', 'frame'])
def test_manual_caption_gate_cli_to_real_dal_is_not_retryable(tmp_path, monkeypatch, gate):
    import subprocess
    from video_processing.processors import native_caption_router, burned_caption_repair
    from video_processing.utils.subtitle_failure_receipt import SubtitleReviewRequired
    from video_processing.pipeline_manager import PipelineManager
    from video_processing.core.wechat_request_guard import WeChatRequestGuard
    module = importlib.import_module('cli.commands.auto_caption')
    source = tmp_path / 'source.mp4'
    source.write_bytes(b'synthetic-media')
    path, attempt, started = tmp_path / 'review.json', uuid.uuid4().hex, time.time()

    class ReviewCaption(AutoCaptionProcessor):
        def process(self):
            self.preserve_source_chinese = gate == 'native'
            return super().process()

        def _source_duration(self):
            return 10.

        def _extract_audio(self):
            return None

        def _generate_ass_file(self, segments):
            if gate == 'narrow':
                return burned_caption_repair.prepare_source(self.input_path, segments)
            return burned_caption_repair._classify(
                [[dict(text='unrelated words', confidence=.5, box=[.1,.7,.8,.74])]],
                [dict(text='Bonds are stable.', start=0., end=1.)], 25)

        def _burn_subtitles(self, path):
            pytest.fail('manual review reached renderer')

    def route(*args, **kwargs):
        raise native_caption_router.NativeCaptionReviewRequired(
            '[NativeCaptionReview] SAMPLE_SEMANTIC_BUDGET_EXCEEDED')

    monkeypatch.setattr(module, 'AutoCaptionProcessor', ReviewCaption)
    monkeypatch.setattr(native_caption_router, 'route', route)
    monkeypatch.setattr(burned_caption_repair, '_probe', lambda source: (500, 1000, 25, 10))
    # 使用真实 process、CLI 和 DAL，只替换模型、路由及媒体探测边界。
    result = CliRunner().invoke(module.auto_caption, [str(source), '--target-lang', 'en',
        '--subtitle-receipt', str(path), '--subtitle-attempt-id', attempt,
        '--output', str(tmp_path / 'output.mp4')])
    assert result.exit_code == 78, result.output
    assert 'Unexpected error' not in result.output
    receipt = read_bound_receipt(path, attempt_id=attempt, input_path=source,
        input_sha256=_digest(source), started_at=started)
    assert receipt and receipt['category'] == 'review'
    manager = PipelineManager(str(tmp_path / 'pipeline.db'))
    manager._OUT_DIR = tmp_path
    manager.db.add_video('review-test', 'test', 'channel', score=90)
    manager.db.update_video_status('review-test', 'TRANSCRIBING')
    manager.send_telegram_msg = lambda message: None
    kwargs = dict(slice_index=0, receipt_path=path, attempt_id=attempt, input_path=source,
                  input_sha256=_digest(source), started_at=started)
    error = subprocess.CalledProcessError(result.exit_code, ['auto-caption'])
    assert manager._consume_subtitle_failure('review-test', 'test', error, **kwargs)
    assert manager._consume_subtitle_failure('review-test', 'test', error, **kwargs)
    video = manager.db.get_video_by_youtube_id('review-test')
    assert video['error_msg'].startswith('SUBTITLE_NEEDS_REPAIR:')
    assert manager.db.subtitle_recovery_blocker(video['id'])['state'] == 'NEEDS_REPAIR'
    assert not manager.db.claim_video_for_processing('review-test')
    assert manager.db.get_high_score_pending_videos(min_score=75) == []
    with manager.db.get_connection() as c:
        assert c.execute('SELECT count(*) FROM publishing_failure_events WHERE video_id=?',
                         (video['id'],)).fetchone()[0] == 1
    assert not (tmp_path / 'output.mp4').exists()
