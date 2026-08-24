#!/usr/bin/env zsh
# 每日英语世界短视频生产协调器：仅制作并发 Telegram 审核，不投稿。
#
# Modification History
# | Version | Date | Author | Description |
# | --- | --- | --- | --- |
# | 1.1.0 | 2026-08-23 | Codex | 固化每日运行日志、状态回执与 EX_CONFIG 三次有界重试；全部失败时主动通知 Telegram。 |
# | 1.0.0 | 2026-08-22 | Codex | 新增 07:00 专用 Codex 生产唤起与并发防重入保护。 |
# | 1.0.1 | 2026-08-22 | Codex | 对 launchd 首次 Codex 配置瞬态失败（EX_CONFIG）仅重试一次。 |
# | 1.2.0 | 2026-08-24 | Codex | 同步英语世界成片严格大于 30 秒且不超过 300 秒的生产边界，保留旧入口仅供兼容。 |

set -uo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing}"
CODEX_HOME="${CODEX_HOME:-/Users/ryusei/.codex}"
CODEX_BIN="${CODEX_BIN:-/Users/ryusei/.local/bin/codex}"
PYTHON_BIN="${PYTHON_BIN:-$PROJECT_ROOT/.venv/bin/python}"
NOTIFIER_SCRIPT="${NOTIFIER_SCRIPT:-$PROJECT_ROOT/scripts/notify_english_world_review.py}"
LOG_DIR="${ENGLISH_WORLD_LOG_DIR:-$PROJECT_ROOT/output/english_world_daily}"
LOCK_DIR="${ENGLISH_WORLD_LOCK_DIR:-$PROJECT_ROOT/output/locks/english_world_daily.lock}"
RESPONSE_PATH="$LOG_DIR/last_codex_response.md"
STATUS_PATH="$LOG_DIR/last_run_status.txt"
RUN_LOG="$LOG_DIR/run_$(date '+%F_%H%M%S').log"
MAX_EX_CONFIG_ATTEMPTS="${MAX_EX_CONFIG_ATTEMPTS:-3}"
RETRY_DELAY_SECONDS="${RETRY_DELAY_SECONDS:-15}"

mkdir -p "$LOG_DIR" "${LOCK_DIR:h}"
exec >> "$RUN_LOG" 2>&1

write_status() {
  local phase="$1"
  local exit_code="$2"
  local attempts="$3"
  {
    print -r -- "timestamp=$(date '+%F %T %z')"
    print -r -- "phase=$phase"
    print -r -- "exit_code=$exit_code"
    print -r -- "attempts=$attempts"
    print -r -- "run_log=$RUN_LOG"
    print -r -- "response_path=$RESPONSE_PATH"
  } > "$STATUS_PATH"
}

notify_failure() {
  local reason="$1"
  if [[ ! -x "$PYTHON_BIN" || ! -f "$NOTIFIER_SCRIPT" ]]; then
    print -r -- "[$(date '+%F %T')] ERROR: cannot notify Telegram; notifier unavailable"
    return 1
  fi
  "$PYTHON_BIN" "$NOTIFIER_SCRIPT" \
    --title "今日英语世界短视频" \
    --failure "$reason"
}

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  print -r -- "[$(date '+%F %T')] skipped: daily English World run is already active"
  write_status "SKIPPED_ACTIVE" 0 0
  exit 0
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT

if [[ ! -x "$CODEX_BIN" ]]; then
  print -r -- "[$(date '+%F %T')] ERROR: Codex CLI is not executable: $CODEX_BIN" >&2
  write_status "FAILED_BOOTSTRAP" 1 0
  notify_failure "生产协调器未启动：Codex CLI 不可执行。运行日志：$RUN_LOG" || true
  exit 1
fi

PROMPT=$(cat <<'EOF'
执行今日“英语世界短视频”无人值守制作任务。工作目录是 Video-precessing。

这是独立的 ENGLISH_WORLD_SHORT 生产：不得编辑项目源码、不得修改通用频道白名单、不得调用 PipelineManager、wechat_uploader.py 或任何平台投稿/发布逻辑；绝不提交视频号。只允许生成学习卡素材和发送 Telegram 审核回执。

来源仅限以下频道，并按频道 ID 严格核验：
- CBC Kids News：UCWUA2W6LueNy9BSovivFVvQ
- CBS Evening News：UCAeWdyKJXGWmVAXFpgLNNTg
- ABC News：UCBi2mrWuNuyYy4gbM6fU18Q

先搜索当天或近期未使用的候选，再检查标题、简介、英文字幕/转写和必要的画面。只能选择适合儿童与家庭学习者的自然、科学、教育、健康、文化、日常生活或正向人文题材。排除政治、战争、暴力、犯罪、成人话题、强时政评论，以及包含真实伤亡、恐慌、疏散或令人不适灾情画面的素材；不确定即放弃当天生产。自然科学与天气科普（包括风暴、闪电、龙卷风的成因）并非关键词禁区，必须结合实际画面和叙事判断。

若找到合格来源，按 make-english-world-short 技能和 production-contract 完整制作一条：自然完整句收尾；逐词红线；每个可见阅读屏至少 8 个微笔记；右栏随左侧同步且可用时至少 5 张词卡；中文完整；词汇只用已有离线 Hermes 分级；`content_type=ENGLISH_WORLD_SHORT`；保留 source_provenance、timeline、manifest、质检材料。最终 MP4 实测时长必须严格大于 30 秒且不超过 300 秒；不得用静音、循环或无语音尾段凑时长，必须覆盖完整自然语句。完成后核验 MP4、音频收尾、manifest 与关键帧。

质检通过后，必须运行以下命令把 MP4 和 manifest 发到 Telegram 人工审核：
PYTHONPATH=src .venv/bin/python scripts/notify_english_world_review.py --title '<实际标题>' --mp4 '<绝对MP4路径>' --manifest '<绝对manifest路径>'
若当天无合格候选或制作/质检失败，必须运行：
PYTHONPATH=src .venv/bin/python scripts/notify_english_world_review.py --title '今日英语世界短视频' --failure '<准确原因>'

最终只报告真实状态、来源、证据路径与 Telegram 发送结果。不得将 Telegram 发送、素材生成或审核回执描述成视频号发布。
EOF
)

print -r -- "[$(date '+%F %T')] starting daily English World production coordinator"
run_coordinator() {
  CODEX_HOME="$CODEX_HOME" "$CODEX_BIN" exec \
    --cd "$PROJECT_ROOT" \
    --add-dir /Users/ryusei/.codex/skills \
    --sandbox danger-full-access \
    -c 'approval_policy="never"' \
    --output-last-message "$RESPONSE_PATH" \
    "$PROMPT"
}

ATTEMPT=1
EXIT_CODE=0
while true; do
  print -r -- "[$(date '+%F %T')] coordinator attempt $ATTEMPT/$MAX_EX_CONFIG_ATTEMPTS"
  run_coordinator
  EXIT_CODE=$?
  if [[ "$EXIT_CODE" -ne 78 || "$ATTEMPT" -ge "$MAX_EX_CONFIG_ATTEMPTS" ]]; then
    break
  fi
  print -r -- "[$(date '+%F %T')] Codex returned EX_CONFIG; retrying after ${RETRY_DELAY_SECONDS}s"
  sleep "$RETRY_DELAY_SECONDS"
  ATTEMPT=$((ATTEMPT + 1))
done

if [[ "$EXIT_CODE" -eq 0 ]]; then
  write_status "COORDINATOR_FINISHED" 0 "$ATTEMPT"
  print -r -- "[$(date '+%F %T')] coordinator exited successfully; inspect its Telegram receipt separately"
  exit 0
fi

write_status "FAILED_COORDINATOR" "$EXIT_CODE" "$ATTEMPT"
notify_failure "生产协调器异常退出（exit=$EXIT_CODE，尝试=$ATTEMPT/$MAX_EX_CONFIG_ATTEMPTS）。运行日志：$RUN_LOG。未生成可确认的今日审核成片，未触发视频号投稿。" || true
exit "$EXIT_CODE"
