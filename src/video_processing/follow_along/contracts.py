"""Timeline 契约、文件证据与宿主语义闸门。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-07 | Codex | 建立独立文件/时间/文本证据闸门 |
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path



class PipelineError(ValueError):
    """可序列化且不隐式重试的阶段错误。"""
    def __init__(self, code: str, message: str, ids=()):
        super().__init__(message)
        self.code, self.ids = code, list(ids)

    def report(self):
        return {"code": self.code, "message": str(self), "affected_ids": self.ids}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False, separators=(",", ":")).encode()).hexdigest()


def local_path(root: Path, uri: str) -> Path:
    root = root.resolve()
    if not uri or "\\" in uri or ":" in uri or Path(uri).is_absolute() or ".." in Path(uri).parts:
        raise PipelineError("INPUT_INVALID", f"非法素材相对路径: {uri}")
    path = (root / uri).resolve()
    if not path.is_relative_to(root):
        raise PipelineError("INPUT_INVALID", f"素材逃逸工作目录: {uri}")
    return path


def verify_ref(root: Path, ref: dict) -> Path:
    path = local_path(root, ref["uri"])
    if not path.is_file() or digest(path) != ref["sha256"]:
        raise PipelineError("INPUT_INVALID", f"证据缺失或哈希不一致: {ref['uri']}")
    if "byte_length" in ref and path.stat().st_size != ref["byte_length"]:
        raise PipelineError("INPUT_INVALID", f"素材大小不一致: {ref['uri']}")
    return path


def unique(items, label):
    result = {item["id"]: item for item in items}
    if len(result) != len(items):
        raise PipelineError("INPUT_INVALID", f"重复 {label} ID")
    return result


def tokens(text):
    """标点不伪装成有声词；Unicode code point span。"""
    return list(re.finditer(r"[^\W_]+(?:['’\-][^\W_]+)*", text, re.UNICODE))


def validate(plan: dict, root: Path | None = None, *, resolved=False):
    """结构与媒体证据分开检查；正式入口不能绕过合成示例禁用。"""
    from jsonschema import Draft202012Validator
    schema = Path(__file__).resolve().parents[3] / "docs/specs/bilingual-follow-along/timeline.schema.json"
    errors = sorted(Draft202012Validator(json.loads(schema.read_text())).iter_errors(plan),
                    key=lambda error: str(list(error.path)))
    if errors:
        error = errors[0]
        raise PipelineError("INPUT_INVALID", f"{list(error.path)}: {error.message}")
    if root is not None and plan["metadata"].get("synthetic_contract_example"):
        raise PipelineError("INPUT_INVALID", "合成契约示例不能进入正式制作")
    if resolved and plan["phase"] != "resolved":
        raise PipelineError("ALIGNMENT_INCOMPLETE", "必须先冻结 resolved timeline")
    duration = plan["metadata"]["duration_tick"]
    assets = unique(plan["assets"], "asset")
    styles = unique(plan["styles"], "style")
    layers = unique(plan["layers"], "layer")
    tracks = unique(plan["tracks"], "track")
    cues = unique(plan["cues"], "cue")
    unique(plan["motions"], "motion")
    words = unique([w for c in cues.values() for w in c["words"]], "word")
    def require(ref, table):
        if ref not in table:
            raise PipelineError("INPUT_INVALID", f"悬空引用: {ref}")
        return table[ref]
    def interval(value, limit=duration):
        if not 0 <= value["start_tick"] < value["end_tick"] <= limit:
            raise PipelineError("INPUT_INVALID", f"时间区间越界: {value}")
    def span_text(asset_id, span, expected):
        asset = require(asset_id, assets)
        if asset["kind"] != "text" or span["end"] <= span["start"]:
            raise PipelineError("INPUT_INVALID", "非法文本来源或 span")
        if root is not None:
            text = verify_ref(root, asset).read_text(encoding="utf-8")
            if span["end"] > len(text) or text[span["start"]:span["end"]] != expected:
                raise PipelineError("INPUT_INVALID", f"原文 span 不匹配: {asset_id}")
    for asset in assets.values():
        if asset["kind"] == "audio":
            from fractions import Fraction
            if abs(Fraction(asset["sample_count"] * plan["clock"]["ticks_per_second"], asset["sample_rate"]) - asset["duration_tick"]) > 1:
                raise PipelineError("INPUT_INVALID", "音频声明样本数与时长不一致", [asset["id"]])
        if root is not None:
            verify_ref(root, asset)
        if "source_asset_id" in asset:
            visited = {asset["id"]}
            ancestor = asset
            while "source_asset_id" in ancestor:
                parent_id = ancestor["source_asset_id"]
                if parent_id in visited:
                    raise PipelineError("INPUT_INVALID", "素材衍生关系存在环")
                visited.add(parent_id)
                ancestor = require(parent_id, assets)
            parent = require(asset["source_asset_id"], assets)
            mapping = asset["source_time_map"]
            interval(mapping["parent_interval"], parent["duration_tick"])
            interval(mapping["asset_interval"], asset["duration_tick"])
            if mapping["playback_rate"]["numerator"] != mapping["playback_rate"]["denominator"]:
                raise PipelineError("INPUT_INVALID", "首版不支持非 1 播放速率")
            if (mapping["parent_interval"]["end_tick"] - mapping["parent_interval"]["start_tick"] !=
                    mapping["asset_interval"]["end_tick"] - mapping["asset_interval"]["start_tick"]):
                raise PipelineError("INPUT_INVALID", "素材时间映射长度不一致")
    for style in styles.values():
        if require(style["font_asset_id"], assets)["kind"] != "font":
            raise PipelineError("FONT_MISSING", "字体引用不是 font 素材")
    roles = [t["role"] for t in tracks.values()]
    if roles.count("performer") != 1 or roles.count("render_master") != 1:
        raise PipelineError("SOURCE_MAPPING_AMBIGUOUS", "须唯一选择 performer/render_master")
    clip_ids = []
    for track in tracks.values():
        previous = 0
        for clip in track["clips"]:
            clip_ids.append(clip)
            asset = require(clip["asset_id"], assets)
            if asset["kind"] != track["kind"]:
                raise PipelineError("INPUT_INVALID", "轨道与素材类型不匹配")
            interval(clip["timeline_interval"])
            interval(clip["source_interval"], asset["duration_tick"])
            if clip["playback_rate"]["numerator"] != clip["playback_rate"]["denominator"]:
                raise PipelineError("INPUT_INVALID", "首版不支持非 1 播放速率")
            a, b = clip["source_interval"], clip["timeline_interval"]
            if a["end_tick"] - a["start_tick"] != b["end_tick"] - b["start_tick"]:
                raise PipelineError("SOURCE_MAPPING_AMBIGUOUS", "音画 clip 时间映射长度不一致")
            if b["start_tick"] < previous:
                raise PipelineError("INPUT_INVALID", "同轨道 clip 重叠")
            previous = b["end_tick"]
    unique(clip_ids, "clip")
    cue_owners = []
    for layer in layers.values():
        interval(layer["visible_interval"])
        if layer["kind"] == "video":
            require(layer["track_id"], tracks)
        if layer["kind"] == "text":
            require(layer["style_id"], styles)
        if layer["kind"] == "lyrics":
            cue_owners.extend(layer["cue_ids"])
            for cue_id in layer["cue_ids"]:
                require(cue_id, cues)
    if sorted(cue_owners) != sorted(cues):
        raise PipelineError("INPUT_INVALID", "阅读窗口须恰好覆盖全部 cue 一次")
    if root is not None:
        for language in ("en", "zh-CN"):
            spans = {}
            for cue in cues.values():
                item = cue if language == "en" else cue["translation"]
                spans.setdefault(item["source_asset_id"], []).append(item["source_span"])
            for asset_id, parts in spans.items():
                text = verify_ref(root, assets[asset_id]).read_text(encoding="utf-8")
                cursor = 0
                for span in sorted(parts, key=lambda p: p["start"]):
                    if span["start"] < cursor or text[cursor:span["start"]].strip():
                        raise PipelineError("INPUT_INVALID", "原文/译文存在遗漏或重复 span", [asset_id])
                    cursor = span["end"]
                if text[cursor:].strip():
                    raise PipelineError("INPUT_INVALID", "原文/译文尾部未覆盖", [asset_id])
    previous = 0
    origin_ids = set()
    for cue in cues.values():
        require(cue["english_style_id"], styles)
        require(cue["translation"]["style_id"], styles)
        span_text(cue["source_asset_id"], cue["source_span"], cue["english_text"])
        translation = cue["translation"]
        span_text(translation["source_asset_id"], translation["source_span"], translation["text"])
        expected = [(m.start(), m.end(), m.group()) for m in tokens(cue["english_text"])]
        actual = [(w["display_span"]["start"], w["display_span"]["end"], w["text"]) for w in cue["words"]]
        if actual != expected:
            raise PipelineError("ALIGNMENT_INCOMPLETE", "词序列/原文 span 不完整", [cue["id"]])
        for word in cue["words"]:
            require(word["highlight"]["style_id"], styles)
            if word["highlight"]["style_id"] != cue["english_style_id"]:
                raise PipelineError("INPUT_INVALID", "首版高亮样式须与英文图集一致")
            for origin in word["origin_token_ids"]:
                if origin in origin_ids:
                    raise PipelineError("ALIGNMENT_AMBIGUOUS", "原词 ID 被重复使用", [origin])
                origin_ids.add(origin)
            if resolved and (word["timing_status"] not in {"observed", "manual"} or not word["interval"]):
                raise PipelineError("ALIGNMENT_INCOMPLETE", "存在缺失或估算词界", [word["id"]])
            if word["interval"]:
                interval(word["interval"])
                if word["interval"]["start_tick"] < previous:
                    raise PipelineError("ALIGNMENT_AMBIGUOUS", "词区间重叠或乱序", [word["id"]])
                previous = word["interval"]["end_tick"]
                if cue["interval"] and not (cue["interval"]["start_tick"] <= word["interval"]["start_tick"] and
                                           word["interval"]["end_tick"] <= cue["interval"]["end_tick"]):
                    raise PipelineError("INPUT_INVALID", "词界超出句界", [word["id"]])
            if root is not None and word["evidence_ref"]:
                verify_ref(root, word["evidence_ref"])
        if cue["interval"]:
            interval(cue["interval"])
        if resolved and root is not None:
            verify_ref(root, cue["layout"]["atlas_ref"])
    motion_keys = set()
    for motion in plan["motions"]:
        target, prop = motion["target"], motion["property"]
        table = {"layer": layers, "cue": cues, "word": words}[target["kind"]]
        obj = require(target["id"], table)
        if prop == "scroll_y_px" and (target["kind"] != "layer" or obj["kind"] != "lyrics"):
            raise PipelineError("INPUT_INVALID", "scroll 仅用于 lyrics layer")
        if prop == "opacity" and target["kind"] == "word":
            raise PipelineError("INPUT_INVALID", "首版不支持独立 word opacity")
        if prop == "opacity" and target["kind"] == "layer" and obj["kind"] != "lyrics":
            raise PipelineError("INPUT_INVALID", "首版仅支持 lyrics layer opacity motion")
        if prop == "highlight_progress" and target["kind"] != "word":
            raise PipelineError("INPUT_INVALID", "高亮进度仅用于 word")
        key = (target["kind"], target["id"], prop)
        if key in motion_keys:
            raise PipelineError("INPUT_INVALID", "重复 target/property motion")
        motion_keys.add(key)
        times = [k["at_tick"] for k in motion["keyframes"]]
        if times != sorted(set(times)) or times[-1] > duration:
            raise PipelineError("INPUT_INVALID", "keyframe 时间重复、乱序或越界")
        if prop != "scroll_y_px" and any(not 0 <= k["value"] <= 1 for k in motion["keyframes"]):
            raise PipelineError("INPUT_INVALID", "opacity/highlight 必须在 [0,1]")
    if root is not None:
        for entry in plan["provenance"]:
            verify_ref(root, entry["evidence_ref"])
    return plan
