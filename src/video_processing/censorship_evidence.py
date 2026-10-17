"""只读审查证据：先核实原审计输入与规则，再解释命中及源字幕 cue 时间。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-17 | Codex | 不改判定或台账，提供可核实命中词、上下文、时间及规则依据。 |
"""
import hashlib
import re

from . import censor_engine
from .utils.file_utils import read_webvtt_cues


def blocklist_inputs(title, zh_title, description, subtitle):
    """保持服务现有拼接（包括空中文通道与重复字幕），供执行和审计回放共用。"""
    zh = zh_title or ""
    if not zh and re.search(r"[一-龥]", title):
        zh = title
    en = f"{title} {description}".strip()
    if subtitle:
        zh = f"{zh} {subtitle}".strip()
        en = f"{en} {subtitle}".strip()
    return zh, en


def review_evidence(video, incidents, subtitle, source_files=()):
    """无任何写入；旧证据缺失/改变就返回原因，不能用当前重扫冒充原命中。"""
    incident = incidents[0] if incidents else {}
    base = {"status": "UNAVAILABLE", "incident_id": incident.get("id"),
            "rule_id": incident.get("rule_id"), "rule_version": incident.get("rule_pack_version"),
            "input_hash": incident.get("input_hash"), "review_stage": incident.get("review_stage")}

    def unavailable(message):
        return {**base, "message": message}

    if not incident:
        return unavailable("没有原审计记录；下方仅为当前重扫，不能证明原拦截位置。")
    if incident.get("stage") != "blocklist":
        return unavailable("该记录不属于 P0/P1/P2 规则证据；请核对对应审计。")
    if not base["input_hash"] or not base["rule_version"]:
        return unavailable("原审计缺少输入或规则指纹，无法核实原命中。")
    if base["rule_version"] != censor_engine.current_rules_fingerprint():
        return unavailable("规则版本已变化，当前重扫不能代替原审计命中。")
    title, zh_title, description = (video.get(field) or "" for field in ("title", "zh_title", "description"))
    zh, en = blocklist_inputs(title, zh_title, description, subtitle)
    joined = "\n".join(t for t in (title, zh_title, description, f"{zh}\n{en}") if t)
    if hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16] != base["input_hash"]:
        return unavailable("标题、描述或字幕与原审计输入不一致／缺失，无法核实原命中。")
    result = censor_engine.check_text(zh_text=zh, en_text=en)
    if not result.hit or any(getattr(result, key) != incident.get(key) for key in ("matched", "level", "channel")):
        return unavailable("当前复核结果与原审计不一致，不能展示为原命中。")
    detail = censor_engine.explain_blocklist_hit(zh if result.channel == "zh" else en, result)
    if not detail:
        return unavailable("该规则暂无可验证的位置解释；请查看原审计及完整字幕。")
    # 解析结果须与送审字幕逐字一致，才允许把位置绑定到 cue。ASS 不伪造 VTT 时间。
    cues = read_webvtt_cues(source_files)
    timed = bool(cues) and "\n".join(cue["text"] for cue in cues) == subtitle
    channel_text = zh if result.channel == "zh" else en
    subtitle_offset = len(channel_text) - len(subtitle) if subtitle else len(channel_text)
    indexed, offset = [], subtitle_offset
    if timed:
        for cue in cues:
            indexed.append((offset, offset + len(cue["text"]), cue))
            offset += len(cue["text"]) + 1
    terms = []
    for term, (start, end) in zip(detail["terms"], detail["raw_spans"]):
        locations = [{key: cue[key] for key in ("file", "start", "end")}
                     for left, right, cue in indexed if left < end and right > start]
        in_subtitle = bool(subtitle) and start >= subtitle_offset
        terms.append({"term": term, "actual": channel_text[start:end], "locations": locations,
                      "source": "字幕" if in_subtitle else "标题／描述", "timing_available": bool(locations)})
    return {**base, "status": "VERIFIED_REPLAY", "message": "原审计输入及规则指纹一致；以下为只读复核，不代表放行。",
            "terms": terms, "context": detail["context"], "gap": detail["gap"],
            "max_gap": detail["max_gap"], "normalization": detail["normalization"],
            "basis": "近距离共现规则" if detail["max_gap"] is not None else "直接词命中规则",
            "timing_note": "时间为原 VTT cue 区间，重叠自动字幕保持原样。" if timed else "当前字幕无可核实的 VTT 时间，不推测时间。"}
