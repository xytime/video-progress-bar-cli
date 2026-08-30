#!/usr/bin/env bash
# 安装每日 07:00、16:30 英语世界短视频生产调度。
#
# 该调度只负责制作并调用独立 Telegram 审计入口；视频号动作仅可由该入口已配置的
# 单次、账本受控策略执行，安装器本身不调用上传器。
#
# Modification History
# | Version | Date | Author | Description |
# | --- | --- | --- | --- |
# | 1.1.0 | 2026-08-23 | Codex | 为调度器建立系统卷持久日志目录，并在重载后输出实际 LaunchAgent 状态。 |
# | 2.0.0 | 2026-08-24 | Codex | 改由 LaunchAgent 直接执行 Python 协调器，避免 shell 读取外接盘脚本被系统拦截。 |
# | 2.1.0 | 2026-08-24 | Codex | 增加 16:30 独立制作机会，仍只推送 Telegram 人工审核。 |
# | 2.2.0 | 2026-08-27 | Codex | 同时安装窗口后回执监测器；仅在原窗口完全缺席时补发起一次协调器。 |
# | 2.3.0 | 2026-08-30 | Codex | 安装前强制验证项目 venv 解释器及配置依赖，拒绝 pyenv Python 运行时漂移。 |
# | 2.4.0 | 2026-08-30 | Codex | 安装时按当前项目根目录和用户目录渲染 plist，安装后逐字段核验运行路径。 |
# | 1.0.0 | 2026-08-22 | Codex | 新增独立英语世界日更 LaunchAgent 安装器。 |

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.videopipeline.english-world-daily"
MONITOR_LABEL="com.videopipeline.english-world-monitor"
SOURCE_PLIST="$PROJECT_ROOT/scripts/$LABEL.plist"
MONITOR_SOURCE_PLIST="$PROJECT_ROOT/scripts/$MONITOR_LABEL.plist"
TARGET_PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
MONITOR_TARGET_PLIST="$HOME/Library/LaunchAgents/$MONITOR_LABEL.plist"
LAUNCHD_LOG_DIR="$HOME/Library/Logs/VideoPrecessing"
USER_ID="$(id -u)"
VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python"
RENDER_DIR="$(mktemp -d)"
trap 'rm -rf "$RENDER_DIR"' EXIT
RENDERED_PLIST="$RENDER_DIR/$LABEL.plist"
RENDERED_MONITOR_PLIST="$RENDER_DIR/$MONITOR_LABEL.plist"

plutil -lint "$SOURCE_PLIST"
plutil -lint "$MONITOR_SOURCE_PLIST"
[[ -f "$PROJECT_ROOT/scripts/run_english_world_daily.py" ]] || {
    echo "英语世界 Python 协调器不存在：$PROJECT_ROOT/scripts/run_english_world_daily.py" >&2
    exit 1
}
[[ -f "$PROJECT_ROOT/scripts/monitor_english_world_daily.py" ]] || {
    echo "英语世界窗口后监测器不存在：$PROJECT_ROOT/scripts/monitor_english_world_daily.py" >&2
    exit 1
}
[[ -x "$VENV_PYTHON" ]] || {
    echo "项目 venv Python 不可执行：$VENV_PYTHON" >&2
    exit 1
}
env -i \
    HOME="$HOME" \
    PATH="/usr/bin:/bin:/usr/sbin:/sbin" \
    PYTHONPATH="$PROJECT_ROOT/src" \
    "$VENV_PYTHON" -c "from config.settings import settings; print(type(settings).__name__)" >/dev/null

render_plist() {
    local source_plist="$1"
    local rendered_plist="$2"
    "$VENV_PYTHON" - "$source_plist" "$rendered_plist" \
        "$PROJECT_ROOT" "$HOME" "$VENV_PYTHON" "$LAUNCHD_LOG_DIR" <<'PY'
import plistlib
import sys

source, target, project_root, user_home, venv_python, log_dir = sys.argv[1:]
replacements = {
    "__PROJECT_ROOT__": project_root,
    "__USER_HOME__": user_home,
    "__VENV_PYTHON__": venv_python,
    "__LAUNCHD_LOG_DIR__": log_dir,
}

def replace(value):
    if isinstance(value, str):
        for token, replacement in replacements.items():
            value = value.replace(token, replacement)
        return value
    if isinstance(value, list):
        return [replace(item) for item in value]
    if isinstance(value, dict):
        return {key: replace(item) for key, item in value.items()}
    return value

with open(source, "rb") as stream:
    configuration = replace(plistlib.load(stream))
with open(target, "wb") as stream:
    plistlib.dump(configuration, stream, sort_keys=False)
PY
}

validate_rendered_plist() {
    local rendered_plist="$1"
    local expected_script="$2"
    "$VENV_PYTHON" - "$rendered_plist" "$PROJECT_ROOT" "$VENV_PYTHON" "$expected_script" <<'PY'
import plistlib
import sys

path, project_root, venv_python, expected_script = sys.argv[1:]
with open(path, "rb") as stream:
    configuration = plistlib.load(stream)
arguments = configuration.get("ProgramArguments", [])
environment = configuration.get("EnvironmentVariables", {})
expected = {
    "python": arguments[0] if arguments else None,
    "script": arguments[1] if len(arguments) > 1 else None,
    "working_directory": configuration.get("WorkingDirectory"),
    "pythonpath": environment.get("PYTHONPATH"),
}
required = {
    "python": venv_python,
    "script": expected_script,
    "working_directory": project_root,
    "pythonpath": project_root + "/src",
}
if expected != required:
    raise SystemExit(f"LaunchAgent 路径渲染错误: expected={required!r} actual={expected!r}")
PY
}

render_plist "$SOURCE_PLIST" "$RENDERED_PLIST"
render_plist "$MONITOR_SOURCE_PLIST" "$RENDERED_MONITOR_PLIST"
plutil -lint "$RENDERED_PLIST"
plutil -lint "$RENDERED_MONITOR_PLIST"
validate_rendered_plist "$RENDERED_PLIST" "$PROJECT_ROOT/scripts/run_english_world_daily.py"
validate_rendered_plist "$RENDERED_MONITOR_PLIST" "$PROJECT_ROOT/scripts/monitor_english_world_daily.py"
mkdir -p "$HOME/Library/LaunchAgents"
mkdir -p "$PROJECT_ROOT/output/english_world_daily"
mkdir -p "$LAUNCHD_LOG_DIR"
launchctl bootout "gui/$USER_ID/$LABEL" 2>/dev/null || true
launchctl bootout "gui/$USER_ID/$MONITOR_LABEL" 2>/dev/null || true
install -m 644 "$RENDERED_PLIST" "$TARGET_PLIST"
install -m 644 "$RENDERED_MONITOR_PLIST" "$MONITOR_TARGET_PLIST"
launchctl bootstrap "gui/$USER_ID" "$TARGET_PLIST"
launchctl bootstrap "gui/$USER_ID" "$MONITOR_TARGET_PLIST"
launchctl print "gui/$USER_ID/$LABEL" >/dev/null
launchctl print "gui/$USER_ID/$MONITOR_LABEL" >/dev/null

echo "✅ 已安装：每天 07:00、16:30 生产英语世界短视频；09:15、19:00 核验本次 Telegram 回执，并仅对完全缺席窗口补发起一次。视频号动作仍只走既有的独立受控入口。"
