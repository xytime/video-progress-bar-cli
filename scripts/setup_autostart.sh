#!/usr/bin/env bash
# =======================================================================
# Setup macOS launchd Auto-start Agents for Video Pipeline
#
# # Modification History
# | Version | Date       | Author                         | Description               |
# |---------|------------|--------------------------------|---------------------------|
# | 1.0.0   | 2026-05-25 | Gemini_3.5_Flash_High_planning | 初始创建自动启动配置脚本  |
# =======================================================================

set -euo pipefail

# [Gemini_3.5_Flash_High_planning] 动态获取项目根目录
PRJ_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"

mkdir -p "$LAUNCH_AGENTS_DIR"

BOT_PLIST="$LAUNCH_AGENTS_DIR/com.videopipeline.bot.plist"
UI_PLIST="$LAUNCH_AGENTS_DIR/com.videopipeline.ui.plist"

echo "⚙️ Creating bot auto-start config at $BOT_PLIST..."
cat <<EOF > "$BOT_PLIST"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.videopipeline.bot</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PRJ_ROOT/.venv/bin/python</string>
        <string>$PRJ_ROOT/src/bot/telegram_bot.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$PRJ_ROOT</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONPATH</key>
        <string>$PRJ_ROOT/src</string>
    </dict>
    <key>StandardOutPath</key>
    <string>$PRJ_ROOT/output/bot.log</string>
    <key>StandardErrorPath</key>
    <string>$PRJ_ROOT/output/bot.log</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
EOF

echo "⚙️ Creating UI auto-start config at $UI_PLIST..."
cat <<EOF > "$UI_PLIST"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.videopipeline.ui</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PRJ_ROOT/.venv/bin/python</string>
        <string>$PRJ_ROOT/src/web/app.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$PRJ_ROOT</string>
    <key>StandardOutPath</key>
    <string>$PRJ_ROOT/output/dashboard.log</string>
    <key>StandardErrorPath</key>
    <string>$PRJ_ROOT/output/dashboard.log</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
EOF

echo "🛑 Unloading existing agents if any..."
launchctl unload "$BOT_PLIST" 2>/dev/null || true
launchctl unload "$UI_PLIST" 2>/dev/null || true

echo "🚀 Loading new agents into launchd..."
launchctl load "$BOT_PLIST"
launchctl load "$UI_PLIST"

echo "✅ Auto-start setup completed successfully!"
echo "🟢 Bot state: $(launchctl list | grep com.videopipeline.bot || echo 'not loaded')"
echo "🟢 UI state: $(launchctl list | grep com.videopipeline.ui || echo 'not loaded')"
