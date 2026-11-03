"""B 无安全带时，保留完整原片的画面外字幕区。

依赖方向：vertical_processor → 本纯几何模块 → utils.layout；不调用模型、DB 或外层脚本。
原片所有像素均位于字幕区之外，所以不需要猜测人脸、解剖结构的语义范围。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-02 | Codex | 有界等比完整画面及独立双语区，禁止裁切、拉伸和遮盖。 |
"""
from ..utils.subtitle_failure_receipt import SubtitleReviewRequired
from dataclasses import asdict, dataclass
from math import gcd

from ..utils.layout import LayoutParams


@dataclass(frozen=True)
class SafeCaptionPanel:
    width: int
    height: int
    x: int
    y: int = 120
    subtitle_top: int = 1320
    subtitle_bottom: int = 1700
    subtitle_width: int = 940
    wrap_width: int = 800
    font_size: int = 76

    def geometry(self, width, height):
        if width*self.height != height*self.width or self.y+self.height+48 > self.subtitle_top:
            raise ValueError('B 画面外字幕区与完整原画面不分离，禁止裁切或遮盖')
        return LayoutParams(self.width/width, self.width, self.height,
                            self.x, self.y, self.subtitle_top, 0)

    def payload(self):
        return asdict(self)


def safe_panel(width, height):
    """只接收接近标准竖屏的源，且主画面至少高 1000px；不能无界缩小以通过门禁。"""
    if not (0 < width < height and .98*9/16 <= width/height <= 1.02*9/16):
        raise SubtitleReviewRequired(f'B 画面外排版不支持源宽高比 {width}×{height}；需人工处理', code='caption_safety_review')
    divisor = gcd(width, height)
    unit_w, unit_h = width//divisor, height//divisor
    multiple = min(940//unit_w, 1152//unit_h)
    panel = SafeCaptionPanel(unit_w*multiple, unit_h*multiple,
                             (1080-unit_w*multiple)//2)
    if panel.height < 1000:
        raise SubtitleReviewRequired(f'B 完整原画面只能缩至 {panel.width}×{panel.height}，低于主画面高度 1000；需人工处理', code='caption_safety_review')
    panel.geometry(width, height)
    return panel
