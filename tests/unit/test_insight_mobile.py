"""mobile-2 实际像素、词汇原子与时码索引验收。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.1 | 2026-10-10 | Codex | 覆盖真实退休金口播繁体识别、错误语音拒绝及字时码索引。 |
"""
import pysubs2
import pytest
from video_processing.processors import insight_mobile as mobile
from video_processing.processors import mobile_editorial_layout as layout


def test_retirement_traditional_asr_keeps_display_and_time_indices():
    display = '华尔街估值高歌猛进的背后，一场美国经济史上罕见的流动性挤兑正在工薪家庭隐秘上演。6%的退休计划参与者不惜承受高达37%的惩罚性税费强制提款。这标志着传统消费信贷防线已彻底枯竭。'
    recognized = '華爾街估值高歌猛進的背後一場美國經濟史上罕見的流動性擠兌正在公新家庭隱密上演6的退休計劃參與者不惜承受高達37的懲罰性稅費強制提款这標誌著傳統消費信貸房線已徹底枯竭'
    positions = [dict(char=c,x=i,y=1,width=1,line=0) for i,c in enumerate(display) if c.isalnum()]
    aligned = layout.align_positions(positions,[dict(word=recognized,start=0,end=30)])
    assert ''.join(p['char'] for p in aligned) == ''.join(c for c in display if c.isalnum())
    assert len(aligned) == len(positions)
    assert all(0 <= p['start'] <= p['end'] <= 30 for p in aligned)
    assert all(a['end'] <= b['start'] for a,b in zip(aligned,aligned[1:]))


def test_simplification_does_not_accept_unrelated_speech():
    positions = [dict(char=c,x=i,y=1,width=1,line=0) for i,c in enumerate('美国退休计划税费强制提款')]
    with pytest.raises(ValueError,match='无法可靠对齐'):
        layout.align_positions(positions,[dict(word='今天我們介紹新能源汽車工廠',start=0,end=10)])


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
