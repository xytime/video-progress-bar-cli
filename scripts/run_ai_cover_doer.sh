#!/usr/bin/env bash
# 兼容已安装的 LaunchAgent 入口；生产封面不再唤起 Codex。
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
exec "$PROJECT_ROOT/.venv/bin/python" "$PROJECT_ROOT/scripts/reconcile_ai_cover_queue.py"
