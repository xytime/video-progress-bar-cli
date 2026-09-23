"""给编辑学习点绑定本机词典证据，模型不得制造音标与等级。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.5 | 2026-09-24 | Codex | 共享批量词典查询与词元证据，为受限选词排除缺音标、歧义点号及审校拒绝词。 |
| 1.0.4 | 2026-09-23 | Codex | 仅规范化已确认字符；保留歧义点号、拒绝空发音，记录规范化版本。 |
| 1.0.0 | 2026-09-09 | Codex | 表面词优先，缺音标时显式标注经词典证明的词元。 |
| 1.0.2 | 2026-09-17 | Codex | 词典查找规范化来源词两端标点，保留屏显原词与词轴不变，避免安全候选因逗号误判无词条。 |
| 1.0.3 | 2026-09-23 | Antigravity | 词条证据保留 raw_phonetic、normalized_phonetic、normalization_rules，规范化西里尔字符 \u04d9 及前导损坏点号，严密缺音标阻断。 |
| 1.0.1 | 2026-09-11 | Codex | 在第二次独立复审前阻断相邻学习点之间的词典义串线。 |
"""
import csv
import re
from .language_protocol import file_digest


def normalize_phonetic(raw: str) -> tuple[str, list[str]]:
    """规范化离线词典音标，保留原始值与规则溯源。

    将非标准西里尔字符 \\u04d9 (ә) 替换为标准 IPA \\u0259 (ə)，
    保留有歧义的点号供独立审校，不能把清洗当成发音正确证明。
    """
    if not raw:
        return "", []
    normalized = str(raw).strip()
    rules: list[str] = []

    # 1. 将非标准西里尔字符 \u04d9 (ә) 和 \u04d8 (Ә) 规范化替换为标准 IPA \u0259 (ə)
    if "\u04d9" in normalized or "\u04d8" in normalized:
        normalized = normalized.replace("\u04d9", "\u0259").replace("\u04d8", "\u0259")
        rules.append("replace_cyrillic_schwa")

    # 历史点号可能承载重音信息，未经词条级核验不能删除或统一改成次重音。
    if normalized.startswith(".") or normalized.endswith("."):
        rules.append("unresolved_legacy_punctuation")

    return normalized, rules


def _chinese_key(value):
    """仅保留可比对的中文语义字，忽略词性、标点和“的”等语法尾缀。"""
    chars = [char for char in str(value) if "\u4e00" <= char <= "\u9fff"]
    return "".join(chars).rstrip("的地得")


def _dictionary_key(value):
    """把词轴表面词映射为词典键；只移除两端标点，不改写中间拼写。"""
    return re.sub(r"^[^a-z]+|[^a-z]+$", "", str(value).casefold())


def _dictionary_sense_keys(translation):
    """把 ecdict 的逗号分隔释义拆为可比对的单一中文义项。"""
    values = []
    for raw in re.split(r"[,，;；]", str(translation)):
        without_prefix = re.sub(r"^(?:\s*\[[^]]+\]\s*)?(?:[a-z]+(?:\.[a-z]+)*\.\s*)?", "", raw,
                                flags=re.IGNORECASE)
        key = _chinese_key(without_prefix)
        if len(key) >= 2 and key not in values:
            values.append(key)
    return values


def validate_context_meaning_separation(points, words):
    """拒绝并列相邻词把彼此词典义写进同一张学习卡。

    这是一条保守的本地预检：仅当一个释义同时命中其词典中的两个独立义项，
    且其中一个义项又出现在由 and/or/but 连接的相邻学习点中时才拒绝。它不替代
    独立语义审校，却能让这类机械串线在唯一一次复审修订前被纠正。
    """
    for point in points:
        meaning = _chinese_key(point.get("context_meaning_zh", ""))
        senses = _dictionary_sense_keys(point.get("dictionary_senses", {}).get("translation", ""))
        matched = [sense for sense in senses if sense in meaning]
        if len(matched) < 2:
            continue
        index = point.get("word_index")
        if type(index) is not int:
            continue
        for neighbour in points:
            neighbour_index = neighbour.get("word_index")
            if neighbour is point or type(neighbour_index) is not int:
                continue
            lower, upper = sorted((index, neighbour_index))
            connector = [str(item.get("text", "")).lower().strip(".,!?;:")
                         for item in words[lower + 1:upper] if isinstance(item, dict)]
            shared = [sense for sense in matched if sense in _chinese_key(neighbour.get("context_meaning_zh", ""))]
            if shared and set(connector) & {"and", "or", "but"}:
                raise ValueError(
                    f"学习点 {point.get('word', '')} 的语境义混入并列学习点 "
                    f"{neighbour.get('word', '')} 的词典义（{shared[0]}）；请只保留本词的单一语境义"
                )


def _load_rows(directory, targets):
    """一次扫描候选词及必要词元，供证据绑定和修订选词共享。"""
    path = directory / "ecdict.csv"
    rows = {}
    with path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            key = _dictionary_key(row["word"])
            if key in targets:
                rows[key] = row
    missing_lemmas = {part[2:] for row in rows.values() for part in row.get("exchange", "").split("/")
                      if part.startswith("0:")} - rows.keys()
    if missing_lemmas:
        with path.open(encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                key = _dictionary_key(row["word"])
                if key in missing_lemmas:
                    rows[key] = row
    return rows


def _pronunciation(row, rows):
    if row.get("phonetic"):
        return row
    lemma = next((part[2:] for part in row.get("exchange", "").split("/") if part.startswith("0:")), "")
    return rows.get(lemma, {})


def dictionary_word_options(words, directory, *, excluded_words=()):
    """提供有本地发音证据的替换词；排除已被审校拒绝的词和未解析音标。

    这里只证明词典可用，不证明语境读音正确；最终仍须独立复审。
    """
    excluded = {_dictionary_key(word) for word in excluded_words}
    keys = {_dictionary_key(word["text"]) for word in words} - {""}
    rows = _load_rows(directory, keys)
    options = []
    for index, word in enumerate(words):
        key = _dictionary_key(word["text"])
        row = rows.get(key)
        if not row or key in excluded:
            continue
        pronunciation = _pronunciation(row, rows)
        phonetic, rules = normalize_phonetic(pronunciation.get("phonetic", ""))
        if not any(c.isalpha() for c in phonetic) or "unresolved_legacy_punctuation" in rules:
            continue
        options.append({"word_index": index, "word": word["text"], "phonetic": phonetic,
                        "phonetic_word": pronunciation["word"], "dictionary_translation": row.get("translation", "")})
    return options


def attach_evidence(payload, directory):
    from ..vocabulary.leveler import VocabularyLeveler
    leveler = VocabularyLeveler(directory)
    points = payload["learning_points"]
    targets = {_dictionary_key(p["word"]) for p in points}
    if "" in targets:
        raise ValueError("学习点必须包含可查询的英文词，不能编造音标")
    path = directory / "ecdict.csv"
    rows = _load_rows(directory, targets)
    for point in points:
        key = _dictionary_key(point["word"])
        row = rows.get(key)
        if not row:
            raise ValueError(f"本机词典没有学习点 {key}，不能编造音标")
        pronunciation = _pronunciation(row, rows)
        if not pronunciation.get("phonetic"):
            raise ValueError(f"本机词典没有 {key} 或其词元的音标")
        raw_phonetic = pronunciation["phonetic"]
        normalized_phonetic, rules = normalize_phonetic(raw_phonetic)
        if not normalized_phonetic or not any(ch.isalpha() for ch in normalized_phonetic):
            raise ValueError(f"本机词典 {key} 的音标缺少发音字符")
        level = leveler.analyze_word(key)
        point.update(phonetic=normalized_phonetic,
                     raw_phonetic=raw_phonetic,
                     normalized_phonetic=normalized_phonetic,
                     normalization_rules=rules,
                     normalization_version="ecdict-phonetic-v2",
                     phonetic_word=pronunciation["word"],
                     dictionary_source="ecdict.csv", dictionary_senses={"definition": row.get("definition", ""),
                     "translation": row.get("translation", ""), "exchange": row.get("exchange", "")},
                     level=level.recommended_level, level_source=level.source)
    validate_context_meaning_separation(points, payload.get("words", []))
    payload["dictionary_sha256"] = file_digest(path)
    return payload
