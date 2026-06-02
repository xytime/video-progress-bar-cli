"""布局参数装配器 (LayoutComposer)

# Modification History
| Version | Date       | Author                       | Description                                                  |
|---------|------------|------------------------------|--------------------------------------------------------------|
| 1.0.0   | 2026-05-26 | Gemini_3.5_Flash_planning    | 初始创建，组装 LayoutSpec，支持双层标题、安全区计算与隐喻位置  |
| 1.1.0   | 2026-06-02 | Gemini_2.5_Pro_planning      | 将 template_variant 字段加入 LayoutSpec，供 HTMLRenderer 选择对应模板文件 |
| 1.2.0   | 2026-06-02 | Gemini_2.5_Pro_planning      | 将 content_label 角标标签透传入 LayoutSpec，供模板渲染丝带角标 |
| 1.3.0   | 2026-06-02 | Gemini_2.5_Pro_planning      | icon/丝带角落冲突避免：丝带在右上角时，自动将 top-right icon 切换到 bottom-left |
| 1.4.0   | 2026-06-02 | Gemini_3.5_Flash_planning    | 修正 LayoutSpec 的 canvas_height 为 6:7 比例 (1260px) |
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
            "canvas_height": 1260, # [Gemini_3.5_Flash_planning] 修正为 6:7 比例以适配视频号竖版封面要求
            
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
            # [Gemini_2.5_Pro_planning] v1.3.0 icon/丝带角落冲突避免
            # 丝带固定占据右上角(top-right)。
            # 若 icon 原定位为 top-right 且有丝带，就将 icon 切到 bottom-left。
            "metaphor_placement": (
                "bottom-left"
                if (
                    str(payload.get("content_label", "") or "").strip()
                    and getattr(signal, "metaphor_placement", "") == "top-right"
                )
                else signal.metaphor_placement
            ),
            
            # [Gemini_2.5_Pro_planning] v1.1.0 模板变体选择
            # rules.json 中每条规则可指定 template_variant 字段
            # 可选值：'cover'（默认）/ 'cover_minimal' / 'cover_drama'
            "template_variant": getattr(signal, 'template_variant', 'cover'),
            
            # [Gemini_2.5_Pro_planning] v1.2.0 封面角标标签，空字符串表示无标签
            "content_label": str(payload.get("content_label", "") or "").strip(),
            
            # 安全区参数（按比例，供 CSS 使用）
            "safe_zone": {
                "top_pct": 12,      # 顶部保留 12% 避开微信头像/状态栏
                "bottom_pct": 88,   # 底部保留 12% 避开播放控件
                "margin_pct": 10    # 左右留白 10%
            }
        }
        
        return layout_spec
