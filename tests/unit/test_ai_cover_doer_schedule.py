"""Codex 专属封面巡查调度脚本测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-31 | Codex | 防止 crontab 读取异常时覆盖既有用户调度 |
| 2.0.0 | 2026-08-02 | Codex | 覆盖 LaunchAgent 安装后旧 cron 清理失败不覆盖用户调度 |
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
INSTALLER = PROJECT_ROOT / "scripts" / "install_ai_cover_doer_schedule.sh"


def test_installer_does_not_replace_crontab_after_read_error(tmp_path: Path):
    marker = tmp_path / "installed.txt"
    fake_crontab = tmp_path / "crontab"
    fake_launchctl = tmp_path / "launchctl"
    fake_plutil = tmp_path / "plutil"
    fake_install = tmp_path / "install"
    fake_crontab.write_text(
        "#!/usr/bin/env bash\n"
        "if [[ $1 == '-l' ]]; then\n"
        "  echo 'permission denied' >&2\n"
        "  exit 2\n"
        "fi\n"
        f"echo installed > {marker}\n",
        encoding="utf-8",
    )
    fake_launchctl.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_plutil.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_install.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_crontab.chmod(0o755)
    fake_launchctl.chmod(0o755)
    fake_plutil.chmod(0o755)
    fake_install.chmod(0o755)

    result = subprocess.run(
        [str(INSTALLER)],
        cwd=PROJECT_ROOT,
        env={
            **os.environ,
            "CRONTAB_BIN": str(fake_crontab),
            "LAUNCHCTL_BIN": str(fake_launchctl),
            "PLUTIL_BIN": str(fake_plutil),
            "INSTALL_BIN": str(fake_install),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "permission denied" in result.stderr
    assert not marker.exists()
