"""龙眼期权 (DragonEye Options) 纯数学与量化哲学图腾生成器 (Mathematical Totem Generator)

以「波动率微笑双弧 (Volatility Smile) × 高斯概率透镜 (Gaussian Lens) × 黄金对数螺旋动量流 (Golden Helix)」
为核心数学内核，构建极简、深刻、顶级机构级的品牌视觉几何图腾。

# Modification History
| Version | Date       | Author                       | Description |
|---------|------------|------------------------------|-------------|
| 3.0.0   | 2026-08-21 | Gemini_3.7_Flash_High_planning | 彻底重构图腾：摒弃具象龙兽头，引入波动率曲面、高斯透镜与对数螺旋数学哲学 |
"""

import math
from pathlib import Path
from dragoneye.tokens import COLORS

def generate_math_dragon_eye_svg(size: int = 512, transparent: bool = True) -> str:
    """
    生成基于期权数学与物理隐喻的「龙眼」抽象几何图腾 SVG。
    
    数学构图内涵：
    1. 【龙之势能 / 动量双螺旋】：对偶交织的黄金对数螺旋流线（金青双轨），象征市场狂暴波动率中的确定性动量。
    2. 【眼之透镜 / 概率之眼】：由 Volatility Smile (波动率微笑) 与 逆向 Skew 曲面交汇而成的透镜形态。
    3. 【瞳之奇点 / 流动性引力核】：中心点位 Delta 0.5 / GEX 零轴奇点，微观引力环与极坐标十字射线。
    """
    cx, cy = size / 2, size / 2
    r_outer = size * 0.44
    r_mid = size * 0.36
    r_inner = size * 0.26
    r_core = size * 0.06

    bg_rect = f'<rect width="{size}" height="{size}" fill="{COLORS.CANVAS_DARK}" rx="{size*0.08}"/>' if not transparent else ''

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" width="{size}" height="{size}">
  <defs>
    <!-- Master Gradients -->
    <linearGradient id="goldHelix" x1="0%" y1="100%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="{COLORS.GOLD_PRIMARY}" stop-opacity="0.2" />
      <stop offset="40%" stop-color="{COLORS.GOLD_PRIMARY}" stop-opacity="0.9" />
      <stop offset="100%" stop-color="{COLORS.GOLD_CHAMPAGNE}" stop-opacity="1" />
    </linearGradient>
    
    <linearGradient id="cyanHelix" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="{COLORS.CYAN_RADAR}" stop-opacity="1" />
      <stop offset="60%" stop-color="{COLORS.CYAN_SECONDARY}" stop-opacity="0.8" />
      <stop offset="100%" stop-color="{COLORS.CYAN_RADAR}" stop-opacity="0.1" />
    </linearGradient>

    <linearGradient id="eyeLensGrad" x1="0%" y1="50%" x2="100%" y2="50%">
      <stop offset="0%" stop-color="{COLORS.CYAN_RADAR}" stop-opacity="0.9" />
      <stop offset="50%" stop-color="#FFFFFF" stop-opacity="1" />
      <stop offset="100%" stop-color="{COLORS.GOLD_PRIMARY}" stop-opacity="0.9" />
    </linearGradient>

    <radialGradient id="singularityGlow" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#FFFFFF" stop-opacity="1" />
      <stop offset="25%" stop-color="{COLORS.CYAN_RADAR}" stop-opacity="0.9" />
      <stop offset="60%" stop-color="{COLORS.CYAN_RADAR}" stop-opacity="0.25" />
      <stop offset="100%" stop-color="{COLORS.CYAN_RADAR}" stop-opacity="0" />
    </radialGradient>

    <filter id="laserGlow" x="-30%" y="-30%" width="160%" height="160%">
      <feGaussianBlur stdDeviation="{size*0.012}" result="blur1" />
      <feGaussianBlur stdDeviation="{size*0.024}" result="blur2" />
      <feMerge>
        <feMergeNode in="blur2" />
        <feMergeNode in="blur1" />
        <feMergeNode in="SourceGraphic" />
      </feMerge>
    </filter>

    <filter id="coreGlow" x="-50%" y="-50%" width="200%" height="200%">
      <feGaussianBlur stdDeviation="{size*0.02}" result="blur" />
      <feMerge>
        <feMergeNode in="blur" />
        <feMergeNode in="SourceGraphic" />
      </feMerge>
    </filter>
  </defs>

  {bg_rect}

  <!-- ================= 1. 外层量化标尺与引力轨道 (Polar Gauge & Gauge Ticks) ================= -->
  <!-- Outer Precision Gauge -->
  <circle cx="{cx}" cy="{cy}" r="{r_outer}" fill="none" stroke="{COLORS.BORDER_LINE}" stroke-width="1.5" stroke-opacity="0.6" />
  <circle cx="{cx}" cy="{cy}" r="{r_mid}" fill="none" stroke="{COLORS.GRID_DARK}" stroke-width="1" stroke-dasharray="4 8" />
  
  <!-- Coordinate Crosshairs (微观订单流引力轴) -->
  <line x1="{cx - r_outer - 10}" y1="{cy}" x2="{cx + r_outer + 10}" y2="{cy}" stroke="{COLORS.BORDER_LINE}" stroke-width="1" stroke-dasharray="2 6" stroke-opacity="0.5" />
  <line x1="{cx}" y1="{cy - r_outer - 10}" x2="{cx}" y2="{cy + r_outer + 10}" stroke="{COLORS.BORDER_LINE}" stroke-width="1" stroke-dasharray="2 6" stroke-opacity="0.5" />

  <!-- Cardinal Angle Tick Markers -->
  <circle cx="{cx + r_outer}" cy="{cy}" r="3" fill="{COLORS.CYAN_RADAR}" />
  <circle cx="{cx - r_outer}" cy="{cy}" r="3" fill="{COLORS.GOLD_PRIMARY}" />
  <circle cx="{cx}" cy="{cy - r_outer}" r="3" fill="{COLORS.TEXT_TITLE}" />
  <circle cx="{cx}" cy="{cy + r_outer}" r="3" fill="{COLORS.TEXT_MUTED}" />

  <!-- ================= 2. 龙之势能：黄金对数螺旋动量流 (The Dragon's Momentum Helices) ================= -->
  <!-- Ascending Dragon Momentum Helix (Cyan Vega Streamline) -->
  <path d="M {cx - r_mid*1.05} {cy + r_mid*0.5}
           C {cx - r_mid*0.9} {cy + r_mid*1.1}, {cx + r_mid*0.2} {cy + r_mid*1.15}, {cx + r_mid*0.9} {cy + r_mid*0.6}
           C {cx + r_mid*1.2} {cy + r_mid*0.3}, {cx + r_mid*1.15} {cy - r_mid*0.6}, {cx + r_mid*0.5} {cy - r_mid*0.95}
           C {cx + r_mid*0.1} {cy - r_mid*1.15}, {cx - r_mid*0.6} {cy - r_mid*0.8}, {cx - r_mid*0.75} {cy - r_mid*0.3}"
        fill="none" stroke="url(#cyanHelix)" stroke-width="3" stroke-linecap="round" filter="url(#laserGlow)" />

  <!-- Counter Balance Golden Spiral (Gold Theta Streamline) -->
  <path d="M {cx + r_mid*0.9} {cy - r_mid*0.45}
           C {cx + r_mid*0.7} {cy - r_mid*1.05}, {cx - r_mid*0.3} {cy - r_mid*1.1}, {cx - r_mid*0.9} {cy - r_mid*0.5}
           C {cx - r_mid*1.2} {cy - r_mid*0.1}, {cx - r_mid*1.1} {cy + r_mid*0.65}, {cx - r_mid*0.4} {cy + r_mid*0.98}
           C {cx - r_mid*0.05} {cy + r_mid*1.12}, {cx + r_mid*0.65} {cy + r_mid*0.8}, {cx + r_mid*0.78} {cy + r_mid*0.25}"
        fill="none" stroke="url(#goldHelix)" stroke-width="2.5" stroke-linecap="round" opacity="0.9" />

  <!-- ================= 3. 眼之透镜：波动率微笑与概率切面 (The Volatility Lens / Probability Eye) ================= -->
  <!-- Upper Volatility Smile Arc (Call Skew Surface) -->
  <path d="M {cx - r_inner*1.4} {cy}
           Q {cx} {cy - r_inner*0.95} {cx + r_inner*1.4} {cy}"
        fill="none" stroke="url(#eyeLensGrad)" stroke-width="4.5" stroke-linecap="round" filter="url(#laserGlow)" />

  <!-- Lower Volatility Smile Arc (Put Skew Surface) -->
  <path d="M {cx - r_inner*1.4} {cy}
           Q {cx} {cy + r_inner*0.95} {cx + r_inner*1.4} {cy}"
        fill="none" stroke="url(#eyeLensGrad)" stroke-width="4.5" stroke-linecap="round" filter="url(#laserGlow)" />

  <!-- Probability Density Lens Fill (Subtle Ambient Glow between Skew curves) -->
  <path d="M {cx - r_inner*1.4} {cy}
           Q {cx} {cy - r_inner*0.95} {cx + r_inner*1.4} {cy}
           Q {cx} {cy + r_inner*0.95} {cx - r_inner*1.4} {cy} Z"
        fill="url(#cyanHelix)" fill-opacity="0.08" />

  <!-- Inner Gaussian Normal Distribution Curves (内嵌高斯正态钟形分布微结构) -->
  <path d="M {cx - r_inner*0.9} {cy}
           Q {cx} {cy - r_inner*0.55} {cx + r_inner*0.9} {cy}"
        fill="none" stroke="{COLORS.CYAN_RADAR}" stroke-width="1.5" stroke-dasharray="3 4" opacity="0.7" />
  <path d="M {cx - r_inner*0.9} {cy}
           Q {cx} {cy + r_inner*0.55} {cx + r_inner*0.9} {cy}"
        fill="none" stroke="{COLORS.GOLD_PRIMARY}" stroke-width="1.5" stroke-dasharray="3 4" opacity="0.7" />

  <!-- ================= 4. 瞳之奇点：Delta 0.5 价格引力核 (Singularity / The Quantum Pupil) ================= -->
  <!-- Quantum Aura -->
  <circle cx="{cx}" cy="{cy}" r="{r_inner*0.5}" fill="url(#singularityGlow)" />
  
  <!-- Precision Target Reticle (0DTE/GEX 汇聚环) -->
  <circle cx="{cx}" cy="{cy}" r="{r_core*1.5}" fill="{COLORS.CARD_DARK}" stroke="{COLORS.CYAN_RADAR}" stroke-width="2.5" filter="url(#laserGlow)" />
  <circle cx="{cx}" cy="{cy}" r="{r_core*0.75}" fill="none" stroke="{COLORS.GOLD_PRIMARY}" stroke-width="1.5" />
  <circle cx="{cx}" cy="{cy}" r="{r_core*0.3}" fill="#FFFFFF" />

  <!-- 45° Breakthrough Arrow Vector (突破引力向量) -->
  <line x1="{cx - r_inner*0.7}" y1="{cy + r_inner*0.7}" x2="{cx + r_inner*0.8}" y2="{cy - r_inner*0.8}" 
        stroke="{COLORS.CYAN_RADAR}" stroke-width="2" stroke-linecap="round" filter="url(#laserGlow)" />
  <polygon points="{cx + r_inner*0.8},{cy - r_inner*0.8} {cx + r_inner*0.6},{cy - r_inner*0.78} {cx + r_inner*0.78},{cy - r_inner*0.6}" 
           fill="{COLORS.CYAN_RADAR}" filter="url(#laserGlow)" />
</svg>"""
