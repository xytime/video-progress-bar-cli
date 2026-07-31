"""校验发布规则的受控配置源是否一致。

检查代码默认值、.env.example 与本机 .env；可选检查已安装 crontab 是否只使用
窗口巡航入口。该脚本只读，不触发下载、加工或发布。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-31 | Codex | 新增发布窗口策略与巡航调度的一致性校验 |
| 1.0.1 | 2026-07-31 | Codex | 巡航命令校验改为前缀匹配，允许保留 crontab 日志重定向 |
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from config.settings import Settings


POLICY_FIELDS = {
    "PUBLIC_PUBLISH_WINDOWS": "public_publish_windows",
    "PUBLIC_PUBLISH_HOLIDAY_WINDOWS": "public_publish_holiday_windows",
    "WECHAT_DEFERRED_RECOVERY_DAILY_LIMIT": "wechat_deferred_recovery_daily_limit",
}
CRON_BEGIN = "# BEGIN Video Pipeline public-window cruise (managed)"
CRON_END = "# END Video Pipeline public-window cruise (managed)"


def _settings_default(field_name: str) -> str:
    return str(Settings.model_fields[field_name].default)


def _check_policy_sources() -> list[str]:
    errors: list[str] = []
    env_example = dotenv_values(PROJECT_ROOT / ".env.example")
    production_env = dotenv_values(PROJECT_ROOT / ".env")

    for env_name, field_name in POLICY_FIELDS.items():
        expected = _settings_default(field_name)
        for source_name, source_values in ((".env.example", env_example), (".env", production_env)):
            actual = source_values.get(env_name)
            if actual != expected:
                errors.append(
                    f"{env_name}: Settings 默认值为 {expected!r}，{source_name} 为 {actual!r}"
                )
    return errors


def _check_installed_schedule() -> list[str]:
    expected_command = (
        f'*/15 6-21 * * * cd "{PROJECT_ROOT}" && '
        f'PYTHONPATH="{SRC_ROOT}" "{PROJECT_ROOT / ".venv/bin/python"}" '
        f'"{PROJECT_ROOT / "scripts/run_publication_window.py"}"'
    )
    result = subprocess.run(["crontab", "-l"], text=True, capture_output=True, check=False)
    if result.returncode != 0:
        return [f"无法读取已安装 crontab：{result.stderr.strip() or '无 crontab'}"]

    lines = result.stdout.splitlines()
    if CRON_BEGIN not in lines or CRON_END not in lines:
        return ["未找到受管的发布窗口巡航 crontab 区块。"]
    if not any(line.startswith(expected_command) for line in lines):
        return ["受管 crontab 区块缺少预期的 15 分钟窗口巡航命令。"]
    if any("video_processing.pipeline_manager" in line for line in lines):
        return ["仍存在旧的直连 PipelineManager crontab 条目。"]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="校验发布规则配置与窗口巡航调度")
    parser.add_argument("--check-installed-schedule", action="store_true", help="同时校验已安装 crontab")
    args = parser.parse_args(argv)

    errors = _check_policy_sources()
    if args.check_installed_schedule:
        errors.extend(_check_installed_schedule())
    if errors:
        print("发布规则校验失败：")
        for error in errors:
            print(f"- {error}")
        return 1

    print("发布规则校验通过：代码默认、.env.example、本机 .env 一致。")
    if args.check_installed_schedule:
        print("已安装 crontab 使用受管的 15 分钟窗口巡航入口。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
