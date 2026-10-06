"""协调器入口必须服从出口保护，不能用下载参数绕开。"""
import importlib.util
import subprocess
from pathlib import Path
import pytest
from video_processing.utils import youtube_route as route

spec = importlib.util.spec_from_file_location('youtube_fetch', Path(__file__).resolve().parents[2]/'scripts/youtube_fetch.py')
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)

@pytest.mark.parametrize('arg', ['--proxy=http://paid:7890', '--downloader=aria2c', '--downloader-args=curl:--noproxy *', '--exec=echo bad'])
def test_coordinator_cannot_override_proxy(monkeypatch, arg):
    monkeypatch.setattr(cli, '_run_command', lambda cmd: pytest.fail('must not launch'))
    with pytest.raises(route.YoutubeRouteError):cli.main([arg, 'https://youtu.be/example'])

def test_coordinator_guard_rejection_never_launches_child(monkeypatch, tmp_path):
    def reject(**kw):raise route.YoutubeRouteError('policy unavailable')
    monkeypatch.setattr(route, 'verify_youtube_route', reject)
    monkeypatch.setattr(cli, '_run_command', lambda cmd: pytest.fail('must not launch'))
    with pytest.raises(route.YoutubeRouteError):cli.main(['--skip-download', 'https://youtu.be/example'])

def test_coordinator_success_preserves_explicit_proxy_and_exit(monkeypatch):
    monkeypatch.setattr(route, 'verify_youtube_route', lambda **kw: {'policy_verified': True})
    commands=[]
    monkeypatch.setattr(cli, '_run_command', lambda cmd: commands.append(cmd) or subprocess.CompletedProcess(cmd, 7, '', ''))
    assert cli.main(['--skip-download', 'https://youtu.be/example']) == 7
    assert commands[0][commands[0].index('--proxy')+1] == 'http://127.0.0.1:7890'
    assert '--ignore-config' in commands[0]

@pytest.mark.parametrize('args', [
    ['--downloader', 'curl', '--downloader-ar', 'curl:--proxy http://127.0.0.1:19999'],
    ['--external-downloader-arg=curl:--noproxy *'], ['--prox=http://paid:7890'],
    ['--config-l', '/tmp/foreign-config'], ['--exec-bef', 'echo bad'],
    ['--alias', 'unsafe', '--proxy http://paid:7890'], ['-a', '/tmp/urls'],
    ['--external-downloa=aria2c'], ['--', '--proxy=http://paid:7890'],
])
def test_alias_abbreviation_and_positional_bypasses_fail_before_guard(monkeypatch, args):
    monkeypatch.setattr(route, 'verify_youtube_route', lambda **kw: pytest.fail('must reject before guard'))
    monkeypatch.setattr(cli, '_run_command', lambda cmd: pytest.fail('must not launch'))
    with pytest.raises(route.YoutubeRouteError):
        cli.main([*args, 'https://youtu.be/example'])

@pytest.mark.parametrize('args', [
    ['--', 'https://youtu.be/example'],
    ['--skip-down', '-fbest', 'https://youtu.be/example'],
    ['--external-downloader', 'curl', '--', 'https://youtu.be/example'],
])
def test_normalized_command_has_enforced_options_before_sources(monkeypatch, args):
    from yt_dlp.options import parseOpts
    monkeypatch.setattr(route, 'verify_youtube_route', lambda **kw: {'policy_verified': True})
    commands = []
    monkeypatch.setattr(cli, '_run_command', lambda cmd: commands.append(cmd) or subprocess.CompletedProcess(cmd, 0, '', ''))
    assert cli.main(args) == 0
    _, options, sources = parseOpts(commands[0][1:], ignore_config_files=True)
    assert options.proxy == 'http://127.0.0.1:7890'
    assert options.ignoreconfig is True
    assert sources == ['https://youtu.be/example']
