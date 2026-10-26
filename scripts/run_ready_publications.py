"""独立成片发布执行者；不持加工锁，不受发布时间或重负载避让限制。

# Modification History
| backlog-v1 | 2026-10-26 | Codex | TED 专属50分、真实资格展示与成片积压治理。 |
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| runtime-center-v1 | 2026-10-24 | Codex | 接入有版本的统一配置、结构化等待或执行者加载确认；保留原额度与提交保护。 |
| operations-v1 | 2026-10-24 | Codex | 心跳公开实际读取的分用途配置摘要；不访问平台。 |
| 1.7.0 | 2026-10-24 | Codex | 复用就绪巡检轮换两个工作流，持久保存下一顺序，阻止通用队列耗尽英语世界机会。 |
| publishing-recovery-v1 | 2026-10-23 | Codex | 接入发布恢复控制台，复用统一准入并保留任务和投稿保护。 |
| 1.6.0 | 2026-10-18 | AGY | 心跳记录加载时源码与模块指纹，并在派生子 worker 与认领任务前执行空白浏览器能力预检与有界退避 |
| 1.5.0 | 2026-10-10 | Codex | 心跳回读当前 TED 原片清理开关和配方，验证独立执行者运行采用。 |
| 1.4.0 | 2026-10-09 | Codex | 非阻塞唤起独立二创执行者，不阻塞 A 发布。 |
| 1.3.0 | 2026-10-05 | Codex | 心跳暴露字幕共享期限、节流与源下载冷却配置，供运行采用验收。 |
| 1.2.0 | 2026-10-03 | Codex | 心跳暴露已加载的 TED 点赞率门槛及演讲评分线，支持运行采用回读。 |
| 1.0.0 | 2026-09-23 | Codex | 全天巡检已就绪成片，独立进程隔离与可回读心跳。 |
| 1.1.0 | 2026-09-27 | Codex | 心跳记录加载的封面首选方案与队列开关，验证部署采用。 |

| maintenance-v1 | 2026-10-12 | Codex | 接入共用维护准入，保留原业务资格。 |
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
import sys
import subprocess
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from video_processing.utils.wallstreet_worker import ensure_wallstreet_worker
from config.settings import settings
from video_processing.core.task_lease import TaskLease, TaskLeaseBusy
from video_processing.pipeline_manager import PipelineManager
from video_processing.utils.wechat_product_execution import blocked_product_task_keys
from video_processing.utils.wechat_product_task import PUBLISHER_CAPABILITY, product_profile_scope
from video_processing.core.wechat_product_attachment import ATTACHMENT_VERSION


from video_processing.core.maintenance import entry, guarded, gate, running, MaintenanceDenied
from video_processing.core.maintenance_child import child_continuation
from video_processing.core.maintenance_runtime import (
    LOADED_SOURCE_HASH,
    compute_browser_capability_backoff_seconds,
    loaded_modules_hash,
    registered,
    verify_browser_launch_capability,
)

def product_configuration_status():
    from video_processing.utils.wechat_product_config import load_policy
    try:
        policy = load_policy(settings.wechat_product_policy_path)
        return {'product_config_digest': policy.digest, 'product_config_version': policy.version,
                'product_config_readable': True}
    except (OSError, ValueError):
        return {'product_config_digest': None, 'product_config_version': None,
                'product_config_readable': False}


def dispatch_once(manager: PipelineManager) -> int:
    """只取就绪候选，不让高分未加工任务挤占发布名额。"""
    if not running() or settings.wechat_publishing_paused:
        return 0
    from video_processing.core.wechat_request_guard import WeChatRequestGuard, WeChatRequestDeferred
    try:
        if not WeChatRequestGuard(manager._OUT_DIR / "wechat_state.json").evaluate(account_only=True)["allowed"]:
            return 0
    except WeChatRequestDeferred:
        return 0
    videos = manager.db.get_high_score_pending_videos(
        min_score=75, limit=1, ready_only=True,
        channel_min_scores=settings.auto_publish_channel_min_scores,
        excluded_product_tasks=blocked_product_task_keys(ROOT / 'output', settings.wechat_product_policy_path),
    )
    if not videos:
        return 0
    manager._process_single_video(videos[0], submission_only=True)
    return 1


def dispatch_english_world_once(manager: PipelineManager) -> int:
    """既有自动授权的英语世界成片同样独立续投，保留专用投稿器的全部闸门。"""
    if not running() or not settings.enable_english_world_auto_publish or settings.wechat_publishing_paused:
        return 0
    from video_processing.core.wechat_request_guard import WeChatRequestGuard, WeChatRequestDeferred
    try:
        if not WeChatRequestGuard(manager._OUT_DIR / "wechat_state.json").evaluate(account_only=True)["allowed"]:
            return 0
    except WeChatRequestDeferred:
        return 0
    manager.db.restore_expired_english_world_operator_recoveries()
    item = manager.db.get_next_auto_approved_english_world_submission(
        excluded_product_tasks=blocked_product_task_keys(ROOT / 'output', settings.wechat_product_policy_path))
    if not item:
        return 0
    review_id = str(item["id"])
    with gate().admit("english-submit", "review:" + review_id) as ticket:
        ticket.start()
        manager._report_runtime_stage(review_id, "ENGLISH_WORLD_SUBMISSION")
        cmd = [str(ROOT / ".venv/bin/python"), str(ROOT / "scripts/submit_english_world_review.py"), "--review-id", review_id]
        with child_continuation(cmd, dict(cwd=ROOT, timeout=1800, check=False)) as kwargs:
            result = subprocess.run(cmd, **kwargs)
    logging.info("英语世界提交执行者退出 review=%s code=%s", review_id, result.returncode)
    return 1


def dispatch_ready_round(manager: PipelineManager) -> int:
    """同一账户每轮只执行一个工作流；忙/额度仍由原准入控制，崩溃后沿用顺序。"""
    from video_processing.core.deployment import write_json
    path = manager._OUT_DIR / 'ready_publications.turn.json'
    if path.exists():
        value = json.loads(path.read_text())
        if value.get('next') not in {'english_world', 'general'}:
            raise ValueError('发布轮次记录损坏，保留现场')
        first = value['next']
    else:
        first = 'english_world'
    dispatchers = {'english_world': dispatch_english_world_once, 'general': dispatch_once}
    second = 'general' if first == 'english_world' else 'english_world'
    for domain, following in ((first, second), (second, first)):
        if dispatchers[domain](manager):
            write_json(path, {'schema': 1, 'next': following})
            return 1
    return 0


@entry
@registered("ready-worker")
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    out = ROOT / "output"
    out.mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                  capture_output=True, text=True, timeout=5)
        git_revision = revision.stdout.strip() if revision.returncode == 0 else "unknown"
    except (OSError, subprocess.TimeoutExpired):
        git_revision = "unknown"
    from video_processing.core.ffmpeg_slot import config_status
    from video_processing.processors.ted_source_cleanup import RECIPE as cleanup_recipe
    state = {"pid": os.getpid(), "stage": "IDLE", "current_video": None,
             "git_revision": git_revision,
             "loaded_source_hash": LOADED_SOURCE_HASH,
             "loaded_modules_hash": loaded_modules_hash(),
             "browser_capability": {"ok": None, "checked_at": None, "reason": None},
             "product_publisher_capability": PUBLISHER_CAPABILITY,
             "product_attachment_version": ATTACHMENT_VERSION,
             "product_internal_profile_scope": product_profile_scope(out / 'wechat_state.json'),
             "ffmpeg_guard_enabled": subprocess.Popen.__module__ == "video_processing.core.ffmpeg_slot",
             **config_status(),
             "ai_cover_primary_provider": settings.ai_cover_primary_provider,
             "ai_cover_queue_enabled": settings.enable_codex_cover_queue,
             "ted_source_cleanup_enabled": settings.enable_ted_source_cleanup,
             "ted_opening_trim_enabled": settings.enable_ted_opening_trim,
             "ted_source_cleanup_recipe": cleanup_recipe,
             "ted_min_like_rate_pct": settings.ted_min_like_rate_pct,
             "speech_publish_score_line": settings.speech_publish_score_line,
             "ted_publish_score_line": settings.ted_publish_score_line,
             "ready_metric_refresh_enabled": settings.enable_ready_metric_refresh,
             "subtitle_translation_total_timeout_seconds": settings.subtitle_translation_total_timeout_seconds,
             "google_translate_interval_seconds": settings.google_translate_interval_seconds,
             "youtube_auth_cooldown_seconds": settings.youtube_auth_cooldown_seconds,
             "started_at": time.time(), "stage_started_at": time.time()}
    stopped = threading.Event()
    state_lock = threading.Lock()
    status_path = out / "ready_publications_status.json"
    browser_capability_verified = False
    browser_capability_failures = 0
    last_runtime_revision = None

    def report(update):
        with state_lock:
            if update.get("stage") != state.get("stage") or update.get("current_video") != state.get("current_video"):
                state["stage_started_at"] = time.time()
            state.update(update)

    def heartbeat():
        nonlocal last_runtime_revision
        while not stopped.is_set():
            with state_lock:
                snapshot = dict(state, heartbeat_at=time.time(), **config_status(), **product_configuration_status())
            from video_processing.utils.wechat_operations_policy import load_policy, revision
            try:
                policy = load_policy()
                snapshot["wechat_operations"] = {"enabled": policy is not None, "loaded_revision": revision(policy) if policy else None,
                                                   "loaded_at": time.time(), "error": None}
            except Exception as exc:
                snapshot["wechat_operations"] = {"enabled": True, "loaded_revision": None, "loaded_at": time.time(), "error": type(exc).__name__}
            try:
                from video_processing.utils.runtime_configuration import acknowledge, snapshot as runtime_snapshot, recompute_waits
                current_policy = runtime_snapshot(fresh=True)
                if current_policy and current_policy.revision != last_runtime_revision:
                    recompute_waits(manager.db, current_policy)
                    last_runtime_revision = current_policy.revision
                snapshot['runtime_configuration'] = acknowledge('ready-worker')
            except Exception as exc:
                snapshot['runtime_configuration'] = {'error':type(exc).__name__,'loaded_revision':None}
            temp = status_path.with_suffix(".tmp")
            temp.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
            temp.replace(status_path)
            stopped.wait(5)

    try:
        with TaskLease(out / "ready_publications.lock", stage="全天发布巡检"):
            manager = PipelineManager(
                str(out / "pipeline.db"), status_reporter=report,
                trigger_source="ready_worker",
            )
            worker = threading.Thread(target=heartbeat, daemon=True)
            worker.start()
            try:
                while True:
                    try:
                        if not running():
                            if args.once:
                                return 0
                            time.sleep(15)
                            continue
                        if not browser_capability_verified:
                            cap = verify_browser_launch_capability()
                            if not cap.get("ok"):
                                browser_capability_failures += 1
                                backoff_sec = compute_browser_capability_backoff_seconds(browser_capability_failures)
                                logging.error(
                                    "[ReadyPublication] 浏览器能力预检未通过（第 %d 次，退避 %ds），阻止业务认领与子 worker 派生: %s",
                                    browser_capability_failures,
                                    backoff_sec,
                                    cap.get("reason"),
                                )
                                report({
                                    "stage": "BROWSER_CAPABILITY_UNAVAILABLE",
                                    "current_video": None,
                                    "browser_capability": cap,
                                })
                                if args.once:
                                    return 1
                                for _ in range(backoff_sec):
                                    time.sleep(1)
                                    if not running():
                                        break
                                continue
                            browser_capability_verified = True
                            browser_capability_failures = 0
                            report({"browser_capability": cap})
                        report({"stage": "POLLING", "current_video": None})
                        ensure_wallstreet_worker()
                        from video_processing.utils.delivery_recovery_worker import ensure_delivery_recovery_worker
                        ensure_delivery_recovery_worker(manager.db, ROOT)
                        from video_processing.utils.publishing_recovery_worker import ensure_publishing_recovery_worker
                        ensure_publishing_recovery_worker(manager.db, ROOT)
                        attempted = dispatch_ready_round(manager)
                        report({"stage": "IDLE", "current_video": None})
                    except Exception:
                        logging.exception("成片发布巡检失败；保留状态供下一轮恢复")
                        report({"stage": "ERROR"})
                        attempted = 0
                    if args.once:
                        return 0
                    # 完成一条即继续；被会话占用时最多每 15 秒重试。
                    wake = out / "ready_publications.wake"
                    version = wake.stat().st_mtime_ns if wake.exists() else 0
                    delay = 15
                    if attempted:
                        row = manager.db.get_high_score_pending_videos(limit=1, ready_only=True,
                            excluded_product_tasks=blocked_product_task_keys(out, settings.wechat_product_policy_path))
                        if row and not str(row[0].get("publication_wait_reason") or "").startswith("同账号"):
                            delay = 1
                    for _ in range(delay):
                        time.sleep(1)
                        if wake.exists() and wake.stat().st_mtime_ns != version:
                            break
            finally:
                stopped.set()
                worker.join(timeout=6)
    except TaskLeaseBusy:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
