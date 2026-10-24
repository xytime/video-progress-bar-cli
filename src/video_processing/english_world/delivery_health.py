"""现有英语世界窗口监测的本地交付事实，不回查平台、不启动业务。

依赖：monitor script → 本模块 → DAL/纯准入及商品等待规则。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-24 | Codex | 区分库存和实际受理，24小时无受理需解释依赖阻塞并沿既有监测报告。 |
| 1.1.0 | 2026-10-24 | Codex | 核验同一冻结包的点击返回回执，与平台受理分列；意图、草稿及不明回执不算真实提交动作。 |
"""
import json
from datetime import datetime, timedelta, timezone
import math
from pathlib import Path
from tempfile import TemporaryDirectory

from config.settings import settings
from video_processing.core.wechat_account_schedule import evaluate
from video_processing.db.database import PipelineDB
from video_processing.utils.wechat_product_execution import blocked_product_task_keys


def delivery_health(database: Path, *, now: datetime) -> dict:
    """全部只读；缺库/坏账本由调用方明确报未知，不能冒充健康。"""
    with TemporaryDirectory(prefix='english-world-health-') as temporary:
        saved = Path(temporary)/'snapshot.db'
        PipelineDB.maintenance_backup(database, saved)
        return _delivery_health(PipelineDB(str(saved), read_only=True), database, now)


def _delivery_health(db, database, now):
    blocked = blocked_product_task_keys(database.parent, settings.wechat_product_policy_path)
    since = now.astimezone(timezone.utc) - timedelta(days=1)
    result = db.get_english_world_delivery_flow(action_since=since.strftime('%Y-%m-%d %H:%M:%S'))
    clicks = []
    for row in result.pop('action_evidence_candidates'):
        try:
            video = Path(row['mp4_path']).resolve()
            directory = Path(row['evidence_dir']).resolve()
            if directory.parent != video.parent/'wechat_evidence':
                continue
            receipt = json.loads((directory/'submission_attempt.json').read_text())
            recorded = receipt['recorded_at']
            if (receipt.get('video') != str(video) or receipt.get('submit_click_returned') is not True
                    or receipt.get('draft_requested') is not False
                    or receipt.get('automatic_result_queries') is not False
                    or type(recorded) not in (int,float) or not math.isfinite(recorded)
                    or not since.timestamp() <= recorded <= now.timestamp()):
                continue
            started = datetime.fromisoformat(row['started_at']).replace(tzinfo=timezone.utc).timestamp()
            if recorded < started-1:
                continue
            clicks.append(recorded)
        except (OSError, ValueError, KeyError, TypeError):
            continue
    result['last_submit_action_at'] = (datetime.fromtimestamp(max(clicks),timezone.utc).isoformat() if clicks else None)
    result['automatic_inventory'] = db.get_english_world_inventory_count(excluded_product_tasks=blocked)
    approved = sum(row['count'] for row in result['states'] if row['state'] == 'SUBMISSION_APPROVED'
                   and row['approval_source'] == 'AUTO_POLICY')
    result['automatic_waiting'] = approved
    result['blocked_automatic_inventory'] = approved - result['automatic_inventory']
    progress = []
    accepted = None
    for raw in (result['last_accepted_receipt_at'],result['last_submit_action_at']):
        if raw:
            value = datetime.fromisoformat(raw)
            value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
            if raw == result['last_accepted_receipt_at']:
                accepted = value
            progress.append(value)
    last = max(progress) if progress else (datetime.fromisoformat(result['first_created_at']).replace(tzinfo=timezone.utc)
                                         if result['first_created_at'] else None)
    result['stalled'] = last is not None and (now.astimezone(timezone.utc) - last).total_seconds() >= 86400
    account = database.parent / '.wechat_state.json.requests.json'
    from video_processing.utils.wechat_scheduler_policy import sync_wechat_scheduler_settings
    sync_wechat_scheduler_settings()
    result['account_blockers'] = evaluate(json.loads(account.read_text()), now.timestamp(), account_only=True)['blockers'] if account.exists() else []
    result['account_evidence'] = 'LOCAL_ONLY' if account.exists() else 'UNKNOWN'
    result['state'] = ('DELIVERY_STALLED' if result['stalled'] else
                       'RECENT_LOCAL_ACCEPTANCE' if accepted and 0 <= (now.astimezone(timezone.utc)-accepted).total_seconds() < 86400 else
                       'RECENT_SUBMIT_ACTION' if result['last_submit_action_at'] else
                       'AWAITING_FIRST_ACCEPTANCE' if result['first_created_at'] else 'NO_HISTORY')
    return result
