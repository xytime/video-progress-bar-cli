# -*- coding: utf-8 -*-
"""自动生成字幕 CLI 命令 — 提供语音识别、翻译及烧录入口

# Modification History
| Version | Date       | Author                    | Description |
| ------- | ---------- | ------------------------- | ----------- |
| 1.10.0 | 2026-10-29 | Codex | 独立阶段证据与继承资源上下文；翻译可让出重计算槽。 |
| 1.10.1 | 2026-10-29 | Codex | 字幕 CLI 只计子阶段，继承规范任务身份，避免重复计整片尝试。 |
| 1.9.0 | 2026-10-27 | Codex | 具名字幕失败/成功回执，临时服务故障与待修复分别退出。 |
| 1.9.0 | 2026-10-27 | Codex | 普通流水线可在翻译前分流原片中文字幕，独立制作默认不启用。 |
| 1.8.0 | 2026-10-23 | Codex | 心跳保留已复用步骤，让字幕定位/渲染与转录分开展示。 |
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
import hashlib
import uuid
from config.settings import settings
from video_processing.processors.caption_processor import AutoCaptionProcessor
from video_processing.processors.vertical_processor import VerticalCaptionProcessor
from video_processing.core.base import VideoProcessingError
from video_processing.utils.subtitle_failure_receipt import (
    SubtitleTranslationFailure, write_failure_receipt, write_success_receipt,
)

from video_processing.core.ffmpeg_slot import wait_state as _ffmpeg_wait_state
from video_processing.core.preparation_resources import (setup_execution_context, resource_stage,
                                                         PreparationYielded, PreparationBusy)
from video_processing.core.preparation_resources import wait_state as _preparation_wait_state
from video_processing.utils.preparation_artifacts import isolated_caption_artifacts
from video_processing.utils.stage_events import StageJournal, bind_journal, canonical_task_id

logger = logging.getLogger(__name__)


def wait_state():
    """同一执行线程的资源等待；心跳继续，等待不计入阶段无进展限时。"""
    ffmpeg, preparation = _ffmpeg_wait_state(), _preparation_wait_state()
    return dict(waiting=ffmpeg['waiting'] or preparation['waiting'],
                seconds=ffmpeg['seconds'] + preparation['seconds'])


class _CaptionProgressReporter:
    """以原子文件持续汇报当前字幕阶段，供父进程辨别存活与停滞。"""

    def __init__(self, progress_file: Path, journal: StageJournal | None = None):
        self._progress_file = progress_file
        self._journal = journal
        self._stage = "STARTING"
        self.reused_steps = set()
        self._stage_started_at = time.time()
        self._stage_wait_baseline = wait_state()["seconds"]
        self._process_wait_baseline = self._stage_wait_baseline
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def __call__(self, stage: str) -> None:
        if self._journal is not None:
            self._journal.transition(stage)
        with self._lock:
            if stage != self._stage:
                self._stage_started_at = time.time()
                self._stage_wait_baseline = wait_state()["seconds"]
            self._stage = stage
            if stage in {'ASR_REUSED', 'TRANSLATION_REUSED'}:
                self.reused_steps.add('asr' if stage == 'ASR_REUSED' else 'translation')
        self._write_current()

    def start(self) -> None:
        if self._journal is not None:
            self._journal.transition(self._stage)
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
                reused_steps = sorted(self.reused_steps)
                stage_started_at = self._stage_started_at
                waiting = wait_state()
                stage_started_at += max(0, waiting["seconds"] - self._stage_wait_baseline)
            self._progress_file.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._progress_file.with_name(f".{self._progress_file.name}.tmp")
            temporary.write_text(
                json.dumps({
                    "stage": stage,
                    "reused_steps": reused_steps,
                    "stage_started_at": stage_started_at,
                    "updated_at": time.time(),
                    "resource_waiting": waiting["waiting"],
                    "resource_wait_seconds": max(0, waiting["seconds"] - self._process_wait_baseline),
                }, ensure_ascii=False),
                encoding="utf-8",
            )
            temporary.replace(self._progress_file)
        except OSError as exc:
            logger.warning("Unable to write caption progress %s: %s", self._progress_file, exc)


def _build_progress_reporter(progress_file: Path | None, journal=None):
    """返回可选的原子阶段上报回调；上报失败不影响字幕成片。"""
    if progress_file is None:
        return None

    return _CaptionProgressReporter(progress_file, journal=journal)


def _build_stage_journal(input_path: Path, output: Path | None, attempt_id: str, scope=None):
    """字幕成片是整片流程的一阶段，独立 CLI 也不冒充完整准备/发布尝试。"""
    if not settings.enable_pipeline_stage_events:
        return None
    task_id = canonical_task_id(input_path.stem, scope_key=scope.key if scope is not None else None)
    journal_root = Path(output).parent if output is not None else input_path.parent
    task_key = hashlib.sha256(task_id.encode()).hexdigest()[:24]
    attempt_key = hashlib.sha256(str(attempt_id).encode()).hexdigest()[:24]
    journal = StageJournal(journal_root / '.stage-events' / task_key / 'phases' / f'{attempt_key}.jsonl',
                           task_id=task_id, attempt_id=attempt_id, role='phase')
    if scope is not None:
        journal.emit('phase_context', parent_attempt_id=scope.owner)
    return journal

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
@click.option('--copy-reused', is_flag=True, help='Report an already verified copywriting checkpoint.')
@click.option('--preserve-source-chinese', is_flag=True, help='Check existing Chinese captions before translation; uncertain sources require review.')
@click.option('--subtitle-receipt', type=click.Path(path_type=Path), default=None, hidden=True)
@click.option('--subtitle-attempt-id', default=None, hidden=True)
def auto_caption(input_path, model, src_lang, target_lang, device, style, output, vertical, title, bg_blur, font_path, font_size, bilingual, source_date, progress_file, copy_reused=False, preserve_source_chinese=False, subtitle_receipt=None, subtitle_attempt_id=None):
    """Generate and burn bilingual subtitles for a video."""
    attempt_id = subtitle_attempt_id or uuid.uuid4().hex
    journal = None
    journal_binding = None
    execution_scope = None
    outcome = 'failed'
    resource_wait_baseline = wait_state()['seconds']
    progress_reporter = None
    try:
        execution_scope = setup_execution_context()
        journal = _build_stage_journal(input_path, output, attempt_id, execution_scope)
        journal_binding = bind_journal(journal)
        journal_binding.__enter__()
        progress_reporter = _build_progress_reporter(progress_file, journal=journal)
        if progress_reporter is not None:
            if copy_reused:
                progress_reporter.reused_steps.add('copy')
            progress_reporter.start()
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
                progress_reporter=progress_reporter or (journal.transition if journal else None),
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
                progress_reporter=progress_reporter or (journal.transition if journal else None),
            )
            mode_str = "Standard"
        
        if preserve_source_chinese and (not vertical or output is None):
            raise click.UsageError('--preserve-source-chinese requires --vertical and --output')
        processor.preserve_source_chinese = preserve_source_chinese
        click.echo(f"Starting auto-captioning for: {input_path}")
        click.echo(f"Mode: {mode_str}")
        click.echo(f"Configuration: Model={model}, Src={src_lang}, Target={target_lang}, Device={device}, Style={style}")
        
        with isolated_caption_artifacts(processor, execution_scope), resource_stage('heavy', 'CAPTION_PIPELINE'):
            output_file = processor.process()
        if subtitle_receipt is not None:
            write_success_receipt(subtitle_receipt, subtitle_attempt_id, input_path,
                                  getattr(processor, '_subtitle_completion', None))
        
        click.echo(f"Success! Output saved to: {output_file}")
        outcome = 'local_complete'
        
    except PreparationYielded:
        outcome = 'yielded'
        raise click.exceptions.Exit(76)
    except PreparationBusy:
        outcome = 'waiting_resource_owner_unknown'
        raise click.exceptions.Exit(77)
    except SubtitleTranslationFailure as e:
        outcome = 'translation_stopped'
        if journal:
            journal.emit('failure', stage='TRANSLATING', category=e.failure['category'],
                         code=e.failure['code'])
        logger.error('Subtitle translation stopped: %s', e)
        if subtitle_receipt is not None:
            write_failure_receipt(subtitle_receipt, subtitle_attempt_id, input_path, e)
        click.echo(f"字幕恢复: {e.failure['category']} / {e.failure['code']}；成功批次已保留。", err=True)
        raise click.exceptions.Exit(75 if e.failure['category'] in
                                    {'network', 'quota', 'busy', 'timeout', 'unavailable'} else 78)
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
        if journal is not None:
            journal.emit('metric', stage='RESOURCE_WAIT',
                         duration_seconds=max(0.0, wait_state()['seconds'] -
                                              resource_wait_baseline))
            journal.close(outcome)
        try:
            if execution_scope is not None:
                execution_scope.close()
        finally:
            if journal_binding is not None:
                journal_binding.__exit__(None, None, None)
