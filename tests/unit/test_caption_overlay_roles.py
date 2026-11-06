"""已核实实片 OCR/ASR fixture；识别画面文字时不擦除标题也不放过未知对白。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-11-02 | Codex | 多区域实片、真双路对白及仅保留 B 的大字/入场 OCR 证据回归。 |
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


def test_static_unknown_single_line_is_non_dialogue_overlay():
    # 稳定且不匹配 ASR 的中部驻留字应避让，不再因 caption_frame_uncertain 死卡。
    frames=[[dict(text='UNKNOWN WORDS',confidence=1,box=[.2,.85,.8,.88])] for _ in range(300)]
    selected, center = repair._classify(frames,[dict(text='unrelated speech',start=0,end=10)],30)
    assert center is None and not any(selected)
    ignored = non_dialogue_rows(frames,[dict(text='unrelated speech',start=0,end=10)],30,repair._caption_text_matches)
    assert ignored


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


def test_multiple_regions_are_roles_before_span_check():
    data=json.loads(gzip.decompress((Path(__file__).parents[1]/'fixtures/source_caption_c4umlxsvAKg.json.gz').read_bytes()))
    frames=[o['rows'] for o in data['observations']]
    ignored=non_dialogue_rows(frames,data['segments'],data['fps'],repair._caption_text_matches)
    frame=15
    preserved=[r['text'] for n,r in enumerate(frames[frame]) if (frame,n) in ignored]
    assert 'PATHOGENIC INVASION' in preserved
    assert any('Cellular Evasion' in text for text in preserved)
    assert any('SUBSCRIB' in text.upper() for i,n in ignored for text in [frames[i][n]['text']])
    # 完整时序证据识别信息区；前 400 帧含大字和 cells 入场 OCR 误识，仍有独立对白。
    selected,center=repair._classify(frames[:400],data['segments'],data['fps'],preserve_large_text=True)
    assert center is not None and selected[15]
    assert max(b[3] for b in selected[15])<.82
    assert all(frames[i][n]['box'] not in selected[i] for i,n in ignored if i<400)
    # 医学词与 ASR 不一致：稳定非对白可避让；若仍进入擦除候选则必须人工复核。
    ignored_full = non_dialogue_rows(frames, data['segments'], data['fps'], repair._caption_text_matches)
    try:
        selected_full, _ = repair._classify(frames, data['segments'], data['fps'], preserve_large_text=True)
    except ValueError as exc:
        assert 'alveolar' in str(exc).lower() or '不确定' in str(exc)
    else:
        for i, rows in enumerate(frames):
            for n, row in enumerate(rows):
                if 'alveolar' in row['text'].lower():
                    assert (i, n) in ignored_full or row['box'] not in selected_full[i]


def test_true_simultaneous_dialogue_remains_blocked():
    rows=[dict(text='We discuss immune cells',confidence=1,box=[.1,.64,.9,.69]),
          dict(text='Another voice explains vessels',confidence=1,box=[.1,.87,.9,.92])]
    segments=[dict(start=0,end=5,text='We discuss immune cells. Another voice explains vessels.')]
    with pytest.raises(ValueError,match='多处疑似原字幕'):
        repair._classify([rows for _ in range(150)],segments,30,preserve_large_text=True)


def test_preserved_large_dialogue_never_enters_erasure(tmp_path,monkeypatch):
    source=tmp_path/'source.mp4';source.write_bytes(b'original')
    rows=[[[.1,.65,.9,.76]]]
    observations=[dict(rows=[dict(text='immune cells',confidence=1,box=rows[0][0])],faces=[])]
    monkeypatch.setattr(repair,'_probe',lambda _: (360,640,1,1))
    monkeypatch.setattr(repair,'_locate',lambda *args:(rows,.7,observations))
    def forbidden(*args):raise AssertionError('大字对白不可擦除')
    monkeypatch.setattr(repair,'_repair_video',forbidden)
    prepared=repair.prepare_source(source,[])
    assert prepared.mode=='B' and prepared.video==source


def test_boundary_ocr_needs_three_direct_anchors_and_one_edit():
    row=lambda text:dict(text=text,confidence=1,box=[.4,.68,.62,.74])
    evidence=[[],[row('cells')],[row('cells')],[row('cells')]]
    assert repair._caption_boundary_ocr(row('cels'),evidence,0,30)
    assert not repair._caption_boundary_ocr(row('tissue'),evidence,0,30)
    assert not repair._caption_boundary_ocr(row('cels'),evidence[:3],0,30)
    assert not repair._caption_boundary_ocr(row('cel'),evidence,0,30)


def test_three_spoken_lines_cannot_be_assumed_to_be_a_chapter_pair():
    frames=[]
    for i in range(150):
        frames.append([dict(text='We discuss cells' if i<75 else 'Another voice speaks',confidence=1,box=[.1,.64,.9,.69]),
                       dict(text='IMMUNE RESPONSE',confidence=1,box=[.1,.85,.88,.885]),
                       dict(text='Blood Vessels',confidence=1,box=[.1,.9,.65,.935])])
    segments=[dict(start=0,end=5,text='We discuss cells. Another voice speaks. Immune response. Blood vessels.')]
    with pytest.raises(ValueError,match='多处疑似原字幕'):
        repair._classify(frames,segments,30,preserve_large_text=True)


def test_kinetic_title_rotating_words_are_overlay_not_dialogue():
    """同一几何框轮换短词（DOLLARS/HISTORY）；即使口播含主题词仍视为非对白 overlay。"""
    fps = 30
    words = ['BIGGEST', 'HISTORY', 'POINT', 'DOLLARS', 'HOURS']
    frames = []
    for i in range(150):
        word = words[(i // 15) % len(words)]
        frames.append([dict(text=word, confidence=1.0,
                            box=[0.26, 0.784, 0.739, 0.841])])
    segments = [dict(start=0.0, end=5.0,
                     text='the biggest crypto heist in history cost billions of dollars within hours')]
    ignored = non_dialogue_rows(frames, segments, fps, repair._caption_text_matches)
    assert ignored, 'kinetic title words should be marked non-dialogue'
    assert any(i == 99 for i, _ in ignored)


def test_isolated_tiny_glyph_fragment_is_overlay():
    """孤立单字符碎屑不构成烧录对白。"""
    fps = 24
    frames = []
    for i in range(80):
        rows = []
        if 40 <= i <= 55:
            rows.append(dict(text='G', confidence=1.0, box=[0.678, 0.616, 0.717, 0.638]))
        frames.append(rows)
    segments = [dict(start=1.0, end=3.0, text='trust the process or its all in Gods plan')]
    ignored = non_dialogue_rows(frames, segments, fps, repair._caption_text_matches)
    assert any(frames[i][n]['text'] == 'G' for i, n in ignored)


def test_isolated_digit_corner_mark_is_overlay():
    """略大的孤立数字角标不构成烧录对白。"""
    fps = 24
    frames = []
    for i in range(80):
        rows = []
        if 40 <= i <= 55:
            rows.append(dict(text='2', confidence=1.0, box=[0.717, 0.394, 0.806, 0.447]))
        frames.append(rows)
    segments = [dict(start=1.0, end=3.0, text='the crowd cheered after the final whistle')]
    ignored = non_dialogue_rows(frames, segments, fps, repair._caption_text_matches)
    assert any(frames[i][n]['text'] == '2' for i, n in ignored)




def test_image_courtesy_credit_is_overlay():
    """底部 Image courtesy / Shutterstock 图注不构成烧录对白。"""
    fps = 24
    frames = []
    for i in range(80):
        rows = []
        if 20 <= i <= 70:
            rows.append(dict(text='Image courtesy of Shutterstock', confidence=1.0,
                             box=[0.056, 0.912, 0.556, 0.934]))
        frames.append(rows)
    segments = [dict(start=0.5, end=3.0, text='cultish language shapes everyday vocabularies')]
    ignored = non_dialogue_rows(frames, segments, fps, repair._caption_text_matches)
    assert any('Shutterstock' in frames[i][n]['text'] for i, n in ignored)


def test_brief_uppercase_flash_word_is_overlay():
    """短暂全大写闪词（AT）不对齐 ASR → overlay。"""
    fps = 30
    frames = []
    for i in range(120):
        rows = []
        if 50 <= i <= 55:
            rows.append(dict(text='AT', confidence=1.0, box=[0.428, 0.784, 0.572, 0.841]))
        frames.append(rows)
    segments = [dict(start=0.0, end=4.0, text='crypto answered the question around london time')]
    ignored = non_dialogue_rows(frames, segments, fps, repair._caption_text_matches)
    assert any(frames[i][n]['text'] == 'AT' for i, n in ignored)


def test_scene_graphic_with_prior_overlay_ignores_unmatched():
    """同帧已有 overlay 时，不对齐 ASR 的中部表格字可豁免。"""
    fps = 30
    # 稳定且不对齐 ASR 的中部条先成为 overlay，再出现选票 OCR 残字。
    frames = []
    for i in range(120):
        rows = [dict(text='POLL TRACKER', confidence=1.0, box=[0.24, 0.60, 0.76, 0.65])]
        if 60 <= i <= 70:
            rows.append(dict(text='BY MAIL BA', confidence=1.0, box=[0.40, 0.395, 0.74, 0.45]))
            rows.append(dict(text='BACK HERE', confidence=1.0, box=[0.43, 0.44, 0.73, 0.49]))
        frames.append(rows)
    segments = [dict(start=0.0, end=4.0, text='millions flooded local high school gyms this morning')]
    ignored = non_dialogue_rows(frames, segments, fps, repair._caption_text_matches)
    assert any(frames[i][n]['text'] == 'BY MAIL BA' for i, n in ignored)
