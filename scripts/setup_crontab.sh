#!/usr/bin/env bash
# =======================================================================
# Setup macOS crontab @reboot Auto-start for Video Pipeline
#
# # Modification History
# | Version | Date       | Author                         | Description               |
# |---------|------------|--------------------------------|---------------------------|
# | 1.0.0   | 2026-05-25 | Gemini_3.5_Flash_High_planning | 初始创建 crontab 自动启动配置脚本 |
# | 1.1.0   | 2026-05-25 | Gemini_3.5_Flash_High_planning | 改为使用 vpanel 启动服务，修复 PID 丢失问题 |
# =======================================================================

set -euo pipefail

# [Gemini_3.5_Flash_High_planning] 动态获取项目根目录
PRJ_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# 创建临时文件
TMP_CRON=$(mktemp)

# 读取当前已有的 crontab 内容（忽略没有 crontab 时的错误）
crontab -l > "$TMP_CRON" 2>/dev/null || true

# 清理可能已经存在的本项目相关的 crontab 记录，避免重复添加
sed -i '' '/video-progress-bar-cli/d; /Video-precessing/d' "$TMP_CRON" 2>/dev/null || \
sed -i '/video-progress-bar-cli/d; /Video-precessing/d' "$TMP_CRON" 2>/dev/null || true

# 添加自动启动命令 (用路径标识以便于清理)
echo "⚙️ Adding @reboot entries to crontab..."
cat <<EOF >> "$TMP_CRON"
# [video-progress-bar-cli] Auto-start Telegram Bot on reboot
@reboot "$PRJ_ROOT/vpanel" bot start
# [video-progress-bar-cli] Auto-start Control Panel Dashboard on reboot
@reboot "$PRJ_ROOT/vpanel" ui start
EOF

# 加载新的 crontab
crontab "$TMP_CRON"
rm -f "$TMP_CRON"

echo "✅ Crontab auto-start setup completed successfully!"
echo "📄 Current crontab entries:"
crontab -l | grep "video-progress-bar-cli"

# 立即启动服务（免去重启等待）
echo "🚀 Starting services immediately..."
# 1. 启动 Bot
"$PRJ_ROOT/vpanel" bot start
# 2. 启动 Dashboard
"$PRJ_ROOT/vpanel" ui start

sleep 2
echo "🟢 Current Bot Process:"
"$PRJ_ROOT/vpanel" bot status
echo "🟢 Current UI Process:"
"$PRJ_ROOT/vpanel" ui status
