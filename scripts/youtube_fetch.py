#!/usr/bin/env python3
"""给英语世界协调器使用的受控 yt-dlp 入口；不切换全局代理组。"""
from __future__ import annotations

import subprocess
import os
import signal
import sys
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from config.settings import settings
from video_processing.utils.subprocess_env import build_subprocess_env
from video_processing.utils.youtube_route import (
    YoutubeRouteError, guarded_youtube_call, youtube_cli_args, youtube_environment,
)


def _run_command(command):
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                          env=youtube_environment(build_subprocess_env()), start_new_session=True) as process:
        try:
            stdout, stderr = process.communicate(timeout=settings.youtube_download_timeout_seconds)
        except BaseException:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
            raise
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    # 下载器由封装传入 HTTP 代理；不允许协调器用额外配置/执行钩子覆盖出口。
    forbidden = {'--proxy', '--geo-verification-proxy', '--config-locations', '--config-location',
                 '--alias', '--exec', '--exec-before-download', '--downloader-args', '--external-downloader-args'}
    for index, arg in enumerate(args):
        option = arg.split('=', 1)[0]
        if option in forbidden:
            raise YoutubeRouteError('受控下载入口禁止覆盖代理、配置或外部执行参数')
        if option in {'--downloader', '--external-downloader'}:
            value = arg.split('=', 1)[1] if '=' in arg else (args[index+1] if index+1 < len(args) else '')
            if value not in {'native', 'curl', 'ffmpeg'}:
                raise YoutubeRouteError('受控下载入口只支持 native、curl、ffmpeg')
    urls = [arg for arg in args if arg.startswith(('https://', 'http://'))]
    source = urls[-1] if urls else 'https://www.youtube.com/'
    identity = parse_qs(urlsplit(source).query).get('v', [urlsplit(source).path.rsplit('/', 1)[-1]])[0] or 'metadata'
    command = [settings.ytdlp_path, *args, *youtube_cli_args(verify=False),
               '--newline', '--progress', '--progress-template',
               'download:ROUTE_MEDIA_BYTES:%(info.id)s:%(info.format_id)s:%(progress.downloaded_bytes)s']
    completed = guarded_youtube_call(
        lambda: _run_command(command),
        task_id=identity, source_url=source, downloader='coordinator yt-dlp',
        evidence_path=settings.project_root / 'output/youtube_route_cli.jsonl',
    )
    sys.stdout.write(completed.stdout)
    sys.stderr.write(completed.stderr)
    return completed.returncode


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except YoutubeRouteError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
