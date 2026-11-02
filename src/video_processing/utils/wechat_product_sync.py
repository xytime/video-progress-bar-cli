"""单次只读目录同步的原生准入、独立预算、锁和尝试回执；不重试或恢复登录。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| catalog-sync-v1 | 2026-11-02 | Codex | 每日同步及过期任务刷新共用2次/24小时、6小时预算；部分结果不覆盖目录。 |
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from time import monotonic, time_ns

from config.settings import settings
from video_processing.core.maintenance import gate, current, MaintenanceDenied
from video_processing.core.wechat_session_lock import WeChatSessionLock, record_current_wechat_login_required, current_wechat_session
from video_processing.core.wechat_browser_context import create_wechat_context
from video_processing.core.wechat_page_contract import check_explicit_login_prompt, is_official_create_url
from video_processing.utils.wechat_product_config import load_policy, atomic_json
from video_processing.utils.wechat_product_catalog import catalog_digest
from video_processing.utils.wechat_product_pool import promote_live_catalog
from video_processing.utils.wechat_product_collector import collect_catalog, CatalogSyncError


def run_catalog_sync(policy_path=None):
    policy_path = Path(policy_path or settings.wechat_product_policy_path)
    output = settings.default_output_dir / 'wechat_catalog_sync' / str(time_ns())
    result = {'schema_version': 1, 'started_at': datetime.now(timezone.utc).isoformat(),
              'state': 'PARTIAL', 'live_verified': False, 'reason': None, 'completeness': 'partial'}
    started = monotonic()
    deadline = started + settings.wechat_product_catalog_sync_timeout_seconds
    def remaining():
        # 留出关闭浏览器和回执落盘时间；启动和翻页共用同一预算。
        value = int((deadline - monotonic() - 3) * 1000)
        if value <= 0:
            raise CatalogSyncError('CATALOG_SYNC_TIMEOUT')
        return value
    try:
        if not settings.wechat_operations_enabled:
            raise CatalogSyncError('CATALOG_OPERATIONS_DISABLED')
        expected_policy = load_policy(policy_path).digest
        expected_catalog = catalog_digest(policy_path.with_name('wechat_product_catalog.json'))
        parent = current()
        key = parent.key if parent else 'catalog-sync'
        with gate().admit('catalog-sync', key) as ticket:
            state_path = settings.default_output_dir / 'wechat_state.json'
            with WeChatSessionLock(state_path, timeout_seconds=0, purpose='商品同步', video='catalog-sync'):
                ticket.start()
                from playwright.sync_api import sync_playwright
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(headless=True, args=['--no-proxy-server'], timeout=remaining())
                    try:
                        context = create_wechat_context(browser, storage_state=state_path)
                        page = context.new_page()
                        page.set_default_timeout(remaining())
                        page.goto('https://channels.weixin.qq.com/platform/post/create',
                                  wait_until='domcontentloaded', timeout=remaining())
                        if check_explicit_login_prompt(page)[0]:
                            record_current_wechat_login_required()
                            raise CatalogSyncError('CATALOG_LOGIN_REQUIRED')
                        if not is_official_create_url(page.url):
                            raise CatalogSyncError('CATALOG_OFFICIAL_PAGE_REQUIRED')
                        data, proof = collect_catalog(page, timeout_seconds=remaining()/1000,
                                                      max_pages=settings.wechat_product_catalog_sync_max_pages)
                        remaining()
                        if current_wechat_session()._request_limited:
                            raise CatalogSyncError('CATALOG_PLATFORM_BACKOFF')
                        result.update(promote_live_catalog(data, proof, policy_path,
                            expected_catalog_digest=expected_catalog, expected_policy_digest=expected_policy))
                        result.update(state='COMPLETE', reason='CATALOG_SYNCED', completeness='complete')
                    finally:
                        browser.close()  # 不调用 storage_state，不写回 Cookie/登录态。
    except CatalogSyncError as exc:
        result.update(reason=exc.reason, partial=exc.partial)
    except MaintenanceDenied:
        result.update(reason='CATALOG_MAINTENANCE_DEFERRED')
    except Exception as exc:
        # 只记录异常类型，避免浏览器错误携带完整 URL 或凭证。
        result.update(reason='CATALOG_SYNC_' + type(exc).__name__)
    result.update(finished_at=datetime.now(timezone.utc).isoformat(), elapsed_seconds=round(monotonic()-started, 3))
    atomic_json(output / 'receipt.json', result)
    return result
