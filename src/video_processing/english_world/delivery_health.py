"""现有英语世界窗口监测的本地交付事实，不回查平台、不启动业务。

依赖：monitor script → 本模块 → DAL/纯准入及商品等待规则。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-24 | Codex | 区分库存和实际受理，24小时无受理需解释依赖阻塞并沿既有监测报告。 |
"""
import json
from datetime import datetime, timezone
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
    result = db.get_english_world_delivery_flow()
    result['automatic_inventory'] = db.get_english_world_inventory_count(excluded_product_tasks=blocked)
    approved = sum(row['count'] for row in result['states'] if row['state'] == 'SUBMISSION_APPROVED'
                   and row['approval_source'] == 'AUTO_POLICY')
    result['automatic_waiting'] = approved
    result['blocked_automatic_inventory'] = approved - result['automatic_inventory']
    raw = result['last_accepted_receipt_at'] or result['first_created_at']
    last = datetime.fromisoformat(raw) if raw else None
    if last is not None:
        last = last.replace(tzinfo=timezone.utc) if last.tzinfo is None else last.astimezone(timezone.utc)
    result['stalled'] = last is not None and (now.astimezone(timezone.utc) - last).total_seconds() >= 86400
    account = database.parent / '.wechat_state.json.requests.json'
    from video_processing.utils.wechat_scheduler_policy import sync_wechat_scheduler_settings
    sync_wechat_scheduler_settings()
    result['account_blockers'] = evaluate(json.loads(account.read_text()), now.timestamp(), account_only=True)['blockers'] if account.exists() else []
    result['account_evidence'] = 'LOCAL_ONLY' if account.exists() else 'UNKNOWN'
    result['state'] = ('DELIVERY_STALLED' if result['stalled'] else
                       'RECENT_LOCAL_ACCEPTANCE' if result['last_accepted_receipt_at'] else
                       'AWAITING_FIRST_ACCEPTANCE' if result['first_created_at'] else 'NO_HISTORY')
    return result
