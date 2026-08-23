"""龙眼期权 (DragonEye Options) 高阶品牌视觉物料构建器 (AssetBuilder)

基于 3D 赛博龙眼母体图腾与 Playwright/Pillow 自动化光栅化管线，
生成全套工作室级高保真品牌资产 (1200x300 Logo, 1080x1080 徽章, 512x512 图标, 1080x240 头图, 1080x320 页尾卡片, 水印与 Favicon)。

# Modification History
| Version | Date       | Author                       | Description |
|---------|------------|------------------------------|-------------|
| 1.0.0   | 2026-08-21 | Gemini_3.7_Flash_High_planning | 初始创建品牌资产构建管线 |
| 2.0.0   | 2026-08-21 | Gemini_3.7_Flash_High_planning | 全面升级为 3D 赛博机构级视觉体系：集成高精母体图腾、光影滤镜、HUD微观流动性组件与 300 DPI 印刷级导出 |
"""

import base64
import os
from pathlib import Path
from PIL import Image
from playwright.sync_api import sync_playwright

from dragoneye.tokens import COLORS, LAYOUT

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ASSETS_BRAND_DIR = PROJECT_ROOT / "assets" / "brand"
LOGOS_DIR = ASSETS_BRAND_DIR / "01_logos"
HEADERS_DIR = ASSETS_BRAND_DIR / "02_headers"
FOOTERS_DIR = ASSETS_BRAND_DIR / "03_footers"
TEMPLATES_DIR = ASSETS_BRAND_DIR / "04_templates"


def _get_totem_base64() -> str:
    """读取母体图腾并编码为 Base64"""
    totem_path = LOGOS_DIR / "totem_master.jpg"
    if not totem_path.exists():
        raise FileNotFoundError(f"Master totem not found at {totem_path}")
    return "data:image/jpeg;base64," + base64.b64encode(totem_path.read_bytes()).decode("utf-8")


def generate_icon_dragon_eye_html() -> str:
    """生成 512x512 高阶圆形/微光 App 头像图标 HTML"""
    totem_b64 = _get_totem_base64()
    return f"""<!DOCTYPE html>
<html>
<head>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      width: 512px;
      height: 512px;
      background: transparent;
      display: flex;
      justify-content: center;
      align-items: center;
      overflow: hidden;
      font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif;
    }}
    .badge {{
      width: 480px;
      height: 480px;
      border-radius: 50%;
      background: radial-gradient(circle at 50% 40%, #1A222D 0%, #0D1117 70%, #06080B 100%);
      border: 3px solid #30363D;
      position: relative;
      overflow: hidden;
      box-shadow: 0 0 50px rgba(0, 240, 255, 0.3), inset 0 0 40px rgba(0, 0, 0, 0.9);
      display: flex;
      justify-content: center;
      align-items: center;
    }}
    .radar-ring {{
      position: absolute;
      border-radius: 50%;
      pointer-events: none;
    }}
    .ring-1 {{ width: 440px; height: 440px; border: 1.5px solid rgba(243, 186, 47, 0.4); }}
    .ring-2 {{ width: 380px; height: 380px; border: 1px dashed rgba(0, 240, 255, 0.35); }}
    .ring-3 {{ width: 300px; height: 300px; border: 1px solid rgba(48, 54, 61, 0.8); }}
    .totem-img {{
      width: 440px;
      height: 440px;
      object-fit: cover;
      border-radius: 50%;
      position: relative;
      z-index: 5;
      mix-blend-mode: lighten;
      filter: contrast(1.15) brightness(1.08);
    }}
    .glow-overlay {{
      position: absolute;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      width: 320px;
      height: 320px;
      border-radius: 50%;
      background: radial-gradient(circle, rgba(0, 240, 255, 0.22) 0%, transparent 70%);
      z-index: 6;
      pointer-events: none;
    }}
    .outer-glow {{
      position: absolute;
      top: -2px; left: -2px; right: -2px; bottom: -2px;
      border-radius: 50%;
      border: 2px solid rgba(0, 240, 255, 0.6);
      filter: blur(4px);
    }}
  </style>
</head>
<body>
  <div class="badge">
    <div class="outer-glow"></div>
    <div class="radar-ring ring-1"></div>
    <div class="radar-ring ring-2"></div>
    <div class="radar-ring ring-3"></div>
    <div class="glow-overlay"></div>
    <img class="totem-img" src="{totem_b64}" />
  </div>
</body>
</html>"""


def generate_logo_horiz_dark_html() -> str:
    """生成 1200x300 横版暗黑底主 Logo HTML"""
    totem_b64 = _get_totem_base64()
    return f"""<!DOCTYPE html>
<html>
<head>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      width: 1200px;
      height: 300px;
      background: transparent;
      display: flex;
      align-items: center;
      padding: 0 40px;
      overflow: hidden;
      font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Inter", sans-serif;
    }}
    .logo-container {{
      display: flex;
      align-items: center;
      gap: 36px;
      width: 100%;
    }}
    .totem-badge {{
      width: 230px;
      height: 230px;
      border-radius: 50%;
      background: radial-gradient(circle at 50% 40%, #1A222D 0%, #0D1117 75%, #06080B 100%);
      border: 2px solid #30363D;
      position: relative;
      overflow: hidden;
      box-shadow: 0 0 35px rgba(0, 240, 255, 0.25), inset 0 0 25px rgba(0, 0, 0, 0.8);
      display: flex;
      justify-content: center;
      align-items: center;
      flex-shrink: 0;
    }}
    .totem-badge img {{
      width: 215px;
      height: 215px;
      object-fit: cover;
      border-radius: 50%;
      mix-blend-mode: lighten;
      filter: contrast(1.15) brightness(1.08);
    }}
    .radar-ring {{
      position: absolute;
      border-radius: 50%;
      pointer-events: none;
    }}
    .ring-1 {{ width: 210px; height: 210px; border: 1px solid rgba(243, 186, 47, 0.4); }}
    .ring-2 {{ width: 175px; height: 175px; border: 1px dashed rgba(0, 240, 255, 0.35); }}
    
    .text-block {{
      display: flex;
      flex-direction: column;
      justify-content: center;
    }}
    .en-title {{
      font-family: "Inter", "Helvetica Neue", Arial, sans-serif;
      font-size: 58px;
      font-weight: 900;
      letter-spacing: 4px;
      line-height: 1.1;
      background: linear-gradient(135deg, #FFFFFF 0%, #F3BA2F 50%, #E5C07B 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      text-shadow: 0 4px 20px rgba(243, 186, 47, 0.25);
    }}
    .en-title .cyan {{
      background: linear-gradient(135deg, #00F0FF 0%, #00D2FF 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      font-weight: 800;
    }}
    .zh-title-row {{
      display: flex;
      align-items: center;
      gap: 16px;
      margin-top: 8px;
    }}
    .zh-title {{
      font-size: 34px;
      font-weight: 800;
      color: #F0F6FC;
      letter-spacing: 8px;
    }}
    .tag-badge {{
      background: rgba(0, 240, 255, 0.12);
      border: 1px solid rgba(0, 240, 255, 0.4);
      color: #00F0FF;
      font-family: "JetBrains Mono", monospace;
      font-size: 14px;
      font-weight: 700;
      padding: 4px 10px;
      border-radius: 4px;
      letter-spacing: 1px;
    }}
    .motto-row {{
      font-size: 18px;
      color: #8B949E;
      letter-spacing: 3px;
      margin-top: 8px;
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .motto-row .dot {{
      color: #F3BA2F;
    }}
  </style>
</head>
<body>
  <div class="logo-container">
    <div class="totem-badge">
      <div class="radar-ring ring-1"></div>
      <div class="radar-ring ring-2"></div>
      <img src="{totem_b64}" />
    </div>
    <div class="text-block">
      <div class="en-title">DRAGONEYE <span class="cyan">OPTIONS</span></div>
      <div class="zh-title-row">
        <div class="zh-title">龙眼期权</div>
        <div class="tag-badge">⚡ OPTIONSENSE V4</div>
      </div>
      <div class="motto-row">
        <span>穿透微观流动性</span>
        <span class="dot">◆</span>
        <span>捕捉日内确定性</span>
        <span class="dot">◆</span>
        <span>QUANTITATIVE OPTIONS DESK</span>
      </div>
    </div>
  </div>
</body>
</html>"""


def generate_logo_badge_dark_html() -> str:
    """生成 1080x1080 竖版研报封面徽章 HTML"""
    totem_b64 = _get_totem_base64()
    return f"""<!DOCTYPE html>
<html>
<head>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      width: 1080px;
      height: 1080px;
      background: transparent;
      display: flex;
      justify-content: center;
      align-items: center;
      overflow: hidden;
      font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Inter", sans-serif;
    }}
    .badge-wrap {{
      width: 1000px;
      height: 1000px;
      border-radius: 50%;
      background: radial-gradient(circle at 50% 35%, #1A222E 0%, #0D1117 65%, #050709 100%);
      border: 4px solid #30363D;
      position: relative;
      box-shadow: 0 0 70px rgba(0, 240, 255, 0.35), inset 0 0 60px rgba(0, 0, 0, 0.9);
      display: flex;
      flex-direction: column;
      justify-content: center;
      align-items: center;
    }}
    .radar-ring {{
      position: absolute;
      border-radius: 50%;
      pointer-events: none;
    }}
    .ring-gold {{ width: 920px; height: 920px; border: 2px solid rgba(243, 186, 47, 0.5); }}
    .ring-cyan {{ width: 840px; height: 840px; border: 1.5px dashed rgba(0, 240, 255, 0.4); }}
    .ring-dark {{ width: 680px; height: 680px; border: 1.5px solid rgba(48, 54, 61, 0.9); }}

    .center-totem {{
      width: 580px;
      height: 580px;
      border-radius: 50%;
      background: radial-gradient(circle at 50% 40%, #161B22 0%, #0D1117 80%);
      border: 2px solid rgba(0, 240, 255, 0.4);
      box-shadow: 0 0 40px rgba(0, 240, 255, 0.3);
      position: relative;
      z-index: 5;
      display: flex;
      justify-content: center;
      align-items: center;
      overflow: hidden;
    }}
    .center-totem img {{
      width: 560px;
      height: 560px;
      object-fit: cover;
      mix-blend-mode: lighten;
      filter: contrast(1.18) brightness(1.1);
    }}

    /* Circular SVG Track for Texts */
    .svg-text-overlay {{
      position: absolute;
      top: 0; left: 0;
      width: 1000px;
      height: 1000px;
      pointer-events: none;
      z-index: 10;
    }}
  </style>
</head>
<body>
  <div class="badge-wrap">
    <div class="radar-ring ring-gold"></div>
    <div class="radar-ring ring-cyan"></div>
    <div class="radar-ring ring-dark"></div>

    <svg class="svg-text-overlay" viewBox="0 0 1000 1000">
      <defs>
        <!-- Top arc clockwise -->
        <path id="circleTop" d="M 120 500 A 380 380 0 1 1 880 500" fill="none" />
        <!-- Bottom arc clockwise from left to right -->
        <path id="circleBottom" d="M 170 560 A 380 380 0 0 0 830 560" fill="none" />
        <linearGradient id="goldGrad" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stop-color="{COLORS.GOLD_PRIMARY}" />
          <stop offset="100%" stop-color="{COLORS.GOLD_CHAMPAGNE}" />
        </linearGradient>
      </defs>
      <text fill="url(#goldGrad)" font-family="'Inter', sans-serif" font-weight="900" font-size="30" letter-spacing="6">
        <textPath href="#circleTop" startOffset="50%" text-anchor="middle">
          ★ DRAGONEYE OPTIONS · QUANTITATIVE RESEARCH ★
        </textPath>
      </text>
      <text fill="#8B949E" font-family="'PingFang SC', sans-serif" font-weight="700" font-size="28" letter-spacing="10">
        <textPath href="#circleBottom" startOffset="50%" text-anchor="middle">
          穿透微观流动性 · 捕捉日内确定性
        </textPath>
      </text>
    </svg>

    <div class="center-totem">
      <img src="{totem_b64}" />
    </div>
  </div>
</body>
</html>"""


def generate_header_html(title_zh: str, title_en: str, badge_text: str, is_macro: bool = False) -> str:
    """生成 1080x240 (或 1920x400) 顶部 Header HTML"""
    totem_b64 = _get_totem_base64()
    width = 1920 if is_macro else 1080
    height = 400 if is_macro else 240

    return f"""<!DOCTYPE html>
<html>
<head>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      width: {width}px;
      height: {height}px;
      background: linear-gradient(135deg, #0A0D12 0%, #161B22 60%, #0D1117 100%);
      border-bottom: 2px solid {COLORS.BORDER_LINE};
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 {48 if not is_macro else 72}px;
      overflow: hidden;
      position: relative;
      font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Inter", sans-serif;
    }}
    
    /* Background Cyber Glow & Grid */
    .bg-grid {{
      position: absolute;
      top: 0; left: 0; right: 0; bottom: 0;
      background-image: 
        linear-gradient(to right, rgba(33, 38, 45, 0.4) 1px, transparent 1px),
        linear-gradient(to bottom, rgba(33, 38, 45, 0.4) 1px, transparent 1px);
      background-size: 32px 32px;
      opacity: 0.5;
    }}
    .ambient-glow-left {{
      position: absolute;
      left: -80px;
      top: 50%;
      transform: translateY(-50%);
      width: 320px;
      height: 320px;
      background: radial-gradient(circle, rgba(0, 240, 255, 0.18) 0%, transparent 70%);
      pointer-events: none;
    }}
    .ambient-glow-right {{
      position: absolute;
      right: 40px;
      top: 50%;
      transform: translateY(-50%);
      width: 360px;
      height: 360px;
      background: radial-gradient(circle, rgba(243, 186, 47, 0.12) 0%, transparent 70%);
      pointer-events: none;
    }}

    .left-brand {{
      display: flex;
      align-items: center;
      gap: {24 if not is_macro else 36}px;
      position: relative;
      z-index: 5;
    }}
    .totem-avatar {{
      width: {160 if not is_macro else 260}px;
      height: {160 if not is_macro else 260}px;
      border-radius: 50%;
      background: radial-gradient(circle at 50% 40%, #1A222D 0%, #0D1117 75%);
      border: 2px solid rgba(0, 240, 255, 0.4);
      box-shadow: 0 0 25px rgba(0, 240, 255, 0.3);
      display: flex;
      justify-content: center;
      align-items: center;
      overflow: hidden;
      flex-shrink: 0;
    }}
    .totem-avatar img {{
      width: 100%;
      height: 100%;
      object-fit: cover;
      mix-blend-mode: lighten;
      filter: contrast(1.15) brightness(1.08);
    }}

    .title-group {{
      display: flex;
      flex-direction: column;
      gap: 4px;
    }}
    .main-zh {{
      font-size: {44 if not is_macro else 64}px;
      font-weight: 900;
      color: #F0F6FC;
      letter-spacing: 4px;
      display: flex;
      align-items: center;
      gap: 12px;
    }}
    .main-zh .gold-dot {{
      color: {COLORS.GOLD_PRIMARY};
      font-size: {32 if not is_macro else 48}px;
    }}
    .sub-en {{
      font-family: "Inter", sans-serif;
      font-size: {18 if not is_macro else 26}px;
      font-weight: 800;
      letter-spacing: 3px;
      background: linear-gradient(135deg, {COLORS.GOLD_PRIMARY} 0%, {COLORS.GOLD_CHAMPAGNE} 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }}

    .right-hud {{
      position: relative;
      z-index: 5;
      display: flex;
      flex-direction: column;
      align-items: flex-end;
      gap: 8px;
    }}
    .hud-pill {{
      background: rgba(22, 27, 34, 0.85);
      border: 1px solid rgba(0, 240, 255, 0.35);
      backdrop-filter: blur(10px);
      padding: {8 if not is_macro else 12}px {20 if not is_macro else 28}px;
      border-radius: 8px;
      display: flex;
      align-items: center;
      gap: 10px;
      box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
    }}
    .pulse-dot {{
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: #00F0FF;
      box-shadow: 0 0 10px #00F0FF;
    }}
    .hud-text {{
      font-family: "JetBrains Mono", monospace;
      font-size: {16 if not is_macro else 22}px;
      font-weight: 700;
      color: #00F0FF;
      letter-spacing: 1px;
    }}
    .hud-sub {{
      font-family: "JetBrains Mono", monospace;
      font-size: {13 if not is_macro else 16}px;
      color: #8B949E;
    }}
    
    /* Bottom glowing accent rail */
    .bottom-rail {{
      position: absolute;
      bottom: 0; left: 0; right: 0;
      height: 2px;
      background: linear-gradient(90deg, transparent 0%, #00F0FF 30%, #F3BA2F 70%, transparent 100%);
      opacity: 0.8;
    }}
  </style>
</head>
<body>
  <div class="bg-grid"></div>
  <div class="ambient-glow-left"></div>
  <div class="ambient-glow-right"></div>
  <div class="bottom-rail"></div>

  <div class="left-brand">
    <div class="totem-avatar">
      <img src="{totem_b64}" />
    </div>
    <div class="title-group">
      <div class="main-zh">
        <span>{title_zh}</span>
        <span class="gold-dot">◆</span>
        <span style="font-size: {28 if not is_macro else 40}px; color: #C9D1D9; font-weight: 700;">龙眼期权</span>
      </div>
      <div class="sub-en">{title_en}</div>
    </div>
  </div>

  <div class="right-hud">
    <div class="hud-pill">
      <div class="pulse-dot"></div>
      <div class="hud-text">{badge_text}</div>
    </div>
    <div class="hud-sub">LIQUIDITY & VOLATILITY DESK</div>
  </div>
</body>
</html>"""


def generate_footer_disclaimer_card_html() -> str:
    """生成 1080x320 底部免责声明卡片 HTML"""
    totem_b64 = _get_totem_base64()
    return f"""<!DOCTYPE html>
<html>
<head>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      width: 1080px;
      height: 320px;
      background: linear-gradient(180deg, #161B22 0%, #0D1117 100%);
      border-top: 1px solid #30363D;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 48px;
      overflow: hidden;
      position: relative;
      font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Inter", sans-serif;
    }}
    .top-accent {{
      position: absolute;
      top: 0; left: 48px; width: 240px; height: 3px;
      background: linear-gradient(90deg, #F3BA2F 0%, #00F0FF 100%);
      box-shadow: 0 0 10px rgba(0, 240, 255, 0.5);
    }}
    
    .left-section {{
      display: flex;
      flex-direction: column;
      gap: 12px;
      max-width: 720px;
    }}
    .brand-motto-row {{
      display: flex;
      align-items: center;
      gap: 16px;
    }}
    .brand-title {{
      font-size: 26px;
      font-weight: 900;
      color: #E5C07B;
      letter-spacing: 2px;
    }}
    .brand-sub {{
      font-size: 18px;
      font-weight: 700;
      color: #00F0FF;
      letter-spacing: 2px;
    }}
    .disclaimer-list {{
      display: flex;
      flex-direction: column;
      gap: 6px;
      font-size: 15px;
      color: #8B949E;
      line-height: 1.5;
    }}
    .disclaimer-item {{
      display: flex;
      align-items: flex-start;
      gap: 8px;
    }}
    .disclaimer-item strong {{
      color: #C9D1D9;
    }}
    .warn-tag {{
      color: #FAAD14;
      font-weight: 700;
    }}

    .right-qr-box {{
      width: 190px;
      height: 220px;
      background: rgba(13, 17, 23, 0.85);
      border: 1px solid rgba(48, 54, 61, 0.8);
      border-radius: 10px;
      padding: 14px;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: space-between;
      position: relative;
      box-shadow: 0 6px 20px rgba(0, 0, 0, 0.5);
    }}
    /* Cyber Corner Brackets */
    .qr-corner {{
      position: absolute;
      width: 10px;
      height: 10px;
      border-color: #00F0FF;
      border-style: solid;
      pointer-events: none;
    }}
    .c-tl {{ top: 6px; left: 6px; border-width: 2px 0 0 2px; }}
    .c-tr {{ top: 6px; right: 6px; border-width: 2px 2px 0 0; }}
    .c-bl {{ bottom: 6px; left: 6px; border-width: 0 0 2px 2px; }}
    .c-br {{ bottom: 6px; right: 6px; border-width: 0 2px 2px 0; }}

    .qr-screen {{
      width: 120px;
      height: 120px;
      border-radius: 6px;
      background: #161B22;
      border: 1px dashed rgba(0, 240, 255, 0.5);
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 4px;
    }}
    .qr-screen .mini-totem {{
      width: 48px;
      height: 48px;
      border-radius: 50%;
      mix-blend-mode: lighten;
    }}
    .qr-screen .scan-tag {{
      font-family: "JetBrains Mono", monospace;
      font-size: 11px;
      color: #00F0FF;
      font-weight: 700;
    }}
    .qr-label {{
      text-align: center;
      font-size: 13px;
      color: #C9D1D9;
      font-weight: 600;
      letter-spacing: 1px;
    }}
    .qr-engine {{
      font-size: 11px;
      color: #8B949E;
      font-family: "JetBrains Mono", monospace;
    }}
  </style>
</head>
<body>
  <div class="top-accent"></div>

  <div class="left-section">
    <div class="brand-motto-row">
      <div class="brand-title">🐉 龙眼期权 · DRAGONEYE</div>
      <div class="brand-sub">穿透微观流动性 · 捕捉日内确定性</div>
    </div>
    <div class="disclaimer-list">
      <div class="disclaimer-item">
        <span class="warn-tag">⚠️ 免责声明：</span>
        <span>本报告基于 <strong>OptionSense</strong> 期权微观订单流、伽马暴露 (GEX) 及波动率曲面量化模型推演。</span>
      </div>
      <div class="disclaimer-item">
        <span>◈</span>
        <span>报告内容仅供量化实战与学术交流，绝不构成任何要约、证券买卖建议或投资咨询。</span>
      </div>
      <div class="disclaimer-item">
        <span>◈</span>
        <span>期权交易具有极高杠杆与时间价值衰减风险，请严格执行风控红线与仓位管理。</span>
      </div>
    </div>
  </div>

  <div class="right-qr-box">
    <div class="qr-corner c-tl"></div>
    <div class="qr-corner c-tr"></div>
    <div class="qr-corner c-bl"></div>
    <div class="qr-corner c-br"></div>
    
    <div class="qr-screen">
      <img class="mini-totem" src="{totem_b64}" />
      <span class="scan-tag">[ 扫码交流 ]</span>
    </div>
    <div class="qr-label">关注量化研报</div>
    <div class="qr-engine">OptionSense V4</div>
  </div>
</body>
</html>"""


def generate_footer_simple_bar_html() -> str:
    """生成 1080x100 极简版横条 HTML"""
    totem_b64 = _get_totem_base64()
    return f"""<!DOCTYPE html>
<html>
<head>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      width: 1080px;
      height: 100px;
      background: #161B22;
      border-top: 1px solid #30363D;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 40px;
      overflow: hidden;
      font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Inter", sans-serif;
    }}
    .left {{
      display: flex;
      align-items: center;
      gap: 16px;
    }}
    .mini-logo {{
      width: 44px;
      height: 44px;
      border-radius: 50%;
      mix-blend-mode: lighten;
    }}
    .title {{
      font-size: 22px;
      font-weight: 800;
      color: #E5C07B;
    }}
    .motto {{
      font-size: 17px;
      color: #8B949E;
    }}
    .right-tag {{
      font-family: "JetBrains Mono", monospace;
      font-size: 14px;
      color: #00F0FF;
      background: rgba(0, 240, 255, 0.1);
      padding: 4px 10px;
      border-radius: 4px;
      border: 1px solid rgba(0, 240, 255, 0.3);
    }}
  </style>
</head>
<body>
  <div class="left">
    <img class="mini-logo" src="{totem_b64}" />
    <div class="title">龙眼期权</div>
    <div class="motto">穿透微观流动性 · 捕捉日内确定性</div>
  </div>
  <div class="right-tag">OptionSense V4</div>
</body>
</html>"""


class AssetBuilder:
    """自动化品牌素材生成器 (3D 赛博机构级)"""

    def __init__(self, output_base: Path = ASSETS_BRAND_DIR):
        self.output_base = Path(output_base)
        self.logos_dir = self.output_base / "01_logos"
        self.headers_dir = self.output_base / "02_headers"
        self.footers_dir = self.output_base / "03_footers"

    def ensure_directories(self):
        self.logos_dir.mkdir(parents=True, exist_ok=True)
        self.headers_dir.mkdir(parents=True, exist_ok=True)
        self.footers_dir.mkdir(parents=True, exist_ok=True)

    def render_all_brand_assets(self):
        """一键渲染全套品牌位图与矢量"""
        self.ensure_directories()

        tasks = [
            # 1. Logos
            (generate_icon_dragon_eye_html(), self.logos_dir / "icon_dragon_eye_512x512.png", 512, 512),
            (generate_logo_horiz_dark_html(), self.logos_dir / "logo_horiz_dark.png", 1200, 300),
            (generate_logo_badge_dark_html(), self.logos_dir / "logo_badge_dark.png", 1080, 1080),
            # 2. Headers
            (
                generate_header_html("盘前剧本", "DRAGONEYE PRE-MARKET SCRIPT", "OptionSense V4"),
                self.headers_dir / "header_daily_script.png",
                1080,
                240
            ),
            (
                generate_header_html("每日复盘", "DRAGONEYE DAILY REVIEW", "OptionSense V4"),
                self.headers_dir / "header_daily_review.png",
                1080,
                240
            ),
            (
                generate_header_html("周度研报", "DRAGONEYE WEEKLY MACRO OUTLOOK", "QUANT RESEARCH", is_macro=True),
                self.headers_dir / "header_weekly_macro.png",
                1920,
                400
            ),
            # 3. Footers
            (
                generate_footer_disclaimer_card_html(),
                self.footers_dir / "footer_disclaimer_card.png",
                1080,
                320
            ),
            (
                generate_footer_simple_bar_html(),
                self.footers_dir / "footer_simple_bar.png",
                1080,
                100
            ),
        ]

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            for html_content, png_path, width, height in tasks:
                page.set_viewport_size({"width": width, "height": height})
                page.set_content(html_content)
                page.screenshot(path=str(png_path), omit_background=True)

                # 设置 300 DPI 元数据
                try:
                    with Image.open(png_path) as im:
                        im.save(png_path, "PNG", dpi=(300, 300))
                except Exception:
                    pass

            browser.close()

        # 生成 1000x1000 10% 透明度水印
        self._generate_watermark_alpha10()

        # 生成 Favicon
        self._generate_favicon()

    def _generate_watermark_alpha10(self):
        """生成纯图腾水印（1000x1000 px, 透明度 10%）"""
        src_png = self.logos_dir / "icon_dragon_eye_512x512.png"
        dst_png = self.logos_dir / "icon_watermark_alpha10.png"
        if not src_png.exists():
            return

        img = Image.open(src_png).convert("RGBA")
        img = img.resize((1000, 1000), Image.Resampling.LANCZOS)
        
        r, g, b, a = img.split()
        a = a.point(lambda p: int(p * 0.10))
        watermark = Image.merge("RGBA", (r, g, b, a))
        watermark.save(dst_png, "PNG")

    def _generate_favicon(self):
        """生成浏览器 / 控制台 Favicon (64x64 .ico)"""
        src_png = self.logos_dir / "icon_dragon_eye_512x512.png"
        dst_ico = self.logos_dir / "icon_favicon_64x64.ico"
        if not src_png.exists():
            return

        img = Image.open(src_png)
        img.resize((64, 64), Image.Resampling.LANCZOS).save(dst_ico, format="ICO")

    def build_all(self):
        """一键构建全部高保真品牌资产"""
        self.render_all_brand_assets()


if __name__ == "__main__":
    builder = AssetBuilder()
    builder.build_all()
    print("✨ DragonEye Options studio-grade brand assets generated successfully!")
