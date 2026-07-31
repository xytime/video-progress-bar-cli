#!/usr/bin/env bash
# 执行 Codex 专属底图巡查；由受管 cron 每三分钟调用。
#
# Modification History
# | Version | Date | Author | Description |
# | --- | --- | --- | --- |
# | 1.0.0 | 2026-07-31 | Codex | 新增带互斥锁和本地运行证据的 Codex 封面队列巡查入口 |
# | 1.1.0 | 2026-07-31 | Codex | 无任务巡查也写入开始、结束和退出码，形成可审计运行回执 |
# | 1.2.0 | 2026-07-31 | Codex | cron 下固定关闭 stdin，避免 Codex 巡查完成后持续等待输入并占用互斥锁 |
# | 1.3.0 | 2026-07-31 | Codex | 先用项目协议判定是否有可领取任务，空队列不唤起 Codex 会话 |

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CODEX_BIN="${CODEX_BIN:-$HOME/.local/bin/codex}"
PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
LOG_DIR="$PROJECT_ROOT/output"
LOCK_DIR="$LOG_DIR/.ai_cover_doer.lock"
LAST_MESSAGE="$LOG_DIR/ai_cover_codex_last_run.txt"

mkdir -p "$LOG_DIR"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    printf '%s ai-cover-doer skipped: another run is active\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    exit 0
fi
trap 'rmdir "$LOCK_DIR"' EXIT

if [[ ! -x "$CODEX_BIN" ]]; then
    printf '%s ai-cover-doer failed: Codex executable not found at %s\n' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$CODEX_BIN" >&2
    exit 1
fi

cd "$PROJECT_ROOT"

set +e
eligibility="$({ PYTHONPATH="$PROJECT_ROOT/src" "$PYTHON_BIN" - <<'PY'
from pathlib import Path
from video_processing.ai_cover_queue import AICoverQueue

root = Path.cwd()
queue = AICoverQueue(root / "ai-cover-queue", root / "ai-cover-finish")
print("eligible" if queue.has_eligible_task() else "empty")
PY
} 2>&1)"
eligibility_status=$?
set -e
if [[ $eligibility_status -ne 0 ]]; then
    printf '%s ai-cover-doer failed: eligibility check: %s\n' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$eligibility" >&2
    exit "$eligibility_status"
fi
if [[ "$eligibility" == "empty" ]]; then
    printf '%s ai-cover-doer skipped_no_eligible_task\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    exit 0
fi

PROMPT='执行 /ai-cover-doer 技能。仅处理 /Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/ai-cover-queue 下当前可领取的任务。严格遵守技能的 claim、deadline、原子 result.json 和视觉验收规则；无任务时直接结束。绝不发布视频、编辑平台、写最终 JPEG、修改数据库或改写任务 Markdown。'

started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf '%s ai-cover-doer started\n' "$started_at"
set +e
"$CODEX_BIN" exec \
    --cd "$PROJECT_ROOT" \
    --sandbox workspace-write \
    --add-dir "$HOME/.codex/generated_images" \
    --output-last-message "$LAST_MESSAGE" \
    "$PROMPT" < /dev/null
exit_code=$?
set -e
printf '%s ai-cover-doer finished exit_code=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$exit_code"
exit "$exit_code"
