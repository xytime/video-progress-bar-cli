"""龙眼期权 (DragonEye Options) 设计系统设计变量 (Design Tokens)

# Modification History
| Version | Date       | Author                       | Description |
|---------|------------|------------------------------|-------------|
| 1.0.0   | 2026-08-21 | Gemini_3.7_Flash_High_planning | 初始定义色彩系统、字体系统及尺寸规范 |
"""

from dataclasses import dataclass
from typing import Dict, Any


@dataclass(frozen=True)
class ColorPalette:
    # Canvas Dark (底色/背景)
    CANVAS_DARK: str = "#0D1117"       # 主背景
    CARD_DARK: str = "#161B22"         # 卡片/模块背景
    
    # Gold Dynamic (龙金/主品牌色)
    GOLD_PRIMARY: str = "#F3BA2F"      # 高光金
    GOLD_CHAMPAGNE: str = "#E5C07B"    # 香槟金/主文字
    
    # Cyan Radar (雷达青/动量点睛色)
    CYAN_RADAR: str = "#00F0FF"        # 瞳孔/上涨动量/关键价位
    CYAN_SECONDARY: str = "#00D2FF"    # 次级高亮
    
    # Border & Grid (分界/网格)
    BORDER_LINE: str = "#30363D"       # 边框线
    GRID_DARK: str = "#21262D"         # 暗网格
    
    # Text Tone (文字层级)
    TEXT_TITLE: str = "#F0F6FC"        # 主标题/数值
    TEXT_BODY: str = "#C9D1D9"         # 正文描述
    TEXT_MUTED: str = "#8B949E"        # 辅助说明/时间戳
    
    # Semantic Accents (语义状态色)
    CALL_BULL: str = "#00F0FF"         # 看多/Call/突破
    PUT_BEAR: str = "#FF4D4F"          # 看空/Put/承压
    RISK_ALERT: str = "#FAAD14"        # 风控警戒色


@dataclass(frozen=True)
class Typography:
    FONT_ZH: str = "'PingFang SC', 'Noto Sans SC', 'Microsoft YaHei', sans-serif"
    FONT_EN: str = "'Inter', 'Helvetica Neue', 'Arial', sans-serif"
    FONT_MONO: str = "'JetBrains Mono', 'Fira Code', 'Consolas', monospace"


@dataclass(frozen=True)
class LayoutSpecs:
    POSTER_WIDTH: int = 1080
    POSTER_PADDING: int = 40
    HEADER_SCRIPT_HEIGHT: int = 240
    HEADER_REVIEW_HEIGHT: int = 240
    HEADER_MACRO_WIDTH: int = 1920
    HEADER_MACRO_HEIGHT: int = 400
    FOOTER_CARD_HEIGHT: int = 320
    FOOTER_BAR_HEIGHT: int = 100
    LOGO_HORIZ_WIDTH: int = 1200
    LOGO_HORIZ_HEIGHT: int = 300
    LOGO_BADGE_SIZE: int = 1080
    WATERMARK_SIZE: int = 1000
    WATERMARK_OPACITY: float = 0.10


COLORS = ColorPalette()
FONTS = Typography()
LAYOUT = LayoutSpecs()
