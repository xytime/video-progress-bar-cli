"""src/bot/video_delivery.py — 成片交付：定位 + 体积适配（超限自动压缩）。

Telegram 云端 Bot API 单文件上限为 **50MB**。本模块只负责把一条已制作完成的成片
准备成「一个可以直接发送的本地文件」：

1. 按 pipeline_manager 的命名约定定位 ``output/{prefix}_vertical.mp4``；
2. 若体积 ≤ 上限，原片直接返回；
3. 若超限，用 ffmpeg 按时长反推码率转码出一份 ≤ 上限的压缩副本（带 checkpoint 复用）。

设计原则（高内聚/低耦合）：本模块**不依赖** telegram / DB / 网络，纯文件系统 + ffmpeg，
因此可独立单元测试而无需 mock 任何外部对象。真正的「发送」动作（Bot.send_video）留在
调用方（telegram_bot 命令 / pipeline_agent 工具）——那是 I/O 层的职责。

注意：``prepare_for_delivery`` 内部会同步调用 ffmpeg/ffprobe，属 CPU/IO 阻塞操作。
异步调用方必须放进 executor（``asyncio.to_thread`` / ``run_in_executor``）执行，
切勿在事件循环线程里直接调用，否则会阻塞 Telegram 轮询。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-06-14 | Claude_Opus_4.8 | 初始创建：成片定位 + 超 50MB 自动压缩交付，供 /getvideo 命令与 AI agent 复用 |
"""
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from config.settings import settings
from video_processing.utils.video_metadata import get_video_duration_ffprobe

logger = logging.getLogger("video_delivery")

# ── 常量 ──────────────────────────────────────────────────────────────────
# Telegram 云端 Bot API 单文件硬上限（自建 Local Bot API 可达 2GB，此处按云端取保守值）
TELEGRAM_BOT_FILE_LIMIT = 50 * 1024 * 1024  # 50 MB

# 小于此体积视为「成片不存在/未制作完成」（与 pipeline 的 >50KB 有效性启发一致）
_MIN_VALID_BYTES = 50 * 1024  # 50 KB
# 转码体积预算留白：实际码率按上限的 90% 反推，给容器/关键帧/抖动留余量
_SIZE_HEADROOM = 0.90
# 视频码率下限（kbps）——再低画面会糊到无意义，宁可判定压不下去
_MIN_VIDEO_KBPS = 200
# 压缩时短边上限（成片均为竖屏 1080×1920，短边=宽）。降到 720 能显著提升码率利用率
_MAX_SHORT_SIDE = 720


@dataclass(frozen=True)
class PreparedVideo:
    """一条「可直接发送」的成片。"""
    path: Path            # 实际要发送的文件（原片或压缩副本）
    original_path: Path   # 原始成片路径
    size_bytes: int       # ``path`` 的体积
    compressed: bool      # 是否经过压缩
    duration_s: float     # 时长（秒，用于文案；探测失败时为 0.0）

    @property
    def size_mb(self) -> float:
        return self.size_bytes / (1024 * 1024)


class FinishedVideoNotFound(Exception):
    """成片不存在或尚未制作完成。"""


class CompressionError(Exception):
    """超限成片无法被压缩到上限以内（时长过长 / ffmpeg 失败）。"""


# ── 路径解析（命名约定的唯一真相来源）────────────────────────────────────
def finished_video_path(
    youtube_id: str,
    slice_index: int = 0,
    output_dir: Optional[Path] = None,
) -> Path:
    """返回成片在磁盘上的路径。

    必须与 ``pipeline_manager`` 的命名约定保持一致：
    ``prefix = f"{yid}_s{slice_index}" if slice_index > 0 else yid``，
    成片为 ``{prefix}_vertical.mp4``。
    """
    prefix = f"{youtube_id}_s{slice_index}" if slice_index and slice_index > 0 else youtube_id
    out = Path(output_dir) if output_dir is not None else settings.default_output_dir
    return out / f"{prefix}_vertical.mp4"


# ── 码率反推（纯函数，便于单测）──────────────────────────────────────────
def compute_target_bitrates(
    duration_s: float,
    size_limit: int = TELEGRAM_BOT_FILE_LIMIT,
    *,
    headroom: float = _SIZE_HEADROOM,
) -> tuple[int, int]:
    """按目标体积与时长反推 (video_kbps, audio_kbps)。

    总比特预算 = size_limit * headroom * 8；扣除音频后即视频码率。
    时长越长，单位时间可用码率越低；音频在码率紧张时从 128k 退到 64k。

    Raises:
        CompressionError: duration 非正（无法反推码率）。
    """
    if duration_s <= 0:
        raise CompressionError("无法获取视频时长，无法反推压缩码率")

    total_kbps = (size_limit * headroom * 8) / duration_s / 1000.0
    # 码率紧张时优先保画面：音频从 128k 退到 64k
    audio_kbps = 128 if total_kbps > 128 * 3 else 64
    video_kbps = int(total_kbps - audio_kbps)
    video_kbps = max(video_kbps, _MIN_VIDEO_KBPS)
    return video_kbps, audio_kbps


# ── 转码（与 ffmpeg 交互）────────────────────────────────────────────────
def _transcode_to_fit(
    src: Path,
    dst: Path,
    video_kbps: int,
    audio_kbps: int,
    ffmpeg_path: Optional[str] = None,
) -> None:
    """用 ffmpeg 把 ``src`` 压成目标码率写入 ``dst``。

    成片为竖屏，故按短边（宽）封顶到 ``_MAX_SHORT_SIDE`` 下采样；``-2`` 保证高为偶数。
    单遍码率控制 + maxrate/bufsize 约束峰值，``+faststart`` 便于流式播放。
    """
    ffmpeg = ffmpeg_path or "ffmpeg"
    cmd = [
        ffmpeg, "-y", "-i", str(src),
        "-vf", f"scale='min({_MAX_SHORT_SIDE},iw)':-2",
        "-c:v", "libx264", "-preset", "veryfast",
        "-b:v", f"{video_kbps}k",
        "-maxrate", f"{int(video_kbps * 1.45)}k",
        "-bufsize", f"{int(video_kbps * 2)}k",
        "-c:a", "aac", "-b:a", f"{audio_kbps}k",
        "-movflags", "+faststart",
        str(dst),
    ]
    logger.info("压缩成片 %s → %s (v=%dk a=%dk)", src.name, dst.name, video_kbps, audio_kbps)
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError as e:
        raise CompressionError(f"未找到 ffmpeg：{e}") from e
    except subprocess.CalledProcessError as e:
        tail = (e.stderr or b"").decode("utf-8", "ignore")[-500:]
        raise CompressionError(f"ffmpeg 压缩失败：{tail}") from e


# ── 对外入口 ──────────────────────────────────────────────────────────────
def prepare_for_delivery(
    youtube_id: str,
    slice_index: int = 0,
    *,
    size_limit: int = TELEGRAM_BOT_FILE_LIMIT,
    output_dir: Optional[Path] = None,
    ffmpeg_path: Optional[str] = None,
    ffprobe_path: Optional[str] = None,
) -> PreparedVideo:
    """把成片准备成一个 ≤ ``size_limit`` 的可发送文件。

    同步阻塞（含 ffmpeg 转码），异步调用方须放进 executor 执行。

    Raises:
        FinishedVideoNotFound: 成片不存在或体积过小（未制作完成）。
        CompressionError: 超限且无法压到上限内。
    """
    src = finished_video_path(youtube_id, slice_index, output_dir)
    if not src.exists() or src.stat().st_size < _MIN_VALID_BYTES:
        raise FinishedVideoNotFound(
            f"未找到成片：{src.name}（请确认该视频已制作完成 / 未被 GC 清理）"
        )

    duration = _safe_duration(src, ffprobe_path)
    size = src.stat().st_size

    # ── 路径 1：原片已在上限内，直接发 ──
    if size <= size_limit:
        return PreparedVideo(src, src, size, False, duration)

    # ── 路径 2：超限，需压缩 ──
    dst = src.with_name(f"{src.stem}_tg.mp4")

    # checkpoint 复用：已有的压缩副本若仍在上限内且不比源旧，直接复用
    if (
        dst.exists()
        and dst.stat().st_size <= size_limit
        and dst.stat().st_mtime >= src.stat().st_mtime
    ):
        logger.info("复用已存在的压缩副本 %s", dst.name)
        return PreparedVideo(dst, src, dst.stat().st_size, True, duration)

    video_kbps, audio_kbps = compute_target_bitrates(duration, size_limit)
    _transcode_to_fit(src, dst, video_kbps, audio_kbps, ffmpeg_path)

    if not dst.exists():
        raise CompressionError("压缩未产出文件")
    out_size = dst.stat().st_size
    if out_size > size_limit:
        raise CompressionError(
            f"压缩后仍有 {out_size / 1024 / 1024:.1f}MB，超过 "
            f"{size_limit / 1024 / 1024:.0f}MB 上限（视频可能过长）"
        )
    return PreparedVideo(dst, src, out_size, True, duration)


def _safe_duration(src: Path, ffprobe_path: Optional[str]) -> float:
    """探测时长，失败返回 0.0（不让文案/探测失败阻断 ≤ 上限的直接发送路径）。"""
    try:
        return get_video_duration_ffprobe(src, ffprobe_path)
    except Exception as e:  # noqa: BLE001 — 探测失败不致命
        logger.warning("探测成片时长失败 %s：%s", src.name, e)
        return 0.0
