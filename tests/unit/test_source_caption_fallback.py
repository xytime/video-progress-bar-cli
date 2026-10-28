"""A→B 只能回到原片，整片布局和避让必须成立。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-21 | Codex | 外观拒绝、原片回退、异常不放行、上下避让及最终 ASS 布局。 |
"""
import json
import cv2
import numpy as np
import pytest
import pysubs2
from video_processing.processors import burned_caption_repair as repair
from video_processing.processors.source_caption_fallback import (
    RepairUnsuitable, appearance, repair_quality, fallback_geometry, place_fallback,
)


def test_white_backplate_black_and_colored_text_is_not_white_glyph():
    frame = np.zeros((640, 360, 3), np.uint8)
    frame[440:490, 45:315] = 245
    cv2.putText(frame, 'COMPUTE', (55, 475), cv2.FONT_HERSHEY_SIMPLEX, .8, (90, 0, 0), 2)
    with pytest.raises(RepairUnsuitable):
        appearance(frame, [[.13,.70,.87,.76]])


def test_separable_white_glyph_can_use_a():
    frame = np.zeros((640,360,3),np.uint8)
    cv2.putText(frame,'cats',(80,465),cv2.FONT_HERSHEY_SIMPLEX,.6,(255,255,255),2)
    appearance(frame, [[.2,.69,.65,.74]])
    mask = repair._mask(frame, [[.2,.69,.65,.74]])
    repair_quality(frame, cv2.inpaint(frame,mask,4,cv2.INPAINT_TELEA), mask)


def test_unmasked_picture_damage_is_not_accepted():
    before = np.zeros((100,100,3),np.uint8)
    mask = np.zeros((100,100),np.uint8);mask[40:43,40:43] = 255
    after = before.copy();after[1,1] = 255
    with pytest.raises(RepairUnsuitable):repair_quality(before,after,mask)


def test_whole_clip_above_position_uses_original_multiline_envelope():
    rows = [[[.1,.75,.8,.78],[.1,.80,.6,.83]], [[.2,.73,.7,.76]]]
    obs = [dict(rows=[],faces=[[.2,.2,.7,.5]]) for _ in rows]
    geometry = fallback_geometry(rows,obs,1920)
    side,top = place_fallback(geometry,180,canvas_height=1920)
    assert side == 'above' and top+180 < .73*1920
    assert geometry['original_band'][3] > .83


def test_below_is_used_only_when_above_is_obstructed():
    geometry = dict(original_band=[.2,.50,.8,.55],obstacles=[[.1,.20,.9,.49]])
    side,top = place_fallback(geometry,100,canvas_height=1920)
    assert side=='below' and top>.55*1920


def test_no_safe_b_position_blocks_instead_of_overlapping():
    geometry = dict(original_band=[.1,.73,.9,.85],obstacles=[[.1,.3,.9,.75]])
    with pytest.raises(ValueError,match='人工处理'):
        place_fallback(geometry,180,canvas_height=1920)


@pytest.mark.parametrize('failure',[RepairUnsuitable('底板'),RuntimeError('OCR/I/O error')])
def test_only_quality_failure_uses_original_not_partial_repair(tmp_path,monkeypatch,failure):
    source=tmp_path/'source.mp4';source.write_bytes(b'pristine')
    rows=[[[.2,.7,.8,.73]]]
    observations=[dict(rows=[dict(box=rows[0][0],text='cats')],faces=[])]
    monkeypatch.setattr(repair,'_probe',lambda p:(360,640,1,1))
    monkeypatch.setattr(repair,'_locate',lambda *a:(rows,.715,observations))
    def fail(*a):
        (a[2]/'silent.mp4').write_bytes(b'partial repair')
        raise failure
    monkeypatch.setattr(repair,'_repair_video',fail)
    if isinstance(failure,RepairUnsuitable):
        prepared=repair.prepare_source(source,[dict(start=0,end=1,text='cats')])
        assert prepared.mode=='B' and prepared.video==source
        assert source.read_bytes()==b'pristine'
        assert json.loads(prepared.plan.read_text())['clean_sha256']==repair.digest(source)
    else:
        with pytest.raises(RuntimeError):repair.prepare_source(source,[])
        assert not list(tmp_path.glob('.caption-repair/*/plan.json'))


def test_b_final_ass_uses_one_position_and_transparent_outline(tmp_path,monkeypatch):
    from video_processing.processors.vertical_processor import VerticalCaptionProcessor
    from video_processing.core.base import VideoProcessorBase
    monkeypatch.setattr(VideoProcessorBase,'_validate_input',lambda self:None)
    monkeypatch.setattr(VerticalCaptionProcessor,'_get_video_resolution',lambda self:(720,1280))
    source=tmp_path/'source.mp4';source.write_bytes(b'original')
    plan=tmp_path/'plan.json';plan.write_text('{}')
    processor=VerticalCaptionProcessor(source,bilingual=True)
    processor._prepared_captions=repair.PreparedCaptions(source,.78,repair.digest(source),plan,(),
        'B',dict(original_band=[.1,.75,.8,.84],obstacles=[]))
    segments=[dict(start=0,end=2,text='Compute in space',zh_text='太空中的计算'),
              dict(start=2,end=4,text='An excellent return on investment',zh_text='投资回报非常出色')]
    ass=processor._build_ass_file(segments)
    subtitles=pysubs2.load(str(ass))
    assert len(subtitles.events)==2 and all(e.style=='Default' for e in subtitles.events)
    placement=json.loads(plan.read_text())['placement']
    assert placement['side']=='above'
    assert placement['top']+placement['height'] < .75*1920
    assert subtitles.styles['Default'].borderstyle==1
    assert subtitles.styles['Default'].outlinecolor.a==0
    assert all('\\pos(540,' in e.text for e in subtitles.events)


def test_short_reply_requires_nearby_matching_caption_track():
    row=lambda text,y=.76:dict(text=text,confidence=1,box=[.125,y,.73,y+.04])
    segments=[dict(start=0,end=3,text='computing out there so we are the highest value computing')]
    frames=[[row('COMPUTING OUT')],[row('CORRECT. RIGHT.')],[row('HIGHEST VALUE')]]
    assert all(repair._classify(frames,segments,1)[0])
    with pytest.raises(ValueError):
        repair._classify([[row('CORRECT. RIGHT.')]],segments,1)
    with pytest.raises(ValueError):
        repair._classify([[row('COMPUTING OUT')],[row('UNKNOWN',.6)]],segments,1)


def test_ocr_cache_is_bound_to_source_worker_and_observation_digest(tmp_path,monkeypatch):
    import hashlib
    source=tmp_path/'clip.mp4';source.write_bytes(b'original')
    cache,identity=repair._scan_file(source,1);cache.parent.mkdir()
    observations=[dict(rows=[dict(text='the cats',confidence=1,box=[.2,.7,.8,.73])],faces=[])]
    data=dict(identity=identity,observations=observations,
        observations_sha256=hashlib.sha256(json.dumps(observations,sort_keys=True).encode()).hexdigest())
    repair._write(cache,data)
    target=tmp_path/'plan';target.mkdir()
    assert repair._locate(source,[dict(start=0,end=1,text='the cats')],target,1,None)[1]==pytest.approx(.715)
    def forbidden():raise RuntimeError('must rescan')
    monkeypatch.setattr(repair,'_vision',forbidden)
    data['observations'][0]['rows'][0]['text']='different';repair._write(cache,data)
    with pytest.raises(RuntimeError,match='must rescan'):
        repair._locate(source,[],target,1,None)
    source.write_bytes(b'changed')
    assert repair._scan_file(source,1)[0]!=cache


def test_timed_geometry_keeps_direction_and_avoids_current_faces():
    rows=[[[.1,.75,.8,.8]],[[.1,.71,.8,.76]]]
    obs=[dict(rows=[],faces=[[.2,.2,.7,.5]]),dict(rows=[],faces=[[.2,.2,.7,.51]])]
    geometry=fallback_geometry(rows,obs,1920,1)
    first=place_fallback(geometry,180,canvas_height=1920,start=0,end=1,side='above')
    second=place_fallback(geometry,180,canvas_height=1920,start=1,end=2,side='above')
    assert first[0]==second[0]=='above' and first[1]>second[1]


def test_a_layout_failure_rebuilds_entire_clip_from_original(tmp_path,monkeypatch):
    from video_processing.processors.vertical_processor import VerticalCaptionProcessor
    from video_processing.core.base import VideoProcessorBase
    monkeypatch.setattr(VideoProcessorBase,'_validate_input',lambda self:None)
    monkeypatch.setattr(VerticalCaptionProcessor,'_get_video_resolution',lambda self:(720,1280))
    source=tmp_path/'original.mp4';source.write_bytes(b'pristine')
    clean=tmp_path/'clean.mp4';clean.write_bytes(b'repaired')
    rows=[[[.2,.75,.8,.79]]]
    plan=tmp_path/'plan.json';repair._write(plan,dict(selected=rows,canvas=[720,1280],fps=1,mode='A'))
    repair._write(tmp_path/'ocr.json',dict(observations=[dict(rows=[],faces=[])]))
    prepared=repair.PreparedCaptions(clean,.96,repair.digest(source),plan)
    monkeypatch.setattr(repair,'prepare_source',lambda *a:prepared)
    processor=VerticalCaptionProcessor(source,bilingual=True)
    ass=processor._generate_ass_file([dict(start=0,end=1,text='Compute in space',zh_text='太空计算')])
    assert processor._prepared_captions.mode=='B' and processor._prepared_captions.video==source
    assert json.loads(processor._prepared_captions.plan.read_text())['placement']['side']=='above'
    assert len(pysubs2.load(str(ass)).events)==1


@pytest.mark.parametrize("box", [[.0444444365,.7125,.9944444365,.75625], [0,.7125,1,.75625]])
def test_full_width_verified_dialogue_uses_actual_repair_quality(box):
    frames=[[dict(text="and I think it is crazy",confidence=1,box=box)]]
    selected,center=repair._classify(frames,[dict(start=0,end=1,text="and I think it is crazy")],1)
    assert selected==[[box]] and center==pytest.approx((box[1]+box[3])/2)


@pytest.mark.parametrize("box", [[-.01,.7125,.99,.75625], [0,.7125,1.01,.75625], [.04,.7,.99,.8]])
def test_outside_or_too_tall_dialogue_still_blocks(box):
    with pytest.raises(ValueError,match="安全修补边界"):
        repair._classify([[dict(text="and I think it is crazy",confidence=1,box=box)]],
                         [dict(start=0,end=1,text="and I think it is crazy")],1)
