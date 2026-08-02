# -*- coding: utf-8 -*-
"""词汇考试分级 CLI。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0 | 2026-08-03 | Codex | 初始创建：暴露离线词表分级 JSON 命令，供脚本和人工验证使用。 |
"""

from __future__ import annotations

import json
from pathlib import Path

import click

from video_processing.vocabulary import DEFAULT_WORDLIST_DIR, VocabularyLeveler


@click.command(name="vocab-level")
@click.argument("words", nargs=-1)
@click.option("--text", "-t", default="", help="包含目标词的英文上下文。")
@click.option(
    "--wordlist-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=DEFAULT_WORDLIST_DIR,
    show_default=True,
    help="hermes-wordlists 词表目录。",
)
@click.option("--indent", type=int, default=2, show_default=True, help="JSON 缩进空格数；0 为单行输出。")
def vocab_level(words: tuple[str, ...], text: str, wordlist_dir: Path, indent: int) -> None:
    """分析英文单词的最低考试级别与覆盖大纲。"""
    if not words and not text.strip():
        raise click.UsageError("请提供至少一个单词，或使用 --text 提供英文文本")

    leveler = VocabularyLeveler(wordlist_dir)
    results = leveler.analyze_text(text, words=words or None) if text else [
        leveler.analyze_word(word) for word in words
    ]
    payload = [result.to_dict() for result in results]
    click.echo(json.dumps(payload, ensure_ascii=False, indent=indent if indent > 0 else None))
