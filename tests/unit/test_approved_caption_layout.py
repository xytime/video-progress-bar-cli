"""单片确认不能扩散到其它素材；真实 42 段双语必须完整放入独立区域。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-23 | Codex | 原片绑定、完整时间轴、真实字幕边界及成片凭证失效回归。 |
"""
import gzip
import json
import re
from pathlib import Path

import pysubs2
import pytest

from video_processing.processors import approved_caption_layout as layout
from video_processing.processors import burned_caption_repair as repair
from video_processing.processors.vertical_processor import VerticalCaptionProcessor
from video_processing.core.base import VideoProcessingError
from video_processing.utils.caption_checkpoints import translation_contract
from video_processing.utils.subtitle_stylist import strip_trailing_punctuation


def segments():
    path = Path(__file__).parents[1] / 'fixtures/caption_translation_i1WsMclsgOs.json.gz'
    return json.loads(gzip.decompress(path.read_bytes()))


def test_approval_requires_subject_and_exact_source():
    approved = layout.ApprovedCaptionLayout()
    assert layout.approved_layout(Path('i1WsMclsgOs.mp4'), approved.source_sha256) == approved
    assert layout.approved_layout(Path('zUv-6-FPQfw.mp4'), approved.source_sha256) is None
    assert layout.approved_layout(Path('i1WsMclsgOs_slice1.mp4'), approved.source_sha256) is None
    with pytest.raises(ValueError, match='摘要'):
        layout.approved_layout(Path('i1WsMclsgOs.mp4'), 'other source')


def test_picture_is_proportional_outside_caption_zone():
    approved = layout.ApprovedCaptionLayout()
    geometry = approved.geometry(360, 640)
    assert geometry.new_width * 640 == geometry.new_height * 360
    assert geometry.video_y + geometry.new_height < approved.subtitle_top
    assert approved.subtitle_bottom <= 1700
    filters = ';'.join(layout.picture_filters(geometry))
    assert 'crop=' not in filters and 'scale=675:1200' in filters
    assert 'pad=1080:1920:202:120:black' in filters
    with pytest.raises(ValueError, match='宽高比'):
        approved.geometry(360, 700)


@pytest.mark.parametrize('damage', ['missing', 'translation', 'start', 'end'])
def test_partial_timeline_is_refused(damage):
    items = segments()
    if damage == 'missing': items.pop(1)
    if damage == 'translation': items[2]['zh_text'] = ''
    if damage == 'start': items[0]['start'] = 1
    if damage == 'end': items[-1]['end'] = 130
    with pytest.raises(ValueError, match='42 段'):
        layout.validate_segments(items, 135.366)


def processor(tmp_path):
    source = tmp_path / 'i1WsMclsgOs.mp4'
    source.write_bytes(b'isolated media stand-in')
    plan = tmp_path / 'plan.json'
    plan.write_text('{}')
    p = VerticalCaptionProcessor(source, bilingual=True, title='三十年期房贷为何高企')
    p._prepared_captions = repair.PreparedCaptions(source, None,
        layout.ApprovedCaptionLayout().source_sha256, plan, mode='FRAMED')
    return p


def test_real_bilingual_content_and_timing_survive_layout(tmp_path, monkeypatch):
    p = processor(tmp_path)
    monkeypatch.setattr(p, '_get_video_resolution', lambda: (360, 640))
    items = segments()
    ass = pysubs2.load(str(p._build_ass_file(items)))
    assert len(ass) == 42
    for original, event in zip(items, ass, strict=True):
        assert (event.start, event.end) == (int(original['start']*1000), int(original['end']*1000))
        text = re.sub(r'\s+', '', event.plaintext)
        for language in ('text', 'zh_text'):
            assert re.sub(r'\s+', '', strip_trailing_punctuation(original[language])) in text
        assert event.text.startswith(r'{\pos(540,1350)}')
    placement = json.loads(p._prepared_captions.plan.read_text())['placement']
    assert placement['segments'] == 42
    assert max(placement['heights']) <= 350 and max(placement['widths']) <= 940


def test_long_unbreakable_content_stops_without_truncation(tmp_path, monkeypatch):
    p = processor(tmp_path)
    monkeypatch.setattr(p, '_get_video_resolution', lambda: (360, 640))
    items = segments()
    items[0]['text'] = 'X'*1000
    with pytest.raises(VideoProcessingError, match='放不下'):
        p._build_ass_file(items)
    assert not p.input_path.with_suffix('.ass').exists()


def test_new_audio_is_refused_before_generation(tmp_path):
    p = processor(tmp_path)
    p.tts_provider = 'edge'
    with pytest.raises(ValueError, match='原声'):
        p._burn_subtitles(tmp_path/'unused.ass')


def test_receipt_rejects_layout_or_source_change(tmp_path, monkeypatch):
    # 两个外部替身：仅媒体探针、特定测试素材的摘要；其余真实计划和 ASS。
    real_digest = repair.digest
    source = tmp_path/'i1WsMclsgOs.mp4'; source.write_bytes(b'fixture')
    monkeypatch.setattr(repair, '_probe', lambda path: (360,640,30,135.366))
    monkeypatch.setattr(repair, 'digest', lambda path: layout.ApprovedCaptionLayout().source_sha256
                        if Path(path)==source else real_digest(Path(path)))
    prepared = repair.prepare_source(source, segments())
    assert prepared.video == source and prepared.mode == 'FRAMED'
    ass = source.with_suffix('.ass'); ass.write_text('full bilingual ASS')
    output = tmp_path/'vertical.mp4'; output.write_bytes(b'output')
    repair.seal_render(output, source, ass, prepared)
    assert repair.render_receipt_matches(output, source)
    plan = json.loads(prepared.plan.read_text())
    plan['identity']['layout']['subtitle_top'] = 1100
    prepared.plan.write_text(json.dumps(plan))
    assert not repair.render_receipt_matches(output, source)


def test_layout_does_not_invalidate_upstream_translation():
    from config.settings import settings
    from video_processing.processors.caption_processor import AutoCaptionProcessor
    assert translation_contract(VerticalCaptionProcessor.__new__(VerticalCaptionProcessor), settings) == \
        translation_contract(AutoCaptionProcessor.__new__(AutoCaptionProcessor), settings)
