"""双语跟读时钟、契约、缓存故障恢复及真实编码边界。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-07 | Codex | 绝对 seek、证据拒绝和小型合成媒体集成验收 |
"""
from copy import deepcopy
from fractions import Fraction
import json
from pathlib import Path
import shutil
import subprocess

import imageio_ffmpeg
import pytest

from video_processing.follow_along.contracts import PipelineError, digest, validate
from video_processing.follow_along.cache import StageCache
from video_processing.follow_along.timing import easing, evaluate, frame_tick, frame_count, half_up, motion_value
from video_processing.follow_along.alignment import apply_word_results
from video_processing.follow_along.qa import preflight
from video_processing.follow_along.audio import MediaTools
from video_processing.follow_along_manager import FollowAlongPipeline


def example():
    root = Path(__file__).resolve().parents[2]
    return json.loads((root / 'docs/specs/bilingual-follow-along/timeline.example.json').read_text())


def test_schema_and_semantics():
    validate(example())
    bad = example()
    bad['cues'][0]['words'][1]['interval']['start_tick'] = 1
    with pytest.raises(PipelineError, match='重叠'):
        validate(bad)


def test_synthetic_never_formal(tmp_path):
    with pytest.raises(PipelineError, match='合成'):
        validate(example(), tmp_path)


def test_half_open_seek_and_rest():
    plan = example()
    assert evaluate(plan, 30)['active_word'] == 'w-1'
    assert evaluate(plan, 45)['active_word'] == 'w-2'
    assert evaluate(plan, 120)['state'] == 'REST'
    forward = {f: evaluate(plan, f) for f in (0, 30, 45, 90, 120, 150, 239, 299)}
    assert {f: evaluate(plan, f) for f in reversed(list(forward))} == forward
    assert frame_tick(plan, 299) < plan['metadata']['duration_tick']
    with pytest.raises(IndexError):
        frame_tick(plan, 300)


def test_rational_clock_no_accumulated_drift():
    plan = example()
    plan['clock']['fps'] = {'numerator': 30000, 'denominator': 1001}
    assert frame_count(plan) == 300
    assert frame_tick(plan, 299) == Fraction(299 * 48000 * 1001, 30000)
    assert half_up(Fraction(1, 2)) == 1
    assert half_up(Fraction(3, 2)) == 2


@pytest.mark.parametrize('spec', [{'type':'linear'}, {'type':'hold'}, {'type':'smoothstep'},
                                  {'type':'exponential_out','k': 5},
                                  {'type':'cubic_bezier','control_points':[.22,0,.36,1]}])
def test_easing_monotonic_endpoints(spec):
    values = [easing(i/100, spec) for i in range(101)]
    assert values[0] == pytest.approx(0, abs=1e-10)
    assert values[-1] == pytest.approx(1)
    assert values == sorted(values)


def test_bezier_solves_x_not_direct_y():
    assert easing(.5, {'type':'cubic_bezier','control_points':[.22,0,.36,1]}) == pytest.approx(.7344852703242106)


def test_cache_validates_all_artifacts_and_failed_retry(tmp_path):
    cache = StageCache(tmp_path)
    calls = []
    def run(directory):
        calls.append(1)
        (directory/'one.json').write_text('one')
        (directory/'two.json').write_text('two')
    final, record = cache.run('resolve', {'font':'a'}, run)
    assert record['state'] == 'SUCCEEDED'
    assert cache.run('resolve', {'font':'a'}, run)[1]['state'] == 'CACHE_HIT'
    (final/'two.json').unlink()
    cache.run('resolve', {'font':'a'}, run)
    assert len(calls) == 2
    def fail(directory):
        (directory/'diagnostic.log').write_text('incomplete')
        raise PipelineError('RENDER_FAILED','test')
    with pytest.raises(PipelineError):
        cache.run('render',{},fail)
    assert list((tmp_path/'render').glob('failed-*/diagnostic.log'))
    assert cache.run('render',{},run)[1]['state'] == 'SUCCEEDED'


def test_alignment_cannot_drop_or_rewrite_words():
    plan = example()
    result = {'words': []}
    with pytest.raises(PipelineError, match='丢词'):
        apply_word_results(plan, result, {})
    result['words'] = [dict(w) for c in plan['cues'] for w in c['words']]
    result['words'][0]['timing_status'] = 'estimated'
    with pytest.raises(PipelineError, match='估算'):
        apply_word_results(plan, result, {})


def test_qa_does_not_exempt_collision_group():
    plan = example()
    plan['layers'][1]['rect'] = plan['layers'][0]['rect'].copy()
    plan['layers'][1]['collision_group'] = plan['layers'][0]['collision_group']
    with pytest.raises(PipelineError, match='相撞'):
        preflight(plan)


def technical_job(tmp_path, ffmpeg):
    """只是工程夹具：色块 + 正弦波 + 人工词界，不是歌曲或口语验收。"""
    plan = example()
    plan['metadata']['synthetic_contract_example'] = False
    root = Path(__file__).resolve().parents[2]
    audio = tmp_path/'assets/original.wav'
    video = tmp_path/'assets/performer.mp4'
    audio.parent.mkdir()
    subprocess.run([ffmpeg,'-v','error','-y','-f','lavfi','-i','sine=frequency=440:duration=10','-ar','48000','-ac','2',str(audio)],check=True,timeout=30)
    subprocess.run([ffmpeg,'-v','error','-y','-f','lavfi','-i','color=c=blue:s=640x360:r=30:d=10','-c:v','libx264',str(video)],check=True,timeout=30)
    en = tmp_path/'text/english.txt';en.parent.mkdir();en.write_text('Hold on to hope.\nSing it with me.')
    zh = tmp_path/'text/chinese.txt';zh.write_text('心怀希望。\n和我一起唱。')
    evidence = tmp_path/'evidence.json';evidence.write_text('{"kind":"technical_fixture_manual_not_real_alignment"}')
    font_en = tmp_path/'assets/fonts/english.ttf';font_en.parent.mkdir()
    shutil.copy('/System/Library/Fonts/Supplemental/Arial.ttf',font_en)
    font_zh = tmp_path/'assets/fonts/chinese.otf'
    shutil.copy('/System/Library/Fonts/STHeiti Medium.ttc',font_zh)
    keep = {'performer-video':video,'source-audio':audio,'en-font':font_en,'zh-font':font_zh,'raw-en':en,'raw-zh':zh}
    plan['assets'] = [a for a in plan['assets'] if a['id'] in keep]
    for asset in plan['assets']:
        path = keep[asset['id']]
        asset.update(sha256=digest(path),byte_length=path.stat().st_size)
        if 'duration_tick' in asset:
            asset['duration_tick']=480000
        if asset['kind']=='audio':
            asset['sample_count']=480000
    plan['tracks'] = [t for t in plan['tracks'] if t['role'] != 'alignment_vocals']
    for t in plan['tracks']:
        if t['role']=='render_master':
            t['clips'][0]['asset_id']='source-audio'
        t['clips'][0]['source_interval']={'start_tick':0,'end_tick':480000}
    for cue in plan['cues']:
        cue['layout']=None
        for w in cue['words']:
            w['glyph_boxes']=[]
            w['evidence_ref']={'uri':'evidence.json','sha256':digest(evidence)}
    plan['phase']='aligned'
    for prov in plan['provenance']:
        prov['evidence_ref']={'uri':'evidence.json','sha256':digest(evidence)}
    plan['motions']=[]
    return plan


def test_real_encoder_technical_fixture_and_cache(tmp_path):
    ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
    ffprobe=shutil.which('ffprobe')
    assert ffprobe, '必需 ffprobe 缺失，不能 skip'
    plan=technical_job(tmp_path,ffmpeg)
    pipeline=FollowAlongPipeline(tmp_path,MediaTools(ffmpeg,ffprobe,120))
    receipt=pipeline.run(plan)
    assert receipt['state']=='LOCAL_PACKAGE_READY', receipt
    assert Path(receipt['video']).stat().st_size>1000
    pipeline.tools.run(['-ss','1.7','-i',receipt['video'],'-frames:v','1',tmp_path/'technical-preview.png'],tmp_path/'preview.log')
    replay=pipeline.run(plan)
    assert replay['state']=='LOCAL_PACKAGE_READY', replay
    assert all(s['state']=='CACHE_HIT' for s in replay['stages'])
    changed=deepcopy(plan)
    changed['policy']['audio']['target_lufs']=-17
    rerun=pipeline.run(changed)
    assert rerun['state']=='LOCAL_PACKAGE_READY', rerun
    states={s['stage']:s['state'] for s in rerun['stages']}
    assert states['prepare']==states['align']==states['resolve']=='CACHE_HIT'
    assert states['mix']=='SUCCEEDED'


def test_raw_chars_do_not_accept_interpolated_missing_word():
    from video_processing.follow_along.whisperx_adapter import observed_words
    words=[{'id':'a','text':'Hi','alignment_text':'hi'}, {'id':'b','text':'you','alignment_text':'you'}]
    chars=[{'char':c,'start':i*.1,'end':(i+1)*.1,'score':.8} for i,c in enumerate('hi you')]
    del chars[-1]['start']
    result=observed_words(words,chars,48000)
    assert result[0]['timing_status']=='observed'
    assert result[1]['timing_status']=='unaligned'
    assert result[1]['interval'] is None


def test_dynamic_partition_prefers_silence_and_preserves_tokens():
    from video_processing.follow_along.chunking import partition
    words=[{'text':t,'interval':{'start_tick':i*1000,'end_tick':i*1000+500}} for i,t in enumerate(['Sing','now','with','me'])]
    words[2]['interval']={'start_tick':20000,'end_tick':20500}
    words[3]['interval']={'start_tick':21000,'end_tick':21500}
    assert partition(words,3,lambda i,j:j-i,10000)==[(0,2),(2,4)]
    with pytest.raises(PipelineError,match='合法'):
        partition(words,3,lambda i,j:j-i,10000,legal_boundaries={0,4})


def test_coverage_and_symlink_escape_fail_closed(tmp_path):
    from video_processing.follow_along.contracts import local_path
    outside=tmp_path.parent/'outside';outside.mkdir(exist_ok=True)
    (tmp_path/'link').symlink_to(outside,target_is_directory=True)
    with pytest.raises(PipelineError,match='逃逸'):
        local_path(tmp_path,'link/file')


def test_model_dependency_missing_is_explicit(tmp_path):
    from video_processing.follow_along.alignment import ExternalProvider
    provider=ExternalProvider(['/nonexistent/follow-along-model-python'],'revision','a'*64)
    with pytest.raises(PipelineError) as error:
        provider.execute({},tmp_path)
    assert error.value.code=='DEPENDENCY_UNAVAILABLE'


def test_new_job_ingests_unaligned_bilingual_assets(tmp_path):
    from video_processing.follow_along.job import create_job
    tools=MediaTools(imageio_ffmpeg.get_ffmpeg_exe(),shutil.which('ffprobe'))
    source=tmp_path/'source';source.mkdir()
    fixture=technical_job(source,tools.ffmpeg)
    target=create_job(tmp_path/'job',tools,audio=source/'assets/original.wav',video=source/'assets/performer.mp4',
                      english=source/'text/english.txt',chinese=source/'text/chinese.txt',
                      english_font=source/'assets/fonts/english.ttf',chinese_font=source/'assets/fonts/chinese.otf',
                      title='Hope',tag='跟读',objective='听清词界',mode='speaking',duration_seconds=10)
    plan=json.loads(target.read_text())
    validate(plan,target.parent)
    assert plan['phase']=='draft'
    assert all(w['interval'] is None and w['timing_status']=='unaligned' for c in plan['cues'] for w in c['words'])
    receipt=FollowAlongPipeline(target.parent,tools).run(plan,'align')
    assert receipt['state']=='NEEDS_REVIEW'
    assert receipt['error']['code']=='ALIGNMENT_INCOMPLETE'
    assert receipt['stages'][-1]['state']=='FAILED'
    class CancellingTools:
        def probe(self, path):
            raise KeyboardInterrupt
    cancelled=FollowAlongPipeline(target.parent,CancellingTools()).run(plan,'align')
    assert cancelled['state']=='CANCELLED'
    with pytest.raises(PipelineError,match='覆盖'):
        create_job(target.parent,tools,audio='',video='',english='',chinese='',english_font='',chinese_font='',
                   title='',tag='',objective='',mode='speaking',duration_seconds=10)


def test_fast_cues_preserve_prior_scroll_curve():
    from video_processing.follow_along.timing import plan_scroll
    plan=example()
    layer=next(l for l in plan['layers'] if l['kind']=='lyrics')
    plan['cues'][0]['layout']['block_rect']['y']=600
    plan['cues'][1]['interval']['start_tick']=plan['cues'][0]['interval']['start_tick']+1000
    first=plan_scroll({**plan,'cues':[plan['cues'][0]]},{**layer,'cue_ids':['cue-1']})
    both=plan_scroll(plan,layer)
    for tick in range(0,48000,1000):
        assert motion_value(first['keyframes'],tick)==pytest.approx(motion_value(both['keyframes'],tick))


def test_local_cli_commands_are_registered_and_do_not_publish():
    from click.testing import CliRunner
    from cli.main import cli
    runner=CliRunner()
    help_result=runner.invoke(cli,['follow-along','--help'])
    assert help_result.exit_code==0, help_result.output
    assert '--aligner-config' in help_result.output
    init_result=runner.invoke(cli,['follow-along-init','--help'])
    assert init_result.exit_code==0, init_result.output
    assert '--same-recording' in init_result.output


def test_stage_specific_implementation_revision_invalidates_only_own_stage(tmp_path):
    cache=StageCache(tmp_path,revisions={'align':'a','resolve':'a'})
    def run(directory):
        (directory/'artifact').write_text('ok')
    cache.run('align',{},run)
    cache.run('resolve',{},run)
    changed=StageCache(tmp_path,revisions={'align':'a','resolve':'b'})
    assert changed.run('align',{},run)[1]['state']=='CACHE_HIT'
    assert changed.run('resolve',{},run)[1]['state']=='SUCCEEDED'


def test_chinese_change_reuses_english_alignment(tmp_path):
    ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
    plan=technical_job(tmp_path,ffmpeg)
    pipeline=FollowAlongPipeline(tmp_path,MediaTools(ffmpeg,shutil.which('ffprobe')))
    assert pipeline.run(plan,'resolve')['state']=='RESOLVED'
    text_path=tmp_path/'text/chinese.txt'
    text_path.write_text('心怀盼望。\n和我一起唱。')
    plan['cues'][0]['translation']['text']='心怀盼望。'
    next(a for a in plan['assets'] if a['id']=='raw-zh')['sha256']=digest(text_path)
    receipt=pipeline.run(plan,'resolve')
    assert receipt['state']=='RESOLVED',receipt
    states={s['stage']:s['state'] for s in receipt['stages']}
    assert states['prepare']==states['align']=='CACHE_HIT'
    assert states['resolve']=='SUCCEEDED'
