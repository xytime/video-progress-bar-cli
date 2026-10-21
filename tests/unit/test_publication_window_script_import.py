"""巡检直接按脚本启动时，延迟导入也必须能找到项目包。"""

import subprocess
import sys
from pathlib import Path


def test_direct_script_bootstrap_resolves_scheduled_readback(tmp_path):
    root = Path(__file__).resolve().parents[2]
    script = root / "scripts/run_publication_window.py"
    # 新解释器不继承 pytest 的项目搜索路径；只加载入口，不执行巡检或发布。
    probe = """
import importlib
import runpy
import sys
namespace = runpy.run_path(sys.argv[1], run_name='import_probe')
module = importlib.import_module('scripts.wechat_scheduled_readback')
assert module.__file__ == str(namespace['PROJECT_ROOT'] / 'scripts/wechat_scheduled_readback.py')
assert callable(module.reconcile_new_submissions)
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", probe, str(script)],
        cwd=tmp_path, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
