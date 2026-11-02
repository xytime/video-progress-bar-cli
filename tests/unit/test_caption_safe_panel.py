"""B 画面外字幕区的几何、实片模板和凭证回归。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-02 | Codex | 7168 模板全时间轴及保留原画面、窄片、不可排版边界。 |
"""
import gzip
import json
from pathlib import Path

import pysubs2
import pytest

from video_processing.processors import burned_caption_repair as repair
from video_processing.processors.caption_safe_panel import safe_panel
from video_processing.processors.source_caption_fallback import fallback_geometry, place_fallback


@pytest.mark.parametrize('w,h', [(360,640),(356,640),(1080,1920)])
def test_panel_preserves_entire_picture_and_leaves_disjoint_subtitles(w,h):
    panel=safe_panel(w,h)
    geometry=panel.geometry(w,h)
    assert geometry.new_width*h==geometry.new_height*w
    assert 1000<=geometry.new_height<=1152
    assert geometry.video_y+geometry.new_height+48<=panel.subtitle_top
    assert 0<=geometry.video_x and geometry.video_x+geometry.new_width<=1080
    assert panel.subtitle_bottom<=1700


@pytest.mark.parametrize('w,h', [(350,640),(640,360),(359,640),(0,640)])
def test_panel_cannot_arbitrarily_shrink_or_crop_to_pass(w,h):
    with pytest.raises(ValueError,match='人工处理'):
        safe_panel(w,h)


def test_brand_template_full_timeline_can_use_outside_picture(tmp_path,monkeypatch):
    from video_processing.processors.vertical_processor import VerticalCaptionProcessor
    from video_processing.core.base import VideoProcessorBase
    monkeypatch.setattr(VideoProcessorBase,'_validate_input',lambda self:None)
    monkeypatch.setattr(VerticalCaptionProcessor,'_get_video_resolution',lambda self:(360,640))
    data=json.loads(gzip.decompress((Path(__file__).parents[1]/'fixtures/source_caption_q2kuwKpZO8g.json.gz').read_bytes()))
    selected,center=repair._classify([o['rows'] for o in data['observations']],data['segments'],data['fps'])
    geometry=fallback_geometry(selected,data['observations'],640,data['fps'])
    source=tmp_path/'q2kuwKpZO8g.mp4';source.write_bytes(b'pristine')
    plan=tmp_path/'plan.json';repair._write(plan,dict(mode='B',identity={'panel_sha256':repair.digest(repair.PANEL)}))
    processor=VerticalCaptionProcessor(source,bilingual=True)
    processor._prepared_captions=repair.PreparedCaptions(source,center,repair.digest(source),plan,mode='B',fallback=geometry)
    segments=[dict(s,zh_text='埃博拉病毒进入人体后，会影响免疫系统并造成血管损伤。') for s in data['segments']]
    subtitles=pysubs2.load(str(processor._build_ass_file(segments)))
    prepared=processor._prepared_captions
    assert prepared.mode=='B_PANEL' and prepared.video==source
    assert source.read_bytes()==b'pristine'
    assert len(subtitles.events)==len(segments)
    assert all(r'\pos(540,1320)' in event.text for event in subtitles.events)
    panel_plan=json.loads(prepared.plan.read_text())
    assert panel_plan['extra_subtitle_panel']
    assert len(panel_plan['placement_attempts'])==2
    assert '占用' in panel_plan['placement_attempts'][0]['reason']
    assert json.loads(plan.read_text())['mode']=='B' # 原 B 失败证据不覆盖。
    assert max(panel_plan['placement']['heights'])<=380


def test_failure_explains_original_band_candidate_and_obstacles():
    geometry=dict(original_band=[.1,.73,.9,.85],obstacles=[[.1,.3,.9,.75]])
    with pytest.raises(ValueError) as exc:
        place_fallback(geometry,180,canvas_height=1920,start=1,end=2,side='above')
    message=str(exc.value)
    assert all(term in message for term in ['原字幕带','时段 1–2','候选','占用','人工处理'])
