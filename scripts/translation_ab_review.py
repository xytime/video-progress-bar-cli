#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""字幕翻译 A/B 质量评估脚本。

从现有双语 ASS 中抽取英文源文本和当前中文译文，调用指定 provider 生成
候选译文，并复用通用质量评估器输出同片对比报告。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-06 | Codex  | 初始创建：支持从 ASS 抽取当前译文并与 DeepSeek 候选做质量对比 |
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Sequence

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SRC_ROOT = _PROJECT_ROOT / "src"
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

import pysubs2  # noqa: E402

from video_processing.utils.deepseek_translation import translate_batch_deepseek  # noqa: E402
from video_processing.utils.translation_context import build_translation_context  # noqa: E402
from video_processing.utils.translation_quality_evaluator import (  # noqa: E402
    TranslationQualityContext,
    evaluate_translation_candidate,
)


def strip_ass_tags(text: str) -> str:
    """去掉 ASS override tags，并把强制换行折成普通空格。"""
    text = re.sub(r"\{[^{}]*\}", "", text or "")
    text = text.replace("\\N", " ")
    return re.sub(r"\s+", " ", text).strip()


def split_bilingual_ass_text(text: str) -> tuple[str, str]:
    """拆分本项目 Default 事件中的英文层和中文层。"""
    marker = re.search(r"\{[^{}]*\\alpha&HFF&[^{}]*\}\s*\\N", text or "", re.IGNORECASE)
    if marker:
        return strip_ass_tags(text[:marker.start()]), strip_ass_tags(text[marker.end():])

    first_zh = re.search(r"[\u4e00-\u9fff]", text or "")
    if first_zh:
        return strip_ass_tags(text[:first_zh.start()]), strip_ass_tags(text[first_zh.start():])
    return strip_ass_tags(text), ""


def load_ass_pairs(ass_path: Path) -> List[Dict[str, str]]:
    """从双语 ASS 加载可评估字幕片段。"""
    subs = pysubs2.load(str(ass_path))
    pairs: List[Dict[str, str]] = []
    for event in subs.events:
        if event.style != "Default":
            continue
        source, current = split_bilingual_ass_text(event.text)
        if not source:
            continue
        pairs.append({
            "start": str(event.start),
            "end": str(event.end),
            "source": source,
            "current": current,
        })
    return pairs


def load_metadata(info_json: Path | None, *, fallback_title: str = "") -> tuple[str, str]:
    """读取 yt-dlp info.json 中的标题和简介。"""
    if not info_json or not info_json.exists():
        return fallback_title, ""
    data = json.loads(info_json.read_text(encoding="utf-8"))
    return str(data.get("title") or fallback_title), str(data.get("description") or "")


def default_info_path(ass_path: Path) -> Path:
    """按现有 output 布局推断 info.json 位置。"""
    if ass_path.parent.name == "original_video":
        return ass_path.parent.parent / f"{ass_path.stem}.info.json"
    return ass_path.with_name(f"{ass_path.stem}.info.json")


def build_quality_context(source_texts: Sequence[str], *, title: str, description: str) -> TranslationQualityContext:
    """构建与生产链路一致的质量上下文。"""
    context = build_translation_context(source_texts, title=title, description=description)
    return TranslationQualityContext(
        source_context_text="\n".join(part for part in (title, description, *source_texts) if part),
        domain=context.domain,
        facts=context.facts,
        entities=context.entities,
        term_notes=context.term_notes,
        style_notes=context.style_notes,
    )


def summarize_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """压缩审计事件，便于命令行快速比较。"""
    warning_codes = [issue["code"] for issue in event.get("warning_issues", [])]
    blocking_codes = [issue["code"] for issue in event.get("blocking_issues", [])]
    return {
        "provider": event.get("provider", ""),
        "status": event.get("status", ""),
        "action": event.get("action", ""),
        "warning_count": len(warning_codes),
        "blocking_count": len(blocking_codes),
        "warning_issue_counts": dict(Counter(warning_codes)),
        "blocking_issue_counts": dict(Counter(blocking_codes)),
    }


def build_diff_samples(
    pairs: Sequence[Dict[str, str]],
    candidate_translations: Sequence[str],
    *,
    limit: int,
) -> List[Dict[str, str]]:
    """输出前几条当前译文与候选译文不同的样例。"""
    samples: List[Dict[str, str]] = []
    for pair, candidate in zip(pairs, candidate_translations):
        current = pair.get("current", "")
        if current == candidate:
            continue
        samples.append({
            "source": pair["source"],
            "current": current,
            "candidate": candidate,
        })
        if len(samples) >= limit:
            break
    return samples


def run_review(
    ass_path: Path,
    *,
    info_json: Path | None,
    output_path: Path | None,
    sample_limit: int,
) -> Dict[str, Any]:
    """执行 DeepSeek vs 当前 ASS 译文的同片质量对比。"""
    pairs = load_ass_pairs(ass_path)
    if not pairs:
        raise ValueError(f"No Default subtitle pairs found in {ass_path}")

    title, description = load_metadata(info_json or default_info_path(ass_path), fallback_title=ass_path.stem)
    source_texts = [pair["source"] for pair in pairs]
    current_translations = [pair.get("current", "") for pair in pairs]
    context = build_translation_context(source_texts, title=title, description=description)
    prompt_context = context.to_prompt_context()
    quality_context = build_quality_context(source_texts, title=title, description=description)

    candidate_translations = translate_batch_deepseek(source_texts, context_text=prompt_context)
    if candidate_translations is None:
        raise RuntimeError("DeepSeek returned no parseable translation candidate")

    current_decision = evaluate_translation_candidate(
        source_texts,
        current_translations,
        provider="CurrentASS",
        final_provider=True,
        quality_context=quality_context,
    )
    deepseek_decision = evaluate_translation_candidate(
        source_texts,
        candidate_translations,
        provider="DeepSeek",
        final_provider=True,
        quality_context=quality_context,
    )
    current_event = current_decision.to_audit_event(final_provider=True)
    deepseek_event = deepseek_decision.to_audit_event(final_provider=True)
    report = {
        "input": str(ass_path),
        "source_title": title,
        "segment_count": len(pairs),
        "quality_context": quality_context.to_audit_context(),
        "summary": {
            "current": summarize_event(current_event),
            "deepseek": summarize_event(deepseek_event),
        },
        "events": [current_event, deepseek_event],
        "diff_samples": build_diff_samples(pairs, candidate_translations, limit=sample_limit),
    }
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run subtitle translation A/B quality review.")
    parser.add_argument("ass_path", type=Path, help="Existing bilingual ASS path")
    parser.add_argument("--info-json", type=Path, default=None, help="Optional yt-dlp info.json path")
    parser.add_argument("--output", type=Path, default=None, help="Output JSON report path")
    parser.add_argument("--sample-limit", type=int, default=8, help="Number of changed segment samples")
    args = parser.parse_args()

    output_path = args.output
    if output_path is None:
        output_path = args.ass_path.with_name(f"{args.ass_path.stem}_translation_ab_review.json")

    report = run_review(
        args.ass_path,
        info_json=args.info_json,
        output_path=output_path,
        sample_limit=max(0, args.sample_limit),
    )
    print(json.dumps({
        "output": str(output_path),
        "source_title": report["source_title"],
        "segment_count": report["segment_count"],
        "summary": report["summary"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
