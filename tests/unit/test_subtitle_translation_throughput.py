"""翻译提速边界：预算、候选批暂存及传输故障注入，不调用真实模型。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.1 | 2026-10-29 | Codex | 覆盖长片后备未准入时实际传输失败及累计预算的保留。 |
| 1.0.0 | 2026-10-29 | Codex | 覆盖后备机会、累计耗尽、原子候选绑定、坏批拒绝和截断连接恢复。 |
"""
import http.client
import json
from pathlib import Path
from types import SimpleNamespace
import urllib.error

import pytest

from video_processing.utils.subtitle_translation_budget import (
    CandidateBudget, TranslationAttemptLedger, transport_failure,
)
from video_processing.utils.subtitle_batch_cache import CandidateBatchCache
from video_processing.utils.deepseek_translation import translate_batch_with_vocab_deepseek


def _cache(tmp_path, **overrides):
    options = dict(provider='deepseek', profile={'model': 'test'}, binding={'input': 'media', 'asr': 'asr'},
                   texts=['Hello world.'] * 26, context='Complete source context.', deadline=None)
    options.update(overrides)
    return CandidateBatchCache(tmp_path, **options)


def test_budget_keeps_next_complete_fallback_and_quality_reserve():
    budget = CandidateBudget(197)
    admission = budget.admit('gemini', 600, ['deepseek', 'google', 'codex'])
    assert admission.allowed
    assert admission.seconds == 240
    assert admission.fallback_reserve == 240
    assert admission.seconds + admission.fallback_reserve + budget.quality_reserve == 600
    assert not budget.admit('codex', 200).allowed


def test_budget_probes_only_api_provider_and_never_splits_fairly():
    budget = CandidateBudget(500)
    assert budget.admit('gemini', 600).probe
    assert not budget.admit('codex', 600).allowed
    assert budget.admit('google', 600).allowed is False
    assert not budget.admit('gemini', 125).allowed


def test_cumulative_ledger_retains_spend_and_cannot_grow_limit(tmp_path, monkeypatch):
    import video_processing.utils.subtitle_translation_budget as module
    now = [100.0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: now[0])
    first = TranslationAttemptLedger(tmp_path, {'plan': 'one'}, 600)
    with first.lease():
        first.checkpoint(reserve=240)
        assert json.loads(first.path.read_text())['used_seconds'] == 240
        now[0] += 35
    resumed = TranslationAttemptLedger(tmp_path, {'plan': 'one'}, 900)
    with resumed.lease():
        assert resumed.remaining() == 565
        assert resumed.limit == 600
        resumed.terminal = True
    with TranslationAttemptLedger(tmp_path, {'plan': 'one'}, 900).lease() as terminal:
        assert terminal.remaining() == 0


def test_crashed_reservation_and_corrupt_ledger_fail_closed(tmp_path):
    ledger = TranslationAttemptLedger(tmp_path, {'plan': 'crashed'}, 600)
    ledger.directory.mkdir(parents=True)
    # 模拟进程在预扣后退出：未核实的调用窗口不能在重启时退还。
    ledger.path.write_text(json.dumps(dict(total_seconds=600, used_seconds=240, terminal=False)))
    with ledger.lease():
        assert ledger.remaining() == 360
    ledger.path.write_text('{broken')
    with TranslationAttemptLedger(tmp_path, {'plan': 'crashed'}, 600).lease() as corrupt:
        assert corrupt.remaining() == 0


@pytest.mark.parametrize('change', [
    {'terminal': 'true'}, {'terminal': 0}, {'total_seconds': 'nan'}, {'total_seconds': float('inf')},
    {'total_seconds': -1}, {'total_seconds': True}, {'used_seconds': True}, {'used_seconds': float('nan')},
])
def test_json_ledger_type_corruption_cannot_restore_budget(tmp_path, change):
    ledger = TranslationAttemptLedger(tmp_path, {'plan': 'damaged-types'}, 600)
    ledger.directory.mkdir(parents=True)
    state = dict(total_seconds=600, used_seconds=0, terminal=False)
    ledger.path.write_text(json.dumps(dict(state, **change)))
    with ledger.lease():
        assert ledger.remaining() == 0 and ledger.terminal is True
        assert ledger.limit == 600
    assert json.loads(ledger.path.read_text()) == dict(version=1, total_seconds=600,
        used_seconds=600, terminal=True)


def test_same_plan_lock_refuses_duplicate_calls(tmp_path):
    with TranslationAttemptLedger(tmp_path, {'plan': 'locked'}, 600).lease():
        with pytest.raises(BlockingIOError):
            with TranslationAttemptLedger(tmp_path, {'plan': 'locked'}, 600).lease():
                pytest.fail('同计划不能重复领取')


def test_batch_cache_reuses_only_exact_full_binding_and_prompt(tmp_path):
    cache = _cache(tmp_path)
    items = [dict(translation='你好世界。', vocab={})] * 25
    with cache.lease():
        assert cache.store(0, 25, 'prompt', items, 'test', 2.5)
        assert cache.load(0, 25, 'prompt') == (items, 'test')
        assert cache.load(0, 25, 'changed prompt') is None
    for changes in ({'context': 'Changed context'}, {'provider': 'gemini'},
                    {'texts': ['Different full source.'] * 26}, {'profile': {'model': 'other'}},
                    {'binding': {'input': 'changed', 'asr': 'asr'}}):
        assert _cache(tmp_path, **changes).load(0, 25, 'prompt') is None
    path = cache.directory / '000000.json'
    payload = json.loads(path.read_text())
    payload['items'][0]['translation'] = '已被替换'
    path.write_text(json.dumps(payload))
    assert cache.load(0, 25, 'prompt') is None


def test_bad_financial_batch_never_enters_candidate_cache(tmp_path):
    cache = _cache(tmp_path, texts=['The fund raised $49 billion.'])
    assert not cache.store(0, 1, 'prompt', [dict(translation='基金退出49美元。', vocab={})], 'test', 1)
    assert cache.load(0, 1, 'prompt') is None
    assert not cache.store(0, 1, 'prompt', [dict(translation='', vocab={})], 'test', 1)


def test_probe_stops_unfinishable_candidate_using_actual_latency(tmp_path, monkeypatch):
    import video_processing.utils.subtitle_batch_cache as module
    monkeypatch.setattr(module.time, 'monotonic', lambda: 100.0)
    cache = _cache(tmp_path, texts=['Hello world.'] * 197, deadline=340.0)
    assert cache.request_deadline(340) == 130
    assert cache.permit(0)
    cache.observations.append(60)
    assert not cache.permit(25)


def test_inventory_deducts_only_verified_cache_and_reuses_profile_latency(tmp_path):
    factory = lambda offset, count: f'actual prompt:{offset}:{count}'
    with _cache(tmp_path, texts=['Hello world.'] * 76, prompt_factory=factory).lease() as cache:
        assert cache.store(0, 25, factory(0, 25), [dict(translation='你好世界。', vocab={})] * 25, 'test', 3)
        assert cache.store(50, 25, factory(50, 25), [dict(translation='你好世界。', vocab={})] * 25, 'test', 4)
    resumed = _cache(tmp_path, texts=['Hello world.'] * 76, prompt_factory=factory)
    inventory = resumed.inventory()
    assert inventory == dict(cached_batches=2, remaining_batches=2, estimated_seconds=12.0,
                             cost_basis='matched_profile_observed')
    budget = CandidateBudget(76)
    assert budget.admit('deepseek', 132, estimates={'deepseek': inventory['estimated_seconds']}).allowed
    # 后缀有效缓存也须扣除，不能把offset之后所有批都当成未完成。
    resumed.deadline = __import__('time').monotonic() + 13
    assert resumed.permit(25)
    (resumed.directory / '000050.json').write_text('{corrupt')
    assert resumed.inventory()['remaining_batches'] == 3


def test_fully_cached_candidate_is_admitted_with_only_quality_reserve(tmp_path):
    factory = lambda offset, count: f'prompt:{offset}:{count}'
    with _cache(tmp_path, texts=['Hello world.'], prompt_factory=factory).lease() as cache:
        cache.store(0, 1, factory(0, 1), [dict(translation='你好世界。', vocab={})], 'test', 3)
    inventory = _cache(tmp_path, texts=['Hello world.'], prompt_factory=factory).inventory()
    admission = CandidateBudget(1).admit('deepseek', 120,
        estimates={'deepseek': inventory['estimated_seconds']})
    assert admission.allowed and admission.estimated_seconds == 0


class _Response:
    def __init__(self, rows):
        self.rows = rows
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self):
        return json.dumps({'choices': [{'message': {'content': json.dumps(self.rows)}}]}).encode()


def test_deepseek_truncated_connection_keeps_good_batch_for_same_provider(tmp_path, monkeypatch):
    import video_processing.utils.deepseek_translation as module
    calls = []
    settings = SimpleNamespace(deepseek_api_key='fixture', deepseek_base_url='https://fixture.invalid',
                               deepseek_model='test')
    def broken(req, timeout):
        calls.append(json.loads(req.data))
        if len(calls) == 2:
            raise http.client.IncompleteRead(b'private content', 100)
        return _Response([dict(id=i, translation='你好世界。', vocab={}) for i in range(25)])
    monkeypatch.setattr(module.urllib.request, 'urlopen', broken)
    errors = []
    with _cache(tmp_path).lease() as cache:
        result = translate_batch_with_vocab_deepseek(cache.texts, settings_obj=settings,
            context_text=cache.context, error_out=errors, batch_cache=cache)
    assert result is None
    assert errors == ['transport_connection']
    assert 'private' not in str(errors)
    monkeypatch.setattr(module.urllib.request, 'urlopen',
        lambda req, timeout: _Response([dict(id=0, translation='你好世界。', vocab={})]))
    with _cache(tmp_path).lease() as cache:
        result = translate_batch_with_vocab_deepseek(cache.texts, settings_obj=settings,
            context_text=cache.context, batch_cache=cache)
    assert len(result) == 26
    assert len(calls) == 2


@pytest.mark.parametrize('provider', ['gemini', 'deepseek'])
def test_complete_bound_api_cache_needs_no_live_credentials_or_request_budget(tmp_path, monkeypatch, provider):
    from video_processing.utils import vocab_helper
    from video_processing.utils.deepseek_translation import _build_vocab_payload
    from importlib import import_module
    settings_module = import_module('config.settings')
    texts, context = ['Hello world.'], 'Complete source context.'
    model = vocab_helper._MODELS_TO_TRY[0] if provider == 'gemini' else 'test'
    prompt = (vocab_helper._build_prompt(texts, None, context_text=context) if provider == 'gemini'
              else _build_vocab_payload(texts, context_text=context, model=model))
    cache = _cache(tmp_path, provider=provider, profile={'model': model}, texts=texts, context=context)
    items = [dict(translation='你好世界。', vocab={})]
    cache.store(0, 1, prompt, items, model, 1)
    errors = []
    if provider == 'gemini':
        monkeypatch.setattr(settings_module, 'settings', SimpleNamespace(gemini_api_key=''))
        result = vocab_helper.extract_vocab_batch(texts, context_text=context, deadline=0,
            error_out=errors, batch_cache=cache)
    else:
        result = translate_batch_with_vocab_deepseek(texts, context_text=context, deadline=0,
            error_out=errors, batch_cache=cache,
            settings_obj=SimpleNamespace(deepseek_api_key='', deepseek_model=model))
    assert result == items and errors == []


@pytest.mark.parametrize('error,category', [
    (http.client.IncompleteRead(b'secret', 50), 'network'),
    (ConnectionResetError('secret endpoint'), 'network'), (TimeoutError('secret'), 'timeout'),
    (urllib.error.HTTPError('https://secret', 429, 'secret', {}, None), 'quota'),
    (urllib.error.HTTPError('https://secret', 403, 'secret', {}, None), 'authentication'),
])
def test_transport_classification_is_typed_and_contains_no_raw_error(error, category):
    result = transport_failure(error)
    assert result['category'] == category
    assert 'secret' not in str(result)
    assert transport_failure(ValueError('programming error')) is None


def _processor_fixture(tmp_path, monkeypatch, providers, build):
    import video_processing.processors.caption_processor as module
    class Processor(module.AutoCaptionProcessor):
        def __init__(self):
            self.input_path, self.output_path = tmp_path / 'source.mp4', tmp_path / 'captioned.mp4'
            self.src_lang, self.target_lang = 'en', 'zh-CN'
            self._translation_cache_binding = dict(input_sha256='source', asr_sha256='asr', contract_sha256='contract')
        def _start_translation_audit(self):
            return None
        def _build_translation_candidate(self, provider, texts, context):
            return build(self, provider, texts, context)
    monkeypatch.setattr(module, 'settings', SimpleNamespace(enable_subtitle_translation_throughput=True,
        subtitle_translation_total_timeout_seconds=600, subtitle_translation_quality_reserve_seconds=120,
        subtitle_translation_provider_order_list=providers, enable_deepseek_vocab_fallback=True,
        default_output_dir=tmp_path / 'output', project_root=tmp_path, deepseek_model='test',
        codex_text_model='gpt-5.6-luna', codex_text_effort='medium', codex_subtitle_batch_size=5,
        codex_text_command='unused-fixture-command', codex_text_request_timeout_seconds=120,
        codex_subtitle_total_timeout_seconds=600))
    return Processor()


@pytest.mark.parametrize('rows', [123, 197])
def test_long_failure_shapes_retain_full_fallback_and_full_quality_gate(tmp_path, monkeypatch, rows):
    import video_processing.processors.caption_processor as module
    from video_processing.utils.subtitle_translation_provider import SubtitleTranslationCandidate
    now, calls, budgets = [100.0], [], []
    monkeypatch.setattr(module.time, 'monotonic', lambda: now[0])
    def build(processor, provider, texts, context):
        calls.append(provider)
        budgets.append(processor._remaining_candidate_budget())
        assert context
        if provider == 'gemini':
            now[0] += 30
            processor._last_provider_error = 'provider_candidate_budget_exhausted'
            return None
        now[0] += 10
        return SubtitleTranslationCandidate(provider='DeepSeek', translations=['你好世界。'] * rows,
                                            vocabs=[{}] * rows, supports_vocab=True)
    processor = _processor_fixture(tmp_path, monkeypatch, ['gemini', 'deepseek', 'google', 'codex'], build)
    result = processor._translate_segments([{'text': 'Hello world.'} for _ in range(rows)])
    assert calls == ['gemini', 'deepseek']
    assert budgets[0] == (330 if rows == 123 else 240)
    assert len(result) == rows and all(row['zh_text'] == '你好世界。' for row in result)
    assert processor._translation_quality_audit[-1]['selected'] is True
    state = json.loads((tmp_path / 'output' / 'translation_model_pool.json').read_text())
    assert 'gemini' not in state  # 宿主候选预算不能冒充服务冷却。
    ledger_path = next((tmp_path / 'output').glob('subtitle_candidate_cache/subtitle-attempt-budget-v1/*/budget.json'))
    assert json.loads(ledger_path.read_text())['used_seconds'] == 40


def test_insufficient_codex_budget_is_terminal_without_any_call_or_cooldown(tmp_path, monkeypatch):
    from video_processing.utils.subtitle_failure_receipt import SubtitleTranslationFailure
    calls = []
    def build(processor, provider, texts, context):
        calls.append(provider)
        pytest.fail('不应启动无法完成的长片 Codex 候选')
    processor = _processor_fixture(tmp_path, monkeypatch, ['codex'], build)
    with pytest.raises(SubtitleTranslationFailure) as first:
        processor._translate_segments([{'text': 'Hello world.'}] * 197)
    assert first.value.failure['category'] == 'budget'
    with pytest.raises(SubtitleTranslationFailure) as second:
        processor._translate_segments([{'text': 'Hello world.'}] * 197)
    assert second.value.failure['code'] == 'translation_budget_exhausted'
    assert not calls
    assert not (tmp_path / 'output' / 'translation_model_pool.json').exists()


def test_only_service_failures_keep_remaining_budget_without_creating_fresh_plan(tmp_path, monkeypatch):
    from video_processing.utils.subtitle_failure_receipt import SubtitleTranslationFailure
    def build(processor, provider, texts, context):
        raise http.client.IncompleteRead(b'secret', 100)
    processor = _processor_fixture(tmp_path, monkeypatch, ['deepseek'], build)
    with pytest.raises(SubtitleTranslationFailure) as failure:
        processor._translate_segments([{'text': 'Hello world.'}])
    assert failure.value.failure['category'] == 'network'
    paths = list((tmp_path / 'output').glob('subtitle_candidate_cache/subtitle-attempt-budget-v1/*/budget.json'))
    assert len(paths) == 1
    state = json.loads(paths[0].read_text())
    assert state['terminal'] is False
    assert 0 <= state['used_seconds'] < 5


@pytest.mark.parametrize('kind,category', [
    ('network', 'network'), ('quota', 'quota'), ('authentication', 'authentication'),
])
def test_unadmitted_long_codex_fallback_does_not_mask_service_failure_or_close_budget(
        tmp_path, monkeypatch, kind, category):
    from video_processing.utils.subtitle_failure_receipt import SubtitleTranslationFailure
    calls = []
    def build(processor, provider, texts, context):
        calls.append(provider)
        if kind == 'network':
            raise http.client.IncompleteRead(b'private body', 100)
        raise urllib.error.HTTPError('https://private', 429 if kind == 'quota' else 401,
                                     'private body', {}, None)
    processor = _processor_fixture(tmp_path, monkeypatch, ['google', 'codex'], build)
    with pytest.raises(SubtitleTranslationFailure) as result:
        processor._translate_segments([{'text': 'Hello world.'}] * 197)
    assert calls == ['google']
    assert result.value.failure['category'] == category
    assert all(item['code'] != 'candidate_not_admitted_budget' for item in result.value.failures)
    assert processor._translation_throughput_events[-1]['action'] == 'not_admitted'
    ledgers = list((tmp_path / 'output').glob(
        'subtitle_candidate_cache/subtitle-attempt-budget-v1/*/budget.json'))
    assert len(ledgers) == 1
    state = json.loads(ledgers[0].read_text())
    assert state['terminal'] is False
    assert 0 <= state['used_seconds'] < 5


def test_throughput_does_not_relax_existing_full_candidate_quality_gate(tmp_path, monkeypatch):
    from video_processing.utils.subtitle_failure_receipt import SubtitleTranslationFailure
    from video_processing.utils.subtitle_translation_provider import SubtitleTranslationCandidate
    def build(processor, provider, texts, context):
        return SubtitleTranslationCandidate(provider='DeepSeek', translations=['基金退出49美元。'],
                                            vocabs=[{}], supports_vocab=True)
    processor = _processor_fixture(tmp_path, monkeypatch, ['deepseek'], build)
    segments = [{'text': 'The fund raised $49 billion.'}]
    with pytest.raises(SubtitleTranslationFailure) as failure:
        processor._translate_segments(segments)
    assert failure.value.failure['category'] == 'quality'
    assert 'zh_text' not in segments[0]


@pytest.mark.parametrize('kind,category,pool_category', [
    ('network', 'network', 'network'), ('quota', 'quota', 'rate_limit'),
    ('authentication', 'authentication', 'auth_or_permission'),
])
def test_all_five_providers_unavailable_preserve_typed_failure_and_same_plan_budget(
        tmp_path, monkeypatch, kind, category, pool_category):
    from video_processing.utils.subtitle_failure_receipt import SubtitleTranslationFailure
    calls = []
    providers = ['agy', 'gemini', 'deepseek', 'google', 'codex']
    def build(processor, provider, texts, context):
        calls.append(provider)
        if kind == 'network':
            raise http.client.IncompleteRead(b'secret body', 100)
        raise urllib.error.HTTPError('https://secret', 429 if kind == 'quota' else 401, 'secret', {}, None)
    processor = _processor_fixture(tmp_path, monkeypatch, providers, build)
    with pytest.raises(SubtitleTranslationFailure) as result:
        processor._translate_segments([{'text': 'Hello world.'}])
    assert calls == providers
    assert {failure['category'] for failure in result.value.failures} == {category}
    assert 'secret' not in str(result.value.failures)
    state = json.loads((tmp_path / 'output' / 'translation_model_pool.json').read_text())
    assert {state[provider]['last_error_class'] for provider in providers} == {pool_category}
    ledgers = list((tmp_path / 'output').glob('subtitle_candidate_cache/subtitle-attempt-budget-v1/*/budget.json'))
    assert len(ledgers) == 1
    assert json.loads(ledgers[0].read_text())['terminal'] is False


def _codex_state_path(root, texts, context, model='gpt-5.6-luna', effort='medium'):
    import hashlib
    from video_processing.utils.subtitle_recovery_state import RECOVERY_RECIPE
    identity = json.dumps([texts, context, model, effort,
        [RECOVERY_RECIPE, 5, 2, 'parent-first-rejection-to-singletons']], ensure_ascii=False, sort_keys=True)
    key = hashlib.sha256(identity.encode()).hexdigest()
    return Path(root) / 'subtitle-recovery' / (key + '.json')


def _write_codex_cache(root, texts, context, binding, *, offset=0, count=None, singleton=False):
    import hashlib
    from video_processing.utils.codex_subtitle_provider import _batch_prompt, _schema, subtitle_cache_contract
    from video_processing.utils.codex_text_provider import strict_schema
    count = count or min(5, len(texts) - offset)
    following = texts[offset + count] if offset + count < len(texts) else ''
    prompt = _batch_prompt(texts[offset:offset + count], offset, '' if singleton else context, following)
    schema = strict_schema(_schema(count))
    parts = ['codex-text-v1', 'gpt-5.6-luna', 'medium', prompt, schema, [],
             subtitle_cache_contract(singleton_repair=singleton, binding=binding)]
    signature = hashlib.sha256(json.dumps(parts, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    payload = {'items': [dict(id=index, translation='你好世界。', vocab=[])
                         for index in range(offset, offset + count)]}
    path = Path(root) / (signature + '.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload=payload)))
    return path


def test_provider_inventory_is_read_only_and_rejects_unproven_or_changed_binding(tmp_path):
    from video_processing.utils.subtitle_provider_inventory import codex_inventory, google_inventory
    root, texts, context = tmp_path / 'cache', ['Hello world.'] * 6, 'Full original context.'
    options = dict(model='gpt-5.6-luna', effort='medium', batch_size=5, seconds_per_batch=120,
                   binding={'source': 'one', 'asr': 'one', 'contract': 'one'})
    assert codex_inventory(root, texts, context, **options)['remaining_batches'] == 2
    assert google_inventory(root, texts, 'zh-CN', 1)['remaining_batches'] == 6
    assert not root.exists()
    # 旧 prompt-only 批次保留，但不能按新模式完整来源绑定复用。
    legacy = _write_codex_cache(root, texts, context, None)
    assert codex_inventory(root, texts, context, **options)['cached_batches'] == 0
    path = _write_codex_cache(root, texts, context, options['binding'])
    inventory = codex_inventory(root, texts, context, **options)
    assert inventory['cached_batches'] == 1 and inventory['remaining_batches'] == 1
    assert inventory['estimated_seconds'] == 120
    assert codex_inventory(root, texts, context,
        **dict(options, binding={'source': 'changed'}))['cached_batches'] == 0
    payload = json.loads(path.read_text())
    payload['payload']['items'][0]['translation'] = ''
    path.write_text(json.dumps(payload))
    assert codex_inventory(root, texts, context, **options)['cached_batches'] == 0
    assert legacy.exists() and path.exists()


def test_google_inventory_deducts_only_valid_rows_without_changing_file(tmp_path):
    import hashlib
    from video_processing.utils.subtitle_provider_inventory import google_inventory
    texts = ['Hello world.'] * 3
    identity = json.dumps(['google-v2', 'auto', 'zh-CN', texts], ensure_ascii=False)
    path = tmp_path / (hashlib.sha256(identity.encode()).hexdigest() + '.json')
    path.write_text(json.dumps(['你好。', '', '<html>captcha</html>']))
    original = path.read_bytes()
    assert google_inventory(tmp_path, texts, 'zh-CN', 2) == dict(cached_batches=1,
        remaining_batches=2, estimated_seconds=4, cost_basis='cold_start_estimate')
    assert path.read_bytes() == original


def test_old_exhausted_codex_plan_cannot_gain_budget_through_new_cache_binding(tmp_path, monkeypatch):
    from video_processing.utils import codex_text_provider as provider
    from video_processing.utils.codex_subtitle_provider import build_codex_subtitle_candidate
    from video_processing.utils.codex_text_provider import CodexTextError
    from video_processing.utils.subtitle_provider_inventory import codex_inventory
    from video_processing.utils.subtitle_recovery_state import RECOVERY_RECIPE
    texts, context = ['Hello world.'] * 5, 'Full source context.'
    root, binding = tmp_path / 'cache', {'source': 'source', 'asr': 'asr', 'contract': 'new'}
    state_path = _codex_state_path(root, texts, context)
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps(dict(identity=state_path.stem, recipe=RECOVERY_RECIPE,
        requests_used=2, max_requests=22, elapsed_seconds=80.35, total_timeout=80.31,
        split_batches={}, units={}, last_failure={'code': 'total_timeout'})))
    legacy_path = _write_codex_cache(root, texts, context, None)
    prior = state_path.read_bytes()
    inventory = codex_inventory(root, texts, context, model='gpt-5.6-luna', effort='medium',
        batch_size=5, seconds_per_batch=120, binding=binding)
    assert inventory['budget_exhausted'] and inventory['cached_batches'] == 0
    assert state_path.read_bytes() == prior
    monkeypatch.setattr(provider, '_execute', lambda *args: pytest.fail('旧耗尽计划不能启动模型'))
    with pytest.raises(CodexTextError) as error:
        build_codex_subtitle_candidate(texts, context, state_dir=root, command='unused',
            total_timeout=600, cache_binding=binding, allow_quality_candidate=True)
    assert error.value.code == 'total_timeout'
    after = json.loads(state_path.read_text())
    assert after['total_timeout'] == 80.31 and after['elapsed_seconds'] >= 80.35
    assert after['requests_used'] == 2
    assert legacy_path.exists()


def test_complete_codex_bound_cache_can_reach_full_qa_with_exact_quality_reserve(tmp_path, monkeypatch):
    import video_processing.processors.caption_processor as module
    from video_processing.utils.translation_context import build_translation_context
    now, texts = [100.0], ['Hello world.']
    monkeypatch.setattr(module.time, 'monotonic', lambda: now[0])
    def build(processor, provider, source, context):
        return module.AutoCaptionProcessor._build_codex_candidate(processor, source, context)
    processor = _processor_fixture(tmp_path, monkeypatch, ['codex'], build)
    binding = processor._translation_cache_binding
    ledger = TranslationAttemptLedger(tmp_path / 'output' / 'subtitle_candidate_cache', binding, 600)
    ledger.directory.mkdir(parents=True)
    ledger.path.write_text(json.dumps(dict(total_seconds=600, used_seconds=480, terminal=False)))
    root = tmp_path / 'output' / 'codex_text_cache'
    _write_codex_cache(root, texts, build_translation_context(texts).to_prompt_context(), binding)
    result = processor._translate_segments([dict(text=texts[0])])
    assert result[0]['zh_text'] == '你好世界。'
    assert processor._translation_quality_audit[-1]['selected'] is True
    assert not (root / 'subtitle-recovery').exists()
    assert processor._translation_throughput_events[0]['estimated_ms'] == 0


def test_quality_repair_pre_reserves_entire_permitted_window_then_settles_actual(tmp_path, monkeypatch):
    import video_processing.processors.caption_processor as module
    import video_processing.utils.codex_subtitle_provider as codex
    from video_processing.utils.subtitle_failure_receipt import SubtitleTranslationFailure
    from video_processing.utils.subtitle_translation_provider import SubtitleTranslationCandidate
    now, observed = [100.0], []
    monkeypatch.setattr(module.time, 'monotonic', lambda: now[0])
    def build(processor, provider, texts, context):
        now[0] += 10
        return SubtitleTranslationCandidate(provider='DeepSeek', translations=['基金退出49美元。'],
            vocabs=[{}], supports_vocab=True)
    processor = _processor_fixture(tmp_path, monkeypatch, ['deepseek'], build)
    def repair(texts, context, **kwargs):
        ledger = next((tmp_path / 'output').glob('subtitle_candidate_cache/subtitle-attempt-budget-v1/*/budget.json'))
        observed.append((kwargs['total_timeout'], json.loads(ledger.read_text())))
        now[0] += 20
        return None
    monkeypatch.setattr(codex, 'build_codex_subtitle_candidate', repair)
    with pytest.raises(SubtitleTranslationFailure) as error:
        processor._translate_segments([dict(start=0, end=3, text='The fund raised $49 billion.')])
    assert error.value.failure['category'] == 'quality'
    assert observed[0][0] == 590  # 最低保留不限制原修复可用额度。
    assert observed[0][1]['used_seconds'] == 600  # 异常退出保守保留整个未核实QA窗口。
    ledger = next((tmp_path / 'output').glob('subtitle_candidate_cache/subtitle-attempt-budget-v1/*/budget.json'))
    assert json.loads(ledger.read_text())['used_seconds'] == 30


def test_arbitration_reselection_reserves_post_google_vocabulary_requests(tmp_path, monkeypatch):
    import video_processing.processors.caption_processor as module
    from video_processing.utils.subtitle_translation_provider import SubtitleTranslationCandidate
    from video_processing.utils.subtitle_translation_quality import SubtitleTranslationQualityDecision
    from video_processing.utils.translation_quality_guard import QualityIssue
    now, observed = [100.0], []
    monkeypatch.setattr(module.time, 'monotonic', lambda: now[0])
    def build(processor, provider, texts, context):
        now[0] += 10
        if provider == 'google':
            return SubtitleTranslationCandidate(provider='Google', translations=['你好世界。'])
        raise http.client.IncompleteRead(b'secret body', 100)
    processor = _processor_fixture(tmp_path, monkeypatch, ['google', 'deepseek'], build)
    decision = SubtitleTranslationQualityDecision(provider='Google', accepted=True, status='warning', action='accept',
        warning_issues=[QualityIssue(severity='P2', code='TEST_WARNING', message='synthetic warning',
                                    source_signal='source', translation_signal='candidate')])
    monkeypatch.setattr(processor, '_evaluate_translation_quality', lambda *args, **kwargs: decision)
    def align(*args, **kwargs):
        path = next((tmp_path / 'output').glob('subtitle_candidate_cache/subtitle-attempt-budget-v1/*/budget.json'))
        observed.append(json.loads(path.read_text())['used_seconds'])
        now[0] += 5
    monkeypatch.setattr(processor, '_align_vocab_after_plain_translation', align)
    result = processor._translate_segments([dict(text='Hello world.')])
    assert result[0]['zh_text'] == '你好世界。'
    assert observed == [600]
    path = next((tmp_path / 'output').glob('subtitle_candidate_cache/subtitle-attempt-budget-v1/*/budget.json'))
    assert json.loads(path.read_text())['used_seconds'] == 25
