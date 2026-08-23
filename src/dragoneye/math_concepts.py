"""龙眼期权 (DragonEye Options) 顶级数理几何概念方案 (Mathematical Concept Explorer)

实现两款纯数理、机构级的标志方案：
方案 A (Archetype A): 【波动率偏斜共振之眸 (Triple Skew Resonance Iris)】- 3层对偶 Call/Put 偏斜曲面 + 极坐标雷达
方案 B (Archetype B): 【斐波那契对数双螺旋之眼 (Fibonacci Logarithmic Eye)】- 极简黄金对数双螺旋眼廓 + 极坐标引力核

# Modification History
| Version | Date       | Author                       | Description |
|---------|------------|------------------------------|-------------|
| 3.4.0   | 2026-08-21 | Gemini_3.7_Flash_High_planning | 构建两款高精度纯几何对偶数理概念方案供横向比选 |
"""

import math
from dragoneye.tokens import COLORS

def generate_concept_a_skew_resonance_svg(size: int = 512) -> str:
    """方案 A：波动率偏斜共振之眸 (Triple Skew Resonance Iris)"""
    cx, cy = size / 2, size / 2
    s = size / 512.0

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" width="{size}" height="{size}">
  <defs>
    <linearGradient id="goldLaser" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#FFF8D0" />
      <stop offset="35%" stop-color="{COLORS.GOLD_PRIMARY}" />
      <stop offset="80%" stop-color="{COLORS.GOLD_CHAMPAGNE}" />
      <stop offset="100%" stop-color="#996E1D" />
    </linearGradient>

    <linearGradient id="cyanLaser" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#0066CC" />
      <stop offset="45%" stop-color="{COLORS.CYAN_RADAR}" />
      <stop offset="100%" stop-color="#E0FFFF" />
    </linearGradient>

    <radialGradient id="pupilCenter" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#FFFFFF" />
      <stop offset="25%" stop-color="{COLORS.CYAN_RADAR}" stop-opacity="0.9" />
      <stop offset="60%" stop-color="{COLORS.CYAN_RADAR}" stop-opacity="0.2" />
      <stop offset="100%" stop-color="{COLORS.CYAN_RADAR}" stop-opacity="0" />
    </radialGradient>

    <filter id="bloomA" x="-30%" y="-30%" width="160%" height="160%">
      <feGaussianBlur stdDeviation="{3.5 * s}" result="blur1" />
      <feGaussianBlur stdDeviation="{8 * s}" result="blur2" />
      <feMerge>
        <feMergeNode in="blur2" />
        <feMergeNode in="blur1" />
        <feMergeNode in="SourceGraphic" />
      </feMerge>
    </filter>
  </defs>

  <rect width="{size}" height="{size}" fill="{COLORS.CANVAS_DARK}" rx="{size*0.12}"/>

  <!-- ================= 0. Polar Radar Graticules ================= -->
  <circle cx="{cx}" cy="{cy}" r="{210 * s}" fill="none" stroke="{COLORS.BORDER_LINE}" stroke-width="{1.5 * s}" stroke-opacity="0.7" />
  <circle cx="{cx}" cy="{cy}" r="{185 * s}" fill="none" stroke="{COLORS.GRID_DARK}" stroke-width="{1 * s}" stroke-dasharray="{4 * s} {6 * s}" />
  <circle cx="{cx}" cy="{cy}" r="{155 * s}" fill="none" stroke="{COLORS.BORDER_LINE}" stroke-width="{1 * s}" stroke-opacity="0.3" />

  <!-- 12-Ray Polar Ticks -->
  """ + "".join([
      f'<line x1="{cx + 195*s*math.cos(math.radians(a))}" y1="{cy + 195*s*math.sin(math.radians(a))}" '
      f'x2="{cx + 210*s*math.cos(math.radians(a))}" y2="{cy + 210*s*math.sin(math.radians(a))}" '
      f'stroke="{COLORS.BORDER_LINE}" stroke-width="{1.5*s}" stroke-opacity="0.8"/>'
      for a in range(0, 360, 30)
  ]) + f"""

  <!-- Cardinal Diamonds -->
  <polygon points="{cx},{cy - 210 * s} {cx - 4 * s},{cy - 220 * s} {cx},{cy - 228 * s} {cx + 4 * s},{cy - 220 * s}" fill="url(#goldLaser)" />
  <polygon points="{cx},{cy + 210 * s} {cx - 4 * s},{cy + 220 * s} {cx},{cy + 228 * s} {cx + 4 * s},{cy + 220 * s}" fill="url(#cyanLaser)" />
  <polygon points="{cx - 210 * s},{cy} {cx - 220 * s},{cy - 4 * s} {cx - 228 * s},{cy} {cx - 220 * s},{cy + 4 * s}" fill="url(#goldLaser)" />
  <polygon points="{cx + 210 * s},{cy} {cx + 220 * s},{cy - 4 * s} {cx + 228 * s},{cy} {cx + 220 * s},{cy + 4 * s}" fill="url(#cyanLaser)" />

  <!-- ================= 1. Triple Call Volatility Skew Curves (Upper Golden Arcs) ================= -->
  <!-- Outer 10 Delta Call -->
  <path d="M {cx - 170 * s} {cy} C {cx - 85 * s} {cy - 120 * s}, {cx + 85 * s} {cy - 120 * s}, {cx + 170 * s} {cy}"
        fill="none" stroke="url(#goldLaser)" stroke-width="{4 * s}" stroke-linecap="round" filter="url(#bloomA)" />
  
  <!-- Middle 25 Delta Call -->
  <path d="M {cx - 145 * s} {cy} C {cx - 72 * s} {cy - 85 * s}, {cx + 72 * s} {cy - 85 * s}, {cx + 145 * s} {cy}"
        fill="none" stroke="url(#goldLaser)" stroke-width="{2.5 * s}" stroke-linecap="round" opacity="0.85" />
  
  <!-- Inner 50 Delta (ATM) Call -->
  <path d="M {cx - 120 * s} {cy} C {cx - 60 * s} {cy - 52 * s}, {cx + 60 * s} {cy - 52 * s}, {cx + 120 * s} {cy}"
        fill="none" stroke="url(#goldLaser)" stroke-width="{1.5 * s}" stroke-dasharray="{3*s} {4*s}" opacity="0.65" />

  <!-- ================= 2. Triple Put Volatility Skew Curves (Lower Cyan Arcs) ================= -->
  <!-- Outer 10 Delta Put -->
  <path d="M {cx - 170 * s} {cy} C {cx - 85 * s} {cy + 120 * s}, {cx + 85 * s} {cy + 120 * s}, {cx + 170 * s} {cy}"
        fill="none" stroke="url(#cyanLaser)" stroke-width="{4 * s}" stroke-linecap="round" filter="url(#bloomA)" />
  
  <!-- Middle 25 Delta Put -->
  <path d="M {cx - 145 * s} {cy} C {cx - 72 * s} {cy + 85 * s}, {cx + 72 * s} {cy + 85 * s}, {cx + 145 * s} {cy}"
        fill="none" stroke="url(#cyanLaser)" stroke-width="{2.5 * s}" stroke-linecap="round" opacity="0.85" />
  
  <!-- Inner 50 Delta (ATM) Put -->
  <path d="M {cx - 120 * s} {cy} C {cx - 60 * s} {cy + 52 * s}, {cx + 60 * s} {cy + 52 * s}, {cx + 120 * s} {cy}"
        fill="none" stroke="url(#cyanLaser)" stroke-width="{1.5 * s}" stroke-dasharray="{3*s} {4*s}" opacity="0.65" />

  <!-- ================= 3. Center GEX Singularity & Quantum Pupil ================= -->
  <circle cx="{cx}" cy="{cy}" r="{52 * s}" fill="url(#pupilCenter)" />
  <circle cx="{cx}" cy="{cy}" r="{38 * s}" fill="#0D1117" stroke="{COLORS.BORDER_LINE}" stroke-width="{2 * s}" />
  
  <!-- Concentric Quantum Laser Calibration Rings -->
  <circle cx="{cx}" cy="{cy}" r="{30 * s}" fill="none" stroke="url(#cyanLaser)" stroke-width="{2.5 * s}" filter="url(#bloomA)" />
  <circle cx="{cx}" cy="{cy}" r="{20 * s}" fill="none" stroke="url(#goldLaser)" stroke-width="{1.5 * s}" stroke-dasharray="{2*s} {3*s}" />
  <circle cx="{cx}" cy="{cy}" r="{10 * s}" fill="#FFFFFF" />
  <circle cx="{cx}" cy="{cy}" r="{4 * s}" fill="{COLORS.CYAN_RADAR}" />

  <!-- Horizontal Equator Line -->
  <line x1="{cx - 180 * s}" y1="{cy}" x2="{cx - 52 * s}" y2="{cy}" stroke="{COLORS.BORDER_LINE}" stroke-width="{1.5 * s}" stroke-opacity="0.5" />
  <line x1="{cx + 52 * s}" y1="{cy}" x2="{cx + 180 * s}" y2="{cy}" stroke="{COLORS.BORDER_LINE}" stroke-width="{1.5 * s}" stroke-opacity="0.5" />
</svg>"""


def generate_concept_b_fibonacci_eye_svg(size: int = 512) -> str:
    """方案 B：斐波那契对数双螺旋之眼 (Fibonacci Logarithmic Eye)"""
    cx, cy = size / 2, size / 2
    s = size / 512.0

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" width="{size}" height="{size}">
  <defs>
    <linearGradient id="spiralGold" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#FFF8D0" />
      <stop offset="40%" stop-color="{COLORS.GOLD_PRIMARY}" />
      <stop offset="100%" stop-color="#8C6314" />
    </linearGradient>

    <linearGradient id="spiralCyan" x1="0%" y1="100%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#0066CC" />
      <stop offset="50%" stop-color="{COLORS.CYAN_RADAR}" />
      <stop offset="100%" stop-color="#E0FFFF" />
    </linearGradient>

    <radialGradient id="pupilAuraB" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#FFFFFF" />
      <stop offset="30%" stop-color="{COLORS.CYAN_RADAR}" stop-opacity="0.8" />
      <stop offset="65%" stop-color="{COLORS.CYAN_RADAR}" stop-opacity="0.15" />
      <stop offset="100%" stop-color="{COLORS.CYAN_RADAR}" stop-opacity="0" />
    </radialGradient>

    <filter id="bloomB" x="-30%" y="-30%" width="160%" height="160%">
      <feGaussianBlur stdDeviation="{3.5 * s}" result="blur1" />
      <feGaussianBlur stdDeviation="{9 * s}" result="blur2" />
      <feMerge>
        <feMergeNode in="blur2" />
        <feMergeNode in="blur1" />
        <feMergeNode in="SourceGraphic" />
      </feMerge>
    </filter>
  </defs>

  <rect width="{size}" height="{size}" fill="{COLORS.CANVAS_DARK}" rx="{size*0.12}"/>

  <!-- ================= 0. Mathematical Graticules ================= -->
  <circle cx="{cx}" cy="{cy}" r="{210 * s}" fill="none" stroke="{COLORS.BORDER_LINE}" stroke-width="{1.5 * s}" stroke-opacity="0.7" />
  <circle cx="{cx}" cy="{cy}" r="{160 * s}" fill="none" stroke="{COLORS.GRID_DARK}" stroke-width="{1 * s}" stroke-dasharray="{4 * s} {6 * s}" />
  <circle cx="{cx}" cy="{cy}" r="{110 * s}" fill="none" stroke="{COLORS.BORDER_LINE}" stroke-width="{1 * s}" stroke-opacity="0.3" />

  <!-- Subtly Piercing Crosshairs -->
  <line x1="{cx - 220 * s}" y1="{cy}" x2="{cx + 220 * s}" y2="{cy}" stroke="{COLORS.BORDER_LINE}" stroke-width="{1 * s}" stroke-opacity="0.5" stroke-dasharray="{3 * s} {5 * s}" />
  <line x1="{cx}" y1="{cy - 220 * s}" x2="{cx}" y2="{cy + 220 * s}" stroke="{COLORS.BORDER_LINE}" stroke-width="{1 * s}" stroke-opacity="0.5" stroke-dasharray="{3 * s} {5 * s}" />

  <!-- ================= 1. Twin Interlocking Fibonacci Spiral Eye ================= -->
  <!-- Upper Golden Spiral Arc (The Dragon Crest / Call Volatility) -->
  <path d="M {cx - 180 * s} {cy}
           C {cx - 180 * s} {cy - 120 * s}, {cx - 50 * s} {cy - 150 * s}, {cx + 40 * s} {cy - 150 * s}
           C {cx + 120 * s} {cy - 150 * s}, {cx + 180 * s} {cy - 90 * s}, {cx + 180 * s} {cy}
           C {cx + 180 * s} {cy + 60 * s}, {cx + 130 * s} {cy + 100 * s}, {cx + 60 * s} {cy + 100 * s}
           C {cx - 10 * s} {cy + 100 * s}, {cx - 60 * s} {cy + 60 * s}, {cx - 60 * s} {cy}
           C {cx - 60 * s} {cy - 35 * s}, {cx - 35 * s} {cy - 55 * s}, {cx} {cy - 55 * s}
           C {cx + 25 * s} {cy - 55 * s}, {cx + 40 * s} {cy - 30 * s}, {cx + 40 * s} {cy}"
        fill="none" stroke="url(#spiralGold)" stroke-width="{3.5 * s}" stroke-linecap="round" filter="url(#bloomB)" />

  <!-- Lower Cyan Spiral Arc (The Dragon Eye / Put Volatility) -->
  <path d="M {cx + 180 * s} {cy}
           C {cx + 180 * s} {cy + 120 * s}, {cx + 50 * s} {cy + 150 * s}, {cx - 40 * s} {cy + 150 * s}
           C {cx - 120 * s} {cy + 150 * s}, {cx - 180 * s} {cy + 90 * s}, {cx - 180 * s} {cy}
           C {cx - 180 * s} {cy - 60 * s}, {cx - 130 * s} {cy - 100 * s}, {cx - 60 * s} {cy - 100 * s}
           C {cx + 10 * s} {cy - 100 * s}, {cx + 60 * s} {cy - 60 * s}, {cx + 60 * s} {cy}
           C {cx + 60 * s} {cy + 35 * s}, {cx + 35 * s} {cy + 55 * s}, {cx} {cy + 55 * s}
           C {cx - 25 * s} {cy + 55 * s}, {cx - 40 * s} {cy + 30 * s}, {cx - 40 * s} {cy}"
        fill="none" stroke="url(#spiralCyan)" stroke-width="{3.5 * s}" stroke-linecap="round" filter="url(#bloomB)" />

  <!-- ================= 2. Center Singularity Pupil ================= -->
  <circle cx="{cx}" cy="{cy}" r="{46 * s}" fill="url(#pupilAuraB)" />
  <circle cx="{cx}" cy="{cy}" r="{28 * s}" fill="#0A0E14" stroke="{COLORS.BORDER_LINE}" stroke-width="{2 * s}" />
  <circle cx="{cx}" cy="{cy}" r="{20 * s}" fill="none" stroke="url(#spiralCyan)" stroke-width="{2 * s}" filter="url(#bloomB)" />
  <circle cx="{cx}" cy="{cy}" r="{8 * s}" fill="#FFFFFF" />
  <circle cx="{cx}" cy="{cy}" r="{3.5 * s}" fill="{COLORS.CYAN_RADAR}" />
</svg>"""
