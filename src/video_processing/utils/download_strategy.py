"""YouTube 视频下载策略与执行引擎 (Strategy & Fallback Pattern)

提供高速原生 yt-dlp 与稳健 curl 外部下载器的策略抽象与有界降级执行器。
单一真相源：pipeline_manager 与 pipeline_agent 共用。

# Modification History
| Version | Date       | Author      | Description                                                        |
|---------|------------|-------------|-------------------------------------------------------------------|
| 1.0.0   | 2026-09-23 | Antigravity | 初始实现：Strategy/Fallback 模式、Native 首选与 Curl 备选、产物后置验真与分片自动清理 |
"""
from __future__ import annotations

import logging
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from .file_utils import clean_partial_downloads

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DownloadOptions:
    """yt-dlp 下载参数聚合对象。"""

    ytdlp_path: str
    url: str
    output_template: str
    cookie_args: Sequence[str] = ()
    format_selector: str = (
        "bestvideo[height<=720][ext=mp4][vcodec^=avc]+bestaudio[ext=m4a]/"
        "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/"
        "best[ext=mp4]/best"
    )
    sort_format: str = "vcodec:h264"
    force_ipv4: bool = True
    remote_components: Sequence[str] = ("ejs:github",)
    write_description: bool = True
    write_info_json: bool = True
    download_sections: Optional[str] = None
    force_keyframes_at_cuts: bool = False
    curl_args: str = (
        "curl:--continue-at - --retry 10 --retry-delay 3 --retry-all-errors "
        "--speed-limit 10000 --speed-time 30 --connect-timeout 15"
    )


class DownloadStrategy(ABC):
    """下载策略抽象基类。"""

    @property
    @abstractmethod
    def name(self) -> str:
        """策略名称。"""
        pass

    @abstractmethod
    def build_command(self, options: DownloadOptions) -> list[str]:
        """构建 yt-dlp 命令行参数列表。"""
        pass


class NativeDownloadStrategy(DownloadStrategy):
    """高速首选策略：使用 yt-dlp 原生多连接流式下载，消除外部 curl 进程调用与限速开销。"""

    @property
    def name(self) -> str:
        return "Native yt-dlp"

    def build_command(self, options: DownloadOptions) -> list[str]:
        cmd = [options.ytdlp_path]
        if options.force_ipv4:
            cmd.append("--force-ipv4")
        if options.format_selector:
            cmd.extend(["-f", options.format_selector])
        if options.sort_format:
            cmd.extend(["-S", options.sort_format])
        if options.cookie_args:
            cmd.extend(options.cookie_args)
        if options.write_description:
            cmd.append("--write-description")
        if options.write_info_json:
            cmd.append("--write-info-json")
        for comp in options.remote_components:
            cmd.extend(["--remote-components", comp])
        if options.download_sections:
            cmd.extend(["--download-sections", options.download_sections])
            if options.force_keyframes_at_cuts:
                cmd.append("--force-keyframes-at-cuts")
        cmd.extend([options.url, "-o", options.output_template])
        return cmd


class CurlDownloadStrategy(DownloadStrategy):
    """稳健备选策略：使用 curl 外部下载器，提供断点续传、超时与网络重试保障。"""

    def __init__(self, curl_args: Optional[str] = None):
        self._curl_args = curl_args

    @property
    def name(self) -> str:
        return "Curl Downloader"

    def build_command(self, options: DownloadOptions) -> list[str]:
        cmd = [options.ytdlp_path]
        if options.force_ipv4:
            cmd.append("--force-ipv4")
        if options.format_selector:
            cmd.extend(["-f", options.format_selector])
        if options.sort_format:
            cmd.extend(["-S", options.sort_format])
        if options.cookie_args:
            cmd.extend(options.cookie_args)
        if options.write_description:
            cmd.append("--write-description")
        if options.write_info_json:
            cmd.append("--write-info-json")
        for comp in options.remote_components:
            cmd.extend(["--remote-components", comp])
        if options.download_sections:
            cmd.extend(["--download-sections", options.download_sections])
            if options.force_keyframes_at_cuts:
                cmd.append("--force-keyframes-at-cuts")

        # 挂载 curl 外部下载器与重试参数
        cmd.extend(["--downloader", "curl"])
        args = self._curl_args if self._curl_args is not None else options.curl_args
        if args:
            cmd.extend(["--downloader-args", args])

        cmd.extend([options.url, "-o", options.output_template])
        return cmd


def execute_download_with_fallback(
    options: DownloadOptions,
    runner: Callable[[list[str]], Any],
    verifier: Callable[[], Optional[str]],
    cleaner: Optional[Callable[[], None]] = None,
    *,
    primary_strategy: Optional[DownloadStrategy] = None,
    fallback_strategy: Optional[DownloadStrategy] = None,
    on_fallback: Optional[Callable[[str], None]] = None,
) -> str:
    """以策略降级模式执行视频下载：首选原生引擎，失败/异常/损坏文件时自动清理并降级 curl。

    Args:
        options: 下载参数聚合。
        runner: 命令行执行函数（接受 list[str]，执行如 _run_tracked 或 subprocess.run）。
        verifier: 产物验真函数（返回已下载有效视频文件的路径，未就绪返回 None）。
        cleaner: 局部临时/损坏文件清理函数，未提供时使用默认清理。
        primary_strategy: 首选策略，默认 NativeDownloadStrategy。
        fallback_strategy: 备选策略，默认 CurlDownloadStrategy。
        on_fallback: 发生降级时的告警/通知回调。

    Returns:
        成功下载并经验真的视频文件绝对路径。

    Raises:
        FileNotFoundError: 降级尝试后仍未产生有效视频文件。
        Exception: 备选策略执行中的严重未捕获异常。
    """
    primary = primary_strategy or NativeDownloadStrategy()
    fallback = fallback_strategy or CurlDownloadStrategy()

    if cleaner:
        cleaner()

    primary_cmd = primary.build_command(options)
    logger.info("[Download] 首选策略 (%s) 开始下载: %s", primary.name, options.url)

    primary_failed = False
    fallback_reason = ""

    try:
        runner(primary_cmd)
        target_file = verifier()
        if target_file:
            return target_file
        primary_failed = True
        fallback_reason = "原生下载命令退出码为 0，但未生成大于 50KB 的有效视频文件"
    except (KeyboardInterrupt, InterruptedError):
        raise
    except Exception as exc:
        primary_failed = True
        fallback_reason = f"原生下载抛出异常: {type(exc).__name__} ({exc})"

    if primary_failed:
        if on_fallback:
            on_fallback(fallback_reason)
        else:
            logger.warning("[Download] %s，清理残余并降级回退至 %s...", fallback_reason, fallback.name)

        if cleaner:
            cleaner()

        fallback_cmd = fallback.build_command(options)
        runner(fallback_cmd)

        target_file = verifier()
        if not target_file:
            raise FileNotFoundError(f"No video file found for {options.url} after fallback download ({fallback.name})")
        return target_file

    return verifier() or ""
