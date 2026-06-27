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
| 1.1.0 | 2026-06-27 | Claude_Opus_4.8 | [进程加固·按 vpanel 标准] 新增 _bot_pids()：以命令模式(pgrep -f BOT_SCRIPT 绝对路径，精确匹配防误杀)为权威，start/stop/status 不再仅信易漂移的 PID 文件——根治「PID 漂移→start 重复起→双 poller→Telegram 409→对话无响应」；status 预警多实例 |
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


def _bot_pids() -> list[int]:
    """按命令行精确模式发现所有 bot 进程（pgrep -f <BOT_SCRIPT 绝对路径>）。

    [Claude_Opus_4.8] 仅信 PID 文件会漏判（PID 文件易漂移：崩溃后手动重启 / 文件被删）：
    - stop 漏杀真进程 → 残留 bot 仍在 getUpdates；
    - start 不察已在运行 → 再起一个 → 两个 poller → Telegram 409 Conflict →「对话无响应」。
    故按 vpanel 同标准以「命令模式」为权威；用 BOT_SCRIPT 的绝对路径精确匹配（不用宽泛
    'python'，避免误杀其它进程——这是历史上该加固被还原的最可能诱因）。
    """
    try:
        out = subprocess.run(
            ["pgrep", "-f", BOT_SCRIPT],
            capture_output=True, text=True, timeout=5,
        ).stdout
    except Exception:
        return []
    pids = []
    for tok in out.split():
        try:
            p = int(tok)
            if p != os.getpid():  # 稳妥起见排除管理脚本自身
                pids.append(p)
        except ValueError:
            pass
    return pids


def start() -> None:
    # [Claude_Opus_4.8] 权威判断：命令模式发现 > PID 文件（防漂移导致重复 poller → Telegram 409）
    running = _bot_pids()
    if running:
        print(f"ℹ️  Bot 已在运行中 (PID: {', '.join(map(str, running))})")
        PID_FILE.write_text(str(running[0]))  # 回填可能漂移的 PID 文件
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
    # [Claude_Opus_4.8] 收集所有 bot 进程：命令模式发现 + PID 文件兜底（覆盖漂移残留/重复实例）
    pids = _bot_pids()
    file_pid = _read_pid()
    if file_pid and file_pid not in pids and _is_running(file_pid):
        pids.append(file_pid)

    if not pids:
        print("ℹ️  Bot 未在运行")
        PID_FILE.unlink(missing_ok=True)
        return

    for pid in pids:
        print(f"🛑 正在停止 Bot (PID: {pid})...")
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    # 等最多 5 秒优雅退出，否则对仍存活者 SIGKILL
    for _ in range(10):
        time.sleep(0.5)
        if not _bot_pids():
            break
    else:
        print("⚡ 进程未响应，强制终止...")
        for pid in _bot_pids():
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    PID_FILE.unlink(missing_ok=True)
    print("✅ Bot 已停止")


def status() -> None:
    # [Claude_Opus_4.8] 以命令模式发现为权威，顺带预警重复 poller（疑似 409「对话无响应」温床）
    pids = _bot_pids()
    if pids:
        print(f"🟢 运行中 (PID: {', '.join(map(str, pids))})")
        print(f"📄 日志: {LOG_FILE}")
        PID_FILE.write_text(str(pids[0]))
        if len(pids) > 1:
            print(f"⚠️  检测到 {len(pids)} 个 bot 进程（疑似重复 poller → Telegram 409，建议 restart 收敛）")
    else:
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
