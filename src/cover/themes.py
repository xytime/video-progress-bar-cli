"""主题配置与加载器 (ThemeRegistry)

# Modification History
| Version | Date       | Author                       | Description                                                  |
|---------|------------|------------------------------|--------------------------------------------------------------|
| 1.0.0   | 2026-05-26 | Gemini_3.5_Flash_planning    | 初始创建，根据 ContentSignal 解析背景渐变、光晕 orb 和高亮色配置 |
"""

import json
from pathlib import Path
from typing import Dict, Any
from .semantic import ContentSignal

class ThemeRegistry:
    """
    主题配置管理器 (ThemeRegistry)
    负责读取 themes.json 配置文件，并根据语义分析器的结果计算出最终的视觉渲染数值。
    """
    def __init__(self, themes_path: Path):
        self.themes_path = Path(themes_path)
        self.themes: Dict[str, Any] = {}
        self.accents: Dict[str, Any] = {}
        self._load_themes()

    def _load_themes(self) -> None:
        if not self.themes_path.exists():
            # [Gemini_3.5_Flash_planning] 兜底静态数据
            self.themes = {
                "deep_blue": {
                    "background_gradient_start": "#020b18",
                    "background_gradient_end": "#041428",
                    "noise_opacity": 0.04,
                    "grid_color": "rgba(56,189,248,0.06)",
                    "orbs": [
                        {"cx_pct": -0.2, "cy_pct": 0.15, "radius_pct": 0.65, "color_rgba": [56, 189, 248, 160]},
                        {"cx_pct": 1.2, "cy_pct": 0.85, "radius_pct": 0.65, "color_rgba": [168, 85, 247, 160]}
                    ]
                }
            }
            self.accents = {
                "cyan_pulsing": {
                    "color": "#00f0ff",
                    "glow": "0 0 30px rgba(0,240,255,0.6)"
                }
            }
            return

        try:
            with open(self.themes_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.themes = data.get("themes", {})
                self.accents = data.get("accents", {})
        except Exception:
            self.themes = {}
            self.accents = {}

    def resolve(self, signal: ContentSignal) -> Dict[str, Any]:
        """
        [Gemini_3.5_Flash_planning] 将 ContentSignal 映射解析为底层的 CSS 渲染色值和 Orb 属性
        """
        bg_name = signal.base_gradient
        accent_name = signal.accent
        
        # 兜底查找主题
        theme_cfg = self.themes.get(bg_name)
        if not theme_cfg:
            theme_cfg = self.themes.get("deep_blue", list(self.themes.values())[0])
            
        # 兜底查找高亮色
        accent_cfg = self.accents.get(accent_name)
        if not accent_cfg:
            accent_cfg = self.accents.get("cyan_pulsing", list(self.accents.values())[0])

        return {
            "background_gradient_start": theme_cfg.get("background_gradient_start", "#020b18"),
            "background_gradient_end": theme_cfg.get("background_gradient_end", "#041428"),
            "noise_opacity": theme_cfg.get("noise_opacity", 0.04),
            "grid_color": theme_cfg.get("grid_color", "rgba(56,189,248,0.06)"),
            "orbs": theme_cfg.get("orbs", []),
            "accent_color": accent_cfg.get("color", "#00f0ff"),
            "accent_glow": accent_cfg.get("glow", "0 0 30px rgba(0,240,255,0.6)")
        }
