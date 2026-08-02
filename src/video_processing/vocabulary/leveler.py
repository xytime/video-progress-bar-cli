# -*- coding: utf-8 -*-
"""基于离线词表的英文单词考试分级。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0 | 2026-08-03 | Codex | 初始创建：合并 hermes-wordlists 的 CEFR 与国内考试标签，支持词形还原与 JSON 输出。 |
| 1.1.0 | 2026-08-03 | Codex | 修复词表缺失静默降级，增加离线语境释义选择与文章生词表提取接口。 |
| 1.2.0 | 2026-08-03 | Codex | 增加 ECDICT lazy/eager/off 加载模式，按目标词批量扫描降低启动内存。 |
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re
from typing import Iterable, Literal, Sequence

from .models import FriendlyTag, WordLevelResult


DEFAULT_WORDLIST_DIR = Path.home() / "Downloads" / "hermes-wordlists"
MAIN_WORDLIST_FILES = ("exam-wordlists.csv", "cefr-enhanced.csv")
ECDICT_WORDLIST_FILE = "ecdict.csv"
ECDICT_MODES = ("lazy", "eager", "off")
EcdictMode = Literal["lazy", "eager", "off"]

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
    "can", "could", "did", "do", "does", "had", "has", "have", "he", "her", "hers", "him",
    "his", "i", "if", "in", "into", "is", "it", "its", "me", "my", "nor", "not", "of", "on",
    "or", "our", "ours", "she", "should", "so", "than", "that", "the", "their", "theirs",
    "them", "then", "there", "these", "they", "this", "those", "to", "us", "was", "we",
    "were", "will", "with", "would", "you", "your", "yours",
})
_EXCHANGE_FORM_CODES = frozenset({"0", "p", "d", "i", "3", "r", "t", "s"})
_VERB_CONTEXT_PREVIOUS = frozenset({
    "am", "are", "be", "been", "being", "can", "could", "did", "do", "does", "had", "has",
    "have", "is", "may", "might", "must", "should", "to", "was", "were", "will", "would",
})
_NOUN_CONTEXT_PREVIOUS = frozenset({
    "a", "an", "another", "each", "every", "his", "its", "many", "my", "our", "several",
    "that", "the", "their", "these", "this", "those", "your",
})


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

    def __init__(
        self,
        wordlist_dir: Path | str = DEFAULT_WORDLIST_DIR,
        *,
        ecdict_mode: EcdictMode = "lazy",
    ) -> None:
        self.wordlist_dir = Path(wordlist_dir).expanduser()
        self.ecdict_mode = _normalise_ecdict_mode(ecdict_mode)
        self._ecdict_path = self.wordlist_dir / ECDICT_WORDLIST_FILE
        self._entries: dict[str, _WordlistEntry] = {}
        self._fallback_entries: dict[str, _WordlistEntry] = {}
        self._lemma_map: dict[str, str] = {}
        self._ecdict_scanned_targets: set[str] = set()
        self._load()

    def analyze_word(self, word: str, context: str = "") -> WordLevelResult:
        """分析单个英文词；context 仅用于离线词性启发式释义选择，不调用外部 API。"""
        normalised = _normalise_word(word)
        if not normalised:
            raise ValueError("word 必须包含英文字符")

        lookup = self._lookup(normalised)
        if lookup is None:
            entry = _WordlistEntry(word=normalised, labels=("Master",), source="unknown")
            lookup = _LookupResult(entry=entry, lemma=normalised, direct_match=False)

        labels = _sort_labels(lookup.entry.labels or ("Master",))
        recommended = labels[0] if labels else "Master"
        meaning_entries = [lookup.entry]
        surface_entry = self._fallback_entries.get(normalised) if not lookup.direct_match else None
        if surface_entry and (surface_entry.translation or surface_entry.definition):
            meaning_entries.append(surface_entry)
        meaning_entry, meaning, meaning_pos = _context_meaning(meaning_entries, normalised, lookup.lemma, context)
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
            pos=meaning_pos or meaning_entry.pos or lookup.entry.pos,
            phonetic=meaning_entry.phonetic or lookup.entry.phonetic,
            source=lookup.entry.source,
            confidence=confidence,
        )

    def analyze_text(self, text: str, words: Iterable[str] | None = None) -> list[WordLevelResult]:
        """分析文本中的目标词；未指定目标词时按首次出现顺序抽取英文词。"""
        targets = list(words) if words is not None else _extract_words(text)
        self.prepare_words(targets)
        results: list[WordLevelResult] = []
        seen: set[str] = set()
        for target in targets:
            key = _normalise_word(target)
            if not key or key in seen:
                continue
            seen.add(key)
            results.append(self.analyze_word(key, context=text))
        return results

    def prepare_words(self, words: Iterable[str]) -> None:
        """按目标词预热懒加载词形/兜底词典，避免正文批量分析时重复扫描。"""
        if self.ecdict_mode != "lazy":
            return
        targets = {_normalise_word(word) for word in words}
        targets = {word for word in targets if word and not self._has_lookup_without_ecdict(word)}
        self._load_ecdict_targets(targets)

    def extract_article_vocabulary(
        self,
        text: str,
        *,
        min_level: str = "PET",
        max_words: int | None = 20,
        include_proper_nouns: bool = False,
    ) -> list[WordLevelResult]:
        """从整篇英文正文中一次性抽取去重后的重点生词表。

        默认从 PET 起筛选并排除疑似专名，等价于抽取学习者更需要注意的正文词汇；
        结果按正文首次出现顺序返回。
        """
        min_label = _normalise_label(min_level)
        if min_label not in _LABEL_PRIORITY:
            raise ValueError(f"未知最低级别: {min_level}")
        if max_words is not None and max_words < 1:
            raise ValueError("max_words 必须为正整数，或传入 None 表示不限制")

        min_priority = _LABEL_PRIORITY[min_label]
        capitalised_words = _capitalised_words(text)
        lowercase_words = _lowercase_words(text)
        results: list[WordLevelResult] = []
        seen_lemmas: set[str] = set()
        for result in self.analyze_text(text):
            if result.lemma in seen_lemmas:
                continue
            seen_lemmas.add(result.lemma)
            if (
                not include_proper_nouns
                and result.word in capitalised_words
                and result.word not in lowercase_words
                and result.source in {"unknown", "ecdict-fallback"}
            ):
                continue
            if _LABEL_PRIORITY.get(result.recommended_level, _LABEL_PRIORITY["Master"]) < min_priority:
                continue
            results.append(result)
            if max_words is not None and len(results) >= max_words:
                break
        return results

    def _lookup(self, word: str) -> _LookupResult | None:
        result = self._lookup_loaded(word)
        if result is not None or self.ecdict_mode != "lazy":
            return result

        self._load_ecdict_targets((word,))
        return self._lookup_loaded(word)

    def _lookup_loaded(self, word: str) -> _LookupResult | None:
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

    def _has_lookup_without_ecdict(self, word: str) -> bool:
        if word in self._entries or word in self._fallback_entries:
            return True
        lemma = self._lemma_map.get(word) or _heuristic_lemma(word)
        return lemma != word and (lemma in self._entries or lemma in self._fallback_entries)

    def _load(self) -> None:
        if not self.wordlist_dir.exists():
            raise FileNotFoundError(f"词表目录不存在: {self.wordlist_dir}")
        required_files = list(MAIN_WORDLIST_FILES)
        if self.ecdict_mode != "off":
            required_files.append(ECDICT_WORDLIST_FILE)
        missing = [name for name in required_files if not (self.wordlist_dir / name).is_file()]
        if missing:
            raise FileNotFoundError(f"词表文件缺失: {', '.join(missing)} in {self.wordlist_dir}")
        self._load_exam_wordlists(self.wordlist_dir / "exam-wordlists.csv")
        self._load_cefr_wordlists(self.wordlist_dir / "cefr-enhanced.csv")
        if self.ecdict_mode == "eager":
            self._load_ecdict(self._ecdict_path)
        if not self._entries:
            raise ValueError(f"主词表为空或格式不正确: {self.wordlist_dir}")

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
            self._set_fallback_entry(word, row)
            self._add_exchange_forms(word, row.get("exchange", ""))

    def _load_ecdict_targets(self, targets: Iterable[str]) -> None:
        pending = {_normalise_word(target) for target in targets}
        pending = {target for target in pending if target and target not in self._ecdict_scanned_targets}
        if not pending or self.ecdict_mode != "lazy":
            return

        scan_terms = set(pending)
        scan_terms.update(_heuristic_lemma(target) for target in pending)
        scan_terms = {term for term in scan_terms if term}
        found_targets: set[str] = set()
        for row in _read_csv(self._ecdict_path):
            word = _normalise_word(row.get("word", ""))
            if not word:
                continue
            exchange = row.get("exchange", "")
            forms = _parse_exchange(exchange)
            related_forms = {word, *forms.values()}
            matched_targets = pending & related_forms
            if word not in scan_terms and not matched_targets:
                continue

            self._set_fallback_entry(word, row)
            self._add_exchange_forms(word, exchange, forms=forms)
            found_targets.update(matched_targets)
            if word in pending:
                found_targets.add(word)
            if pending <= found_targets:
                break

        self._ecdict_scanned_targets.update(pending)

    def _set_fallback_entry(self, word: str, row: dict[str, str]) -> None:
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

    def _add_exchange_forms(self, word: str, exchange: str, forms: dict[str, str] | None = None) -> None:
        forms = forms if forms is not None else _parse_exchange(exchange)
        lemma = forms.get("0", word)
        if lemma:
            self._lemma_map.setdefault(word, lemma)
        for form in forms.values():
            normalised = _normalise_word(form)
            if normalised:
                self._lemma_map.setdefault(normalised, lemma)


@lru_cache(maxsize=4)
def _cached_leveler(wordlist_dir: str, ecdict_mode: EcdictMode) -> VocabularyLeveler:
    return VocabularyLeveler(Path(wordlist_dir), ecdict_mode=ecdict_mode)


def analyze_word(
    word: str,
    context: str = "",
    wordlist_dir: Path | str = DEFAULT_WORDLIST_DIR,
    *,
    ecdict_mode: EcdictMode = "lazy",
) -> WordLevelResult:
    """便捷函数：使用缓存的离线分级器分析单词。"""
    return _cached_leveler(str(Path(wordlist_dir).expanduser()), ecdict_mode).analyze_word(word, context=context)


def analyze_text(
    text: str,
    words: Iterable[str] | None = None,
    wordlist_dir: Path | str = DEFAULT_WORDLIST_DIR,
    *,
    ecdict_mode: EcdictMode = "lazy",
) -> list[WordLevelResult]:
    """便捷函数：使用缓存的离线分级器分析文本。"""
    return _cached_leveler(str(Path(wordlist_dir).expanduser()), ecdict_mode).analyze_text(text, words=words)


def extract_article_vocabulary(
    text: str,
    *,
    min_level: str = "PET",
    max_words: int | None = 20,
    include_proper_nouns: bool = False,
    ecdict_mode: EcdictMode = "lazy",
    wordlist_dir: Path | str = DEFAULT_WORDLIST_DIR,
) -> list[WordLevelResult]:
    """便捷函数：从整篇英文正文中抽取重点生词表。"""
    return _cached_leveler(str(Path(wordlist_dir).expanduser()), ecdict_mode).extract_article_vocabulary(
        text,
        min_level=min_level,
        max_words=max_words,
        include_proper_nouns=include_proper_nouns,
    )


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


def _normalise_ecdict_mode(mode: str) -> EcdictMode:
    normalised = (mode or "").strip().lower()
    if normalised not in ECDICT_MODES:
        raise ValueError(f"未知 ECDICT 加载模式: {mode}")
    return normalised  # type: ignore[return-value]


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


def _context_meaning(
    entries: Sequence[_WordlistEntry],
    target_word: str,
    lemma: str,
    context: str,
) -> tuple[_WordlistEntry, str, str]:
    preferred_pos = _infer_context_pos(target_word, lemma, context)
    candidates: list[tuple[_WordlistEntry, str, str, str]] = []
    for entry in entries:
        for line in _translation_lines(entry.translation):
            cleaned = _clean_translation_line(line)
            if cleaned:
                display_pos = _display_pos(_line_pos(line) or entry.pos)
                candidates.append((entry, _pos_group(display_pos), display_pos, cleaned))
        if entry.definition:
            definition = entry.definition.splitlines()[0].strip()
            if definition:
                display_pos = _display_pos(entry.pos)
                candidates.append((entry, _pos_group(display_pos), display_pos, definition))

    if preferred_pos:
        for entry, pos, display_pos, meaning in candidates:
            if pos == preferred_pos:
                return entry, meaning, display_pos
    if candidates:
        entry, _, display_pos, meaning = candidates[0]
        return entry, meaning, display_pos
    return entries[0], "", ""


def _translation_lines(translation: str) -> list[str]:
    normalised = (translation or "").replace("\\n", "\n")
    lines = []
    for line in normalised.splitlines():
        stripped = line.strip()
        if stripped:
            lines.append(stripped)
    return lines


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


def _line_pos(line: str) -> str:
    cleaned = line.strip()
    for raw_pos in _POS_MAP:
        if cleaned.startswith(raw_pos):
            return raw_pos
    return ""


def _pos_group(pos: str) -> str:
    normalised = _display_pos(pos)
    if normalised in {"vi.", "vt."}:
        return "v."
    if normalised == "adj.":
        return "adj."
    if normalised == "adv.":
        return "adv."
    if normalised.startswith("n."):
        return "n."
    if normalised.startswith("v."):
        return "v."
    return normalised


def _display_pos(pos: str) -> str:
    return _POS_MAP.get((pos or "").strip(), (pos or "").strip())


def _infer_context_pos(target_word: str, lemma: str, context: str) -> str:
    if target_word.endswith("ly"):
        return "adv."
    if not context:
        if target_word.endswith(("ing", "ed")) and lemma != target_word:
            return "v."
        return ""

    words = _extract_all_words(context)
    for index, word in enumerate(words):
        if word not in {target_word, lemma}:
            continue
        previous = words[index - 1] if index > 0 else ""
        next_word = words[index + 1] if index + 1 < len(words) else ""
        if previous in _VERB_CONTEXT_PREVIOUS:
            return "v."
        if target_word.endswith("ing") and next_word and next_word not in _FUNCTION_WORDS:
            return "v."
        if previous in _NOUN_CONTEXT_PREVIOUS:
            return "n."
    if target_word.endswith(("ing", "ed")) and lemma != target_word:
        return "v."
    return ""


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
    for word in _extract_all_words(text):
        if word not in _FUNCTION_WORDS:
            words.append(word)
    return words


def _extract_all_words(text: str) -> list[str]:
    words: list[str] = []
    for match in re.finditer(r"[A-Za-z]+(?:'[A-Za-z]+)?", text):
        word = match.group(0).lower()
        if word.endswith("'s"):
            word = word[:-2]
        if word:
            words.append(word)
    return words


def _capitalised_words(text: str) -> set[str]:
    return {
        _normalise_word(match.group(0))
        for match in re.finditer(r"\b[A-Z][A-Za-z]+(?:'[A-Za-z]+)?\b", text)
    }


def _lowercase_words(text: str) -> set[str]:
    return {
        _normalise_word(match.group(0))
        for match in re.finditer(r"\b[a-z][A-Za-z]+(?:'[A-Za-z]+)?\b", text)
    }


def _normalise_word(word: str) -> str:
    parts = re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", word.lower())
    return " ".join(parts)
