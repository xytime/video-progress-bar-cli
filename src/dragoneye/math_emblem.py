"""龙眼期权 (DragonEye Options) 顶级机构级极简数学图腾 (Iconic Geometric Quant Emblem v3.3)

以「波动率双曲面对偶咬合 × 黄金对数对称环 × Delta 微观量子透镜」为纯数学构图，比例与边距严格对齐黄金分割。

# Modification History
| Version | Date       | Author                       | Description |
|---------|------------|------------------------------|-------------|
| 3.3.0   | 2026-08-21 | Gemini_3.7_Flash_High_planning | 黄金比例微调：轨道内收、坐标轴对齐，实现顶级金融机构极简高级感 |
"""

from dragoneye.tokens import COLORS

def generate_iconic_dragon_eye_svg(size: int = 512, transparent: bool = True) -> str:
    cx, cy = size / 2, size / 2
    s = size / 512.0

    bg_rect = f'<rect width="{size}" height="{size}" fill="{COLORS.CANVAS_DARK}" rx="{size*0.12}"/>' if not transparent else ''

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" width="{size}" height="{size}">
  <defs>
    <!-- Master Metallic 24K Gold Gradient -->
    <linearGradient id="emblemGold" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#FFF8D0" />
      <stop offset="30%" stop-color="{COLORS.GOLD_PRIMARY}" />
      <stop offset="75%" stop-color="{COLORS.GOLD_CHAMPAGNE}" />
      <stop offset="100%" stop-color="#8C6314" />
    </linearGradient>

    <!-- Master Cyan Laser Gradient -->
    <linearGradient id="emblemCyan" x1="0%" y1="100%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#0066CC" />
      <stop offset="40%" stop-color="{COLORS.CYAN_RADAR}" />
      <stop offset="100%" stop-color="#EAFFFF" />
    </linearGradient>

    <!-- Dark Titanium Hull -->
    <linearGradient id="titaniumHull" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#1E2530" />
      <stop offset="50%" stop-color="#121720" />
      <stop offset="100%" stop-color="#090C10" />
    </linearGradient>

    <radialGradient id="singularityAura" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#FFFFFF" stop-opacity="1" />
      <stop offset="25%" stop-color="{COLORS.CYAN_RADAR}" stop-opacity="0.9" />
      <stop offset="60%" stop-color="{COLORS.CYAN_RADAR}" stop-opacity="0.2" />
      <stop offset="100%" stop-color="{COLORS.CYAN_RADAR}" stop-opacity="0" />
    </radialGradient>

    <filter id="bloomNeon" x="-40%" y="-40%" width="180%" height="180%">
      <feGaussianBlur stdDeviation="{4 * s}" result="blur1" />
      <feGaussianBlur stdDeviation="{10 * s}" result="blur2" />
      <feMerge>
        <feMergeNode in="blur2" />
        <feMergeNode in="blur1" />
        <feMergeNode in="SourceGraphic" />
      </feMerge>
    </filter>

    <filter id="softLaser" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="{2.5 * s}" result="blur" />
      <feComposite in="SourceGraphic" in2="blur" operator="over" />
    </filter>
  </defs>

  {bg_rect}

  <!-- ================= 1. Background Quantitative Radar Matrix ================= -->
  <!-- Outer Precision Gauge Rings -->
  <circle cx="{cx}" cy="{cy}" r="{216 * s}" fill="none" stroke="{COLORS.BORDER_LINE}" stroke-width="{1.5 * s}" stroke-opacity="0.8" />
  <circle cx="{cx}" cy="{cy}" r="{192 * s}" fill="none" stroke="{COLORS.GRID_DARK}" stroke-width="{1 * s}" stroke-dasharray="{4 * s} {8 * s}" />
  <circle cx="{cx}" cy="{cy}" r="{160 * s}" fill="none" stroke="{COLORS.BORDER_LINE}" stroke-width="{1 * s}" stroke-opacity="0.4" stroke-dasharray="{2 * s} {6 * s}" />

  <!-- Coordinate Crosshairs (微观极坐标基准轴) -->
  <line x1="{cx - 224 * s}" y1="{cy}" x2="{cx + 224 * s}" y2="{cy}" stroke="{COLORS.BORDER_LINE}" stroke-width="{1 * s}" stroke-opacity="0.6" stroke-dasharray="{4 * s} {6 * s}" />
  <line x1="{cx}" y1="{cy - 224 * s}" x2="{cx}" y2="{cy + 224 * s}" stroke="{COLORS.BORDER_LINE}" stroke-width="{1 * s}" stroke-opacity="0.6" stroke-dasharray="{4 * s} {6 * s}" />

  <!-- Cardinal Precision Diamond Nodes (四向黄金奇点标) -->
  <polygon points="{cx},{cy - 216 * s} {cx - 4 * s},{cy - 226 * s} {cx},{cy - 234 * s} {cx + 4 * s},{cy - 226 * s}" fill="url(#emblemGold)" />
  <polygon points="{cx},{cy + 216 * s} {cx - 4 * s},{cy + 226 * s} {cx},{cy + 234 * s} {cx + 4 * s},{cy + 226 * s}" fill="url(#emblemGold)" />
  <polygon points="{cx - 216 * s},{cy} {cx - 226 * s},{cy - 4 * s} {cx - 234 * s},{cy} {cx - 226 * s},{cy + 4 * s}" fill="url(#emblemCyan)" />
  <polygon points="{cx + 216 * s},{cy} {cx + 226 * s},{cy - 4 * s} {cx + 234 * s},{cy} {cx + 226 * s},{cy + 4 * s}" fill="url(#emblemCyan)" />

  <!-- ================= 2. Symmetrical Momentum Dragon Orbits (对偶势能双环) ================= -->
  <!-- Upper Ascending Momentum Orbit (Cyan Volatility Streamline) -->
  <path d="M {cx - 155 * s} {cy - 20 * s}
           C {cx - 165 * s} {cy - 160 * s}, {cx + 60 * s} {cy - 195 * s}, {cx + 155 * s} {cy - 120 * s}"
        fill="none" stroke="url(#emblemCyan)" stroke-width="{3.5 * s}" stroke-linecap="round" filter="url(#bloomNeon)" />
  
  <circle cx="{cx + 155 * s}" cy="{cy - 120 * s}" r="{5 * s}" fill="{COLORS.CYAN_RADAR}" filter="url(#bloomNeon)" />

  <!-- Lower Counter-Weight Momentum Orbit (Gold Liquidity Streamline) -->
  <path d="M {cx + 155 * s} {cy + 20 * s}
           C {cx + 165 * s} {cy + 160 * s}, {cx - 60 * s} {cy + 195 * s}, {cx - 155 * s} {cy + 120 * s}"
        fill="none" stroke="url(#emblemGold)" stroke-width="{3.5 * s}" stroke-linecap="round" filter="url(#softLaser)" />
  
  <circle cx="{cx - 155 * s}" cy="{cy + 120 * s}" r="{5 * s}" fill="{COLORS.GOLD_PRIMARY}" />

  <!-- ================= 3. The Central Volatility Lens / Eye of Probability (核心概率之眼) ================= -->
  <!-- Outer Obsidian Titanium Structural Shell -->
  <path d="M {cx - 165 * s} {cy}
           C {cx - 85 * s} {cy - 95 * s}, {cx + 85 * s} {cy - 95 * s}, {cx + 165 * s} {cy}
           C {cx + 85 * s} {cy + 95 * s}, {cx - 85 * s} {cy + 95 * s}, {cx - 165 * s} {cy} Z"
        fill="url(#titaniumHull)" stroke="{COLORS.BORDER_LINE}" stroke-width="{2 * s}" />

  <!-- Inner Ambient Lens Gradient Fill -->
  <path d="M {cx - 155 * s} {cy}
           C {cx - 80 * s} {cy - 85 * s}, {cx + 80 * s} {cy - 85 * s}, {cx + 155 * s} {cy}
           C {cx + 80 * s} {cy + 85 * s}, {cx - 80 * s} {cy + 85 * s}, {cx - 155 * s} {cy} Z"
        fill="url(#singularityAura)" fill-opacity="0.1" />

  <!-- Upper Call Volatility Smile Arch (24K Gold Laser Ridge) -->
  <path d="M {cx - 160 * s} {cy}
           C {cx - 80 * s} {cy - 90 * s}, {cx + 80 * s} {cy - 90 * s}, {cx + 160 * s} {cy}"
        fill="none" stroke="url(#emblemGold)" stroke-width="{5 * s}" stroke-linecap="round" filter="url(#softLaser)" />

  <!-- Lower Put Volatility Smile Arch (Radiant Laser Cyan Ridge) -->
  <path d="M {cx - 160 * s} {cy}
           C {cx - 80 * s} {cy + 90 * s}, {cx + 80 * s} {cy + 90 * s}, {cx + 160 * s} {cy}"
        fill="none" stroke="url(#emblemCyan)" stroke-width="{5 * s}" stroke-linecap="round" filter="url(#bloomNeon)" />

  <!-- Inner Skew Coordinate Graticules (微观概率切线) -->
  <path d="M {cx - 120 * s} {cy} C {cx - 60 * s} {cy - 48 * s}, {cx + 60 * s} {cy - 48 * s}, {cx + 120 * s} {cy}"
        fill="none" stroke="{COLORS.GOLD_CHAMPAGNE}" stroke-width="{1.5 * s}" stroke-dasharray="{3 * s} {5 * s}" opacity="0.7" />
  <path d="M {cx - 120 * s} {cy} C {cx - 60 * s} {cy + 48 * s}, {cx + 60 * s} {cy + 48 * s}, {cx + 120 * s} {cy}"
        fill="none" stroke="{COLORS.CYAN_RADAR}" stroke-width="{1.5 * s}" stroke-dasharray="{3 * s} {5 * s}" opacity="0.7" />

  <!-- ================= 4. The Quantum Singularity Pupil (Delta 0.50 奇点准星) ================= -->
  <!-- Ambient Radiant Core Glow -->
  <circle cx="{cx}" cy="{cy}" r="{56 * s}" fill="url(#singularityAura)" />

  <!-- Titanium Orbit Housing -->
  <circle cx="{cx}" cy="{cy}" r="{40 * s}" fill="#0A0E14" stroke="{COLORS.BORDER_LINE}" stroke-width="{2 * s}" />
  
  <!-- Outer GEX Laser Calibration Ring -->
  <circle cx="{cx}" cy="{cy}" r="{32 * s}" fill="none" stroke="url(#emblemCyan)" stroke-width="{3 * s}" filter="url(#bloomNeon)" />
  <circle cx="{cx}" cy="{cy}" r="{22 * s}" fill="none" stroke="url(#emblemGold)" stroke-width="{1.5 * s}" stroke-dasharray="{2 * s} {4 * s}" />

  <!-- Central Singularity Photon Point -->
  <circle cx="{cx}" cy="{cy}" r="{10 * s}" fill="{COLORS.CANVAS_DARK}" stroke="#FFFFFF" stroke-width="{2 * s}" />
  <circle cx="{cx}" cy="{cy}" r="{5 * s}" fill="{COLORS.CYAN_RADAR}" filter="url(#bloomNeon)" />

  <!-- 45° Breakthrough Momentum Vector Piercing Ray (胜负手突破引力箭头) -->
  <line x1="{cx - 85 * s}" y1="{cy + 85 * s}" x2="{cx + 105 * s}" y2="{cy - 105 * s}"
        stroke="url(#emblemCyan)" stroke-width="{2.5 * s}" stroke-linecap="round" filter="url(#bloomNeon)" />
  <polygon points="{cx + 105 * s},{cy - 105 * s} {cx + 86 * s},{cy - 101 * s} {cx + 101 * s},{cy - 86 * s}"
           fill="{COLORS.CYAN_RADAR}" filter="url(#bloomNeon)" />
</svg>"""
