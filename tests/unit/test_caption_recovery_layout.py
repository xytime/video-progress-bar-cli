"""实际故障样片的完整双语、原片绑定与字幕区容量回归。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-29 | Codex | 验证 25 段真实字幕、原画面边界、完整时间轴和成片凭证。 |
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
from video_processing.utils.subtitle_stylist import strip_trailing_punctuation


def segments():
    path = Path(__file__).parents[1] / 'fixtures/caption_translation_W-kr-Fm3AzU.json.gz'
    return json.loads(gzip.decompress(path.read_bytes()))


def test_recovery_is_bound_to_exact_approved_source():
    approved = layout.RECOVERY_LAYOUT
    assert layout.approved_layout(Path('W-kr-Fm3AzU.mp4'), approved.source_sha256) == approved
    assert layout.approved_layout(Path('other.mp4'), approved.source_sha256) is None
    assert layout.approved_layout(Path('W-kr-Fm3AzU_slice1.mp4'), approved.source_sha256) is None
    with pytest.raises(ValueError, match='摘要'):
        layout.approved_layout(Path('W-kr-Fm3AzU.mp4'), 'different source')


@pytest.mark.parametrize('damage', ['missing', 'translation', 'start', 'end', 'duration'])
def test_recovery_requires_complete_timeline(damage):
    items, duration = segments(), 123.456667
    if damage == 'missing': items.pop(1)
    if damage == 'translation': items[2]['zh_text'] = ''
    if damage == 'start': items[0]['start'] = 1
    if damage == 'end': items[-1]['end'] = 120
    if damage == 'duration': duration = 135.366
    with pytest.raises(ValueError, match='25 段'):
        layout.validate_segments(items, duration, source_hash=layout.RECOVERY_LAYOUT.source_sha256)


def test_recovery_renders_every_real_segment_and_binds_receipt(tmp_path, monkeypatch):
    source = tmp_path / 'W-kr-Fm3AzU.mp4'
    source.write_bytes(b'fixture')
    approved = layout.RECOVERY_LAYOUT
    real_digest = repair.digest
    # 仅替代媒体探针及测试素材摘要；真实排版、字幕、计划和凭证一起验收。
    monkeypatch.setattr(repair, '_probe', lambda path: (360, 640, 24000/1001, 123.456667))
    monkeypatch.setattr(repair, 'digest', lambda path: approved.source_sha256
                        if Path(path) == source else real_digest(Path(path)))
    items = segments()
    prepared = repair.prepare_source(source, items)
    assert prepared.video == source and prepared.mode == 'FRAMED'
    p = VerticalCaptionProcessor(source, bilingual=True)
    p._prepared_captions = prepared
    monkeypatch.setattr(p, '_get_video_resolution', lambda: (360, 640))
    ass_path = p._build_ass_file(items)
    ass = pysubs2.load(str(ass_path))
    assert len(ass) == 25
    for original, event in zip(items, ass, strict=True):
        # ASS 保存精度为百分之一秒，避免浮点数 95.2 被 int 截成 95199。
        assert (event.start, event.end) == (round(original['start']*100)*10,
                                          round(original['end']*100)*10)
        text = re.sub(r'\s+', '', event.plaintext)
        for language in ('text', 'zh_text'):
            assert re.sub(r'\s+', '', strip_trailing_punctuation(original[language])) in text
        assert event.text.startswith(r'{\pos(540,1302)}')
    plan = json.loads(prepared.plan.read_text())
    assert plan['crop'] is False and plan['extra_subtitle_panel'] is True
    assert max(plan['placement']['heights']) <= 398
    assert max(plan['placement']['widths']) <= 940
    geometry = approved.geometry(360, 640)
    assert geometry.video_y + geometry.new_height < approved.subtitle_top
    assert 'crop=' not in ';'.join(layout.picture_filters(geometry))
    output = tmp_path / 'render.mp4'
    output.write_bytes(b'output')
    repair.seal_render(output, source, ass_path, prepared)
    assert repair.render_receipt_matches(output, source)
    plan['identity']['layout']['font_size'] = 10
    prepared.plan.write_text(json.dumps(plan))
    assert not repair.render_receipt_matches(output, source)
