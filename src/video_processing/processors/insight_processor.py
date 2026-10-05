"""洞察卡片、解说和高光缝合。依赖：processors → core/utils → config。

始终保留基础竖版，临时目录内完成渲染，验证后原子替换增强成片。
# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-06 | Codex | 四维增量、音画校验、输入绑定回执及失败回退 |
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
from video_processing.core.insight_script import InsightScript
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
        receipt = json.loads(output.with_suffix(".receipt.json").read_text(encoding="utf-8"))
        InsightScript.model_validate_json(script_path.read_text(encoding="utf-8"))
        if receipt["voice"] != settings.insight_default_voice:
            return False
        for key, path in [("source_sha256", source), ("script_sha256", script_path),
                          ("output_sha256", output)]:
            if receipt[key] != sha256(path):
                return False
        validate_media(output, receipt["duration"])
        return True
    except Exception:
        return False


class InsightProcessor:
    def __init__(self, tts=None, runner=None):
        self.tts = tts or TTSEngine(TTSProvider.EDGE)
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

    def render_card(self, path: Path, title: str, paragraphs: list[str], *, overlay=False):
        image = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0) if overlay else (15, 18, 24, 255))
        if not overlay:
            glow = Image.new("RGBA", image.size)
            ImageDraw.Draw(glow).ellipse((90, 260, 990, 1260), fill=(24, 45, 75, 150))
            image = Image.alpha_composite(image, glow.filter(ImageFilter.GaussianBlur(100)))
        draw = ImageDraw.Draw(image)
        top, bottom = (240, 650) if overlay else (400, 1520)
        draw.rounded_rectangle((60, top, 1020, bottom), radius=24,
                               fill=(16, 24, 36, 240), outline=(240, 195, 90, 240), width=3)
        y = top + 40
        for index, text in enumerate([title, *paragraphs]):
            font = self.font(32 if overlay else (52 if index == 0 else 38))
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

    def run(self, args):
        self.runner([resolve_ffmpeg_cmd(), "-nostdin", "-v", "error", "-y", *args],
                    check=True, capture_output=True, timeout=900)

    @staticmethod
    def codecs():
        return ["-c:v", "libx264", "-preset", "fast", "-crf", "19", "-pix_fmt", "yuv420p",
                "-r", "30", "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "192k"]

    def bookend(self, card: Path, audio: Path, output: Path) -> float:
        seconds = math.ceil(duration(audio) * 30) / 30
        self.run(["-loop", "1", "-framerate", "30", "-i", str(card), "-i", str(audio),
                  "-vf", "zoompan=z='min(zoom+0.0003,1.05)':d=1:s=1080x1920:fps=30,setsar=1",
                  "-af", "aresample=44100,apad", "-t", str(seconds), *self.codecs(), str(output)])
        return seconds

    def process(self, source: Path, script_path: Path, output: Path) -> bool:
        try:
            source, script_path, output = Path(source), Path(script_path), Path(output)
            if source.resolve() == output.resolve():
                raise ValueError("基础成片不可被增强过程覆盖")
            script = InsightScript.model_validate_json(script_path.read_text(encoding="utf-8"))
            window = script.highlight_window
            if window.end_sec > duration(source):
                raise ValueError("高光时间窗超出源成片")
            output.parent.mkdir(parents=True, exist_ok=True)
            source_hash, script_hash = sha256(source), sha256(script_path)
            with tempfile.TemporaryDirectory(prefix="insight-", dir=output.parent) as directory:
                work = Path(directory)
                intro, outro = work / "intro.png", work / "outro.png"
                self.render_card(intro, script.hook_title, [script.hook_narration])
                close = script.closing_takeaway
                self.render_card(outro, close.quote, [close.poll_topic])
                segments = [work / f"seg{i}.mp4" for i in range(3)]
                lengths = []
                for index, (text, card) in enumerate([(script.hook_narration, intro), (close.narration, outro)]):
                    audio = work / f"voice{index}.mp3"
                    self.tts.generate_audio(text, audio, voice=settings.insight_default_voice)
                    lengths.append(self.bookend(card, audio, segments[index * 2]))
                inputs = ["-i", str(source)]
                core_duration = math.ceil((window.end_sec - window.start_sec) * 30) / 30
                filters = [
                    f"[0:v]trim=start={window.start_sec}:end={window.end_sec},setpts=PTS-STARTPTS,"
                    "scale=1080:1920,setsar=1,fps=30[v0]",
                    f"[0:a]atrim=start={window.start_sec}:end={window.end_sec},asetpts=PTS-STARTPTS,"
                    "aresample=44100,aformat=channel_layouts=stereo,apad[a]",
                ]
                for index, card in enumerate(script.context_cards, 1):
                    png = work / f"card{index}.png"
                    self.render_card(png, card.badge, card.points, overlay=True)
                    inputs += ["-loop", "1", "-framerate", "30", "-i", str(png)]
                    end = card.trigger_sec + card.duration_sec
                    fade = min(0.5, card.duration_sec / 2)
                    filters += [
                        f"[{index}:v]format=rgba,fade=t=in:st={card.trigger_sec}:d={fade}:alpha=1,"
                        f"fade=t=out:st={end-fade}:d={fade}:alpha=1[c{index}]",
                        f"[v{index-1}][c{index}]overlay=0:0:enable='between(t,{card.trigger_sec},{end})'[v{index}]",
                    ]
                self.run([*inputs, "-filter_complex", ";".join(filters), "-map", "[v2]", "-map", "[a]",
                          "-t", str(core_duration), *self.codecs(), str(segments[1])])
                assembled = work / "assembled.mp4"
                concat = []
                for index in range(3):
                    concat += [f"[{index}:v]setpts=PTS-STARTPTS[v{index}]",
                               f"[{index}:a]asetpts=PTS-STARTPTS[a{index}]"]
                concat += ["[v0][a0][v1][a1][v2][a2]concat=n=3:v=1:a=1[v][a]"]
                self.run([*(arg for segment in segments for arg in ["-i", str(segment)]),
                          "-filter_complex", ";".join(concat), "-map", "[v]", "-map", "[a]",
                          *self.codecs(), "-movflags", "+faststart", str(assembled)])
                expected = sum(lengths) + core_duration
                validate_media(assembled, expected)
                if source_hash != sha256(source) or script_hash != sha256(script_path):
                    raise ValueError("渲染期间输入发生变化")
                receipt = work / "receipt.json"
                receipt.write_text(json.dumps({"source_sha256": source_hash, "script_sha256": script_hash,
                    "output_sha256": sha256(assembled), "voice": settings.insight_default_voice,
                    "duration": expected}, ensure_ascii=False), encoding="utf-8")
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
