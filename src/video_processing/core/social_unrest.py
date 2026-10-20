"""社会动荡题材的局部语义规则；只依赖标准库，不推断法律结论。

依赖方向：censor_engine -> 本模块；本模块不读取配置、文件或数据库。
"""
import hashlib
import json
import re
import unicodedata
from functools import lru_cache


MATCHER_VERSION = "social-unrest-context-v1"
DEFAULT_RULES = {
    "window_chars": 180,
    "cue_window_seconds": 15,
    "families": {
        "unrest": {
            "terms": [
                "骚乱", "暴乱", "打砸抢", "抢掠", "抢劫商店", "街头暴力", "警民冲突",
                "街头冲突", "暴动", "纵火", "焚烧车辆",
                r"\briots?\b", r"\brioting\b", r"\bloot(?:ing|ed|ers?)?\b",
                r"\bcivil\s+unrest\b", r"\bstreet\s+clashes\b",
                r"\bclash(?:es|ed|ing)?\s+with\s+(?:the\s+)?police\b",
            ],
            "requires_context": False,
        },
        "protest": {
            "terms": [
                "抗议", "示威", "游行", "封堵道路", "封锁道路",
                r"\bprotest(?:s|ed|ing|ers?)?\b", r"\bdemonstrat(?:e|es|ed|ion|ions|ors?|ing)\b",
                r"\broad\s+blockad(?:e|es|ing)\b",
            ],
            "requires_context": True,
            "non_civic": [r"\bdemonstrations?\s+of\s+(?:(?:a|an|the|new|latest)\s+)*(?:ai|software|chips?|devices?|(?:police\s+)?robots?)\b"],
        },
        "collective_action": {
            "terms": ["集会", "罢工", r"\b(?:mass\s+)?rall(?:y|ies|ied|ying)\b",
                      r"\b(?:general\s+)?strik(?:e|es|ers?|ing)\b"],
            "requires_context": True,
            "non_civic": [r"\b(?:stock|bond|market|equity|price|prices)\s+(?:market\s+)?rall(?:y|ies)\b",
                          r"\brall(?:y|ies)\s+in\s+(?:(?:stock|bond|share)\s+)?prices\b",
                          r"\bstrik(?:e|es|ing)\s+out\b"],
            "context": ["群众", "民众", "工人", "学生", "街头", "警察", "政府", "全国",
                        r"\b(?:crowds?|workers?|students?|streets?|police|government|nationwide|union|unions)\b",
                        r"\b(?:mass\s+rally|general\s+strike)\b"],
        },
        "mobilization": {
            "terms": [
                "起义", "叛乱", "造反", "推翻政权", "号召上街", "走上街头", "革命",
                r"\buprisings?\b", r"\binsurrections?\b", r"\brebellions?\b",
                r"\boverthrow(?:s|ing|n)?\b", r"\brevolutions?\b",
                r"\btak(?:e|es|ing)\s+to\s+the\s+streets\b",
            ],
            "requires_context": True,
            "context": ["政权", "推翻", "起义", "叛乱", "造反", "号召上街", "走上街头", "警察",
                        r"\b(?:regime|overthrow(?:n|ing)?|police|streets?|uprising|insurrection)\b"],
        },
    },
    "context": [
        "民众", "群众", "工人", "学生", "街头", "街道", "警方", "警察", "政府", "政权",
        "燃油", "油价", "生活成本", "物价", "养老金", "抗议者", "示威者", "全国", "爆发", "镇压",
        r"\b(?:police|government|regime|crowds?|workers?|students?|marchers?|streets?)\b",
        r"\b(?:fuel|diesel|petrol|pension|tax|prices?|costs?)\b",
        r"\b(?:nationwide|anti-government|erupt(?:s|ed|ing)?|crackdown)\b",
        r"\b(?:protesters?|demonstrators?)\b",
    ],
    "historical": [
        r"(?:^|\bin\s+)(?:1[0-8][0-9]{2}|19[0-6][0-9])\b", "法国大革命", "辛亥革命",
        r"\bfrench\s+revolution\b", r"\bancient\b", "古代", "历史上的",
    ],
    "current": [
        "今天", "昨日", "昨天", "近日", "本周", "周末", "再次", "目前", "如今",
        r"\b(?:today|yesterday|tonight|recent(?:ly)?|now|ongoing|this\s+week|again)\b",
        r"\berupts?\b",
    ],
}


def validate_rules(rules):
    """热加载缺失/空规则不可静默关掉该类别。"""
    if not isinstance(rules, dict):
        raise ValueError("social_unrest must be an object")
    for key, maximum in (("window_chars", 300), ("cue_window_seconds", 30)):
        if type(rules.get(key)) is not int or not 1 <= rules[key] <= maximum:
            raise ValueError(f"social_unrest.{key} out of range")
    if set(rules.get("families", {})) != set(DEFAULT_RULES["families"]):
        raise ValueError("social_unrest requires all term families")
    for family in rules["families"].values():
        if type(family.get("requires_context")) is not bool:
            raise ValueError("social_unrest requires_context must be bool")
        _validate_patterns(family.get("terms"))
        if "context" in family:
            _validate_patterns(family["context"])
        if "non_civic" in family:
            _validate_patterns(family["non_civic"])
    for key in ("context", "historical", "current"):
        _validate_patterns(rules.get(key))


def _validate_patterns(patterns):
    if not isinstance(patterns, list) or not patterns or not all(isinstance(p, str) and p for p in patterns):
        raise ValueError("social_unrest patterns must be nonempty string lists")
    for pattern in patterns:
        re.compile(pattern, re.IGNORECASE)


@lru_cache(maxsize=64)
def _patterns(patterns):
    return re.compile("|".join(f"(?:{p})" for p in patterns), re.IGNORECASE)


def input_hash(documents):
    payload = json.dumps(documents, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _normalized(text):
    chars, offsets = [], []
    for index, char in enumerate(text):
        for normalized in unicodedata.normalize("NFKC", char).lower():
            if normalized not in "\u200b\ufeff":
                if normalized.isspace():
                    normalized = " "
                    if chars and chars[-1] == " ":
                        continue
                chars.append(normalized)
                offsets.append(index)
    keep = [i for i, char in enumerate(chars) if not (
        char == " " and 0 < i < len(chars) - 1
        and "\u4e00" <= chars[i - 1] <= "\u9fff" and "\u4e00" <= chars[i + 1] <= "\u9fff")]
    return "".join(chars[i] for i in keep), [offsets[i] for i in keep]


def _seconds(value):
    result = 0.0
    for part in value.split(":"):
        result = result * 60 + float(part)
    return result


def _local_bounds(text, start, end, radius):
    left, right = max(0, start - radius), min(len(text), end + radius)
    # 不跨句找语义搭配；字幕换行由真实时间窗口约束。
    before = list(re.finditer(r"[.!?。！？;；]", text[left:start]))
    after = re.search(r"[.!?。！？;；]", text[end:right])
    if before:
        left += before[-1].end()
    if after:
        right = end + after.start()
    return left, right


def classify(documents, rules):
    """返回首个可解释风险；每份输入独立，禁止跨文档/跨远距离字幕共现。"""
    context = _patterns(tuple(rules["context"]))
    history = _patterns(tuple(rules["historical"]))
    current = _patterns(tuple(rules["current"]))
    for document in documents:
        raw = document["text"]
        text, offsets = _normalized(raw)
        # JSON 键顺序不参与规则指纹，因此首命中顺序也必须固定。
        for family_name in DEFAULT_RULES["families"]:
            family = rules["families"][family_name]
            for term in _patterns(tuple(family["terms"])).finditer(text):
                # 只排除该次词义命中的精确短语，不让财经/科技词替同句真实事件豁免。
                if "non_civic" in family and any(
                    other.start() <= term.start() and other.end() >= term.end()
                    for other in _patterns(tuple(family["non_civic"])).finditer(text)
                ):
                    continue
                left, right = _local_bounds(text, term.start(), term.end(), rules["window_chars"])
                cues = document.get("cues", [])
                anchor = [cue for cue in cues if cue["offset"] <= offsets[term.start()] < cue["offset"] + len(cue["text"])]
                if anchor:
                    # 只允许时间邻近的相邻 cue 参与上下文；缺失/非法时间直接退到命中 cue。
                    try:
                        anchor_time = _seconds(anchor[0]["start"])
                        nearby = [cue for cue in cues if abs(_seconds(cue["start"]) - anchor_time) <= rules["cue_window_seconds"]]
                    except (ValueError, KeyError):
                        nearby = anchor
                    raw_left = min(cue["offset"] for cue in nearby)
                    raw_right = max(cue["offset"] + len(cue["text"]) for cue in nearby)
                    while left < term.start() and offsets[left] < raw_left:
                        left += 1
                    while right > term.end() and offsets[right - 1] >= raw_right:
                        right -= 1
                local = text[left:right]
                if history.search(local) and not current.search(local):
                    continue
                family_context = _patterns(tuple(family["context"])) if "context" in family else context
                contextual = family_context.search(local)
                if family["requires_context"] and contextual is None:
                    continue
                spans = [(term.start(), term.end())]
                if family["requires_context"]:
                    spans.append((left + contextual.start(), left + contextual.end()))
                ordered = sorted(spans)
                gap = max(0, ordered[-1][0] - ordered[0][1]) if len(spans) > 1 else None
                terms = []
                for start, end in dict.fromkeys(spans):
                    a, b = offsets[start], offsets[end - 1] + 1
                    locations = [{k: cue[k] for k in ("file", "start", "end")}
                                 for cue in cues if cue["offset"] < b and cue["offset"] + len(cue["text"]) > a]
                    terms.append({"term": text[start:end], "actual": raw[a:b], "source": document["source"],
                                  "offset_start": a, "offset_end": b,
                                  "locations": locations, "timing_available": bool(locations)})
                return {"family": family_name, "matched": " + ".join(t["actual"] for t in terms),
                        "source_field": document["source"], "terms": terms,
                        "context": raw[offsets[left]:offsets[right - 1] + 1],
                        "basis": "社会动荡题材局部上下文规则", "matcher": MATCHER_VERSION,
                        "max_gap": rules["window_chars"] if gap is not None else None,
                        "gap": gap, "normalization": "NFKC + lower"}
    return None
