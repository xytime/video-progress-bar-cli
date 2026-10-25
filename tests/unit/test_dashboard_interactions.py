"""隔离浏览器验证后台选择、中文状态与请求竞态。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.3.0 | 2026-10-25 | Codex | 刷新复核弹窗测试数据并覆盖手动处理失败响应边界。 |
| 1.2.0 | 2026-09-23 | Codex | 真实浏览器验证待发布计数、占用原因和平台事实分离。 |
| 1.0.0 | 2026-09-08 | Codex | 覆盖刷新选择、具名删除确认、状态一致性和过期响应隔离 |
| 1.1.0 | 2026-09-08 | Codex | 共用显式 Chromium 快照夹具；依赖缺失明确失败 |
"""

import pytest

from tests.browser_fixtures import chromium, dashboard, _payload, _video


@pytest.mark.parametrize('slice_index', [0, 2])
@pytest.mark.parametrize('severity', ['high', 'critical'])
@pytest.mark.parametrize('viewport', [(1440, 1000), (390, 844)])
def test_bypass_modal_without_vibration_support(dashboard, slice_index, severity, viewport):
    """无震动 API 的浏览器也能复核；打开/取消弹窗不发起放行。"""
    from playwright.sync_api import expect
    page, state = dashboard
    page.evaluate("Object.defineProperty(navigator, 'vibrate', {value: undefined})")
    video = dict(_video('first', status='FAILED'),
                 error_msg='Censorship P0 Reject' if severity == 'critical' else 'Channel Policy Reject')
    video['censorship_state'] = {'can_review': True}
    parent = dict(_video('first', status='SEGMENTED'), slices_count=1)
    state['payload'] = _payload([parent if slice_index else video], total=1)
    page.route('**/api/videos/first/slices', lambda route: route.fulfill(
        json={'slices': [dict(video, slice_index=slice_index)]}))
    page.route(f'**/api/videos/first/censor-keywords?slice_index={slice_index}',
               lambda route: route.fulfill(json={
                   'success': True, 'severity': severity, 'layer_label': '测试审查',
                   'error_msg': '测试拦截原因', 'matched': [{'term': '测试词', 'layer': 'P0'}],
                   'keywords': [], 'has_subtitle': False,
               }))
    page.locator('.console-primary[data-section=production]').click()
    page.locator('#tab-error').click()
    page.evaluate('async () => { await loadVideos(); }')
    if slice_index:
        page.locator('#btn-toggle-first').click()
    page.set_viewport_size({'width': viewport[0], 'height': viewport[1]})
    row = page.locator('.child-row-first' if slice_index else '#row-first')
    row.get_by_role('button', name='🔓 复核放行', exact=True).click()
    modal = page.locator('#bypass-modal')
    expect(modal).to_be_visible(timeout=2000)
    expect(modal.locator('#bypass-banner')).to_contain_text('测试拦截原因')
    expect(modal.locator('#bypass-matched')).to_contain_text('测试词')
    confirm = modal.locator('#btn-confirm-bypass')
    if severity == 'critical':
        expect(confirm).to_be_disabled()
        modal.locator('#bypass-p0-review-checkbox').check()
        expect(confirm).to_be_disabled()
        modal.locator('#bypass-p0-resume-checkbox').check()
        expect(confirm).to_be_enabled()
    else:
        expect(confirm).to_be_enabled()
    modal.get_by_role('button', name='取消', exact=True).click()
    expect(modal).to_be_hidden()
    assert state['writes'] == []


@pytest.mark.parametrize('slice_index', [None, 2])
@pytest.mark.parametrize('can_review', [False, None], ids=['explicitly-denied', 'missing-state'])
def test_historical_censorship_text_alone_does_not_show_bypass(dashboard, slice_index, can_review):
    page, state = dashboard
    video = dict(_video('first', status='FAILED'), error_msg='Censorship P0 Reject')
    if can_review is not None:
        video['censorship_state'] = {'can_review': can_review}
    if slice_index is None:
        state['payload'] = _payload([video], total=1)
    else:
        parent = dict(_video('first', status='SEGMENTED'), slices_count=1)
        state['payload'] = _payload([parent], total=1)
        page.route('**/api/videos/first/slices', lambda route: route.fulfill(
            json={'slices': [dict(video, slice_index=slice_index)]}))
    page.locator('.console-primary[data-section=production]').click()
    page.locator('#tab-error').click()
    page.evaluate('async () => { await loadVideos(); }')
    if slice_index is not None:
        page.locator('#btn-toggle-first').click()
        row = page.locator(f'#row-first_s{slice_index}')
    else:
        row = page.locator('#row-first')
    from playwright.sync_api import expect
    expect(row).to_be_visible()
    assert row.get_by_role('button', name='🔓 复核放行', exact=True).count() == 0
    assert state['writes'] == []


@pytest.mark.parametrize('slice_index', [None, 2])
@pytest.mark.parametrize('status,payload,expected', [
    (503, {'detail': {'code': 'MAINTENANCE', 'message': '维护状态不允许领取新工作'}},
     '维护状态不允许领取新工作 [MAINTENANCE]'),
    (503, {'detail': {'code': 'UNKNOWN', 'message': '维护状态无法确认'}},
     '维护状态无法确认 [UNKNOWN]'),
    (503, {'detail': None}, '请求失败（HTTP 503）'),
    (503, {'detail': '服务暂不可用'}, '服务暂不可用'),
    (503, None, '请求失败（HTTP 503）'),
    (503, [], '请求失败（HTTP 503）'),
    (503, 'empty-body', '请求失败（HTTP 503）'),
    (200, {'success': False, 'error': '视频当前状态不是 PENDING'}, '视频当前状态不是 PENDING'),
    (200, {'success': 'true'}, '请求未确认，请刷新查看后再操作'),
    (200, [], '响应格式无效，请刷新查看后再操作'),
])
def test_process_failure_shows_reason_and_restores_button(dashboard, slice_index, status, payload, expected):
    from playwright.sync_api import expect
    page, state = dashboard
    requests = []
    suffix = f'/slices/{slice_index}' if slice_index is not None else ''

    def deny(route):
        requests.append(route.request.method)
        if payload is None:
            route.fulfill(status=status, content_type='text/html', body='<h1>Unavailable</h1>')
        elif payload == 'empty-body':
            route.fulfill(status=status, content_type='application/json', body='')
        else:
            route.fulfill(status=status, json=payload)

    page.route(f'**/api/videos/first{suffix}/process', deny)
    if slice_index is None:
        button = page.locator('#row-first button[onclick="processVideoNow(\'first\')"]')
    else:
        state['payload'] = _payload([dict(_video('first', status='SEGMENTED'), slices_count=1)], total=1)
        page.route('**/api/videos/first/slices', lambda route: route.fulfill(
            json={'slices': [dict(_video('first'), slice_index=slice_index)]}))
        page.evaluate('async () => { await loadVideos(); }')
        page.locator('#btn-toggle-first').click()
        button = page.locator('.child-row-first button[onclick^="processSliceNow"]')
    old_text = button.inner_text()
    button.click()
    expect(page.locator('.toast-item').last).to_have_text('❌ 启动失败: ' + expected)
    expect(button).to_be_enabled()
    expect(button).to_have_text(old_text)
    assert requests == ['POST']
    # 浏览器会为被刻意拒绝的 HTTP 请求记录资源错误，其他告警仍须通过夹具检查。
    expected_warning = f'Failed to load resource: the server responded with a status of {status} (Service Unavailable)'
    state['warnings'][:] = [message for message in state['warnings'] if message != expected_warning]


@pytest.mark.parametrize('payload,expected', [
    ({'detail': {'code': 'MAINTENANCE', 'message': '维护状态不允许领取新工作'}},
     '维护状态不允许领取新工作 [MAINTENANCE]'),
    (None, '请求失败（HTTP 503）'),
])
def test_delete_rejection_keeps_task_and_explains_failure(dashboard, payload, expected):
    from playwright.sync_api import expect
    page, state = dashboard
    requests = []

    def deny(route):
        requests.append((route.request.method, route.request.url))
        if payload is None:
            route.fulfill(status=503, content_type='text/html', body='<h1>Unavailable</h1>')
        else:
            route.fulfill(status=503, json=payload)

    page.route('**/api/videos/first?delete_files=false', deny)
    row = page.locator('#row-first')
    row.get_by_role('button', name='❌ 删除', exact=True).click()
    page.locator('#delete-confirm-code-input').fill(page.locator('#delete-safety-code').inner_text())
    confirm = page.locator('#btn-confirm-delete')
    confirm.click()
    expect(page.locator('.toast-item').last).to_have_text('❌ 删除失败: ' + expected)
    expect(confirm).to_be_enabled()
    expect(confirm).to_have_text('确认删除 (Delete)')
    expect(page.locator('#delete-modal')).to_be_visible()
    expect(row).to_be_visible()
    assert requests == [('DELETE', 'http://dashboard-test.invalid/api/videos/first?delete_files=false')]
    state['warnings'][:] = [message for message in state['warnings'] if message !=
        'Failed to load resource: the server responded with a status of 503 (Service Unavailable)']


def test_processing_row_has_stop_and_delete_controls(dashboard):
    page, state = dashboard
    state['payload'] = _payload([_video('preparing', status='PROCESSING')], total=1)
    page.evaluate('async () => { await loadVideos(); }')
    row = page.locator('#row-preparing')
    assert row.locator('.btn-stop').is_visible()
    assert row.get_by_role('button', name='❌ 删除', exact=True).is_visible()
    page.on('dialog', lambda dialog: dialog.accept())
    row.locator('.btn-stop').click()
    page.wait_for_function("document.querySelector('#row-preparing .btn-stop') !== null")
    assert state['writes'] == [{'method': 'POST', 'path': '/api/videos/preparing/stop', 'data': None}]


def test_processing_slice_has_stop_control_with_slice_identity(dashboard):
    page, state = dashboard
    parent = dict(_video('parent', status='SEGMENTED'), slices_count=1)
    state['payload'] = _payload([parent], total=1)
    child = dict(_video('parent', status='PROCESSING'), slice_index=2)
    page.route('**/api/videos/parent/slices', lambda route: route.fulfill(json={'slices': [child]}))
    page.evaluate('async () => { await loadVideos(); }')
    page.locator('#btn-toggle-parent').click()
    stop = page.locator('.child-row-parent .btn-stop')
    stop.wait_for()
    assert stop.get_attribute('onclick') == "stopVideo('parent', 2)"


@pytest.mark.parametrize('action', ['delete', 'stop'])
def test_missing_task_refreshes_stale_row(dashboard, action):
    page, state = dashboard
    state['payload'] = _payload([_video('gone', status='PROCESSING')], total=1)
    page.evaluate('async () => { await loadVideos(); }')
    endpoint = '**/api/videos/gone' + ('/stop' if action == 'stop' else '?delete_files=false')

    def missing(route):
        state['payload'] = _payload([], total=0)
        route.fulfill(json={'success': False, 'error': '视频不存在'})

    page.route(endpoint, missing)
    row = page.locator('#row-gone')
    if action == 'delete':
        row.get_by_role('button', name='❌ 删除', exact=True).click()
        code = page.locator('#delete-safety-code').inner_text()
        page.locator('#delete-confirm-code-input').fill(code)
        page.locator('#btn-confirm-delete').click()
        page.locator('#delete-modal').wait_for(state='hidden')
    else:
        page.on('dialog', lambda dialog: dialog.accept())
        row.locator('.btn-stop').click()
    row.wait_for(state='detached')
    assert page.locator('.toast-item').last.inner_text() == '该任务记录已不存在，已刷新列表'


def test_ready_tab_explains_wait_and_keeps_platform_result_separate(dashboard, tmp_path):
    page, state = dashboard
    video = _video("ready-video")
    video.update(display_status="READY_TO_PUBLISH", preparation_ready=1, score=90,
                 publication_ready_at="2026-09-23 00:00:00",
                 publication_last_attempt_at="2026-09-23 00:01:00",
                 publication_next_attempt_at="2026-09-23 00:20:00",
                 publication_wait_reason="同账号浏览器占用：other-video（发布，PID 123）",
                 publication_target="视频号")
    counts = dict.fromkeys(("waitlist", "queue", "active", "wechat_deferred", "local_accepted", "review", "completed", "error"), 0)
    state["payload"] = dict(_payload([video], total=1), total_pages=1, tab_counts=dict(counts, ready=1))
    page.locator(".console-primary[data-section=production]").click()
    page.locator("#tab-ready").click()
    row = page.locator("#row-ready-video")
    row.wait_for()
    assert page.locator("#tab-ready").inner_text() == "待发布(1)"
    assert row.locator(".status-cell .desktop-only-status > .badge").inner_text() == "待发布"
    details = row.locator(".publication-wait-detail").inner_text()
    for text in ("视频号", "other-video", "PID 123", "就绪：", "已等待", "最近尝试：", "下次重试："):
        assert text in details
    assert "已发布" not in row.locator(".plat-wechat").inner_text()
    assert state["queries"][-1]["tab"] == ["ready"]
    assert not state["writes"]
    page.screenshot(path=str(tmp_path / "ready-publication.png"), full_page=True)


def _select_first(page):
    page.locator("#batch-normal-view .btn-batch-del").click()
    page.locator('#row-first .row-cb').check()


def _assert_selection(page, ids):
    selected = page.evaluate("""() => ({
        ids: [..._selectedYids],
        checked: [...document.querySelectorAll('#activity-body .row-cb:checked')].map(el => el.dataset.yid),
        highlighted: [...document.querySelectorAll('#activity-body .row-selected')].map(el => el.id.slice(4)),
        count: document.getElementById('batch-selected-count').textContent,
    })""")
    assert selected == {"ids": ids, "checked": ids, "highlighted": ids, "count": str(len(ids))}


def _hold_video_requests(page):
    # 故意不遵守 AbortSignal，让测试同时证明“取消请求”和“拒绝旧响应回写”。
    page.evaluate("""() => {
        const originalFetch = window.fetch;
        window.pendingVideoRequests = [];
        window.fetch = (url, options = {}) => {
            if (new URL(url, location.href).pathname !== '/api/videos') return originalFetch(url, options);
            return new Promise(resolve => pendingVideoRequests.push({url, signal: options.signal,
                finish: (payload, ok = true) => resolve({ok, status: ok ? 200 : 500, json: async () => payload})}));
        };
    }""")


def test_refresh_keeps_visible_selection_and_prunes_missing_rows(dashboard):
    page, state = dashboard
    _select_first(page)
    page.evaluate("async () => { await loadVideos(); }")
    _assert_selection(page, ["first"])
    assert page.locator("#cb-header").evaluate("el => el.indeterminate")
    page.locator("#cb-header").check()
    _assert_selection(page, ["first", "second"])
    state["payload"] = _payload([_video("second")])
    page.evaluate("async () => { await loadVideos(); }")
    _assert_selection(page, ["second"])
    assert page.locator("#cb-header").is_checked()
    state["payload"] = _payload([], total=0)
    page.evaluate("async () => { await loadVideos(); }")
    _assert_selection(page, [])
    assert page.evaluate("Object.keys(_currentVideosMap)") == []
    assert not page.locator("#cb-header").is_checked()
    assert not state["writes"]


@pytest.mark.parametrize("action", [
    "() => changePage(1)",
    "() => { document.getElementById('video-filter-search').value = '新条件'; applyVideoFilters(); }",
    "() => { document.getElementById('video-filter-channel').value = '测试频道'; applyVideoFilters(); }",
    "() => { document.getElementById('video-filter-sort').value = 'score_desc'; applyVideoFilters(); }",
    "() => { document.getElementById('video-filter-score').value = '80_plus'; applyVideoFilters(); }",
    "() => { document.getElementById('video-filter-size').value = '50'; applyVideoFilters(); }",
    "() => switchTab('review')",
])
def test_query_changes_clear_selection_before_response(dashboard, action):
    page, state = dashboard
    _select_first(page)
    _hold_video_requests(page)
    page.evaluate(action)
    _assert_selection(page, [])
    assert page.evaluate("Object.keys(_currentVideosMap)") == []
    assert page.locator("#activity-body .row-cb").count() == 0
    page.evaluate("payload => pendingVideoRequests[0].finish(payload)", state["payload"])
    page.wait_for_function("!document.getElementById('activity-body').hasAttribute('aria-busy')")
    _assert_selection(page, [])


def test_delete_confirmation_names_only_current_checked_videos(dashboard):
    page, state = dashboard
    _select_first(page)
    page.evaluate("async () => { await loadVideos(); _selectedYids.add('invisible-old-id'); }")
    prompts = []

    def confirm(dialog):
        prompts.append(dialog.message)
        dialog.accept("delete")

    page.on("dialog", confirm)
    page.get_by_role("button", name="🗑 删除所选", exact=True).click()
    page.wait_for_function("document.getElementById('batch-selected-count').textContent === '0'")
    assert len(prompts) == 1
    assert "所选 1 条" in prompts[0]
    assert "测试视频 first [first]" in prompts[0]
    assert "second" not in prompts[0] and "invisible-old-id" not in prompts[0]
    assert state["writes"] == [{"method": "DELETE", "path": "/api/videos", "data": {"youtube_ids": ["first"]}}]


def test_delete_rechecks_selection_after_confirmation(dashboard):
    page, state = dashboard
    _select_first(page)
    page.evaluate("""async () => {
        window.prompt = () => { clearSelection(); return 'delete'; };
        await batchDelete();
    }""")
    assert not state["writes"]
    _assert_selection(page, [])


def test_normal_row_click_does_not_create_hidden_selection(dashboard):
    page, _ = dashboard
    page.locator("#row-first .time-cell").click()
    _assert_selection(page, [])


def test_chinese_statuses_match_table_platform_and_details(dashboard):
    page, state = dashboard
    labels = {
        "SUBMITTED_BOUND": "已提交，待确认发布",
        "SUBMITTED_UNBOUND": "本地已受理，待关联作品",
        "REJECTED": "审核未通过", "NOT_FOUND": "平台未找到作品", "CANCELED": "已取消",
        "QUEUED": "排队中", "UPLOADING": "上传中", "UNDER_REVIEW": "审核中",
        "PUBLISHED": "已发布", "COMPLETED": "处理完成", "LOGIN_REQUIRED": "需要登录",
        "NEW_UNMAPPED": "待核验", "__proto__": "待核验",
    }
    state["payload"] = _payload([_video(f"status-{i}", code) for i, code in enumerate(labels)])
    page.locator(".console-primary[data-section=publications]").click()
    page.locator("#row-status-0").wait_for()
    for i, (code, label) in enumerate(labels.items()):
        row = page.locator(f"#row-status-{i}")
        assert row.locator(".status-cell .desktop-only-status > .badge").inner_text() == label
        badge = row.locator(".plat-wechat")
        assert f"微信·{label}" in badge.inner_text()
        assert code in badge.get_attribute("title")
        badge.click()
        assert page.locator("#plat-modal-table-body tr").first.locator(".badge").inner_text() == label
        if code.startswith("SUBMITTED_"):
            assert "禁止重发" in page.locator("#plat-modal-table-body").inner_text()
            assert "公开发布证明" in badge.get_attribute("title")
            assert code not in page.locator("#plat-modal-table-body").inner_text()
        page.locator("#platform-detail-modal").get_by_role("button", name="关闭", exact=True).click()
    assert not state["writes"]


def test_platform_display_state_takes_precedence_and_unknown_is_not_unqueued(dashboard):
    page, state = dashboard
    video = _video("platform-overrides", "SUBMITTED_BOUND")
    video["platforms"] = {
        "wechat": {"state": "UNCERTAIN", "display_state": "SUBMITTED_BOUND"},
        "douyin": {},
    }
    state["payload"] = _payload([video])
    page.evaluate("async () => { await loadVideos(); }")
    row = page.locator("#row-platform-overrides")
    assert "已提交，待确认发布" in row.locator(".plat-wechat").inner_text()
    assert "待核验" in row.locator(".plat-douyin").inner_text()
    assert "未入队" in row.locator(".plat-kuaishou").inner_text()
    row.locator(".plat-douyin").click()
    assert page.locator("#plat-modal-table-body tr").last.locator(".badge").inner_text() == "待核验"


@pytest.mark.parametrize("older_ok", [True, False])
def test_old_tab_response_cannot_overwrite_new_tab(dashboard, older_ok):
    page, state = dashboard
    _hold_video_requests(page)
    page.locator(".console-primary[data-section=publications]").click()
    page.locator(".console-subnav a[href*=\"tab=waitlist\"]").click()
    assert page.evaluate("pendingVideoRequests[0].signal.aborted")
    page.evaluate("payload => pendingVideoRequests[1].finish(payload)", state["payload"])
    page.locator("#row-first").wait_for()
    page.evaluate("args => pendingVideoRequests[0].finish(...args)",
                  [_payload([_video("old-review", "SUBMITTED_BOUND")], total=47), older_ok])
    assert page.locator(".tab-btn.active").get_attribute("id") == "tab-waitlist"
    assert page.evaluate("Object.keys(_currentVideosMap)") == ["first", "second"]
    assert page.locator("#total-count-display").inner_text() == "2"
    assert page.locator("#activity-body .row-cb").count() == 2
    assert page.locator("#row-old-review").count() == 0


def test_hotwords_invalidates_pending_video_requests(dashboard):
    page, state = dashboard
    _hold_video_requests(page)
    page.locator(".console-primary[data-section=publications]").click()
    page.locator(".console-subnav a[href*=\"tab=hotwords\"]").click()
    assert page.evaluate("pendingVideoRequests[0].signal.aborted")
    page.evaluate("payload => pendingVideoRequests[0].finish(payload)", state["payload"])
    assert page.locator("#hotwords-panel").is_visible()
    assert page.evaluate("Object.keys(_currentVideosMap)") == []
    page.evaluate("async () => { await loadVideos(); }")
    assert page.evaluate("pendingVideoRequests.length") == 1


def test_same_query_latest_refresh_wins_and_query_failure_can_retry(dashboard):
    page, state = dashboard
    _hold_video_requests(page)
    page.evaluate("() => { loadVideos(); loadVideos(); }")
    page.evaluate("payload => pendingVideoRequests[1].finish(payload)", _payload([_video("newest")]))
    page.locator("#row-newest").wait_for()
    page.evaluate("payload => pendingVideoRequests[0].finish(payload)", state["payload"])
    assert page.evaluate("Object.keys(_currentVideosMap)") == ["newest"]
    page.locator(".console-primary[data-section=publications]").click()
    page.locator(".console-subnav a[href*=\"tab=waitlist\"]").click()
    page.evaluate("() => pendingVideoRequests[3].finish({detail: '测试失败'}, false)")
    page.get_by_text("列表加载失败，请重试刷新。", exact=True).wait_for()
    assert page.evaluate("Object.keys(_currentVideosMap)") == []
    assert len(state["warnings"]) == 1 and "测试失败" in state["warnings"].pop()
    page.evaluate("() => { loadVideos(); }")
    page.evaluate("payload => pendingVideoRequests[4].finish(payload)", state["payload"])
    page.locator("#row-first").wait_for()


def test_missing_channel_stays_filtered_until_user_clears_it(dashboard):
    page, state = dashboard
    page.locator("#video-filter-channel").select_option("测试频道")
    page.wait_for_function("!document.getElementById('activity-body').hasAttribute('aria-busy')")
    state["payload"] = {**_payload([], total=0), "filter_options": {"channels": []}}
    page.evaluate("async () => { await loadVideos(); }")
    assert page.locator("#video-filter-channel").input_value() == "测试频道"
    page.evaluate("async () => { await loadVideos(); }")
    assert state["queries"][-1]["channel"] == ["测试频道"]
    page.locator(".btn-filter-clear").click()
    assert page.locator("#video-filter-channel").input_value() == ""
    assert page.evaluate("filterState.channel") == ""
