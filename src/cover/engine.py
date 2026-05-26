"""封面生成引擎入口 Facade (CoverEngine)

# Modification History
| Version | Date       | Author                       | Description                                                  |
|---------|------------|------------------------------|--------------------------------------------------------------|
| 1.0.0   | 2026-05-26 | Gemini_3.5_Flash_planning    | 初始创建，协调语义分析、主题解析、版式装配与 HTML 截图渲染      |
"""

from pathlib import Path
from config.settings import settings
from .semantic import SemanticAnalyzer
from .themes import ThemeRegistry
from .layout import LayoutComposer
from .renderer import HTMLRenderer

class CoverEngine:
    """
    封面生成引擎唯一对外 Facade 入口 (CoverEngine)
    高度内聚了语义识别、配色决策、布局装配与 Playwright 截图流程，降低外部模块的调用耦合。
    """
    def __init__(self, 
                 rules_path: Path = None, 
                 themes_path: Path = None, 
                 template_path: Path = None, 
                 metaphors_dir: Path = None):
        
        # [Gemini_3.5_Flash_planning] 默认使用全局 settings 中的项目路径推导
        root = settings.project_root
        
        self.rules_path = Path(rules_path) if rules_path else root / "resources" / "cover" / "rules.json"
        self.themes_path = Path(themes_path) if themes_path else root / "resources" / "cover" / "themes.json"
        self.template_path = Path(template_path) if template_path else root / "resources" / "cover" / "template" / "cover.html.j2"
        self.metaphors_dir = Path(metaphors_dir) if metaphors_dir else root / "resources" / "cover" / "metaphors"

        # 初始化各子模块
        self.analyzer = SemanticAnalyzer(self.rules_path)
        self.registry = ThemeRegistry(self.themes_path)
        self.composer = LayoutComposer()
        self.renderer = HTMLRenderer(self.template_path, self.metaphors_dir)

    def generate(self, payload: dict, output_path: str) -> None:
        """
        [Gemini_3.5_Flash_planning] 运行全链路管线生成图片文件
        
        Args:
            payload: dict，结构如下：
                {
                    "title": "主标题",
                    "subtitle": "副标题",
                    "category": "可选，如 科技/财经",
                    "content_hints": ["ai", "market", "policy"]  # 语义标识
                }
            output_path: str，输出的 JPEG 图片绝对路径
        """
        # 1. 运行语义分析
        signal = self.analyzer.analyze(payload)
        
        # 2. 映射配色主题
        theme = self.registry.resolve(signal)
        
        # 3. 组装布局参数
        layout = self.composer.compose(payload, signal, theme)
        
        # 4. 调用 Playwright 渲染为图片
        self.renderer.render(layout, output_path)
