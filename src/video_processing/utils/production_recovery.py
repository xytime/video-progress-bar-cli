"""英语世界恢复合同：保存启动配置，读取本次宿主结果；不执行生产或访问数据库。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-18 | Codex | 固定恢复配置与本轮结果来源，保护投稿未知任务。 |
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from .retry_policy import failure_kind

PATH_OPTIONS = ("codex_home", "codex_bin", "python_bin", "notifier_script", "log_dir", "lock_dir", "agy_bin")
TEXT_OPTIONS = ("coordinator_provider", "codex_model", "agy_model")
NUMBER_OPTIONS = ("coordinator_timeout_seconds", "retry_delay_seconds", "wait_for_lock_seconds")


def context_path(request_path: Path) -> Path:
    return request_path.with_suffix(".recovery-context.json")


def write_context(request_path: Path, paths, *, retry_delay_seconds: float,
                  wait_for_lock_seconds: float, excluded_youtube_ids: tuple[str, ...], recoverable: bool) -> None:
    options = {name: str(getattr(paths, name)) for name in PATH_OPTIONS}
    options.update({name: getattr(paths, name) or "" for name in TEXT_OPTIONS})
    options.update(coordinator_timeout_seconds=paths.coordinator_timeout_seconds,
                   retry_delay_seconds=retry_delay_seconds, wait_for_lock_seconds=wait_for_lock_seconds,
                   excluded_youtube_ids=list(excluded_youtube_ids))
    payload = {"version": 1, "project_root": str(paths.project_root.resolve()),
               "recoverable": recoverable, "options": options}
    destination = context_path(request_path)
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(destination)


def recovery_arguments(path: Path, root: Path) -> list[str]:
    """只接受宿主保存的完整配置；旧任务缺配置时不能静默换成默认引擎。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    if (data.get("version") != 1 or data.get("project_root") != str(root.resolve())
            or data.get("recoverable") is not True):
        raise ValueError("原制作配置不完整或此任务不允许通用恢复")
    options = data.get("options", {})
    required = set(PATH_OPTIONS + TEXT_OPTIONS + NUMBER_OPTIONS) | {"excluded_youtube_ids"}
    if not isinstance(options, dict) or set(options) != required:
        raise ValueError("原制作配置缺字段，不能使用默认参数恢复")
    if options["coordinator_provider"] not in {"programmatic", "codex", "agy"}:
        raise ValueError("原制作引擎无效")
    args = ["--project-root", str(root.resolve())]
    for name in PATH_OPTIONS + TEXT_OPTIONS:
        value = options[name]
        if not isinstance(value, str) or (name in PATH_OPTIONS and not Path(value).is_absolute()):
            raise ValueError("原制作路径或模型配置无效")
        args.extend(["--" + name.replace("_", "-"), value])
    for name in NUMBER_OPTIONS:
        value = options[name]
        if (type(value) not in (int, float) or not math.isfinite(value) or value < 0
                or (name == "coordinator_timeout_seconds" and value == 0)):
            raise ValueError("原制作时间预算无效")
        args.extend(["--" + name.replace("_", "-"), str(value)])
    ids = options["excluded_youtube_ids"]
    if not isinstance(ids, list) or any(not isinstance(value, str) or len(value) != 11
                                      or not all(c.isascii() and (c.isalnum() or c in "_-") for c in value) for value in ids):
        raise ValueError("原任务来源排除清单无效")
    for value in ids:
        args.extend(["--exclude-youtube-id", value])
    return args


def read_outcome(status_path: Path, root: Path, returncode: int) -> tuple[str, bool]:
    """仅明确的制作前失败可重试；投稿/交付不确定、缺回执不能转成生产重做。"""
    status = dict(line.split("=", 1) for line in status_path.read_text().splitlines() if "=" in line)
    phase = status["phase"]
    if int(status["exit_code"]) != returncode:
        raise ValueError("协调器退出码与本次结果记录不一致")
    log = Path(status["run_log"]).resolve()
    if not log.is_relative_to((root / "output/english_world_daily").resolve()) or not log.is_file():
        raise ValueError("本次运行日志缺失或不属于英语世界运行目录")
    if returncode == 0:
        labels = {"SKIPPED_ACTIVE": "已有制作正在运行，本轮未启动",
                  "SKIPPED_MARKET_GUARD": "当前处于避让时段，本轮未启动",
                  "SKIPPED_STOCK_FULL": "待发库存充足，本轮未启动",
                  "SKIPPED_LIMIT_REACHED": "已达到当日上限，本轮未启动"}
        return labels.get(phase, "本轮制作协调器已结束；成片、Telegram 和平台结果以阶段回执为准") + f"；日志 {log}", False
    with log.open("rb") as stream:
        stream.seek(max(0, log.stat().st_size - 12000))
        detail = stream.read().decode("utf-8", errors="replace")
    request_path = log.with_suffix(".delivery-request.json")
    request = json.loads(request_path.read_text()) if request_path.is_file() else {}
    reason = str(request.get("failure") or detail[-1500:])
    category = failure_kind(reason + "\n" + detail)
    safe_phase = phase in {"FAILED_COORDINATOR", "REPORTED_PRODUCTION_FAILURE", "SOURCE_ACCESS_BLOCKED",
                           "REPORTED_SOURCE_ACCESS_BLOCKED", "SOURCE_ACCESS_PREFLIGHT_EXCEPTION",
                           "REPORTED_SOURCE_ACCESS_PREFLIGHT_EXCEPTION", "COORDINATOR_TIMED_OUT"}
    retry = (safe_phase and request.get("kind") == "failure"
             and request.get("failure_kind") != "internal_error" and category == "TRANSIENT")
    return f"本轮失败：{reason[:800]}；分类 {category}；阶段 {phase}；日志 {log}", retry
