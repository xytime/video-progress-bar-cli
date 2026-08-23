"""龙眼期权 (DragonEye Options) 绘图与水印基础设施辅助模块 (ChartHelper)

提供 Matplotlib / Plotly 主题配置字典以及位图图表水印中心合成功能。

# Modification History
| Version | Date       | Author                       | Description |
|---------|------------|------------------------------|-------------|
| 1.0.0   | 2026-08-21 | Gemini_3.7_Flash_High_planning | 初始创建绘图主题字典与图表水印自动合成工具 |
"""

from pathlib import Path
from typing import Optional, Union, Dict, Any
from PIL import Image

from dragoneye.tokens import COLORS, FONTS, LAYOUT

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
WATERMARK_PATH = PROJECT_ROOT / "assets" / "brand" / "01_logos" / "icon_watermark_alpha10.png"


def get_matplotlib_theme_dict() -> Dict[str, Any]:
    """
    返回符合「龙眼期权」暗黑金青设计系统的 Matplotlib rcParams 配置字典。
    """
    return {
        "figure.facecolor": COLORS.CANVAS_DARK,
        "axes.facecolor": COLORS.CARD_DARK,
        "axes.edgecolor": COLORS.BORDER_LINE,
        "axes.labelcolor": COLORS.TEXT_TITLE,
        "axes.grid": True,
        "grid.color": COLORS.GRID_DARK,
        "grid.linestyle": "--",
        "grid.alpha": 0.6,
        "xtick.color": COLORS.TEXT_MUTED,
        "ytick.color": COLORS.TEXT_MUTED,
        "text.color": COLORS.TEXT_BODY,
        "axes.prop_cycle": [
            COLORS.CYAN_RADAR,     # 主数据/Call/动量
            COLORS.GOLD_PRIMARY,    # 次级/现价/Gamma Wall
            COLORS.PUT_BEAR,        # 看跌/Put
            COLORS.GOLD_CHAMPAGNE,  # 辅助
            COLORS.CYAN_SECONDARY,  # 次级高亮
        ],
    }


def get_plotly_template_dict() -> Dict[str, Any]:
    """
    返回符合「龙眼期权」暗黑金青设计系统的 Plotly 布局模板字典。
    """
    return {
        "layout": {
            "paper_bgcolor": COLORS.CANVAS_DARK,
            "plot_bgcolor": COLORS.CARD_DARK,
            "font": {
                "color": COLORS.TEXT_BODY,
                "family": "PingFang SC, Inter, sans-serif"
            },
            "xaxis": {
                "gridcolor": COLORS.GRID_DARK,
                "linecolor": COLORS.BORDER_LINE,
                "tickcolor": COLORS.TEXT_MUTED,
                "zerolinecolor": COLORS.BORDER_LINE,
            },
            "yaxis": {
                "gridcolor": COLORS.GRID_DARK,
                "linecolor": COLORS.BORDER_LINE,
                "tickcolor": COLORS.TEXT_MUTED,
                "zerolinecolor": COLORS.BORDER_LINE,
            },
            "colorway": [
                COLORS.CYAN_RADAR,
                COLORS.GOLD_PRIMARY,
                COLORS.PUT_BEAR,
                COLORS.GOLD_CHAMPAGNE,
                COLORS.CYAN_SECONDARY,
            ]
        }
    }


def apply_watermark_to_chart(
    chart_image_path: Union[str, Path],
    output_path: Optional[Union[str, Path]] = None,
    watermark_path: Optional[Union[str, Path]] = None,
    scale_ratio: float = 0.5
) -> Path:
    """
    在动态生成的行情图、GEX 柱状图、K 线图正中央，底层铺设 10% 透明度纯图腾水印。

    :param chart_image_path: 原始图表图片路径
    :param output_path: 输出带水印图片路径 (默认覆盖或生成 _watermarked.png)
    :param watermark_path: 自定义水印图路径 (默认加载 icon_watermark_alpha10.png)
    :param scale_ratio: 水印尺寸占图表较短边的比例 (默认 0.5)
    :return: Path
    """
    in_p = Path(chart_image_path).resolve()
    if not in_p.exists():
        raise FileNotFoundError(f"Chart image not found: {in_p}")

    wm_p = Path(watermark_path).resolve() if watermark_path else WATERMARK_PATH
    if not wm_p.exists():
        raise FileNotFoundError(f"Watermark file not found: {wm_p}")

    if output_path is None:
        out_p = in_p.parent / f"{in_p.stem}_watermarked{in_p.suffix}"
    else:
        out_p = Path(output_path).resolve()

    chart_img = Image.open(in_p).convert("RGBA")
    wm_img = Image.open(wm_p).convert("RGBA")

    # 根据图表尺寸自适应缩放水印
    c_w, c_h = chart_img.size
    target_wm_size = int(min(c_w, c_h) * scale_ratio)
    if target_wm_size > 0:
        wm_resized = wm_img.resize((target_wm_size, target_wm_size), Image.Resampling.LANCZOS)
        
        # 计算居中坐标
        offset_x = (c_w - target_wm_size) // 2
        offset_y = (c_h - target_wm_size) // 2

        # 合成水印
        composed = Image.alpha_composite(
            chart_img,
            Image.new("RGBA", (c_w, c_h), (0, 0, 0, 0))
        )
        composed.paste(wm_resized, (offset_x, offset_y), wm_resized)
        
        out_p.parent.mkdir(parents=True, exist_ok=True)
        if out_p.suffix.lower() in [".jpg", ".jpeg"]:
            composed.convert("RGB").save(out_p, "JPEG", quality=95)
        else:
            composed.save(out_p, "PNG")
        return out_p
    else:
        chart_img.save(out_p)
        return out_p
