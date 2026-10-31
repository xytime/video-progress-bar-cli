"""原片绑定的 ASR 时间轴校验；不裁切、重排或丢弃已识别的对白。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-01 | Codex | 拒绝超过原片的识别结果，保留一秒内 Whisper 尾部舍入容差。 |
"""
import math

from .caption_checkpoints import valid_segments


def validate_asr_timeline(segments, duration):
    """严重越界需要重新识别，不能靠裁掉坏段伪装成有效检查点。"""
    if (type(duration) not in (float, int) or not math.isfinite(duration)
            or duration <= 0 or not valid_segments(segments)):
        raise ValueError('ASR_SOURCE_TIMELINE_INVALID: 原片时长或识别结构无效')
    for index, segment in enumerate(segments):
        if segment['start'] >= duration or segment['end'] > duration + 1:
            raise ValueError(
                f'ASR_SOURCE_TIMELINE_INVALID: 第 {index + 1} 段 '
                f"{segment['start']:.3f}–{segment['end']:.3f}s 超过原片 {duration:.3f}s"
            )
