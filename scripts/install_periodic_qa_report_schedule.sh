#!/usr/bin/env bash
# 安装每三小时 Telegram 管线质检 LaunchAgent。
#
# Modification History
# | Version | Date       | Author | Description |
# |---------|------------|--------|-------------|
# | 1.0.0 | 2026-07-28 | Codex | 安装独立只读质检任务，每三小时第5分钟投递 Telegram |

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.videopipeline.periodic-qa-report"
SOURCE_PLIST="$PROJECT_ROOT/scripts/$LABEL.plist"
TARGET_PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
USER_ID="$(id -u)"

plutil -lint "$SOURCE_PLIST"
mkdir -p "$HOME/Library/LaunchAgents"
launchctl bootout "gui/$USER_ID/$LABEL" 2>/dev/null || true
install -m 644 "$SOURCE_PLIST" "$TARGET_PLIST"
launchctl bootstrap "gui/$USER_ID" "$TARGET_PLIST"
launchctl print "gui/$USER_ID/$LABEL" >/dev/null

echo "已安装：每三小时第 5 分钟向 Telegram 推送只读管线质检报告。"
