"""给编辑学习点绑定本机词典证据，模型不得制造音标与等级。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-09 | Codex | 表面词优先，缺音标时显式标注经词典证明的词元。 |
| 1.0.1 | 2026-09-11 | Codex | 在第二次独立复审前阻断相邻学习点之间的词典义串线。 |
"""
import csv
import re
from .language_qa import file_digest


def _chinese_key(value):
    """仅保留可比对的中文语义字，忽略词性、标点和“的”等语法尾缀。"""
    chars = [char for char in str(value) if "\u4e00" <= char <= "\u9fff"]
    return "".join(chars).rstrip("的地得")


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


def attach_evidence(payload, directory):
    from ..vocabulary.leveler import VocabularyLeveler
    leveler = VocabularyLeveler(directory)
    points = payload["learning_points"]
    targets = {p["word"].lower() for p in points}
    path = directory / "ecdict.csv"
    rows = {}
    with path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            if row["word"].lower() in targets:
                rows[row["word"].lower()] = row
    missing_lemmas = {part[2:] for row in rows.values() for part in row.get("exchange", "").split("/")
                      if part.startswith("0:")} - rows.keys()
    if missing_lemmas:
        with path.open(encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                if row["word"] in missing_lemmas:
                    rows[row["word"]] = row
    for point in points:
        key = point["word"].lower()
        row = rows.get(key)
        if not row:
            raise ValueError(f"本机词典没有学习点 {key}，不能编造音标")
        pronunciation = row
        if not row.get("phonetic"):
            lemma = next((part[2:] for part in row.get("exchange", "").split("/") if part.startswith("0:")), "")
            pronunciation = rows.get(lemma, {})
        if not pronunciation.get("phonetic"):
            raise ValueError(f"本机词典没有 {key} 或其词元的音标")
        level = leveler.analyze_word(key)
        point.update(phonetic=pronunciation["phonetic"], phonetic_word=pronunciation["word"],
                     dictionary_source="ecdict.csv", dictionary_senses={"definition": row.get("definition", ""),
                     "translation": row.get("translation", ""), "exchange": row.get("exchange", "")},
                     level=level.recommended_level, level_source=level.source)
    validate_context_meaning_separation(points, payload.get("words", []))
    payload["dictionary_sha256"] = file_digest(path)
    return payload
