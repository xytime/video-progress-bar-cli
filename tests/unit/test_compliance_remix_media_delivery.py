"""媒体与交付整改回归；模型及平台调用禁止。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-25 | GPT-6.1 Sol | 纯演练、能力闸及真实短源拼接回归 |
"""
import asyncio
import copy
import subprocess
from types import SimpleNamespace

import pytest

from video_processing.compliance_remix.remix_pipeline import ComplianceVideoRemixPipeline
from video_processing.compliance_remix.video_compositor import VideoCompositor


def manifest():
    return dict(id='synthetic_demo',title='市场观察',description='合成测试内容',cover_title='市场成本长期观察',cover_subtitle='观察',cover_label='研究',category='财经',badge_text='观察',keywords=['市场'],content_hints=['研究'],chapters=[dict(index=1,text='市场关注长期成本。',clauses=[['市场关注长期成本。',3.0]])],cards=[],raw_shots=[[0,3]],comparison_table=[dict(timestamp_range='00:00 - 00:03',source_english_gist='Synthetic source evidence.',remix_chinese_commentary='市场关注长期成本。',reframing_rationale='解释商业成本。')])


def test_dry_run_no_media_or_file_side_effects(tmp_path):
    work = tmp_path / 'absent'
    pipeline = ComplianceVideoRemixPipeline(work)
    result = asyncio.run(pipeline.execute_full_pipeline(manifest(),tmp_path/'absent.mp4',dry_run=True))
    assert result['status']=='VALIDATED' and result['upload_status']=='NOT_SUBMITTED'
    assert not work.exists() and pipeline.audio_mixer is None and pipeline.compositor is None


def test_invalid_manifest_before_any_media(tmp_path):
    pipeline = ComplianceVideoRemixPipeline(tmp_path/'absent')
    value=manifest();value['raw_shots']=[[0,float('nan')]]
    with pytest.raises(ValueError):asyncio.run(pipeline.execute_full_pipeline(value,'absent'))
    assert not pipeline.work_dir.exists() and pipeline.audio_mixer is None


def test_no_permit_blocks_production(tmp_path):
    pipeline = ComplianceVideoRemixPipeline(tmp_path/'absent')
    with pytest.raises(PermissionError):asyncio.run(pipeline.execute_full_pipeline(manifest(),'absent'))
    assert not pipeline.work_dir.exists()


@pytest.mark.parametrize('output', [' ... bass A->A unrelated', 'configuration --enable-libass', ' ... subtitles V->V subtitles'])
def test_ass_capability_exact_name(monkeypatch,output):
    monkeypatch.setattr(subprocess,'run',lambda *a,**kw:SimpleNamespace(returncode=0,stdout=output,stderr='--enable-libass'))
    assert not VideoCompositor._supports_ass_filter('/explicit/ffmpeg')


def test_ass_capability_positive(monkeypatch):
    monkeypatch.setattr(subprocess,'run',lambda *a,**kw:SimpleNamespace(returncode=0,stdout=' ... ass V->V Render ASS subtitles',stderr=''))
    assert VideoCompositor._supports_ass_filter('/explicit/ffmpeg')


def test_all_ffmpeg_candidates_missing_ass(monkeypatch):
    monkeypatch.setattr(VideoCompositor,'_supports_ass_filter',staticmethod(lambda path:False))
    with pytest.raises(RuntimeError,match='ass'):VideoCompositor('/explicit/ffmpeg')


def test_unknown_or_public_claim_remains_uncertain(tmp_path):
    pipeline=ComplianceVideoRemixPipeline(tmp_path,submission_adapter=lambda *args:{'status':'PUBLISHED'})
    result=pipeline.run_step_wechat_upload_preflight(None,None,None,manifest(),upload_now=True)
    assert result['status']=='UNCERTAIN'


def test_submission_non_dict_remains_uncertain(tmp_path):
    pipeline=ComplianceVideoRemixPipeline(tmp_path,submission_adapter=lambda *args:True)
    assert pipeline.run_step_wechat_upload_preflight(None,None,None,manifest(),upload_now=True)['status']=='UNCERTAIN'


def test_short_source_repeats_actual_duration(tmp_path):
    comp=VideoCompositor()
    source=tmp_path/'source.mp4'
    subprocess.run([comp.ffmpeg_bin,'-y','-f','lavfi','-i','color=c=blue:s=64x64:r=25','-t','0.4','-c:v','libx264',str(source)],check=True,capture_output=True)
    output=comp.extract_and_concat_broll(source,[(0,2)],tmp_path/'concat.mp4',tmp_path/'cache',target_w=64,target_h=64,min_duration=1.2)
    assert comp.probe_duration(output)>=1.2
    # 内容改变后必须产生不同缓存，即便输出名称不变。
    first=set((tmp_path/'cache').iterdir())
    comp.extract_and_concat_broll(source,[(0,0.2)],output,tmp_path/'cache',target_w=64,target_h=64,min_duration=1.2)
    assert len(set((tmp_path/'cache').iterdir())-first)==1


def test_audio_cache_content_voice_and_invalid_old_file(tmp_path,monkeypatch):
    from pydub import AudioSegment
    from video_processing.compliance_remix import audio_mixer as module
    calls=[]
    class LocalTTS:
        def __init__(self,**kwargs):pass
        async def async_synthesize(self,**kwargs):
            calls.append(kwargs['text'])
            AudioSegment.silent(duration=200).export(kwargs['output_path'],format='mp3')
    monkeypatch.setattr(module,'DoubaoTTSClient',LocalTTS)
    (tmp_path/'dragon_ch1_15x.mp3').write_bytes(b'old nonempty corrupt cache')
    def chapters(text):return [dict(index=1,text=text,clauses=[[text,1]])]
    engine=module.AudioMixerEngine()
    first=asyncio.run(engine.synthesize_chapters(chapters('first'),tmp_path))[0][1]
    assert asyncio.run(engine.synthesize_chapters(chapters('first'),tmp_path))[0][1]==first
    second=asyncio.run(engine.synthesize_chapters(chapters('second'),tmp_path))[0][1]
    third=asyncio.run(module.AudioMixerEngine(voice_id='other').synthesize_chapters(chapters('first'),tmp_path))[0][1]
    assert len(calls)==3 and len({first,second,third})==3
    first.write_bytes(b'corrupt')
    asyncio.run(engine.synthesize_chapters(chapters('first'),tmp_path))
    assert len(calls)==4


def test_all_audio_chapters_validated_before_tts(tmp_path,monkeypatch):
    from video_processing.compliance_remix import audio_mixer as module
    def forbidden(**kwargs):raise AssertionError('TTS must not initialize')
    monkeypatch.setattr(module,'DoubaoTTSClient',forbidden)
    chapters=[dict(index=1,text='valid',clauses=[['valid',1]]),dict(index=2,text='bad',clauses=[['bad',float('nan')]])]
    with pytest.raises(ValueError):asyncio.run(module.AudioMixerEngine().synthesize_chapters(chapters,tmp_path/'absent'))
    assert not (tmp_path/'absent').exists()


def test_symlink_workdir_rejected(tmp_path):
    (tmp_path/'target').mkdir();(tmp_path/'link').symlink_to(tmp_path/'target',target_is_directory=True)
    with pytest.raises(ValueError,match='符号链接'):ComplianceVideoRemixPipeline(tmp_path/'link'/'child')


def test_render_never_uses_shortest(tmp_path,monkeypatch):
    comp=object.__new__(VideoCompositor);comp.ffmpeg_bin='ffmpeg'
    comp.probe_duration=lambda path:2.0
    seen=[]
    def command(cmd,**kwargs):
        seen.append(cmd); __import__('pathlib').Path(cmd[-1]).write_bytes(b'local test')
    monkeypatch.setattr(comp,'_run_media',command)
    comp.render_final_vertical_video('broll','audio','overlay',[],'subs',tmp_path/'final.mp4')
    assert '-shortest' not in seen[0] and seen[0][seen[0].index('-t')+1]=='2.0'


@pytest.mark.parametrize('state,returncode,expected',[('SUBMITTED',0,'SUBMITTED'),('UNDER_REVIEW',0,'UNDER_REVIEW'),('UNCERTAIN',1,'UNCERTAIN'),('NOT_SUBMITTED',1,'FAILED'),('PUBLISHED',0,'UNCERTAIN')])
def test_fresh_submission_receipt_bound_to_actual_video(tmp_path,state,returncode,expected):
    video=tmp_path/'video.mp4';video.write_bytes(b'fixed local bytes')
    def adapter(video_path,cover,provenance,value,work_dir):
        import json
        receipt=work_dir/'submission_receipt.json'
        receipt.write_text(json.dumps(dict(video_id=value['id'],video_sha256=VideoCompositor._digest(video_path),status=state)))
        return dict(receipt_path=str(receipt),returncode=returncode)
    pipeline=ComplianceVideoRemixPipeline(tmp_path,submission_adapter=adapter)
    result=pipeline.run_step_wechat_upload_preflight(video,None,None,manifest(),upload_now=True)
    assert result['status']==expected


def test_old_receipt_never_reused(tmp_path):
    import json
    import os
    receipt=tmp_path/'submission_receipt.json';receipt.write_text(json.dumps(dict(status='SUBMITTED')))
    os.utime(receipt,(1,1))
    pipeline=ComplianceVideoRemixPipeline(tmp_path,submission_adapter=lambda *args:dict(receipt_path=str(receipt),returncode=0))
    assert pipeline.run_step_wechat_upload_preflight(tmp_path/'video',None,None,manifest(),upload_now=True)['status']=='UNCERTAIN'
