#!/usr/bin/env bash
# 安装受管的 Codex 专属封面底图巡查调度。
#
# Modification History
# | Version | Date | Author | Description |
# | --- | --- | --- | --- |
# | 1.0.0 | 2026-07-31 | Codex | 新增每三分钟巡查安装器，保留其他 crontab 条目 |

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNNER="$PROJECT_ROOT/scripts/run_ai_cover_doer.sh"
TMP_CRONTAB="$(mktemp)"
trap 'rm -f "$TMP_CRONTAB"' EXIT

[[ -x "$HOME/.local/bin/codex" ]] || {
    echo "Codex CLI is unavailable at $HOME/.local/bin/codex" >&2
    exit 1
}
[[ -f "$HOME/.codex/skills/ai-cover-doer/SKILL.md" ]] || {
    echo "ai-cover-doer skill is unavailable" >&2
    exit 1
}

chmod +x "$RUNNER"
crontab -l > "$TMP_CRONTAB" 2>/dev/null || true

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

crontab "$TMP_CRONTAB"
crontab -l | sed -n '/BEGIN Video Pipeline ai-cover-doer/,/END Video Pipeline ai-cover-doer/p'
