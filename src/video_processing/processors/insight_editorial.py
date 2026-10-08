"""财经纪录片版式：原片、字幕、洞察各占独立区域；不裁切或改写字幕。

绘制与时序在本模块，FFmpeg/TTS 的执行由调用方提供，避免依赖编排器。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.1 | 2026-10-09 | Codex | 标题均衡末行，数字与中文计量单位不拆分 |
"""
from functools import lru_cache
import math
import re
from pathlib import Path

import pysubs2
from PIL import Image, ImageDraw, ImageFont, ImageOps

WIDTH, HEIGHT = 1080, 1920
PAPER = (242, 238, 229)
INK = (25, 28, 28)
COPPER = (167, 108, 67)
VIDEO_Y, VIDEO_H = 360, 608
ASSETS = Path(__file__).resolve().parents[3] / "assets"
SERIF = ASSETS / "fonts/SourceHanSerifCN-Medium.otf"
SANS = Path("/System/Library/Fonts/Hiragino Sans GB.ttc")
QR = ASSETS / "brand/05_qrcodes/liuwei-shikonghao-wechat-channels-code-source.jpeg"
LOGO = ASSETS / "brand/01_logos/concept_a.png"


def resolve_inputs(source, original=None, subtitles=None):
    """只匹配当前片段的精确文件名，禁止将父视频误配给切片。"""
    source = Path(source)
    stem = source.stem.removesuffix("_vertical")
    roots = [source.parent, source.parent / "original_video"]
    if original is None:
        original = next((root / f"{stem}{ext}" for root in roots
                         for ext in (".mp4", ".mkv", ".webm", ".mov")
                         if (root / f"{stem}{ext}").is_file()
                         and (root / f"{stem}{ext}").resolve() != source.resolve()), None)
    if subtitles is None:
        subtitles = next((root / f"{stem}.ass" for root in roots
                          if (root / f"{stem}.ass").is_file()), None)
    if not original or not subtitles or not Path(original).is_file() or not Path(subtitles).is_file():
        raise ValueError("编辑版式需要对应原片及双语 ASS 字幕；保留普通成片")
    if Path(original).resolve() == source.resolve():
        raise ValueError("原片不能使用已烧录字幕的基础竖版")
    return Path(original), Path(subtitles)


@lru_cache(maxsize=32)
def font(size, serif=False):
    return ImageFont.truetype(str(SERIF if serif else SANS), size)


def wrap(text, size, width, serif=False, *, balanced=True):
    """按真实字宽折行，英文单词不拆分；不截断文本。"""
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    tokens = re.findall(r"[0-9]+(?:\.[0-9]+)?(?:个月|小时|分钟|秒|年|天|美元|元|%|％)|[A-Za-z0-9]+(?:['’.-][A-Za-z0-9]+)*[%％]?|[^A-Za-z0-9]", text)
    joined = []
    for token in tokens:
        if joined and token in "，。！？；：、,.!?;%％）】》」』":
            joined[-1] += token
        else:
            joined.append(token)
    lines, line = [], ""
    for token in joined:
        if token == "\n":
            lines.append(line.rstrip())
            line = ""
        elif line and measure.textlength(line + token, font=font(size, serif)) > width:
            lines.append(line.rstrip())
            line = token.lstrip()
        else:
            line += token
        if measure.textlength(line, font=font(size, serif)) > width:
            raise ValueError("单词超出版面宽度")
    if line.strip():
        lines.append(line.rstrip())
    # 中文末行不孤留百分号或一两个字；采用均衡行宽，保持词组与数字原样。
    if (balanced and "\n" not in text and len(lines) > 1
            and measure.textlength(lines[-1], font=font(size, serif)) < width * .3
            and re.search(r"[\u3400-\u9fff]", text)):
        target = min(width, measure.textlength(text, font=font(size, serif)) / len(lines) + size)
        candidate = wrap(text, size, target, serif, balanced=False)
        if len(candidate) == len(lines):
            lines = candidate
    return lines


def text_block(draw, text, xy, width, height, size, *, serif=False, color=INK):
    lines = wrap(text, size, width, serif)
    step = round(size * 1.4)
    if step * len(lines) > height:
        raise ValueError(f"文字超出可读区域：{text[:24]}")
    for i, line in enumerate(lines):
        draw.text((xy[0], xy[1] + i * step), line, font=font(size, serif), fill=color, anchor="lt")
    return len(lines) * step


def brand(image, y=110, *, dark=False):
    draw = ImageDraw.Draw(image)
    color = PAPER if dark else INK
    logo = Image.open(LOGO).convert("RGBA")
    logo.thumbnail((52, 52), Image.Resampling.LANCZOS)
    image.paste(logo, (76, y - 8), logo)
    draw.text((150, y), "六维时空号", font=font(30), fill=color, anchor="lt")
    draw.text((720, y + 4), "深度观察", font=font(24), fill=COPPER, anchor="lt")


def render_body(path, script):
    image = Image.new("RGB", (WIDTH, HEIGHT), PAPER)
    brand(image, 66)
    draw = ImageDraw.Draw(image)
    text_block(draw, script.headline, (76, 151), 912, 182, 62, serif=True)
    draw.line((76, 1400, 988, 1400), fill=COPPER, width=2)
    draw.text((76, 1788), "不同的视角，看见更大的世界。", font=font(28), fill=INK, anchor="lt")
    image.save(path)


def render_intro(path, title, photograph):
    image = Image.new("RGB", (WIDTH, HEIGHT), INK)
    photo = Image.open(photograph).convert("RGB")
    # 仅片头摄影允许构图；正文从不裁切。
    photo = ImageOps.fit(photo, (WIDTH, 1080), centering=(0.5, 0.3))
    image.paste(photo, (0, 0))
    shade = Image.new("RGBA", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(shade)
    for y in range(HEIGHT):
        alpha = int(190 * (1 - y / 280)) if y < 280 else int(255 * min(1, max(0, (y - 620) / 450)))
        draw.line((0, y, WIDTH, y), fill=(*INK, alpha))
    image = Image.alpha_composite(image.convert("RGBA"), shade)
    brand(image, 94, dark=True)
    draw = ImageDraw.Draw(image)
    draw.text((76, 1060), "本期观察", font=font(30), fill=COPPER, anchor="lt")
    title_size = 92 if len(wrap(title, 92, 900, True)) <= 2 else 84
    text_block(draw, title, (76, 1150), 900, 360, title_size, serif=True, color=PAPER)
    draw.line((76, 1570, 164, 1570), fill=COPPER, width=4)
    draw.text((76, 1810), "不同的视角，看见更大的世界。", font=font(28), fill=PAPER, anchor="lt")
    image.save(path)


def render_outro(path, outro):
    image = Image.new("RGB", (WIDTH, HEIGHT), PAPER)
    brand(image)
    draw = ImageDraw.Draw(image)
    draw.text((76, 257), "留一个问题", font=font(30), fill=COPPER, anchor="lt")
    text_block(draw, outro.reflection_question, (76, 350), 912, 440, 76, serif=True)
    for i, option in enumerate(outro.poll_options):
        y = 842 + i * 85
        draw.text((76, y), f"0{i + 1}", font=font(27), fill=COPPER, anchor="lt")
        text_block(draw, option, (157, y - 5), 820, 70, 40)
    text_block(draw, outro.comment_invitation, (76, 1155), 912, 72, 40, color=COPPER)
    draw.line((76, 1280, 988, 1280), fill=(210, 199, 185), width=2)
    text_block(draw, outro.philosophical_quote, (76, 1340), 912, 150, 34)
    # 保留完整微信视频号码，不将它当作可由普通 QR 解码器解析的二维码。
    qr = ImageOps.contain(Image.open(QR).convert("RGB"), (228, 228))
    plate = Image.new("RGB", (260, 260), "white")
    plate.paste(qr, ((260 - qr.width) // 2, (260 - qr.height) // 2))
    image.paste(plate, (76, 1540))
    draw.text((380, 1580), "六维时空号", font=font(38), fill=INK, anchor="lt")
    text_block(draw, "不同的视角，\n看见更大的世界。", (380, 1652), 580, 110, 30)
    image.save(path)


def ass_file():
    result = pysubs2.SSAFile()
    result.info.update(PlayResX="1080", PlayResY="1920", WrapStyle="2")
    result.styles["Default"] = pysubs2.SSAStyle(
        fontname="Hiragino Sans GB", fontsize=42, primarycolor=pysubs2.Color(*INK),
        outline=0, shadow=0, alignment=pysubs2.Alignment.TOP_LEFT, marginl=0, marginr=0, marginv=0)
    return result


def add_text(subs, text, start, end, x, y, width, height, size, *, color=None):
    lines = wrap(text, size, width)
    step = round(size * 1.4)
    if step * len(lines) > height:
        raise ValueError(f"字幕或洞察超出可读区域：{text[:24]}")
    # 独立行定位，避免 libass 的字体行高与 Pillow 测量差异造成覆盖。
    for i, line in enumerate(lines):
        safe = line.replace("\\", "＼").replace("{", "｛").replace("}", "｝")
        c = "" if color is None else rf"\c&H{color[2]:02X}{color[1]:02X}{color[0]:02X}&"
        subs.append(pysubs2.SSAEvent(start=round(start * 1000), end=round(end * 1000),
            text=rf"{{\an7\pos({x},{y+i*step})\fs{size}{c}}}" + safe))


def bilingual_events(path, body_duration):
    """兼容当前复合双语 ASS；重置旧版字号和定位，保留台词与时码。"""
    source = pysubs2.load(str(path), format_="ass")
    result = []
    for event in source:
        if event.is_comment or event.style == "GlossaryCard":
            continue
        lines = [s.strip() for s in event.plaintext.splitlines() if s.strip()]
        # 当前渲染器以空行分隔语言；找首个中文行，对专有名词英文保留原序。
        split = next((i for i, line in enumerate(lines) if re.search(r"[\u3400-\u9fff]", line)), None)
        if split is None or split == 0:
            raise ValueError("无法无损识别双语 ASS，保留普通成片")
        if event.start < 0 or event.end > (body_duration + .12) * 1000 or event.end <= event.start:
            raise ValueError("双语字幕时码与对应原片不符")
        en = " ".join(lines[:split])
        zh = "".join(lines[split:])
        result.append((event.start / 1000, event.end / 1000, en, zh))
    if not result:
        raise ValueError("没有可复用双语字幕")
    return result


def write_body_subtitles(path, original_ass, script, body_duration):
    subs = ass_file()
    for start, end, en, zh in bilingual_events(original_ass, body_duration):
        # 字体保持可读下限，过长台词分成同步分页而不删字。
        en_lines, zh_lines = wrap(en, 38, 912), wrap(zh, 46, 912)
        pages = max(math.ceil(len(en_lines) / 3), math.ceil(len(zh_lines) / 2))
        for page in range(pages):
            t0 = start + (end - start) * page / pages
            t1 = start + (end - start) * (page + 1) / pages
            # 均匀分配两种语言行，避免尾页一种语言消失。
            e = en_lines[len(en_lines)*page//pages:len(en_lines)*(page+1)//pages]
            z = zh_lines[len(zh_lines)*page//pages:len(zh_lines)*(page+1)//pages]
            if not e or not z or t1 - t0 < .7:
                raise ValueError("双语字幕过密，无法在保留全部文字时保证可读")
            add_text(subs, "\n".join(e), t0, t1, 76, 1008, 912, 162, 38)
            add_text(subs, "\n".join(z), t0, t1, 76, 1194, 912, 132, 46)
    manifest = []
    for index, card in enumerate(script.cards):
        for p, point in enumerate(card.points):
            start = card.start_sec + (card.end_sec - card.start_sec) * p / 3
            end = card.start_sec + (card.end_sec - card.start_sec) * (p + 1) / 3
            add_text(subs, f"{card.badge}   /   {p+1:02d} — 03", start, end, 76, 1440, 912, 46, 28, color=COPPER)
            add_text(subs, card.title, start, end, 76, 1494, 912, 64, 32 if len(wrap(card.title, 40, 912)) > 1 else 40)
            add_text(subs, point.keyword, start, end, 76, 1568, 912, 67, 46, color=COPPER)
            add_text(subs, point.explanation, start, end, 76, 1636, 912, 128, 42)
            manifest.append({"card_id": card.card_id, "point": p+1, "start": start, "end": end,
                             "keyword": point.keyword, "explanation": point.explanation})
    subs.save(str(path))
    return manifest


def subtitle_filter(path):
    # FFmpeg filtergraph quoting与shell quoting是不同层；路径只进入argv，不经shell。
    escaped = str(path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "'\\''")
    return f"subtitles=filename='{escaped}'"


def render_segments(processor, script, original, original_ass, work, body_duration, voice, get_duration):
    segments = [work / f"seg{i}.mp4" for i in range(3)]
    poster = work / "poster.png"
    processor.run(["-ss", str(min(1, body_duration / 2)), "-i", str(original), "-frames:v", "1", str(poster)])
    intro, outro, body = [work / f"{name}.png" for name in ("intro", "outro", "body")]
    render_intro(intro, script.hook.title, poster)
    render_outro(outro, script.outro)
    render_body(body, script)
    body_ass = work / "body.ass"
    points = write_body_subtitles(body_ass, original_ass, script, body_duration)
    lengths = []
    for i, (text, card) in enumerate(((script.hook.narration, intro), (script.outro.tts_narration, outro))):
        # TTS 无时间戳：按短句合成并测量实际音长，字幕与句级音频严格绑定。
        clauses = re.findall(r"[^，。！？；、!?;]+[，。！？；、!?;]*", text)
        chunks = [chunk for clause in clauses
                  for chunk in ([clause] if len(wrap(clause, 46, 912)) <= 2 else wrap(clause, 46, 912))]
        audio_inputs, labels, offset = [], [], 0.0
        speech_subs = ass_file()
        for n, chunk in enumerate(chunks):
            audio = work / f"voice-{i}-{n}.wav"
            processor.tts.generate_audio(chunk, audio, voice=voice)
            seconds = get_duration(audio)
            audio_inputs += ["-i", str(audio)]
            labels.append(f"[{n}:a]aresample=44100,aformat=channel_layouts=stereo:sample_rates=44100[a{n}]")
            if i == 0:
                add_text(speech_subs, chunk, offset, offset + seconds, 76, 1630, 912, 153, 46, color=PAPER)
            offset += seconds
        labels.append("".join(f"[a{n}]" for n in range(len(chunks))) + f"concat=n={len(chunks)}:v=0:a=1[a]")
        merged = work / f"voice-{i}.wav"
        processor.run([*audio_inputs, "-filter_complex", ";".join(labels), "-map", "[a]", "-c:a", "pcm_s16le", str(merged)])
        seconds = math.ceil((offset + .45) * 30) / 30
        vf = "setsar=1"
        if i == 0:
            subpath = work / "intro.ass"
            speech_subs.save(str(subpath))
            vf += "," + subtitle_filter(subpath)
        # 不缩放整张画面，保留品牌码静区；不淡出人声尾字。
        processor.run(["-loop", "1", "-framerate", "30", "-i", str(card), "-i", str(merged),
                       "-vf", vf, "-af", "apad", "-t", str(seconds), *processor.codecs(), str(segments[i*2])])
        lengths.append(seconds)
    core_duration = math.ceil(body_duration * 30) / 30
    filters = (f"[0:v]setpts=PTS-STARTPTS,scale=1080:{VIDEO_H}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
               f"pad=1080:{VIDEO_H}:(ow-iw)/2:(oh-ih)/2:color=0xF2EEE5,setsar=1,fps=30[raw];"
               f"[1:v][raw]overlay=0:{VIDEO_Y}:shortest=1,{subtitle_filter(body_ass)}[v];"
               "[0:a]asetpts=PTS-STARTPTS,aresample=44100,aformat=channel_layouts=stereo:sample_rates=44100,apad[a]")
    processor.run(["-i", str(original), "-loop", "1", "-framerate", "30", "-i", str(body),
                   "-filter_complex", filters, "-map", "[v]", "-map", "[a]", "-t", str(core_duration),
                   *processor.codecs(), str(segments[1])])
    return segments, lengths, core_duration, points
