"""音频修正与保留英文的中文补充回归；原片/时间轴变化必须拒绝。"""
import gzip,json,copy
from pathlib import Path
import pytest
import pysubs2
from video_processing.processors import reviewed_caption_sources as reviewed


def fixture():
    return json.loads(gzip.decompress((Path(__file__).parents[1]/'fixtures/source_caption_c4umlxsvAKg.json.gz').read_bytes()))['segments']


def test_correction_is_bound_non_mutating_and_idempotent(monkeypatch):
    before=fixture(); saved=copy.deepcopy(before)
    record=reviewed.SOURCES['c4umlxsvAKg']
    monkeypatch.setattr(reviewed,'digest',lambda _:record['source_sha256'])
    result=reviewed.corrected_source_segments(Path('c4umlxsvAKg.mp4'),before)
    assert before==saved
    assert 'the barrier lining blood vessels' in result[3]['text']
    assert 'apoptosis' in result[7]['text']
    assert 'Hemostatic' in result[8]['text']
    assert 'zh_text' not in result[3]
    assert reviewed.corrected_source_segments(Path('c4umlxsvAKg.mp4'),result)==result
    changed=copy.deepcopy(before);changed[0]['end']+=.1
    with pytest.raises(ValueError):reviewed.corrected_source_segments(Path('c4umlxsvAKg.mp4'),changed)
    monkeypatch.setattr(reviewed,'digest',lambda _:'changed')
    with pytest.raises(ValueError):reviewed.corrected_source_segments(Path('c4umlxsvAKg.mp4'),before)


def test_chinese_only_panel_preserves_original_and_animation(tmp_path,monkeypatch):
    record=reviewed.SOURCES['c4umlxsvAKg'];source=tmp_path/'c4umlxsvAKg.mp4';source.write_bytes(b'unchanged')
    monkeypatch.setattr(reviewed,'digest',lambda _:record['source_sha256'])
    segments=reviewed.corrected_source_segments(source,fixture())
    for s in segments:s['zh_text']='经过核实的完整中文字幕。'
    ass=reviewed.chinese_only_ass(source,record['source_sha256'],segments)
    events=pysubs2.load(ass).events
    assert len(events)==14 and source.read_bytes()==b'unchanged'
    assert all('经过核实' in e.text and 'pos(540,1400)' in e.text for e in events)
    assert not any('barrier' in e.text for e in events)
    layout=reviewed.reviewed_layout(source,record['source_sha256'])
    assert layout['width']*640==layout['height']*356
    assert layout['y']+layout['height']<layout['subtitle_top']
    segments[0]['zh_text']='长'*100
    with pytest.raises(ValueError):reviewed.chinese_only_ass(source,record['source_sha256'],segments)


def test_unreviewed_sources_unchanged():
    segments=fixture()
    assert reviewed.corrected_source_segments(Path('other.mp4'),segments) is segments
    assert reviewed.chinese_only_ass(Path('other.mp4'),'unknown',segments) is None
