"""基于 Playwright + Jinja2 的 HTML 封面渲染器 (HTMLRenderer)

# Modification History
| Version | Date       | Author                       | Description                                                  |
|---------|------------|------------------------------|--------------------------------------------------------------|
| 1.0.0   | 2026-05-26 | Gemini_3.5_Flash_planning    | 初始创建，支持 Jinja2 模板装配、Inline SVG 注入以及 Playwright 截图生成 |
| 1.1.0   | 2026-06-02 | Gemini_2.5_Pro_planning      | 模板目录化：接受 template_dir 替代单文件，根据 layout_spec.template_variant 动态选择 .html.j2 文件 |
| 1.2.0   | 2026-06-02 | Gemini_3.5_Flash_planning    | 修正截图视口为 6:7 比例 (1080x1260) |
"""

import os
from pathlib import Path
from jinja2 import Template
from playwright.sync_api import sync_playwright

class HTMLRenderer:
    """
    封面图片截图渲染器 (HTMLRenderer)
    使用 Jinja2 模板和 Playwright 无头浏览器生成高质量、高精度的 1080x1920 封面。
    """
    def __init__(self, template_dir: Path, metaphors_dir: Path):
        # [Gemini_2.5_Pro_planning] v1.1.0: 接受目录而非单文件
        self.template_dir = Path(template_dir)
        self.metaphors_dir = Path(metaphors_dir)

    def _load_metaphor_svg(self, metaphor_name: str) -> str:
        """
        [Gemini_3.5_Flash_planning] 读取隐喻矢量图 SVG，以便将其内联注入 HTML 模板中进行 CSS 样式调整
        """
        if not metaphor_name:
            return ""
        
        # 确保带 .svg 后缀
        if not metaphor_name.endswith(".svg"):
            metaphor_name += ".svg"
            
        svg_path = self.metaphors_dir / metaphor_name
        if svg_path.exists():
            try:
                return svg_path.read_text(encoding="utf-8")
            except Exception:
                pass
        
        # Fallback to a simple default dot/circle SVG if metaphor not found
        return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/></svg>'

    def render(self, layout_spec: dict, output_path: str) -> None:
        """
        [Gemini_3.5_Flash_planning] 将 LayoutSpec 渲染成 HTML，并通过 Playwright 无头浏览器截图输出为图片
        [Gemini_2.5_Pro_planning] v1.1.0: 依据 layout_spec.template_variant 选择对应的 .html.j2 文件
        """
        # [Gemini_2.5_Pro_planning] v1.1.0 动态选择模板
        variant = layout_spec.get("template_variant", "cover")
        template_path = self.template_dir / f"{variant}.html.j2"
        # 文件不存在时阶梯到默认模板
        if not template_path.exists():
            template_path = self.template_dir / "cover.html.j2"
        if not template_path.exists():
            raise FileNotFoundError(f"No template found in: {self.template_dir}")

        # 1. 注入 SVG 隐喻
        metaphor_name = layout_spec.get("metaphor", "")
        layout_spec["metaphor_svg"] = self._load_metaphor_svg(metaphor_name)

        # 2. 渲染 Jinja2 模板得到 HTML
        template_text = template_path.read_text(encoding="utf-8")
        template = Template(template_text)
        rendered_html = template.render(**layout_spec)

        # 3. 创建临时 HTML 文件
        temp_html_path = Path(output_path).parent / f"temp_{Path(output_path).stem}.html"
        temp_html_path.write_text(rendered_html, encoding="utf-8")

        # 4. 调用 Playwright 无头浏览器截图
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                
                # [Gemini_3.5_Flash_planning] 微信视频号竖版封面标准比例：6:7 (1080x1260)
                page.set_viewport_size({"width": 1080, "height": 1260})
                
                # 导航到临时文件 URL
                file_url = temp_html_path.resolve().as_uri()
                page.goto(file_url, wait_until="networkidle")
                
                # 截图并保存为 JPEG
                out_p = Path(output_path)
                out_p.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(out_p), type="jpeg", quality=95)
                
                browser.close()
        finally:
            # 5. 清理临时 HTML 文件
            if temp_html_path.exists():
                try:
                    os.remove(temp_html_path)
                except Exception:
                    pass
