#!/usr/bin/env bash
# 安装受管的 Codex 专属封面底图巡查调度。
#
# Modification History
# | Version | Date | Author | Description |
# | --- | --- | --- | --- |
# | 1.0.0 | 2026-07-31 | Codex | 新增每三分钟巡查安装器，保留其他 crontab 条目 |
# | 1.1.0 | 2026-07-31 | Codex | crontab 读取异常时停止安装，避免空表覆盖既有用户调度 |
# | 2.0.0 | 2026-08-02 | Codex | 改用用户 LaunchAgent 调度 Codex CLI，并仅清理旧 cron 托管块 |

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNNER="$PROJECT_ROOT/scripts/run_ai_cover_doer.sh"
LABEL="com.videopipeline.ai-cover-doer"
SOURCE_PLIST="$PROJECT_ROOT/scripts/$LABEL.plist"
TARGET_PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
SUPPORT_DIR="$HOME/Library/Application Support/VideoPrecessing"
LAUNCHER="$SUPPORT_DIR/ai-cover-doer-launcher.sh"
LAUNCHD_LOG_DIR="$HOME/Library/Logs/VideoPrecessing"
USER_ID="$(id -u)"
CRONTAB_BIN="${CRONTAB_BIN:-crontab}"
LAUNCHCTL_BIN="${LAUNCHCTL_BIN:-launchctl}"
PLUTIL_BIN="${PLUTIL_BIN:-plutil}"
INSTALL_BIN="${INSTALL_BIN:-install}"
TMP_CRONTAB="$(mktemp)"
TMP_CRONTAB_ERR="$(mktemp)"
trap 'rm -f "$TMP_CRONTAB" "$TMP_CRONTAB_ERR"' EXIT

[[ -x "$HOME/.local/bin/codex" ]] || {
    echo "Codex CLI is unavailable at $HOME/.local/bin/codex" >&2
    exit 1
}
[[ -f "$HOME/.codex/skills/ai-cover-doer/SKILL.md" ]] || {
    echo "ai-cover-doer skill is unavailable" >&2
    exit 1
}

chmod +x "$RUNNER"

if ! "$CRONTAB_BIN" -l > "$TMP_CRONTAB" 2> "$TMP_CRONTAB_ERR"; then
    if ! grep -qi "no crontab" "$TMP_CRONTAB_ERR"; then
        cat "$TMP_CRONTAB_ERR" >&2
        exit 1
    fi
fi

awk '
  /^# BEGIN Video Pipeline ai-cover-doer \(managed\)$/ { skip = 1; next }
  /^# END Video Pipeline ai-cover-doer \(managed\)$/ { skip = 0; next }
  skip { next }
  { print }
' "$TMP_CRONTAB" > "$TMP_CRONTAB.filtered"
mv "$TMP_CRONTAB.filtered" "$TMP_CRONTAB"

"$PLUTIL_BIN" -lint "$SOURCE_PLIST"
mkdir -p "$HOME/Library/LaunchAgents"
mkdir -p "$SUPPORT_DIR" "$LAUNCHD_LOG_DIR"
cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$PROJECT_ROOT"
LOG_FILE="\$PROJECT_ROOT/output/ai_cover_codex_runs.log"

mkdir -p "\$(dirname "\$LOG_FILE")"
exec "\$PROJECT_ROOT/scripts/run_ai_cover_doer.sh" >> "\$LOG_FILE" 2>&1
EOF
chmod 755 "$LAUNCHER"
"$LAUNCHCTL_BIN" bootout "gui/$USER_ID/$LABEL" 2>/dev/null || true
"$INSTALL_BIN" -m 644 "$SOURCE_PLIST" "$TARGET_PLIST"
"$LAUNCHCTL_BIN" bootstrap "gui/$USER_ID" "$TARGET_PLIST"
"$LAUNCHCTL_BIN" print "gui/$USER_ID/$LABEL" >/dev/null
"$CRONTAB_BIN" "$TMP_CRONTAB"
echo "已安装 LaunchAgent：${LABEL}，每 180 秒巡查 AI 封面队列。"
echo "已清理旧 crontab 托管块（如存在）。"
