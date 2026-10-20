"""AGY 封面由宿主执行唯一超时边界。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-20 | Codex | 防止 CLI 内部空成功遮蔽封面真实超时，保留确定性封面回退条件。 |
"""
import subprocess

import pytest
from scripts import generate_english_agi_cover as cover


def test_cover_timeout_is_host_failure_instead_of_empty_cli_success(tmp_path, monkeypatch):
    def timed_out(args, **kwargs):
        assert args[args.index("--print-timeout") + 1] == "0s"
        assert kwargs["timeout"] == 47
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    monkeypatch.setattr(cover.subprocess, "run", timed_out)
    with pytest.raises(subprocess.TimeoutExpired):
        cover._run_agy(agy_bin="agy", model="test", work_dir=tmp_path,
                       prompt="test", timeout_seconds=17)
