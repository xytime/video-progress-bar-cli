"""有明确人工确认及原片绑定的单片字幕版式，不作为自动 A/B 回退。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-23 | Codex | 为 i1WsMclsgOs 保留完整原画面并使用画面外的双语区。 |
"""
from dataclasses import asdict, dataclass
from pathlib import Path

from ..utils.layout import LayoutParams


@dataclass(frozen=True)
class ApprovedCaptionLayout:
    profile: str = 'i1WsMclsgOs-framed-v1'
    source_sha256: str = '8cca6dba707efd8b7de8410ebe93ad4c52b2ab7ee249cfdb94eae88b79b70a9e'
    width: int = 675
    height: int = 1200
    x: int = 202
    y: int = 120
    subtitle_top: int = 1350
    subtitle_bottom: int = 1700
    subtitle_width: int = 940
    wrap_width: int = 750
    font_size: int = 76

    def geometry(self, width, height):
        if width * self.height != height * self.width:
            raise ValueError('单片已确认版式与源片宽高比不符，拒绝拉伸或裁切')
        return LayoutParams(self.width / width, self.width, self.height,
                            self.x, self.y, self.subtitle_top, 0)

    def payload(self):
        return asdict(self)


def approved_layout(source: Path, source_hash: str):
    if source.stem != 'i1WsMclsgOs':
        return None
    layout = ApprovedCaptionLayout()
    if source_hash != layout.source_sha256:
        raise ValueError('单片字幕版式的原片摘要不符，需要重新确认')
    return layout


def validate_segments(segments, duration):
    from ..utils.caption_checkpoints import valid_segments
    if (not valid_segments(segments, translated=True) or len(segments) != 42
            or segments[0]['start'] != 0 or abs(segments[-1]['end'] - duration) > .05):
        raise ValueError('单片字幕版式需要完整 42 段双语时间轴，拒绝缺失内容')


def picture_filters(layout):
    # 奇数宽度先在 4:4:4 下等比缩放再补画布，避免 4:2:0 将 675 静默改成 674。
    return [f'[0:v]format=yuv444p,scale={layout.new_width}:{layout.new_height},setsar=1[fg]',
            f'[fg]pad=1080:1920:{layout.video_x}:{layout.video_y}:black,format=yuv420p[merged]']
