#!/usr/bin/env bash
# 安装受管的 Codex 专属封面底图巡查调度。
#
# Modification History
# | Version | Date | Author | Description |
# | --- | --- | --- | --- |
# | 1.0.0 | 2026-07-31 | Codex | 新增每三分钟巡查安装器，保留其他 crontab 条目 |
# | 1.1.0 | 2026-07-31 | Codex | crontab 读取异常时停止安装，避免空表覆盖既有用户调度 |

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNNER="$PROJECT_ROOT/scripts/run_ai_cover_doer.sh"
CRONTAB_BIN="${CRONTAB_BIN:-crontab}"
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

cat >> "$TMP_CRONTAB" <<EOF
# BEGIN Video Pipeline ai-cover-doer (managed)
*/3 * * * * "$RUNNER" >> "$PROJECT_ROOT/output/ai_cover_codex_runs.log" 2>&1
# END Video Pipeline ai-cover-doer (managed)
EOF

"$CRONTAB_BIN" "$TMP_CRONTAB"
"$CRONTAB_BIN" -l | sed -n '/BEGIN Video Pipeline ai-cover-doer/,/END Video Pipeline ai-cover-doer/p'
