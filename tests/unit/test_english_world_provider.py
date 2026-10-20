"""供应商切换的真实预算、独立输入与失败关闭边界。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-20 | Codex | 验证预检、冷却、单次故障切换、崩溃占额及内容拒绝不可切换。 |
"""
import json
from pathlib import Path
import pytest
from video_processing.utils import english_world_provider as module


def routes():
    return [module.Provider('agy', 'gemini-3.8-flash-high', 'agy'),
            module.Provider('codex', 'gpt-5.6-luna', 'codex')]


def test_health_requires_generation_and_cooldown_survives_restart(tmp_path, monkeypatch):
    calls = []
    def call(provider, prompt, **kwargs):
        calls.append(provider.name)
        if provider.name == 'agy':
            raise module.AgyProviderError('agy exit 1: location ineligible')
        return {'structured_result': {'nonce': prompt.split('：')[-1]}}
    monkeypatch.setattr(module.Provider, 'call', call)
    router = module.ProviderRouter(tmp_path, routes())
    assert router.preflight()['provider'] == 'codex'
    assert module.ProviderRouter(tmp_path, routes()).preflight()['provider'] == 'codex'
    assert calls == ['agy', 'codex']
    health = json.loads(router._health_path(routes()[0]).read_text())
    assert health['next_check_at'] > health['checked_at']


def test_one_fallback_and_successful_replay_without_model(tmp_path, monkeypatch):
    monkeypatch.setattr(module.ProviderRouter, 'ready', lambda *a: True)
    router = module.ProviderRouter(tmp_path / 'health', routes())
    calls = []
    def action(provider):
        calls.append(provider.name)
        if provider.name == 'agy':
            raise module.AgyProviderError('agy exit 1: location ineligible')
        return {'state': 'PASS'}
    kwargs = dict(receipt=tmp_path / 'stage.json', binding={'input': 'same'})
    result, identity = router.run(action, **kwargs)
    assert identity['provider'] == 'codex' and identity['model'] == 'gpt-5.6-luna'
    assert router.run(action, **kwargs)[0] == result
    assert calls == ['agy', 'codex']
    attempts = json.loads(kwargs['receipt'].read_text())['attempts']
    assert [a['state'] for a in attempts] == ['INFRASTRUCTURE_ERROR', 'COMPLETED']
    with pytest.raises(ValueError, match='输入已改变'):
        router.run(action, receipt=kwargs['receipt'], binding={'input': 'changed'})
    def refuse(_):
        raise ValueError('historical terminal')
    with pytest.raises(ValueError, match='historical terminal'):
        router.run(action, **kwargs, replay=refuse)


@pytest.mark.parametrize('result', [{'state': 'BLOCKED'}, {'state': 'FAIL'}, {'state': 'UNCERTAIN'}])
def test_content_decision_is_never_retried(tmp_path, monkeypatch, result):
    monkeypatch.setattr(module.ProviderRouter, 'ready', lambda *a: True)
    calls = []
    def action(provider):
        calls.append(provider.name)
        return result
    assert module.ProviderRouter(tmp_path, routes()).run(action,
        receipt=tmp_path / 'stage.json', binding={})[0] == result
    assert calls == ['agy']


def test_both_failed_no_more_calls_after_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(module.ProviderRouter, 'ready', lambda *a: True)
    calls = []
    def action(provider):
        calls.append(provider.name)
        raise module.AgyProviderError('provider error')
    for _ in range(3):
        with pytest.raises(module.EnglishWorldProviderError, match='PROVIDER_BLOCKED'):
            module.ProviderRouter(tmp_path, routes()).run(action, receipt=tmp_path / 'stage.json', binding={})
    assert calls == ['agy', 'codex']


@pytest.mark.parametrize('state', ['RUNNING', 'INVALID'])
def test_crashed_and_invalid_stage_cannot_restart(tmp_path, state):
    receipt = tmp_path / 'stage.json'
    receipt.write_text(json.dumps({'binding': module.fingerprint({}), 'state': state, 'attempts': []}))
    with pytest.raises(ValueError, match='不得自动'):
        module.ProviderRouter(tmp_path, routes()).run(lambda _: pytest.fail('must not call'), receipt=receipt, binding={})
