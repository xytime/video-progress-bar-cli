# -*- coding: utf-8 -*-
"""自动生成字幕 CLI 命令 — 提供语音识别、翻译及烧录入口

# Modification History
| Version | Date       | Author                    | Description |
| ------- | ---------- | ------------------------- | ----------- |
| 1.0.0   | 2026-05-21 | Claude_Sonnet_4.6_Thinking | 初始创建，提供 cli 主入口与 edge/indextts 选择 |
| 1.1.0   | 2026-05-28 | Gemini_3.5_Flash_planning | 新增 --tts-cosy 参数，支持阿里云百炼 CosyVoice 配音服务，标有 # [Gemini_3.5_Flash_planning] |
| 1.1.1   | 2026-05-28 | Gemini_3.5_Flash_planning | 新增 --mute-original / --no-mute-original 参数，支持将原视频静音只保留 TTS，标注 # [Gemini_3.5_Flash_planning] |
| 1.2.0   | 2026-05-28 | Gemini_3.5_Flash_planning | 新增 --tts-volume 和 --tts-speech-rate 参数以控制音量与语速，标有 # [Gemini_3.5_Flash_planning] |
| 1.3.0   | 2026-05-28 | Gemini_2.5_Pro_planning  | 将 --tts-voice 默认值改为 "auto"，自动从精选播音音色池随机选取，标注 # [Gemini_2.5_Pro_planning] |
| 1.4.0   | 2026-06-25 | Claude_Opus_4.8 | 新增 --source-date 参数，透传源视频发布日期(YYYY-MM-DD)到 VerticalCaptionProcessor 渲染左上角毛玻璃日期戳 |
| 1.5.0   | 2026-07-17 | Codex | 当前无配音业务场景，移除全部 TTS CLI 入口 |
| 1.6.0   | 2026-08-27 | Codex | 增加原子阶段心跳文件，供父管线在子进程运行中报告真实进度 |
| 1.7.0   | 2026-09-03 | Codex | 心跳载荷记录阶段起点，允许父进程区分存活心跳与同阶段停滞。 |
"""
import click
from pathlib import Path
import logging
import json
import time
import threading
from video_processing.processors.caption_processor import AutoCaptionProcessor
from video_processing.processors.vertical_processor import VerticalCaptionProcessor
from video_processing.core.base import VideoProcessingError

logger = logging.getLogger(__name__)


class _CaptionProgressReporter:
    """以原子文件持续汇报当前字幕阶段，供父进程辨别存活与停滞。"""

    def __init__(self, progress_file: Path):
        self._progress_file = progress_file
        self._stage = "STARTING"
        self._stage_started_at = time.time()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def __call__(self, stage: str) -> None:
        with self._lock:
            if stage != self._stage:
                self._stage_started_at = time.time()
            self._stage = stage
        self._write_current()

    def start(self) -> None:
        self._write_current()
        self._thread = threading.Thread(target=self._heartbeat_loop, name="caption-progress", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1)

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(15):
            self._write_current()

    def _write_current(self) -> None:
        try:
            with self._lock:
                stage = self._stage
                stage_started_at = self._stage_started_at
            self._progress_file.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._progress_file.with_name(f".{self._progress_file.name}.tmp")
            temporary.write_text(
                json.dumps({
                    "stage": stage,
                    "stage_started_at": stage_started_at,
                    "updated_at": time.time(),
                }, ensure_ascii=False),
                encoding="utf-8",
            )
            temporary.replace(self._progress_file)
        except OSError as exc:
            logger.warning("Unable to write caption progress %s: %s", self._progress_file, exc)


def _build_progress_reporter(progress_file: Path | None):
    """返回可选的原子阶段上报回调；上报失败不影响字幕成片。"""
    if progress_file is None:
        return None

    return _CaptionProgressReporter(progress_file)

@click.command()
@click.argument('input_path', type=click.Path(exists=True, path_type=Path))
@click.option('--model', '-m', default="small", help='Whisper model size (tiny, base, small, medium, large)', show_default=True)
@click.option('--src-lang', default="en", help='Source language code (e.g. en)', show_default=True)
@click.option('--target-lang', default="zh-CN", help='Target language code for translation (e.g. zh-CN)', show_default=True)
@click.option('--device', default="cpu", help='Device to use (cpu, cuda, mps)', show_default=True)
@click.option('--style', default="default", help='Caption style (default, movie_yellow, tech_blue)', show_default=True)
@click.option('--output', '-o', type=click.Path(path_type=Path), help='Output file path')
# Vertical Layout Options
@click.option('--vertical', is_flag=True, help='Enable 9:16 vertical layout mode with 3 sections')
@click.option('--title', help='Custom title for vertical video. Defaults to filename if empty.')
@click.option('--bg-blur', is_flag=True, help='Use blurred video background instead of black (Vertical mode only)')
@click.option('--font-path', type=click.Path(path_type=Path), default="/Library/Fonts/Arial Unicode.ttf", show_default=True, help='Font file path for title/subtitles.')
@click.option('--font-size', type=int, default=84, show_default=True, help='Subtitle font size (Vertical mode only, default 84)')
@click.option('--bilingual', is_flag=True, help='Show bilingual subtitles (ZH+EN) in Vertical mode. Default is Chinese only.')
@click.option('--source-date', default=None, help='Source video publish date (YYYY-MM-DD) for the frosted date stamp in the top-left corner. Vertical mode only.')  # [Claude_Opus_4.8]
@click.option('--progress-file', type=click.Path(path_type=Path), default=None, help='Optional atomic stage heartbeat file for the parent pipeline.')
def auto_caption(input_path, model, src_lang, target_lang, device, style, output, vertical, title, bg_blur, font_path, font_size, bilingual, source_date, progress_file):
    """Generate and burn bilingual subtitles for a video."""
    progress_reporter = _build_progress_reporter(progress_file)
    if progress_reporter is not None:
        progress_reporter.start()
    try:
        if vertical:
            processor = VerticalCaptionProcessor(
                input_path=input_path,
                output_path=output,
                model_size=model,
                src_lang=src_lang,
                target_lang=target_lang,
                device=device,
                style=style,
                title=title,
                bg_blur=bg_blur,
                font_path=str(font_path),
                font_size=font_size,
                bilingual=bilingual,
                source_date=source_date,  # [Claude_Opus_4.8] 源视频发布日期毛玻璃戳
                progress_reporter=progress_reporter,
            )
            mode_str = "Vertical (9:16)"
        else:
            processor = AutoCaptionProcessor(
                input_path=input_path,
                output_path=output,
                model_size=model,
                src_lang=src_lang,
                target_lang=target_lang,
                device=device,
                style=style,
                progress_reporter=progress_reporter,
            )
            mode_str = "Standard"
        
        click.echo(f"Starting auto-captioning for: {input_path}")
        click.echo(f"Mode: {mode_str}")
        click.echo(f"Configuration: Model={model}, Src={src_lang}, Target={target_lang}, Device={device}, Style={style}")
        
        output_file = processor.process()
        
        click.echo(f"Success! Output saved to: {output_file}")
        
    except VideoProcessingError as e:
        logger.error(f"Processing error: {e}")
        click.echo(f"Error: {e}", err=True)
        raise click.Abort()
    except Exception as e:
        logger.exception("Unexpected error")
        click.echo(f"Unexpected error: {e}", err=True)
        raise click.Abort()
    finally:
        if progress_reporter is not None:
            progress_reporter.close()
