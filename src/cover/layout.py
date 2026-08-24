"""布局参数装配器 (LayoutComposer)

# Modification History
| Version | Date       | Author                       | Description                                                  |
|---------|------------|------------------------------|--------------------------------------------------------------|
| 1.0.0   | 2026-05-26 | Gemini_3.5_Flash_planning    | 初始创建，组装 LayoutSpec，支持双层标题、安全区计算与隐喻位置  |
| 1.1.0   | 2026-06-02 | Gemini_2.5_Pro_planning      | 将 template_variant 字段加入 LayoutSpec，供 HTMLRenderer 选择对应模板文件 |
| 1.2.0   | 2026-06-02 | Gemini_2.5_Pro_planning      | 将 content_label 角标标签透传入 LayoutSpec，供模板渲染丝带角标 |
| 1.3.0   | 2026-06-02 | Gemini_2.5_Pro_planning      | icon/丝带角落冲突避免：丝带在右上角时，自动将 top-right icon 切换到 bottom-left |
| 1.4.0   | 2026-06-02 | Gemini_3.5_Flash_planning    | 修正 LayoutSpec 的 canvas_height 为 6:7 比例 (1260px) |
| 1.5.0   | 2026-07-31 | Codex                         | 支持专属主视觉图层与标题位置，主视觉存在时移除无关装饰图标 |
| 1.6.0   | 2026-08-21 | Codex                         | 停用模型运营角标，避免无事实依据的告警式装饰降低封面质量 |
| 1.7.0   | 2026-08-24 | Gemini_3.7_Flash_High_planning | 支持 ENGLISH_WORLD_SHORT 英语报刊封面载荷（双语金句、高亮、词汇卡、难度分级） |
| 1.8.0   | 2026-08-24 | Codex | 为英语封面补充真实词汇统计与长中文标题的双行排版数据。 |
"""

import html
import re
from typing import Dict, Any, List
from .semantic import ContentSignal


def _format_quote_en_html(quote_en: str, highlight_words: list[str]) -> str:
    """对英文原句中的重点生词安全注入高亮 span 标签"""
    if not quote_en:
        return ""
    safe_quote = html.escape(quote_en)
    if not highlight_words:
        return safe_quote
    for word in sorted(highlight_words, key=len, reverse=True):
        if not word:
            continue
        pattern = re.compile(rf"\b({re.escape(word)})\b", re.IGNORECASE)
        safe_quote = pattern.sub(r'<span class="hl">\1</span>', safe_quote)
    return safe_quote


def _title_lines(title: str) -> list[str]:
    """长中文标题固定分为两行，避免移动端出现单字孤行。"""
    compact = "".join(title.split())
    if len(compact) <= 11 or not all("\u4e00" <= char <= "\u9fff" for char in compact):
        return [title]
    split_at = len(compact) // 2
    if split_at < len(compact) - 1 and compact[split_at - 1] in "一二三四五六七八九十" and compact[split_at] in "个座只条本":
        split_at += 1
    return [compact[:split_at], compact[split_at:]]


class LayoutComposer:
    """
    布局分析与参数装配器 (LayoutComposer)
    将元数据（标题、副标题）、语义信号、主题配色等组装成标准的 HTML 渲染配置载荷 (LayoutSpec)。
    """
    def __init__(self):
        pass

    def compose(self, payload: dict, signal: ContentSignal, theme_resolved: dict) -> Dict[str, Any]:
        """
        [Gemini_3.5_Flash_planning] 组装 LayoutSpec 数据包，供 HTML/Jinja2 模板渲染使用
        """
        # 获取基础信息
        title = payload.get("title", "").strip()
        subtitle = payload.get("subtitle", "").strip()

        # 确定 badge 文本：如果 payload 指定了 category，则使用 category，否则使用默认语义默认值
        category = payload.get("category", "")
        badge = category if category else signal.default_badge
        visual_asset_path = str(payload.get("visual_asset_path", "") or "").strip()
        headline_position = str(payload.get("headline_position", "center") or "center").strip()
        if headline_position not in {"center", "upper_left"}:
            headline_position = "center"

        # [Gemini_3.7_Flash_High_planning] 提取英语世界专属教学字段
        quote_en = str(payload.get("quote_en") or payload.get("headline_en") or payload.get("english_text") or "").strip()
        quote_zh = str(payload.get("quote_zh") or payload.get("translation_zh") or "").strip()
        highlight_words = list(payload.get("highlight_words") or [])

        # 规范化词汇卡列表
        vocab_items = []
        raw_vocab = payload.get("vocab_items") or payload.get("vocabulary_candidates") or payload.get("vocabulary") or []
        for item in raw_vocab:
            if isinstance(item, dict):
                word = str(item.get("word") or "").strip()
                if not word:
                    continue
                vocab_items.append({
                    "word": word,
                    "ipa": str(item.get("ipa") or item.get("phonetic") or "").strip(),
                    "meaning": str(item.get("meaning") or item.get("context_meaning_zh") or item.get("meaning_zh") or "").strip(),
                    "level": str(item.get("level") or item.get("friendly_tag") or item.get("recommended_level") or "外刊高频").strip(),
                })
                if word not in highlight_words:
                    highlight_words.append(word)

        quote_en_html = _format_quote_en_html(quote_en, highlight_words)
        difficulty_tag = str(payload.get("difficulty_tag") or payload.get("difficulty_level") or "★★★☆☆ (中高考 / 四六级)").strip()
        audio_source = str(payload.get("audio_source") or payload.get("publisher") or "原声精选").strip()
        date_str = str(payload.get("date_str") or "今日外刊打卡").strip()
        vocab_stat = str(payload.get("vocab_stat") or f"本篇 {len(vocab_items)} 个核心词").strip()

        # 组装 layout_spec
        layout_spec = {
            "canvas_width": 1080,
            "canvas_height": 1260, # [Gemini_3.5_Flash_planning] 修正为 6:7 比例以适配视频号竖版封面要求

            # 文字载荷
            "title": title,
            "title_lines": _title_lines(title),
            "subtitle": subtitle,
            "badge": badge,
            "style_id": signal.id,
            "visual_asset_path": visual_asset_path,
            "has_visual_asset": bool(visual_asset_path),
            "headline_position": headline_position,

            # 英语世界专属教学载荷
            "quote_en": quote_en,
            "quote_zh": quote_zh,
            "quote_en_html": quote_en_html,
            "highlight_words": highlight_words,
            "vocab_items": vocab_items,
            "difficulty_tag": difficulty_tag,
            "audio_source": audio_source,
            "date_str": date_str,
            "vocab_stat": vocab_stat,

            # 主题视觉属性
            "accent_color": theme_resolved["accent_color"],
            "accent_glow": theme_resolved["accent_glow"],
            "background_gradient_start": theme_resolved["background_gradient_start"],
            "background_gradient_end": theme_resolved["background_gradient_end"],
            "noise_opacity": theme_resolved["noise_opacity"],
            "grid_color": theme_resolved["grid_color"],
            "orbs": theme_resolved["orbs"],

            # 隐喻属性
            "metaphor": signal.metaphor,
            "metaphor_placement": signal.metaphor_placement,
            "show_metaphor": not bool(visual_asset_path),

            # [Gemini_2.5_Pro_planning] v1.1.0 模板变体选择
            # rules.json 中每条规则可指定 template_variant 字段
            # 可选值：'cover'（默认）/ 'cover_minimal' / 'cover_drama' / 'cover_english_newspaper'
            "template_variant": getattr(signal, 'template_variant', 'cover'),

            # 运营标签容易制造与内容无关的告警/揭秘式装饰；保留分类 badge，统一不渲染标签。
            "content_label": "",

            # 安全区参数（按比例，供 CSS 使用）
            "safe_zone": {
                "top_pct": 12,      # 顶部保留 12% 避开微信头像/状态栏
                "bottom_pct": 88,   # 底部保留 12% 避开播放控件
                "margin_pct": 10    # 左右留白 10%
            }
        }
        
        return layout_spec
