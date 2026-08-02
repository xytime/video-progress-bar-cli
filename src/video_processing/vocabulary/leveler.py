# -*- coding: utf-8 -*-
"""基于离线词表的英文单词考试分级。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0 | 2026-08-03 | Codex | 初始创建：合并 hermes-wordlists 的 CEFR 与国内考试标签，支持词形还原与 JSON 输出。 |
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re
from typing import Iterable, Sequence

from .models import FriendlyTag, WordLevelResult


DEFAULT_WORDLIST_DIR = Path.home() / "Downloads" / "hermes-wordlists"

_LABEL_PRIORITY = {
    "KET": 0,
    "中考": 1,
    "PET": 2,
    "高考": 3,
    "CET-4": 4,
    "FCE": 5,
    "CET-6": 6,
    "CAE": 7,
    "Master": 8,
}
_CEFR_TO_EXAM = {
    "A1": "KET",
    "A2": "KET",
    "B1": "PET",
    "B2": "FCE",
    "C1": "CAE",
    "C2": "Master",
}
_POS_MAP = {
    "a.": "adj.",
    "ad.": "adv.",
    "adv.": "adv.",
    "conj.": "conj.",
    "int.": "interj.",
    "n.": "n.",
    "num.": "num.",
    "prep.": "prep.",
    "pron.": "pron.",
    "v.": "v.",
    "vi.": "vi.",
    "vt.": "vt.",
}
_FUNCTION_WORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "been", "being", "but", "by", "for", "from",
    "has", "have", "had", "he", "her", "his", "i", "in", "is", "it", "its", "of", "on",
    "or", "our", "she", "that", "the", "their", "them", "this", "to", "was", "were", "with",
    "you", "your",
})
_EXCHANGE_FORM_CODES = frozenset({"0", "p", "d", "i", "3", "r", "t", "s"})


@dataclass(frozen=True)
class _WordlistEntry:
    word: str
    labels: tuple[str, ...]
    pos: str = ""
    phonetic: str = ""
    translation: str = ""
    definition: str = ""
    source: str = "wordlist"


@dataclass(frozen=True)
class _LookupResult:
    entry: _WordlistEntry
    lemma: str
    direct_match: bool


class VocabularyLeveler:
    """离线词表分级器。

    数据源优先级：
    1. ``exam-wordlists.csv`` 提供中考/高考/CET-4/CET-6；
    2. ``cefr-enhanced.csv`` 提供 KET/PET/FCE/CAE/Master 近似标签；
    3. ``ecdict.csv`` 提供词形还原与超纲词兜底释义。
    """

    def __init__(self, wordlist_dir: Path | str = DEFAULT_WORDLIST_DIR) -> None:
        self.wordlist_dir = Path(wordlist_dir).expanduser()
        self._entries: dict[str, _WordlistEntry] = {}
        self._fallback_entries: dict[str, _WordlistEntry] = {}
        self._lemma_map: dict[str, str] = {}
        self._load()

    def analyze_word(self, word: str, context: str = "") -> WordLevelResult:
        """分析单个英文词；context 目前用于结果保留，释义仍以离线词典为准。"""
        normalised = _normalise_word(word)
        if not normalised:
            raise ValueError("word 必须包含英文字符")

        lookup = self._lookup(normalised)
        if lookup is None:
            entry = _WordlistEntry(word=normalised, labels=("Master",), source="unknown")
            lookup = _LookupResult(entry=entry, lemma=normalised, direct_match=False)

        labels = _sort_labels(lookup.entry.labels or ("Master",))
        recommended = labels[0] if labels else "Master"
        surface_entry = self._fallback_entries.get(normalised) if not lookup.direct_match else None
        meaning_entry = surface_entry if surface_entry and (surface_entry.translation or surface_entry.definition) else lookup.entry
        meaning = _context_meaning(meaning_entry.translation, meaning_entry.definition)
        if not meaning:
            meaning = "词表未提供释义；建议结合上下文人工确认"
        confidence = _confidence(lookup.entry, lookup.direct_match)
        return WordLevelResult(
            word=normalised,
            lemma=lookup.lemma,
            context_meaning_zh=meaning,
            recommended_level=recommended,
            covered_syllabi=labels,
            friendly_tag=_friendly_tag(recommended),
            pos=meaning_entry.pos or lookup.entry.pos,
            phonetic=meaning_entry.phonetic or lookup.entry.phonetic,
            source=lookup.entry.source,
            confidence=confidence,
        )

    def analyze_text(self, text: str, words: Iterable[str] | None = None) -> list[WordLevelResult]:
        """分析文本中的目标词；未指定目标词时按首次出现顺序抽取英文词。"""
        targets = list(words) if words is not None else _extract_words(text)
        results: list[WordLevelResult] = []
        seen: set[str] = set()
        for target in targets:
            key = _normalise_word(target)
            if not key or key in seen:
                continue
            seen.add(key)
            results.append(self.analyze_word(key, context=text))
        return results

    def _lookup(self, word: str) -> _LookupResult | None:
        direct = self._entries.get(word)
        if direct is not None:
            return _LookupResult(entry=direct, lemma=word, direct_match=True)

        lemma = self._lemma_map.get(word) or _heuristic_lemma(word)
        if lemma != word:
            entry = self._entries.get(lemma)
            if entry is not None:
                return _LookupResult(entry=entry, lemma=lemma, direct_match=False)

        fallback = self._fallback_entries.get(word)
        if fallback is not None:
            return _LookupResult(entry=fallback, lemma=word, direct_match=True)
        if lemma != word:
            fallback = self._fallback_entries.get(lemma)
            if fallback is not None:
                return _LookupResult(entry=fallback, lemma=lemma, direct_match=False)
        return None

    def _load(self) -> None:
        if not self.wordlist_dir.exists():
            raise FileNotFoundError(f"词表目录不存在: {self.wordlist_dir}")
        self._load_exam_wordlists(self.wordlist_dir / "exam-wordlists.csv")
        self._load_cefr_wordlists(self.wordlist_dir / "cefr-enhanced.csv")
        self._load_ecdict(self.wordlist_dir / "ecdict.csv")

    def _load_exam_wordlists(self, path: Path) -> None:
        for row in _read_csv(path):
            word = _normalise_word(row.get("word", ""))
            if not word:
                continue
            labels = _split_labels(row.get("exam", ""))
            self._merge_entry(
                _WordlistEntry(
                    word=word,
                    labels=labels,
                    pos=(row.get("pos") or "").strip(),
                    phonetic=(row.get("phonetic") or "").strip(),
                    translation=(row.get("translation") or "").strip(),
                    source="exam-wordlists",
                )
            )

    def _load_cefr_wordlists(self, path: Path) -> None:
        for row in _read_csv(path):
            word = _normalise_word(row.get("word", ""))
            if not word:
                continue
            labels = _cefr_labels(row.get("level", ""), row.get("exam", ""))
            self._merge_entry(
                _WordlistEntry(
                    word=word,
                    labels=labels,
                    pos=(row.get("pos") or "").strip(),
                    phonetic=(row.get("phonetic") or "").strip(),
                    translation=(row.get("translation") or "").strip(),
                    definition=(row.get("definition") or "").strip(),
                    source="cefr-enhanced",
                )
            )

    def _load_ecdict(self, path: Path) -> None:
        for row in _read_csv(path):
            word = _normalise_word(row.get("word", ""))
            if not word:
                continue
            self._fallback_entries.setdefault(
                word,
                _WordlistEntry(
                    word=word,
                    labels=("Master",),
                    pos=(row.get("pos") or "").strip(),
                    phonetic=(row.get("phonetic") or "").strip(),
                    translation=(row.get("translation") or "").strip(),
                    definition=(row.get("definition") or "").strip(),
                    source="ecdict-fallback",
                ),
            )
            self._add_exchange_forms(word, row.get("exchange", ""))

    def _merge_entry(self, entry: _WordlistEntry) -> None:
        current = self._entries.get(entry.word)
        if current is None:
            self._entries[entry.word] = _WordlistEntry(
                word=entry.word,
                labels=_sort_labels(entry.labels),
                pos=entry.pos,
                phonetic=entry.phonetic,
                translation=entry.translation,
                definition=entry.definition,
                source=entry.source,
            )
            return
        labels = _sort_labels((*current.labels, *entry.labels))
        self._entries[entry.word] = _WordlistEntry(
            word=entry.word,
            labels=labels,
            pos=current.pos or entry.pos,
            phonetic=current.phonetic or entry.phonetic,
            translation=current.translation or entry.translation,
            definition=current.definition or entry.definition,
            source=f"{current.source}+{entry.source}" if entry.source not in current.source else current.source,
        )

    def _add_exchange_forms(self, word: str, exchange: str) -> None:
        forms = _parse_exchange(exchange)
        lemma = forms.get("0", word)
        if lemma:
            self._lemma_map.setdefault(word, lemma)
        for form in forms.values():
            normalised = _normalise_word(form)
            if normalised:
                self._lemma_map.setdefault(normalised, lemma)


@lru_cache(maxsize=4)
def _cached_leveler(wordlist_dir: str) -> VocabularyLeveler:
    return VocabularyLeveler(Path(wordlist_dir))


def analyze_word(word: str, context: str = "", wordlist_dir: Path | str = DEFAULT_WORDLIST_DIR) -> WordLevelResult:
    """便捷函数：使用缓存的离线分级器分析单词。"""
    return _cached_leveler(str(Path(wordlist_dir).expanduser())).analyze_word(word, context=context)


def analyze_text(
    text: str,
    words: Iterable[str] | None = None,
    wordlist_dir: Path | str = DEFAULT_WORDLIST_DIR,
) -> list[WordLevelResult]:
    """便捷函数：使用缓存的离线分级器分析文本。"""
    return _cached_leveler(str(Path(wordlist_dir).expanduser())).analyze_text(text, words=words)


def _read_csv(path: Path) -> Iterable[dict[str, str]]:
    if not path.exists():
        return ()
    with path.open(newline="", encoding="utf-8") as handle:
        yield from csv.DictReader(handle)


def _split_labels(value: str) -> tuple[str, ...]:
    labels: list[str] = []
    for raw in re.split(r"[,/]", value or ""):
        label = _normalise_label(raw)
        if label in _LABEL_PRIORITY and label not in labels:
            labels.append(label)
    return tuple(labels)


def _cefr_labels(level: str, exam: str) -> tuple[str, ...]:
    labels = list(_split_labels(exam))
    cefr_label = _CEFR_TO_EXAM.get((level or "").strip().upper())
    if cefr_label and cefr_label not in labels:
        labels.append(cefr_label)
    return tuple(labels)


def _normalise_label(label: str) -> str:
    cleaned = label.strip()
    lowered = cleaned.lower()
    if lowered in {"ket", "pet", "fce", "cae", "master"}:
        return cleaned.upper() if lowered != "master" else "Master"
    if lowered in {"cet4", "cet-4"}:
        return "CET-4"
    if lowered in {"cet6", "cet-6"}:
        return "CET-6"
    return cleaned


def _sort_labels(labels: Sequence[str]) -> tuple[str, ...]:
    unique = {label for label in labels if label in _LABEL_PRIORITY}
    return tuple(sorted(unique, key=lambda item: (_LABEL_PRIORITY[item], item)))


def _friendly_tag(recommended_level: str) -> FriendlyTag:
    if recommended_level in {"KET", "中考"}:
        return FriendlyTag.BASIC
    if recommended_level in {"PET", "高考", "CET-4", "FCE"}:
        return FriendlyTag.PROGRESSIVE
    return FriendlyTag.NEWS_ADVANCED


def _confidence(entry: _WordlistEntry, direct_match: bool) -> float:
    if entry.source == "unknown":
        return 0.2
    if entry.source == "ecdict-fallback":
        return 0.55 if direct_match else 0.5
    return 0.95 if direct_match else 0.88


def _context_meaning(translation: str, definition: str) -> str:
    for line in (translation or "").splitlines():
        cleaned = _clean_translation_line(line)
        if cleaned:
            return cleaned
    if definition:
        return definition.splitlines()[0].strip()
    return ""


def _clean_translation_line(line: str) -> str:
    cleaned = line.strip().replace("\\n", "\n").splitlines()[0].strip()
    if not cleaned or cleaned.startswith("["):
        return ""
    for raw_pos, display_pos in _POS_MAP.items():
        if cleaned.startswith(raw_pos):
            body = cleaned[len(raw_pos):].strip(" ,，;；")
            if body:
                body = re.sub(r"[,，]\s*", "；", body)
                return f"{display_pos} {body}"
    return cleaned


def _parse_exchange(exchange: str) -> dict[str, str]:
    forms: dict[str, str] = {}
    for part in (exchange or "").split("/"):
        if ":" not in part:
            continue
        code, value = part.split(":", 1)
        normalised = _normalise_word(value)
        if code in _EXCHANGE_FORM_CODES and normalised:
            forms[code] = normalised
    return forms


def _heuristic_lemma(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return f"{word[:-3]}y"
    if len(word) > 5 and word.endswith("ing"):
        stem = word[:-3]
        if len(stem) > 2 and stem[-1] == stem[-2]:
            stem = stem[:-1]
        return stem
    if len(word) > 4 and word.endswith("ed"):
        stem = word[:-2]
        if len(stem) > 2 and stem[-1] == stem[-2]:
            stem = stem[:-1]
        return stem
    if len(word) > 3 and word.endswith("es"):
        if word.endswith(("ses", "xes", "zes", "ches", "shes")):
            return word[:-2]
    if len(word) > 3 and word.endswith("s"):
        return word[:-1]
    return word


def _extract_words(text: str) -> list[str]:
    words: list[str] = []
    for match in re.finditer(r"[A-Za-z]+(?:'[A-Za-z]+)?", text):
        word = match.group(0).lower()
        if word not in _FUNCTION_WORDS:
            words.append(word)
    return words


def _normalise_word(word: str) -> str:
    parts = re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", word.lower())
    return " ".join(parts)
