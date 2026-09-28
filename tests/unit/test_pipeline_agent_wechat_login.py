"""验证手机扫码入口不会继承后台 Bot 不可用的标准输入。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-29 | Codex | 用不可读标准输入验证扫码登录子进程独立启动 |
"""

import json
import subprocess
import sys
from pathlib import Path


def test_wechat_login_starts_when_bot_standard_input_is_invalid(tmp_path):
    """父进程继续活着但 stdin 不可读时，登录进程仍能启动并读取空输入。"""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (tmp_path / "output").mkdir()
    probe = scripts / "wechat_uploader.py"
    probe.write_text(
        "import json, sys\n"
        "from pathlib import Path\n"
        "Path('started.json').write_text(json.dumps({"
        "'args': sys.argv[1:], 'stdin': sys.stdin.read()}))\n",
        encoding="utf-8",
    )
    # 隔离环境不允许创建 PTY；用目录 FD 重现子 Python 标准流初始化失败。
    parent = """
import json
import os
import subprocess
import sys
from pathlib import Path
from bot.pipeline_agent import PipelineAgent

agent = PipelineAgent.__new__(PipelineAgent)
agent.project_root = Path(sys.argv[1])
agent.output_dir = agent.project_root / 'output'
agent.venv_python = sys.executable
invalid_input = os.open(agent.project_root, os.O_RDONLY)
os.dup2(invalid_input, 0)
os.close(invalid_input)
control = subprocess.run([sys.executable, '-c', 'pass'], capture_output=True)
assert control.returncode != 0, 'Invalid stdin did not reproduce startup failure'
assert b'init_sys_streams' in control.stderr, control.stderr
result = json.loads(agent.trigger_wechat_login())
assert result['ok'], result
_, status = os.waitpid(-1, 0)
sys.exit(os.waitstatus_to_exitcode(status))
"""
    result = subprocess.run(
        [sys.executable, "-c", parent, str(tmp_path)],
        cwd=Path(__file__).resolve().parents[2],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    started = json.loads((tmp_path / "started.json").read_text())
    assert started["stdin"] == ""
    assert started["args"] == [
        "--login-only", "--relogin", "--state", str(tmp_path / "output/wechat_state.json")
    ]
