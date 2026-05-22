#!/usr/bin/env python3
"""scripts/bot_daemon.py — Telegram Bot 进程守护管理器

职责单一：PID 文件管理 + 进程启停。
不包含任何 Bot 业务逻辑（高内聚低耦合）。
vpanel 的 bot 命令组通过 CLI 参数调用本脚本（透传网关）。

用法:
    python scripts/bot_daemon.py start
    python scripts/bot_daemon.py stop
    python scripts/bot_daemon.py status
    python scripts/bot_daemon.py restart

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-05-22 | Claude_Sonnet_4.6_Thinking_planning | 初始创建 |
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

PRJ_ROOT  = Path(__file__).parent.parent
PYTHON    = str(PRJ_ROOT / ".venv" / "bin" / "python")
BOT_SCRIPT = str(PRJ_ROOT / "src" / "bot" / "telegram_bot.py")
PID_FILE  = PRJ_ROOT / "output" / "bot.pid"
LOG_FILE  = PRJ_ROOT / "output" / "bot.log"


def _read_pid() -> int | None:
    """读取 PID 文件，返回整数 PID 或 None（文件不存在/格式错误）"""
    if not PID_FILE.exists():
        return None
    try:
        return int(PID_FILE.read_text().strip())
    except (ValueError, OSError):
        return None


def _is_running(pid: int) -> bool:
    """检查 PID 对应的进程是否存活"""
    try:
        os.kill(pid, 0)  # signal 0 = 仅探活，不杀进程
        return True
    except (ProcessLookupError, PermissionError):
        return False


def start() -> None:
    pid = _read_pid()
    if pid and _is_running(pid):
        print(f"ℹ️  Bot 已在运行中 (PID: {pid})")
        return

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    # [Claude_Sonnet_4.6_Thinking_planning] PYTHONPATH 确保 src/bot 包可被正确导入
    env = {**os.environ, "PYTHONPATH": str(PRJ_ROOT / "src")}

    with open(LOG_FILE, "a") as log:
        proc = subprocess.Popen(
            [PYTHON, BOT_SCRIPT],
            cwd=str(PRJ_ROOT),
            stdout=log,
            stderr=log,
            env=env,
            start_new_session=True,  # 与当前终端脱钩，关闭终端不影响 Bot
        )

    PID_FILE.write_text(str(proc.pid))
    time.sleep(1.5)  # 等待进程启动或快速失败

    if _is_running(proc.pid):
        print(f"✅ Bot 已启动 (PID: {proc.pid})")
        print(f"📄 日志: {LOG_FILE}")
    else:
        print(f"❌ Bot 启动失败，请查看日志: {LOG_FILE}")
        PID_FILE.unlink(missing_ok=True)
        sys.exit(1)


def stop() -> None:
    pid = _read_pid()
    if not pid:
        print("ℹ️  Bot 未在运行（无 PID 文件）")
        return

    if not _is_running(pid):
        print("⚠️  PID 文件存在但进程已不在运行（已清理）")
        PID_FILE.unlink(missing_ok=True)
        return

    print(f"🛑 正在停止 Bot (PID: {pid})...")
    os.kill(pid, signal.SIGTERM)

    # 等最多 5 秒优雅退出，否则 SIGKILL
    for _ in range(10):
        time.sleep(0.5)
        if not _is_running(pid):
            break
    else:
        print("⚡ 进程未响应，强制终止...")
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    PID_FILE.unlink(missing_ok=True)
    print("✅ Bot 已停止")


def status() -> None:
    pid = _read_pid()
    if pid and _is_running(pid):
        print(f"🟢 运行中 (PID: {pid})")
        print(f"📄 日志: {LOG_FILE}")
    else:
        if pid:
            PID_FILE.unlink(missing_ok=True)
        print("🔴 已停止")


def restart() -> None:
    stop()
    time.sleep(1)
    start()


_COMMANDS = {"start": start, "stop": stop, "status": status, "restart": restart}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    fn = _COMMANDS.get(cmd)
    if not fn:
        print(f"用法: python scripts/bot_daemon.py [{'/'.join(_COMMANDS)}]")
        sys.exit(1)
    fn()
