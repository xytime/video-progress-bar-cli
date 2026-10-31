"""实际原片边界的回归，不以裁切异常对白获得通过。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-01 | Codex | 覆盖真实越界故障、尾部舍入及无效时长。 |
"""
from copy import deepcopy

import pytest

from video_processing.utils.asr_timeline import validate_asr_timeline


def test_old_7031_timeline_is_rejected_without_removing_or_clipping_content():
    segments = [dict(start=0., end=3.44, text='It is despicable.'),
                dict(start=120., end=146.96, text='Unverified tail')]
    original = deepcopy(segments)
    with pytest.raises(ValueError, match='第 2 段.*146.960.*121.521'):
        validate_asr_timeline(segments, 121.5214)
    assert segments == original


def test_normal_whisper_tail_rounding_is_preserved():
    segments = [dict(start=119., end=121.9, text='Final sentence.')]
    validate_asr_timeline(segments, 121.1)
    assert segments[-1]['end'] == 121.9


@pytest.mark.parametrize('segments,duration', [
    ([dict(start=121.1, end=121.5, text='Outside')], 121.1),
    ([dict(start=0., end=float('nan'), text='Invalid')], 121.),
    ([dict(start=2., end=3., text='Later'), dict(start=0., end=1., text='Earlier')], 121.),
    ([], float('nan')), ([], 0), ([], True),
])
def test_invalid_boundaries_and_duration_fail_closed(segments, duration):
    with pytest.raises(ValueError, match='ASR_SOURCE_TIMELINE_INVALID'):
        validate_asr_timeline(segments, duration)


def test_silent_source_remains_valid():
    validate_asr_timeline([], 12.)
