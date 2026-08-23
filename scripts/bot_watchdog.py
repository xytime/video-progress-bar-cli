#!/usr/bin/env python3
"""scripts/bot_watchdog.py — Telegram Bot 状态监测守护与看门狗脚本

仅以 Bot 进程存活作为自动重启判据。Telegram 的长轮询在没有新消息时可以长期不写
bot.log，日志静默只能作为诊断信息，不能单独证明轮询挂死。

# Modification History
| Version | Date       | Author                         | Description |
| ------- | ---------- | ------------------------------ | ----------- |
| 1.1.0   | 2026-08-21 | Codex                          | 长轮询空闲时不再因 bot.log 静默误重启；仅进程退出才自动拉起 |
| 1.0.0   | 2026-05-25 | Gemini_3.5_Flash_High_planning | 初始创建看门狗，实现日志活跃度与进程存活探测 |
"""
import os
import subprocess
import sys
import time
from pathlib import Path

# [Gemini_3.5_Flash_High_planning] 动态获取项目根目录
PRJ_ROOT = Path(__file__).parent.parent.resolve()
VPANEL = str(PRJ_ROOT / "vpanel")
LOG_FILE = PRJ_ROOT / "output" / "bot.log"
PID_FILE = PRJ_ROOT / "output" / "bot.pid"

def _read_pid() -> int | None:
    if not PID_FILE.exists():
        return None
    try:
        return int(PID_FILE.read_text().strip())
    except (ValueError, OSError):
        return None


def _is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def main() -> None:
    pid = _read_pid()
    running = pid is not None and _is_running(pid)

    if not running:
        # [Gemini_3.5_Flash_High_planning] 进程未启动，执行启动
        print("⚠️ Bot is not running. Starting bot...")
        subprocess.run([VPANEL, "bot", "start"], check=True)
        return

    # 长轮询在没有新消息时不会持续写日志；仅报告日志年龄，不把它当成重启依据。
    if not LOG_FILE.exists():
        print("🟢 Bot process is running; bot.log does not exist yet.")
        return

    mtime = LOG_FILE.stat().st_mtime
    elapsed = time.time() - mtime

    print(
        f"🟢 Bot process is running (PID: {pid}); "
        f"last log update: {elapsed:.1f}s ago (long-poll idle is normal)."
    )


if __name__ == "__main__":
    main()
