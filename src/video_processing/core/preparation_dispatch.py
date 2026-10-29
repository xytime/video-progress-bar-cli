"""有限 canary 预加工派发；最多两个独立进程，不共享 PipelineManager 线程。

依赖：scripts / pipeline_manager → 本模块 → resources / maintenance / DAL。
关闸仅停止新领取，现有子孙自然排空；跨代 FD 未归零前旧执行器无法穿透。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-29 | Codex | 默认关闭、三源允许名单、两进程有限派发与 owner CAS。 |
"""
from __future__ import annotations
import json
import subprocess
import time
import fcntl
from pathlib import Path
from .maintenance import gate, MaintenanceDenied
from .preparation_resources import PreparationCohort
from ..utils.stage_events import emit_event, persistent_queue_wait_seconds


def _recover_drained_cohort(db, output):
    """仅在新 cohort 已独占跨代锁后调用；旧子孙只要活着就会保留该 FD。"""
    from .maintenance_runtime import process_birth
    for row in db.preparation_queue_snapshot():
        if row['state'] not in {'RESERVED', 'RUNNING'}:
            continue
        if row.get('owner_pid'):
            try:
                if process_birth(row['owner_pid']) == row.get('owner_birth'):
                    continue
            except ProcessLookupError:
                pass
            except (OSError, ValueError, subprocess.SubprocessError):
                continue  # 不能核实归属时闭锁。
        prefix = row['youtube_id'] + (f"_s{row['slice_index']}" if row['slice_index'] else '')
        safe = True
        for path in (Path(output) / 'task_locks' / (prefix+'.lock'),
                     Path(output) / 'source_locks' / (row['youtube_id']+'.lock')):
            try:
                with path.open('r+') as stream:
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except FileNotFoundError:
                continue
            except (BlockingIOError, OSError):
                safe = False
                break
        if safe:
            db.recover_preparation_execution(row['video_id'], row['owner_token'])


def canary_sources(config):
    if not getattr(config, 'enable_preparation_dispatch', False):
        return ()
    value = getattr(config, 'preparation_dispatch_allowlist', ())
    if isinstance(value, str):
        value = tuple(part.strip() for part in value.split(',') if part.strip())
    sources = tuple(dict.fromkeys(value))
    if not 1 <= len(sources) <= 3:
        raise ValueError('preparation dispatch requires one to three explicit source IDs')
    if (getattr(config, 'preparation_heavy_slots', 1), getattr(config, 'preparation_network_slots', 1)) != (1, 1):
        raise ValueError('canary resource limits must remain heavy=1/network=1')
    return sources


def run_preparation_dispatch(db, config, *, output, project, popen=subprocess.Popen, sleep=time.sleep):
    """显式入口；不开发布执行者，不认领已投稿任务。退出0只表示派发循环完成。"""
    from .maintenance_runtime import process_birth
    sources = canary_sources(config)
    if not sources:
        return {'state': 'DISABLED', 'started': 0}
    gate().require_running()
    try:
        cohort = PreparationCohort(output)
    except BlockingIOError:
        emit_event('queue_wait', stage='WAITING_LEGACY_OR_COHORT', outcome='unknown_wait_duration')
        return {'state': 'WAITING_LEGACY_OR_COHORT', 'started': 0}
    workers, started = [], 0
    try:
        _recover_drained_cohort(db, output)
        while True:
            for proc, row in list(workers):
                if proc.poll() is None:
                    continue
                workers.remove((proc, row))
                # 正常 worker 自己写精确结果；未回执的崩溃保留 RESERVED/RUNNING，
                # 下次不能以 PID 消失自动回队（可能仍有孤儿子孙持写租约）。
            draining = not canary_sources(config)
            try:
                gate().require_running()
            except MaintenanceDenied:
                draining = True
            launched = False
            while not draining and len(workers) < 2:
                row = db.reserve_preparation(sources)
                if row is None:
                    break
                emit_event('queue_reserved', stage='RESERVED', owner_token=row['owner_token'],
                           duration_seconds=persistent_queue_wait_seconds(row.get('queued_at')),
                           category='persistent_wall_clock_approximation')
                key = f"{row['youtube_id']}:{row['slice_index']}"
                video = db.get_video_by_youtube_id(row['youtube_id'], slice_index=row['slice_index'])
                command = [str(Path(project) / '.venv/bin/python'), str(Path(project) / 'scripts/run_video_task.py'),
                           '--trigger-source', row['trigger_source'], '--object-key', key,
                           '--preparation-owner', row['owner_token']]
                options = cohort.options(key, row['owner_token'], dict(cwd=str(project), text=True,
                    stdin=subprocess.PIPE, start_new_session=True))
                try:
                    proc = popen(command, **options)
                    proc.stdin.write(json.dumps(video))
                    proc.stdin.close()
                    db.attach_preparation_worker(row['video_id'], row['owner_token'], proc.pid, process_birth(proc.pid))
                except Exception:
                    # 如果已产生进程，其执行状态不明，保持闭锁，不声称可以安全回队。
                    raise
                workers.append((proc, row))
                started += 1
                launched = True
            if not workers:
                return {'state': 'DRAINED' if draining else 'IDLE', 'started': started}
            if not launched:
                sleep(min(30, max(.1, float(getattr(config, 'preparation_queue_poll_seconds', 5)))))
    finally:
        # 仅 close；本进程异常/退出仍有子孙时，继承 FD 继续挡住旧粗锁路径。
        cohort.close()
