"""统一执行状态与恢复调度；只读准入不消费账号额度。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-22 | Codex | 复用账号策略、维护准入与已有管线；等待请求跨重启保存。 |
"""
import copy
import time
from config.settings import settings
from video_processing.core.maintenance import gate
from video_processing.core.task_lease import read_lease_owner
from video_processing.core.wechat_account_schedule import admission
from video_processing.core.wechat_request_guard import WeChatRequestGuard, WeChatRequestDeferred


def execution_status(db, out, video=None, *, task=None):
    blockers = []
    maintenance = gate().status()
    if maintenance.get('state') != 'RUNNING':
        blockers.append('系统维护尚未恢复或状态无法确认')
    if settings.wechat_publishing_paused:
        blockers.append('视频号发布已暂停')
    info = None
    try:
        guard = WeChatRequestGuard(out / 'wechat_state.json')
        info = guard.cooldown()
        if info['active']:
            blockers.append(info['reason'])
        if settings.wechat_account_scheduler_enabled:
            row = copy.deepcopy(guard.snapshot())
            # 不持久排队、不预占预算；真实会话仍在原子准入内复检。
            reason = admission(row, time.time(), '发布', task or '__execution_status__')
            if reason:
                blockers.append(reason)
    except (WeChatRequestDeferred, OSError, ValueError) as exc:
        blockers.append('账号调度状态无法确认：' + str(exc))
    request = None
    if video:
        yid, index = video['youtube_id'], int(video.get('slice_index') or 0)
        reason = db.execution_task_blocker(yid, index)
        if reason:
            blockers.append(reason)
        request = db.execution_recovery(yid, index)
    return dict(blockers=list(dict.fromkeys(blockers)), cooldown=info,
                maintenance=maintenance.get('state', 'UNKNOWN'), request=request,
                prepared=bool(video and video.get('preparation_ready')))


def recovery_view(db, out):
    result = execution_status(db, out)
    rows = db.list_execution_recovery()
    for row in rows:
        prefix = row['youtube_id'] + (f"_s{row['slice_index']}" if row['slice_index'] else '')
        if row['state'] == 'RUNNING' and not read_lease_owner(out / 'task_locks' / (prefix + '.lock')):
            # 不重领崩溃后的未知结果；账本仍保留原认领，可人工检查。
            row['display_state'] = 'ATTENTION'
            row['message'] = '执行者已退出，结果需核验；不会自动重做'
        video = db.get_video_by_youtube_id(row['youtube_id'], slice_index=row['slice_index'])
        row['blockers'] = execution_status(db, out, video)['blockers'] if row['state'] == 'WAITING' else []
    result['requests'] = rows
    return result


def dispatch_recovery_once(manager):
    """真实业务仍通过 PipelineManager 的任务锁和发布闸门。"""
    if gate().status().get('state') != 'RUNNING':
        return 0
    for request in manager.db.list_execution_recovery(waiting_only=True):
        video = manager.db.get_video_by_youtube_id(request['youtube_id'], slice_index=request['slice_index'])
        if not video:
            continue
        prefix = video['youtube_id'] + (f"_s{video['slice_index']}" if video.get('slice_index') else '')
        task = prefix
        if video.get('preparation_ready'):
            try:
                task = str(manager._get_published_video_path(prefix).resolve())
            except (ValueError, RuntimeError, OSError):
                manager.db.update_execution_recovery(request['id'], 'ATTENTION', '成片校验未通过，请检查产物', expected='WAITING')
                continue
        state = execution_status(manager.db, manager._OUT_DIR, video, task=task)
        if state['blockers']:
            manager.db.note_execution_recovery(request['id'], '；'.join(state['blockers']))
            continue
        if video.get('slice_index') and not manager._find_downloaded_video(video['youtube_id']):
            manager.db.note_execution_recovery(request['id'], '等待父视频主文件就绪')
            continue
        return int(bool(manager._process_single_video(video, recovery_request=request['id'],
            preparation_only=not bool(video.get('preparation_ready')),
            submission_only=bool(video.get('preparation_ready')))))
    return 0
