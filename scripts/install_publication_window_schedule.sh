#!/usr/bin/env bash
# 安装 Video Pipeline 的受管自动发布巡航调度。
#
# # Modification History
# | Version | Date | Author | Description |
# | --- | --- | --- | --- |
# | 1.0.0 | 2026-07-31 | Codex | 以 Settings 窗口判定替代硬编码的单点发布 cron，并保留其他项目条目 |
# | 1.1.0 | 2026-07-31 | Codex | 加入源字幕先行后台预加工巡航，并收窄旧 cron 清理范围 |
# | 1.2.0 | 2026-08-02 | Codex | 改为每分钟完整流水线巡航，关闭按时段等待与冗余预加工巡航 |

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
TMP_CRONTAB="$(mktemp)"
trap 'rm -f "$TMP_CRONTAB"' EXIT

PYTHONPATH="$PROJECT_ROOT/src" "$PYTHON_BIN" "$PROJECT_ROOT/scripts/verify_publication_policy.py"
crontab -l > "$TMP_CRONTAB" 2>/dev/null || true

# 清除上一版受管区块，以及已知的历史单点发布条目；不要误删其他项目的
# PipelineManager 调度，以免安装脚本越权修改用户自定义任务。
awk '
  /^# BEGIN Video Pipeline public-window cruise \(managed\)$/ { skip = 1; next }
  /^# END Video Pipeline public-window cruise \(managed\)$/ { skip = 0; next }
  skip { next }
  /PYTHONPATH=.*video_processing\.pipeline_manager/ { next }
  /run_kuaishou_history_migration/ { next }
  /^# \[(工作日上午视频发布|工作日午间视频发布|工作日傍晚视频发布|视频发布\+平台审核|休息日视频发布候选|快手历史迁移)\]/ { next }
  { print }
' "$TMP_CRONTAB" > "$TMP_CRONTAB.filtered"
mv "$TMP_CRONTAB.filtered" "$TMP_CRONTAB"

cat >> "$TMP_CRONTAB" <<EOF
# BEGIN Video Pipeline public-window cruise (managed)
# 每分钟巡航；成片与审查完成后立即提交。重叠轮次由入口锁跳过。
* * * * * cd "$PROJECT_ROOT" && PYTHONPATH="$PROJECT_ROOT/src" "$PYTHON_BIN" "$PROJECT_ROOT/scripts/run_publication_window.py" >> "$PROJECT_ROOT/output/pipeline_window.log" 2>&1
# END Video Pipeline public-window cruise (managed)
EOF

crontab "$TMP_CRONTAB"
PYTHONPATH="$PROJECT_ROOT/src" "$PYTHON_BIN" "$PROJECT_ROOT/scripts/verify_publication_policy.py" --check-installed-schedule
