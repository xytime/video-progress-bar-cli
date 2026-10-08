"""跨进程真实子进程验收；只使用临时目录和低负载假 FFmpeg。"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from video_processing.core import ffmpeg_slot as gate


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    directory = tmp_path / "slot"
    monkeypatch.setattr(gate, "_DIRECTORY", directory)
    fake = tmp_path / "ffmpeg-test"
    fake.write_text(f"#!{sys.executable}\n" + '''import os, sys, time
with open(sys.argv[1], "a") as f:
    f.write("start " + str(os.getpid()) + "\\n"); f.flush()
time.sleep(float(sys.argv[2]))
with open(sys.argv[1], "a") as f:
    f.write("end " + str(os.getpid()) + "\\n")
''')
    fake.chmod(0o700)
    return directory, fake, tmp_path / "events"


def child(runtime, duration="0.4", timeout=4):
    directory, fake, events = runtime
    code = '''from pathlib import Path
import subprocess, sys
from video_processing.core import ffmpeg_slot as g
g._DIRECTORY = Path(sys.argv[1])
subprocess.run([sys.argv[2], sys.argv[3], sys.argv[4]], check=True, timeout=float(sys.argv[5]))
'''
    return gate._BASE_POPEN([sys.executable, "-c", code, str(directory), str(fake),
                              str(events), duration, str(timeout)], stderr=subprocess.PIPE)


def until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("等待测试条件超时")


def lines(events):
    return events.read_text().splitlines() if events.exists() else []


def test_processes_serialize_and_timeout_excludes_wait(runtime):
    first = child(runtime, "0.6")
    until(lambda: len(lines(runtime[2])) == 1)
    second = child(runtime, "0.1", timeout=0.3)
    third = child(runtime, "0.1", timeout=0.3)
    for p in (first, second, third):
        _, errors = p.communicate(timeout=8)
        assert p.returncode == 0, errors
    assert [line.split()[0] for line in lines(runtime[2])] == ["start", "end"] * 3
    assert not list(runtime[0].glob("*.wait"))


def test_parent_killed_child_keeps_slot(runtime):
    first = child(runtime, "1")
    until(lambda: len(lines(runtime[2])) == 1)
    first.kill()
    first.wait(timeout=2)
    second = child(runtime, "0.1")
    _, errors = second.communicate(timeout=6)
    assert second.returncode == 0, errors
    assert [line.split()[0] for line in lines(runtime[2])] == ["start", "end", "start", "end"]


def test_dead_waiter_is_reaped(runtime):
    first = child(runtime, "0.7")
    until(lambda: len(lines(runtime[2])) == 1)
    waiting = child(runtime)
    until(lambda: bool(list(runtime[0].glob("*.wait"))))
    waiting.kill()
    waiting.communicate(timeout=2)
    third = child(runtime, "0.1")
    for p in (first, third):
        _, errors = p.communicate(timeout=6)
        assert p.returncode == 0, errors
    assert [line.split()[0] for line in lines(runtime[2])] == ["start", "end"] * 2
    assert not list(runtime[0].glob("*.wait"))


def test_spawn_error_and_timeout_release(runtime):
    with pytest.raises(FileNotFoundError):
        subprocess.run([str(runtime[1].parent / "ffmpeg-missing")])
    with pytest.raises(subprocess.TimeoutExpired):
        subprocess.run([str(runtime[1]), str(runtime[2]), "2"], timeout=0.05)
    subprocess.run([str(runtime[1]), str(runtime[2]), "0.01"], check=True, timeout=1)
    assert not list(runtime[0].glob("*.wait"))


def test_non_ffmpeg_is_not_queued(runtime):
    owner = gate.Slot(runtime[0]); owner.acquire()
    try:
        result = subprocess.run([sys.executable, "-c", "print('free')"],
                                capture_output=True, text=True, timeout=2)
        assert result.stdout.strip() == "free"
    finally:
        owner.close()


@pytest.mark.parametrize("command,expected", [
    (["ffmpeg", "-version"], True), (["/a/ffmpeg-macos-aarch64-v7.1"], True),
    (["ffprobe", "a.mp4"], False), (["python", "ffmpeg.py"], False),
    (["/a/ffmpeg-test"], True),
])
def test_recognition(command, expected):
    assert gate.is_ffmpeg(command) == expected


def test_lock_failure_is_closed(runtime, monkeypatch):
    runtime[0].write_text("cannot make this a directory")
    with pytest.raises(FileExistsError):
        subprocess.run([str(runtime[1]), str(runtime[2]), "0.01"])
    assert not runtime[2].exists()


def test_real_ffmpeg_holds_inherited_fd_after_parent_exit(runtime):
    import imageio_ffmpeg
    exe = imageio_ffmpeg.get_ffmpeg_exe()
    marker = runtime[2]
    code = '''from pathlib import Path
import os, subprocess, sys
from video_processing.core import ffmpeg_slot as g
g._DIRECTORY = Path(sys.argv[1])
p = subprocess.Popen([sys.argv[2], "-v", "error", "-re", "-f", "lavfi", "-i", "color=s=16x16:r=5", "-t", "1.5", "-threads", "1", "-f", "null", "-"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
Path(sys.argv[3]).write_text(str(p.pid))
os._exit(0)
'''
    p = gate._BASE_POPEN([sys.executable, "-c", code, str(runtime[0]), exe, str(marker)])
    p.wait(timeout=3)
    assert p.returncode == 0
    started = time.monotonic()
    slot = gate.Slot(runtime[0]); slot.acquire(); slot.close()
    assert time.monotonic() - started >= 0.5, "真实 FFmpeg 必须保留继承的锁 FD"


def test_parent_execution_budget_excludes_child_queue(runtime):
    first = child(runtime, "1.2")
    until(lambda: len(lines(runtime[2])) == 1)
    second = child(runtime, "0.05")
    _, errors = gate.communicate_with_progress_budget(second, timeout=0.7)
    assert second.returncode == 0, errors
    first.communicate(timeout=4)
    assert [line.split()[0] for line in lines(runtime[2])] == ["start", "end"] * 2


def test_queue_budget_merges_descendant_intervals_and_ignores_old_pid(runtime, monkeypatch):
    runtime[0].mkdir()
    budget = gate.QueueBudget(42)
    monkeypatch.setattr(gate.time, "time", lambda: budget.started_at + 10)
    monkeypatch.setattr(gate.time, "monotonic", lambda: budget.started_monotonic + 10)
    for index, (begin, end) in enumerate([(1, 5), (3, 7), (-20, -10)]):
        (runtime[0] / f"{index}.finished").write_text(json.dumps({
            "ancestors": [42], "started_at": budget.started_at + begin,
            "ended_at": budget.started_at + end}))
    assert budget.elapsed() == pytest.approx(4)


def set_limit(directory, value):
    directory.mkdir(parents=True, exist_ok=True)
    temporary = directory / "config.tmp"
    temporary.write_text(json.dumps({"ffmpeg_slots": value}))
    temporary.replace(directory / "resource-limits.json")


def test_config_default_and_live_reload(runtime):
    assert gate.configured_limit() == 1
    set_limit(runtime[0], 2)
    assert gate.configured_limit() == 2
    set_limit(runtime[0], 1)
    assert gate.config_status()["ffmpeg_limit"] == 1


@pytest.mark.parametrize("value", [0, -1, 65, True, 1.5, "2", None])
def test_invalid_config_prevents_spawn(runtime, value):
    set_limit(runtime[0], value)
    with pytest.raises(ValueError, match="ffmpeg_slots"):
        subprocess.run([str(runtime[1]), str(runtime[2]), "0.01"])
    assert not runtime[2].exists()
    assert gate.config_status()["ffmpeg_limit"] is None
    assert not list(runtime[0].glob("*.wait"))


def test_corrupt_config_prevents_spawn(runtime):
    set_limit(runtime[0], 1)
    (runtime[0] / "resource-limits.json").write_text("{")
    with pytest.raises(ValueError, match="无法读取"):
        subprocess.run([str(runtime[1]), str(runtime[2]), "0.01"])
    assert not runtime[2].exists()


def test_two_slots_are_shared_across_three_processes(runtime):
    set_limit(runtime[0], 2)
    first = child(runtime, "0.9")
    until(lambda: len(lines(runtime[2])) == 1)
    second = child(runtime, "0.9")
    until(lambda: len(lines(runtime[2])) >= 2)
    assert [line.split()[0] for line in lines(runtime[2])][:2] == ["start", "start"]
    third = child(runtime, "0.1")
    for p in (first, second, third):
        _, errors = p.communicate(timeout=8)
        assert p.returncode == 0, errors
    active = peak = 0
    for line in lines(runtime[2]):
        active += 1 if line.startswith("start") else -1
        peak = max(peak, active)
    assert peak == 2 and active == 0


def test_lowering_limit_drains_existing_slots(runtime):
    set_limit(runtime[0], 2)
    first = child(runtime, "0.7")
    until(lambda: len(lines(runtime[2])) == 1)
    second = child(runtime, "1.2")
    until(lambda: len(lines(runtime[2])) >= 2)
    set_limit(runtime[0], 1)
    third = child(runtime, "0.01")
    for p in (first, second, third):
        _, errors = p.communicate(timeout=8)
        assert p.returncode == 0, errors
    assert [line.split()[0] for line in lines(runtime[2])] == ["start", "start", "end", "end", "start", "end"]
    assert json.loads((runtime[0] / "last-start.json").read_text())["limit"] == 1
