#!/usr/bin/env bash
# 每日 API 用量与 DeepSeek 余额日报安装器。
#
# # Modification History
# | Version | Date       | Author | Description |
# | ------- | ---------- | ------ | ----------- |
# | 1.0.0   | 2026-07-17 | Codex  | 安装每日 09:00 LaunchAgent，执行只读日报并推送 Telegram |

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_PLIST="$PROJECT_ROOT/scripts/com.videopipeline.daily-ops.plist"
TARGET_PLIST="$HOME/Library/LaunchAgents/com.videopipeline.daily-ops.plist"
USER_ID="$(id -u)"

plutil -lint "$SOURCE_PLIST"
mkdir -p "$HOME/Library/LaunchAgents"
launchctl bootout "gui/$USER_ID/com.videopipeline.daily-ops" 2>/dev/null || true
install -m 644 "$SOURCE_PLIST" "$TARGET_PLIST"
launchctl bootstrap "gui/$USER_ID" "$TARGET_PLIST"
launchctl print "gui/$USER_ID/com.videopipeline.daily-ops" >/dev/null

echo "✅ 已安装：每天 09:00 推送 API 用量与 DeepSeek 余额日报到 Telegram。"
