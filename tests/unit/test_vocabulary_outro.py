"""片尾的字幕身份、分页、缓存与流水线连接回归。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-13 | Codex | 验证真实字幕抽取和受控渲染串联，不调用上传器 |
| 1.0.1 | 2026-10-15 | Codex | 流水线连接使用显式测试策略，保留生产独立类型开关 |
| 1.0.2 | 2026-10-17 | Codex | 复现真实长例句，验证完整目标词、原文连续片段和短句兼容 |
"""
import json
from pathlib import Path
from unittest.mock import Mock

import pysubs2
import pytest
from video_processing.processors import vocabulary_outro as vo
from video_processing.processors import vocabulary_outro_layout as layout


def subtitle(path, words=('cosmic',), start=0):
    subs = pysubs2.SSAFile()
    subs.styles['GlossaryCard'] = pysubs2.SSAStyle()
    for j, word in enumerate(words):
        subs.append(pysubs2.SSAEvent(start=start+j*1000, end=start+j*1000+900,
                                   text=f'This is {word} sound\\N这是宇宙声音'))
        subs.append(pysubs2.SSAEvent(start=start+j*1000, end=start+j*1000+900,
                                   style='GlossaryCard', text=f'词汇  {word} · 宇宙'))
    subs.save(str(path))
    return path


def test_extract_same_subtitle_deduplicates(tmp_path):
    ass = subtitle(tmp_path/'one.ass', ('cosmic', 'cosmic', 'frequency'))
    items = vo.extract_items(ass)
    assert [x['word'] for x in items] == ['cosmic', 'frequency']
    assert items[1]['timestamp'] == '00:02'
    assert items[0]['excerpt'] == 'This is cosmic sound'


def test_unmatched_glossary_and_other_time_not_used(tmp_path):
    ass = subtitle(tmp_path/'a.ass')
    subs = pysubs2.load(str(ass))
    subs.append(pysubs2.SSAEvent(start=9000,end=10000,style='GlossaryCard',text='词汇  cosmic · 宇宙'))
    subs[1].text = '词汇  wrong · 宇宙'
    subs.save(str(ass))
    assert vo.extract_items(ass) == []


def test_multiword_pairs_and_wrapped_source(tmp_path):
    ass = subtitle(tmp_path/'a.ass')
    subs = pysubs2.load(str(ass))
    subs[0].text = 'peaks and\\Ntroughs reveal frequency\\N波峰和波谷揭示频率'
    subs[1].text = r'词汇  {\fnGeorgia}peaks and troughs {\i1}· 波峰和波谷{\i0}   frequency · 频率'
    subs.save(str(ass))
    assert [i['word'] for i in vo.extract_items(ass)] == ['peaks and troughs','frequency']


def test_pagination_and_fixed_brand_cta(tmp_path):
    ass = subtitle(tmp_path/'a.ass',('one','two','three','four'))
    items = vo.extract_items(ass)
    for item in items: item.update(phonetic='/test/',pos='n.')
    cards = layout.render_cards(items,'字幕测试')
    assert len(cards) == 2 and layout.PAGE_SECONDS == 3
    assert layout.frame_at(cards,0).crop((80,1393,936,1508)).tobytes() == layout.frame_at(cards,70).crop((80,1393,936,1508)).tobytes()
    assert layout.frame_at(cards,72).crop((80,509,936,1327)).tobytes() == cards[1].crop((80,509,936,1327)).tobytes()


def test_text_never_silently_truncated():
    with pytest.raises(ValueError):
        layout.fit('unbreakable'*100, 'en', 700, 60, 30)


LONG_EXAMPLE = (
    'The moment we hear the word leader, we feel that somebody who is very confident, '
    'somebody who is getting the direction, somebody who is leading the path, '
    'somebody who is different is coming into our mind'
)


@pytest.mark.parametrize('word,text', [
    ('leader', LONG_EXAMPLE),
    ('confident', LONG_EXAMPLE),
    ('mind', LONG_EXAMPLE),
    ('The moment', LONG_EXAMPLE),
    ('coming into our mind', LONG_EXAMPLE),
    ('LEADER', LONG_EXAMPLE),
    ('leading the path', LONG_EXAMPLE),
    ('leader', 'unbreakable' * 100 + ' a leader in this example'),
])
def test_long_example_keeps_complete_target_and_measured_bounds(word, text):
    face, lines, excerpt = layout.fit_example(text, word)
    assert excerpt != text and '…' in excerpt
    assert 20 <= face.size <= 23 and len(lines) <= 2
    assert all(face.getlength(line) <= 774 for line in lines)
    core = excerpt.removeprefix('… ').removesuffix(' …')
    assert core in text and word.casefold() in core.casefold()
    start = text.index(core)
    assert start == 0 or text[start - 1].isspace()
    end = start + len(core)
    assert end == len(text) or text[end].isspace()


@pytest.mark.parametrize('text', ['This is a leader.', 'This is a leader. ' * 4])
def test_fitting_examples_stay_unchanged(text):
    _, _, excerpt = layout.fit_example(text, 'leader')
    assert excerpt == text


def test_long_example_cannot_substitute_substring_or_clip_target():
    with pytest.raises(ValueError, match='完整目标词'):
        layout.fit_example('leadership ' * 100, 'leader')
    word = 'unbreakable' * 100
    with pytest.raises(ValueError, match='容量'):
        layout.fit_example('This is ' + word + ' in context', word)


def test_display_preparation_preserves_full_source_and_every_term():
    original = dict(word='leader', excerpt=LONG_EXAMPLE, context_sentence=LONG_EXAMPLE,
                    phonetic='/ˈliːdə/', pos='n.', meaning_zh='领导者', timestamp='01:00')
    items = [dict(original) for _ in range(4)]
    prepared = layout.prepare_examples(items)
    assert len(prepared) == 4 and len(layout.render_cards(prepared, '长例句回归')) == 2
    assert all(item['context_sentence'] == LONG_EXAMPLE for item in prepared)
    assert all(item['excerpt'] != LONG_EXAMPLE for item in prepared)
    assert all(item == original for item in items)


def test_cache_bound_to_source_subtitle_layout_and_output(tmp_path, monkeypatch):
    source=tmp_path/'a.mp4';source.write_bytes(b'original')
    ass=subtitle(tmp_path/'a.ass');output=tmp_path/'a_vocab.mp4';output.write_bytes(b'complete')
    receipt={'inputs':vo.fingerprint(source,ass,'title'),'status':'rendered','output_sha256':vo.sha256(output)}
    vo.receipt_path(output).write_text(json.dumps(receipt))
    assert vo.valid_outro(source,ass,output,'title')
    assert not vo.valid_outro(source,ass,output,'changed title')
    output.write_bytes(b'truncated');assert not vo.valid_outro(source,ass,output)
    output.write_bytes(b'complete');ass.write_text(ass.read_text()+'\n');assert not vo.valid_outro(source,ass,output)
    assert not vo.valid_outro(source, tmp_path/'other.ass',output)


def test_render_cache_reused_before_media_processing(tmp_path, monkeypatch):
    source=tmp_path/'a.mp4';source.write_bytes(b'original');ass=subtitle(tmp_path/'a.ass')
    output=tmp_path/'a_vocab.mp4';output.write_bytes(b'complete')
    inputs = vo.fingerprint(source,ass,'title')
    inputs['version'] = 'approved-v4-1'  # 修复不能让已经完成的旧版成片被迫重做。
    vo.receipt_path(output).write_text(json.dumps({'inputs':inputs, 'status':'rendered','output_sha256':vo.sha256(output)}))
    monkeypatch.setattr(vo,'probe',Mock(side_effect=AssertionError('should reuse')))
    assert vo.build(source,ass,output,'title') == output
    with pytest.raises(ValueError):vo.build(source,ass,source,'title')


def test_empty_vocab_invalidates_old_receipt_without_touching_base(tmp_path,monkeypatch):
    source=tmp_path/'a.mp4';source.write_bytes(b'original');ass=subtitle(tmp_path/'a.ass',())
    output=tmp_path/'a_vocab.mp4';vo.receipt_path(output).write_text('{}')
    monkeypatch.setattr(vo,'probe',lambda _: {'format':{'duration':'2'}})
    assert vo.build(source,ass,output,'title') == source
    assert not vo.receipt_path(output).exists() and source.read_bytes()==b'original'


def test_pipeline_tracked_hook_and_actual_selection(tmp_path,monkeypatch):
    from config.settings import settings
    from video_processing.pipeline_manager import PipelineManager
    active=tmp_path/'policy.json'
    active.write_bytes((Path(__file__).resolve().parents[1]/'fixtures/vocabulary_outro_v1.json').read_bytes())
    monkeypatch.setattr(settings,'vocabulary_outro_policy_path',active)
    manager=PipelineManager.__new__(PipelineManager);manager._OUT_DIR=tmp_path
    source=tmp_path/'abc_s2_vertical.mp4';source.write_bytes(b'base')
    ass=subtitle(tmp_path/'abc_s2.ass')
    monkeypatch.setattr(manager,'_get_base_video_path',lambda *a: source)
    captured=[]
    def tracked(command,yid,**kwargs):
        captured.append((command,yid,kwargs))
        output=tmp_path/'abc_s2_vocab.mp4';output.write_bytes(b'derived')
        vo.receipt_path(output).write_text(json.dumps({'inputs':vo.fingerprint(source,ass,'title'),'status':'rendered','output_sha256':vo.sha256(output)}))
        from video_processing.utils.vocabulary_outro_policy import update_record
        update_record(tmp_path, 'abc_s2', 'RENDERED')
    monkeypatch.setattr(manager,'_run_tracked',tracked)
    manager._process_vocabulary_outro('abc_s2','abc','title',slice_index=2)
    assert captured[0][1]=='abc' and captured[0][2]['slice_index']==2
    assert str(ass) in captured[0][0] and '--publish' not in captured[0][0]
    assert manager._get_published_video_path('abc_s2')==tmp_path/'abc_s2_vocab.mp4'
    source.write_bytes(b'new base')
    with pytest.raises(RuntimeError, match='失效'):
        manager._get_published_video_path('abc_s2')


def test_mismatched_source_identity_rejected(tmp_path):
    with pytest.raises(ValueError,match='身份'):
        vo.build(tmp_path/'wrong_vertical.mp4',tmp_path/'right.ass',tmp_path/'out.mp4','title')


def test_failed_encoding_never_replaces_source_or_old_output(tmp_path,monkeypatch):
    source=tmp_path/'a.mp4';source.write_bytes(b'base');ass=subtitle(tmp_path/'a.ass')
    output=tmp_path/'a_vocab.mp4';output.write_bytes(b'previous')
    monkeypatch.setattr(vo,'probe',lambda _: {'format':{'duration':'2'}})
    monkeypatch.setattr(vo,'enrich_items',lambda *a:None)
    monkeypatch.setattr(layout,'render_outro',Mock(side_effect=RuntimeError('encoder failed')))
    with pytest.raises(RuntimeError,match='encoder failed'):
        vo.build(source,ass,output,'title')
    assert source.read_bytes()==b'base' and output.read_bytes()==b'previous'
    assert not vo.receipt_path(output).exists()
    assert not list(tmp_path.glob('.vocab-*'))


def test_gc_retains_bound_ass_for_same_final_asset(tmp_path,monkeypatch):
    from video_processing.pipeline_manager import PipelineManager
    manager=PipelineManager.__new__(PipelineManager);manager._OUT_DIR=tmp_path
    manager.db=Mock();manager.db.wallstreet_pinned_sources.return_value=[]
    monkeypatch.setattr(manager,'_preserve_subtitle_evidence',lambda *a:True)
    ass=subtitle(tmp_path/'abc.ass')
    (tmp_path/'abc_vocab.receipt.json').write_text('{}')
    manager._run_garbage_collection('abc',0,'PUBLISHED')
    assert ass.exists()
