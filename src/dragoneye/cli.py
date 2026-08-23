"""龙眼期权 (DragonEye Options) 独立命令行工具 (CLI)

用于执行品牌资产生成、Markdown 日报长图渲染与研报封面输出。

# Modification History
| Version | Date       | Author                       | Description |
|---------|------------|------------------------------|-------------|
| 1.0.0   | 2026-08-21 | Gemini_3.7_Flash_High_planning | 初始创建独立 CLI 工具，集成 build-assets、render-poster 与 render-cover |
"""

import sys
from pathlib import Path
import click

from dragoneye.asset_builder import AssetBuilder
from dragoneye.renderer import DragonEyeRenderer


@click.group()
def cli():
    """龙眼期权 (DragonEye Options) 品牌与渲染工具箱"""
    pass


@cli.command("build-assets")
@click.option("--output-dir", "-o", default=None, help="自定义品牌资产输出根目录")
def build_assets(output_dir):
    """一键生成/重建全套品牌资产 (SVG / PNG / Favicon / 水印)"""
    click.echo("🐉 正在构建龙眼期权品牌资产库...")
    if output_dir:
        builder = AssetBuilder(output_base=Path(output_dir))
    else:
        builder = AssetBuilder()
    builder.build_all()
    click.echo("✅ 品牌资产全部构建完成，已就绪！")


@cli.command("render-poster")
@click.argument("markdown_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--output", "-o", required=True, type=click.Path(), help="输出长图路径 (.png / .jpg)")
@click.option("--header", "-h", type=click.Choice(["auto", "script", "review", "macro", "fallback"]), default="auto", help="顶部头图模式")
@click.option("--quality", "-q", type=int, default=95, help="JPEG 质量 (1-100)")
def render_poster(markdown_file, output, header, quality):
    """根据标准 Markdown 文本渲染 1080px 交付长图"""
    click.echo(f"🎨 正在渲染长图: {markdown_file} -> {output}")
    md_text = Path(markdown_file).read_text(encoding="utf-8")
    renderer = DragonEyeRenderer()
    out_p = renderer.render_markdown_to_poster(
        md_text=md_text,
        output_path=output,
        header_type=header,
        quality=quality
    )
    click.echo(f"✨ 长图渲染成功: {out_p}")


@cli.command("render-cover")
@click.option("--title", "-t", required=True, help="研报主标题")
@click.option("--subtitle", "-s", default="", help="研报副标题")
@click.option("--date", "-d", default="2026-08-21", help="报告日期 (YYYY-MM-DD)")
@click.option("--doc-id", default="DE-OPT-20260821", help="文档编号")
@click.option("--engine", default="OptionSense V4", help="量化引擎标识")
@click.option("--output", "-o", required=True, type=click.Path(), help="输出文件路径 (.png / .pdf)")
@click.option("--pdf", is_flag=True, help="输出为 PDF 格式")
def render_cover(title, subtitle, date, doc_id, engine, output, pdf):
    """渲染研报 PDF 封面 / 高阶海报"""
    click.echo(f"📑 正在渲染研报封面 -> {output}")
    meta = {
        "report_title": title,
        "report_subtitle": subtitle,
        "trading_date": date,
        "doc_id": doc_id,
        "engine_name": engine,
    }
    renderer = DragonEyeRenderer()
    out_p = renderer.render_report_cover(meta=meta, output_path=output, as_pdf=pdf)
    click.echo(f"✨ 研报封面渲染成功: {out_p}")


if __name__ == "__main__":
    cli()
