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
