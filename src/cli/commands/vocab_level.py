# -*- coding: utf-8 -*-
"""词汇考试分级 CLI。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0 | 2026-08-03 | Codex | 初始创建：暴露离线词表分级 JSON 命令，供脚本和人工验证使用。 |
| 1.1.0 | 2026-08-03 | Codex | 增加整篇正文生词表模式与筛选参数。 |
| 1.2.0 | 2026-08-03 | Codex | 增加 ECDICT 加载模式参数，兼顾低内存与长进程高吞吐。 |
"""

from __future__ import annotations

import json
from pathlib import Path

import click

from video_processing.vocabulary import DEFAULT_WORDLIST_DIR, ECDICT_MODES, VocabularyLeveler


@click.command(name="vocab-level")
@click.argument("words", nargs=-1)
@click.option("--text", "-t", default="", help="包含目标词的英文上下文。")
@click.option("--article", is_flag=True, help="将 --text 作为整篇正文，抽取去重后的重点生词表。")
@click.option("--include-names", is_flag=True, help="--article 模式保留疑似专名或品牌名。")
@click.option(
    "--min-level",
    type=click.Choice(["KET", "中考", "PET", "高考", "CET-4", "FCE", "CET-6", "CAE", "Master"]),
    default="PET",
    show_default=True,
    help="--article 模式下纳入的最低考试级别。",
)
@click.option(
    "--limit",
    type=int,
    default=20,
    show_default=True,
    help="--article 模式最多返回词数；0 表示不限制。",
)
@click.option(
    "--wordlist-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=DEFAULT_WORDLIST_DIR,
    show_default=True,
    help="hermes-wordlists 词表目录。",
)
@click.option(
    "--ecdict-mode",
    type=click.Choice(ECDICT_MODES),
    default="lazy",
    show_default=True,
    help="ECDICT 兜底词典加载策略：lazy 低内存，eager 适合长进程，off 最省资源。",
)
@click.option("--indent", type=int, default=2, show_default=True, help="JSON 缩进空格数；0 为单行输出。")
def vocab_level(
    words: tuple[str, ...],
    text: str,
    article: bool,
    include_names: bool,
    min_level: str,
    limit: int,
    wordlist_dir: Path,
    ecdict_mode: str,
    indent: int,
) -> None:
    """分析英文单词的最低考试级别与覆盖大纲。"""
    if not words and not text.strip():
        raise click.UsageError("请提供至少一个单词，或使用 --text 提供英文文本")
    if article and words:
        raise click.UsageError("--article 模式请只传 --text，不要同时传入单词参数")
    if limit < 0:
        raise click.UsageError("--limit 不能为负数")

    leveler = VocabularyLeveler(wordlist_dir, ecdict_mode=ecdict_mode)
    if article:
        results = leveler.extract_article_vocabulary(
            text,
            min_level=min_level,
            max_words=None if limit == 0 else limit,
            include_proper_nouns=include_names,
        )
    elif text:
        results = leveler.analyze_text(text, words=words or None)
    else:
        results = [leveler.analyze_word(word) for word in words]
    payload = [result.to_dict() for result in results]
    click.echo(json.dumps(payload, ensure_ascii=False, indent=indent if indent > 0 else None))
