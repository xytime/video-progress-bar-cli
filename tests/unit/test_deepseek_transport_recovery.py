"""响应读取中断须交回现有供应商降级，不能丢失审计结束记录。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-01 | Codex | 复现真实IncompleteRead，验证网络分类、响应关闭、降级与实际DAL审计。 |
"""
import http.client
import json
import ssl
import urllib.error
from types import SimpleNamespace

import pytest

from video_processing.utils import deepseek_translation as provider
from video_processing.utils.translation_model_pool import classify_error


class BrokenResponse:
    def __init__(self, error):
        self.error = error
        self.closed = False

    def __enter__(self):
        return self

    def read(self):
        raise self.error

    def __exit__(self, *_args):
        self.closed = True


@pytest.mark.parametrize('vocab', [False, True])
@pytest.mark.parametrize('error,category', [
    (http.client.IncompleteRead(b'private-response-body'), 'network'),
    (http.client.BadStatusLine('private-response-body'), 'network'),
    (http.client.RemoteDisconnected('private-response-body'), 'network'),
    (ConnectionResetError('private-response-body'), 'network'),
    (ssl.SSLEOFError('private-response-body'), 'network'),
    (TimeoutError('private-response-body'), 'network'),
    (urllib.error.URLError('private-response-body'), 'network'),
    (UnicodeDecodeError('utf8', b'\xff', 0, 1, 'private-response-body'), 'invalid_response'),
    (json.JSONDecodeError('private-response-body', 'private-response-body', 0), 'invalid_response'),
    (urllib.error.HTTPError('https://private-response-body', 429, 'private-response-body', {}, None), 'rate_limit'),
    (urllib.error.HTTPError('https://private-response-body', 401, 'private-response-body', {}, None), 'auth_or_permission'),
    (urllib.error.HTTPError('https://private-response-body', 402, 'private-response-body', {}, None), 'billing'),
    (urllib.error.HTTPError('https://private-response-body', 503, 'private-response-body', {}, None), 'network'),
])
def test_broken_read_is_bounded_sanitized_and_classified(monkeypatch, caplog, vocab, error, category):
    response = BrokenResponse(error)
    calls = []

    def open_response(request, *, timeout):
        calls.append(timeout)
        return response

    monkeypatch.setattr(provider.urllib.request, 'urlopen', open_response)
    settings = SimpleNamespace(deepseek_api_key='offline-test', deepseek_model='offline-test')
    errors = []
    texts = ['Bonds are stable.'] * 26
    result = (provider.translate_batch_with_vocab_deepseek(texts, settings_obj=settings, error_out=errors)
              if vocab else provider.translate_batch_deepseek(texts, settings_obj=settings))
    assert result is None and len(calls) == 1 and response.closed
    assert 0 < calls[0] <= 90
    assert 'private-response-body' not in caplog.text
    message = errors[0] if vocab else caplog.records[-1].getMessage()
    assert classify_error(message) == category


@pytest.mark.parametrize('vocab', [False, True])
def test_programming_errors_still_propagate(monkeypatch, vocab):
    response = BrokenResponse(ValueError('implementation-error'))
    monkeypatch.setattr(provider.urllib.request, 'urlopen', lambda *args, **kwargs: response)
    settings = SimpleNamespace(deepseek_api_key='offline-test')
    translate = provider.translate_batch_with_vocab_deepseek if vocab else provider.translate_batch_deepseek
    with pytest.raises(ValueError, match='implementation-error'):
        translate(['Bonds are stable.'], settings_obj=settings)
    assert response.closed


@pytest.mark.parametrize('has_fallback', [False, True])
def test_real_orchestrator_closes_audit_after_truncated_response(tmp_path, monkeypatch, has_fallback):
    from config.settings import settings
    from video_processing.db.database import PipelineDB
    from video_processing.processors.caption_processor import AutoCaptionProcessor
    from video_processing.utils.subtitle_translation_provider import SubtitleTranslationCandidate
    from video_processing.utils.subtitle_failure_receipt import SubtitleTranslationFailure

    # 仅三个外部边界：同一配置对象、HTTP响应、下一供应商；DAL/质量门/模型池均真实执行。
    monkeypatch.setattr(type(settings), 'project_root', property(lambda _: tmp_path))
    monkeypatch.setattr(settings, 'subtitle_translation_provider_order', 'deepseek,google' if has_fallback else 'deepseek')
    monkeypatch.setattr(settings, 'deepseek_api_key', 'offline-test')
    monkeypatch.setattr(settings, 'enable_deepseek_vocab_fallback', True)
    response = BrokenResponse(http.client.IncompleteRead(b'private-response-body'))
    monkeypatch.setattr(provider.urllib.request, 'urlopen', lambda *args, **kwargs: response)
    source = tmp_path / f'readfailure{int(has_fallback)}.mp4'
    source.touch()
    processor = AutoCaptionProcessor(source, tmp_path / 'unused.mp4')
    fallbacks = []

    def fallback(texts):
        fallbacks.append(texts)
        return SubtitleTranslationCandidate('Google', ['债券保持稳定。'], supports_vocab=True)

    monkeypatch.setattr(processor, '_build_google_candidate', fallback)
    segments = [{'text': 'Bonds are stable.', 'start': 0., 'end': 4.}]
    if has_fallback:
        translated = processor._translate_segments(segments)
        assert translated[0]['zh_text'] == '债券保持稳定。'
        assert fallbacks == [['Bonds are stable.']]
    else:
        with pytest.raises(SubtitleTranslationFailure):
            processor._translate_segments(segments)
        assert not fallbacks and 'zh_text' not in segments[0]
    assert segments[0]['text'] == 'Bonds are stable.'
    assert (segments[0]['start'], segments[0]['end']) == (0., 4.)
    run = PipelineDB().get_ai_audit_for_video(source.stem, limit=1)[0]
    assert run['id'] == processor._translation_audit_run_id
    assert run['status'] == ('SUCCEEDED' if has_fallback else 'FAILED')
    assert run['finished_at'] and response.closed
    assert run['attempts'][0]['provider'] == 'deepseek'
    assert run['attempts'][0]['status'] == 'FAILED'
    assert run['attempts'][0]['error_class'] == 'network'
    assert 'private-response-body' not in run['attempts'][0]['error_message']
    if has_fallback:
        assert run['final_provider'] == 'Google' and run['fallback_used']
        assert run['attempts'][1]['status'] == 'SUCCEEDED' and run['attempts'][1]['selected']
    else:
        assert len(run['attempts']) == 1
