#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""为独立新闻精读时间线生成可审阅的生词候选。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0 | 2026-08-02 | Codex | 初始创建：调用既有词汇服务生成十级生词候选，不接入发布流水线。 |
| 1.1.0 | 2026-08-02 | Codex | 改为全文抽词并请求 IPA 音标，提高生词覆盖度。 |
| 1.2.0 | 2026-08-04 | Codex | 改用既有离线词汇分级模块；保留 timeline 中人工维护的固定短语，不调用 LLM/API。 |
| 1.3.0 | 2026-08-04 | Codex | 支持以独立 JSON 传入已审核的短语候选，保持离线分级与人工短语供给的可替换边界。 |
| 1.4.0 | 2026-08-27 | Codex | 富化阶段排除缺失 IPA 的候选，避免空音标进入英语世界成片后才在验收阶段失败。 |
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from video_processing.study_cards import StudyCardContent, select_vocabulary  # noqa: E402
from video_processing.vocabulary import DEFAULT_WORDLIST_DIR, extract_article_vocabulary  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="为新闻精读 timeline 提取 3–10 级生词候选")
    parser.add_argument("--timeline", required=True, type=Path, help="原始 timeline JSON")
    parser.add_argument("--output", required=True, type=Path, help="输出 enriched timeline JSON（不可与输入相同）")
    parser.add_argument(
        "--wordlist-dir", type=Path, default=DEFAULT_WORDLIST_DIR,
        help="hermes-wordlists 目录；默认 ~/Downloads/hermes-wordlists",
    )
    parser.add_argument(
        "--phrase-candidates", type=Path,
        help="可选：人工审核的短语候选 JSON 数组；仅合并到本次旁路输出",
    )
    return parser.parse_args()


def build_candidates(
    payload: dict[str, Any], wordlist_dir: Path, phrase_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """离线抽取单词，并合并输入时间线中已经审核过的固定短语。"""
    text = str(payload["english_text"])
    offline = extract_article_vocabulary(
        text, min_level="KET", max_words=None, wordlist_dir=wordlist_dir,
    )
    candidates: dict[str, dict[str, Any]] = {
        result.word.lower(): result.to_dict()
        for result in offline
        if result.context_meaning_zh.strip()
    }
    for item in [*payload.get("vocabulary_candidates", payload.get("vocabulary", [])), *phrase_candidates]:
        if not isinstance(item, dict):
            continue
        word = str(item.get("word", "")).strip()
        meaning = str(item.get("meaning_zh", item.get("context_meaning_zh", ""))).strip()
        if not word or not meaning:
            continue
        key = " ".join(word.lower().split())
        if " " in key or key not in candidates:
            candidates[key] = dict(item)
    # 英语世界右栏要求每张词卡都可跟读；离线词表未给 IPA 的词不能带入成片。
    return [
        candidate for candidate in candidates.values()
        if str(candidate.get("phonetic") or "").strip()
    ]


def load_phrase_candidates(path: Path | None) -> list[dict[str, Any]]:
    """读取独立短语清单；格式错误时拒绝写出时间线，避免隐性丢词。"""
    if path is None:
        return []
    payload = json.loads(path.expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ValueError("--phrase-candidates 必须是对象数组 JSON")
    return payload


def main() -> int:
    args = parse_args()
    if args.timeline.resolve() == args.output.resolve():
        print("enrich_study_card_vocabulary: --output 必须是新文件，避免覆盖原始时间线", file=sys.stderr)
        return 2
    try:
        payload = json.loads(args.timeline.read_text(encoding="utf-8"))
        candidates = build_candidates(
            payload, args.wordlist_dir.expanduser(), load_phrase_candidates(args.phrase_candidates),
        )
        payload["vocabulary_candidates"] = candidates
        content = StudyCardContent.from_mapping(payload)
        selection = select_vocabulary(payload["english_text"], content.vocabulary)
        payload["vocabulary_selection"] = {
            "minimum_level": 3,
            "selection_scope": "无全篇上限；成片由模板按阅读屏控制最少/最多微笔记数",
            "candidate_count": len(candidates),
            "selected_count": len(content.vocabulary),
            "lexical_word_count": selection.lexical_word_count,
            "actual_density": round(selection.density, 4),
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (KeyError, OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"enrich_study_card_vocabulary: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
