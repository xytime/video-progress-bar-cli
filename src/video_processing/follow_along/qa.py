"""渲染前几何/时间 QA 与编码后独立媒体验收。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-07 | Codex | 完整活动双语块逐帧安全区检测与成片音画检查 |
"""
from fractions import Fraction

from .contracts import PipelineError
from .timing import evaluate, frame_count


def contains(outer, inner):
    return (outer["x"] <= inner["x"] and outer["y"] <= inner["y"] and
            inner["x"] + inner["width"] <= outer["x"] + outer["width"] and
            inner["y"] + inner["height"] <= outer["y"] + outer["height"])


def overlaps(a, b):
    return (a["x"] < b["x"] + b["width"] and b["x"] < a["x"] + a["width"] and
            a["y"] < b["y"] + b["height"] and b["y"] < a["y"] + a["height"])


def preflight(plan):
    if plan["canvas"]["width"] % 2 or plan["canvas"]["height"] % 2:
        raise PipelineError("LAYOUT_OVERFLOW", "yuv420p 成片尺寸必须为偶数")
    safe = plan["canvas"]["content_safe_rect"]
    layers = [l for l in plan["layers"] if l["kind"] != "background"]
    for layer in layers:
        if not contains(safe, layer["rect"]):
            raise PipelineError("LAYOUT_OVERFLOW", "图层越出安全区", [layer["id"]])
        for blocked in plan["canvas"]["occlusions"]:
            if overlaps(layer["rect"], blocked["rect"]):
                raise PipelineError("LAYOUT_OVERFLOW", "图层撞入平台 UI 预留区", [layer["id"], blocked["id"]])
    for i, left in enumerate(layers):
        for right in layers[i + 1:]:
            if overlaps(left["rect"], right["rect"]):
                raise PipelineError("LAYOUT_OVERFLOW", "静态图层相撞", [left["id"], right["id"]])
    cues = {c["id"]: c for c in plan["cues"]}
    for frame in range(frame_count(plan)):
        state = evaluate(plan, frame)
        if not state["active_cue"]:
            continue
        cue = cues[state["active_cue"]]
        for layer in layers:
            if layer["kind"] != "lyrics" or cue["id"] not in layer["cue_ids"]:
                continue
            if not layer["visible_interval"]["start_tick"] <= state["tick"] < layer["visible_interval"]["end_tick"]:
                raise PipelineError("LAYOUT_OVERFLOW", "活动词所在阅读窗口不可见", [cue["id"]])
            block = cue["layout"]["block_rect"].copy()
            block["y"] -= state["layers"][layer["id"]]["scroll"]
            if not contains({"x": 0, "y": 0, "width": layer["rect"]["width"], "height": layer["rect"]["height"]}, block):
                raise PipelineError("LAYOUT_OVERFLOW", f"活动双语块在 frame={frame} 被裁", [cue["id"]])
    return {"state": "PASS", "frames_checked": frame_count(plan), "checks": ["safe_zone", "static_collision", "active_bilingual_block"]}


def final_media(plan, path, tools, directory):
    probe = tools.probe(path)
    video = [s for s in probe["streams"] if s["codec_type"] == "video"]
    audio = [s for s in probe["streams"] if s["codec_type"] == "audio"]
    if len(video) != 1 or len(audio) != 1:
        raise PipelineError("OUTPUT_QA_FAILED", "成片必须含一个视频轨和一个音轨")
    v, a = video[0], audio[0]
    fps = plan["clock"]["fps"]
    frame_seconds = Fraction(fps["denominator"], fps["numerator"])
    expected = Fraction(plan["metadata"]["duration_tick"], plan["clock"]["ticks_per_second"])
    if (v["width"], v["height"]) != (plan["canvas"]["width"], plan["canvas"]["height"]):
        raise PipelineError("OUTPUT_QA_FAILED", "成片尺寸与计划不符")
    if int(v.get("nb_frames", -1)) != frame_count(plan) or Fraction(v["avg_frame_rate"]) != Fraction(fps["numerator"], fps["denominator"]):
        raise PipelineError("OUTPUT_QA_FAILED", "实际帧数/帧率与计划不符")
    if int(a["sample_rate"]) != 48000 or a["channels"] != 2:
        raise PipelineError("OUTPUT_QA_FAILED", "成片音轨须为 48k stereo")
    durations = [Fraction(s["duration"]) for s in (v, a)]
    if any(abs(d - expected) > frame_seconds for d in durations) or abs(durations[0] - durations[1]) > frame_seconds:
        raise PipelineError("OUTPUT_QA_FAILED", "成片音画时长漂移超过一帧")
    loudness = tools.measure(path, directory, "encoded-check")
    tools.check_loudness(loudness, plan["policy"]["audio"], encoded=True)
    # 完整解码检查，不能用可读 MP4 header 替代成功编码。
    tools.run(["-v", "error", "-xerror", "-i", path, "-f", "null", "-"], directory / "decode-check.log")
    return {"state": "LOCAL_PACKAGE_READY", "probe": probe, "loudness": loudness,
            "real_alignment_accuracy": "NOT_MEASURED"}
