"""Data contracts and validation for handwritten pager video pipeline.

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-08 | Antigravity | Initial implementation of contracts and validators |
| 1.1.0 | 2026-10-08 | Antigravity | Refined pen profile width to 195 and tip offset to 58.0 for clean word-level tracking |
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple


class HandwrittenPagerError(Exception):
    """Base exception for handwritten pager video errors."""
    def __init__(self, code: str, message: str):
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


@dataclass
class LyricWord:
    """Represents a single English word with precise timing and canvas geometry."""
    word: str
    start_time: float
    end_time: float
    x_start: float = 0.0
    x_end: float = 0.0
    y_bottom: float = 0.0

    @property
    def duration(self) -> float:
        return max(0.0, self.end_time - self.start_time)

    @property
    def width(self) -> float:
        return max(0.0, self.x_end - self.x_start)


@dataclass
class LyricLine:
    """Represents a bilingual lyric line pair (English + Chinese translation)."""
    line_index: int
    en_text: str
    zh_text: str
    words: List[LyricWord] = field(default_factory=list)
    y_en: float = 0.0
    y_zh: float = 0.0
    ruled_line_y: float = 0.0

    @property
    def start_time(self) -> float:
        return self.words[0].start_time if self.words else 0.0

    @property
    def end_time(self) -> float:
        return self.words[-1].end_time if self.words else 0.0


@dataclass
class PenState:
    """Represents the instantaneous physics state of the pen at time t."""
    frame_idx: int
    t: float
    x: float
    y: float
    z: float  # 0.0 = touching paper, >0.0 = lifted/hovering
    angle_deg: float  # dynamic wrist tilt angle
    is_active: bool
    active_word: Optional[str] = None


@dataclass
class HandwrittenPagerConfig:
    """Global configuration for canvas layout, physics, and rendering."""
    width: int = 1080
    height: int = 1920
    fps: int = 60
    paper_color: Tuple[int, int, int, int] = (250, 247, 242, 255)
    ruled_line_color: Tuple[int, int, int, int] = (210, 220, 230, 180)
    margin_line_color: Tuple[int, int, int, int] = (230, 175, 175, 200)
    en_ink_color: Tuple[int, int, int] = (30, 38, 52)
    zh_ink_color: Tuple[int, int, int] = (90, 100, 115)
    pen_width: int = 195
    tip_y_offset: float = 58.0  # pixels below text top to track strictly beneath word cleanly
    pen_sprite_path: Optional[str] = None

    def validate(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise HandwrittenPagerError("CONFIG_INVALID", f"Invalid canvas size: {self.width}x{self.height}")
        if self.fps not in (30, 60):
            raise HandwrittenPagerError("CONFIG_INVALID", f"FPS must be 30 or 60, got {self.fps}")


@dataclass
class CopywritingPackage:
    """Platform-compliant copy package for WeChat Channels and Douyin."""
    wechat_short_title: str
    wechat_copy: str
    douyin_title: str
    douyin_copy: str
    hashtags: List[str]

    def validate(self) -> None:
        # WeChat short title: 6-16 characters
        if not (6 <= len(self.wechat_short_title) <= 16):
            raise HandwrittenPagerError(
                "COPY_INVALID",
                f"WeChat short title length must be 6-16 chars, got {len(self.wechat_short_title)}: '{self.wechat_short_title}'"
            )
        # Douyin title: <= 30 characters
        if not (1 <= len(self.douyin_title) <= 30):
            raise HandwrittenPagerError(
                "COPY_INVALID",
                f"Douyin title length must be <= 30 chars, got {len(self.douyin_title)}: '{self.douyin_title}'"
            )
