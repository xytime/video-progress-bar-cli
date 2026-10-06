"""冻结 RGBA 图集 + 单 FFmpeg 编码；内存不随帧总数增长。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-07 | Codex | 单进程原声合成、圆角人物窗与逐词 sweep |
"""
import subprocess
import threading
from pathlib import Path

from PIL import Image, ImageDraw

from .contracts import PipelineError, verify_ref
from .layout import LayoutCompiler
from .timing import evaluate, frame_count


class Renderer:
    def __init__(self, tools):
        self.tools = tools

    def render(self, plan, root: Path, master: Path, directory: Path):
        width, height = plan["canvas"]["width"], plan["canvas"]["height"]
        assets = {a["id"]: a for a in plan["assets"]}
        styles = {s["id"]: s for s in plan["styles"]}
        cues = {c["id"]: c for c in plan["cues"]}
        video_layers = [l for l in plan["layers"] if l["kind"] == "video"]
        if len(video_layers) != 1:
            raise PipelineError("INPUT_INVALID", "首版须一个人物图层")
        performer = video_layers[0]
        track = next(t for t in plan["tracks"] if t["id"] == performer["track_id"])
        if track["role"] != "performer" or len(track["clips"]) != 1:
            raise PipelineError("INPUT_INVALID", "首版人物轨仅支持单个 clip")
        clip = track["clips"][0]
        if clip["timeline_interval"] != {"start_tick": 0, "end_tick": plan["metadata"]["duration_tick"]}:
            raise PipelineError("SOURCE_MAPPING_AMBIGUOUS", "人物 clip 必须覆盖完整成片")
        if performer["opacity"] != 1 or performer["visible_interval"] != clip["timeline_interval"]:
            raise PipelineError("INPUT_INVALID", "首版人物图层须全程可见且 opacity=1")
        video_path = verify_ref(root, assets[clip["asset_id"]])
        box = performer["rect"]
        crop = performer["crop"]
        if crop["fit"] != "cover":
            raise PipelineError("INPUT_INVALID", "首版人物窗口采用 cover")
        padding = round(crop["padding_px"])
        vw, vh = round(box["width"]) - 2 * padding, round(box["height"]) - 2 * padding
        if vw <= 0 or vh <= 0:
            raise PipelineError("LAYOUT_OVERFLOW", "人物 padding 无有效画面")
        mask = Image.new("L", (vw, vh))
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, vw - 1, vh - 1), radius=crop["corner_radius_px"], fill=255)
        mask_path = directory / "performer-mask.png"
        mask.save(mask_path)
        base = Image.new("RGBA", (width, height), plan["canvas"]["background"])
        compiler = LayoutCompiler(root)
        for layer in sorted(plan["layers"], key=lambda l: l["z_index"]):
            if layer["kind"] != "text":
                continue
            if layer["visible_interval"] != clip["timeline_interval"] or layer["opacity"] != 1 or layer["text_align"] != "left":
                raise PipelineError("INPUT_INVALID", "首版 header 须全程、左对齐、opacity=1")
            style = styles[layer["style_id"]]
            font = compiler.font(style, assets, layer["text"])
            bbox = font.getbbox(layer["text"], anchor="lt", stroke_width=round(style["stroke_width_px"]))
            r = layer["rect"]
            if bbox[2] - bbox[0] > r["width"] or bbox[3] - bbox[1] > r["height"]:
                raise PipelineError("LAYOUT_OVERFLOW", "静态标题/目标文字溢出", [layer["id"]])
            ImageDraw.Draw(base).text((r["x"] - bbox[0], r["y"] - bbox[1]), layer["text"], font=font,
                                     anchor="lt", fill=style["base_color"], stroke_width=round(style["stroke_width_px"]), stroke_fill=style["stroke_color"])
        # 图集按可见块加载；不预载整段音视频或所有帧。
        atlas_cache = {}
        fps = plan["clock"]["fps"]
        rate = f"{fps['numerator']}/{fps['denominator']}"
        ticks = plan["clock"]["ticks_per_second"]
        start, end = (clip["source_interval"][k] / ticks for k in ("start_tick", "end_tick"))
        graph = (f"[1:v]trim=start={start}:end={end},setpts=PTS-STARTPTS,"
                 f"scale={vw}:{vh}:force_original_aspect_ratio=increase,"
                 f"crop={vw}:{vh}:(iw-ow)*{crop['focus_x']}:(ih-oh)*{crop['focus_y']},setsar=1,format=rgba[clip];"
                 "[3:v]format=gray[mask];[clip][mask]alphamerge[rounded];"
                 f"[0:v][rounded]overlay=x={round(box['x']) + padding}:y={round(box['y']) + padding}:eof_action=pass,format=yuv420p[v]")
        output = directory / "video.mp4"
        args = [self.tools.ffmpeg, "-hide_banner", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{width}x{height}",
                "-r", rate, "-i", "pipe:0", "-i", str(video_path), "-i", str(master), "-loop", "1", "-i", str(mask_path),
                "-filter_complex", graph, "-map", "[v]", "-map", "2:a:0", "-frames:v", str(frame_count(plan)),
                "-t", str(plan["metadata"]["duration_tick"] / ticks), "-r", rate, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(output)]
        with (directory / "render.log").open("wb") as log:
            process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log)
            timer = threading.Timer(self.tools.timeout, process.kill)
            timer.start()
            try:
                for frame_index in range(frame_count(plan)):
                    state = evaluate(plan, frame_index)
                    image = base.copy()
                    used = set()
                    for layer in plan["layers"]:
                        if layer["kind"] != "lyrics":
                            continue
                        interval = layer["visible_interval"]
                        if not interval["start_tick"] <= state["tick"] < interval["end_tick"]:
                            continue
                        viewport = Image.new("RGBA", (round(layer["rect"]["width"]), round(layer["rect"]["height"])))
                        for item in state["layers"][layer["id"]]["visible"]:
                            cue = cues[item["id"]]
                            used.add(cue["id"])
                            if cue["id"] not in atlas_cache:
                                with Image.open(verify_ref(root, cue["layout"]["atlas_ref"])) as loaded:
                                    atlas_cache[cue["id"]] = loaded.convert("RGBA")
                            atlas = atlas_cache[cue["id"]]
                            cw = atlas.width // 2
                            block = atlas.crop((0, 0, cw, atlas.height))
                            if cue["id"] == state["active_cue"]:
                                # 中文只按句强调；英文仅高亮当前有声词。
                                top = cue["layout"]["block_rect"]["y"]
                                for row in cue["layout"]["rows"]:
                                    if row["language"] == "zh-CN":
                                        y = round(row["rect"]["y"] - top)
                                        h = round(row["rect"]["height"])
                                        block.paste(atlas.crop((cw, y, 2*cw, y+h)), (0, y))
                                word = next(w for w in cue["words"] if w["id"] == state["active_word"])
                                for glyph in word["glyph_boxes"]:
                                    r = glyph["ink_rect"]
                                    x, y = max(0, int(r["x"])), max(0, int(r["y"] - top))
                                    amount = 1 if word["highlight"]["mode"] == "whole_word" else state["progress"]
                                    right = min(cw, round(r["x"] + r["width"] * amount))
                                    bottom = min(atlas.height, round(r["y"] - top + r["height"]))
                                    if right > x and bottom > y:
                                        block.paste(atlas.crop((cw+x, y, cw+right, bottom)), (x, y))
                            block.putalpha(block.getchannel("A").point(lambda a: round(a * item["opacity"])))
                            viewport.alpha_composite(block, (0, round(item["y"])))
                        edge = Image.new("L", (1, viewport.height))
                        edge.putdata([round(255 * min(1, y/30, (viewport.height-1-y)/30)) for y in range(viewport.height)])
                        from PIL import ImageChops
                        viewport.putalpha(ImageChops.multiply(viewport.getchannel("A"), edge.resize(viewport.size)))
                        image.alpha_composite(viewport, (round(layer["rect"]["x"]), round(layer["rect"]["y"])))
                    atlas_cache = {k: v for k, v in atlas_cache.items() if k in used}
                    process.stdin.write(image.tobytes())
                process.stdin.close()
                code = process.wait(timeout=self.tools.timeout)
                if code:
                    raise PipelineError("RENDER_FAILED", f"编码器退出 {code}，见 render.log")
            except (BrokenPipeError, subprocess.TimeoutExpired) as exc:
                raise PipelineError("RENDER_FAILED", "编码管道中断/超时，见 render.log") from exc
            finally:
                timer.cancel()
                if process.poll() is None:
                    process.kill()
                if not process.stdin.closed:
                    try:
                        process.stdin.close()
                    except BrokenPipeError:
                        pass
                process.wait()
        return output
