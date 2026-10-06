#!/usr/bin/env python3
"""给英语世界协调器使用的受控 yt-dlp 入口；不切换全局代理组。"""
from __future__ import annotations

import subprocess
import os
import optparse
import re
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

# 只开放来源研究和媒体获取所需选项；不接受配置、执行钩子和下载器参数透传。
_ALLOWED_OPTIONS = frozenset('''
--skip-download --simulate --dump-json --dump-single-json --get-url --get-id
--get-title --print --quiet --no-warnings --verbose --no-progress --newline
--progress --no-playlist --flat-playlist --playlist-start --playlist-end
--playlist-items --dateafter --datebefore --match-filter --max-downloads
--socket-timeout --retries --fragment-retries --sleep-requests --sleep-interval
--max-sleep-interval --limit-rate --max-filesize --min-filesize --continue
--no-continue --no-overwrites --no-part --force-ipv4 --force-ipv6
--cookies --cookies-from-browser --format --format-sort --output --paths
--merge-output-format --remux-video --recode-video --write-subs --write-auto-subs
--sub-langs --sub-format --convert-subs --write-info-json --write-description
--write-thumbnail --write-all-thumbnails --convert-thumbnails --embed-subs
--embed-thumbnail --download-sections --force-keyframes-at-cuts --downloader
--remote-components
'''.split())


def _validated_arguments(args):
    """用 yt-dlp 的选项定义规范化别名/缩写，但不加载配置或执行解析回调。"""
    from yt_dlp.options import create_parser

    parser = create_parser()
    options, sources = [], []
    index, positional = 0, False
    while index < len(args):
        arg = args[index]
        index += 1
        if arg == '--' and not positional:
            positional = True
            continue
        if positional or not arg.startswith('-'):
            parsed = urlsplit(arg)
            host = (parsed.hostname or '').lower()
            allowed_host = any(host == domain or host.endswith('.' + domain)
                               for domain in ('youtube.com', 'youtu.be', 'youtube-nocookie.com', 'googlevideo.com'))
            if not ((parsed.scheme in {'http', 'https'} and allowed_host and not parsed.username)
                    or re.fullmatch(r'ytsearch\d*:.*\S', arg)):
                raise YoutubeRouteError('受控下载入口只接受 YouTube 来源，不接受批处理文件或额外选项')
            sources.append(arg)
            continue
        try:
            if arg.startswith('--'):
                name, separator, attached = arg.partition('=')
                option = parser.get_option(parser._match_long_opt(name))
                value = attached if separator else None
            else:
                option = parser.get_option(arg[:2])
                value = arg[2:] or None
            canonical = option.get_opt_string() if option else ''
            if canonical not in _ALLOWED_OPTIONS:
                raise YoutubeRouteError('受控下载入口禁止此选项及其别名/缩写')
            if option.takes_value():
                if option.nargs != 1:
                    raise YoutubeRouteError('受控下载入口不支持多值选项')
                if value is None:
                    if index >= len(args):
                        raise YoutubeRouteError('下载选项缺少值')
                    value = args[index]
                    index += 1
                if canonical == '--downloader' and value not in {'native', 'curl', 'ffmpeg'}:
                    raise YoutubeRouteError('受控下载入口只支持 native、curl、ffmpeg')
                if canonical == '--remote-components' and value != 'ejs:github':
                    raise YoutubeRouteError('受控下载入口只允许既有 ejs:github 组件')
                options.append(f'{canonical}={value}')
            elif value is not None:
                raise YoutubeRouteError('受控下载入口不接受组合短选项或无值选项的额外值')
            else:
                options.append(canonical)
        except optparse.OptParseError:
            raise YoutubeRouteError('下载选项未知或缩写不唯一') from None
    if not sources:
        raise YoutubeRouteError('受控下载入口缺少 YouTube 来源')
    return options, sources


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
    options, sources = _validated_arguments(args)
    source = sources[-1]
    identity = parse_qs(urlsplit(source).query).get('v', [urlsplit(source).path.rsplit('/', 1)[-1]])[0] or 'metadata'
    command = [settings.ytdlp_path, *options, *youtube_cli_args(verify=False),
               '--newline', '--progress', '--progress-template',
               'download:ROUTE_MEDIA_BYTES:%(info.id)s:%(info.format_id)s:%(progress.downloaded_bytes)s',
               '--', *sources]
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
