#!/usr/bin/env bash
# 安装每日 07:00、16:30 英语世界短视频生产调度。
#
# 该调度只允许制作并发 Telegram 人工审核材料，不能投稿视频号。
#
# Modification History
# | Version | Date | Author | Description |
# | --- | --- | --- | --- |
# | 1.1.0 | 2026-08-23 | Codex | 为调度器建立系统卷持久日志目录，并在重载后输出实际 LaunchAgent 状态。 |
# | 2.0.0 | 2026-08-24 | Codex | 改由 LaunchAgent 直接执行 Python 协调器，避免 shell 读取外接盘脚本被系统拦截。 |
# | 2.1.0 | 2026-08-24 | Codex | 增加 16:30 独立制作机会，仍只推送 Telegram 人工审核。 |
# | 1.0.0 | 2026-08-22 | Codex | 新增独立英语世界日更 LaunchAgent 安装器。 |

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.videopipeline.english-world-daily"
SOURCE_PLIST="$PROJECT_ROOT/scripts/$LABEL.plist"
TARGET_PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LAUNCHD_LOG_DIR="$HOME/Library/Logs/VideoPrecessing"
USER_ID="$(id -u)"

plutil -lint "$SOURCE_PLIST"
[[ -f "$PROJECT_ROOT/scripts/run_english_world_daily.py" ]] || {
    echo "英语世界 Python 协调器不存在：$PROJECT_ROOT/scripts/run_english_world_daily.py" >&2
    exit 1
}
mkdir -p "$HOME/Library/LaunchAgents"
mkdir -p "$PROJECT_ROOT/output/english_world_daily"
mkdir -p "$LAUNCHD_LOG_DIR"
launchctl bootout "gui/$USER_ID/$LABEL" 2>/dev/null || true
install -m 644 "$SOURCE_PLIST" "$TARGET_PLIST"
launchctl bootstrap "gui/$USER_ID" "$TARGET_PLIST"
launchctl print "gui/$USER_ID/$LABEL" >/dev/null

echo "✅ 已安装：每天 07:00、16:30 仅制作英语世界短视频并发送 Telegram 审核；不提交视频号。"
