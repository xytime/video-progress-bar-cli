#!/usr/bin/env python3
"""视频号封面丝带优化 5 版 Demo 生成脚本 (generate_ribbon_demos.py)

# Modification History
| Version | Date       | Author                    | Description                                                      |
|---------|------------|---------------------------|------------------------------------------------------------------|
| 1.0.0   | 2026-06-03 | Gemini_3.5_Flash_planning | 初始创建，整合 Playwright 与 Jinja2 渲染五款优化后的丝带角标封面  |
"""

import os
import sys
import re
import shutil
from pathlib import Path
from jinja2 import Template
from playwright.sync_api import sync_playwright

# [Gemini_3.5_Flash_planning] 引入项目 src 目录
sys.path.append(str(Path(__file__).parent.parent / "src"))
from cover.engine import CoverEngine

# 渲染尺寸
W, H = 1080, 1260  # 视频号标准 6:7 尺寸
BRAIN_DIR = Path("/Users/ryusei/.gemini/antigravity/brain/32806bed-8a65-4dc4-8965-9418818349df")

# 5 版设计方案的 HTML 代码
RIBBONS_HTML = {
    "v1_enlarged_diagonal": """
    <div style="position:absolute; top:0; right:0; width:450px; height:450px; z-index:30; overflow:hidden; pointer-events:none;">
      <svg width="450" height="450" viewBox="0 0 450 450" xmlns="http://www.w3.org/2000/svg">
        <defs>
          <linearGradient id="lrg_v1" x1="330" y1="0" x2="170" y2="0" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stop-color="{{ _rl }}"/>
            <stop offset="45%" stop-color="{{ _rc }}"/>
            <stop offset="100%" stop-color="{{ _rd }}"/>
          </linearGradient>
          <filter id="lrs_v1" x="-5%" y="-5%" width="110%" height="110%">
            <feDropShadow dx="-4" dy="8" stdDeviation="12" flood-color="rgba(0,0,0,0.7)"/>
          </filter>
        </defs>
        <!-- Center line from (130, 0) to (450, 320), Midpoint at (290, 160) -->
        <polygon
          points="50,0 210,0 450,240 450,400"
          fill="url(#lrg_v1)"
          filter="url(#lrs_v1)"/>
        <line x1="50" y1="0" x2="450" y2="400" stroke="rgba(255,255,255,0.25)" stroke-width="3"/>
        <line x1="210" y1="0" x2="450" y2="240" stroke="rgba(0,0,0,0.3)" stroke-width="2"/>
        <text
          transform="translate(290, 160) rotate(45)"
          text-anchor="middle"
          dominant-baseline="middle"
          font-family="-apple-system, BlinkMacSystemFont, PingFang SC, STHeiti, Microsoft YaHei, sans-serif"
          font-size="58"
          font-weight="900"
          fill="{{ _rt }}"
          letter-spacing="6"
          style="filter: drop-shadow(0 2px 4px rgba(0,0,0,0.4));">{{ content_label }}</text>
      </svg>
    </div>
    """,
    "v2_hanging_swallowtail": """
    <div style="position:absolute; top:0; right:75px; width:120px; height:220px; z-index:30; pointer-events:none;">
      <svg width="120" height="220" viewBox="0 0 120 220" xmlns="http://www.w3.org/2000/svg" style="filter: drop-shadow(0 8px 16px rgba(0,0,0,0.55));">
        <defs>
          <linearGradient id="lrg_v2" x1="0" y1="0" x2="0" y2="200" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stop-color="{{ _rl }}"/>
            <stop offset="70%" stop-color="{{ _rc }}"/>
            <stop offset="100%" stop-color="{{ _rd }}"/>
          </linearGradient>
        </defs>
        <!-- V-cut: 0,0 to 120,0 to 120,185 to 60,220 to 0,185 -->
        <polygon
          points="0,0 120,0 120,185 60,220 0,185"
          fill="url(#lrg_v2)"/>
        <line x1="0" y1="0" x2="0" y2="185" stroke="rgba(255,255,255,0.22)" stroke-width="2"/>
        <line x1="120" y1="0" x2="120" y2="185" stroke="rgba(0,0,0,0.25)" stroke-width="2"/>
        
        <!-- Center-aligned stacked text for 2 characters. Visual vertical midpoint at y=92.5 -->
        <text x="60" y="65" text-anchor="middle" dominant-baseline="middle"
              font-family="-apple-system, BlinkMacSystemFont, PingFang SC, STHeiti, Microsoft YaHei, sans-serif"
              font-size="44" font-weight="900" fill="{{ _rt }}">
          {{ content_label[0] if content_label else '' }}
        </text>
        <text x="60" y="120" text-anchor="middle" dominant-baseline="middle"
              font-family="-apple-system, BlinkMacSystemFont, PingFang SC, STHeiti, Microsoft YaHei, sans-serif"
              font-size="44" font-weight="900" fill="{{ _rt }}">
          {{ content_label[1] if content_label and content_label|length > 1 else '' }}
        </text>
      </svg>
    </div>
    """,
    "v3_floating_capsule": """
    {% set _rgb = '110, 68, 255' %}
    {% if content_label in ['重磅', '突发', '警示'] %}{% set _rgb = '239, 68, 68' %}
    {% elif content_label in ['独家', '首发', '专访'] %}{% set _rgb = '217, 119, 6' %}
    {% elif content_label == '最新' %}{% set _rgb = '8, 145, 178' %}
    {% elif content_label in ['深度', '解析', '完整版'] %}{% set _rgb = '124, 58, 237' %}
    {% elif content_label == '揭秘' %}{% set _rgb = '234, 88, 12' %}
    {% elif content_label == '局势' %}{% set _rgb = '29, 78, 216' %}
    {% else %}{% set _rgb = '156, 163, 175' %}{% endif %}
    
    <div style="position:absolute; top:75px; right:70px; z-index:30; pointer-events:none;
                display:flex; align-items:center; justify-content:center;
                background: rgba(15, 23, 42, 0.75);
                border: 2px solid {{ _rc }};
                border-radius: 40px;
                padding: 10px 28px;
                box-shadow: 0 0 25px rgba({{ _rgb }}, 0.45), inset 0 0 10px rgba({{ _rgb }}, 0.25);
                backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px);">
      <span style="width: 12px; height: 12px; border-radius: 50%; background-color: {{ _rl }}; 
                   margin-right: 14px; box-shadow: 0 0 12px {{ _rl }}; display: inline-block;"></span>
      <span style="font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', sans-serif;
                   font-size: 36px; font-weight: 900; color: #ffffff; letter-spacing: 4px;
                   text-shadow: 0 0 8px rgba(255,255,255,0.5);">
        {{ content_label }}
      </span>
    </div>
    """,
    "v4_integrated_tab": """
    <div style="position:absolute; top:115px; right:150px; z-index:25; pointer-events:none;
                background: linear-gradient(135deg, {{ _rl }} 0%, {{ _rc }} 100%);
                border: 2.5px solid rgba(255,255,255,0.45);
                border-bottom: none;
                border-radius: 20px 20px 0 0;
                padding: 8px 30px;
                height: 48px;
                box-shadow: 0 -8px 20px rgba(0,0,0,0.3);
                display: flex; align-items: center; justify-content: center;">
      <span style="font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', sans-serif;
                   font-size: 34px; font-weight: 900; color: {{ _rt }}; letter-spacing: 4px; line-height: 1;">
        {{ content_label }}
      </span>
    </div>
    """,
    "v5_hud_bracket": """
    {% set _rgb = '110, 68, 255' %}
    {% if content_label in ['重磅', '突发', '警示'] %}{% set _rgb = '239, 68, 68' %}
    {% elif content_label in ['独家', '首发', '专访'] %}{% set _rgb = '217, 119, 6' %}
    {% elif content_label == '最新' %}{% set _rgb = '8, 145, 178' %}
    {% elif content_label in ['深度', '解析', '完整版'] %}{% set _rgb = '124, 58, 237' %}
    {% elif content_label == '揭秘' %}{% set _rgb = '234, 88, 12' %}
    {% elif content_label == '局势' %}{% set _rgb = '29, 78, 216' %}
    {% else %}{% set _rgb = '156, 163, 175' %}{% endif %}
    
    <div style="position:absolute; top:90px; right:100px; z-index:30; pointer-events:none;
                display:flex; flex-direction:column; align-items:flex-end;">
      <!-- Horizontal indicator line with label -->
      <div style="display:flex; align-items:center; margin-bottom: 8px;">
        <!-- Small tech dot -->
        <span style="width: 8px; height: 8px; background-color: {{ _rl }}; margin-right: 10px; border-radius: 50%; box-shadow: 0 0 8px {{ _rl }};"></span>
        <!-- Small sub text -->
        <span style="font-family: monospace; font-size: 16px; color: {{ _rl }}; letter-spacing: 2px; font-weight: bold; text-transform: uppercase;">
          SYS_ALERT // {{ content_label }}
        </span>
      </div>
      <!-- Main label box -->
      <div style="background: linear-gradient(135deg, rgba({{ _rgb }}, 0.15) 0%, rgba({{ _rgb }}, 0.03) 100%);
                  border: 1px solid rgba({{ _rgb }}, 0.3);
                  border-right: 6px solid {{ _rl }};
                  border-radius: 4px;
                  padding: 12px 24px;
                  height: 48px;
                  box-shadow: -5px 5px 25px rgba(0,0,0,0.5);
                  backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px);
                  display: flex; align-items: center; justify-content: center;">
        <span style="font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', sans-serif;
                     font-size: 36px; font-weight: 900; color: #ffffff; letter-spacing: 6px; line-height: 1;
                     text-shadow: 0 0 10px rgba({{ _rgb }}, 0.8);">
          {{ content_label }}
        </span>
      </div>
      <!-- Corner bracket line accents -->
      <div style="width: 180px; height: 2px; background: linear-gradient(to left, transparent, {{ _rl }}); margin-top: 6px; opacity: 0.8;"></div>
    </div>
    """
}

def substitute_ribbon(template_text: str, new_ribbon_html: str) -> str:
    """[Gemini_3.5_Flash_planning] 使用正则替换 cover.html.j2 中原来的丝带 div """
    # 匹配从注释“右上角丝带定位”开始到 endif 之前的 div 块
    pattern = re.compile(
        r"(<!-- \[Gemini_3.5_Flash_planning\] 右上角丝带定位.*?-->\s*).*?(\s*{% endif %})",
        re.DOTALL
    )
    replaced, count = pattern.subn(rf"\1{new_ribbon_html}\2", template_text)
    if count == 0:
        raise ValueError("Could not find the ribbon pattern in template!")
    return replaced

def main():
    # 1. 初始化引擎并组装 LayoutSpec
    payload = {
        "title": "大模型底层重构",
        "subtitle": "2026年企业级AI爆发式增长的关键引擎",
        "category": "前沿科技",
        "content_label": "重磅"
    }
    
    print("Initializing CoverEngine...")
    engine = CoverEngine()
    signal = engine.analyzer.analyze(payload)
    theme = engine.registry.resolve(signal)
    layout_spec = engine.composer.compose(payload, signal, theme)
    
    # 2. 读取基本模板文件
    template_path = engine.template_dir / "cover.html.j2"
    if not template_path.exists():
        print(f"Error: Template not found at {template_path}")
        sys.exit(1)
        
    template_text = template_path.read_text(encoding="utf-8")
    
    # 3. 注入隐喻 SVG 并解析 payload
    metaphor_name = layout_spec.get("metaphor", "")
    layout_spec["metaphor_svg"] = engine.renderer._load_metaphor_svg(metaphor_name)
    
    # 4. 逐个渲染 5 个版本
    BRAIN_DIR.mkdir(parents=True, exist_ok=True)
    
    print("\n--- Starting Playwright Render Pipeline ---")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        
        for name, html_snippet in RIBBONS_HTML.items():
            print(f"Rendering: {name}...")
            
            # 替换模板里的丝带部分
            modified_template = substitute_ribbon(template_text, html_snippet)
            
            # 渲染 Jinja2
            template = Template(modified_template)
            rendered_html = template.render(**layout_spec)
            
            # 保存为临时 HTML 文件
            temp_html_path = BRAIN_DIR / f"temp_{name}.html"
            temp_html_path.write_text(rendered_html, encoding="utf-8")
            
            # 截图保存
            output_jpg_path = BRAIN_DIR / f"{name}.jpg"
            
            page = browser.new_page()
            page.set_viewport_size({"width": W, "height": H})
            
            file_url = temp_html_path.resolve().as_uri()
            page.goto(file_url, wait_until="networkidle")
            
            page.screenshot(path=str(output_jpg_path), type="jpeg", quality=95)
            page.close()
            
            # 删除临时 HTML 文件
            if temp_html_path.exists():
                os.remove(temp_html_path)
                
            print(f"✅ Generated: {output_jpg_path.name}")
            
        browser.close()
        
    print("All demos successfully generated!")

if __name__ == "__main__":
    main()
