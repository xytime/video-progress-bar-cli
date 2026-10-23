"""原位字幕几何、修补边界及凭证的隔离回归。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.2.0 | 2026-10-23 | Codex | 实片全扫描、百分比和数字、双向轨迹、孤帧及背景文字保护。 |
| 1.1.0 | 2026-10-23 | Codex | 第169帧单字形拆框及缺失相邻合框证据的阻断回归。 |
| 1.0.0 | 2026-10-21 | Codex | 无 host OCR/网络的纯数据门禁与摘要失效回归。 |
"""
import json
from pathlib import Path
import cv2
import numpy as np
import pytest
from video_processing.processors import burned_caption_repair as repair


def row(text="the cats", top=.70, confidence=1):
    return dict(text=text,confidence=confidence,box=[.2,top,.8,top+.03])


def test_detection_anchor_and_static_logo():
    logo=dict(text='NEWS',confidence=1,box=[.01,.7,.15,.73])
    frames=[[row("the cats"),logo],[row("the dogs"),logo]]
    selected, center=repair._classify(frames,[dict(text="the cats the dogs",start=0,end=2)],30)
    assert len(selected)==2 and all(len(v)==1 for v in selected)
    assert center==pytest.approx(.715)


@pytest.mark.parametrize('frames,segments',[
    ([[row(confidence=.5)]],[dict(text="the cats",start=0,end=2)]),
    ([[row("unknown sentence")],[row("other words")]],[dict(text="the cats",start=0,end=2)]),
    ([[row(top=.4),row(top=.8)]],[dict(text="the cats",start=0,end=2)]),
    ([[row()]],[dict(text="the cats",start=10,end=12)]),
])
def test_uncertain_moving_or_unaligned_text_stops(frames,segments):
    with pytest.raises(ValueError):repair._classify(frames,segments,30)


def test_no_detected_text_changes_no_pixels():
    assert repair._classify([[],[]],[],30)==([[],[]],None)
    assert not repair._mask(np.zeros((640,360,3),np.uint8),[]).any()


def split_glyph_frames():
    main=dict(text='STILL 7.4',confidence=1,box=[.222222,.784375,.711111,.846875])
    glyph=dict(text='O',confidence=1,box=[.694444,.790625,.766667,.834375])
    merged=dict(text='STILL 7.4 0',confidence=1,box=[.221919,.783529,.766970,.847721])
    return [[merged],[main,glyph],[merged]]


def test_real_frame_169_glyph_kept_in_caption_mask_with_neighbor_evidence():
    frames=split_glyph_frames()
    selected,_=repair._classify(frames,[dict(text='Mortgages still 7.4 percent.',start=0,end=1)],30)
    assert selected[1] == [r['box'] for r in frames[1]]


@pytest.mark.parametrize('change',['no_neighbor','other_word','off_baseline','unrelated_asr','low_confidence'])
def test_split_glyph_without_complete_evidence_still_blocks(change):
    frames=split_glyph_frames()
    text='Mortgages still 7.4 percent.'
    if change=='no_neighbor': frames=[frames[1]]
    if change=='other_word': frames[1][1]['text']='UNKNOWN'
    if change=='off_baseline': frames[1][1]['box'][1:4:2]=[.60,.64]
    if change=='unrelated_asr': text='Entirely different speech.'
    if change=='low_confidence': frames[1][1]['confidence']=.7
    with pytest.raises(ValueError):repair._classify(frames,[dict(text=text,start=0,end=1)],30)


def test_real_full_scan_and_background_obstacles_are_preserved():
    import gzip
    from video_processing.processors.source_caption_fallback import fallback_geometry
    path=Path(__file__).parents[1]/'fixtures/source_caption_i1WsMclsgOs.json.gz'
    data=json.loads(gzip.decompress(path.read_bytes()))
    frames=[o['rows'] for o in data['observations']]
    before=json.dumps(frames)
    selected,_=repair._classify(frames,data['segments'],30)
    assert len(selected)==4061 and sum(bool(x) for x in selected)==4046
    assert selected[169]==[r['box'] for r in frames[169]]
    assert selected[173]==[r['box'] for r in frames[173] if r['text']=='PERCENT']
    assert selected[176]==[r['box'] for r in frames[176] if r['text']=='PERCENT']
    assert selected[2312]==[r['box'] for r in frames[2312] if r['text']=='TREASURY']
    geometry=fallback_geometry(selected,data['observations'],640,30)
    background=next(r['box'] for r in frames[2312] if r['text']=='9')
    assert background in geometry['frames'][2312]['text']
    assert json.dumps(frames)==before


@pytest.mark.parametrize('text,spoken',[
    ('PERCENT','still 7.40%'),('TENYEAR','the 10 year treasuries'),
    ('ITS 2020',"It's 2020"),('2.3','roughly 2.3 percentage points'),
    ('74','7.40%'),('HUNDRED','roughly 179'),('B-N-D','the fund BND'),
])
def test_spoken_and_written_forms_locate_without_changing_text(text,spoken):
    frames=[[row(text)]]
    assert repair._classify(frames,[dict(text=spoken,start=0,end=1)],30)[0][0]
    assert frames[0][0]['text']==text


@pytest.mark.parametrize('text,spoken',[('100','1'),('9','179'),('5.5','6.5')])
def test_numeric_caption_contract_rejects_different_values(text,spoken):
    assert not repair._numeric_caption(text,spoken)
    with pytest.raises(ValueError):
        repair._classify([[row(text)]],[dict(text=spoken,start=0,end=1)],30)


def test_centered_short_reply_needs_independent_evidence_on_both_sides():
    anchor=row('the cats'); reply=row('HMM');reply['box'][0:3:2]=[.35,.65]
    segments=[dict(text='the cats',start=0,end=1)]
    assert repair._classify([[anchor],[reply],[anchor]],segments,30)[0][1]
    for frames in ([[reply],[anchor]],[[anchor],[reply]],[[reply]]):
        with pytest.raises(ValueError):repair._classify(frames,segments,30)
    with pytest.raises(ValueError):
        repair._classify([[anchor]]+[[]]*30+[[reply]]+[[]]*30+[[anchor]],segments,30)


def test_split_line_ocr_typo_requires_both_merged_neighbors():
    anchor=dict(text='AND BY',confidence=1,box=[.294,.784,.705,.84])
    split=[dict(text='ANDI',confidence=1,box=[.294,.784,.578,.837]),
           dict(text='BY',confidence=1,box=[.555,.784,.705,.837])]
    segments=[dict(text='And by the summer',start=0,end=1)]
    assert repair._classify([[anchor],split,[anchor]],segments,30)[0][1] == [r['box'] for r in split]
    for frames in ([split,[anchor]],[[anchor],split],[[anchor],[dict(split[0],text='UNKNOWN'),split[1]],[anchor]]):
        with pytest.raises(ValueError):repair._classify(frames,segments,30)


def test_low_confidence_recovery_requires_immediate_identical_neighbors():
    anchor=row('the cats'); glitch=row('garbled',confidence=.3)
    segments=[dict(text='the cats the dogs',start=0,end=1)]
    assert repair._classify([[anchor],[glitch],[anchor]],segments,30)[0][1]
    for frames in ([[anchor],[glitch],[glitch],[anchor]],
                   [[anchor],[glitch],[row('the dogs')]]):
        with pytest.raises(ValueError):repair._classify(frames,segments,30)


def test_unknown_in_caption_band_and_second_supported_track_are_not_dropped():
    anchor=row('the cats',top=.78)
    background=row('9',top=.63)
    segments=[dict(text='the cats',start=0,end=1)]
    selected,_=repair._classify([[anchor],[anchor,background],[anchor]],segments,30)
    assert selected[1]==[anchor['box']]
    with pytest.raises(ValueError):repair._classify([[anchor,background]],segments,30)
    unknown=row('unknown sentence',top=.78)
    with pytest.raises(ValueError):repair._classify([[anchor],[unknown],[anchor]],segments,30)
    # 有第二条独立 ASR 字幕时保留它，仍由既有跨区域门禁决定是否安全。
    upper=row('the dogs',top=.55)
    with pytest.raises(ValueError):
        repair._classify([[anchor,upper]]*3,[dict(text='the cats the dogs',start=0,end=1)],30)


def test_position_change_splits_caption_time_in_place(tmp_path):
    frames=[[row(top=.7)],[row(top=.4)]]
    rows,center=repair._classify(frames,[dict(text='the cats',start=0,end=2)],1)
    prepared=repair.PreparedCaptions(tmp_path/'clip',center,'hash',tmp_path/'plan',repair._anchors(rows,1))
    spans=repair.caption_spans(prepared,.5,1.5)
    assert spans==[(.5,1.0,pytest.approx(.715)),(1.0,1.5,pytest.approx(.415))]


def test_only_glyph_region_masked_and_bright_background_refused():
    frame=np.zeros((640,360,3),np.uint8)
    cv2.putText(frame,'cats',(80,465),cv2.FONT_HERSHEY_SIMPLEX,.6,(255,255,255),2)
    box=[.2,.69,.65,.74]
    mask=repair._mask(frame,[box])
    assert mask.any() and not mask[:430].any() and not mask[480:].any()
    with pytest.raises(ValueError):repair._mask(np.full_like(frame,240),[box])


def test_neighboring_book_box_is_not_caption_residue():
    caption = [.349, .428, .645, .463]
    book = dict(text='book title', box=[.227, .234, .734, .442])
    assert not repair._residual_text([book], [caption])
    assert repair._residual_text([dict(text='a', box=[.35,.429,.37,.46])], [caption])
    assert repair._residual_text([dict(text='residue', box=[.34,.42,.65,.465])], [caption])


def test_old_or_mutated_receipt_cannot_satisfy_checkpoint(tmp_path,monkeypatch):
    source=tmp_path/'source.mp4';source.write_bytes(b'original')
    ass=source.with_suffix('.ass');ass.write_text('captions')
    output=tmp_path/'vertical.mp4';output.write_bytes(b'output')
    plan=tmp_path/'plan.json';plan.write_text('{}')
    monkeypatch.setattr(repair,'_probe',lambda path:(360,640,30,1))
    assert not repair.render_receipt_matches(output,source)
    prepared=repair.PreparedCaptions(source,.7,repair.digest(source),plan)
    repair.seal_render(output,source,ass,prepared)
    assert repair.render_receipt_matches(output,source)
    ass.write_text('different captions')
    assert not repair.render_receipt_matches(output,source)
    source.write_bytes(b'different source')
    with pytest.raises(ValueError):repair.seal_render(output,source,ass,prepared)
