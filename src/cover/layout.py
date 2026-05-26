"""布局参数装配器 (LayoutComposer)

# Modification History
| Version | Date       | Author                       | Description                                                  |
|---------|------------|------------------------------|--------------------------------------------------------------|
| 1.0.0   | 2026-05-26 | Gemini_3.5_Flash_planning    | 初始创建，组装 LayoutSpec，支持双层标题、安全区计算与隐喻位置  |
"""

from typing import Dict, Any, List
from .semantic import ContentSignal

class LayoutComposer:
    """
    布局分析与参数装配器 (LayoutComposer)
    将元数据（标题、副标题）、语义信号、主题配色等组装成标准的 HTML 渲染配置载荷 (LayoutSpec)。
    """
    def __init__(self):
        pass

    def compose(self, payload: dict, signal: ContentSignal, theme_resolved: dict) -> Dict[str, Any]:
        """
        [Gemini_3.5_Flash_planning] 组装 LayoutSpec 数据包，供 HTML/Jinja2 模板渲染使用
        """
        # 获取基础信息
        title = payload.get("title", "").strip()
        subtitle = payload.get("subtitle", "").strip()
        
        # 确定 badge 文本：如果 payload 指定了 category，则使用 category，否则使用默认语义默认值
        category = payload.get("category", "")
        badge = category if category else signal.default_badge
        
        # 组装 layout_spec
        layout_spec = {
            "canvas_width": 1080,
            "canvas_height": 1920,
            
            # 文字载荷
            "title": title,
            "subtitle": subtitle,
            "badge": badge,
            
            # 主题视觉属性
            "accent_color": theme_resolved["accent_color"],
            "accent_glow": theme_resolved["accent_glow"],
            "background_gradient_start": theme_resolved["background_gradient_start"],
            "background_gradient_end": theme_resolved["background_gradient_end"],
            "noise_opacity": theme_resolved["noise_opacity"],
            "grid_color": theme_resolved["grid_color"],
            "orbs": theme_resolved["orbs"],
            
            # 隐喻属性
            "metaphor": signal.metaphor,
            "metaphor_placement": signal.metaphor_placement,
            
            # 安全区参数（按比例，供 CSS 使用）
            "safe_zone": {
                "top_pct": 12,      # 顶部保留 12% 避开微信头像/状态栏
                "bottom_pct": 88,   # 底部保留 12% 避开播放控件
                "margin_pct": 10    # 左右留白 10%
            }
        }
        
        return layout_spec
