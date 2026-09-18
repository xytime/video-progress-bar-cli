"""统一子进程运行环境构建工厂。

集中管理子进程调用时的代理嗅探、PATH 保证、密钥注入与凭据隔离，
供管线调度、AI 封面队列、文案渲染及外围脚本统一复用，避免环境变量在 cron 下静默丢失。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-09-18 | Antigravity | 候选 PATH 补齐 /usr/bin 与 /bin 基础系统路径，支持系统命令与守护进程保底 |
| 1.0.0 | 2026-09-18 | Antigravity | 建立子进程环境工厂单一真相源，支持代理探测、PATH 补齐、GEMINI 密钥注入与 PYTHONPATH 保障 |
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from config.settings import settings

PROXY_KEYS = frozenset({
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
})


def build_subprocess_env(
    extra_env: Mapping[str, str] | None = None,
    *,
    include_proxies: bool = True,
    include_gemini: bool = True,
    include_telegram: bool = True,
    include_pythonpath: bool = True,
) -> dict[str, str]:
    """构建安全、完备的子进程运行环境字典。

    核心能力：
    1. 动态检测并注入可用代理（避免代理离线时 192.168.1.5 连接被拒造成死锁）；
    2. 保证 PATH 包含 .venv/bin, /opt/homebrew/bin (deno/node), /usr/local/bin, ~/.local/bin (agy)；
    3. 注入 GEMINI_API_KEY 避免 cron 下 LLM / 生图凭据丢失；
    4. 注入 Telegram 凭证供外部上传/机器人使用；
    5. 确保 PYTHONPATH 包含项目 src 目录，消除模块引用找不到问题。
    """
    if include_proxies:
        active_proxies = settings.get_active_proxies()
        env = {k: v for k, v in os.environ.items() if k not in PROXY_KEYS}
        env.update(active_proxies)
    else:
        env = dict(os.environ)

    if include_telegram:
        if settings.telegram_bot_token:
            env["TELEGRAM_BOT_TOKEN"] = settings.telegram_bot_token
        if settings.active_telegram_chat_id:
            env["TELEGRAM_CHAT_ID"] = settings.active_telegram_chat_id
        if settings.telegram_admin_ids:
            env["TELEGRAM_ADMIN_IDS"] = settings.telegram_admin_ids

    if include_gemini and settings.gemini_api_key:
        env["GEMINI_API_KEY"] = settings.gemini_api_key

    candidate_paths = [
        str(settings.project_root / ".venv" / "bin"),
        "/opt/homebrew/bin",
        "/usr/local/bin",
        str(Path.home() / ".local" / "bin"),
        "/usr/bin",
        "/bin",
    ]
    current_paths = env.get("PATH", "").split(":") if env.get("PATH") else []
    merged_paths: list[str] = []
    seen: set[str] = set()
    for p in candidate_paths + current_paths:
        if p and p not in seen:
            seen.add(p)
            merged_paths.append(p)
    env["PATH"] = ":".join(merged_paths)

    if include_pythonpath:
        src_path = str(settings.project_root / "src")
        current_pythonpath = env.get("PYTHONPATH", "").split(":") if env.get("PYTHONPATH") else []
        if src_path not in current_pythonpath:
            env["PYTHONPATH"] = ":".join([src_path] + [p for p in current_pythonpath if p])

    if extra_env:
        env.update({k: str(v) for k, v in extra_env.items()})

    return env
