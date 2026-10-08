"""mobile-2 实际像素、词汇原子与时码索引验收。"""
import pysubs2
import pytest
from video_processing.processors import insight_mobile as mobile
from video_processing.processors import mobile_editorial_layout as layout


def test_alignment_preserves_indices_after_one_missing_character():
    positions = [dict(char=c,x=i,y=1,width=1,line=0) for i,c in enumerate('abcdefghijk')]
    words = [dict(word='abcdfghijk',start=0,end=10)]
    aligned = layout.align_positions(positions,words)
    assert ''.join(p['char'] for p in aligned)=='abcdefghijk'
    assert all(p['start']<=p['end'] for p in aligned)
    assert aligned[4]['start']>=aligned[3]['end']
    assert aligned[5]['start']>=aligned[4]['end']


def test_meaning_inline_and_original_highlight_phrase_atomic(tmp_path):
    source = tmp_path/'v.ass'
    subs = pysubs2.SSAFile()
    text = 'A subprime crisis exposes long term risk.'
    subs.events=[pysubs2.SSAEvent(start=0,end=8000,text=text+r'\N次级贷款危机暴露长期风险。'),
                 pysubs2.SSAEvent(start=0,end=8000,style='GlossaryCard',text='词汇 subprime crisis · 次级贷款危机')]
    subs.save(str(source))
    pages = mobile.caption_pages(source,[dict(word=text,start=0,end=8)],8)
    assert ''.join(''.join(row) for p in pages for row in p['rows'])==text
    assert any(p['terms'].get('subprime crisis')=='次级贷款危机' for p in pages)
    assert any('次级贷款危机' in line for p in pages for line in p['zh'].splitlines())
    for page in pages:
        image = mobile.base()
        mobile.draw_caption(image,page)
        assert image.crop((0,1480,1080,1920)).getbbox()
        assert len(set(image.crop((0,1480,1080,1920)).getdata()))==1


def test_overflowing_hand_mark_rejected():
    image = mobile.base()
    with pytest.raises(ValueError,match='遮挡区'):
        layout.pen_stroke(image,layout.hand_circle(930,1450,'长期风险',43))


def test_caption_alignment_preserves_real_words_across_ass_boundaries(tmp_path):
    source = tmp_path/'boundary.ass'
    subs = pysubs2.SSAFile()
    subs.events = [
        pysubs2.SSAEvent(start=1000,end=3000,text=r'You understand risk.\N你理解风险。'),
        pysubs2.SSAEvent(start=3000,end=5000,text=r'You understand debt.\N你理解债务。'),
    ]
    subs.save(str(source))
    words = [dict(word='You',start=.4,end=.6),
             dict(word='understand',start=1,end=2),dict(word='risk',start=2,end=2.8),
             dict(word='You',start=2.5,end=2.7),
             dict(word='understand',start=3,end=4),dict(word='debt',start=4,end=4.8)]
    pages = mobile.caption_pages(source,words,5)
    assert len(pages)==2
    assert pages[0]['positions'][0]['start']==.4
    assert pages[1]['positions'][0]['start']==2.5
    assert ''.join(p['char'] for page in pages for p in page['positions'])=='YouunderstandriskYouunderstanddebt'
