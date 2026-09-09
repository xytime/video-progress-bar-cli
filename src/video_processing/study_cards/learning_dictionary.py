"""给编辑学习点绑定本机词典证据，模型不得制造音标与等级。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-09 | Codex | 表面词优先，缺音标时显式标注经词典证明的词元。 |
"""
import csv
from .language_qa import file_digest


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
    payload["dictionary_sha256"] = file_digest(path)
    return payload
