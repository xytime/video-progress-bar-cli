#!/usr/bin/env python3
"""英语世界日更的窗口后交付监测与缺席自愈。

主生产任务负责内容、质检、Telegram 回执和已有的投稿策略；本监测器只核验
某个预定窗口是否取得本次可审计交付回执。仅当该窗口根本没有启动记录、且没有
活跃锁时，才补发起一次同一协调器。已有失败记录绝不重跑，避免重复内容或投稿。

# Modification History
# | Version | Date | Author | Description |
# | --- | --- | --- | --- |
# | 1.0.0 | 2026-08-27 | Codex | 新增 07:00/16:30 窗口后的回执监测、缺席自愈和持久健康账本。 |
# | 1.1.0 | 2026-08-29 | Codex | 监控器按 09:15/19:00 实际触发时刻分别映射 07:00/16:30，修复晚间仍检查早班。 |
# | 1.2.0 | 2026-08-30 | Codex | 单独识别已获 Telegram 接受的生产失败回执，避免误报成未交付。 |
# | 1.3.0 | 2026-08-30 | Codex | 健康账本固定输出调度、产物、Telegram、平台提交、公开可见五层证据，禁止将已受理写成已公开。 |
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any


DEFAULT_PROJECT_ROOT = Path("/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing")
SCHEDULED_LOG_PATTERN = re.compile(r"^run_(?P<date>\d{4}-\d{2}-\d{2})_(?P<clock>\d{6})\.log$")
ACCEPTED_DELIVERY_KINDS = {"review", "review_and_auto_submission"}
ACCEPTED_FAILURE_KINDS = {"failure_notice"}


@dataclass(frozen=True)
class MonitorPaths:
    project_root: Path
    log_dir: Path
    lock_dir: Path
    python_bin: Path
    daily_runner: Path


def _parse_slot(value: str) -> time:
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--slot must use HH:MM") from exc


def _slot_for_observation(observed_at: datetime) -> time:
    """将两个固定监控触发时刻映射到各自最近的生产窗口。"""
    return time(7, 0) if observed_at.time() < time(13, 0) else time(16, 30)


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _has_active_lock(lock_dir: Path) -> bool:
    """不确定的锁一律当作活跃，宁可等待也不并发补跑。"""
    if not lock_dir.exists():
        return False
    try:
        payload = json.loads((lock_dir / "owner.json").read_text(encoding="utf-8"))
        return _pid_is_running(int(payload.get("pid", 0)))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return True


def _accepted_delivery_receipt(
    log_dir: Path,
    day: datetime,
    slot: time,
    *,
    kinds: set[str] = ACCEPTED_DELIVERY_KINDS,
) -> Path | None:
    """返回当天该窗口之后、指定类型中最新的 Telegram API 接受回执。"""
    slot_start = datetime.combine(day.date(), slot, tzinfo=day.tzinfo)
    accepted: list[tuple[datetime, Path]] = []
    for receipt_path in log_dir.glob("*.delivery.json"):
        try:
            payload = json.loads(receipt_path.read_text(encoding="utf-8"))
            changed_at = datetime.fromtimestamp(receipt_path.stat().st_mtime, tz=day.tzinfo)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if (
            changed_at.date() == day.date()
            and changed_at >= slot_start
            and isinstance(payload, dict)
            and payload.get("status") == "ACCEPTED"
            and payload.get("kind") in kinds
        ):
            accepted.append((changed_at, receipt_path))
    return max(accepted, default=(None, None), key=lambda item: item[0])[1]


def _scheduled_run_logs(log_dir: Path, day: datetime, slot: time) -> list[Path]:
    """只识别计划窗口前后 30 分钟内启动的原始日更，不把人工补跑当作原始运行。"""
    slot_start = datetime.combine(day.date(), slot, tzinfo=day.tzinfo)
    window_start = slot_start - timedelta(minutes=15)
    window_end = slot_start + timedelta(minutes=30)
    matches: list[Path] = []
    for run_log in log_dir.glob("run_*.log"):
        matched = SCHEDULED_LOG_PATTERN.match(run_log.name)
        if not matched or matched.group("date") != day.strftime("%F"):
            continue
        try:
            started_at = datetime.strptime(
                f"{matched.group('date')} {matched.group('clock')}", "%Y-%m-%d %H%M%S"
            ).replace(tzinfo=day.tzinfo)
        except ValueError:
            continue
        if window_start <= started_at <= window_end:
            matches.append(run_log)
    return sorted(matches)


def _receipt_payload(receipt_path: Path | None) -> dict[str, Any]:
    """读取已被筛选过的回执摘要；读不到时保持未知而非补造成功。"""
    if receipt_path is None:
        return {}
    try:
        payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _five_layer_evidence(payload: dict[str, Any]) -> dict[str, dict[str, str]]:
    """把窗口事实拆成不可互相越级的五层证据，供人和机器安全阅读。"""
    state = str(payload.get("state") or "")
    receipt_path = payload.get("delivery_receipt") or payload.get("failure_receipt")
    receipt = _receipt_payload(Path(str(receipt_path))) if receipt_path else {}
    is_delivery = state in {"DELIVERED", "RECOVERED_DELIVERED"}
    is_failure = state in {"PRODUCTION_FAILED_REPORTED", "RECOVERED_PRODUCTION_FAILED_REPORTED"}

    if state == "IN_PROGRESS":
        scheduled = "RUNNING"
    elif state.startswith("MISSING"):
        scheduled = "MISSING"
    elif state.startswith("RECOVERED"):
        scheduled = "RECOVERED_RUN"
    elif state:
        scheduled = "EXECUTED"
    else:
        scheduled = "UNKNOWN"

    if is_delivery:
        artifact = "REVIEW_PACKAGE_REPORTED"
        telegram = "API_ACCEPTED"
    elif is_failure:
        artifact = "FAILED_REPORTED"
        telegram = "API_ACCEPTED"
    else:
        artifact = "UNKNOWN"
        telegram = "NOT_ACCEPTED"

    submission_result = str(receipt.get("submission_result") or "").strip()
    if submission_result:
        submission = "LOCAL_WORKER_REPORTED"
    elif is_delivery:
        submission = "NOT_SUBMITTED_OR_UNVERIFIED"
    else:
        submission = "UNKNOWN"

    evidence = {
        "scheduled_window": {"state": scheduled},
        "artifact": {"state": artifact},
        "telegram": {"state": telegram},
        "platform_submission": {"state": submission},
        "public_visibility": {"state": "NOT_VERIFIED"},
    }
    if submission_result:
        evidence["platform_submission"]["detail"] = submission_result
    return evidence


def _write_health(log_dir: Path, day: datetime, slot: time, payload: dict[str, Any]) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    target = log_dir / f"monitor_{day.strftime('%F')}_{slot.strftime('%H%M')}.json"
    temporary = target.with_suffix(".tmp")
    payload["evidence_layers"] = _five_layer_evidence(payload)
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)
    return target


def _run_missing_window_recovery(paths: MonitorPaths) -> int:
    """仅补跑完全缺席的窗口；协调器本身继续负责锁、回执和有界重试。"""
    if not paths.python_bin.is_file() or not paths.daily_runner.is_file():
        return 127
    try:
        result = subprocess.run(
            [str(paths.python_bin), str(paths.daily_runner)],
            cwd=paths.project_root,
            env=dict(os.environ),
            check=False,
            timeout=2 * 60 * 60 + 5 * 60,
        )
        return result.returncode
    except subprocess.TimeoutExpired:
        return 124


def monitor_slot(
    paths: MonitorPaths,
    *,
    slot: time,
    now: datetime | None = None,
    recover_missing: bool = False,
) -> tuple[int, dict[str, Any]]:
    """核验一个生产窗口；返回退出码及可持久化的健康摘要。"""
    observed_at = now or datetime.now().astimezone()
    delivery_receipt = _accepted_delivery_receipt(paths.log_dir, observed_at, slot)
    payload: dict[str, Any] = {
        "checked_at": observed_at.isoformat(),
        "date": observed_at.strftime("%F"),
        "slot": slot.strftime("%H:%M"),
        "recovery_attempted": False,
    }
    if delivery_receipt:
        payload.update({"state": "DELIVERED", "delivery_receipt": str(delivery_receipt)})
        _write_health(paths.log_dir, observed_at, slot, payload)
        return 0, payload

    failure_receipt = _accepted_delivery_receipt(
        paths.log_dir, observed_at, slot, kinds=ACCEPTED_FAILURE_KINDS,
    )
    if failure_receipt:
        payload.update({
            "state": "PRODUCTION_FAILED_REPORTED",
            "failure_receipt": str(failure_receipt),
        })
        _write_health(paths.log_dir, observed_at, slot, payload)
        return 1, payload

    if _has_active_lock(paths.lock_dir):
        payload.update({"state": "IN_PROGRESS", "lock_dir": str(paths.lock_dir)})
        _write_health(paths.log_dir, observed_at, slot, payload)
        return 0, payload

    run_logs = _scheduled_run_logs(paths.log_dir, observed_at, slot)
    if run_logs:
        payload.update({"state": "RUN_COMPLETED_WITHOUT_DELIVERY", "run_logs": [str(path) for path in run_logs]})
        _write_health(paths.log_dir, observed_at, slot, payload)
        return 1, payload

    if not recover_missing:
        payload.update({"state": "MISSING_SCHEDULED_RUN"})
        _write_health(paths.log_dir, observed_at, slot, payload)
        return 1, payload

    payload["recovery_attempted"] = True
    payload["recovery_exit_code"] = _run_missing_window_recovery(paths)
    delivery_receipt = _accepted_delivery_receipt(paths.log_dir, observed_at, slot)
    if delivery_receipt:
        payload.update({"state": "RECOVERED_DELIVERED", "delivery_receipt": str(delivery_receipt)})
        _write_health(paths.log_dir, observed_at, slot, payload)
        return 0, payload
    failure_receipt = _accepted_delivery_receipt(
        paths.log_dir, observed_at, slot, kinds=ACCEPTED_FAILURE_KINDS,
    )
    if failure_receipt:
        payload.update({
            "state": "RECOVERED_PRODUCTION_FAILED_REPORTED",
            "failure_receipt": str(failure_receipt),
        })
        _write_health(paths.log_dir, observed_at, slot, payload)
        return 1, payload
    payload.update({"state": "MISSING_RUN_RECOVERY_FAILED"})
    _write_health(paths.log_dir, observed_at, slot, payload)
    return 1, payload


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=DEFAULT_PROJECT_ROOT)
    parser.add_argument("--log-dir", type=Path)
    parser.add_argument("--lock-dir", type=Path)
    parser.add_argument("--python-bin", type=Path)
    parser.add_argument("--daily-runner", type=Path)
    parser.add_argument("--slot", type=_parse_slot, help="显式覆盖待核验窗口；计划任务默认按触发时刻推导")
    parser.add_argument("--recover-missing", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    project_root = args.project_root.resolve()
    paths = MonitorPaths(
        project_root=project_root,
        log_dir=args.log_dir or project_root / "output/english_world_daily",
        lock_dir=args.lock_dir or project_root / "output/locks/english_world_daily.lock",
        python_bin=args.python_bin or project_root / ".venv/bin/python",
        daily_runner=args.daily_runner or project_root / "scripts/run_english_world_daily.py",
    )
    observed_at = datetime.now().astimezone()
    slot = args.slot or _slot_for_observation(observed_at)
    exit_code, payload = monitor_slot(
        paths, slot=slot, now=observed_at, recover_missing=args.recover_missing,
    )
    print(json.dumps(payload, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
