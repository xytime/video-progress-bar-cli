"""高互动刷新结果：逐次采集回执、互斥与重启后中断识别。

依赖方向：web/app → 本模块 → core/task_lease、maintenance；采集由入口注入。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-25 | Codex | 持久化新增数量、零新增原因和素材去向 |
"""
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import uuid

from video_processing.core.maintenance import MaintenanceDenied, current
from video_processing.core.task_lease import TaskLease, TaskLeaseBusy, read_lease_owner


def result_message(result: dict) -> str:
    """只用本次采集计数解释结果，不以列表总量差推断新增。"""
    report = result.get('report', {})
    added = report.get('added', 0)
    outcome = result['outcome']
    if outcome == 'unknown':
        return '上次高互动刷新结果读取失败，新增数量尚未核实；可稍后手动重试。素材进入「近期高互动」，查看时请核对当前筛选。'
    if outcome == 'running':
        return f"高互动素材刷新中，已新增 {added} 条至「近期高互动」；请等待采集结果。"
    if outcome == 'interrupted':
        lead = f"高互动刷新已中断，已记录新增 {added} 条；任务未完成，最终新增数量尚未核实。"
    elif outcome == 'error':
        lead = f"高互动刷新失败，已新增 {added} 条。"
    else:
        label = '部分完成' if outcome == 'partial' else '完成'
        lead = f"高互动刷新{label}，新增 {added} 条。"
    reasons = []
    for field, template in (
        ('duplicates', '已有记录 {n} 条，未重复入库'),
        ('blocked', '入库保护规则排除 {n} 条'),
        ('outdated', '超出最近 3 天发布窗口 {n} 条'),
        ('low_views', '观看量未超过 500 的 {n} 条'),
        ('invalid', '元数据不完整或无法解析 {n} 条'),
        ('failed', '搜索或采集失败 {n} 组'),
        ('timeouts', '搜索超时 {n} 组'),
    ):
        if report.get(field):
            reasons.append(template.format(n=report[field]))
    if not added and not reasons and outcome == 'complete':
        reasons.append('本次搜索未返回符合采集条件的视频' if report.get('searches') else '没有可执行的搜索词')
    if reasons:
        lead += ' ' + '；'.join(reasons) + '。'
    if result.get('error_reason'):
        lead += ' ' + result['error_reason'] + '。'
    if outcome in {'error', 'partial', 'interrupted'}:
        lead += ' 可稍后手动重试。'
    return lead + ' 素材进入「近期高互动」，不进入「待筛选」；查看时请核对频道、入库时间等当前筛选。'


class HighLikesRefresh:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.lock_path = self.path.with_suffix('.lock')

    def _read(self):
        try:
            result = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(result, dict) or not {'run_id', 'outcome', 'report'} <= result.keys() or not isinstance(result['report'], dict):
                raise ValueError('invalid refresh receipt')
            return result
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            return dict(run_id='unreadable', outcome='unknown', report={})

    def _save(self, result):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
        temporary.replace(self.path)

    def status(self):
        result = self._read()
        running = bool(read_lease_owner(self.lock_path))
        if result:
            if result['outcome'] == 'running' and not running:
                result['outcome'] = 'interrupted'
            result['message'] = result_message(result)
        return dict(running=running, result=result)

    def start(self, collect, dispatch):
        lease = TaskLease(self.lock_path, stage='high-likes-refresh')
        try:
            lease.__enter__()
        except TaskLeaseBusy:
            return dict(started=False, message='刷新任务已在进行中，请稍候。')
        result = dict(run_id=uuid.uuid4().hex, outcome='running', report={},
                      destination='high_likes', started_at=datetime.now(timezone.utc).isoformat())

        def progress(report):
            result['report'] = dict(report)
            self._save(result)

        def finish(outcome):
            result.update(outcome=outcome, finished_at=datetime.now(timezone.utc).isoformat())
            self._save(result)

        def run():
            try:
                ticket = current()
                if ticket:
                    ticket.start()
                report = collect(progress)
                progress(report)
                errors = report.get('failed', 0) + report.get('timeouts', 0)
                finish(('error' if errors == report.get('completed') else 'partial') if errors else 'complete')
            except MaintenanceDenied:
                finish('interrupted')
            except Exception:
                logging.getLogger(__name__).exception('[HighLikes] refresh failed')
                result['error_reason'] = '采集发生异常，本次搜索未完整完成'
                finish('error')
            finally:
                lease.__exit__(None, None, None)

        try:
            self._save(result)
            # 等待项由 run 内启动，确保维护竞态也能记录结果并释放任务锁。
            dispatch(run, role='high-like-dispatch', object_key='high-like-dispatch',
                     name='high-likes-refresh', waiting=True)
        except BaseException as exc:
            try:
                finish('interrupted' if isinstance(exc, MaintenanceDenied) else 'error')
            finally:
                lease.__exit__(None, None, None)
            raise
        return dict(started=True, run_id=result['run_id'],
                    message='高互动素材刷新已启动；完成后将显示新增数量，素材进入「近期高互动」。')
