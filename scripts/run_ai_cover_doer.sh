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
# | 1.4.0 | 2026-07-31 | Codex | 增加 PID/时限锁回收和日志轮转，避免异常终止永久阻塞或日志无限增长 |
# | 1.5.0 | 2026-07-31 | Codex | 仅在确认有可领取底图任务后检查并启动 Codex |
# | 1.6.0 | 2026-07-31 | Codex | 默认使用 gpt-5.5 和 medium 推理强度启动 Codex 子任务 |
# | 1.7.0 | 2026-07-31 | Codex | 修复运行中锁误回收、日志轮转描述符和预检输出容错问题 |

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CODEX_BIN="${CODEX_BIN:-$HOME/.local/bin/codex}"
CODEX_MODEL="${CODEX_MODEL:-gpt-5.5}"
CODEX_REASONING_EFFORT="${CODEX_REASONING_EFFORT:-medium}"
PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
LOG_DIR="$PROJECT_ROOT/output"
LOCK_DIR="$LOG_DIR/.ai_cover_doer.lock"
LAST_MESSAGE="$LOG_DIR/ai_cover_codex_last_run.txt"
RUN_LOG="$LOG_DIR/ai_cover_codex_runs.log"
LOCK_INITIALIZING_GRACE_SECONDS=30
MAX_LOG_BYTES=5242880

lock_is_live() {
    local pid=""
    local lock_mtime=0
    local now

    if [[ -f "$LOCK_DIR/pid" ]]; then
        pid="$(tr -d '[:space:]' < "$LOCK_DIR/pid")"
        if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
            return 0
        fi
    fi

    # 创建锁和写入 pid 之间的极短窗口内，不让下一轮抢走刚创建的锁。
    now="$(date +%s)"
    lock_mtime="$(date -r "$LOCK_DIR" +%s 2>/dev/null || printf '0')"
    (( now - lock_mtime < LOCK_INITIALIZING_GRACE_SECONDS ))
}

rotate_run_log() {
    local log_size=0

    [[ -f "$RUN_LOG" ]] || return
    log_size="$(wc -c < "$RUN_LOG")"
    if (( log_size >= MAX_LOG_BYTES )); then
        mv -f "$RUN_LOG" "$RUN_LOG.1"
        : > "$RUN_LOG"
        # cron 在脚本启动前已打开重定向；轮转后需把同一描述符重新指向新文件。
        if [[ -e /dev/fd/1 && /dev/fd/1 -ef "$RUN_LOG.1" ]]; then
            exec >> "$RUN_LOG"
        fi
        if [[ -e /dev/fd/2 && /dev/fd/2 -ef "$RUN_LOG.1" ]]; then
            exec 2>> "$RUN_LOG"
        fi
    fi
}

mkdir -p "$LOG_DIR"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    if lock_is_live; then
        printf '%s ai-cover-doer skipped: another run is active\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        exit 0
    fi
    stale_lock="$LOCK_DIR.stale.$$"
    if ! mv "$LOCK_DIR" "$stale_lock" 2>/dev/null || ! mkdir "$LOCK_DIR"; then
        printf '%s ai-cover-doer skipped: lock recovery raced with another run\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        exit 0
    fi
    rm -rf "$stale_lock"
fi
printf '%s\n' "$$" > "$LOCK_DIR/pid"
printf '%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$LOCK_DIR/started_at"
trap 'rm -rf "$LOCK_DIR"' EXIT
rotate_run_log

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
case "$eligibility" in
    empty)
        printf '%s ai-cover-doer skipped_no_eligible_task\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        exit 0
        ;;
    eligible)
        ;;
    *)
        printf '%s ai-cover-doer failed: unexpected eligibility result: %s\n' \
            "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$eligibility" >&2
        exit 1
        ;;
esac

if [[ ! -x "$CODEX_BIN" ]]; then
    printf '%s ai-cover-doer failed: Codex executable not found at %s\n' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$CODEX_BIN" >&2
    exit 1
fi

PROMPT='执行 /ai-cover-doer 技能。仅处理 /Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/ai-cover-queue 下当前可领取的任务。严格遵守技能的 claim、deadline、原子 result.json 和视觉验收规则；无任务时直接结束。绝不发布视频、编辑平台、写最终 JPEG、修改数据库或改写任务 Markdown。'

started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf '%s ai-cover-doer started\n' "$started_at"
set +e
"$CODEX_BIN" exec \
    --cd "$PROJECT_ROOT" \
    --model "$CODEX_MODEL" \
    --config "model_reasoning_effort=\"$CODEX_REASONING_EFFORT\"" \
    --sandbox workspace-write \
    --add-dir "$HOME/.codex/generated_images" \
    --output-last-message "$LAST_MESSAGE" \
    "$PROMPT" < /dev/null
exit_code=$?
set -e
printf '%s ai-cover-doer finished exit_code=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$exit_code"
exit "$exit_code"
