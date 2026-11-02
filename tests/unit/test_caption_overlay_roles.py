"""已核实实片 OCR/ASR fixture；识别画面文字时不擦除标题也不放过未知对白。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-02 | Codex | 人工门禁、一次领取、实片标题和微窄画面回归。 |
"""
import gzip,json
from pathlib import Path
import pytest
from video_processing.processors import burned_caption_repair as repair
from video_processing.processors.caption_overlay_roles import non_dialogue_rows
from video_processing.utils.layout import VerticalLayout


@pytest.mark.parametrize('yid',['q2kuwKpZO8g','OYWnj6pZvwI'])
def test_verified_title_card_nameplate_and_persistent_bar(yid):
    data=json.loads(gzip.decompress((Path(__file__).parents[1]/f'fixtures/source_caption_{yid}.json.gz').read_bytes()))
    observations=data['observations'];frames=[o['rows'] for o in observations]
    before=json.dumps(frames)
    selected,center=repair._classify(frames,data['segments'],data['fps'])
    ignored=non_dialogue_rows(frames,data['segments'],data['fps'],repair._caption_text_matches)
    assert ignored
    for i,n in ignored:
        assert frames[i][n]['box'] not in selected[i]
    if yid=='q2kuwKpZO8g':
        assert center is not None and any(selected)
        assert any(frames[i][n]['text']=='HOW EBOLA SPREADS' for i,n in ignored)
        assert selected[619] # 同帧真正对白仍须处理。
    else:
        assert center is None and not any(selected), [(i,frames[i]) for i,boxes in enumerate(selected) if boxes][:15]
        assert any(frames[i][n]['text']=='DAVID BYRNE' for i,n in ignored)
    assert json.dumps(frames)==before


def test_static_unknown_single_line_remains_blocked():
    frames=[[dict(text='UNKNOWN WORDS',confidence=1,box=[.2,.85,.8,.88])] for _ in range(300)]
    with pytest.raises(ValueError):
        repair._classify(frames,[dict(text='unrelated speech',start=0,end=10)],30)


@pytest.mark.parametrize('width,height,expected',[(356,640,(1068,1920,6)),(360,640,(1080,1920,0)),(1080,1920,(1080,1920,0))])
def test_narrow_fixture_preserves_full_picture(width,height,expected):
    layout=VerticalLayout.calculate(width,height)
    assert (layout.new_width,layout.new_height,layout.video_x)==expected
    assert layout.video_y==0
    assert layout.new_width/width==pytest.approx(layout.new_height/height)


def test_two_percent_tolerance_is_bounded(tmp_path,monkeypatch):
    source=tmp_path/'source.mp4';source.write_bytes(b'geometry-fixture')
    monkeypatch.setattr(repair,'_probe',lambda _: (356,640,30,1))
    monkeypatch.setattr(repair,'_locate',lambda *args: ([[] for _ in range(30)],None,[{'rows':[]} for _ in range(30)]))
    assert repair.prepare_source(source,[]).mode=='NONE'
    monkeypatch.setattr(repair,'_probe',lambda _: (350,640,30,1))
    with pytest.raises(ValueError,match='源片比 9:16 更窄'):
        repair.prepare_source(source,[])


def test_narrow_render_filter_uses_padding(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from video_processing.core.base import VideoProcessorBase
    from video_processing.processors.vertical_processor import VerticalCaptionProcessor
    import video_processing.processors.vertical_processor as vertical
    calls=[]
    def run(command,**kwargs):
        calls.append(command)
        return SimpleNamespace(stdout='356x640' if '-show_entries' in command else '',returncode=0)
    monkeypatch.setattr(VideoProcessorBase,'_validate_input',lambda *_: None)
    monkeypatch.setattr(vertical.subprocess,'run',run)
    monkeypatch.setattr(repair,'seal_render',lambda *args: None)
    processor=VerticalCaptionProcessor(Path('source.mp4'),output_path=tmp_path/'out.mp4',bg_blur=False)
    processor._prepared_captions=SimpleNamespace(video=processor.input_path,mode='DIRECT')
    processor._burn_subtitles(tmp_path/'source.ass')
    filters=calls[-1][calls[-1].index('-filter_complex')+1]
    assert '[0:v]scale=1068:1920[fg]' in filters
    assert 'pad=1080:1920:6:0:black' in filters
    assert 'crop=' not in filters
