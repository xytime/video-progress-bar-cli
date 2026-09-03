"""自动发布巡航入口。

crontab 每分钟调用一次本脚本，确保完成处理与审查的候选无需等待发布时段。
跨进程非阻塞锁确保上一轮尚未结束时不并发启动。发布时段限制仅在
``ENABLE_PUBLIC_PUBLISH_WINDOWS=true`` 时由 PipelineManager 的平台提交闸门恢复。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-31 | Codex | 新增窗口内巡航入口，以 Settings 作为唯一窗口判定并避免定时任务重叠 |
| 1.1.0 | 2026-08-02 | Codex | 改为每分钟自动巡航，不再因发布时段跳过完整流水线 |
| 1.2.0 | 2026-08-04 | Codex | 记录巡航实例 PID、Git revision 与心跳，区分已推送代码和实际运行版本 |
| 1.3.0 | 2026-08-04 | Codex | 接收管线阶段回调，状态文件记录当前视频、阶段与阶段开始时间 |
| 1.4.0 | 2026-08-29 | Codex | 每分钟巡航在公共窗口内先续投一条英语世界 AUTO_POLICY 延后项，仍由专用投稿器原子领取。 |
| 1.5.0 | 2026-08-30 | Codex | 公共窗口调度前回收未领取且过期的具名补发授权，避免批准项永久脱离队列。 |
| 1.6.0 | 2026-08-30 | Codex | 已受理英语世界作品按原生 ID 节流回查；全程复用 pipeline.lock 且绝不触发重传。 |
| 1.6.1 | 2026-08-30 | Codex | 统一回查超时与普通失败的熔断通知收口，并转义 Telegram HTML 动态字段。 |
| 1.7.0 | 2026-08-30 | Codex | 视频号已受理的英语世界审核项按独立账本同步到抖音，并节流回查公开状态。 |
| 1.8.0 | 2026-09-01 | Codex | 英语世界抖音同步取消单轮和 24 小时来源限制，按不可重复账本逐条清空可投队列。 |
| 1.8.1 | 2026-09-01 | Codex | 每轮输出抖音发布策略实效指纹，定位 cron 与源码载入偏差。 |
| 1.8.2 | 2026-09-02 | Codex | 英语世界抖音管理页回查在领取账本前遵循持久阶段熔断，避免无效访问消耗回查窗口。 |
| 1.8.3 | 2026-09-02 | Codex | 英语世界抖音同步恢复独立正数单轮上限；零值不领取，避免历史受理项被连续提交。 |
"""

from __future__ import annotations

import fcntl
import html
import json
import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from video_processing.pipeline_manager import PipelineManager
from video_processing.core.douyin_ui_guard_policy import (
    active_douyin_ui_failure_stages,
    douyin_management_verify_is_blocked,
)
from config.settings import settings
from video_processing.db.database import PipelineDB
from video_processing.telegram_delivery import send_text


LOCK_PATH = PROJECT_ROOT / "output" / "publication_window_runner.lock"
RUN_STATUS_PATH = PROJECT_ROOT / "output" / "publication_window_status.json"
_HEARTBEAT_INTERVAL_SEC = 60


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git_revision() -> str:
    """读取本次实例启动时的 Git revision；不可用时显式标记未知。"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _write_run_status(status: dict[str, Any]) -> None:
    """原子写入单实例运行状态，供日志、面板和事故排查读取。"""
    RUN_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = RUN_STATUS_PATH.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(status, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(RUN_STATUS_PATH)


def _read_run_status() -> dict[str, Any]:
    try:
        return json.loads(RUN_STATUS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _update_run_status(
    status: dict[str, Any],
    status_lock: threading.Lock,
    **updates: Any,
) -> None:
    """串行合并状态更新，避免心跳与阶段回调互相覆盖 JSON。"""
    with status_lock:
        status.update(updates)
        status["last_heartbeat_at"] = updates.get("last_heartbeat_at", _now_iso())
        _write_run_status(status)


def _start_heartbeat(
    status: dict[str, Any],
    status_lock: threading.Lock,
) -> tuple[threading.Event, threading.Thread]:
    """低频刷新存活时间，避免锁跳过日志看起来像无进度。"""
    stop_event = threading.Event()

    def heartbeat() -> None:
        while not stop_event.wait(_HEARTBEAT_INTERVAL_SEC):
            _update_run_status(status, status_lock)

    thread = threading.Thread(target=heartbeat, name="publication-window-heartbeat", daemon=True)
    thread.start()
    return stop_event, thread


def run_publication_window() -> int:
    """串行执行一轮完整流水线；仅在已有巡航仍运行时跳过。"""
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("a+") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            active = _read_run_status()
            logging.info(
                "[PublicationWindow] 上一轮流水线仍在运行，本轮跳过。"
                " run_id=%s pid=%s revision=%s heartbeat=%s",
                active.get("run_id", "unknown"),
                active.get("pid", "unknown"),
                active.get("git_revision", "unknown"),
                active.get("last_heartbeat_at", "unknown"),
            )
            return 0

        started_at = _now_iso()
        status: dict[str, Any] = {
            "run_id": f"{int(time.time())}-{os.getpid()}",
            "pid": os.getpid(),
            "git_revision": _git_revision(),
            "state": "RUNNING",
            "started_at": started_at,
            "last_heartbeat_at": started_at,
        }
        status_lock = threading.Lock()
        _write_run_status(status)
        stop_heartbeat, heartbeat_thread = _start_heartbeat(status, status_lock)

        def report_pipeline_stage(update: dict[str, Any]) -> None:
            _update_run_status(
                status,
                status_lock,
                **update,
                stage_started_at=_now_iso(),
            )
        try:
            logging.info(
                "[AutoPublish] 启动完整流水线。 run_id=%s revision=%s",
                status["run_id"],
                status["git_revision"],
            )
            logging.info(
                "[DouyinPolicy] history_limit=%s action_interval=%s review_limit=%s "
                "new_batch_limit=%s new_daily_limit=%s new_lookback=%s "
                "english_world_batch_limit=%s require_wechat_public=%s",
                settings.douyin_history_daily_limit,
                settings.douyin_browser_action_interval_sec,
                settings.douyin_review_max_per_run,
                settings.douyin_new_sync_max_per_run,
                settings.douyin_new_sync_daily_limit,
                settings.douyin_new_sync_lookback_hours,
                settings.english_world_douyin_sync_max_per_run,
                settings.douyin_require_wechat_public_confirmation,
            )
            PipelineManager(status_reporter=report_pipeline_stage).run_daily_job()
            _update_run_status(status, status_lock, state="COMPLETED")
        except Exception as exc:
            _update_run_status(status, status_lock, state="FAILED", error=str(exc))
            raise
        finally:
            stop_heartbeat.set()
            heartbeat_thread.join(timeout=1)
            ended_at = _now_iso()
            _update_run_status(
                status,
                status_lock,
                ended_at=ended_at,
                last_heartbeat_at=ended_at,
            )
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    return 0


def dispatch_one_deferred_english_world_submission() -> None:
    """仅在公共窗口内唤起一条自动授权项；不处理人工、失败或未确认状态。"""
    if (
        not settings.enable_english_world_auto_publish
        or settings.wechat_publishing_paused
        or not settings.is_public_publish_window()
    ):
        return
    db = PipelineDB()
    db.restore_expired_english_world_operator_recoveries()
    item = db.get_next_auto_approved_english_world_submission()
    if not item:
        return
    review_id = str(item["id"])
    result = subprocess.run(
        [
            str(PROJECT_ROOT / ".venv/bin/python"),
            str(PROJECT_ROOT / "scripts/submit_english_world_review.py"),
            "--review-id",
            review_id,
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30 * 60,
    )
    if result.returncode:
        logging.error(
            "[EnglishWorld] deferred submission worker returned %s for %s: %s",
            result.returncode,
            review_id[:8],
            result.stderr[-500:],
        )


def dispatch_one_english_world_douyin_submission() -> None:
    """按独立正数上限同步视频号已受理且从未建抖音账本的英语世界审核项。"""
    if (
        not settings.enable_english_world_douyin_sync
        or not settings.enable_douyin_browser_publishing
    ):
        return
    max_per_run = max(0, int(settings.english_world_douyin_sync_max_per_run))
    if max_per_run < 1:
        logging.info("[EnglishWorld][Douyin] sync dispatch disabled: max_per_run=%s", max_per_run)
        return
    db = PipelineDB()
    for _ in range(max_per_run):
        item = db.get_next_english_world_douyin_sync_candidate()
        if not item:
            return
        review_id = str(item["id"])
        result = subprocess.run(
            [
                str(PROJECT_ROOT / ".venv/bin/python"),
                str(PROJECT_ROOT / "scripts/submit_english_world_douyin.py"),
                "--review-id", review_id,
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=30 * 60,
        )
        if result.returncode:
            logging.error(
                "[EnglishWorld][Douyin] sync worker returned %s for %s: %s",
                result.returncode,
                review_id[:8],
                result.stderr[-500:],
            )
            return


def reconcile_one_english_world_douyin_submission() -> None:
    """按完整标题和文案只读回查一条英语世界抖音审核项；绝不上传。"""
    if (
        not settings.enable_english_world_douyin_sync
        or not settings.enable_douyin_browser_publishing
    ):
        return
    db = PipelineDB()
    try:
        active_stages = active_douyin_ui_failure_stages(
            db.get_platform_ui_failure_streaks("douyin"),
            recording_threshold=settings.douyin_ui_failure_recording_threshold,
        )
    except Exception:  # noqa: BLE001 - 熔断账本不可读时不能打开创作者中心
        logging.exception("[EnglishWorld][Douyin] 无法读取 UI 熔断账本，跳过管理页回查。")
        return
    if douyin_management_verify_is_blocked(active_stages):
        logging.warning(
            "[EnglishWorld][Douyin] UI 熔断阶段 %s 已激活，领取前跳过管理页回查。",
            ", ".join(sorted(active_stages)),
        )
        return
    item = db.claim_next_english_world_douyin_reconciliation(
        min_interval_minutes=settings.english_world_reconcile_interval_minutes,
        failure_limit=settings.douyin_ui_failure_recording_threshold,
    )
    if not item:
        return
    review_id = str(item["review_id"])
    remaining = db.reserve_douyin_browser_action_slot(
        settings.douyin_browser_action_interval_sec,
        f"english-world:{review_id}:management-verify",
    )
    if remaining > 0:
        logging.info(
            "[EnglishWorld][Douyin] browser action throttled for %.1fs; skip this reconciliation.",
            remaining,
        )
        return
    evidence_dir = (
        PROJECT_ROOT / "output/english_world_douyin/reconciliation"
        / review_id / str(time.time_ns())
    )
    command = [
        str(PROJECT_ROOT / ".venv/bin/python"),
        str(PROJECT_ROOT / "scripts/douyin_uploader.py"),
        "--copy", str(item["copy_path"]),
        "--title-file", str(item["title_path"]),
        "--state", str(PROJECT_ROOT / "output/douyin_state.json"),
        "--evidence-dir", str(evidence_dir),
        "--fail-fast-login",
        "--verify-only",
    ]
    if not settings.douyin_browser_headless:
        command.append("--no-headless")
    pipeline_lock = PROJECT_ROOT / "output/pipeline.lock"
    pipeline_lock.parent.mkdir(parents=True, exist_ok=True)
    with pipeline_lock.open("a+") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logging.info("[EnglishWorld][Douyin] pipeline.lock 正忙，本轮跳过只读回查。")
            return
        try:
            try:
                result = subprocess.run(
                    command,
                    cwd=PROJECT_ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=180,
                )
                observed = {0: "PUBLISHED", 6: "UNDER_REVIEW"}.get(
                    result.returncode, "UNCERTAIN",
                )
                message = {
                    "PUBLISHED": "抖音作品管理页按完整标题/文案确认已发布。",
                    "UNDER_REVIEW": "抖音作品管理页按完整标题/文案确认仍在审核。",
                    "UNCERTAIN": f"抖音作品管理页回查未确认，exit={result.returncode}。",
                }[observed]
            except subprocess.TimeoutExpired:
                observed = "UNCERTAIN"
                message = "抖音作品管理页只读回查超时；保留已受理状态。"
            updated = db.record_english_world_douyin_reconciliation(
                review_id,
                platform_state=observed,
                evidence_dir=str(evidence_dir),
                message=message,
            )
            title = html.escape(str(item.get("title") or review_id[:8]))
            short_review_id = html.escape(review_id[:8])
            if observed == "PUBLISHED":
                send_text(
                    event_type="english_world.douyin_published",
                    priority="P1",
                    text=f"✅ 英语世界抖音已公开\n标题：{title}\n审核编号：{short_review_id}",
                    cooldown_seconds=24 * 60 * 60,
                    dedupe_key=review_id,
                    db=db,
                )
            elif (
                observed == "UNCERTAIN"
                and int(updated.get("reconciliation_failures") or 0)
                >= max(1, int(settings.douyin_ui_failure_recording_threshold))
            ):
                send_text(
                    event_type="english_world.douyin_recording_required",
                    priority="P1",
                    text=(
                        "⚠️ 英语世界抖音回查已连续失败并熔断，不会重传。\n"
                        f"标题：{title}\n审核编号：{short_review_id}\n"
                        "请录制一次从抖音创作者中心进入作品管理并查看该作品状态的流程。"
                    ),
                    cooldown_seconds=24 * 60 * 60,
                    dedupe_key=review_id,
                    db=db,
                )
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _record_english_world_reconciliation_result(
    db: PipelineDB,
    item: dict[str, Any],
    *,
    review_id: str,
    platform_state: str,
    evidence_dir: Path,
    message: str,
) -> dict[str, Any]:
    """统一记录回查结果并在终态或失败阈值到达时发送一次通知。"""
    updated = db.record_english_world_reconciliation(
        review_id,
        platform_state=platform_state,
        evidence_dir=str(evidence_dir),
        message=message,
        platform_url=item.get("platform_url"),
    )
    title = html.escape(str(item.get("title") or review_id[:8]))
    short_review_id = html.escape(review_id[:8])
    if platform_state == "PUBLISHED":
        send_text(
            event_type="english_world.platform_published",
            priority="P1",
            text=f"✅ 英语世界视频号已公开\n标题：{title}\n审核编号：{short_review_id}",
            cooldown_seconds=24 * 60 * 60,
            dedupe_key=review_id,
            db=db,
        )
    elif platform_state == "REJECTED":
        send_text(
            event_type="english_world.platform_rejected",
            priority="P0",
            text=f"⛔ 英语世界视频号审核未通过，已禁止重传\n标题：{title}\n审核编号：{short_review_id}",
            cooldown_seconds=24 * 60 * 60,
            dedupe_key=review_id,
            db=db,
        )
    elif (
        platform_state in {"UNCERTAIN", "NOT_FOUND"}
        and int(updated.get("reconciliation_failures") or 0)
        >= max(1, int(settings.english_world_reconcile_failure_limit))
    ):
        send_text(
            event_type="english_world.reconciliation_recording_required",
            priority="P1",
            text=(
                "⚠️ 英语世界视频号精确回查已连续失败并自动熔断，不会重传。\n"
                f"标题：{title}\n审核编号：{short_review_id}\n"
                "请录制一次从视频号作品管理打开并查看该作品状态的流程，供定位页面变化。"
            ),
            cooldown_seconds=24 * 60 * 60,
            dedupe_key=review_id,
            db=db,
        )
    return updated


def reconcile_one_english_world_submission() -> None:
    """按同次提交绑定的原生 ID 回查一条英语世界作品；不上传、不按标题匹配。"""
    pipeline_lock = PROJECT_ROOT / "output" / "pipeline.lock"
    pipeline_lock.parent.mkdir(parents=True, exist_ok=True)
    with pipeline_lock.open("a+") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logging.info("[EnglishWorld] pipeline.lock 正忙，本轮跳过只读作品回查。")
            return
        try:
            db = PipelineDB()
            item = db.claim_next_english_world_reconciliation(
                min_interval_minutes=settings.english_world_reconcile_interval_minutes,
                max_age_hours=settings.english_world_reconcile_max_age_hours,
                failure_limit=settings.english_world_reconcile_failure_limit,
            )
            if not item:
                return
            review_id = str(item["id"])
            platform_post_id = str(item["platform_post_id"])
            evidence_root = Path(str(item.get("evidence_dir") or PROJECT_ROOT / "output"))
            evidence_dir = evidence_root / "reconciliation" / str(time.time_ns())
            command = [
                str(PROJECT_ROOT / ".venv/bin/python"),
                str(PROJECT_ROOT / "scripts/wechat_uploader.py"),
                "--state", str(PROJECT_ROOT / "output/wechat_state.json"),
                "--evidence-dir", str(evidence_dir),
                "--fail-fast-login",
                "--verify-only",
                "--platform-post-id", platform_post_id,
            ]
            if not settings.wechat_headless:
                command.append("--no-headless")
            try:
                result = subprocess.run(
                    command,
                    cwd=PROJECT_ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=max(30, int(settings.wechat_review_timeout_seconds or 180)),
                )
            except subprocess.TimeoutExpired:
                _record_english_world_reconciliation_result(
                    db,
                    item,
                    review_id=review_id,
                    platform_state="UNCERTAIN",
                    evidence_dir=evidence_dir,
                    message="视频号原生 ID 只读回查超时；保留已受理状态并等待下一次节流回查。",
                )
                return

            outcomes = {
                0: ("PUBLISHED", "management_published.png", "作品管理页按原生 ID 明确显示已发布。"),
                6: ("UNDER_REVIEW", "management_under_review.png", "作品管理页按原生 ID 明确显示仍在审核/处理中。"),
                8: ("REJECTED", "management_rejected.png", "作品管理页按原生 ID 明确显示审核未通过；禁止自动重传。"),
                9: ("NOT_FOUND", "management_not_found.png", "作品管理页按原生 ID 未找到记录；保留提交事实且禁止自动重传。"),
            }
            platform_state, evidence_name, message = outcomes.get(
                result.returncode,
                ("UNCERTAIN", "management_uncertain.png", "视频号原生 ID 只读回查暂不可判定；保留已受理状态。"),
            )
            evidence_path = evidence_dir / evidence_name
            if not evidence_path.is_file():
                platform_state = "UNCERTAIN"
                message = "视频号原生 ID 回查缺少对应页面证据；不改变已受理事实。"
            _record_english_world_reconciliation_result(
                db,
                item,
                review_id=review_id,
                platform_state=platform_state,
                evidence_dir=evidence_dir,
                message=message,
            )
            logging.info(
                "[EnglishWorld] 原生 ID 回查完成 review=%s platform_state=%s",
                review_id[:8], platform_state,
            )
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        reconcile_one_english_world_submission()
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        logging.error("[EnglishWorld] accepted submission reconciliation failed: %s", exc)
    try:
        reconcile_one_english_world_douyin_submission()
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        logging.error("[EnglishWorld][Douyin] accepted submission reconciliation failed: %s", exc)
    try:
        dispatch_one_deferred_english_world_submission()
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        logging.error("[EnglishWorld] deferred submission dispatch failed: %s", exc)
    try:
        dispatch_one_english_world_douyin_submission()
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        logging.error("[EnglishWorld][Douyin] sync dispatch failed: %s", exc)
    return run_publication_window()


if __name__ == "__main__":
    raise SystemExit(main())
