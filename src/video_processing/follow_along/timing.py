"""有理数时钟与任意 seek 可重复的运动求值。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-07 | Codex | 半开词界、正规化 easing 和绝对时间滚动 |
"""
from bisect import bisect_right
from fractions import Fraction
from math import ceil, exp


def half_up(value):
    value = Fraction(value)
    return (2 * value.numerator + value.denominator) // (2 * value.denominator)


def frame_count(plan):
    clock = plan["clock"]
    return ceil(Fraction(plan["metadata"]["duration_tick"] * clock["fps"]["numerator"],
                         clock["ticks_per_second"] * clock["fps"]["denominator"]))


def frame_tick(plan, frame):
    if not 0 <= frame < frame_count(plan):
        raise IndexError("frame 超出输出区间")
    clock = plan["clock"]
    return Fraction(frame * clock["ticks_per_second"] * clock["fps"]["denominator"],
                    clock["fps"]["numerator"])


def easing(u, spec):
    u = max(0.0, min(1.0, float(u)))
    kind = spec["type"]
    if kind == "hold":
        return float(u == 1)
    if kind == "linear":
        return u
    if kind == "smoothstep":
        return u * u * (3 - 2 * u)
    if kind == "exponential_out":
        k = spec["k"]
        from math import expm1
        return expm1(-k * u) / expm1(-k)
    if kind != "cubic_bezier":
        raise ValueError(f"未知 easing: {kind}")
    x1, y1, x2, y2 = spec["control_points"]
    if not 0 <= x1 <= x2 <= 1:
        raise ValueError("bezier x 必须单调")
    def curve(v, a, b):
        return 3 * (1 - v)**2 * v * a + 3 * (1 - v) * v**2 * b + v**3
    lo, hi = 0.0, 1.0
    for _ in range(48):
        mid = (lo + hi) / 2
        if curve(mid, x1, x2) < u:
            lo = mid
        else:
            hi = mid
    return curve((lo + hi) / 2, y1, y2)


def motion_value(keyframes, tick):
    index = bisect_right([k["at_tick"] for k in keyframes], tick) - 1
    if index < 0:
        return keyframes[0]["value"]
    start = keyframes[index]
    if index == len(keyframes) - 1:
        return start["value"]
    end = keyframes[index + 1]
    u = (tick - start["at_tick"]) / (end["at_tick"] - start["at_tick"])
    return start["value"] + (end["value"] - start["value"]) * easing(u, start["easing_to_next"])


def plan_scroll(plan, layer):
    """提前滚动；遇到重叠过渡从已求值位置开始新过渡。"""
    cues = {c["id"]: c for c in plan["cues"]}
    policy = plan["policy"]["scroll"]
    keys = [{"at_tick": 0, "value": layer["initial_scroll_y_px"], "easing_to_next": {"type": "hold"}}]
    for cue_id in layer["cue_ids"]:
        cue = cues[cue_id]
        rect = cue["layout"]["block_rect"]
        anchor = layer["active_anchor_y_px"] - layer["rect"]["y"]
        target = max(0, min(layer["document_height_px"] - layer["rect"]["height"],
                            rect["y"] + rect["height"] / 2 - anchor))
        start = max(keys[-1]["at_tick"], cue["interval"]["start_tick"] - policy["transition_tick"])
        current = motion_value(keys, start)
        if abs(current - target) <= policy["deadband_px"]:
            continue
        keys = [k for k in keys if k["at_tick"] < start]
        keys.append({"at_tick": start, "value": current, "easing_to_next": {"type": "smoothstep"}})
        end = cue["interval"]["start_tick"]
        if end == start:
            keys[-1]["value"] = target
            keys[-1]["easing_to_next"] = {"type": "hold"}
        else:
            keys.append({"at_tick": end, "value": target, "easing_to_next": {"type": "hold"}})
    return {"id": f"scroll-{layer['id']}", "target": {"kind": "layer", "id": layer["id"]},
            "property": "scroll_y_px", "keyframes": keys}


def evaluate(plan, frame):
    tick = frame_tick(plan, frame)
    motions = {(m["target"]["kind"], m["target"]["id"], m["property"]):
               motion_value(m["keyframes"], tick) for m in plan["motions"]}
    active_cue, active_word = None, None
    progress = 0.0
    for cue in plan["cues"]:
        for word in cue["words"]:
            a = word["interval"]
            if a and a["start_tick"] <= tick < a["end_tick"]:
                active_cue, active_word = cue["id"], word["id"]
                progress = float((tick - a["start_tick"]) / (a["end_tick"] - a["start_tick"]))
                progress = motions.get(("word", word["id"], "highlight_progress"), progress)
    layers = {}
    cues = {c["id"]: c for c in plan["cues"]}
    policy = plan["policy"]["scroll"]
    for layer in plan["layers"]:
        if layer["kind"] != "lyrics":
            continue
        scroll = motions.get(("layer", layer["id"], "scroll_y_px"), layer["initial_scroll_y_px"])
        visible = []
        for cue_id in layer["cue_ids"]:
            cue = cues[cue_id]
            rect = cue["layout"]["block_rect"]
            y = rect["y"] - scroll
            if y + rect["height"] <= 0 or y >= layer["rect"]["height"]:
                continue
            distance = abs(layer["rect"]["y"] + y + rect["height"] / 2 - layer["active_anchor_y_px"])
            floor = policy["past_opacity_floor"] if tick >= cue["interval"]["end_tick"] else policy["future_opacity_floor"]
            alpha = 1 if cue_id == active_cue else floor + (1 - floor) * exp(-policy["falloff_k"] * distance / layer["rect"]["height"])
            alpha = motions.get(("cue", cue_id, "opacity"), alpha)
            alpha *= motions.get(("layer", layer["id"], "opacity"), layer["opacity"])
            visible.append({"id": cue_id, "y": y, "opacity": alpha})
        layers[layer["id"]] = {"scroll": scroll, "visible": visible}
    return {"tick": tick, "state": "ACTIVE" if active_word else "REST", "active_cue": active_cue,
            "active_word": active_word, "progress": progress, "layers": layers}
