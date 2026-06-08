#!/usr/bin/env python3
"""
[Claude_Sonnet_4.6_Thinking_planning] 验证脚本：
从生成的 ASS 文件中读取实际样式值，数学计算主字幕与 GlossaryCard 的空间占用，
证明两者不重叠，且 GlossaryCard 底部满足视频号 10% 安全区要求。
"""
import re
import sys

ASS_FILE = "XcSdPK5Xwbk_1min.ass"
CANVAS_HEIGHT = 1920
WECHAT_SAFETY_MARGIN = int(CANVAS_HEIGHT * 0.10)  # 192

# ── 1. 解析样式行 ──────────────────────────────────────────────────────────────
styles = {}
with open(ASS_FILE, encoding='utf-8') as f:
    for line in f:
        if line.startswith("Style:"):
            parts = [p.strip() for p in line[len("Style:"):].split(',')]
            # ASS Format columns (0-based):
            # 0=Name, 1=Fontname, 2=Fontsize, 3=PriColour, 4=SecColour,
            # 5=OutlineColour, 6=BackColour, 7=Bold, 8=Italic, 9=Underline,
            # 10=StrikeOut, 11=ScaleX, 12=ScaleY, 13=Spacing, 14=Angle,
            # 15=BorderStyle, 16=Outline, 17=Shadow, 18=Alignment,
            # 19=MarginL, 20=MarginR, 21=MarginV, 22=Encoding
            name        = parts[0]
            fontsize    = int(parts[2])
            borderstyle = int(parts[15])
            outline     = int(parts[16])
            alignment   = int(parts[18])
            marginv     = int(parts[21])
            styles[name] = dict(fontsize=fontsize, borderstyle=borderstyle,
                                outline=outline, alignment=alignment, marginv=marginv)

print("=" * 60)
print(f"Canvas: 1080 × {CANVAS_HEIGHT}")
print(f"WeChat safety margin: {WECHAT_SAFETY_MARGIN}px (10%)")
print()

# ── 2. 主字幕 (Default) 空间估算 ────────────────────────────────────────────────
s = styles["Default"]
SUBTITLE_TOP = s["marginv"]        # alignment=8 → top of text block
LINE_HEIGHT_FACTOR = 1.25          # libass default line spacing

# Bilingual layout: en(59pt) + spacer(24pt) + zh(68pt)
en_size = 59
spacer_size = 24
zh_size = 68
outline_px = s["outline"]

# Worst case: 2 lines English + spacer + 2 lines Chinese (based on actual ASS file observation)
# From the ASS file, first dialogue has 2-line english + spacer + 2-line chinese
en_lines = 2
zh_lines = 2

subtitle_text_height = (
    en_lines * en_size * LINE_HEIGHT_FACTOR +
    spacer_size +
    zh_lines * zh_size * LINE_HEIGHT_FACTOR +
    outline_px * 2  # top + bottom padding
)
SUBTITLE_BOTTOM = SUBTITLE_TOP + subtitle_text_height

print(f"── Default (主字幕) ─────────────────────────────────")
print(f"  alignment={s['alignment']} (Top Center), marginv={s['marginv']}")
print(f"  fontsize={s['fontsize']}, outline={s['outline']}")
print(f"  TOP    : Y = {SUBTITLE_TOP}")
print(f"  HEIGHT : {en_lines}×{en_size}×{LINE_HEIGHT_FACTOR} + {spacer_size} + {zh_lines}×{zh_size}×{LINE_HEIGHT_FACTOR} + {outline_px*2}(outline) = {subtitle_text_height:.0f}px")
print(f"  BOTTOM : Y ≈ {SUBTITLE_BOTTOM:.0f}")
print()

# ── 3. GlossaryCard 空间估算 ────────────────────────────────────────────────────
g = styles["GlossaryCard"]
GLOSSARY_BOTTOM_LIMIT = CANVAS_HEIGHT - g["marginv"]  # alignment=2 → bottom from canvas bottom
glossary_fontsize = g["fontsize"]
glossary_outline = g["outline"]
LINE_HEIGHT_FACTOR_G = 1.5  # tighter for compact gloss card

# Worst case: 3 vocab items
vocab_items = 3
glossary_text_height = (
    vocab_items * glossary_fontsize * LINE_HEIGHT_FACTOR_G +
    glossary_outline * 2
)
GLOSSARY_TOP = GLOSSARY_BOTTOM_LIMIT - glossary_text_height

print(f"── GlossaryCard (释义底栏) ──────────────────────────")
print(f"  alignment={g['alignment']} (Bottom Center), marginv={g['marginv']}")
print(f"  fontsize={g['fontsize']}, outline={g['outline']}")
print(f"  BOTTOM : Y = {CANVAS_HEIGHT} - {g['marginv']} = {GLOSSARY_BOTTOM_LIMIT}")
print(f"  HEIGHT : {vocab_items}×{glossary_fontsize}×{LINE_HEIGHT_FACTOR_G} + {glossary_outline*2}(outline) = {glossary_text_height:.0f}px")
print(f"  TOP    : Y ≈ {GLOSSARY_TOP:.0f}")
print()

# ── 4. 重叠判断 ─────────────────────────────────────────────────────────────────
gap = GLOSSARY_TOP - SUBTITLE_BOTTOM
wechat_clearance = CANVAS_HEIGHT - GLOSSARY_BOTTOM_LIMIT

print("=" * 60)
print(f"RESULT 1 - 主字幕 vs GlossaryCard 间距")
print(f"  GlossaryCard TOP  : Y ≈ {GLOSSARY_TOP:.0f}")
print(f"  Subtitle BOTTOM   : Y ≈ {SUBTITLE_BOTTOM:.0f}")
print(f"  Gap               : {gap:.0f}px")
if gap >= 0:
    print(f"  ✅ PASS: No overlap. Gap = {gap:.0f}px")
else:
    print(f"  ❌ FAIL: OVERLAP by {-gap:.0f}px!")

print()
print(f"RESULT 2 - 视频号底部安全区")
print(f"  GlossaryCard BOTTOM : Y = {GLOSSARY_BOTTOM_LIMIT}")
print(f"  WeChat Safety Zone  : bottom {wechat_clearance}px ({wechat_clearance/CANVAS_HEIGHT*100:.1f}%)")
if wechat_clearance >= WECHAT_SAFETY_MARGIN:
    print(f"  ✅ PASS: {wechat_clearance}px clearance >= {WECHAT_SAFETY_MARGIN}px required (10%)")
else:
    print(f"  ❌ FAIL: only {wechat_clearance}px clearance, need {WECHAT_SAFETY_MARGIN}px!")
print("=" * 60)
