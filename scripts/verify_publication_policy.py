"""校验发布规则的受控配置源是否一致。

检查代码默认值、.env.example 与本机 .env；可选检查已安装 crontab 是否只使用
自动发布巡航入口。该脚本只读，不触发下载、加工或发布。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-31 | Codex | 新增发布窗口策略与巡航调度的一致性校验 |
| 1.0.1 | 2026-07-31 | Codex | 巡航命令校验改为前缀匹配，允许保留 crontab 日志重定向 |
| 1.0.2 | 2026-07-31 | Codex | 校验进程环境覆盖与后台预加工巡航，避免规则只在文件层面一致 |
| 1.1.0 | 2026-08-02 | Codex | 校验关闭窗口限制后的每分钟自动发布巡航 |
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
    "ENABLE_PUBLIC_PUBLISH_WINDOWS": "enable_public_publish_windows",
    "PUBLIC_PUBLISH_WINDOWS": "public_publish_windows",
    "PUBLIC_PUBLISH_HOLIDAY_WINDOWS": "public_publish_holiday_windows",
    "WECHAT_DEFERRED_RECOVERY_DAILY_LIMIT": "wechat_deferred_recovery_daily_limit",
}
CRON_BEGIN = "# BEGIN Video Pipeline public-window cruise (managed)"
CRON_END = "# END Video Pipeline public-window cruise (managed)"


def _settings_default(field_name: str) -> str:
    value = Settings.model_fields[field_name].default
    return str(value).lower() if isinstance(value, bool) else str(value)


def _settings_value(value: object) -> str:
    """按 .env 的布尔值表示法比较 Settings 值。"""
    return str(value).lower() if isinstance(value, bool) else str(value)


def _check_policy_sources() -> list[str]:
    errors: list[str] = []
    env_example = dotenv_values(PROJECT_ROOT / ".env.example")
    production_env = dotenv_values(PROJECT_ROOT / ".env")
    effective_settings = Settings()

    for env_name, field_name in POLICY_FIELDS.items():
        expected = _settings_default(field_name)
        for source_name, source_values in ((".env.example", env_example), (".env", production_env)):
            actual = source_values.get(env_name)
            if actual != expected:
                errors.append(
                    f"{env_name}: Settings 默认值为 {expected!r}，{source_name} 为 {actual!r}"
                )
        effective = _settings_value(getattr(effective_settings, field_name))
        if effective != expected:
            errors.append(
                f"{env_name}: 当前进程有效值为 {effective!r}，覆盖了批准默认值 {expected!r}"
            )
    return errors


def _check_installed_schedule() -> list[str]:
    expected_command = (
        f'* * * * * cd "{PROJECT_ROOT}" && '
        f'PYTHONPATH="{SRC_ROOT}" "{PROJECT_ROOT / ".venv/bin/python"}" '
        f'"{PROJECT_ROOT / "scripts/run_publication_window.py"}"'
    )
    result = subprocess.run(["crontab", "-l"], text=True, capture_output=True, check=False)
    if result.returncode != 0:
        return [f"无法读取已安装 crontab：{result.stderr.strip() or '无 crontab'}"]

    lines = result.stdout.splitlines()
    if CRON_BEGIN not in lines or CRON_END not in lines:
        return ["未找到受管的自动发布巡航 crontab 区块。"]
    if not any(line.startswith(expected_command) for line in lines):
        return ["受管 crontab 区块缺少预期的每分钟自动发布巡航命令。"]
    if any("run_background_preparation.py" in line for line in lines):
        return ["受管 crontab 区块仍包含已停用的窗口外预加工巡航命令。"]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="校验发布规则配置与自动发布巡航调度")
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

    print("发布规则校验通过：代码默认、.env.example、本机 .env 与当前有效配置一致。")
    if args.check_installed_schedule:
        print("已安装 crontab 使用受管的每分钟自动发布巡航入口。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
