"""从独立本地素材建立 draft AST；逐行中英配对须由作者声明。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-07 | Codex | 保留原文 span 的素材导入与未对齐词节点 |
"""
from fractions import Fraction
import json
from pathlib import Path
import shutil

from .contracts import PipelineError, digest, fingerprint, tokens, validate
from .timing import half_up


def text_lines(text):
    offset, result=0,[]
    for raw in text.splitlines(keepends=True):
        stripped=raw.strip()
        if stripped:
            start=offset+len(raw)-len(raw.lstrip())
            result.append((stripped,{'start':start,'end':start+len(stripped)}))
        offset+=len(raw)
    return result


def create_job(root, tools, *, audio, video, english, chinese, english_font, chinese_font,
               title, tag, objective, mode, duration_seconds, audio_start=0, video_start=0, vocals=None):
    """新目录内复制素材；不覆盖已有作业。显式偏移由作者声明同一录音对应。"""
    root=Path(root).resolve()
    if root.exists():
        raise PipelineError('INPUT_INVALID','作业目录已存在；拒绝覆盖')
    texts=[Path(p).read_text(encoding='utf-8') for p in (english,chinese)]
    pairs=[text_lines(t) for t in texts]
    if not pairs[0] or len(pairs[0])!=len(pairs[1]):
        raise PipelineError('TRANSLATION_MAPPING_MISSING','中英文非空行须一一对应；请先提供显式意群映射')
    duration=half_up(Fraction(str(duration_seconds))*48000)
    if duration<=0 or audio_start<0 or video_start<0:
        raise PipelineError('INPUT_INVALID','时长/偏移非法')
    sources={'source-audio':(audio,'audio'),'performer-video':(video,'video'),
             'raw-en':(english,'text'),'raw-zh':(chinese,'text'),
             'en-font':(english_font,'font'),'zh-font':(chinese_font,'font')}
    if vocals is not None:
        sources['provided-vocals']=(vocals,'audio')
    # 规格模板仅提供样式/安全区推荐值；不会沿用其假素材、词界或证据。
    template=Path(__file__).resolve().parents[3]/'docs/specs/bilingual-follow-along/timeline.example.json'
    plan=json.loads(template.read_text())
    root.mkdir(parents=True)
    (root/'assets').mkdir()
    assets=[]
    for identity,(source,kind) in sources.items():
        source=Path(source)
        target=root/'assets'/f'{identity}{source.suffix}'
        shutil.copyfile(source,target)
        asset={'id':identity,'kind':kind,'uri':str(target.relative_to(root)), 'sha256':digest(target),'byte_length':target.stat().st_size}
        if kind in {'audio','video'}:
            probe=tools.probe(target)
            streams=[s for s in probe['streams'] if s['codec_type']==kind]
            if len(streams)!=1:
                raise PipelineError('SOURCE_MAPPING_AMBIGUOUS','素材须明确只含一个目标类型 stream',[identity])
            s=streams[0]
            tb=Fraction(s['time_base'])
            asset.update(duration_tick=half_up(Fraction(str(s.get('duration',probe['format']['duration'])))*48000),
                         native_time_base={'numerator':tb.numerator,'denominator':tb.denominator},
                         pts_origin_tick=half_up(Fraction(str(s.get('start_time',0)))*48000), stream_index=s['index'])
            if kind=='audio':
                count=tools.count_samples(target,s['index'],int(s['sample_rate']),s['channels'],root)
                asset.update(sample_rate=int(s['sample_rate']),channels=s['channels'],sample_count=count,
                             duration_tick=half_up(Fraction(count,int(s['sample_rate']))*48000))
            else:
                asset.update(width=s['width'],height=s['height'])
        assets.append(asset)
    plan.update(timeline_id='follow-along-job-'+fingerprint(str(root))[:12],phase='draft',assets=assets,cues=[],tracks=[],motions=[])
    plan['metadata']={'title':title,'tag':tag,'exercise_objective':objective,'mode':mode,'source_language':'en',
                      'translation_language':'zh-CN','duration_tick':duration,'content_type':'BILINGUAL_FOLLOW_ALONG'}
    for role,asset_id,start in [('source_master','source-audio',audio_start),('render_master','source-audio',audio_start),('performer','performer-video',video_start)]:
        start_tick=half_up(Fraction(str(start))*48000)
        plan['tracks'].append({'id':f'{role}-track','kind':'video' if role=='performer' else 'audio','role':role,
                              'clips':[{'id':f'{role}-clip','asset_id':asset_id,'source_interval':{'start_tick':start_tick,'end_tick':start_tick+duration},
                                        'timeline_interval':{'start_tick':0,'end_tick':duration},'playback_rate':{'numerator':1,'denominator':1}}]})
    if vocals is not None:
        start_tick=half_up(Fraction(str(audio_start))*48000)
        plan['tracks'].append({'id':'vocals-track','kind':'audio','role':'alignment_vocals','clips':[{'id':'vocals-clip','asset_id':'provided-vocals',
            'source_interval':{'start_tick':start_tick,'end_tick':start_tick+duration},'timeline_interval':{'start_tick':0,'end_tick':duration},'playback_rate':{'numerator':1,'denominator':1}}]})
    token_index=0
    for index,((en,en_span),(zh,zh_span)) in enumerate(zip(*pairs),1):
        words=[]
        for token in tokens(en):
            words.append({'id':f'word-{token_index}','text':token.group(),'alignment_text':token.group().lower(),
                          'origin_token_ids':[f'raw-en:{token_index}'],'display_span':{'start':token.start(),'end':token.end()},
                          'interval':None,'timing_status':'unaligned','alignment_score':None,'evidence_ref':None,'glyph_boxes':[],
                          'highlight':{'mode':'sweep','style_id':'en-main'}})
            token_index+=1
        plan['cues'].append({'id':f'cue-{index}','origin_line_id':f'line-{index}','occurrence_index':0,
                            'source_asset_id':'raw-en','source_span':en_span,'english_text':en,'english_style_id':'en-main',
                            'translation':{'text':zh,'style_id':'zh-main','source_asset_id':'raw-zh','source_span':zh_span,'meaning_group_id':f'meaning-{index}','sync_mode':'cue'},
                            'voice_id':'lead','interval':None,'boundary_reason':'source_line','words':words,'layout':None})
    for layer in plan['layers']:
        layer['visible_interval']={'start_tick':0,'end_tick':duration}
        if layer['kind']=='video':
            layer['track_id']='performer-track'
        if layer['kind']=='lyrics':
            layer['cue_ids']=[c['id'] for c in plan['cues']]
        if layer['id'].startswith('header-'):
            layer['text']={'header-title':title,'header-tag':tag,'header-objective':objective}[layer['id']]
    plan['policy']['alignment'].update(adapter='unconfigured',model_id='unconfigured',model_revision='unconfigured',weights_sha256='0'*64)
    evidence=root/'input-evidence.json'
    evidence.write_text(json.dumps({'declared_audio_video_correspondence':True,'audio_start_seconds':audio_start,'video_start_seconds':video_start,
                                    'duration_seconds':duration_seconds,'line_pairing':'author-declared'},ensure_ascii=False,indent=2))
    plan['provenance']=[{'component':'local-job-import','version':'1','actual_device':'not_executed',
                        'input_hashes':[{'id':a['id'],'sha256':a['sha256']} for a in assets],
                        'evidence_ref':{'uri':evidence.name,'sha256':digest(evidence)}}]
    validate(plan,root)
    target=root/'timeline.json'
    target.write_text(json.dumps(plan,ensure_ascii=False,indent=2))
    return target
