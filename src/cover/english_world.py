"""英语世界短视频封面载荷构建。

将 enriched timeline 中已有的文字、词库和来源信息收敛为可审计的封面输入；
不调用模型，也不生成或猜测学习数据。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-24 | Codex | 新增确定性时间线提取、词汇排序与封面载荷校验。 |
| 1.0.1 | 2026-09-09 | Codex | 封面音标携带并呈现词形或显式词元标签。 |
| 1.0.3 | 2026-09-17 | Antigravity | 修复首句无词导致封面词汇统计误判 0 词及词汇项留空缺陷，优先引用全文实际学习点。 |
| 1.0.5 | 2026-09-23 | Antigravity | 加固英文缩写点后接大写专名时首句防截断，强化中英文引语对称性与闭合校验。 |
| 1.0.4 | 2026-09-23 | Antigravity | 加固英文常见缩写点识别防止封面截断，增加中英文引语语义闭合与专名完整性校验。 |
| 1.0.2 | 2026-09-09 | Codex | 优先消费已冻结且经语言审校绑定的封面载荷，杜绝从旧候选池二次选词。 |
"""

from __future__ import annotations

from datetime import date
import re
from typing import Any, Mapping


_LEVEL_ORDER = {
    "KET": 1,
    "中考": 2,
    "PET": 3,
    "高考": 4,
    "CET-4": 5,
    "FCE": 6,
    "CET-6": 7,
    "Master": 8,
    "CAE": 9,
}

_ABBREVIATIONS = frozenset({
    "u.s.", "u.n.", "e.u.", "d.c.", "b.c.", "a.d.",
    "mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.", "st.",
    "co.", "corp.", "inc.", "ltd.", "vs.", "gen.", "gov.", "rep.", "sen.",
    "approx.", "e.g.", "i.e.", "a.m.", "p.m.", "etc.",
    "u.", "s.", "n.", "e.", "d.", "c.", "b.", "a.",
})

_NON_TERMINATING_ABBREVIATIONS = frozenset({
    "mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.", "st.",
    "vs.", "gen.", "gov.", "rep.", "sen.", "approx.", "e.g.", "i.e.",
})

_SENTENCE_STARTERS = frozenset({
    "the", "a", "an", "this", "that", "these", "those",
    "he", "she", "it", "they", "we", "i", "you", "there", "what", "who", "where", "when", "why", "how",
    "some", "many", "most", "all", "both", "each", "every", "no", "another",
    "however", "moreover", "meanwhile", "furthermore", "therefore", "thus", "instead",
    "then", "later", "now", "today", "yesterday", "recently", "currently", "finally",
    "in", "on", "at", "after", "before", "during", "under", "with", "without", "by", "from", "since", "until",
    "although", "while", "because", "if", "as", "so", "but", "and",
})

_UNCLOSED_ENDINGS = frozenset({
    "the", "a", "an", "by", "in", "on", "at", "to", "for", "with", "of", "from",
    "into", "onto", "upon", "about", "over", "under", "through", "between", "among",
    "behind", "without", "within", "against", "during", "toward", "towards", "as",
    "like", "and", "or", "but", "nor", "so", "yet", "because", "although", "though",
    "while", "whereas", "if", "unless", "since", "that", "which", "who", "whom",
    "whose", "where", "when",
})

_KNOWN_MULTIWORD_PROPER_NOUNS = [
    ("ku", "klux", "klan"),
    ("ku", "klux"),
    ("united", "states"),
    ("white", "house"),
    ("wall", "street"),
    ("silicon", "valley"),
    ("united", "nations"),
    ("federal", "reserve"),
    ("supreme", "court"),
    ("new", "york"),
]


def _first_sentence(text: object, *, fallback: str = "") -> str:
    """取得首个完整句，避免把整段转写塞入封面。识别常见缩写点，防止中途截断。"""
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return fallback

    zh_match = re.search(r"^.*?[。！？][”’\"']?", normalized)
    if zh_match:
        return zh_match.group(0).strip()

    pattern = re.compile(r'([.!?])([”’"\'\)]*)(\s+|$)')
    for m in pattern.finditer(normalized):
        punct = m.group(1)
        closing = m.group(2)
        end_pos = m.end()
        candidate = normalized[:m.start(1) + 1 + len(closing)].strip()
        trailing = normalized[end_pos:]

        if punct in ("!", "?"):
            return candidate

        # 对于英文句号 '.'
        if m.start(1) > 0 and normalized[m.start(1) - 1].isdigit() and trailing and trailing[0].isdigit():
            continue

        if (m.start(1) > 0 and normalized[m.start(1) - 1] == ".") or (trailing and trailing.startswith(".")):
            continue

        if trailing and trailing[0].islower():
            continue

        prefix = normalized[:m.start(1) + 1]
        words = prefix.split()
        if not words:
            continue
        clean_token = re.sub(r"[^a-z.]", "", words[-1].lower())
        if clean_token in _ABBREVIATIONS:
            # 1. 纯头衔/称谓/指示缩写绝不截断
            if clean_token in _NON_TERMINATING_ABBREVIATIONS:
                continue
            # 2. 单字母缩写点（如 U. S. 或 A. B.）绝不截断
            if len(clean_token) == 2 and clean_token[0].isalpha():
                continue
            # 3. 后随小写字母显然属于同一句
            if trailing and re.match(r"^[a-z]", trailing.strip()):
                continue
            # 4. 专名/机构缩写（如 U.S., U.N., E.U., Co., Inc.）：
            # 候选词数少于 3 词绝不可能构成独立主谓句（如 "The U.S.", "Apple Co."）
            if len(words) < 3:
                continue
            # 缩写前悬挂冠词/介词（如 "in the U.S.", "by the U.N."），语义未闭合
            if len(words) < 5 and any(w.lower().strip(".,!?;:\"'“”‘’") in {"the", "a", "an", "in", "on", "at", "to", "for", "from", "of", "by", "with", "across", "several"} for w in words[:-1]):
                continue
            # 5. 若后续词不是典型新句起始词（例如 Congress, Supreme, Federal, CEO, President 等），说明正在充当定语，属于同一句
            if trailing:
                next_word = trailing.strip().split()[0].lower().strip(".,!?;:\"'“”‘’()")
                if next_word and next_word not in _SENTENCE_STARTERS:
                    continue

        if len(words) >= 2 and words[-1] == "." and len(words[-2]) == 1 and words[-2].isalpha():
            continue

        return candidate

    return normalized


def _validate_quote_closure(quote_en: str, quote_zh: str) -> None:
    """确保中英文封面引语表达同一语义范围，检查专名完整性与引句闭合。"""
    en = str(quote_en or "").strip()
    zh = str(quote_zh or "").strip()
    if not en or not zh:
        raise ValueError("封面引语 quote_en 与 quote_zh 均不能为空")

    en_words = [w.strip(".,!?;:\"'“”‘’()") for w in en.split() if w.strip(".,!?;:\"'“”‘’()")]
    if len(en_words) < 3:
        raise ValueError(f"封面英文引语过短或不是完整句（仅 {len(en_words)} 词）：{en}")

    if re.search(r"\b[A-Za-z]\s*\.$", en) and not re.search(r"\b(?:u\.s\.|u\.n\.|e\.u\.|d\.c\.|etc\.)$", en, re.IGNORECASE):
        raise ValueError(f"封面英文引语截断在单字母专名缩写处：{en}")
    if re.search(r"\bseveral\s+U\b", en, re.IGNORECASE) and not re.search(r"\bseveral\s+U\.?\s*S\b", en, re.IGNORECASE):
        raise ValueError(f"封面英文引语包含残缺专有名词碎片：{en}")

    if len(en_words) < 4 and any(w.lower() in {"the", "a", "an", "in", "on", "at", "to", "for", "from", "of", "by", "with", "across", "several"} for w in en_words[:-1]) and any(en.lower().rstrip(".,!?;:\"'“”‘’()").endswith(abbr.rstrip(".")) for abbr in ("u.s", "u.n", "e.u", "co", "inc", "corp", "ltd")):
        raise ValueError(f"封面英文引语在专名缩写处残缺（缺少谓语或核心宾语）：{en}")

    if en_words:
        last_clean = en_words[-1].lower()
        if last_clean in _UNCLOSED_ENDINGS:
            raise ValueError(f"封面英文引语以悬空语法词结尾（{last_clean}）：{en}")

    en_lower_tokens = [w.strip(".,!?;:\"'“”‘’").lower() for w in en.split()]
    for entity in _KNOWN_MULTIWORD_PROPER_NOUNS:
        m = len(entity)
        for i in range(1, m):
            prefix = list(entity[:i])
            if len(en_lower_tokens) >= i and en_lower_tokens[-i:] == prefix:
                raise ValueError(f"封面英文引语在专有名词内部截断（{' '.join(prefix)}）：{en}")

    if en.count('"') % 2 != 0:
        raise ValueError(f"封面英文引语双引号未闭合：{en}")
    if en.count('“') != en.count('”'):
        raise ValueError(f"封面英文引语中文双引号未闭合：{en}")
    if en.count('(') != en.count(')'):
        raise ValueError(f"封面英文引语括号未闭合：{en}")
    if en.count('[') != en.count(']'):
        raise ValueError(f"封面英文引语方括号未闭合：{en}")

    if zh.count('"') % 2 != 0 or zh.count('“') != zh.count('”') or zh.count('‘') != zh.count('’') or zh.count('（') != zh.count('）') or zh.count('《') != zh.count('》'):
        raise ValueError(f"封面中文引语引号或括号未闭合：{zh}")

    en_len = len(en_words)
    zh_len = len(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", zh))
    if en_len >= 8 and zh_len < 4:
        raise ValueError(f"封面中英文引语语义范围不匹配（英文 {en_len} 词，中文仅 {zh_len} 字）：en='{en}', zh='{zh}'")
    if en_len <= 3 and zh_len >= 8:
        raise ValueError(f"封面中英文引语语义范围不匹配（英文仅 {en_len} 词，中文却有 {zh_len} 字）：en='{en}', zh='{zh}'")


def _normalise_ipa(value: object) -> str:
    ipa = str(value or "").strip()
    if not ipa:
        return ""
    return ipa if ipa.startswith("/") else f"/{ipa}/"


def _candidate_items(timeline: Mapping[str, Any], quote_en: str) -> list[dict[str, Any]]:
    """筛掉不可教学展示的伪词条，并按真实课程等级排序。"""
    raw_candidates = (
        timeline.get("learning_points")
        or timeline.get("vocabulary_candidates")
        or timeline.get("vocabulary")
        or []
    )
    if not isinstance(raw_candidates, list):
        return []

    in_quote: list[dict[str, Any]] = []
    all_valid: list[dict[str, Any]] = []
    for index, raw_item in enumerate(raw_candidates):
        if not isinstance(raw_item, Mapping):
            continue
        word = str(raw_item.get("word") or "").strip().strip(".,;:!?\"'“”‘’")
        meaning = str(raw_item.get("context_meaning_zh") or raw_item.get("meaning_zh") or raw_item.get("meaning") or "").strip()
        level = str(raw_item.get("recommended_level") or "外刊高频").strip()
        friendly_tag = str(raw_item.get("friendly_tag") or "").strip()
        if (
            not word
            or not meaning
            or "'" in word
            or "’" in word
            or not re.search(r"[A-Za-z]", word)
        ):
            continue
        item = {
            "word": word,
            "ipa": _normalise_ipa(raw_item.get("phonetic") or raw_item.get("ipa")),
            "phonetic_word": str(raw_item.get("phonetic_word") or word).strip(),
            "meaning": meaning,
            "level": " · ".join(part for part in (level, friendly_tag) if part),
            "_rank": _LEVEL_ORDER.get(level, 0),
            "_index": index,
        }
        all_valid.append(item)
        if re.search(rf"\b{re.escape(word)}\b", quote_en, re.IGNORECASE):
            in_quote.append(item)

    chosen = in_quote if in_quote else all_valid
    chosen.sort(key=lambda item: (-item["_rank"], -len(item["word"]), item["_index"]))
    return chosen


def _difficulty_tag(candidates: list[dict[str, Any]]) -> str:
    highest_rank = max((item["_rank"] for item in candidates), default=4)
    if highest_rank >= 7:
        return "★★★★☆ (六级 / 考研 / 雅思)"
    if highest_rank >= 4:
        return "★★★☆☆ (中高考 / 四六级)"
    return "★★☆☆☆ (中考 / KET / PET)"


def _vocab_stat(timeline: Mapping[str, Any], candidates: list[dict[str, Any]]) -> str:
    selection = timeline.get("vocabulary_selection")
    if isinstance(selection, Mapping):
        lexical_word_count = selection.get("lexical_word_count")
        selected_count = selection.get("selected_count")
        if isinstance(lexical_word_count, int) and isinstance(selected_count, int):
            return f"本篇 {lexical_word_count} 词 · {selected_count} 个重点"
    total_points = (
        timeline.get("learning_points")
        or timeline.get("vocabulary_candidates")
        or timeline.get("vocabulary")
        or []
    )
    if isinstance(total_points, list) and total_points:
        return f"本篇 {len(total_points)} 个可学词"
    return f"本篇 {len(candidates)} 个可学词"


def build_english_world_cover_payload(timeline: Mapping[str, Any], *, date_str: str | None = None) -> dict[str, Any]:
    """从已富集时间线构建英语世界封面 payload。"""
    if not isinstance(timeline, Mapping):
        raise ValueError("timeline 必须是 JSON object")

    # 语言 QA 新流程在冻结展示计划时会写入此精确载荷。封面是最终教学
    # 内容的一部分，绝不能在渲染前又根据旧 vocabulary_candidates 重新选词。
    publication = timeline.get("publication_text")
    if isinstance(publication, Mapping) and isinstance(publication.get("cover_payload"), Mapping):
        payload = dict(publication["cover_payload"])
        if date_str is not None:
            payload["date_str"] = date_str
        return validate_english_world_cover_payload(payload)

    title = str(timeline.get("headline_zh") or "英语时事精读").strip()
    quote_en = _first_sentence(timeline.get("english_text"))
    quote_zh = _first_sentence(timeline.get("translation_zh"))
    if not quote_en or not quote_zh:
        raise ValueError("timeline 缺少可用于封面的中英文首句")
    _validate_quote_closure(quote_en, quote_zh)

    ranked_candidates = _candidate_items(timeline, quote_en)
    vocab_items = [{key: value for key, value in item.items() if not key.startswith("_")} for item in ranked_candidates[:2]]
    source_provenance = timeline.get("source_provenance")
    source_provenance = source_provenance if isinstance(source_provenance, Mapping) else {}
    publisher = str(source_provenance.get("publisher") or source_provenance.get("source_channel") or "原声精选").strip()

    return {
        "content_type": "ENGLISH_WORLD_SHORT",
        "title": title,
        "subtitle": "● 英语新闻 · 原声双语精读",
        "quote_en": quote_en,
        "quote_zh": quote_zh,
        "highlight_words": [
            item["word"] for item in vocab_items
            if re.search(rf"\b{re.escape(item['word'])}\b", quote_en, re.IGNORECASE)
        ],
        "vocab_items": vocab_items,
        "difficulty_tag": _difficulty_tag(ranked_candidates),
        "vocab_stat": _vocab_stat(timeline, ranked_candidates),
        "audio_source": f"{publisher} 原声",
        "date_str": date_str or f"{date.today():%Y.%m.%d} 今日外刊打卡",
        "audio_edition": "original_audio_subtitled",
    }


def validate_english_world_cover_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """在渲染前拒绝缺少关键教学字段的外部 payload。"""
    if not isinstance(payload, Mapping):
        raise ValueError("payload 必须是 JSON object")
    normalized = dict(payload)
    normalized["content_type"] = "ENGLISH_WORLD_SHORT"
    for field_name in ("title", "quote_en", "quote_zh", "difficulty_tag", "audio_source", "date_str"):
        if not isinstance(normalized.get(field_name), str) or not normalized[field_name].strip():
            raise ValueError(f"payload 缺少非空字段：{field_name}")
    _validate_quote_closure(normalized["quote_en"], normalized["quote_zh"])
    if not isinstance(normalized.get("highlight_words", []), list):
        raise ValueError("payload.highlight_words 必须是 list")
    if not isinstance(normalized.get("vocab_items", []), list):
        raise ValueError("payload.vocab_items 必须是 list")
    return normalized
