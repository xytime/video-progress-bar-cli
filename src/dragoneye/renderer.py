"""龙眼期权 (DragonEye Options) 自动化渲染引擎 (DragonEyeRenderer)

基于 Playwright + Jinja2 将 Markdown 文本或数据结构渲染为 1080px 高质量长图或研报 PDF 封面。

# Modification History
| Version | Date       | Author                       | Description |
|---------|------------|------------------------------|-------------|
| 1.0.0   | 2026-08-21 | Gemini_3.7_Flash_High_planning | 初始创建龙眼期权长图与封面渲染引擎 |
"""

import os
from pathlib import Path
from typing import Optional, Dict, Any, Union
from jinja2 import Template
from playwright.sync_api import sync_playwright

from dragoneye.parser import parse_dragon_eye_markdown
from dragoneye.tokens import LAYOUT

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ASSETS_BRAND_DIR = PROJECT_ROOT / "assets" / "brand"
TEMPLATES_DIR = ASSETS_BRAND_DIR / "04_templates"


class DragonEyeRenderer:
    """龙眼期权品牌物料自动化渲染器"""

    def __init__(self, brand_dir: Path = ASSETS_BRAND_DIR):
        self.brand_dir = Path(brand_dir)
        self.templates_dir = self.brand_dir / "04_templates"
        self.logos_dir = self.brand_dir / "01_logos"
        self.headers_dir = self.brand_dir / "02_headers"
        self.footers_dir = self.brand_dir / "03_footers"
        
        self.css_path = self.templates_dir / "report_theme.css"
        self.poster_template_path = self.templates_dir / "template_daily_poster.html"
        self.cover_template_path = self.templates_dir / "template_report_cover.html"

    def _get_theme_css(self) -> str:
        if self.css_path.exists():
            return self.css_path.read_text(encoding="utf-8")
        return ""

    def _resolve_asset_uri(self, relative_or_abs_path: Union[str, Path]) -> str:
        """将资产文件路径转化为 file:// URI 供浏览器无损加载"""
        p = Path(relative_or_abs_path)
        if not p.is_absolute():
            p = (self.brand_dir / p).resolve()
        else:
            p = p.resolve()
        if p.exists():
            return p.as_uri()
        return ""

    def render_markdown_to_poster(
        self,
        md_text: str,
        output_path: Union[str, Path],
        header_type: str = "auto",
        quality: int = 95
    ) -> Path:
        """
        将标准 Markdown 研报/剧本渲染为 1080px 宽度的高清长图。

        :param md_text: Markdown 文本
        :param output_path: 输出图片路径 (.png 或 .jpg/.jpeg)
        :param header_type: 'script', 'review', 'macro', 'fallback' 或 'auto'
        :param quality: JPEG 压缩质量 (默认 95)
        :return: Path
        """
        data = parse_dragon_eye_markdown(md_text)
        out_p = Path(output_path).resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)

        # 1. 判定 Header 头图
        header_img_url = ""
        col_name = data.get("column_name", "")
        if header_type == "auto":
            if "复盘" in col_name or "review" in col_name.lower():
                header_file = self.headers_dir / "header_daily_review.png"
            elif "宏观" in col_name or "周度" in col_name or "macro" in col_name.lower():
                header_file = self.headers_dir / "header_weekly_macro.png"
            else:
                header_file = self.headers_dir / "header_daily_script.png"
        elif header_type == "review":
            header_file = self.headers_dir / "header_daily_review.png"
        elif header_type == "macro":
            header_file = self.headers_dir / "header_weekly_macro.png"
        elif header_type == "script":
            header_file = self.headers_dir / "header_daily_script.png"
        else:
            header_file = None

        if header_file and header_file.exists():
            header_img_url = header_file.resolve().as_uri()

        # 2. 判定 Logo, Watermark, Footer
        watermark_file = self.logos_dir / "icon_watermark_alpha10.png"
        watermark_url = watermark_file.resolve().as_uri() if watermark_file.exists() else ""

        footer_file = self.footers_dir / "footer_disclaimer_card.png"
        footer_img_url = footer_file.resolve().as_uri() if footer_file.exists() else ""

        logo_file = self.logos_dir / "logo_horiz_dark.png"
        logo_url = logo_file.resolve().as_uri() if logo_file.exists() else ""

        # 3. 组装模板上下文
        context = {
            **data,
            "theme_css": self._get_theme_css(),
            "header_img_url": header_img_url,
            "watermark_url": watermark_url,
            "footer_img_url": footer_img_url,
            "logo_url": logo_url,
        }

        # 4. 渲染 Jinja2
        template_text = self.poster_template_path.read_text(encoding="utf-8")
        template = Template(template_text)
        rendered_html = template.render(**context)

        # 5. Playwright 截图
        temp_html_path = out_p.parent / f"temp_{out_p.stem}.html"
        temp_html_path.write_text(rendered_html, encoding="utf-8")

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.set_viewport_size({"width": LAYOUT.POSTER_WIDTH, "height": 1920})
                page.goto(temp_html_path.resolve().as_uri(), wait_until="networkidle")

                # 获取根容器实际渲染高度
                root_el = page.locator("#poster-root")
                if root_el.count() > 0:
                    box = root_el.bounding_box()
                    actual_height = int(box["height"]) if box else 1920
                else:
                    actual_height = page.evaluate("document.body.scrollHeight")

                page.set_viewport_size({"width": LAYOUT.POSTER_WIDTH, "height": max(actual_height, 600)})

                is_jpeg = out_p.suffix.lower() in [".jpg", ".jpeg"]
                if is_jpeg:
                    page.screenshot(path=str(out_p), type="jpeg", quality=quality, full_page=True)
                else:
                    page.screenshot(path=str(out_p), type="png", full_page=True)

                browser.close()
        finally:
            if temp_html_path.exists():
                try:
                    os.remove(temp_html_path)
                except Exception:
                    pass

        return out_p

    def render_report_cover(
        self,
        meta: Dict[str, Any],
        output_path: Union[str, Path],
        as_pdf: bool = False
    ) -> Path:
        """
        渲染研报 PDF 封面或高清海报。

        :param meta: 封面元数据 (report_title, report_subtitle, trading_date, doc_id, etc.)
        :param output_path: 输出路径
        :param as_pdf: 是否导出为 PDF
        :return: Path
        """
        out_p = Path(output_path).resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)

        logo_file = self.logos_dir / "logo_horiz_dark.png"
        badge_file = self.logos_dir / "logo_badge_dark.png"

        context = {
            **meta,
            "theme_css": self._get_theme_css(),
            "logo_url": logo_file.resolve().as_uri() if logo_file.exists() else "",
            "badge_url": badge_file.resolve().as_uri() if badge_file.exists() else "",
        }

        template_text = self.cover_template_path.read_text(encoding="utf-8")
        template = Template(template_text)
        rendered_html = template.render(**context)

        temp_html_path = out_p.parent / f"temp_cover_{out_p.stem}.html"
        temp_html_path.write_text(rendered_html, encoding="utf-8")

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.set_viewport_size({"width": 1080, "height": 1440})
                page.goto(temp_html_path.resolve().as_uri(), wait_until="networkidle")

                if as_pdf or out_p.suffix.lower() == ".pdf":
                    page.pdf(
                        path=str(out_p),
                        width="1080px",
                        height="1440px",
                        print_background=True
                    )
                else:
                    is_jpeg = out_p.suffix.lower() in [".jpg", ".jpeg"]
                    if is_jpeg:
                        page.screenshot(path=str(out_p), type="jpeg", quality=95)
                    else:
                        page.screenshot(path=str(out_p), type="png")

                browser.close()
        finally:
            if temp_html_path.exists():
                try:
                    os.remove(temp_html_path)
                except Exception:
                    pass

        return out_p
