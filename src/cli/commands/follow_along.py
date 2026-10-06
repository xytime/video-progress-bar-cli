"""显式本地双语跟读 CLI；没有发布副作用。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-07 | Codex | 本地 Timeline 制作与阶段收据 |
"""
import json
from pathlib import Path
import shutil

import click


@click.command("follow-along")
@click.argument("timeline", type=click.Path(exists=True, path_type=Path, dir_okay=False))
@click.option("--root", type=click.Path(exists=True, path_type=Path, file_okay=False), help="素材根目录，缺省为 Timeline 所在目录")
@click.option("--target-stage", type=click.Choice(["align", "resolve", "render", "package"]), default="package")
@click.option("--no-resume", is_flag=True, help="显式重算本次依赖阶段")
@click.option("--aligner-config", type=click.Path(exists=True, path_type=Path, dir_okay=False), help="隔离 WhisperX 配置 JSON；缺省导入已有证据词界")
@click.option("--timeout", type=click.IntRange(min=1), default=600, help="每个 FFmpeg 的执行超时秒数")
def follow_along(timeline, root, target_stage, no_resume, timeout, aligner_config):
    """从有证据的本地 Timeline 制作双语跟读视频。"""
    import imageio_ffmpeg
    from config.settings import settings
    from video_processing.follow_along.audio import MediaTools
    from video_processing.follow_along_manager import FollowAlongPipeline
    ffmpeg = settings.ffmpeg_path or imageio_ffmpeg.get_ffmpeg_exe()
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise click.ClickException("缺少 ffprobe；未安装或更改生产依赖")
    plan = json.loads(timeline.read_text(encoding="utf-8"))
    aligner = None
    if aligner_config:
        from video_processing.follow_along.whisperx_adapter import WhisperXAligner
        config = json.loads(aligner_config.read_text())
        aligner = WhisperXAligner(config["python"], config["model_directory"], config["nltk_directory"], config["package_version"], timeout)
    receipt = FollowAlongPipeline(root or timeline.parent, MediaTools(ffmpeg, ffprobe, timeout), aligner).run(plan, target_stage, not no_resume)
    click.echo(json.dumps(receipt, ensure_ascii=False, indent=2))
    if receipt["state"] == "CANCELLED":
        raise click.Abort()
    if receipt["state"] in {"FAILED", "NEEDS_REVIEW"}:
        raise click.ClickException(f"制作停止: {receipt['state']}")


@click.command("follow-along-init")
@click.argument("job_directory", type=click.Path(path_type=Path))
@click.option("--audio", type=click.Path(exists=True, path_type=Path, dir_okay=False), required=True)
@click.option("--video", type=click.Path(exists=True, path_type=Path, dir_okay=False), required=True)
@click.option("--english", type=click.Path(exists=True, path_type=Path, dir_okay=False), required=True)
@click.option("--chinese", type=click.Path(exists=True, path_type=Path, dir_okay=False), required=True)
@click.option("--english-font", type=click.Path(exists=True, path_type=Path, dir_okay=False), required=True)
@click.option("--chinese-font", type=click.Path(exists=True, path_type=Path, dir_okay=False), required=True)
@click.option("--vocals", type=click.Path(exists=True, path_type=Path, dir_okay=False))
@click.option("--title", required=True)
@click.option("--tag", default="跟读")
@click.option("--objective", required=True)
@click.option("--mode", type=click.Choice(["speaking", "singing"]), default="speaking")
@click.option("--duration-seconds", type=click.FloatRange(min=0, min_open=True), required=True)
@click.option("--audio-start", type=click.FloatRange(min=0), default=0)
@click.option("--video-start", type=click.FloatRange(min=0), default=0)
@click.option("--same-recording", is_flag=True, required=True, help="明确声明音视频来自同一录音版本，并确认逐行译文对应")
def follow_along_init(job_directory, same_recording, **options):
    """复制本地素材并建立未对齐 Timeline；不会伪造词界。"""
    import imageio_ffmpeg
    from config.settings import settings
    from video_processing.follow_along.audio import MediaTools
    from video_processing.follow_along.job import create_job
    from video_processing.follow_along.contracts import PipelineError
    ffprobe = shutil.which("ffprobe")
    if not ffprobe or not same_recording:
        raise click.ClickException("需要 ffprobe 和明确的同录音/逐行意群对应声明")
    tools = MediaTools(settings.ffmpeg_path or imageio_ffmpeg.get_ffmpeg_exe(), ffprobe)
    try:
        click.echo(str(create_job(job_directory, tools, **options)))
    except PipelineError as exc:
        raise click.ClickException(f"{exc.code}: {exc}") from exc
