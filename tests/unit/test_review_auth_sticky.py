"""认证旁路回归；使用合成时钟/状态，不探测真实账号或修改生产池。"""
import json

import pytest

from video_processing.utils.translation_model_pool import DynamicTranslationModelPool


@pytest.mark.parametrize('provider', ['agy', 'gemini', 'codex'])
def test_auth_stays_blocked_after_cooldown_and_restart(tmp_path, monkeypatch, provider):
    clock = [1000.]
    monkeypatch.setattr('video_processing.utils.translation_model_pool.time.time', lambda: clock[0])
    path = tmp_path / 'pool.json'
    pool = DynamicTranslationModelPool(path)
    pool.record_failure(provider, category='auth_or_permission')
    assert pool.order([provider, 'google'], ignore_cooldown={provider}) == ['google']
    clock[0] += 86401
    restored = DynamicTranslationModelPool(path)
    assert restored.order([provider, 'google']) == ['google']
    # 一次非认证错误不是登录恢复证据，也不能重新打开旁路。
    restored.record_failure(provider, category='network')
    clock[0] += 200
    assert DynamicTranslationModelPool(path).order([provider]) == []
    restored.record_quality(provider, score=90)
    assert DynamicTranslationModelPool(path).order([provider]) == [provider]


@pytest.mark.parametrize('incident', [None, 1000.])
def test_legacy_auth_state_is_blocked_without_rewriting_history(tmp_path, monkeypatch, incident):
    monkeypatch.setattr('video_processing.utils.translation_model_pool.time.time', lambda: 100000.)
    path = tmp_path / 'pool.json'
    path.write_text(json.dumps({'agy': dict(last_error_class='auth_or_permission',
        cooldown_until=87400., auth_incident=incident)}))
    original = path.read_bytes()
    pool = DynamicTranslationModelPool(path)
    assert pool.order(['agy', 'codex'], ignore_cooldown={'agy'}) == ['codex']
    assert path.read_bytes() == original
    pool.record_failure('agy', category='timeout')
    assert DynamicTranslationModelPool(path).snapshot()['agy']['auth_blocked'] is True


def test_legacy_success_is_not_misread_as_active_auth_failure(tmp_path):
    path = tmp_path / 'pool.json'
    path.write_text(json.dumps({'agy': dict(last_error_class='auth_or_permission',
        cooldown_until=0, auth_incident=None, last_success_at=1000)}))
    assert DynamicTranslationModelPool(path).order(['agy']) == ['agy']


def test_quota_still_expires_and_outer_gemini_exception_still_works(tmp_path, monkeypatch):
    clock = [1000.]
    monkeypatch.setattr('video_processing.utils.translation_model_pool.time.time', lambda: clock[0])
    pool = DynamicTranslationModelPool(tmp_path / 'pool.json')
    pool.record_failure('agy', category='rate_limit')
    pool.record_failure('gemini', category='rate_limit')
    assert pool.order(['agy']) == []
    assert pool.order(['gemini'], ignore_cooldown={'gemini'}) == ['gemini']
    clock[0] += 901
    assert pool.order(['agy']) == ['agy']
