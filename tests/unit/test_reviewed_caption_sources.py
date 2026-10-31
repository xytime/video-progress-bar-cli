"""具名原片不能扩散为未知画面文字的通用豁免。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-01 | Codex | 验证原片/对白绑定及字幕区不会覆盖原画面。 |
"""
from pathlib import Path

import pytest

from video_processing.processors.approved_caption_layout import approved_layout
from video_processing.processors.reviewed_caption_sources import (
    SOURCES, reviewed_layout, validate_reviewed_timeline,
)


def test_unknown_source_has_no_automatic_framed_exemption():
    assert reviewed_layout(Path('unknown.mp4'), 'a' * 64) is None
    assert validate_reviewed_timeline([], 123., 'a' * 64) is False


@pytest.mark.parametrize('name', SOURCES)
def test_framed_recovery_preserves_whole_picture_and_requires_exact_source(name):
    row = SOURCES[name]
    result = approved_layout(Path(name + '.mp4'), row['source_sha256'])
    geometry = result.geometry(360, 640)
    assert (geometry.new_width, geometry.new_height) == (675, 1200)
    assert geometry.video_y + geometry.new_height < result.subtitle_top
    assert result.subtitle_bottom <= 1920
    with pytest.raises(ValueError, match='摘要不符'):
        approved_layout(Path(name + '.mp4'), 'a' * 64)


@pytest.mark.parametrize('name', SOURCES)
def test_truncated_or_changed_dialogue_cannot_use_reviewed_layout(name):
    row = SOURCES[name]
    with pytest.raises(ValueError, match='对白或时间轴变化'):
        validate_reviewed_timeline([dict(start=0., end=1., text='Changed', zh_text='已变更')],
                                  row['duration'], row['source_sha256'])
    with pytest.raises(ValueError, match='完整双语时间轴与原片时长'):
        validate_reviewed_timeline([], row['duration'] + 3, row['source_sha256'])
