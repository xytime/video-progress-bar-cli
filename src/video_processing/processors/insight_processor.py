"""洞察卡片、解说和高光缝合。依赖：processors → core/utils → config。

始终保留基础竖版，临时目录内完成渲染，验证后原子替换增强成片。
# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-06 | Codex | 四维增量、音画校验、输入绑定回执及失败回退 |
| 2.0.0 | 2026-10-08 | Antigravity | 落实 RFC-2026-DEEP-CREATION-001：InsightScriptV2 契约、100% 完整原片零裁切、全幅安全横栏(Y=265~555)、0.6s Dip to Black + 60Hz Hit 母带转场与三级收据系统 |
| 2.1.0 | 2026-10-08 | Antigravity | 绑定官方品牌图腾微标、受控真实二维码、Slogan与思辨投票选项渲染，增强三级收据深层校验 |
| 2.2.0 | 2026-10-08 | Antigravity | 接入火山引擎豆包语音 2.0 (Doubao Voice) 沉稳男声，并将转场音效升级为克制高级的 subtle_tape_swish，彻底消除炫耀感 |
| 2.2.1 | 2026-10-08 | Antigravity | 修复 receipt_data 中 tts_provider 字段在 Mock/自定义对象下的序列化异常 |
"""
import argparse
import hashlib
import json
import logging
import math
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from config.settings import settings
from video_processing.core.insight_script import InsightScript, InsightScriptV2
from video_processing.core.tts_engine import TTSEngine, TTSProvider
from video_processing.utils.video_metadata import _resolve_ffprobe_cmd, resolve_ffmpeg_cmd

logger = logging.getLogger(__name__)
WIDTH, HEIGHT = 1080, 1920


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe(path: Path) -> dict:
    result = subprocess.run(
        [_resolve_ffprobe_cmd(), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        check=True, capture_output=True, text=True, timeout=30,
    )
    return json.loads(result.stdout)


def duration(path: Path) -> float:
    value = float(probe(path)["format"]["duration"])
    if not math.isfinite(value) or value <= 0:
        raise ValueError("媒体时长无效")
    return value


def validate_media(path: Path, expected: float) -> None:
    data = probe(path)
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    audio = next(s for s in data["streams"] if s["codec_type"] == "audio")
    if (video["width"], video["height"], video["r_frame_rate"]) != (WIDTH, HEIGHT, "30/1"):
        raise ValueError("增强成片尺寸或帧率错误")
    if audio["sample_rate"] != "44100" or audio["channels"] != 2:
        raise ValueError("增强成片音频格式错误")
    if abs(float(data["format"]["duration"]) - expected) > 0.12:
        raise ValueError("增强成片时长不符")
    if abs(float(video["duration"]) - float(audio["duration"])) > 0.05:
        raise ValueError("音画尾点偏差超过 50ms")
    if abs(float(video.get("start_time", 0)) - float(audio.get("start_time", 0))) > 0.035:
        raise ValueError("音画起点偏差超过一帧")


def valid_enrichment(source: Path, script_path: Path, output: Path) -> bool:
    """检查脚本、声音、源成片和输出哈希，拒绝陈旧或损坏增强缓存。"""
    try:
        receipt_path = output.with_suffix(".receipt.json")
        if not receipt_path.is_file() or not output.is_file() or not source.is_file() or not script_path.is_file():
            return False
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        script_raw = script_path.read_text(encoding="utf-8")
        try:
            InsightScriptV2.model_validate_json(script_raw)
        except Exception:
            InsightScript.model_validate_json(script_raw)
        if receipt["voice"] != settings.insight_default_voice:
            return False
        for key, path in [("source_sha256", source), ("script_sha256", script_path),
                          ("output_sha256", output)]:
            if receipt.get(key) != sha256(path):
                return False
        # 三级收据深度指纹校验
        l1 = receipt.get("level1_manifest")
        if isinstance(l1, dict):
            if l1.get("source_sha256") != sha256(source) or l1.get("script_sha256") != sha256(script_path):
                return False
        l3 = receipt.get("level3_receipt")
        if isinstance(l3, dict):
            if l3.get("output_sha256") != sha256(output) or not l3.get("validate_media_passed"):
                return False
        validate_media(output, receipt["duration"])
        return True
    except Exception:
        return False


class InsightProcessor:
    def __init__(self, tts=None, runner=None):
        if tts is not None:
            self.tts = tts
        else:
            has_doubao = bool(getattr(settings, "doubao_tts_api_key", None) or getattr(settings, "volc_speech_api_key", None))
            use_doubao = getattr(settings, "tts_provider", "doubao").lower() == "doubao" and has_doubao
            self.tts = TTSEngine(TTSProvider.DOUBAO if use_doubao else TTSProvider.EDGE)
        self.runner = runner or subprocess.run

    @staticmethod
    def font(size: int):
        root = Path(__file__).resolve().parents[3]
        for candidate in [root / "assets/fonts/SourceHanSerifCN-Medium.otf",
                          Path("/System/Library/Fonts/Hiragino Sans GB.ttc"),
                          Path("/System/Library/Fonts/PingFang.ttc")]:
            if candidate.is_file():
                return ImageFont.truetype(str(candidate), size)
        raise FileNotFoundError("没有可用中文字体，拒绝生成缺字卡片")

    def render_intro_card(self, path: Path, title: str, narration: str):
        """渲染片头独占导读大卡 (1080x1920)。
        绑定官方「几何共振之眸」图腾微标、品牌名称「六维时空号」与主 Slogan「不同的视角，看见更大的世界。」。
        """
        image = Image.new("RGBA", (WIDTH, HEIGHT), (12, 18, 32, 255))
        glow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        ImageDraw.Draw(glow).ellipse((90, 200, 990, 1100), fill=(24, 45, 75, 120))
        image = Image.alpha_composite(image, glow.filter(ImageFilter.GaussianBlur(120)))
        draw = ImageDraw.Draw(image)

        root = Path(__file__).resolve().parents[3]
        logo_path = root / "assets/brand/01_logos/concept_a.png"
        if logo_path.is_file():
            logo = Image.open(logo_path).convert("RGBA").resize((110, 110), Image.Resampling.LANCZOS)
            image.paste(logo, (100, 190), mask=logo)

        draw.text((230, 205), "六维时空号", font=self.font(40), fill=(245, 197, 66))
        draw.text((230, 260), "不同的视角，看见更大的世界。", font=self.font(24), fill=(160, 185, 220))
        draw.line([100, 330, 980, 330], fill=(56, 189, 248, 100), width=2)

        # 核心内容卡片容器
        top, bottom = 370, 1480
        draw.rounded_rectangle([100, top, 980, bottom], radius=24, fill=(18, 26, 44, 255),
                               outline=(245, 197, 66, 200), width=2)
        draw.text((150, top + 45), "◆ 深度观察 · 独家导读", font=self.font(26), fill=(245, 197, 66))

        # 标题换行与渲染
        f_title = self.font(46)
        if draw.textlength(title, font=f_title) > 740:
            f_title = self.font(38)
        draw.text((150, top + 100), title, font=f_title, fill=(255, 255, 255))
        draw.line([150, top + 175, 930, top + 175], fill=(56, 189, 248, 80), width=1)

        # 导读口播正文折行渲染
        f_body = self.font(34)
        cur_y = top + 215
        line = ""
        for char in narration:
            if draw.textlength(line + char, font=f_body) > 720:
                if cur_y + f_body.size > bottom - 60:
                    raise ValueError("导读正文超出可读布局，拒绝截断")
                draw.text((150, cur_y), line, font=f_body, fill=(230, 240, 255))
                cur_y += 58
                line = char
            else:
                line += char
        if line:
            if cur_y + f_body.size > bottom - 60:
                raise ValueError("导读正文超出可读布局，拒绝截断")
            draw.text((150, cur_y), line, font=f_body, fill=(230, 240, 255))

        draw.text((150, bottom - 60), "六维时空号 · 深度智囊出品", font=self.font(22), fill=(140, 160, 190))
        image.save(path)

    def render_outro_card(self, path: Path, quote: str, question: str, poll_options: list[str] = None):
        """渲染片尾独占终章大卡 (1080x1920)。
        1:1 嵌入官方受控真实二维码 (内嵌地球仪头像) 并展示思辨哲学金句与互动议题选项。
        """
        image = Image.new("RGBA", (WIDTH, HEIGHT), (12, 18, 32, 255))
        glow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        ImageDraw.Draw(glow).ellipse((90, 300, 990, 1400), fill=(24, 45, 75, 120))
        image = Image.alpha_composite(image, glow.filter(ImageFilter.GaussianBlur(120)))
        draw = ImageDraw.Draw(image)

        # 1. 深度思辨内容卡片 (Y=180~1260)
        top, bottom = 180, 1260
        draw.rounded_rectangle([100, top, 980, bottom], radius=24, fill=(18, 26, 44, 255),
                               outline=(56, 189, 248, 180), width=2)
        draw.text((150, top + 40), "◆ 深度思辨 · 终章观察", font=self.font(26), fill=(245, 197, 66))

        # 哲学金句
        f_quote = self.font(38)
        cur_y = top + 95
        line = ""
        for char in quote:
            if draw.textlength(line + char, font=f_quote) > 720:
                draw.text((150, cur_y), line, font=f_quote, fill=(245, 197, 66))
                cur_y += 56
                line = char
            else:
                line += char
        if line:
            draw.text((150, cur_y), line, font=f_quote, fill=(245, 197, 66))
            cur_y += 75

        draw.line([150, cur_y, 930, cur_y], fill=(56, 189, 248, 80), width=1)
        cur_y += 35

        # 思辨问题
        f_q = self.font(32)
        line = ""
        for char in question:
            if draw.textlength(line + char, font=f_q) > 720:
                draw.text((150, cur_y), line, font=f_q, fill=(230, 240, 255))
                cur_y += 48
                line = char
            else:
                line += char
        if line:
            draw.text((150, cur_y), line, font=f_q, fill=(230, 240, 255))
            cur_y += 65

        # 互动投票选项 (A / B / C)
        if poll_options:
            prefixes = ["[A]", "[B]", "[C]"]
            for i, opt in enumerate(poll_options[:3]):
                opt_y = cur_y + i * 80
                if opt_y + 64 <= bottom - 20:
                    draw.rounded_rectangle([150, opt_y, 930, opt_y + 64], radius=12,
                                           fill=(28, 40, 68, 240), outline=(56, 189, 248, 120), width=1)
                    label = f"{prefixes[i]}  {opt}"
                    draw.text((180, opt_y + 14), label, font=self.font(28), fill=(240, 245, 255))

        # 2. 底部受控官方二维码卡片 (Y=1310~1710)
        qr_top, qr_bottom = 1310, 1710
        draw.rounded_rectangle([100, qr_top, 980, qr_bottom], radius=24, fill=(16, 24, 38, 240),
                               outline=(245, 197, 66, 180), width=2)

        root = Path(__file__).resolve().parents[3]
        qr_path = root / "assets/brand/05_qrcodes/liuwei-shikonghao-wechat-channels-code-source.jpeg"
        if qr_path.is_file():
            qr_img = Image.open(qr_path).convert("RGB").resize((190, 190), Image.Resampling.LANCZOS)
            qr_frame = Image.new("RGB", (206, 206), (255, 255, 255))
            qr_frame.paste(qr_img, (8, 8))
            image.paste(qr_frame, (140, qr_top + 95))

        draw.text((380, qr_top + 65), "扫码关注 · 六维时空号", font=self.font(34), fill=(245, 197, 66))
        draw.text((380, qr_top + 120), "微信视频号官方认证", font=self.font(24), fill=(56, 189, 248))
        draw.text((380, qr_top + 165), "不同的视角，看见更大的世界。", font=self.font(24), fill=(210, 225, 245))
        draw.text((380, qr_top + 215), "长按或扫码识别 · 获取更多独家深度洞察", font=self.font(20), fill=(140, 160, 190))

        image.save(path)

    def render_card(self, path: Path, title: str, paragraphs: list[str], *, overlay: bool = False,
                    badge: str = "", card_index: int = 1):
        """渲染认知透视卡。
        当 overlay=True 时生成 1080x1920 全幅透明底板，在 Y=265~555 处绘制不透明深蓝灰安全横栏
        及左侧 14px 发光指示条，彻底覆盖源视频日期水印，下方留出 1365px 避让人脸与双语字幕。
        """
        image = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0) if overlay else (15, 18, 24, 255))
        if not overlay:
            glow = Image.new("RGBA", image.size)
            ImageDraw.Draw(glow).ellipse((90, 260, 990, 1260), fill=(24, 45, 75, 150))
            image = Image.alpha_composite(image, glow.filter(ImageFilter.GaussianBlur(100)))
            draw = ImageDraw.Draw(image)
            top, bottom = 400, 1520
            draw.rounded_rectangle((60, top, 1020, bottom), radius=24,
                                   fill=(16, 24, 36, 240), outline=(240, 195, 90, 240), width=3)
            y = top + 40
            for index, text in enumerate([title, *paragraphs]):
                font = self.font(52 if index == 0 else 38)
                line = ""
                for char in text + "\n":
                    if char == "\n" or draw.textlength(line + char, font=font) > 860:
                        if y + font.size + 12 > bottom - 20:
                            raise ValueError("卡片正文超出可读布局，拒绝截断")
                        draw.text((100, y), line, font=font,
                                  fill=(240, 195, 90) if index == 0 else (230, 240, 255))
                        y += font.size + 12
                        line = "" if char == "\n" else char
                    else:
                        line += char
                y += 18
            image.save(path)
            return

        # ==================== Overlay 全幅安全横栏模式 (Y=265~555) ====================
        top, bottom = 265, 555
        draw = ImageDraw.Draw(image)
        # 1. 100% 不透明深度科技蓝灰底板，彻底遮盖源视频自带的发布日期水印戳
        draw.rectangle([0, top, WIDTH, bottom], fill=(12, 18, 32, 255))

        # 2. 左侧 14px 发光指示条与上下边界线
        if card_index == 2:
            indicator_color = (56, 189, 248, 255)  # 青蓝色
            border_color = (245, 197, 66, 220)     # 金黄色微边框
        else:
            indicator_color = (245, 197, 66, 255)  # 金黄色
            border_color = (56, 189, 248, 220)     # 青蓝色微边框

        draw.rectangle([0, top, 14, bottom], fill=indicator_color)
        draw.line([0, top, WIDTH, top], fill=border_color, width=2)
        draw.line([0, bottom, WIDTH, bottom], fill=border_color, width=2)

        # 3. 顶部标题与徽标
        font_title = self.font(31)
        if badge:
            header_text = f"◆ {badge} · {title}"
        else:
            header_text = f"◆ {title}" if not title.startswith("◆") else title

        # 标题长度防御
        if draw.textlength(header_text, font=font_title) > 960:
            font_title = self.font(26)
        draw.text((70, top + 33), header_text, font=font_title, fill=(245, 197, 66))

        # 4. 论据要点渲染 (每点 1 行或自动折行，严密控制在 Y=265~555 范围内)
        font_body = self.font(28)
        cur_y = top + 91  # 356
        for idx, text in enumerate(paragraphs):
            line_str = text
            if len(paragraphs) > 1 and not (line_str.startswith(f"{idx+1}.") or line_str.startswith("•")):
                line_str = f"{idx + 1}. {text}"

            # 布局溢出拦截
            if cur_y + font_body.size > bottom - 10:
                raise ValueError("卡片正文超出可读布局，拒绝截断")

            if draw.textlength(line_str, font=font_body) > 960:
                # 需折行
                wrapped_lines = []
                cur_line = ""
                for char in line_str:
                    if draw.textlength(cur_line + char, font=font_body) > 940:
                        wrapped_lines.append(cur_line)
                        cur_line = char
                    else:
                        cur_line += char
                if cur_line:
                    wrapped_lines.append(cur_line)

                for w_line in wrapped_lines:
                    if cur_y + font_body.size > bottom - 10:
                        raise ValueError("卡片正文超出可读布局，拒绝截断")
                    draw.text((70, cur_y), w_line, font=font_body, fill=(230, 240, 255))
                    cur_y += 36
                cur_y += 18
            else:
                draw.text((70, cur_y), line_str, font=font_body, fill=(230, 240, 255))
                cur_y += 58

        image.save(path)

    def run(self, args):
        self.runner([resolve_ffmpeg_cmd(), "-nostdin", "-v", "error", "-y", *args],
                    check=True, capture_output=True, timeout=900)

    @staticmethod
    def codecs():
        return ["-c:v", "libx264", "-preset", "fast", "-crf", "19", "-pix_fmt", "yuv420p",
                "-r", "30", "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "192k"]

    def bookend(self, card: Path, audio: Path, output: Path, *, is_intro: bool = True) -> float:
        """生成片头或片尾独占片段，支持 0.6s 电影级 Dip to Black 溶镜。"""
        seconds = math.ceil(duration(audio) * 30) / 30
        vf_filters = [
            "zoompan=z='min(zoom+0.0003,1.05)':d=1:s=1080x1920:fps=30,setsar=1",
        ]
        if is_intro:
            # 片尾 0.6s 淡出至纯黑
            fade_st = max(0.0, seconds - 0.6)
            vf_filters.append(f"fade=t=out:st={fade_st}:d=0.6")
            af_filter = f"aresample=44100,aformat=channel_layouts=stereo:sample_rates=44100,afade=t=out:st={fade_st}:d=0.6,apad"
        else:
            # 片头 0.6s 从纯黑淡入
            vf_filters.append("fade=t=in:st=0:d=0.6")
            af_filter = "aresample=44100,aformat=channel_layouts=stereo:sample_rates=44100,afade=t=in:st=0:d=0.6,apad"

        self.run(["-loop", "1", "-framerate", "30", "-i", str(card), "-i", str(audio),
                  "-vf", ",".join(vf_filters),
                  "-af", af_filter, "-t", str(seconds), *self.codecs(), str(output)])
        return seconds

    def process(self, source: Path, script_path: Path, output: Path) -> bool:
        try:
            source, script_path, output = Path(source), Path(script_path), Path(output)
            if source.resolve() == output.resolve():
                raise ValueError("基础成片不可被增强过程覆盖")

            raw_script_text = script_path.read_text(encoding="utf-8")
            is_v2 = False
            try:
                script = InsightScriptV2.model_validate_json(raw_script_text)
                is_v2 = True
            except Exception:
                script = InsightScript.model_validate_json(raw_script_text)

            source_dur = duration(source)
            preserve_full_body = is_v2 or getattr(script, "preserve_full_body", False)

            if is_v2:
                for c in script.cards:
                    if c.end_sec > source_dur:
                        raise ValueError(f"卡片时间窗 {c.end_sec}s 超出源成片 {source_dur}s")
            elif not preserve_full_body:
                window = script.highlight_window
                if window.end_sec > source_dur:
                    raise ValueError("高光时间窗超出源成片")

            output.parent.mkdir(parents=True, exist_ok=True)
            source_hash, script_hash = sha256(source), sha256(script_path)
            with tempfile.TemporaryDirectory(prefix="insight-", dir=output.parent) as directory:
                work = Path(directory)
                intro_card, outro_card = work / "intro.png", work / "outro.png"

                if is_v2:
                    hook_title = script.hook.title
                    hook_narration = script.hook.narration
                    outro_quote = script.outro.philosophical_quote
                    outro_narration = script.outro.tts_narration
                    outro_poll = script.outro.reflection_question
                    cards_list = script.cards
                else:
                    hook_title = script.hook_title
                    hook_narration = script.hook_narration
                    close = script.closing_takeaway
                    outro_quote = close.quote
                    outro_narration = close.narration
                    outro_poll = close.poll_topic
                    cards_list = script.context_cards

                if is_v2:
                    self.render_intro_card(intro_card, hook_title, hook_narration)
                    self.render_outro_card(outro_card, outro_quote, outro_poll, script.outro.poll_options)
                else:
                    self.render_card(intro_card, hook_title, [hook_narration], overlay=False)
                    self.render_card(outro_card, outro_quote, [outro_poll], overlay=False)

                segments = [work / f"seg{i}.mp4" for i in range(3)]
                lengths = []

                # 生成片头与片尾 TTS 配音及音视频片段 (44.1kHz)
                tts_prov = getattr(self.tts, "provider", None)
                is_doubao = tts_prov == TTSProvider.DOUBAO or tts_prov == "doubao"
                active_voice = (
                    getattr(settings, "doubao_tts_speaker", "zh_male_m191_uranus_bigtts")
                    if is_doubao
                    else settings.insight_default_voice
                )
                for index, (text, card, is_in) in enumerate([
                    (hook_narration, intro_card, True),
                    (outro_narration, outro_card, False),
                ]):
                    audio = work / f"voice{index}.mp3"
                    self.tts.generate_audio(text, audio, voice=active_voice)
                    seg_len = self.bookend(card, audio, segments[index * 2], is_intro=is_in)
                    lengths.append(seg_len)

                # 处理 Segment 1：原片正文 + 认知透视卡定时叠加 + 首尾 0.6s Dip to Black 溶镜
                inputs = ["-i", str(source)]
                if preserve_full_body:
                    # 100% 完整原片零裁切
                    core_duration = math.ceil(source_dur * 30) / 30
                    fade_out_st = max(0.0, core_duration - 0.6)
                    filters = [
                        f"[0:v]scale=1080:1920,setsar=1,fps=30,format=yuv420p,"
                        f"fade=t=in:st=0:d=0.6,fade=t=out:st={fade_out_st}:d=0.6[v0]",
                        f"[0:a]aresample=44100,aformat=channel_layouts=stereo:sample_rates=44100,"
                        f"afade=t=in:st=0:d=0.2,afade=t=out:st={fade_out_st}:d=0.6,apad[a]",
                    ]
                else:
                    # Legacy 裁切兼容
                    window = script.highlight_window
                    core_duration = math.ceil((window.end_sec - window.start_sec) * 30) / 30
                    filters = [
                        f"[0:v]trim=start={window.start_sec}:end={window.end_sec},setpts=PTS-STARTPTS,"
                        "scale=1080:1920,setsar=1,fps=30[v0]",
                        f"[0:a]atrim=start={window.start_sec}:end={window.end_sec},asetpts=PTS-STARTPTS,"
                        "aresample=44100,aformat=channel_layouts=stereo:sample_rates=44100,apad[a]",
                    ]

                for index, card in enumerate(cards_list, 1):
                    png = work / f"card{index}.png"
                    if is_v2:
                        badge = card.badge
                        card_title = card.title
                        points = [f"{p.keyword}：{p.explanation}" for p in card.points]
                        start_sec = card.start_sec
                        end_sec = card.end_sec
                    else:
                        badge = card.badge
                        card_title = card.badge
                        points = card.points
                        start_sec = card.trigger_sec
                        end_sec = card.trigger_sec + card.duration_sec

                    self.render_card(png, card_title, points, overlay=True, badge=badge, card_index=index)
                    inputs += ["-loop", "1", "-framerate", "30", "-i", str(png)]
                    card_dur = end_sec - start_sec
                    fade = min(0.5, card_dur / 2)
                    filters += [
                        f"[{index}:v]format=rgba,fade=t=in:st={start_sec}:d={fade}:alpha=1,"
                        f"fade=t=out:st={end_sec-fade}:d={fade}:alpha=1[c{index}]",
                        f"[v{index-1}][c{index}]overlay=0:0:enable='between(t,{start_sec},{end_sec})'[v{index}]",
                    ]

                last_v = f"[v{len(cards_list)}]"
                self.run([*inputs, "-filter_complex", ";".join(filters), "-map", last_v, "-map", "[a]",
                          "-t", str(core_duration), *self.codecs(), str(segments[1])])

                # 缝合三大段落并混流沉稳克制转场过渡音效
                assembled = work / "assembled.mp4"
                t_intro = lengths[0]
                t_main = core_duration
                t_outro = lengths[1]
                expected = t_intro + t_main + t_outro

                sfx_name = str(getattr(settings, "transition_sfx", "subtle_tape_swish")).lower()
                sfx_vol = float(getattr(settings, "transition_sfx_volume", 0.22))
                root_sfx = Path(__file__).resolve().parents[3] / "assets/audio/sfx"
                sfx_file_map = {
                    "subtle_tape_swish": root_sfx / "subtle_tape_swish.wav",
                    "gentle_warm_thud": root_sfx / "gentle_warm_thud.wav",
                    "cinema_hit_60hz": root_sfx / "cinema_hit_60hz_subbass.wav",
                }
                sfx_path = sfx_file_map.get(sfx_name)

                if sfx_name != "none" and sfx_path and sfx_path.is_file():
                    d1 = int(round(max(0.0, t_intro - 0.25) * 1000))
                    d2 = int(round(max(0.0, t_intro + t_main - 0.25) * 1000))
                    concat_filter = (
                        "[0:v]setsar=1[v0];[1:v]setsar=1[v1];[2:v]setsar=1[v2];"
                        "[v0][0:a][v1][1:a][v2][2:a]concat=n=3:v=1:a=1[cv][ca];"
                        f"[3:a]adelay={d1}|{d1},aresample=44100,volume={sfx_vol}[h1];"
                        f"[4:a]adelay={d2}|{d2},aresample=44100,volume={sfx_vol}[h2];"
                        "[ca][h1][h2]amix=inputs=3:duration=first:dropout_transition=0:normalize=0[aout]"
                    )
                    self.run([
                        "-i", str(segments[0]),
                        "-i", str(segments[1]),
                        "-i", str(segments[2]),
                        "-i", str(sfx_path),
                        "-i", str(sfx_path),
                        "-filter_complex", concat_filter,
                        "-map", "[cv]", "-map", "[aout]",
                        *self.codecs(), "-movflags", "+faststart", str(assembled),
                    ])
                else:
                    concat_filter = (
                        "[0:v]setsar=1[v0];[1:v]setsar=1[v1];[2:v]setsar=1[v2];"
                        "[v0][0:a][v1][1:a][v2][2:a]concat=n=3:v=1:a=1[cv][aout]"
                    )
                    self.run([
                        "-i", str(segments[0]),
                        "-i", str(segments[1]),
                        "-i", str(segments[2]),
                        "-filter_complex", concat_filter,
                        "-map", "[cv]", "-map", "[aout]",
                        *self.codecs(), "-movflags", "+faststart", str(assembled),
                    ])

                validate_media(assembled, expected)
                if source_hash != sha256(source) or script_hash != sha256(script_path):
                    raise ValueError("渲染期间输入发生变化")

                # 三级 SHA-256 收据系统 (Level 1 / Level 2 / Level 3)
                output_hash = sha256(assembled)
                prov = getattr(self.tts, "provider", None)
                if hasattr(prov, "value") and isinstance(prov.value, str):
                    provider_str = prov.value
                elif isinstance(prov, str):
                    provider_str = prov
                else:
                    provider_str = "custom"

                receipt_data = {
                    "source_sha256": source_hash,
                    "script_sha256": script_hash,
                    "output_sha256": output_hash,
                    "voice": str(active_voice),
                    "tts_provider": provider_str,
                    "transition_sfx": sfx_name,
                    "duration": expected,
                    "schema_version": "2.0.0" if is_v2 else "1.0.0",
                    "level1_manifest": {
                        "source_sha256": source_hash,
                        "script_sha256": script_hash,
                    },
                    "level2_segments": [
                        {"segment": "intro", "duration": t_intro, "sha256": sha256(segments[0])},
                        {"segment": "main", "duration": t_main, "sha256": sha256(segments[1])},
                        {"segment": "outro", "duration": t_outro, "sha256": sha256(segments[2])},
                    ],
                    "level3_receipt": {
                        "output_sha256": output_hash,
                        "duration": expected,
                        "sample_rate": 44100,
                        "validate_media_passed": True,
                    }
                }

                receipt = work / "receipt.json"
                receipt.write_text(json.dumps(receipt_data, ensure_ascii=False, indent=2), encoding="utf-8")
                assembled.replace(output)
                receipt.replace(output.with_suffix(".receipt.json"))
            return True
        except Exception as exc:
            logger.warning("[InsightFallback] 增强失败，保留基础成片：%s", exc)
            return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("script", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if not settings.enable_deep_insight_enrichment:
        return 1
    return 0 if InsightProcessor().process(args.source, args.script, args.output) else 1


if __name__ == "__main__":
    raise SystemExit(main())

