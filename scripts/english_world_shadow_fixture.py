#!/usr/bin/env python3
"""复制已知 2026-09-09 回归来源到隔离目录，绝不更改历史产物。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-09 | Codex | 冻结真实错误样本与独立审校初稿。 |
"""
import argparse
from pathlib import Path
import shutil
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from video_processing.study_cards.language_qa import VERSION, atomic_json, read_json, file_digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("影子目录已存在，不覆盖或重置审校次数")
    (args.output / "source").mkdir(parents=True)
    originals = {}
    for name in ("source/source.mp4", "source/source.en-orig.json3", "timeline_raw.json", "timeline_enriched.json"):
        destination = args.output / (name if name.startswith("source/") else "original_" + name)
        shutil.copy2(args.source / name, destination)
        originals[name] = file_digest(destination)
    payload = read_json(args.source / "timeline_enriched.json")
    payload["language_contract"] = VERSION
    # 继承原始逐词时轴，不将新词典检索结果当作上下文释义。
    choices = [(22, "adj.", "重要的"), (35, "adj.", "令人警醒的"),
               (38, "adj.", "平均的"), (44, "v.", "骤降"), (52, "adv.", "基本上"), (72, "n.", "表现"),
               (84, "n.", "差距"), (108, "v.", "排名"), (110, "adv.", "总体上"),
               (148, "adj.", "困难的"), (159, "adv.", "落后"), (167, "adj.", "投入的")]
    payload["learning_points"] = [dict(word_index=i, word=payload["words"][i]["text"], pos=pos,
                                      context_meaning_zh=meaning) for i, pos, meaning in choices]
    payload["publication_text"] = {
        "title": "英语世界｜阅读成绩与学习投入",
        "copy": "跟随 ABC News 原声学习阅读成绩与学习投入的表达。A2–B1 家庭英语精读。新闻观点与数据归属于原报道。",
        "cover_payload": {"content_type": "ENGLISH_WORLD_SHORT", "title": "阅读成绩与学习投入",
            "quote_en": "The results for reading are sobering.", "quote_zh": "阅读方面的结果令人警醒。",
            "difficulty_tag": "A2–B1 家庭精读", "audio_source": "ABC News 原声", "date_str": "2026.09.09",
            "highlight_words": [], "vocab_items": []}}
    atomic_json(args.output / "timeline.json", payload)
    atomic_json(args.output / "editorial_changes.json", {"version": VERSION, "revision": 0,
        "changes": [{"kind": "parser_repair", "before": "15 / 13 / 27", "after": "15-year-olds / 13th / 27th",
            "source_ref": "source/source.en-orig.json3", "evidence": "原 JSON3 含完整 15year-olds、13th、27th；旧临时解析器截断后缀。15-year-olds 仅作连字符规范化。"}],
        "original_files": originals, "human_review": "PENDING"})


if __name__ == "__main__":
    main()
