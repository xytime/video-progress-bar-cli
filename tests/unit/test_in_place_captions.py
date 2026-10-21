"""原位字幕几何、修补边界及凭证的隔离回归。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
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
