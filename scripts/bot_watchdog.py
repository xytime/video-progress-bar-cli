#!/usr/bin/env python3
"""scripts/bot_watchdog.py — Telegram Bot 状态监测守护与看门狗脚本

监测 bot.log 的最后修改时间。如果 Bot 进程在运行但日志在 3 分钟内没有更新（说明轮询挂死），
或者 Bot 进程根本没有启动，则自动执行重启/启动，确保服务高可用。

# Modification History
| Version | Date       | Author                         | Description |
| ------- | ---------- | ------------------------------ | ----------- |
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

# 阈值：3 分钟 (180 秒) 无日志写入则判定为挂死
IDLE_THRESHOLD = 180


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

    # 进程在运行，检查日志更新时间
    if not LOG_FILE.exists():
        # 如果日志文件不存在，可能是刚启动或被清理，跳过检查
        print("ℹ️ Bot is running, but bot.log does not exist yet. Skipping watchdog check.")
        return

    mtime = LOG_FILE.stat().st_mtime
    elapsed = time.time() - mtime

    if elapsed > IDLE_THRESHOLD:
        # [Gemini_3.5_Flash_High_planning] 日志长时间没有更新，判定为网络轮询挂死
        print(f"🚨 Bot is running (PID: {pid}) but bot.log has not been updated for {elapsed:.1f}s.")
        print("🚨 Restarting Bot daemon via vpanel...")
        subprocess.run([VPANEL, "bot", "restart"], check=True)
    else:
        print(f"🟢 Bot is running and healthy (last log update: {elapsed:.1f}s ago).")


if __name__ == "__main__":
    main()
