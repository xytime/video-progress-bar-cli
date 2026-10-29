"""只读交叉审查的坏批复现；不调用模型或网络。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-29 | Codex | 候选批、Google库存和真实缓存消费拒绝硬占位语。 |
"""
import hashlib
import json

from video_processing.utils.subtitle_batch_cache import CandidateBatchCache
from video_processing.utils.subtitle_provider_inventory import google_inventory


def _cache(root):
    return CandidateBatchCache(root, provider='deepseek', profile={'model': 'fixture'},
        binding={'input': 'fixture', 'asr': 'fixture'}, texts=['Hello world.'],
        context='Full source context.')


def test_candidate_cache_does_not_save_hard_placeholder(tmp_path):
    cache = _cache(tmp_path)
    assert not cache.store(0, 1, 'actual prompt',
        [{'translation': '待翻译', 'vocab': {}}], 'fixture', 1.0)


def test_candidate_cache_rejects_old_hash_consistent_hard_placeholder(tmp_path):
    cache = _cache(tmp_path)
    assert cache.store(0, 1, 'actual prompt',
        [{'translation': '你好世界。', 'vocab': {}}], 'fixture', 1.0)
    path = cache.directory / '000000.json'
    payload = json.loads(path.read_text())
    payload['items'][0]['translation'] = '待翻译'
    payload['result_sha256'] = hashlib.sha256(json.dumps(
        dict(items=payload['items'], model=payload['model']), ensure_ascii=False,
        sort_keys=True, allow_nan=False).encode()).hexdigest()
    path.write_text(json.dumps(payload))
    assert cache.load(0, 1, 'actual prompt') is None


def test_google_inventory_does_not_count_hard_placeholder(tmp_path):
    texts = ['Hello world.']
    signature = hashlib.sha256(json.dumps(
        ['google-v2', 'auto', 'zh-CN', texts], ensure_ascii=False).encode()).hexdigest()
    (tmp_path / (signature + '.json')).write_text(json.dumps(['待翻译']))
    inventory = google_inventory(tmp_path, texts, 'zh-CN', 1)
    assert inventory['cached_batches'] == 0
    assert inventory['remaining_batches'] == 1


def test_google_old_placeholder_is_requested_again(tmp_path, monkeypatch):
    from video_processing.utils import translation_helper as module
    texts = ['Hello world.']
    signature = hashlib.sha256(json.dumps(
        ['google-v2', 'auto', 'zh-CN', texts], ensure_ascii=False).encode()).hexdigest()
    path = tmp_path / (signature + '.json')
    path.write_text(json.dumps(['待翻译']))
    calls = []

    class Translator:
        def translate(self, text):
            calls.append(text)
            return '你好世界。'

    monkeypatch.setattr(module, 'GoogleTranslator', lambda **kwargs: Translator())
    assert module._google_translate_batch(texts, cache_dir=tmp_path) == ['你好世界。']
    assert calls == texts
    assert json.loads(path.read_text()) == ['你好世界。']


def test_google_response_placeholder_is_never_saved(tmp_path, monkeypatch):
    from video_processing.utils import translation_helper as module

    class Translator:
        def translate(self, text):
            return '待翻译'

    monkeypatch.setattr(module, 'GoogleTranslator', lambda **kwargs: Translator())
    assert module._google_translate_batch(['Hello world.'], cache_dir=tmp_path) == ['']
    assert list(tmp_path.glob('*.json')) == []


def test_candidate_cache_preserves_correct_split_amount_at_batch_boundary(tmp_path):
    texts = ['Hello world.'] * 24 + ['The platforms committed $600',
        'billion in capital expenditure.']
    cache = CandidateBatchCache(tmp_path, provider='deepseek', profile={'model': 'fixture'},
        binding={'input': 'fixture'}, texts=texts, context='Full source context.')
    items = [{'translation': '你好世界。', 'vocab': {}}] * 24 + [
        {'translation': '平台承诺6000亿美元', 'vocab': {}}]
    assert cache.store(0, 25, 'actual prompt', items, 'fixture', 1.0)
    assert cache.load(0, 25, 'actual prompt') == (items, 'fixture')


def test_candidate_cache_rejects_wrong_split_amount_at_batch_boundary(tmp_path):
    texts = ['Hello world.'] * 24 + ['The platforms committed $600',
        'billion in capital expenditure.']
    cache = CandidateBatchCache(tmp_path, provider='deepseek', profile={'model': 'fixture'},
        binding={'input': 'fixture'}, texts=texts, context='Full source context.')
    items = [{'translation': '你好世界。', 'vocab': {}}] * 24 + [
        {'translation': '平台承诺600美元', 'vocab': {}}]
    assert not cache.store(0, 25, 'actual prompt', items, 'fixture', 1.0)
