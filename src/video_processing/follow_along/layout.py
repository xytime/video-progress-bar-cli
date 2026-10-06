"""同一 FreeType 度量冻结字形和双语图集，不按英文词数切中文。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-07 | Codex | 冻结双语 rows、word boxes、正常/高亮图集与滚动 |
"""
from copy import deepcopy
from math import ceil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, __version__ as pillow_version
from .font_coverage import missing_characters

from .contracts import PipelineError, digest, fingerprint, local_path, tokens
from .timing import plan_scroll
from .chunking import partition


def rect(x, y, width, height):
    return {"x": x, "y": y, "width": max(0.01, width), "height": max(0.01, height)}


class LayoutCompiler:
    def __init__(self, root: Path):
        self.root = root

    def font(self, style, assets, text):
        asset = assets[style["font_asset_id"]]
        path = local_path(self.root, asset["uri"])
        face = asset.get("font_face_index", 0)
        missing = missing_characters(path, text, face)
        if missing:
            raise PipelineError("FONT_MISSING", f"字体缺字: {''.join(missing)}", [asset["id"]])
        if style["letter_spacing_px"] != 0 or any(style["shadow"][k] != 0 for k in ("dx", "dy", "blur_px")):
            raise PipelineError("INPUT_INVALID", "首版要求字距和模糊阴影为零；不忽略未支持样式")
        return ImageFont.truetype(str(path), size=round(style["font_size_px"]), index=face)

    @staticmethod
    def wrap(text, font, width, language, words=None, min_silence_tick=12000):
        atoms = list(tokens(text)) if language == "en" else None
        if language == "en" and words:
            def segment_span(i,j):
                a = words[i]["display_span"]["start"] if i else 0
                b = words[j]["display_span"]["start"] if j < len(words) else len(text)
                return a,b
            boundaries = [{**word, "boundary_punctuation": any(c in ",.;:!?" for c in text[word["display_span"]["end"]:words[index+1]["display_span"]["start"] if index+1 < len(words) else len(text)])}
                          for index,word in enumerate(words)]
            parts = partition(boundaries, width, lambda i,j: font.getlength(text[slice(*segment_span(i,j))].rstrip()), min_silence_tick)
            return [segment_span(i,j) for i,j in parts]
        spans = [(m.start(), m.end()) for m in atoms] if atoms is not None else [(i, i + 1) for i in range(len(text))]
        if not spans:
            raise PipelineError("LAYOUT_OVERFLOW", "没有可排版文字")
        rows, start, end = [], 0, 0
        for a, b in spans:
            candidate = text[start:b]
            if font.getlength(candidate) > width:
                if end <= start:
                    raise PipelineError("LAYOUT_OVERFLOW", f"不可分词超过可读宽度: {candidate}")
                rows.append((start, a))
                start = a
                if font.getlength(text[start:b]) > width:
                    raise PipelineError("LAYOUT_OVERFLOW", f"不可分词超过可读宽度: {text[start:b]}")
            end = b
        # 英文标点归属尾行，若增加视觉宽度仍需拒绝，不能丢弃标点。
        rows.append((start, len(text)))
        for a, b in rows:
            if font.getlength(text[a:b]) > width:
                raise PipelineError("LAYOUT_OVERFLOW", "含标点的文字超宽，需意群修订")
        return rows

    def compile(self, source, directory: Path):
        plan = deepcopy(source)
        assets = {a["id"]: a for a in plan["assets"]}
        styles = {s["id"]: s for s in plan["styles"]}
        lyrics = [l for l in plan["layers"] if l["kind"] == "lyrics"]
        if len(lyrics) != 1:
            raise PipelineError("INPUT_INVALID", "首版要求一个独立阅读窗口")
        layer = lyrics[0]
        width, viewport_height = int(layer["rect"]["width"]), layer["rect"]["height"]
        directory.mkdir(parents=True, exist_ok=True)
        policy = plan["policy"]["chunking"]
        y = viewport_height / 2
        for cue in plan["cues"]:
            if cue["id"] not in layer["cue_ids"]:
                raise PipelineError("INPUT_INVALID", "所有句须属于阅读窗口")
            if not cue["interval"] or any(w["timing_status"] not in {"observed", "manual"} or not w["interval"] for w in cue["words"]):
                raise PipelineError("ALIGNMENT_INCOMPLETE", "缺失/估算词界须人工复核", [cue["id"]])
            rows, fonts = [], {}
            local_y = 8.0
            for language, text, style_id, max_rows in (
                ("en", cue["english_text"], cue["english_style_id"], policy["max_en_rows"]),
                ("zh-CN", cue["translation"]["text"], cue["translation"]["style_id"], policy["max_zh_rows"]),
            ):
                style = styles[style_id]
                minimum = policy["min_en_font_px"] if language == "en" else policy["min_zh_font_px"]
                if style["font_size_px"] < minimum:
                    raise PipelineError("LAYOUT_OVERFLOW", "字号低于可读下限", [style_id])
                font = self.font(style, assets, text)
                fonts[style_id] = font
                spans = self.wrap(text, font, width - 24, language, cue["words"] if language == "en" else None, policy["min_silence_tick"])
                if len(spans) > max_rows:
                    raise PipelineError("TRANSLATION_MAPPING_MISSING", "意群太长；请提供子句双语映射，不能按比例拆译文", [cue["id"]])
                ascent, descent = font.getmetrics()
                if style["line_height_px"] < ascent + descent:
                    raise PipelineError("LAYOUT_OVERFLOW", "行高不足以容纳字体", [style_id])
                for a, b in spans:
                    row = {"language": language, "display_span": {"start": a, "end": b},
                           "rect": rect(12, y + local_y, font.getlength(text[a:b]), style["line_height_px"]),
                           "baseline_y_px": y + local_y + ascent, "style_id": style_id}
                    rows.append(row)
                    local_y += style["line_height_px"]
                local_y += 10
            height = ceil(local_y + 8)
            if height > min(viewport_height, policy["max_active_block_height_px"]):
                raise PipelineError("LAYOUT_OVERFLOW", "完整双语块超过活动区容量", [cue["id"]])
            atlas = Image.new("RGBA", (width * 2, height))
            draw = ImageDraw.Draw(atlas)
            for row in rows:
                style, font = styles[row["style_id"]], fonts[row["style_id"]]
                text = cue["english_text"] if row["language"] == "en" else cue["translation"]["text"]
                a, b = row["display_span"].values()
                for side, color in ((0, style["base_color"]), (width, style["active_color"])):
                    draw.text((12 + side, row["baseline_y_px"] - y), text[a:b], font=font,
                              fill=color, anchor="ls", stroke_width=round(style["stroke_width_px"]),
                              stroke_fill=style["stroke_color"])
                bbox = font.getbbox(text[a:b], anchor="ls", stroke_width=round(style["stroke_width_px"]))
                if bbox[0] + 12 < 0 or bbox[2] + 12 > width:
                    raise PipelineError("LAYOUT_OVERFLOW", "实际墨迹含描边溢出", [cue["id"]])
                if bbox[1] + row["baseline_y_px"] < y or bbox[3] + row["baseline_y_px"] > y + height:
                    raise PipelineError("LAYOUT_OVERFLOW", "实际字形高度溢出", [cue["id"]])
            for word in cue["words"]:
                word["glyph_boxes"] = []
                a, b = word["display_span"].values()
                for index, row in enumerate(rows):
                    if row["language"] != "en" or not row["display_span"]["start"] <= a < b <= row["display_span"]["end"]:
                        continue
                    font = fonts[row["style_id"]]
                    text = cue["english_text"]
                    # 前缀度量包含 kerning；墨迹由同一字体计算。
                    x = 12 + font.getlength(text[row["display_span"]["start"]:a])
                    advance = font.getlength(text[row["display_span"]["start"]:b]) - (x - 12)
                    box = font.getbbox(text[a:b], anchor="ls", stroke_width=round(styles[row["style_id"]]["stroke_width_px"]))
                    word["glyph_boxes"].append({"row_index": index, "display_span": word["display_span"],
                        "advance_rect": rect(x, row["rect"]["y"], advance, row["rect"]["height"]),
                        "ink_rect": rect(x + box[0], row["baseline_y_px"] + box[1], box[2] - box[0], box[3] - box[1])})
                if not word["glyph_boxes"]:
                    raise PipelineError("LAYOUT_OVERFLOW", "词未映射到冻结图集", [word["id"]])
            path = directory / f"{cue['id']}.png"
            atlas.save(path)
            cue["layout"] = {"coordinate_space": "lyrics_document_px", "block_rect": rect(0, y, width, height),
                "rows": rows, "atlas_ref": {"uri": str(path.relative_to(self.root)), "sha256": digest(path)},
                "metrics_fingerprint": fingerprint({"pillow": pillow_version, "styles": styles,
                                                      "fonts": [a["sha256"] for a in assets.values() if a["kind"] == "font"]})}
            y += height + 52
        layer["document_height_px"] = y + viewport_height / 2
        plan["motions"] = [m for m in plan["motions"] if not (m["target"] == {"kind": "layer", "id": layer["id"]} and m["property"] == "scroll_y_px")]
        plan["motions"].append(plan_scroll(plan, layer))
        plan["phase"] = "resolved"
        return plan
