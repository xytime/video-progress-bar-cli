"""耗尽的持久兜底额度不占用其他供应商份额；读取不改账本。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-01 | Codex | 使用真实持久预算验证不可执行的兜底不留空闲份额，完整质量门和缓存入口保持。 |
"""
from pathlib import Path
from types import SimpleNamespace
import json

import pytest

from video_processing.utils.subtitle_recovery_state import SubtitleRecoveryState
from video_processing.utils.translation_context import build_translation_context


TEXT = 'MGX announced the final close of Fund I at $49 billion.'
TRANSLATION = 'MGX一期基金最终募集规模达490亿美元。'


def config(root):
    return SimpleNamespace(subtitle_translation_provider_order_list=['gemini','deepseek','google','codex'],
        subtitle_provider_budget_allocation_enabled=True, subtitle_translation_total_timeout_seconds=600,
        subtitle_translation_quality_reserve_seconds=120, subtitle_translation_fallback_reserve_seconds=300,
        default_output_dir=root, codex_text_model='gpt-5.6-luna', codex_text_effort='medium',
        codex_subtitle_batch_size=50, codex_subtitle_total_timeout_seconds=600,
        codex_text_request_timeout_seconds=120)


def exhausted_state(root):
    context=build_translation_context([TEXT]).to_prompt_context()
    state=SubtitleRecoveryState(root/'codex_text_cache',texts=[TEXT],context=context,
        model='gpt-5.6-luna',effort='medium',batch_size=50,max_attempts=2,max_requests=4,
        total_timeout=600,request_timeout=120)
    with state:
        state.data['elapsed_seconds']=600
    return state


@pytest.mark.parametrize('fast_failure', [False,True])
def test_exhausted_fallback_donates_reserve_without_disabling_cached_candidate(tmp_path,monkeypatch,fast_failure):
    import video_processing.processors.caption_processor as module
    from video_processing.core.base import VideoProcessingError
    from video_processing.utils.subtitle_translation_provider import SubtitleTranslationCandidate
    cfg=config(tmp_path);state=exhausted_state(tmp_path);before=state.path.read_bytes();mtime=state.path.stat().st_mtime_ns
    monkeypatch.setattr(module,'settings',cfg)
    now=[100.];calls=[]
    monkeypatch.setattr(module.time,'monotonic',lambda:now[0])
    source=tmp_path/'source.mp4';source.touch();processor=module.AutoCaptionProcessor(source,tmp_path/'unused.mp4')
    def build(provider,texts,context):
        calls.append((provider,processor._translation_deadline-now[0]))
        if fast_failure:
            now[0]+=1
        else:
            now[0]=processor._translation_deadline
        if provider=='codex':
            return SubtitleTranslationCandidate('codex',[TRANSLATION],supports_vocab=True)
        processor._last_provider_error='network interruption'
        return None
    monkeypatch.setattr(processor,'_build_translation_candidate',build)
    segments=[{'text':TEXT,'start':0.,'end':4.}]
    if fast_failure:
        translated=processor._translate_segments(segments)
        assert translated[0]['zh_text']==TRANSLATION
        assert calls[0]==('gemini',160)
        assert calls[-1][0]=='codex'
    else:
        with pytest.raises(VideoProcessingError):processor._translate_segments(segments)
        assert calls==[('gemini',160),('deepseek',160),('google',160)]
        assert 'zh_text' not in segments[0]
        assert now[0]==580 and processor._translation_deadline==700
        assert not any(e['selected'] for e in processor._translation_quality_audit)
    assert state.path.read_bytes()==before and state.path.stat().st_mtime_ns==mtime


def plan(root, **overrides):
    args=dict(texts=['business'],context='context',model='gpt-5.6-luna',effort='medium',
        batch_size=5,max_attempts=2,max_requests=4,total_timeout=600,request_timeout=120)
    args.update(overrides)
    return SubtitleRecoveryState(root,**args)


def stored(root, **values):
    state=plan(root)
    with state:pass
    payload=json.loads(state.path.read_text());payload.update(values);state.path.write_text(json.dumps(payload))
    return state


def test_new_plan_capacity_does_not_create_or_admit_a_request(tmp_path):
    state=plan(tmp_path/'missing')
    assert state.execution_capacity_seconds()==600
    assert not state.directory.exists()


@pytest.mark.parametrize(('timeout','expected'),[(900,350),(300,50)])
def test_capacity_clamps_original_budget_without_rewriting_it(tmp_path,timeout,expected):
    state=stored(tmp_path,elapsed_seconds=250,requests_used=1)
    before=state.path.read_bytes();mtime=state.path.stat().st_mtime_ns
    assert plan(tmp_path,total_timeout=timeout,max_requests=99).execution_capacity_seconds()==expected
    assert state.path.read_bytes()==before and state.path.stat().st_mtime_ns==mtime


def test_used_request_allowance_leaves_no_execution_reserve(tmp_path):
    state=stored(tmp_path,requests_used=4)
    before=state.path.read_bytes()
    assert state.execution_capacity_seconds()==0
    assert state.path.read_bytes()==before


def test_unclean_window_is_charged_at_most_its_original_allowance(tmp_path,monkeypatch):
    import video_processing.utils.subtitle_recovery_state as module
    state=stored(tmp_path,elapsed_seconds=250,active_window={'started_at':1000,'allowance_seconds':120})
    before=state.path.read_bytes()
    monkeypatch.setattr(module.time,'time',lambda:100000)
    assert state.execution_capacity_seconds()==230
    assert state.path.read_bytes()==before


@pytest.mark.parametrize('invalid',['{}','[]','broken','{"elapsed_seconds":NaN}'])
def test_invalid_budget_does_not_grant_execution_capacity_or_reset(tmp_path,invalid):
    state=plan(tmp_path);state.directory.mkdir();state.path.write_text(invalid)
    assert state.execution_capacity_seconds()==0
    assert state.path.read_text()==invalid


def test_real_other_process_holds_budget_lock(tmp_path):
    import subprocess,sys
    state=stored(tmp_path);before=state.path.read_bytes()
    child=subprocess.Popen([sys.executable,'-c',
        'import fcntl,sys; f=open(sys.argv[1],"a+"); fcntl.flock(f,fcntl.LOCK_EX); print("locked",flush=True); sys.stdin.read()',
        str(state.path.with_suffix('.lock'))],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
    try:
        assert child.stdout.readline().strip()=='locked'
        assert state.execution_capacity_seconds()==0
        assert state.path.read_bytes()==before
    finally:
        child.communicate(timeout=5)
    assert state.execution_capacity_seconds()>599


def test_read_uses_exact_existing_plan_identity(tmp_path):
    from video_processing.utils.codex_subtitle_provider import codex_subtitle_capacity
    state=exhausted_state(tmp_path);context=build_translation_context([TEXT]).to_prompt_context();before=state.path.read_bytes()
    kwargs=dict(state_dir=tmp_path/'codex_text_cache',model='gpt-5.6-luna',effort='medium',
        batch_size=50,total_timeout=900,request_timeout=120)
    assert codex_subtitle_capacity([TEXT],context,**kwargs)==0
    assert codex_subtitle_capacity([TEXT+' changed'],context,**kwargs)==900
    assert len(list(state.directory.glob('*.json')))==1 and state.path.read_bytes()==before


def test_flag_off_does_not_inspect_or_create_budget(tmp_path):
    from video_processing.utils.subtitle_provider_window import fallback_capacity_seconds
    cfg=config(tmp_path);cfg.subtitle_provider_budget_allocation_enabled=False
    assert fallback_capacity_seconds([TEXT],'context',cfg) is None
    assert not (tmp_path/'codex_text_cache').exists()


@pytest.mark.parametrize(('capacity','expected'),[(0,160),(30,150),(150,110),(600,60),(float('nan'),160)])
def test_reserve_never_exceeds_execution_capacity_or_original_limit(capacity,expected):
    from video_processing.utils.subtitle_provider_window import candidate_deadline
    end=candidate_deadline(600,['gemini','deepseek','google','codex'],0,now=0,
        total_seconds=600,quality_seconds=120,fallback_seconds=300,fallback_capacity=capacity)
    assert end==expected
