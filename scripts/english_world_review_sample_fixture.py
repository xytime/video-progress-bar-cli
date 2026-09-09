#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建一条可审计、不可投稿的英语世界本地审看样片。

此脚本只复制已选定的真实来源到一个全新的隔离目录，并将人工撰写的
正文、译文、学习点和封面文案按 source -> alignment -> lexicon 的顺序冻结。
它不调用外部模型、不修改来源包，也不触达任何发布账本。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-09 | Codex | 为用户审看建立独立、可复现的 ABC News 语言质检样片。 |
"""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from video_processing.study_cards.language_qa import VERSION, atomic_json, file_digest, read_json
from video_processing.study_cards.text_normalization import normalise_words


SOURCE_START = 7.919
SOURCE_END = 47.84
ENGLISH_TEXT = (
    "Good morning to you Michael So this is the first time in three years that we are seeing "
    "how students perform on critical global tests measuring reading math and science "
    "The results for reading are sobering Since 2022 average reading scores for American "
    "15-year-olds plunged 14 points Math and science scores were mostly flat during that time "
    "Now these tests which are given by the education department in the US compare the performance "
    "of high schoolers in nearly 90 countries In the US the gap in reading scores between the highest "
    "and lowest achieving students is bigger than in any other education system in the report "
    "The US ranks 13th overall in reading and science and 27th in math scores"
)
PARAGRAPHS = [
    {
        "english_text": (
            "Good morning to you Michael So this is the first time in three years that we are seeing "
            "how students perform on critical global tests measuring reading math and science"
        ),
        "translation_zh": "早上好，迈克尔。这是三年来我们首次看到学生在衡量阅读、数学和科学的关键全球测试中的表现。",
    },
    {
        "english_text": (
            "The results for reading are sobering Since 2022 average reading scores for American "
            "15-year-olds plunged 14 points Math and science scores were mostly flat during that time"
        ),
        "translation_zh": "阅读方面的结果令人警醒。自2022年以来，美国15岁青少年的平均阅读成绩骤降了14分。在这段时间里，数学和科学成绩大多持平。",
    },
    {
        "english_text": (
            "Now these tests which are given by the education department in the US compare the performance "
            "of high schoolers in nearly 90 countries"
        ),
        "translation_zh": "这些由美国教育部组织的测试，会比较近90个国家高中生的表现。",
    },
    {
        "english_text": (
            "In the US the gap in reading scores between the highest and lowest achieving students is bigger "
            "than in any other education system in the report The US ranks 13th overall in reading and science "
            "and 27th in math scores"
        ),
        "translation_zh": "在美国，阅读成绩最高与最低学生之间的差距，比报告中的任何其他教育体系都更大。美国在阅读和科学方面总体排名第13，在数学方面排名第27。",
    },
]
LEARNING_POINTS = [
    ("critical", "adj.", "关键的"),
    ("sobering", "adj.", "令人警醒的"),
    ("average", "adj.", "平均的"),
    ("plunged", "v.", "骤降"),
    ("mostly", "adv.", "大多"),
    ("performance", "n.", "表现"),
    ("gap", "n.", "差距"),
    ("ranks", "v.", "排名"),
    ("overall", "adv.", "总体上"),
]


def _timeline() -> dict:
    return {
        "language_contract": VERSION,
        "content_type": "ENGLISH_WORLD_SHORT",
        "headline_zh": "美国阅读成绩下滑",
        "headline_en": "US Reading Scores Fall",
        "english_text": ENGLISH_TEXT,
        "translation_zh": "".join(item["translation_zh"] for item in PARAGRAPHS),
        "paragraphs": PARAGRAPHS,
        "words": [],
        "learning_points": [],
        "vocabulary_candidates": [],
        "source_provenance": {
            "publisher": "ABC News",
            "channel_id": "UCBi2mrWuNuyYy4gbM6fU18Q",
            "youtube_id": "xsfUZ55Yv-M",
            "source_url": "https://www.youtube.com/watch?v=xsfUZ55Yv-M",
            "source_title": "Global report shows where US kids rank in reading, math and science",
            "upload_date": "20260908",
            "source_start_seconds": SOURCE_START,
            "source_end_seconds": SOURCE_END,
            "source_duration_seconds": 76.161451,
            "source_video": "source/source.mp4",
            "caption_artifact": "source/source.en-orig.json3",
            "caption_format": "youtube_json3",
            "caption_transcription_note": (
                "YouTube en-orig 自动字幕；完整片段须以本地 16kHz 单声道 Whisper 对齐。"
                "15year-olds 仅作连字符规范化为 15-year-olds，不自动改写其他内容。"
            ),
        },
    }


def _index_once(words: list[dict], word: str) -> int:
    matches = [index for index, value in enumerate(words) if value["text"].lower() == word.lower()]
    if len(matches) != 1:
        raise ValueError(f"对齐时间线中 {word!r} 出现 {len(matches)} 次，无法安全绑定学习点")
    return matches[0]


def initialize(source: Path, output: Path) -> None:
    if output.exists():
        raise ValueError("样片目录已存在；禁止覆盖或重置审校证据")
    required = ("source/source.mp4", "source/source.en-orig.json3")
    missing = [name for name in required if not (source / name).is_file()]
    if missing:
        raise FileNotFoundError(f"来源包缺少: {', '.join(missing)}")
    (output / "source").mkdir(parents=True)
    original_files = {}
    for name in required:
        destination = output / name
        shutil.copy2(source / name, destination)
        original_files[name] = file_digest(destination)
    atomic_json(output / "timeline.json", _timeline())
    atomic_json(output / "editorial_changes.json", {
        "version": VERSION,
        "revision": 0,
        "changes": [{
            "kind": "typography",
            "before": "15year-olds",
            "after": "15-year-olds",
            "source_ref": "source/source.en-orig.json3 events[16].segs[1]",
            "evidence": "原 JSON3 自动字幕缺少连字符；仅规范为同一年龄词组的标准排印，须由本地 ASR 和独立审校复核。",
        }],
        "original_files": original_files,
        "human_review": "PENDING_USER_REVIEW",
        "scope": "LOCAL_REVIEW_SAMPLE_ONLY",
    })


def apply_alignment(output: Path) -> None:
    timeline_path = output / "timeline.json"
    evidence = read_json(output / "qa/source_evidence.json")
    if evidence.get("alignment_status") != "PASS":
        raise ValueError("来源字幕与 ASR 尚未可靠对齐，禁止冻结逐词时间线")
    words = evidence.get("aligned_words")
    if not isinstance(words, list) or not words:
        raise ValueError("来源证据没有已对齐逐词时间线")
    aligned_text = " ".join(item["text"] for item in words)
    if normalise_words(aligned_text) != normalise_words(ENGLISH_TEXT):
        raise ValueError("本地 ASR 对齐正文与人工冻结正文不一致；需人工裁决，禁止自动覆盖")
    payload = read_json(timeline_path)
    payload["words"] = words
    payload["learning_points"] = [
        {"word_index": _index_once(words, word), "word": word, "pos": pos,
         "context_meaning_zh": meaning}
        for word, pos, meaning in LEARNING_POINTS
    ]
    atomic_json(timeline_path, payload)


def freeze_publication(output: Path) -> None:
    """冻结实际封面文案；此样片只用于用户审看，绝不生成投稿包。"""
    timeline_path = output / "timeline.json"
    payload = read_json(timeline_path)
    by_word = {point["word"].lower(): point for point in payload.get("learning_points", [])}
    selected = []
    for word in ("sobering", "plunged"):
        point = by_word.get(word)
        if not point:
            raise ValueError(f"词典证据后缺少封面词 {word}")
        selected.append({
            "word": point["word"],
            "meaning": point["context_meaning_zh"],
            "ipa": point["phonetic"],
            "phonetic_word": point["phonetic_word"],
            "level": point["level"],
        })
    payload["publication_text"] = {
        "title": "英语世界｜美国阅读成绩下滑",
        "copy": "跟随 ABC News 原声，学习描述成绩变化、差距与排名的英语表达。面向 A2–B1 家庭学习者；数据与观点归原报道。本包仅供本地审看，未投稿。",
        "cover_payload": {
            "content_type": "ENGLISH_WORLD_SHORT",
            "title": "美国阅读成绩下滑",
            "subtitle": "● 英语新闻 · 原声双语精读",
            "quote_en": "The results for reading are sobering.",
            "quote_zh": "阅读方面的结果令人警醒。",
            "highlight_words": ["sobering"],
            "vocab_items": selected,
            "difficulty_tag": "A2–B1 家庭精读",
            "vocab_stat": "本篇 9 个重点学习点",
            "audio_source": "ABC News 原声",
            "date_str": "2026.09.09 本地审看样片",
            "audio_edition": "original_audio_subtitled",
        },
    }
    atomic_json(timeline_path, payload)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("init", "apply-alignment", "freeze-publication"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", type=Path, help="仅 init 阶段需要：原始来源包")
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    if args.stage == "init":
        if not args.source:
            raise ValueError("init 阶段需要 --source")
        initialize(args.source.expanduser().resolve(), output)
    elif args.stage == "apply-alignment":
        apply_alignment(output)
    else:
        freeze_publication(output)


if __name__ == "__main__":
    main()
