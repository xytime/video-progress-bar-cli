"""龙眼期权 (DragonEye Options) 单元测试与端到端渲染验证

# Modification History
| Version | Date       | Author                       | Description |
|---------|------------|------------------------------|-------------|
| 1.0.0   | 2026-08-21 | Gemini_3.7_Flash_High_planning | 初始创建 DragonEye 模块测试集 |
"""

import os
from pathlib import Path
import pytest
from PIL import Image

from dragoneye.tokens import COLORS, LAYOUT
from dragoneye.parser import parse_dragon_eye_markdown
from dragoneye.renderer import DragonEyeRenderer

SAMPLE_STANDARD_MD = """🐉 **龙眼期权 · DRAGONEYE OPTIONS** | **[栏目名称：盘前剧本]**
📅 交易日：2026-08-21 | 编号：No.088 | 核心引擎：OptionSense
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🎯 **【龙眼定点】核心流动性分布**
* **Gamma Wall（多空分水岭）**: $602.50
* **VWAP 关键引力带**: $598.20 ~ $604.00
* **日内最大痛点 / 0DTE 密集区**: Call $605 / Put $595

⚡ **【异动雷达】主力扫单与 IV 追踪**
* **大单异动（Block / Sweep）**: SPY 0DTE 605 Call 扫单 2.4M 金额
* **波动率曲面（IV/Skew）**: 偏斜向 OTM Call 异动抬升 +3.2%

🗡️ **【剧本推演 / 胜负手】战术应对**
* **情境 A（多头突破）**: 放量站上 $602.50，第一目标 $605.00，防守位 $600.00
* **情境 B（空头承压）**: 跌破 $598.20，向下探寻 $595.00 流动性支撑

🛡️ **【风控红线】**
* 0DTE 时间价值（Theta）衰减拐点预警，硬止损严格锁定单笔权利金 30%。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
👁️ *龙眼期权 | 穿透微观流动性 · 捕捉日内确定性*
⚠️ *免责声明：本内容基于期权微观量化模型推演，仅供实战交流，不构成直接投资建议。*
"""


def test_design_tokens():
    """验证设计系统变量与色彩规范"""
    assert COLORS.CANVAS_DARK == "#0D1117"
    assert COLORS.CARD_DARK == "#161B22"
    assert COLORS.GOLD_PRIMARY == "#F3BA2F"
    assert COLORS.CYAN_RADAR == "#00F0FF"
    assert COLORS.BORDER_LINE == "#30363D"
    assert LAYOUT.POSTER_WIDTH == 1080


def test_markdown_parser_standard():
    """验证标准 Markdown 解析逻辑"""
    data = parse_dragon_eye_markdown(SAMPLE_STANDARD_MD)
    assert data["column_name"] == "盘前剧本"
    assert data["trading_date"] == "2026-08-21"
    assert data["issue_no"] == "No.088"
    assert data["engine_name"] == "OptionSense"
    
    assert len(data["sections"]) == 4
    sec_types = [s["type"] for s in data["sections"]]
    assert "liquidity" in sec_types
    assert "radar" in sec_types
    assert "scenarios" in sec_types
    assert "risk" in sec_types

    # 验证流动性条目提取
    liq_sec = [s for s in data["sections"] if s["type"] == "liquidity"][0]
    labels = [item["label"] for item in liq_sec["metrics"]]
    assert "Gamma Wall（多空分水岭）" in labels


def test_brand_assets_exist():
    """验证基础品牌物料是否生成完整"""
    base_dir = Path(__file__).resolve().parent.parent.parent / "assets" / "brand"
    required_files = [
        "01_logos/icon_dragon_eye.svg",
        "01_logos/icon_dragon_eye_512x512.png",
        "01_logos/icon_favicon_64x64.ico",
        "01_logos/icon_watermark_alpha10.png",
        "01_logos/logo_horiz_dark.svg",
        "01_logos/logo_horiz_dark.png",
        "01_logos/logo_badge_dark.svg",
        "01_logos/logo_badge_dark.png",
        "02_headers/header_daily_script.png",
        "02_headers/header_daily_review.png",
        "02_headers/header_weekly_macro.png",
        "03_footers/footer_disclaimer_card.png",
        "03_footers/footer_simple_bar.png",
        "04_templates/report_theme.css",
        "04_templates/template_daily_poster.html",
        "04_templates/template_report_cover.html",
    ]
    for rel_path in required_files:
        f = base_dir / rel_path
        assert f.exists(), f"Missing required brand asset: {rel_path}"
        assert f.stat().st_size > 0, f"Asset file is empty: {rel_path}"


def test_render_poster_e2e(tmp_path):
    """端到端测试：从 Markdown 渲染出 1080px 高清长图"""
    output_png = tmp_path / "test_poster.png"
    renderer = DragonEyeRenderer()
    res_path = renderer.render_markdown_to_poster(
        md_text=SAMPLE_STANDARD_MD,
        output_path=output_png,
        header_type="script"
    )
    assert res_path.exists()
    assert res_path.stat().st_size > 1000

    # 验证图像规格 (宽度应为 1080px)
    with Image.open(res_path) as img:
        width, height = img.size
        assert width == 1080
        assert height > 500


def test_render_cover_e2e(tmp_path):
    """端到端测试：渲染研报封面 PNG 与 PDF"""
    output_png = tmp_path / "test_cover.png"
    output_pdf = tmp_path / "test_cover.pdf"
    renderer = DragonEyeRenderer()
    
    meta = {
        "report_title": "期权微观流动性与波动率结构研报",
        "report_subtitle": "穿透主力订单流 · 锚定伽马临界点位",
        "trading_date": "2026-08-21",
        "doc_id": "DE-OPT-20260821-01",
        "engine_name": "OptionSense V4",
    }
    
    # 1. 渲染 PNG
    res_png = renderer.render_report_cover(meta, output_png, as_pdf=False)
    assert res_png.exists()
    with Image.open(res_png) as img:
        assert img.size == (1080, 1440)

    # 2. 渲染 PDF
    res_pdf = renderer.render_report_cover(meta, output_pdf, as_pdf=True)
    assert res_pdf.exists()
    assert res_pdf.stat().st_size > 1000


def test_chart_helper_theme_and_watermark(tmp_path):
    """测试图表主题配置与位图图表水印合成"""
    from dragoneye.chart_helper import (
        get_matplotlib_theme_dict,
        get_plotly_template_dict,
        apply_watermark_to_chart
    )

    mpl_theme = get_matplotlib_theme_dict()
    assert mpl_theme["figure.facecolor"] == "#0D1117"
    assert mpl_theme["axes.facecolor"] == "#161B22"

    plotly_theme = get_plotly_template_dict()
    assert plotly_theme["layout"]["paper_bgcolor"] == "#0D1117"

    # 生成一个测试用纯色假图表并叠加水印
    dummy_chart = tmp_path / "dummy_chart.png"
    im = Image.new("RGBA", (800, 600), (22, 27, 34, 255))
    im.save(dummy_chart, "PNG")

    watermarked_out = tmp_path / "dummy_chart_watermarked.png"
    out_path = apply_watermark_to_chart(dummy_chart, watermarked_out, scale_ratio=0.4)
    assert out_path.exists()
    with Image.open(out_path) as out_im:
        assert out_im.size == (800, 600)

