# -*- coding: utf-8 -*-
"""Layout utilities for video processing.

# Modification History
| Version | Date       | Author                    | Description |
| ------- | ---------- | ------------------------- | ----------- |
| 1.0.0   | 2026-05-21 | Claude_Sonnet_4.6_Thinking | 初始创建 |
| 1.1.0   | 2026-06-07 | Gemini_3.5_Flash_planning | 竖屏输入视频不进行TOP_MARGIN偏移裁切，居中显示，标有 # [Gemini_3.5_Flash_planning] |
"""
from dataclasses import dataclass
from typing import Tuple

@dataclass
class LayoutParams:
    scale_factor: float
    new_width: int
    new_height: int
    video_x: int
    video_y: int
    subtitle_margin_v: int
    title_y: int

class VerticalLayout:
    """
    Handles coordinate calculations for 9:16 Vertical Video Layout (Three-Section).
    Canvas: 1080x1920
    """
    CANVAS_WIDTH = 1080
    CANVAS_HEIGHT = 1920
    
    # Zone Definitions
    # Top Title Zone: 0 - 450
    # Video Zone: Middle (approx 600-1200)
    # Subtitle Zone: 1264 - 1500 (Safe area above bottom UI)
    
    # Layout Constants
    # Title Zone: Top 350px
    TOP_MARGIN = 350
    DEFAULT_TITLE_Y = 150
    
    # Subtitle Zone: Keep at bottom safety area
    # User feedback: "Below video a bit, not centered in black area".
    # Video ends approx 350 + 810 = 1160.
    # We want subs around 1200-1250.
    # MarginV = 1920 - 1250 = 670.
    DEFAULT_SUBTITLE_MARGIN_V = 650 

    @classmethod
    def calculate(cls, video_w: int, video_h: int) -> LayoutParams:
        """
        Calculate layout parameters for a given input video.
        """
        # 1. Scale Video to Width 1080 (maintain aspect ratio)
        scale = cls.CANVAS_WIDTH / video_w
        new_w = cls.CANVAS_WIDTH
        new_h = int(video_h * scale)
        
        # 2. Position Video (Fixed Top Margin instead of Center for landscape)
        # For vertical videos, center vertically to avoid cropping the bottom.
        video_x = 0
        if video_w < video_h:
            # [Gemini_3.5_Flash_planning] For vertical inputs, center vertically
            video_y = max(0, (cls.CANVAS_HEIGHT - new_h) // 2)
        else:
            video_y = cls.TOP_MARGIN
        
        return LayoutParams(
            scale_factor=scale,
            new_width=new_w,
            new_height=new_h,
            video_x=video_x,
            video_y=video_y,
            subtitle_margin_v=cls.DEFAULT_SUBTITLE_MARGIN_V,
            title_y=cls.DEFAULT_TITLE_Y
        )
