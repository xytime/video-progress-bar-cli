# -*- coding: utf-8 -*-
"""上沿防遮挡专业 ASS 字幕生成器 (subtitle_generator.py)

特性与合规指标：
1. 顶部上沿安全区定位：Alignment 8 (Top-Center), MarginV: 570
   精准停留在 16:9 居中视频的上沿上方 (y=570~625)，既不遮挡画面主体，
   又彻底规避微信视频号底部约 350px 互动区域遮挡。
2. 财经关键词动态高亮：采用 ASS 金色代码 `{\\c&H20D0FF&}` 突出核心数据与专有名词。
3. 纯黑磨砂半透明胶囊边框：BorderStyle 3 (Opaque Box), BackColour `&HD0080D14`。

# Modification History
| Version | Date       | Author      | Description |
| ------- | ---------- | ----------- | ----------- |
| 1.0.0   | 2026-10-25 | Antigravity | 初始创建，实现 9:16 上沿安全区 ASS 字幕与关键词高亮引擎 |
| 1.2.0 | 2026-10-25 | Codex | 封闭用户 ASS 控制语法及头部换行注入 |
| 1.1.0   | 2026-10-25 | Antigravity | 重构关键词高亮为非重叠区间映射（彻底消除标签损坏），引入 tag_aware_wrap_zh 长句优雅折行 |
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import unicodedata
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


logger = logging.getLogger(__name__)

# 标准 ASS 字幕样式模板 (1080x1920)
ASS_HEADER_TEMPLATE = """[Script Info]
Title: {title}
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},{primary_color},&H000000FF,{outline_color},{back_box_color},-1,0,0,0,100,100,0,0,{border_style},{outline_width},0,{alignment},30,30,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

GOLD_ON = "{\\c&H20D0FF&}"
GOLD_OFF = "{\\c&HFFFFFF&}"


def seconds_to_ass_time(sec: float) -> str:
    """将秒数浮点数转换为 ASS 标准时间戳格式 (H:MM:SS.cs)。"""
    total_cs = int(round(sec * 100))
    h = total_cs // 360000
    m = (total_cs % 360000) // 6000
    s = (total_cs % 6000) // 100
    cs = total_cs % 100
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def sanitize_ass_text(text: str) -> str:
    """用户文本不能执行 ASS override、转义或注入新事件。"""
    if not isinstance(text, str):
        raise ValueError("subtitle text must be string")
    return "".join(ch for ch in text if unicodedata.category(ch) not in {"Cc", "Cf"}).replace("\\", "＼").replace("{", "｛").replace("}", "｝")


def apply_keyword_highlights(text: str, keywords: List[str]) -> str:
    """在文本中为命中关键词包裹金色高亮标签。使用区间映射算法，杜绝标签嵌套损坏与重复包裹。"""
    text = sanitize_ass_text(text)
    keywords = [sanitize_ass_text(k) for k in keywords]
    if not keywords or not text:
        return text

    valid_kws = [k for k in set(keywords) if k]
    if not valid_kws:
        return text

    # 按关键词长度降序排序
    valid_kws.sort(key=len, reverse=True)

    # 在原始干净文本上查找所有匹配区间 (start, end)
    spans: List[Tuple[int, int]] = []
    for kw in valid_kws:
        start_idx = 0
        while True:
            idx = text.find(kw, start_idx)
            if idx == -1:
                break
            spans.append((idx, idx + len(kw)))
            start_idx = idx + 1

    if not spans:
        return text

    # 按起始位置升序、长度降序排序
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))

    # 过滤重叠区间，优先保留最长匹配
    non_overlapping: List[Tuple[int, int]] = []
    last_end = 0
    for s_start, s_end in spans:
        if s_start >= last_end:
            non_overlapping.append((s_start, s_end))
            last_end = s_end

    # 构建高亮文本
    out: List[str] = []
    curr = 0
    for s_start, s_end in non_overlapping:
        out.append(text[curr:s_start])
        out.append(f"{GOLD_ON}{text[s_start:s_end]}{GOLD_OFF}")
        curr = s_end
    out.append(text[curr:])
    return "".join(out)


class TopEdgeSubtitleGenerator:
    """顶部上沿防遮挡字幕生成器。"""

    def __init__(
        self,
        font_name: str = "Hiragino Sans GB",
        font_size: int = 46,
        alignment: int = 8,
        margin_v: int = 570,
        primary_color: str = "&H00FFFFFF",
        outline_color: str = "&H00141A24",
        back_box_color: str = "&HD0080D14",
        border_style: int = 3,
        outline_width: int = 10,
    ):
        self.font_name = font_name
        self.font_size = font_size
        self.alignment = alignment
        self.margin_v = margin_v
        self.primary_color = primary_color
        self.outline_color = outline_color
        self.back_box_color = back_box_color
        self.border_style = border_style
        self.outline_width = outline_width

    def build_ass_header(self, title: str = "Compliance Video Remix Subtitles") -> str:
        """构建 ASS 文件头部与样式定义。"""
        return ASS_HEADER_TEMPLATE.format(
            title=sanitize_ass_text(title),
            font_name=sanitize_ass_text(self.font_name).replace(",", " "),
            font_size=self.font_size,
            primary_color=self.primary_color,
            outline_color=self.outline_color,
            back_box_color=self.back_box_color,
            border_style=self.border_style,
            outline_width=self.outline_width,
            alignment=self.alignment,
            margin_v=self.margin_v,
        )

    def generate_subtitles(
        self,
        clauses_with_timing: List[Tuple[float, float, str]],
        output_path: Path | str,
        keywords: Optional[List[str]] = None,
        title: str = "Compliance Video Remix Subtitles",
    ) -> Path:
        """生成完整的 ASS 字幕文件。

        Args:
            clauses_with_timing: 包含 (start_s, end_s, text) 的列表。
            output_path: ASS 输出路径。
            keywords: 需高亮的关键词列表。
            title: ASS 脚本标题。
        """
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)

        kws = keywords or []
        events: List[str] = []

        # 导入项目标准 tag_aware_wrap_zh
        try:
            from video_processing.utils.subtitle_stylist import tag_aware_wrap_zh
        except Exception:
            tag_aware_wrap_zh = None

        for start_s, end_s, text in clauses_with_timing:
            if not all(isinstance(t, (int, float)) and not isinstance(t, bool) and math.isfinite(t) for t in (start_s, end_s)) or start_s < 0 or end_s <= start_s:
                raise ValueError("invalid subtitle timing")
            if not text.strip():
                continue
            hl_text = apply_keyword_highlights(text.strip(), kws)
            # 使用项目统一规范：先高亮后 tag-aware 折行，最大宽约 18 字
            if tag_aware_wrap_zh:
                wrapped_text = tag_aware_wrap_zh(hl_text, max_width=18)
            else:
                wrapped_text = hl_text
            # ASS 换行符转义
            wrapped_text = wrapped_text.replace("\n", "\\N")
            start_str = seconds_to_ass_time(start_s)
            end_str = seconds_to_ass_time(end_s)
            events.append(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{wrapped_text}")

        content = self.build_ass_header(title) + "\n".join(events) + "\n"
        out_p.write_text(content, encoding="utf-8")
        logger.info(f"Subtitles successfully written to {out_p} ({len(events)} lines)")
        return out_p


def main():
    parser = argparse.ArgumentParser(description="上沿防遮挡 ASS 字幕生成工具")
    parser.add_argument("--input-json", type=str, help="包含分句与时码的 JSON 文件")
    parser.add_argument("--output", type=str, required=True, help="ASS 输出文件路径")
    parser.add_argument("--title", type=str, default="Remix Subtitles", help="字幕标题")
    args = parser.parse_args()

    gen = TopEdgeSubtitleGenerator()
    if args.input_json:
        data = json.loads(Path(args.input_json).read_text("utf-8"))
        # 兼容 list of [start, end, text]
        clauses = [(float(c[0]), float(c[1]), str(c[2])) for c in data.get("clauses", [])]
        kws = data.get("keywords", [])
        gen.generate_subtitles(clauses, args.output, keywords=kws, title=args.title)
        print(f"Subtitles written: {args.output}")


if __name__ == "__main__":
    main()
