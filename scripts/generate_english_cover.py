#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""英语世界短视频专属封面生成 CLI (generate_english_cover.py)

支持通过 Timeline JSON、Payload JSON 或命令行参数直接生成符合 6:7 规范的报刊封面。

# Modification History
| Version | Date       | Author                         | Description                                            |
|---------|------------|--------------------------------|--------------------------------------------------------|
| 1.0.0   | 2026-08-24 | Gemini_3.7_Flash_High_planning | 初始创建：提供确定性 Prompt/JSON/Timeline 的多模式命令行封面生成入口 |
| 1.1.0   | 2026-08-24 | Codex | 改用共享载荷构建器，并输出 payload/timeline 哈希审计信息。 |
| 1.2.0   | 2026-08-24 | Codex | 支持绑定已验收的无字 Antigravity 主视觉。 |
| 1.3.0   | 2026-08-28 | Codex | Chromium 不可启动时改用本地 Pillow 渲染英语报刊封面，避免回退路径仍依赖浏览器。 |
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import signal
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from cover import CoverEngine, build_english_world_cover_payload, validate_english_world_cover_payload
from video_processing.core.cover_policy import compliant_cover_layout_policy


def extract_payload_from_timeline(timeline_data: dict) -> dict:
    """兼容旧调用；真实提取逻辑位于 core 层的共享纯函数。"""
    return build_english_world_cover_payload(timeline_data)


_CJK_FONT_CANDIDATES = (
    PROJECT_ROOT / "assets" / "fonts" / "SourceHanSerifCN-Medium.otf",
    Path("/System/Library/Fonts/PingFang.ttc"),
    Path("/System/Library/Fonts/STHeiti Light.ttc"),
)


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """加载可显示中文的本地字体；备用路径不依赖浏览器或网络。"""
    for candidate in _CJK_FONT_CANDIDATES:
        if not candidate.is_file():
            continue
        try:
            index = 5 if bold and "PingFang" in candidate.name else 0
            return ImageFont.truetype(str(candidate), size, index=index)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrapped_lines(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, *, width: int, limit: int) -> list[str]:
    """按实际像素宽度折行；末行截断而不让封面文字越界。"""
    source = str(text or "")
    tokens = re.findall(r"[A-Za-z0-9’'-]+\\s*|[^\\s]", source)
    lines: list[str] = []
    current = ""
    for token in tokens:
        candidate = f"{current}{token}"
        if current and draw.textbbox((0, 0), candidate, font=font)[2] > width:
            lines.append(current.rstrip())
            current = token.lstrip()
            if len(lines) >= limit:
                break
        else:
            current = candidate
    if current and len(lines) < limit:
        lines.append(current.rstrip())
    if not lines:
        return [""]
    if len(lines) == limit and len("".join(lines)) < len(source):
        lines[-1] = lines[-1].rstrip(".。…") + "…"
    return lines


def _render_with_pillow_fallback(layout: dict, output: Path) -> None:
    """浏览器受 macOS 阻断时，渲染同规格的英语报刊封面。"""
    width, height = 1080, 1260
    image = Image.new("RGB", (width, height), "#FBF9F4")
    draw = ImageDraw.Draw(image)
    draw.rectangle((14, 14, width - 14, height - 14), outline="#EFEAE0", width=14)

    badge_font = _font(30, bold=True)
    meta_font = _font(20, bold=True)
    draw.rounded_rectangle((48, 48, 288, 104), radius=4, fill="#A53C2B")
    draw.text((66, 58), str(layout.get("badge") or "世界英语新闻精读"), font=badge_font, fill="#FFFFFF")
    draw.text((594, 65), "DAILY NEWS · STUDY", font=meta_font, fill="#6E625A")
    draw.line((48, 124, width - 48, 124), fill="#1E1A18", width=3)
    draw.text((48, 142), str(layout.get("date_str") or "今日英语打卡"), font=meta_font, fill="#8C7E72")
    draw.text((660, 142), str(layout.get("difficulty_tag") or "英语精读"), font=meta_font, fill="#8C7E72")
    draw.line((48, 176, width - 48, 176), fill="#D8CFC4", width=2)

    title_font = _font(82, bold=True)
    title_lines = list(layout.get("title_lines") or [layout.get("title") or "英语世界"])
    title_y = 206
    for line in title_lines[:2]:
        draw.text((52, title_y), str(line), font=title_font, fill="#1E1A18", stroke_width=2, stroke_fill="#E7DED3")
        title_y += 98

    quote_en_font = _font(31)
    quote_zh_font = _font(27)
    quote_y = max(402, title_y + 12)
    draw.rounded_rectangle((48, quote_y, width - 48, quote_y + 248), radius=14, fill="#F3ECE0", outline="#E6DDD0", width=2)
    draw.rectangle((48, quote_y, 58, quote_y + 248), fill="#A53C2B")
    draw.text((82, quote_y + 22), "KEY SENTENCE · 精选原声金句", font=meta_font, fill="#A53C2B")
    line_y = quote_y + 62
    for line in _wrapped_lines(draw, str(layout.get("quote_en") or ""), quote_en_font, width=880, limit=3):
        draw.text((82, line_y), line, font=quote_en_font, fill="#2D241E")
        line_y += 42
    line_y += 6
    for line in _wrapped_lines(draw, str(layout.get("quote_zh") or ""), quote_zh_font, width=880, limit=2):
        draw.text((82, line_y), line, font=quote_zh_font, fill="#5A4E44")
        line_y += 36

    cards_y = quote_y + 276
    draw.text((48, cards_y), "本篇核心词汇", font=meta_font, fill="#8C7E72")
    for index, card in enumerate(list(layout.get("vocab_items") or [])[:2]):
        x0 = 48 + index * 492
        draw.rounded_rectangle((x0, cards_y + 38, x0 + 468, cards_y + 198), radius=12, fill="#FFFFFF", outline="#E6DDD0", width=2)
        draw.rectangle((x0, cards_y + 38, x0 + 6, cards_y + 198), fill="#A87914")
        draw.text((x0 + 24, cards_y + 56), str(card.get("word") or ""), font=_font(29, bold=True), fill="#1E1A18")
        draw.text((x0 + 24, cards_y + 97), str(card.get("meaning") or ""), font=_font(23), fill="#4A3E34")
        draw.text((x0 + 24, cards_y + 132), str(card.get("level") or "英语学习"), font=_font(20, bold=True), fill="#785A18")

    # 纯抽象编辑插画：不使用原视频帧，也不使用网页截图。
    illustration = Image.new("RGBA", (width - 96, 250), (0, 0, 0, 0))
    art = ImageDraw.Draw(illustration)
    art.rounded_rectangle((0, 0, illustration.width - 1, illustration.height - 1), radius=18, fill="#EAF0ED", outline="#D5E0DA", width=2)
    art.ellipse((585, -85, 920, 250), fill="#9CBEB0")
    art.ellipse((700, 35, 1040, 330), fill="#D6A975")
    art.ellipse((610, 42, 790, 222), fill="#F6E7C8")
    art.line((88, 70, 505, 70), fill="#A53C2B", width=6)
    art.line((88, 116, 425, 116), fill="#A87914", width=6)
    art.line((88, 162, 348, 162), fill="#6E625A", width=6)
    image.paste(illustration.filter(ImageFilter.GaussianBlur(0.15)), (48, height - 326), illustration)
    draw = ImageDraw.Draw(image)
    draw.line((48, height - 54, width - 48, height - 54), fill="#D8CFC4", width=2)
    draw.text((48, height - 42), "英语世界｜原声双语精读", font=meta_font, fill="#A53C2B")
    draw.text((770, height - 42), str(layout.get("vocab_stat") or "每日学习"), font=meta_font, fill="#6E625A")

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, quality=95)


@contextmanager
def _browser_render_deadline(seconds: float):
    """为 Chromium 启动设置硬上限，避免卡死时永远到不了本地回退。"""
    if seconds <= 0:
        yield
        return

    def _expired(_signum, _frame):
        raise TimeoutError(f"Playwright cover render exceeded {seconds:g}s")

    previous_handler = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, _expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成英语世界短视频专属 6:7 报刊封面")
    parser.add_argument("--timeline", type=Path, help="已 enriched 的时间轴 JSON 文件路径")
    parser.add_argument("--payload", type=str, help="直接传入的 JSON payload 字符串")
    parser.add_argument("--payload-file", type=Path, help="JSON payload 文件路径")
    parser.add_argument("--output", "-o", required=True, type=Path, help="输出的封面 JPG/PNG 绝对路径")
    parser.add_argument("--provenance-output", type=Path, help="可选：输出的来源审计 JSON 文件路径")
    parser.add_argument("--payload-output", type=Path, help="可选：写入实际渲染的规范化 payload JSON")
    parser.add_argument("--visual-asset", type=Path, help="已通过无字验收的本地主视觉 PNG/JPG")
    parser.add_argument("--visual-asset-manifest", type=Path, help="可选：主视觉候选验收记录 JSON")
    parser.add_argument("--browser-timeout-seconds", type=float, default=20.0, help="Playwright 渲染最大等待时间；超时改用本地封面")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.browser_timeout_seconds <= 0:
        raise ValueError("--browser-timeout-seconds must be greater than 0")
    payload = {}
    source_timeline_sha256 = None
    if sum(bool(value) for value in (args.timeline, args.payload, args.payload_file)) != 1:
        print("Error: 必须且只能提供 --timeline, --payload 或 --payload-file 之一", file=sys.stderr)
        return 1

    if args.timeline:
        if not args.timeline.is_file():
            print(f"Error: timeline file not found: {args.timeline}", file=sys.stderr)
            return 1
        timeline_bytes = args.timeline.read_bytes()
        timeline_data = json.loads(timeline_bytes)
        payload = extract_payload_from_timeline(timeline_data)
        source_timeline_sha256 = hashlib.sha256(timeline_bytes).hexdigest()
    elif args.payload_file:
        if not args.payload_file.is_file():
            print(f"Error: payload file not found: {args.payload_file}", file=sys.stderr)
            return 1
        payload = json.loads(args.payload_file.read_text(encoding="utf-8"))
    elif args.payload:
        try:
            payload = json.loads(args.payload)
        except json.JSONDecodeError as exc:
            print(f"Error: invalid JSON payload: {exc}", file=sys.stderr)
            return 1
    else:
        print("Error: 必须提供 --timeline, --payload 或 --payload-file 之一", file=sys.stderr)
        return 1

    try:
        payload = validate_english_world_cover_payload(payload)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    visual_asset = None
    if args.visual_asset:
        visual_asset = args.visual_asset.expanduser().resolve()
        if not visual_asset.is_file():
            print(f"Error: visual asset file not found: {visual_asset}", file=sys.stderr)
            return 1
        payload["visual_asset_path"] = str(visual_asset)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    engine = CoverEngine()
    try:
        with _browser_render_deadline(args.browser_timeout_seconds):
            layout = engine.generate(payload, str(args.output))
        render_backend = "playwright"
    except Exception as exc:
        # launchd/Codex 沙箱下 Chromium 可能被 macOS MachPort 策略拒绝；
        # 备用封面必须真正脱离浏览器，不能把同一故障伪装成“回退”。
        print(f"Playwright cover render unavailable; using Pillow fallback: {exc}", file=sys.stderr)
        layout = engine.plan(payload)
        _render_with_pillow_fallback(layout, args.output)
        render_backend = "pillow"
    payload_sha256 = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    if args.payload_output:
        args.payload_output.parent.mkdir(parents=True, exist_ok=True)
        args.payload_output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.provenance_output:
        digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
        args.provenance_output.parent.mkdir(parents=True, exist_ok=True)
        args.provenance_output.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "cover_kind": "dedicated_generated_image",
                    "uses_video_frame": False,
                    "cover_filename": args.output.name,
                    "cover_sha256": digest,
                    "audio_edition": payload.get("audio_edition", "original_audio_subtitled"),
                    "visual_asset": (
                        {
                            "kind": "dedicated_generated_visual",
                            "filename": visual_asset.name,
                            "sha256": hashlib.sha256(visual_asset.read_bytes()).hexdigest(),
                            "manifest": str(args.visual_asset_manifest.resolve()) if args.visual_asset_manifest and args.visual_asset_manifest.is_file() else None,
                        }
                        if visual_asset
                        else None
                    ),
                    "layout_policy": compliant_cover_layout_policy(),
                    "template_variant": layout["template_variant"],
                    "payload_sha256": payload_sha256,
                    "source_timeline_sha256": source_timeline_sha256,
                    "generator": "scripts/generate_english_cover.py@1.3.0",
                    "render_backend": render_backend,
                },
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )

    print(f"✅ 英语封面生成成功: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
