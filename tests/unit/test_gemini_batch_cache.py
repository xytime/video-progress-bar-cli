"""真实磁盘断点验证后批失败不丢已完成批；供应商仅用离线替身。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-01 | Codex | 中断续跑、上下文与实现漂移、坏缓存、结构拒绝及原期限保护。 |
"""
import json
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from video_processing.utils import vocab_helper
from video_processing.utils.gemini_batch_cache import GeminiBatchCache, fingerprint


MODEL = vocab_helper._MODELS_TO_TRY[0]


def response(count):
    return json.dumps([dict(id=i, translation=f'第{i}句译文', vocab={}) for i in range(count)])


def cache_at(directory, **changes):
    identity = dict(english=['first', 'outside batch'], context='finance', implementation='v1',
                    chinese=None, maximum=3, minimum=0, authoritative=True)
    identity.update(changes)
    return GeminiBatchCache(directory, identity, [MODEL])


def test_new_interpreter_reuses_complete_disk_batch(tmp_path):
    cache = cache_at(tmp_path)
    cache.save('prompt', response(2), MODEL, 2, vocab_helper._parse_response)
    script = '''import json,sys
from pathlib import Path
from video_processing.utils.gemini_batch_cache import GeminiBatchCache
from video_processing.utils.vocab_helper import _parse_response
r=json.loads(sys.stdin.read())
c=GeminiBatchCache(Path(r['directory']),r['identity'],r['models'])
print(json.dumps(c.load('prompt',2,_parse_response)))
'''
    identity = dict(english=['first','outside batch'], context='finance', implementation='v1',
                    chinese=None,maximum=3,minimum=0,authoritative=True)
    run = subprocess.run([sys.executable,'-c',script],input=json.dumps(dict(directory=str(tmp_path),
        identity=identity,models=[MODEL])),capture_output=True,text=True,timeout=10,check=True)
    rows, model = json.loads(run.stdout)
    assert len(rows)==2 and rows[1]['translation']=='第1句译文' and model==MODEL


@pytest.mark.parametrize('change',[
    dict(english=['first','changed outside batch']), dict(context='health'),
    dict(implementation='v2'), dict(chinese=['中文','另一句']),
    dict(maximum=5), dict(minimum=1), dict(authoritative=False),
])
def test_full_input_and_contract_change_never_reuses_other_batch(tmp_path,change):
    cache_at(tmp_path).save('prompt',response(1),MODEL,1,vocab_helper._parse_response)
    assert cache_at(tmp_path,**change).load('prompt',1,vocab_helper._parse_response) is None
    assert cache_at(tmp_path).load('changed prompt',1,vocab_helper._parse_response) is None


@pytest.mark.parametrize('raw',[
    '[]', 'not json', '[{"id":0,"translation":"","vocab":{}}]',
    '[{"id":0,"translation":"<html>502 Bad Gateway</html>","vocab":{}}]',
    '[{"id":0,"translation":"译文","vocab":{}}]',
])
def test_partial_empty_error_or_unparseable_response_is_not_saved(tmp_path,raw):
    cache = cache_at(tmp_path)
    cache.save('prompt',raw,MODEL,2,vocab_helper._parse_response)
    assert cache.load('prompt',2,vocab_helper._parse_response) is None
    assert not list(tmp_path.glob('*.json'))


@pytest.mark.parametrize('fault',['raw','identity','model','corrupt'])
def test_invalid_disk_evidence_is_not_trusted(tmp_path,fault):
    cache = cache_at(tmp_path)
    cache.save('prompt',response(2),MODEL,2,vocab_helper._parse_response)
    path = cache.path('prompt')
    payload = json.loads(path.read_text())
    if fault=='raw': payload['raw']=response(1)
    elif fault=='identity': payload['identity']='other'
    elif fault=='model':
        payload['model']='unrequested-provider'
        payload['response_sha256']=fingerprint([payload['raw'],payload['model']])
    if fault=='corrupt': path.write_text('{')
    else: path.write_text(json.dumps(payload))
    assert cache.load('prompt',2,vocab_helper._parse_response) is None


@pytest.fixture
def offline(tmp_path,monkeypatch):
    import importlib
    config_module = importlib.import_module('config.settings')
    from google import genai
    state = SimpleNamespace(calls=0, clients=0, closes=0, fail_at=2)
    class Client:
        def __init__(self,**_kwargs): state.clients+=1
        def close(self): state.closes+=1
    def call(_client,prompt,_types,**_kwargs):
        state.calls+=1
        if state.calls==state.fail_at: return None
        payload=json.loads(prompt.rsplit('Input segments:\n',1)[1])
        return SimpleNamespace(text=response(len(payload))), MODEL
    monkeypatch.setattr(config_module,'settings',SimpleNamespace(gemini_api_key='offline-test',
        default_output_dir=tmp_path, project_root=tmp_path, gemini_subtitle_total_timeout_seconds=300))
    monkeypatch.setattr(genai,'Client',Client)
    monkeypatch.setattr(vocab_helper,'_call_with_retry',call)
    return state


def test_failed_later_batch_resumes_without_repeating_completed_request(offline):
    texts=[f'source sentence {i}' for i in range(52)]
    assert vocab_helper.extract_vocab_batch(texts) is None
    assert offline.calls==2 and offline.clients==offline.closes==2
    models=[]
    result=vocab_helper.extract_vocab_batch(texts,model_out=models)
    assert len(result)==52
    assert offline.calls==4 and offline.clients==offline.closes==4
    assert result[0]['translation']=='第0句译文' and result[25]['translation']=='第0句译文'
    assert models==[MODEL]
    # 完整缓存再读不构造 SDK 客户端；全片候选仍交由调用者的原质量门。
    assert vocab_helper.extract_vocab_batch(texts)==result
    assert offline.calls==4 and offline.clients==4


def test_expired_deadline_does_not_initialize_client_even_with_valid_cache(offline):
    offline.fail_at=None
    assert vocab_helper.extract_vocab_batch(['one'])
    assert vocab_helper.extract_vocab_batch(['one'],deadline=time.monotonic()-1) is None
    assert offline.calls==1 and offline.clients==1


def test_bad_cache_fetches_supplier_again(offline,tmp_path):
    offline.fail_at=None
    first=vocab_helper.extract_vocab_batch(['one'])
    files=list((tmp_path/'gemini_subtitle_cache').glob('*.json'))
    assert len(files)==1
    files[0].write_text('{broken')
    assert vocab_helper.extract_vocab_batch(['one'])==first
    assert offline.calls==2


def test_snapshot_write_failure_does_not_discard_supplier_output(tmp_path,monkeypatch):
    from video_processing.utils import gemini_batch_cache
    def denied(**_kwargs): raise OSError('disk unavailable')
    monkeypatch.setattr(gemini_batch_cache.tempfile,'NamedTemporaryFile',denied)
    cache=cache_at(tmp_path)
    cache.save('prompt',response(1),MODEL,1,vocab_helper._parse_response)
    assert cache.load('prompt',1,vocab_helper._parse_response) is None
