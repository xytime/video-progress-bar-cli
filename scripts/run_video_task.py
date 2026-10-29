"""单视频子进程入口；真实归属随 FD 继承，视频数据经 stdin 传入。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-12 | Codex | 替换 Web 内联执行并保持单项维护归属 |
| 1.1.0 | 2026-10-29 | Codex | canary 只预加工，资源就绪才 claim，等待/让行不进入失败态。 |
| 1.1.1 | 2026-10-29 | Codex | claim 后仅观测 owner 匹配的持久排队墙钟；缺失或读取失败保持未知。 |
"""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from video_processing.core.maintenance import current, MaintenanceDenied
from video_processing.core.maintenance_child import single_script
from video_processing.pipeline_manager import PipelineManager


@single_script
def _legacy(video, args):
    manager = PipelineManager(trigger_source=args.trigger_source)
    manager._process_single_video(video, preparation_only=args.preparation_only,
                                  submission_only=args.submission_only)
    manager.wait_for_review_notifications(timeout=120.0)
    return 0


def _preparation(video, args):
    import os
    import hashlib
    import time
    from config.settings import settings
    from video_processing.core.maintenance import gate
    from video_processing.core.maintenance_runtime import process_birth
    from video_processing.core.preparation_dispatch import canary_sources
    from video_processing.core.preparation_resources import (setup_execution_context, execution_context,
        PreparationBusy, PreparationYielded)
    from video_processing.utils.stage_events import StageJournal, bind_journal, persistent_queue_wait_seconds
    if video['youtube_id'] not in canary_sources(settings):
        raise ValueError('preparation task is outside explicit canary allowlist')
    scope = setup_execution_context()
    if scope is None or scope.owner != args.preparation_owner or scope.key != args.object_key:
        raise ValueError('preparation worker has no inherited ownership')
    manager = PipelineManager(trigger_source=args.trigger_source)
    task_hash = hashlib.sha256(args.object_key.encode()).hexdigest()[:24]
    journal = StageJournal(manager._OUT_DIR / '.stage-events' / task_hash / (scope.owner + '.jsonl'),
                           task_id=args.object_key, attempt_id=scope.owner) if settings.enable_pipeline_stage_events else None
    outcome = 'unknown'
    try:
        with bind_journal(journal), gate().admit('preparation-worker', args.object_key) as admission:
            with execution_context(manager._OUT_DIR, args.object_key, scope.owner):
                waiting_at = time.monotonic()
                scope.switch('network', 'WAITING_ADMISSION')
                admission.start()  # 资源等待后重新核实维护；此处之前不修改视频 FSM。
                fresh = manager.db.get_video_by_youtube_id(video['youtube_id'], slice_index=int(video.get('slice_index') or 0))
                prefix = video['youtube_id'] + (f"_s{int(video.get('slice_index') or 0)}" if video.get('slice_index') else '')
                if manager._wechat_submission_evidence_paths(prefix) or manager._has_wechat_submission_terminal_state(
                        video['youtube_id'], slice_index=int(video.get('slice_index') or 0)):
                    manager.db.finish_preparation_execution(fresh['id'], scope.owner, state='BLOCKED', reason='submission evidence excludes preparation')
                    outcome = 'blocked_submission'
                    return 0
                if not manager.db.start_preparation_execution(video['youtube_id'], int(video.get('slice_index') or 0), scope.owner,
                        pid=os.getpid(), birth=process_birth(os.getpid())):
                    manager.db.finish_preparation_execution(fresh['id'], scope.owner, state='BLOCKED', reason='claim or eligibility changed')
                    outcome = 'not_claimed'
                    return 0
                if journal:
                    journal.emit('queue_claim', duration_seconds=max(0, time.monotonic()-waiting_at), owner_token=scope.owner)
                    try:
                        queued = next((row.get('queued_at') for row in manager.db.preparation_queue_snapshot()
                            if row['video_id'] == fresh['id'] and row.get('owner_token') == scope.owner), None)
                    except Exception:
                        # 观测失败不能改变已完成的资源/业务准入，也不能编造零等待。
                        queued = None
                    journal.emit('queue_wait', stage='WAITING_PREPARATION_QUEUE',
                        duration_seconds=persistent_queue_wait_seconds(queued), owner_token=scope.owner,
                        category='persistent_wall_clock_approximation')
                manager._preparation_execution = scope
                manager._preparation_video_id = fresh['id']
                try:
                    manager._process_single_video(fresh, preparation_only=True, claim=False)
                except PreparationYielded:
                    # 仍在原单项 ACTIVE 准入内回写；维护关闸不能截断在途安全收尾。
                    if not manager.db.yield_preparation_execution(video['youtube_id'], int(video.get('slice_index') or 0), scope.owner):
                        raise RuntimeError('yield ownership or submission boundary changed')
                    outcome = 'yielded'
                    return 0
                except PreparationBusy:
                    manager.db.finish_preparation_execution(fresh['id'], scope.owner, state='WAITING',
                        reason='resource owner cannot be verified; no quality failure')
                    outcome = 'waiting_resource_owner_unknown'
                    return 0
                row = next(r for r in manager.db.preparation_queue_snapshot() if r['video_id'] == fresh['id'])
                business = manager.db.get_video_by_youtube_id(video['youtube_id'], slice_index=int(video.get('slice_index') or 0))
                state = 'DONE' if row['local_preparation'] else ('WAITING' if business['status'] == 'PENDING' else 'BLOCKED')
                manager.db.finish_preparation_execution(fresh['id'], scope.owner, state=state,
                    reason='LOCAL_READY; no publication admission' if state == 'DONE' else 'preparation stopped; inspect original business state')
                outcome = 'local_prepared' if state == 'DONE' else 'preparation_stopped'
        return 0
    except (PreparationBusy, MaintenanceDenied) as exc:
        try:
            manager.db.finish_preparation_execution(video['id'], scope.owner, state='WAITING', reason=type(exc).__name__)
        except MaintenanceDenied:
            # 关闸时不另造写入许可；保留 RESERVED 票据，由排空对账恢复。
            outcome = 'waiting_maintenance_reconcile'
            return 0
        outcome = 'waiting'
        return 0
    finally:
        if journal:
            journal.close(outcome)
        scope.close()


def main():
    if current() is None:
        from video_processing.core.maintenance import gate
        gate().require_running()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--trigger-source", required=True)
    parser.add_argument("--object-key", required=True)
    parser.add_argument('--preparation-only', action='store_true', help='只执行预加工不触发提交')
    parser.add_argument('--submission-only', action='store_true', help='只执行提交不重复预加工')
    parser.add_argument('--preparation-owner')
    args = parser.parse_args()
    if ((args.preparation_only and args.submission_only)
            or (args.preparation_owner and args.submission_only)):
        parser.error('preparation and submission modes cannot be combined')
    video = json.load(sys.stdin)
    key = f"{video['youtube_id']}:{int(video.get('slice_index') or 0)}"
    if key != args.object_key or (current() and current().row.get("parent") and current().key != key):
        raise MaintenanceDenied("INVALID_CONTINUATION")
    return _preparation(video, args) if args.preparation_owner else _legacy(video, args)


if __name__ == "__main__":
    raise SystemExit(main())
