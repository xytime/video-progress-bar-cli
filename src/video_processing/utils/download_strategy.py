"""YouTube 视频下载策略与执行引擎 (Strategy & Fallback Pattern)

提供高速原生 yt-dlp 与稳健 curl 外部下载器的策略抽象与有界降级执行器。
单一真相源：pipeline_manager 与 pipeline_agent 共用。

# Modification History
| Version | Date       | Author      | Description                                                        |
|---------|------------|-------------|-------------------------------------------------------------------|
| 1.2.0   | 2026-10-05 | Codex       | 认证/限流有界冷却，失败后验真清理，保留有效分片；压缩脱敏错误证据 |
| 1.1.1   | 2026-09-23 | Antigravity | [Code Review Fix] 增加 SystemExit 识别为取消异常，防止退出信号误触发 curl 降级 |
| 1.1.0   | 2026-09-23 | Antigravity | 提取公共参数构建器；纠正 Native 流式下载注释；精准识别 SIGTERM/SIGINT 取消信号与外部取消回调，杜绝取消后误降级 curl；引入贯穿降级链路的总截止时间与动态超时预算 |
| 1.0.0   | 2026-09-23 | Antigravity | 初始实现：Strategy/Fallback 模式、Native 首选与 Curl 备选、产物后置验真与分片自动清理 |
"""
from __future__ import annotations

import inspect
import json
import logging
import re
import shutil
from functools import lru_cache
from importlib import metadata
import signal
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from .file_utils import clean_partial_downloads
from .youtube_route import YoutubeRouteError, guarded_youtube_call

logger = logging.getLogger(__name__)


@lru_cache(maxsize=4)
def download_runtime_status(search_path: str) -> dict:
    """下载前核对本机依赖；只执行版本命令，不联网或改变代理。"""
    from packaging.requirements import Requirement
    result = {"yt_dlp": metadata.version("yt-dlp")}
    try:
        result["ejs"] = metadata.version("yt-dlp-ejs")
    except metadata.PackageNotFoundError as exc:
        raise RuntimeError("下载运行时缺少兼容 yt-dlp-ejs；安装 requirements.txt 的 yt-dlp[default]。") from exc
    for raw in metadata.requires("yt-dlp") or []:
        requirement = Requirement(raw)
        if requirement.name == "yt-dlp-ejs" and result["ejs"] not in requirement.specifier:
            raise RuntimeError("yt-dlp-ejs 与当前 yt-dlp 不兼容，停止下载。")
    for name, flag in (("deno", "--version"), ("ffmpeg", "-version"), ("ffprobe", "-version")):
        executable = shutil.which(name, path=search_path)
        if not executable:
            raise RuntimeError(f"下载运行时缺少 {name}，停止下载。")
        version = subprocess.run([executable, flag], capture_output=True, text=True, timeout=5, check=True).stdout.splitlines()[0]
        result[name] = version
    match = re.search(r"deno (\d+)\.(\d+)", result["deno"])
    if not match or tuple(map(int, match.groups())) < (2, 3):
        raise RuntimeError("YouTube challenge runtime requires Deno >=2.3，停止下载。")
    return result

_CANCELLATION_RETURNCODES = frozenset({
    -signal.SIGTERM,
    -signal.SIGINT,
    -signal.SIGKILL,
    143,  # 128 + 15
    130,  # 128 + 2
    137,  # 128 + 9
})


class DownloadBlockedError(RuntimeError):
    """同一身份的认证/限流阻断；换下载器不能恢复。"""

    def __init__(self, category: str, detail: str, retry_after: float):
        self.category = category
        self.retry_after = retry_after
        super().__init__(f"SOURCE_DOWNLOAD_{category.upper()}: {detail}; retry_after={retry_after:.0f}")


def _failure_detail(exc: BaseException) -> str:
    raw = getattr(exc, "stderr", None) or str(exc)
    if isinstance(raw, bytes):
        raw = raw.decode(errors="replace")
    # 保留核心错误，拒绝把签名媒体 URL 和整段进度写入账本。
    lines = [line for line in str(raw).splitlines() if "error" in line.lower() or "warning" in line.lower()]
    detail = "\n".join(lines[-6:]) or str(raw)[-1000:]
    return re.sub(r"https?://[^\s]+", "<url>", detail)[-1500:]


def _blocking_category(detail: str) -> Optional[str]:
    text = detail.lower()
    if any(marker in text for marker in ("sign in to confirm", "not a bot", "login required", "use --cookies for the authentication")):
        return "auth"
    if any(marker in text for marker in ("429", "too many requests", "rate limit")):
        return "rate_limit"
    return None


def _is_cancellation_exception(exc: BaseException) -> bool:
    """判断异常是否由主动取消或进程终止信号引发。"""
    if isinstance(exc, (KeyboardInterrupt, InterruptedError, SystemExit)):
        return True
    if isinstance(exc, subprocess.CalledProcessError):
        return exc.returncode in _CANCELLATION_RETURNCODES or exc.returncode < 0
    return False


def _invoke_runner(runner: Callable[..., Any], cmd: list[str], timeout: Optional[float] = None) -> Any:
    """自适应调用 runner：若 runner 支持 timeout 参数则传入，否则按单参数调用。"""
    try:
        sig = inspect.signature(runner)
    except (ValueError, TypeError):
        return runner(cmd)
    if "timeout" in sig.parameters or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
        return runner(cmd, timeout=timeout)
    return runner(cmd)


@dataclass(frozen=True)
class DownloadOptions:
    """yt-dlp 下载参数聚合对象。"""

    ytdlp_path: str
    url: str
    output_template: str
    cookie_args: Sequence[str] = ()
    proxy_url: Optional[str] = None
    route_audit_path: Optional[Path] = None
    task_id: str = ""
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
    cooldown_path: Optional[Path] = None
    auth_cooldown_seconds: int = 21600
    rate_limit_cooldown_seconds: int = 900
    curl_args: str = (
        "curl:--continue-at - --retry 10 --retry-delay 3 --retry-all-errors "
        "--speed-limit 10000 --speed-time 30 --connect-timeout 15"
    )


def _build_common_ytdlp_args(options: DownloadOptions) -> list[str]:
    """提取两套策略共用的 yt-dlp 基础命令行参数。"""
    cmd = [options.ytdlp_path]
    if options.proxy_url:
        cmd.extend(["--ignore-config", "--proxy", options.proxy_url, "--no-playlist",
                    "--newline", "--progress", "--progress-template",
                    "download:ROUTE_MEDIA_BYTES:%(info.id)s:%(info.format_id)s:%(progress.downloaded_bytes)s"])
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
    return cmd


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
    """高速首选策略：使用 yt-dlp 原生流式下载引擎（按协议处理内部流，分段选择 FFmpeg），消除外部 curl 进程调用开销。"""

    @property
    def name(self) -> str:
        return "Native yt-dlp"

    def build_command(self, options: DownloadOptions) -> list[str]:
        cmd = _build_common_ytdlp_args(options)
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
        cmd = _build_common_ytdlp_args(options)
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
    total_timeout: Optional[float] = None,
    is_cancelled_callback: Optional[Callable[[], bool]] = None,
) -> str:
    """以策略降级模式执行视频下载：首选原生引擎，失败/异常/损坏文件时自动清理并降级 curl。

    严格区分明确取消与下载故障：子进程收到终止信号或外部显式取消时立即中止，绝不触发回退。
    总耗时由贯穿两阶段的统一截止时间约束，备选策略仅能消费剩余预算。

    Args:
        options: 下载参数聚合。
        runner: 命令行执行函数（接受 list[str]，可选支持 timeout 关键字参数）。
        verifier: 产物验真函数（返回已下载有效视频文件的路径，未就绪返回 None）。
        cleaner: 局部临时/损坏文件清理函数，未提供时使用默认清理。
        primary_strategy: 首选策略，默认 NativeDownloadStrategy。
        fallback_strategy: 备选策略，默认 CurlDownloadStrategy。
        on_fallback: 发生降级时的告警/通知回调。
        total_timeout: 两阶段共享的全局超时上界（秒），超时则阻断降级。
        is_cancelled_callback: 取消状态查询钩子，返回 True 则中止并不再重试。

    Returns:
        成功下载并经验真的视频文件绝对路径。

    Raises:
        InterruptedError: 任务被取消或子进程收到终止信号。
        TimeoutError: 超出全局下载预算。
        FileNotFoundError: 降级尝试后仍未产生有效视频文件。
        Exception: 备选策略执行中的严重未捕获异常。
    """
    if options.cooldown_path and options.cooldown_path.exists():
        try:
            state = json.loads(options.cooldown_path.read_text())
            if float(state["retry_after"]) > time.time():
                raise DownloadBlockedError(state["category"], state["detail"], float(state["retry_after"]))
        except (ValueError, KeyError, TypeError):
            logger.warning("[Download] 忽略损坏的源下载冷却记录。")
    if is_cancelled_callback and is_cancelled_callback():
        raise InterruptedError(f"Download cancelled for {options.url} before start.")

    deadline = (time.time() + total_timeout) if total_timeout and total_timeout > 0 else None
    primary = primary_strategy or NativeDownloadStrategy()
    fallback = fallback_strategy or CurlDownloadStrategy()

    if cleaner:
        cleaner()

    primary_cmd = primary.build_command(options)
    logger.info("[Download] 首选策略 (%s) 开始下载: %s", primary.name, options.url)

    primary_failed = False
    fallback_reason = ""

    def block_if_needed(exc: BaseException) -> str:
        detail = _failure_detail(exc)
        category = _blocking_category(detail)
        if category:
            seconds = options.auth_cooldown_seconds if category == "auth" else options.rate_limit_cooldown_seconds
            retry_after = time.time() + seconds
            if options.cooldown_path:
                from .file_utils import write_json_atomically
                write_json_atomically(options.cooldown_path, {"category": category, "detail": detail, "retry_after": retry_after})
            if cleaner:
                cleaner()
            raise DownloadBlockedError(category, detail, retry_after) from exc
        return detail

    def run_attempt(cmd, timeout, strategy):
        if not options.proxy_url:
            return _invoke_runner(runner, cmd, timeout=timeout)
        template = Path(options.output_template)
        prefix = template.name.split("%", 1)[0]
        def transfer():
            remaining = min(timeout, deadline - time.time()) if deadline and timeout else timeout
            if remaining is not None and remaining <= 0:
                raise TimeoutError("Download budget exhausted during route preflight")
            return _invoke_runner(runner, cmd, timeout=remaining)
        return guarded_youtube_call(
            transfer,
            task_id=options.task_id or template.stem, source_url=options.url,
            downloader="FFmpeg sections" if options.download_sections else strategy.name,
            evidence_path=options.route_audit_path, expected_proxy=options.proxy_url,
            artifact_paths=lambda: [p for p in template.parent.glob(prefix + "*")
                                    if p.suffix in {".mp4", ".m4a", ".webm", ".mkv", ".part"}],
        )

    primary_timeout = max(1.0, deadline - time.time()) if deadline else None
    try:
        run_attempt(primary_cmd, primary_timeout, primary)
        if is_cancelled_callback and is_cancelled_callback():
            raise InterruptedError(f"Download cancelled for {options.url} after primary execution.")
        target_file = verifier()
        if target_file:
            return target_file
        primary_failed = True
        fallback_reason = "原生下载退出码为 0，但未生成通过完整音视频轨道验真的有效视频文件"
    except BaseException as exc:
        if isinstance(exc, YoutubeRouteError):
            raise
        if _is_cancellation_exception(exc):
            if cleaner:
                cleaner()
            logger.info("[Download] 原生下载检测到取消信号/中断 (%s)，终止下载并不再启动备选降级。", exc)
            raise InterruptedError(f"Download cancelled by signal/interrupt: {exc}") from exc
        primary_failed = True
        fallback_reason = f"原生下载抛出异常: {type(exc).__name__}: {block_if_needed(exc)}"

    if is_cancelled_callback and is_cancelled_callback():
        if cleaner:
            cleaner()
        raise InterruptedError(f"Download cancelled for {options.url} before fallback.")

    if primary_failed:
        if deadline:
            remaining_budget = deadline - time.time()
            if remaining_budget <= 0:
                if cleaner:
                    cleaner()
                raise TimeoutError(
                    f"Download budget of {total_timeout}s exhausted during primary strategy; skipping fallback."
                )
        else:
            remaining_budget = None

        if on_fallback:
            on_fallback(fallback_reason)
        else:
            logger.warning("[Download] %s，清理残余并降级回退至 %s...", fallback_reason, fallback.name)

        if cleaner:
            cleaner()

        fallback_cmd = fallback.build_command(options)
        fallback_timeout = deadline - time.time() if deadline else None
        if fallback_timeout is not None and fallback_timeout <= 0:
            raise TimeoutError("Download budget exhausted before fallback execution")
        try:
            run_attempt(fallback_cmd, fallback_timeout, fallback)
        except BaseException as exc:
            if isinstance(exc, YoutubeRouteError):
                raise
            if _is_cancellation_exception(exc):
                logger.info("[Download] 备选下载检测到取消信号/中断 (%s)，终止下载。", exc)
                raise InterruptedError(f"Fallback download cancelled by signal/interrupt: {exc}") from exc
            detail = block_if_needed(exc)
            if isinstance(exc, subprocess.CalledProcessError):
                raise subprocess.CalledProcessError(exc.returncode, exc.cmd, stderr=detail) from exc
            raise
        finally:
            # 验真而非删除：有效单轨与 .part/.ytdl 均保留供续传。
            if cleaner:
                cleaner()

        if is_cancelled_callback and is_cancelled_callback():
            raise InterruptedError(f"Download cancelled for {options.url} after fallback execution.")

        target_file = verifier()
        if not target_file:
            raise FileNotFoundError(f"No video file found for {options.url} after fallback download ({fallback.name})")
        return target_file

    return verifier() or ""
