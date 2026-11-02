"""单次只读目录同步的原生准入、独立预算、锁和尝试回执；不重试或恢复登录。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| catalog-sync-v3 | 2026-11-02 | Codex | 同一浏览器上下文采集前后读取官方首页稳定ID，失败不刷新目录。 |
| catalog-sync-v2 | 2026-11-02 | Codex | 与发布模式一致，成功及失败均记录脱敏 DOM 诊断和全程阶段计时。 |
| catalog-sync-v1 | 2026-11-02 | Codex | 每日同步及过期任务刷新共用2次/24小时、6小时预算；部分结果不覆盖目录。 |
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from time import monotonic, time_ns

from config.settings import settings
from video_processing.core.maintenance import gate, current, MaintenanceDenied
from video_processing.core.wechat_session_lock import WeChatSessionLock, record_current_wechat_login_required, current_wechat_session
from video_processing.core.wechat_browser_context import create_wechat_context, wechat_launch_options, WECHAT_LAUNCH_PROFILE
from video_processing.core.wechat_page_contract import check_explicit_login_prompt, is_official_create_url
from video_processing.utils.wechat_product_config import load_policy, atomic_json
from video_processing.utils.wechat_product_catalog import catalog_digest
from video_processing.utils.wechat_product_pool import promote_live_catalog
from video_processing.utils.wechat_product_collector import collect_catalog, CatalogSyncError
from video_processing.utils.wechat_catalog_account import visit_home_account
from video_processing.utils.wechat_catalog_diagnostics import public_path, timed_phase


def run_catalog_sync(policy_path=None):
    policy_path = Path(policy_path or settings.wechat_product_policy_path)
    output = settings.default_output_dir / 'wechat_catalog_sync' / str(time_ns())
    result = {'schema_version': 1, 'started_at': datetime.now(timezone.utc).isoformat(),
              'state': 'PARTIAL', 'live_verified': False, 'reason': None, 'completeness': 'partial',
              'receipt_path': str(output / 'receipt.json')}
    diagnostics = result['diagnostics'] = {'schema_version': 1, 'url_path': None, 'observed_items': 0,
        'timings_seconds': {}, 'browser': {'profile': WECHAT_LAUNCH_PROFILE,
        'headless': settings.wechat_headless, 'launched': False}}
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
        with timed_phase(diagnostics, 'local_validation'):
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
                    with timed_phase(diagnostics, 'browser_launch'):
                        options = wechat_launch_options(headless=settings.wechat_headless)
                        diagnostics['browser']['args'] = options['args']
                        browser = pw.chromium.launch(**options, timeout=remaining())
                        diagnostics['browser']['launched'] = True
                    try:
                        with timed_phase(diagnostics, 'context'):
                            context = create_wechat_context(browser, storage_state=state_path)
                            page = context.new_page()
                            page.set_default_timeout(remaining())
                        with timed_phase(diagnostics, 'navigation'):
                            try:
                                page.goto('https://channels.weixin.qq.com/platform/post/create',
                                          wait_until='domcontentloaded', timeout=remaining())
                            finally:
                                diagnostics['url_path'] = public_path(page.url)
                        if check_explicit_login_prompt(page)[0]:
                            record_current_wechat_login_required()
                            raise CatalogSyncError('CATALOG_LOGIN_REQUIRED')
                        if not is_official_create_url(page.url):
                            raise CatalogSyncError('CATALOG_OFFICIAL_PAGE_REQUIRED')
                        with timed_phase(diagnostics, 'account_before'):
                            account_before = visit_home_account(page, timeout_ms=min(5000, remaining()),
                                diagnostics=diagnostics.setdefault('account_before', {}))
                        # 首页与发布页共享本次独立浏览器上下文，不切换账号、不写回登录态。
                        page.goto('https://channels.weixin.qq.com/platform/post/create',
                                  wait_until='domcontentloaded', timeout=remaining())
                        if check_explicit_login_prompt(page)[0]:
                            record_current_wechat_login_required()
                            raise CatalogSyncError('CATALOG_LOGIN_REQUIRED')
                        if not is_official_create_url(page.url):
                            raise CatalogSyncError('CATALOG_OFFICIAL_PAGE_REQUIRED')
                        data, proof = collect_catalog(page, timeout_seconds=remaining()/1000,
                            max_pages=settings.wechat_product_catalog_sync_max_pages, diagnostics=diagnostics,
                            account_evidence=account_before)
                        with timed_phase(diagnostics, 'account_after'):
                            account_after = visit_home_account(page, timeout_ms=min(5000, remaining()),
                                diagnostics=diagnostics.setdefault('account_after', {}))
                        if not account_before or account_before != account_after or data['account_id'] != account_after['value']:
                            raise CatalogSyncError('CATALOG_ACCOUNT_UNVERIFIED')
                        proof['account_checks'] = {'before': account_before, 'after': account_after}
                        remaining()
                        if current_wechat_session()._request_limited:
                            raise CatalogSyncError('CATALOG_PLATFORM_BACKOFF')
                        with timed_phase(diagnostics, 'promotion'):
                            result.update(promote_live_catalog(data, proof, policy_path,
                                expected_catalog_digest=expected_catalog, expected_policy_digest=expected_policy))
                        result.update(state='COMPLETE', reason='CATALOG_SYNCED', completeness='complete')
                    finally:
                        with timed_phase(diagnostics, 'browser_close'):
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
