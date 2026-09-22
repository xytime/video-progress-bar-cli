"""双本地原声证据解决唯一 P2 连接词疑点；不改写独立审校或重开预算。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-22 | Codex | 限定 at/and 原声恢复，独立侧车绑定修订前后全部证据。 |

依赖：scripts → language_qa → source_resolution → language_protocol / display_plan。
"""
from copy import deepcopy
from pathlib import Path
import re

from .caption_evidence import tokens, transcript_differences

RESOLUTION_VERSION = "english-world-source-resolution-v1"


def corrected_payload(before, index, replacement):
    """只同步一个 0-based 词及全文、段落；绝不改译文、时间、专名或教学内容。"""
    if type(index) is not int or not 0 <= index < len(before["words"]):
        raise ValueError("原声裁决词位置非法")
    old = before["words"][index]["text"]
    if (old, replacement) != ("at", "and"):
        raise ValueError("原声恢复仅支持 at → and；其他差异继续阻断")
    result = deepcopy(before)
    if before["english_text"].split() != [w["text"] for w in before["words"]]:
        raise ValueError("原声恢复要求全文与词轴精确一致")
    if " ".join(p["english_text"] for p in before["paragraphs"]) != before["english_text"]:
        raise ValueError("原声恢复要求段落完整一致")

    def replace_nth(text, word_index):
        matches = list(re.finditer(r"\S+", text))
        match = matches[word_index]
        if match.group() != old:
            raise ValueError("原声恢复目标不一致")
        return text[:match.start()] + replacement + text[match.end():]

    result["words"][index]["text"] = replacement
    result["english_text"] = replace_nth(before["english_text"], index)
    offset = 0
    for paragraph in result["paragraphs"]:
        count = len(paragraph["english_text"].split())
        if offset <= index < offset + count:
            paragraph["english_text"] = replace_nth(paragraph["english_text"], index - offset)
        offset += count
    # 不能更改任何被单独审校的学习点或封面引文。
    for point in before.get("learning_points", []):
        if point["word_index"] <= index < point["word_index"] + len(point["word"].split()):
            raise ValueError("原声恢复不能修改教学词")
    return result


def check_resolution(before, after, plan, report, evidence, editorial, confirmation, *, index):
    """纯验证：一项 P2 不确定、完整审校覆盖、双模型同词同位置及严格最小差异。"""
    from .language_protocol import cache_key, digest, evaluate, review_input, VERSION
    if report.get("version") != VERSION or report.get("state") != "FAIL" or report.get("adjudications"):
        raise ValueError("必须保留原始独立审校失败报告")
    evaluate(report["result"], plan, evidence=evidence, editorial=editorial)  # 验证覆盖和 schema
    unresolved = [f for f in report["result"]["findings"]
                  if f["status"] != "PASS" or f["severity"] in {"P0", "P1"}]
    if len(unresolved) != 1:
        raise ValueError("必须仅有一个未决问题")
    finding = unresolved[0]
    if (finding["check"], finding["status"], finding["severity"]) != (
            "TRANSCRIPT_ACCURACY", "UNCERTAIN", "P2"):
        raise ValueError("只允许 P2 转录不确定，不覆盖内容错误")
    match = re.fullmatch(r"timeline_differences:(\d+)", finding["target"])
    if not match:
        raise ValueError("未决目标不是时间线转录差异")
    difference = evidence["timeline_differences"][int(match[1])]
    if not difference["expected_span"][0] <= index < difference["expected_span"][1]:
        raise ValueError("改词不属于独立审校的未决目标")
    if report["plan_sha256"] != digest(plan) or report["input_key"] != cache_key(
            review_input(plan, evidence, editorial, projection=report.get("input_projection", "legacy")),
            report["model"], report.get("effort")):
        raise ValueError("原审校输入绑定失效")
    if evidence["timeline_differences"] != transcript_differences(before["english_text"], evidence["asr_text"]):
        raise ValueError("原 ASR 差异不匹配")
    if after != corrected_payload(before, index, "and"):
        raise ValueError("原声恢复存在额外修改")
    word = before["words"][index]
    primary = evidence["asr_words"][index]
    if (tokens(primary["word"]) != ["and"] or primary["start"] != word["start"]
            or primary["end"] != word["end"]):
        raise ValueError("原 ASR 没有相同位置的 and")
    if (confirmation.get("state") != "COMPLETE"
            or confirmation.get("engine") != "whisper-local-unprompted"
            or confirmation.get("word_index") != index
            or confirmation.get("timeline_sha256") != report["timeline_sha256"]
            or confirmation.get("source_sha256") != evidence["source_sha256"]
            or not confirmation.get("model_sha256")
            or confirmation["model_sha256"] == evidence["model_sha256"]
            or confirmation.get("sample_rate") != 16000 or confirmation.get("channels") != 1):
        raise ValueError("缺少绑定同源不同模型的无提示复听")
    absolute_start = word["start"] + evidence["source_start"]
    absolute_end = word["end"] + evidence["source_start"]
    if not evidence["source_start"] <= confirmation["source_start"] <= absolute_start < absolute_end <= confirmation["source_end"] <= evidence["source_end"]:
        raise ValueError("复听范围未覆盖疑点")
    candidates = [w for w in confirmation["words"] if tokens(w["word"]) == ["and"]
                  and absolute_start <= w["start"] + confirmation["source_start"]
                  < w["end"] + confirmation["source_start"] <= absolute_end
                  and w.get("probability", 0) >= 0.9]
    if len(candidates) != 1:
        raise ValueError("第二模型未明确确认相同时间位置的 and")
    return finding["target"]


def validate_resolution(timeline, *, manifest=None):
    """每次渲染、封装及提交重新验证；原报告始终保持 FAIL。"""
    from .language_protocol import digest, file_digest, read_json
    from .display_plan import verify_plan
    from .timeline_guard import validate_source_caption_boundary
    timeline = Path(timeline).resolve()
    root = timeline.parent
    receipt_path = root / "qa/source_resolution.json"
    receipt = read_json(receipt_path)
    if receipt.get("version") != RESOLUTION_VERSION or receipt.get("state") != "SOURCE_RESOLVED":
        raise ValueError("原声裁决状态非法")
    required = {"qa/language_qa.json", "qa/source_evidence.json", "editorial_changes.json",
                "qa/source_word_confirmation.json", "qa/source_word_confirmation.wav",
                "qa/source_resolution/timeline.before.json", "qa/source_resolution/display_plan.before.json"}
    if set(receipt.get("bindings", {})) != required:
        raise ValueError("原声裁决缺少完整证据指纹")
    for name, expected in receipt["bindings"].items():
        if file_digest(root / name) != expected:
            raise ValueError(f"原声裁决证据已变化: {name}")
    before = read_json(root / "qa/source_resolution/timeline.before.json")
    old_plan = read_json(root / "qa/source_resolution/display_plan.before.json")
    report = read_json(root / "qa/language_qa.json")
    evidence = read_json(root / "qa/source_evidence.json")
    confirmation = read_json(root / "qa/source_word_confirmation.json")
    if (report["timeline_sha256"] != file_digest(root / "qa/source_resolution/timeline.before.json")
            or confirmation["audio_sha256"] != file_digest(root / "qa/source_word_confirmation.wav")):
        raise ValueError("原时间线或复听音频绑定失效")
    payload = read_json(timeline)
    target = check_resolution(before, payload, old_plan, report, evidence,
                              read_json(root / "editorial_changes.json"), confirmation,
                              index=receipt["word_index"])
    if target != receipt["target"]:
        raise ValueError("原声裁决目标改变")
    p = payload["source_provenance"]
    if (file_digest(root / p["source_video"]) != evidence["source_sha256"]
            or file_digest(root / p["caption_artifact"]) != evidence["caption_sha256"]
            or p["source_start_seconds"] != evidence["source_start"]
            or p["source_end_seconds"] != evidence["source_end"]):
        raise ValueError("原声或源区间已变化")
    if file_digest(timeline) != receipt["timeline_sha256"]:
        raise ValueError("裁决后时间线已变化")
    plan = read_json(root / "display_plan.json")
    if digest(plan) != receipt["plan_sha256"]:
        raise ValueError("裁决后展示计划已变化")
    verify_plan(before, old_plan, report["timeline_sha256"])
    verify_plan(payload, plan, file_digest(timeline))
    validate_source_caption_boundary(payload, timeline_path=timeline)
    for name in ("ledger", "cache"):
        if file_digest(Path(receipt[name + "_path"])) != receipt[name + "_sha256"]:
            raise ValueError("原审校账本或缓存已变化")
    if manifest is not None:
        value = read_json(manifest)
        if (value.get("display_plan_sha256") != digest(plan)
                or value.get("language_qa_sha256") != file_digest(root / "qa/language_qa.json")
                or value.get("source_resolution_sha256") != file_digest(receipt_path)):
            raise ValueError("成片未绑定原报告与原声裁决")
    return {**report, "state": "SOURCE_RESOLVED", "independent_review_state": "FAIL",
            "resolution": {"target": target, "method": "TWO_LOCAL_ASR_MINIMAL_RESTORE"}}
